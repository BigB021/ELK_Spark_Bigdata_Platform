"""Collects authentic command outputs as evidence for the TP4 report.

For each command: <out>/preuves_texte/NN_name.txt (raw output) and
<out>/preuves_texte/html/NN_name.html (terminal-style page, turned into a PNG
by scripts/capture_screenshots.py).

usage: python scripts/collect_evidence.py <deliverable_dir>/6_captures
"""
import html
import json
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "evidence"
TXT, HTML = OUT / "preuves_texte", OUT / "preuves_texte" / "html"


def http(url, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode()


def sh(*cmd):
    res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (res.stdout + res.stderr).rstrip()


def pretty(text):
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except ValueError:
        return text


def ls_plugin_stats():
    s = json.loads(http("http://localhost:9600/_node/stats/pipelines/ed-visits"))["pipelines"]["ed-visits"]
    lines = [f"pipeline ed-visits : events in={s['events']['in']}  filtered={s['events']['filtered']}  "
             f"out={s['events']['out']}  duration_ms={s['events']['duration_in_millis']}", ""]
    lines.append(f"{'kind':8} {'plugin id':24} {'events in':>10} {'events out':>11}")
    for kind in ("inputs", "filters", "outputs"):
        for p in s["plugins"][kind]:
            ev = p.get("events", {})
            lines.append(f"{kind[:-1]:8} {p['id']:24} {str(ev.get('in', '-')):>10} {str(ev.get('out', '-')):>11}")
    return "\n".join(lines)


def logstash_startup():
    log = sh("docker", "compose", "logs", "--no-log-prefix", "logstash")
    keep = [l for l in log.splitlines() if any(k in l for k in (
        "Starting Logstash", "Pipeline started", "Pipelines running", "Elasticsearch version determined",
        "Starting pipeline", "Successfully started Logstash API"))]
    return "\n".join(l[:230] for l in keep[-12:])


def warning_sample():
    body = {"size": 1, "query": {"bool": {"filter": [{"term": {"dq.status": "warning"}},
                                                     {"term": {"dq.issues": "out_of_range:heart_rate_bpm=900"}}]}}}
    return pretty(http("http://localhost:9200/ed-visits-main/_search?filter_path=hits.total,hits.hits._source", body))


COMMANDS = [
    ("01_docker_compose_ps", "docker compose ps",
     lambda: sh("docker", "compose", "ps", "--format", "table {{.Name}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}")),
    ("02_cluster_nodes_health", "GET _cat/nodes?v  +  GET _cluster/health",
     lambda: http("http://localhost:9200/_cat/nodes?v&h=name,ip,node.role,master,heap.max,version")
     + "\n" + pretty(http("http://localhost:9200/_cluster/health"))),
    ("03_indices", "GET _cat/indices/ed-*?v",
     lambda: http("http://localhost:9200/_cat/indices/ed-*?v&s=index&h=health,status,index,pri,rep,docs.count,store.size")
     + "\n" + http("http://localhost:9200/_cat/shards/ed-visits-main,ed-rejects-main?v&h=index,shard,prirep,state,docs,node")),
    ("04_index_template", "GET _index_template/ed-visits (extrait)",
     lambda: json.dumps({k: v for k, v in json.loads(http("http://localhost:9200/_index_template/ed-visits"))
                         ["index_templates"][0]["index_template"].items() if k != "template"}, indent=2)
     + "\n\nsettings appliqués à ed-visits-main :\n"
     + pretty(http("http://localhost:9200/ed-visits-main/_settings?filter_path=*.settings.index.number_of_*,"
                   "*.settings.index.refresh_interval"))),
    ("05_logstash_startup", "docker compose logs logstash (démarrage des pipelines)", logstash_startup),
    ("06_logstash_pipeline_stats", "GET :9600/_node/stats/pipelines/ed-visits (compteurs par plugin)", ls_plugin_stats),
    ("07_validation_main", "python scripts/validate.py",
     lambda: sh(sys.executable, "scripts/validate.py").split("\n-> written")[0]),
    ("08_validation_test", "python scripts/validate.py --run test",
     lambda: sh(sys.executable, "scripts/validate.py", "--run", "test").split("\n## Most frequent")[0]),
    ("09_rejected_file", "logstash/output/rejected-main.ndjson (2 premières lignes)",
     lambda: "\n".join(pretty(l) for l in
                       (ROOT / "logstash/output/rejected-main.ndjson").read_text(encoding="utf-8").splitlines()[:2])),
    ("10_warning_document", "Document indexé avec anomalie corrigée (dq.status = warning)", warning_sample),
    ("11_mapping_check", "GET ed-visits-main/_mapping/field/... (types appliqués)",
     lambda: "\n".join(f"{k:36} {list(v['mapping'].values())[0].get('type')}" for k, v in sorted(
         json.loads(http("http://localhost:9200/ed-visits-main/_mapping/field/*"))["ed-visits-main"]["mappings"].items())
         if not k.startswith("_"))),
]

CSS = """body{margin:0;background:#1e1e2e;font:13px/1.45 Consolas,'Cascadia Mono',monospace;color:#d4d4d4}
.bar{background:#2d2d3f;padding:8px 14px;color:#a6adc8;font-family:Segoe UI,Arial;font-size:12px}
.bar b{color:#cdd6f4}pre{margin:0;padding:14px 18px;white-space:pre-wrap;word-break:break-word}
.p{color:#89b4fa}.c{color:#a6e3a1}"""


def main():
    TXT.mkdir(parents=True, exist_ok=True)
    HTML.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    for name, title, fn in COMMANDS:
        try:
            output = fn()
        except Exception as exc:  # keep going, record the failure honestly
            output = f"ERROR: {exc}"
        (TXT / f"{name}.txt").write_text(f"$ {title}\n{output}\n", encoding="utf-8")
        page = (f"<!doctype html><meta charset='utf-8'><style>{CSS}</style>"
                f"<div class='bar'><b>{html.escape(title)}</b> &nbsp;·&nbsp; ed-bigdata &nbsp;·&nbsp; {stamp}</div>"
                f"<pre><span class='p'>PS big_data&gt;</span> <span class='c'>{html.escape(title)}</span>\n"
                f"{html.escape(output)}</pre>")
        (HTML / f"{name}.html").write_text(page, encoding="utf-8")
        print("ok", name)


if __name__ == "__main__":
    main()
