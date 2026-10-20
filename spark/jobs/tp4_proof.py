"""TP4 - minimal proof: Spark reads the index produced by the Logstash pipeline.

Run:
  docker compose exec spark-master bash -c '/opt/spark/bin/spark-submit --packages $ES_SPARK_CONNECTOR /opt/spark/jobs/tp4_proof.py'
"""
from pyspark.sql import SparkSession

spark = SparkSession.builder.appName("TP4-proof").getOrCreate()
spark.sparkContext.setLogLevel("WARN")

# 1. Read the cleaned index written by Logstash
df = (spark.read.format("org.elasticsearch.spark.sql")
      .option("es.nodes", "es01,es02")
      .option("es.nodes.wan.only", "true")
      .option("es.read.field.as.array.include", "dq.issues,dq.anomaly_categories")
      .load("ed-visits-main"))

# print(f"Head {df.head(5)}")

# 2. Proof: number of documents and types coming from the explicit mapping
print("Documents in ed-visits-main:", df.count())
df.select("stay_id", "arrival_datetime", "triage_acuity_esi", "length_of_stay_hours", "admitted_flag").printSchema()

# 3. One simple aggregation: visits per quality status (valid / warning)
df.groupBy("dq.status").count().show()

spark.stop()
