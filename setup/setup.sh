#!/bin/sh
# -----------------------------------------------------------------------------
# One-shot bootstrap, run by the `setup` service before Logstash starts:
#   1. wait for a GREEN 2-node cluster
#   2. install the index templates (explicit mappings)
#   3. create the indices (so the applied mapping can be checked before ingestion)
#   4. create Kibana data views + set Kibana timezone to UTC
# Idempotent: safe to run on every `docker compose up`.
# -----------------------------------------------------------------------------
set -eu

ES="http://es01:9200"
KB="http://kibana:5601"

log() { echo "[setup] $*"; }

log "waiting for cluster health=green with 2 nodes..."
until curl -s "$ES/_cluster/health?wait_for_status=green&wait_for_nodes=2&timeout=30s" | grep -q '"status":"green"'; do
  sleep 5
done
curl -s "$ES/_cat/nodes?v&h=name,ip,node.role,master,heap.max"

for tpl in ed-visits ed-rejects; do
  log "PUT _index_template/$tpl"
  curl -sf -X PUT "$ES/_index_template/$tpl" \
       -H 'Content-Type: application/json' \
       --data-binary "@/templates/$tpl.template.json"
  echo
done

for idx in ed-visits-main ed-visits-test ed-rejects-main ed-rejects-test ed-rejects-dlq; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -I "$ES/$idx")
  if [ "$code" = "404" ]; then
    log "creating index $idx"
    curl -sf -X PUT "$ES/$idx"; echo
  else
    log "index $idx already exists"
  fi
done

log "waiting for Kibana..."
until curl -s "$KB/api/status" | grep -q '"level":"available"'; do sleep 5; done

create_view() { # id title name [timeField] (no time field for result tables)
  log "data view $1 ($2)"
  time_field=""
  [ -n "${4:-}" ] && time_field=",\"timeFieldName\":\"$4\""
  curl -sf -X POST "$KB/api/data_views/data_view" \
       -H 'kbn-xsrf: setup' -H 'Content-Type: application/json' \
       -d "{\"override\":true,\"data_view\":{\"id\":\"$1\",\"title\":\"$2\",\"name\":\"$3\",\"allowNoIndex\":true$time_field}}" >/dev/null
}
create_view ed-visits    "ed-visits-*"    "ED visits (valid + warning)" "@timestamp"
create_view ed-rejects   "ed-rejects-*"   "ED rejected events"          "@timestamp"
# Spark result tables (written by spark/jobs/*.py)
create_view ed-analytics "ed-analytics-*" "ED Spark analytics"

curl -sf -X POST "$KB/api/data_views/default" -H 'kbn-xsrf: setup' -H 'Content-Type: application/json' \
     -d '{"data_view_id":"ed-visits","force":true}' >/dev/null
curl -sf -X POST "$KB/api/kibana/settings" -H 'kbn-xsrf: setup' -H 'Content-Type: application/json' \
     -d '{"changes":{"dateFormat:tz":"UTC"}}' >/dev/null
# Default time range: last 2 years covers every arrival date (2025-01 -> 2026-06) and the rejects (ingestion time)
curl -sf -X POST "$KB/api/kibana/settings" -H 'kbn-xsrf: setup' -H 'Content-Type: application/json' \
     -d '{"changes":{"timepicker:timeDefaults":"{\"from\":\"now-2y\",\"to\":\"now\"}"}}' >/dev/null

log "importing Kibana dashboards (Lens visualizations)"
curl -sf -X POST "$KB/api/saved_objects/_import?overwrite=true" -H 'kbn-xsrf: setup' \
     --form file=@/kibana/ed-dashboards.ndjson | grep -o '"successCount":[0-9]*'

log "done"
