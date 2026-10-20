"""TP3 - first Spark job: Données -> Spark -> Résultat.

Reads the raw ED visits CSV, keeps plausible rows and computes three
aggregations. Results are printed and written as CSV in /opt/spark/output/tp3.
Set TP3_WRITE_ES=true to also index the three result tables in Elasticsearch.

Run:
  docker compose exec spark-master /opt/spark/bin/spark-submit /opt/spark/jobs/tp3_first_job.py
  (add --packages $ES_SPARK_CONNECTOR and TP3_WRITE_ES=true to write result indices)
"""
import csv
import os

from pyspark.sql import SparkSession, functions as F

INPUT = os.environ.get("TP3_INPUT", "/data/ed_synthetic_visits.csv")
OUT_DIR = os.environ.get("TP3_OUTPUT", "/opt/spark/output/tp3")
WRITE_ES = os.environ.get("TP3_WRITE_ES", "false").lower() == "true"
ES_OPTIONS = {"es.nodes": "es01,es02", "es.port": "9200", "es.nodes.wan.only": "true"}


def to_es(df, index):
    """Index a result table when the Elasticsearch connector was requested."""
    df.write.format("org.elasticsearch.spark.sql").options(**ES_OPTIONS).mode("overwrite").save(index)
    print(f"    -> Elasticsearch index {index}")


def save(df, name, index):
    """Results are small: collect on the driver and write a single CSV file (+ ES index)."""
    if WRITE_ES:
        to_es(df, index)
    rows = df.collect()
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{name}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(df.columns)
        writer.writerows([list(r) for r in rows])
    print(f"--- {name} ({len(rows)} rows) -> {path}")
    df.show(truncate=False)


def main():
    spark = SparkSession.builder.appName("TP3-first-job-ED-visits").getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    print(f"Spark {spark.version} | Java {spark.sparkContext._jvm.System.getProperty('java.version')}")

    raw = spark.read.option("header", True).csv(INPUT)  # everything as string first
    df = (
        raw.withColumn("los", F.col("length_of_stay_hours").cast("double"))
        .withColumn("esi", F.col("triage_acuity_esi").cast("int"))
        .withColumn("admitted", F.col("disposition") == F.lit("ADMITTED"))
    )
    clean = df.filter(F.col("esi").between(1, 5) & F.col("los").between(0, 72) & F.col("disposition").isNotNull())
    print(f"rows read: {raw.count()} | plausible rows kept: {clean.count()}")

    save(clean.groupBy("disposition").count().orderBy(F.desc("count")), "visits_by_disposition", "ed-analytics-tp3-disposition")

    save(
        clean.groupBy("esi")
        .agg(
            F.count("*").alias("visits"),
            F.round(F.avg("los"), 2).alias("avg_los_hours"),
            F.round(F.percentile_approx("los", 0.5), 2).alias("median_los_hours"),
        )
        .orderBy("esi"),
        "los_by_triage_acuity", "ed-analytics-tp3-los-esi",
    )

    save(
        clean.groupBy("arrival_transport")
        .agg(
            F.count("*").alias("visits"),
            F.round(100 * F.avg(F.col("admitted").cast("int")), 1).alias("admission_rate_pct"),
        )
        .orderBy(F.desc("visits")),
        "admission_rate_by_transport", "ed-analytics-tp3-transport",
    )

    spark.stop()


if __name__ == "__main__":
    main()
