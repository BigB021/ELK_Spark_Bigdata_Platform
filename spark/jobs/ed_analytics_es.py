"""Spark analyses on the cleaned index ed-visits-main (prepared in TP4, docs/spark_analyses.md).

  A1  statistics per triage level (ESI): volume, LOS distribution, admission rate
  A2  temporal analysis: arrivals per weekday x hour, monthly trend
  A3  business analysis: diagnoses with the highest admission / long-stay rates

Results: CSV in /opt/spark/output/analytics/ AND Elasticsearch indices ed-analytics-a*
(data view "ED Spark analytics" in Kibana).

Run (the ES connector is downloaded on first use):
  docker compose exec spark-master bash -c '/opt/spark/bin/spark-submit --packages $ES_SPARK_CONNECTOR /opt/spark/jobs/ed_analytics_es.py'
"""
import csv
import os

from pyspark.sql import SparkSession, functions as F

INDEX = os.environ.get("ED_INDEX", "ed-visits-main")
OUT_DIR = "/opt/spark/output/analytics"
ES_OPTIONS = {"es.nodes": "es01,es02", "es.port": "9200", "es.nodes.wan.only": "true"}


def to_es(df, index):
    """Writes a result table to its own index (replaced on every run)."""
    df.write.format("org.elasticsearch.spark.sql").options(**ES_OPTIONS).mode("overwrite").save(index)
    print(f"    -> Elasticsearch index {index}")


def save(df, name, index, es_df=None):
    """CSV file for the report + Elasticsearch index for Kibana (es_df: alternative shape for ES)."""
    to_es(es_df if es_df is not None else df, index)
    rows = df.collect()
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{name}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(df.columns)
        writer.writerows([list(r) for r in rows])
    print(f"--- {name} ({len(rows)} rows) -> {path}")
    df.show(30, truncate=False)


def main():
    spark = SparkSession.builder.appName("ED-analytics-from-Elasticsearch").getOrCreate()
    spark.sparkContext.setLogLevel("WARN")

    visits = (
        spark.read.format("org.elasticsearch.spark.sql")
        .options(**ES_OPTIONS)
        .option("es.read.field.as.array.include", "dq.issues,dq.anomaly_categories")
        .load(INDEX)
        .withColumn("admitted", F.col("admitted_flag").cast("int"))
        .withColumn("long_stay", (F.col("length_of_stay_hours") > 6).cast("int"))
    )
    print(f"documents read from {INDEX}: {visits.count()}")

    # A1 - statistics per triage level
    save(
        visits.filter(F.col("triage_acuity_esi").isNotNull())
        .groupBy("triage_acuity_esi")
        .agg(
            F.count("*").alias("visits"),
            F.round(F.avg("length_of_stay_hours"), 2).alias("avg_los_h"),
            F.round(F.percentile_approx("length_of_stay_hours", 0.5), 2).alias("median_los_h"),
            F.round(F.percentile_approx("length_of_stay_hours", 0.9), 2).alias("p90_los_h"),
            F.round(100 * F.avg("admitted"), 1).alias("admission_rate_pct"),
            F.round(F.avg("shock_index"), 2).alias("avg_shock_index"),
        )
        .orderBy("triage_acuity_esi"),
        "a1_triage_statistics", "ed-analytics-a1-triage",
    )

    # A2 - temporal analysis
    # CSV: 7 x 24 grid ; ES: one document per (weekday, hour), easier to chart in Kibana
    save(
        visits.groupBy("arrival_dow").pivot("arrival_hour", list(range(24))).count()
        .na.fill(0).orderBy("arrival_dow"),
        "a2_arrivals_weekday_x_hour", "ed-analytics-a2-weekday-hour",
        es_df=visits.groupBy("arrival_dow", "arrival_hour").agg(F.count("*").alias("visits")),
    )
    save(
        visits.groupBy("arrival_month")
        .agg(
            F.count("*").alias("visits"),
            F.round(F.avg("length_of_stay_hours"), 2).alias("avg_los_h"),
            F.round(100 * F.avg("admitted"), 1).alias("admission_rate_pct"),
        )
        .orderBy("arrival_month"),
        "a2_monthly_trend", "ed-analytics-a2-monthly",
    )

    # A3 - business analysis: high-risk diagnoses (min 50 visits)
    save(
        visits.filter(F.col("primary_diagnosis_icd10").isNotNull())
        .groupBy("primary_diagnosis_icd10", F.col("primary_diagnosis_title"))
        .agg(
            F.count("*").alias("visits"),
            F.round(F.avg("triage_acuity_esi"), 2).alias("avg_esi"),
            F.round(100 * F.avg("admitted"), 1).alias("admission_rate_pct"),
            F.round(100 * F.avg("long_stay"), 1).alias("long_stay_rate_pct"),
        )
        .filter(F.col("visits") >= 50)
        .orderBy(F.desc("admission_rate_pct"), F.desc("visits")),
        "a3_high_risk_diagnoses", "ed-analytics-a3-diagnoses",
    )

    spark.stop()


if __name__ == "__main__":
    main()
