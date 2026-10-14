"""Generates kibana/ed-dashboards.ndjson (Lens visualizations + 2 dashboards).

The file is imported by setup/setup.sh (POST /api/saved_objects/_import?overwrite=true).
Re-run this script only to change the visualizations:  python scripts/build_kibana_objects.py
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "kibana" / "ed-dashboards.ndjson"
MAIN_ONLY = 'ingest.run_id : "main"'


# ----------------------------------------------------------------- columns --
def count(label="Passages"):
    return {"label": label, "dataType": "number", "operationType": "count", "sourceField": "___records___",
            "isBucketed": False, "scale": "ratio", "params": {"emptyAsNull": True}, "customLabel": True}


def avg(field, label, decimals=1):
    return {"label": label, "dataType": "number", "operationType": "average", "sourceField": field,
            "isBucketed": False, "scale": "ratio", "customLabel": True,
            "params": {"emptyAsNull": True, "format": {"id": "number", "params": {"decimals": decimals}}}}


def terms(field, label, size, order_col=None, numeric=False, other=False):
    order = {"type": "column", "columnId": order_col} if order_col else {"type": "alphabetical", "fallback": False}
    return {"label": label, "dataType": "number" if numeric else "string", "operationType": "terms",
            "sourceField": field, "isBucketed": True, "scale": "ordinal", "customLabel": True,
            "params": {"size": size, "orderBy": order, "orderDirection": "desc" if order_col else "asc",
                       "otherBucket": other, "missingBucket": False, "parentFormat": {"id": "terms"},
                       "include": [], "exclude": [], "includeIsRegex": False, "excludeIsRegex": False}}


def date_hist(label="Semaine d'arrivée", interval="w"):
    return {"label": label, "dataType": "date", "operationType": "date_histogram", "sourceField": "@timestamp",
            "isBucketed": True, "scale": "interval", "customLabel": True,
            "params": {"interval": interval, "includeEmptyRows": True, "dropPartials": False}}


# ------------------------------------------------------------------- lens --
def lens(obj_id, title, vis_type, columns, visualization, data_view="ed-visits", query=MAIN_ONLY, description=""):
    return {
        "id": obj_id, "type": "lens", "typeMigrationVersion": "8.9.0", "coreMigrationVersion": "8.8.0",
        "attributes": {
            "title": title, "description": description, "visualizationType": vis_type,
            "state": {
                "datasourceStates": {"formBased": {"layers": {"layer1": {
                    "columns": columns, "columnOrder": list(columns), "incompleteColumns": {}}}}},
                "visualization": visualization,
                "query": {"query": query, "language": "kuery"},
                "filters": [], "internalReferences": [], "adHocDataViews": {},
            },
        },
        "references": [{"type": "index-pattern", "id": data_view, "name": "indexpattern-datasource-layer-layer1"}],
    }


def xy(series, x, y, split=None, horizontal=False, legend=True, y_title=None, x_title=None):
    layer = {"layerId": "layer1", "layerType": "data", "seriesType": series, "xAccessor": x, "accessors": [y]}
    if split:
        layer["splitAccessor"] = split
    vis = {"preferredSeriesType": series, "layers": [layer],
           "legend": {"isVisible": legend, "position": "right"}, "valueLabels": "hide",
           "fittingFunction": "None", "axisTitlesVisibilitySettings": {"x": True, "yLeft": True, "yRight": True}}
    if y_title:
        vis["yTitle"] = y_title
    if x_title:
        vis["xTitle"] = x_title
    return vis


objects = []

# 1 - volume per week, split by triage level
objects.append(lens(
    "ed-lens-weekly-esi", "Passages par semaine et niveau de triage (ESI)", "lnsXY",
    {"x": date_hist(), "esi": terms("triage_acuity_esi", "ESI", 5, numeric=True), "n": count()},
    xy("bar_stacked", "x", "n", split="esi", y_title="Passages")))

# 2 - disposition donut
objects.append(lens(
    "ed-lens-disposition", "Orientation de sortie (disposition)", "lnsPie",
    {"d": terms("disposition", "Disposition", 10, order_col="n"), "n": count()},
    {"shape": "donut", "layers": [{"layerId": "layer1", "layerType": "data", "primaryGroups": ["d"],
                                   "metrics": ["n"], "numberDisplay": "percent", "categoryDisplay": "default",
                                   "legendDisplay": "show", "nestedLegend": False, "legendPosition": "right"}]}))

# 3 - average LOS and admission per ESI
objects.append(lens(
    "ed-lens-los-esi", "Durée de séjour moyenne (h) par ESI", "lnsXY",
    {"esi": terms("triage_acuity_esi", "ESI", 5, numeric=True),
     "los": avg("length_of_stay_hours", "LOS moyenne (h)", 2)},
    xy("bar", "esi", "los", legend=False, y_title="LOS moyenne (h)", x_title="Niveau ESI")))

# 4 - heatmap weekday x hour
objects.append(lens(
    "ed-lens-heatmap", "Affluence : jour de la semaine x heure d'arrivée", "lnsHeatmap",
    {"h": terms("arrival_hour", "Heure d'arrivée", 24, numeric=True),
     "d": terms("arrival_dow", "Jour", 7), "n": count()},
    {"shape": "heatmap", "layerId": "layer1", "layerType": "data", "xAccessor": "h", "yAccessor": "d",
     "valueAccessor": "n",
     "legend": {"isVisible": True, "position": "right", "type": "heatmap_legend"},
     "gridConfig": {"type": "heatmap_grid", "isCellLabelVisible": False, "isYAxisLabelVisible": True,
                    "isXAxisLabelVisible": True, "isYAxisTitleVisible": True, "isXAxisTitleVisible": True}}))

# 5 - top diagnoses table
objects.append(lens(
    "ed-lens-top-diagnoses", "Top 10 des diagnostics", "lnsDatatable",
    {"dx": terms("primary_diagnosis_title.keyword", "Diagnostic", 10, order_col="n"), "n": count(),
     "los": avg("length_of_stay_hours", "LOS moyenne (h)", 2), "esi": avg("triage_acuity_esi", "ESI moyen", 2)},
    {"layerId": "layer1", "layerType": "data",
     "columns": [{"columnId": "dx"}, {"columnId": "n"}, {"columnId": "los"}, {"columnId": "esi"}]}))

# 6 - data quality: anomaly categories on indexed records
objects.append(lens(
    "ed-lens-quality", "Qualité : anomalies des enregistrements indexés", "lnsXY",
    {"cat": terms("dq.anomaly_categories", "Catégorie d'anomalie", 10, order_col="n"), "n": count("Enregistrements")},
    xy("bar_horizontal", "cat", "n", legend=False, y_title="Enregistrements")))

# 7 - KPI: indexed visits / status
objects.append(lens(
    "ed-lens-status", "Statut qualité (valid / warning)", "lnsPie",
    {"s": terms("dq.status", "Statut", 3, order_col="n"), "n": count("Enregistrements")},
    {"shape": "pie", "layers": [{"layerId": "layer1", "layerType": "data", "primaryGroups": ["s"],
                                 "metrics": ["n"], "numberDisplay": "value", "categoryDisplay": "default",
                                 "legendDisplay": "show", "nestedLegend": False}]}))

# 8 - rejects by reason
objects.append(lens(
    "ed-lens-reject-reasons", "Événements rejetés par catégorie", "lnsXY",
    {"cat": terms("dq.anomaly_categories", "Catégorie", 10, order_col="n"), "n": count("Rejets")},
    xy("bar_horizontal", "cat", "n", legend=False, y_title="Événements rejetés"),
    data_view="ed-rejects", query='ingest.run_id : "main"'))

# 9 - rejects table
objects.append(lens(
    "ed-lens-reject-table", "Motifs de rejet détaillés", "lnsDatatable",
    {"r": terms("reject_reasons", "Motif de rejet", 20, order_col="n"), "n": count("Événements")},
    {"layerId": "layer1", "layerType": "data", "columns": [{"columnId": "r"}, {"columnId": "n"}]},
    data_view="ed-rejects", query='ingest.run_id : "main"'))


# -------------------------------------------------------------- dashboards --
def dashboard(obj_id, title, description, panels):
    panels_json, refs = [], []
    for i, (lens_id, x, y, w, h) in enumerate(panels):
        pid = f"p{i + 1}"
        panels_json.append({"type": "lens", "gridData": {"x": x, "y": y, "w": w, "h": h, "i": pid},
                            "panelIndex": pid, "embeddableConfig": {"enhancements": {}},
                            "panelRefName": f"panel_{pid}"})
        refs.append({"name": f"{pid}:panel_{pid}", "type": "lens", "id": lens_id})
    return {
        "id": obj_id, "type": "dashboard", "typeMigrationVersion": "8.9.0", "coreMigrationVersion": "8.8.0",
        "attributes": {
            "title": title, "description": description, "timeRestore": True,
            "timeFrom": "now-2y", "timeTo": "now", "refreshInterval": {"pause": True, "value": 0},
            "panelsJSON": json.dumps(panels_json),
            "optionsJSON": json.dumps({"useMargins": True, "syncColors": True, "syncCursor": True,
                                       "syncTooltips": False, "hidePanelTitles": False}),
            "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps(
                {"query": {"query": "", "language": "kuery"}, "filter": []})},
        },
        "references": refs,
    }


objects.append(dashboard(
    "ed-dashboard-activity", "ED - Supervision de l'activité des urgences",
    "Volumes, gravité, durées de séjour, orientation et diagnostics (index ed-visits-main)",
    [("ed-lens-weekly-esi", 0, 0, 48, 13),
     ("ed-lens-disposition", 0, 13, 20, 14), ("ed-lens-los-esi", 20, 13, 28, 14),
     ("ed-lens-heatmap", 0, 27, 26, 15), ("ed-lens-top-diagnoses", 26, 27, 22, 15)]))

objects.append(dashboard(
    "ed-dashboard-quality", "ED - Qualité des données et rejets",
    "Statut qualité des enregistrements indexés et événements rejetés par le pipeline Logstash",
    [("ed-lens-status", 0, 0, 16, 14), ("ed-lens-quality", 16, 0, 32, 14),
     ("ed-lens-reject-reasons", 0, 14, 22, 15), ("ed-lens-reject-table", 22, 14, 26, 15)]))

OUT.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in objects) + "\n", encoding="utf-8")
print(f"{len(objects)} saved objects -> {OUT}")
