"""Status of every service of the platform (TP3 demo: installé -> configuré -> démarré -> fonctionnel).

Checks each container through Docker, then each service through its own API.
Standard library only:  python scripts/status.py
"""
import json
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK, KO, WARN = "OK ", "KO ", "-- "


def get(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def containers():
    out = subprocess.run(["docker", "compose", "ps", "-a", "--format", "json"], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8").stdout
    rows = [json.loads(l) for l in out.splitlines() if l.strip().startswith("{")]
    if not rows and out.strip().startswith("["):  # older compose versions print a JSON array
        rows = json.loads(out)
    return {r["Service"]: r for r in rows}


def line(flag, name, detail):
    print(f"  [{flag}] {name:<14} {detail}")


def main():
    print("\n=== Conteneurs (docker compose) ===")
    ps = containers()
    for svc in ["es01", "es02", "kibana", "setup", "logstash", "spark-master", "spark-worker"]:
        c = ps.get(svc)
        if not c:
            line(KO, svc, "absent (docker compose up -d)")
            continue
        state, health = c.get("State", ""), c.get("Health", "")
        if svc == "setup":
            good = state == "exited" and "(0)" in c.get("Status", "")   # one-shot job: must have exited with code 0
        else:
            good = state == "running" and health in ("healthy", "")
        line(OK if good else KO, svc, f"{c.get('Status', state)}  [{c.get('Image', '')}]")

    print("\n=== Elasticsearch (ELK-01 / ELK-02) ===")
    health = get("http://localhost:9200/_cluster/health")
    if health:
        line(OK if health["status"] == "green" else WARN, "cluster",
             f"{health['cluster_name']}  status={health['status']}  nodes={health['number_of_nodes']}  "
             f"shards={health['active_shards']}/{health['active_shards'] + health['unassigned_shards']}")
        nodes = get("http://localhost:9200/_nodes/stats/jvm,os") or {"nodes": {}}
        master = (get("http://localhost:9200/_cluster/state/master_node") or {}).get("master_node")
        for nid, n in sorted(nodes["nodes"].items(), key=lambda kv: kv[1]["name"]):
            heap = n["jvm"]["mem"]["heap_used_percent"]
            role = "master" if nid == master else "      "
            line(OK, n["name"], f"{n['ip'].split(':')[0]:<13} {role} heap={heap}%  version="
                 f"{(get('http://localhost:9200') or {}).get('version', {}).get('number', '?')}")
        for idx in get("http://localhost:9200/_cat/indices/ed-*?format=json&s=index") or []:
            line(OK if idx["health"] == "green" else WARN, "index",
                 f"{idx['index']:<30} {idx['health']:<6} docs={idx['docs.count']}")
    else:
        line(KO, "cluster", "pas de réponse sur http://localhost:9200")

    print("\n=== Kibana (ELK-01) ===")
    kb = get("http://localhost:5601/api/status", timeout=10)
    if kb:
        level = kb["status"]["overall"]["level"]
        line(OK if level == "available" else WARN, "kibana",
             f"version={kb['version']['number']}  overall={level}  -> http://localhost:5601")
    else:
        line(KO, "kibana", "pas de réponse sur http://localhost:5601")

    print("\n=== Logstash (LOGSTASH-01) ===")
    ls = get("http://localhost:9600/_node/stats/pipelines")
    if ls:
        line(OK, "logstash", f"version={ls['version']}  status={ls.get('status', '?')}")
        for pid, p in ls["pipelines"].items():
            ev = p["events"]
            line(OK, f"pipeline", f"{pid:<10} in={ev['in']}  filtered={ev['filtered']}  out={ev['out']}")
    else:
        line(KO, "logstash", "pas de réponse sur http://localhost:9600")

    print("\n=== Spark (SPARK-01) ===")
    sm = get("http://localhost:8080/json/")
    if sm:
        alive = [w for w in sm.get("workers", []) if w.get("state") == "ALIVE"]
        line(OK if sm.get("status") == "ALIVE" and alive else WARN, "master",
             f"{sm.get('url')}  status={sm.get('status')}  workers alive={len(alive)}  "
             f"cores={sm.get('cores')}  memory={sm.get('memory')} MB")
        for w in alive:
            line(OK, "worker", f"{w.get('host')}  cores={w.get('cores')}  memory={w.get('memory')} MB")
        line(OK, "applications", f"running={len(sm.get('activeapps', []))}  "
             f"completed={len(sm.get('completedapps', []))}")
    else:
        line(KO, "master", "pas de réponse sur http://localhost:8080")
    print()


if __name__ == "__main__":
    main()
