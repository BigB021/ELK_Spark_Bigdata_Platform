"""Check the simple, offline requirements shared by TP3 and TP4.

This check does not need Docker or Elasticsearch. It verifies the delivered
CSV, anomaly fixture, and explicit mapping before running the full platform.
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "datasets" / "ed_synthetic_visits.csv"
FIXTURE = ROOT / "tests" / "fixtures" / "ed_anomaly_samples.csv"
MAPPING = ROOT / "elasticsearch" / "templates" / "ed-visits.template.json"


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def main():
    rows = read_csv(DATASET)
    fixture = read_csv(FIXTURE)
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    columns = set(rows[0]) if rows else set()
    properties = mapping["template"]["mappings"]["properties"]

    checks = [
        (len(rows) >= 5000, f"dataset rows: {len(rows)} (need at least 5000)"),
        (len({r["stay_id"] for r in rows if r.get("stay_id")}) ==
         sum(bool(r.get("stay_id")) for r in rows),
         "non-empty stay_id values are unique (missing IDs are intentional test anomalies)"),
        (len(columns) >= 12, f"dataset columns: {len(columns)} (need at least 12)"),
        (len(properties) >= 12, f"explicit mapping fields: {len(properties)}"),
        (mapping["template"]["mappings"].get("dynamic") == "strict",
         "mapping uses dynamic: strict"),
        (len({r.get("arrival_transport") for r in rows}) >= 5,
         "dataset has at least five transport categories"),
        (len({r.get("disposition") for r in rows}) >= 5,
         "dataset has at least five disposition categories"),
        (len(fixture) >= 20, f"anomaly fixture rows: {len(fixture)}"),
        (any(not r.get("stay_id") for r in fixture), "fixture includes a missing field"),
        (any("/" in r.get("arrival_datetime", "") or "30" in r.get("arrival_datetime", "")
             for r in fixture), "fixture includes an invalid or alternate date"),
        (any(r.get("temperature_f") == "abc" or r.get("heart_rate_bpm") == "900"
             for r in fixture), "fixture includes an invalid numeric value"),
        (any(r.get("arrival_transport") == "TELEPORT" for r in fixture),
         "fixture includes an unknown category"),
    ]

    failed = [message for passed, message in checks if not passed]
    for passed, message in checks:
        print(f"[{'OK' if passed else 'FAIL'}] {message}")
    if failed:
        print(f"\n{len(failed)} assignment check(s) failed.", file=sys.stderr)
        return 1
    print(f"\nAll {len(checks)} offline assignment checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
