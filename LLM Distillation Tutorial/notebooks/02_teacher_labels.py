# Databricks notebook source
# MAGIC %md
# MAGIC # Step 2 · The teacher labels the tickets
# MAGIC The teacher is **OpenAI's gpt-oss-120b**, an open-weight mixture-of-experts model (117B parameters in total,
# MAGIC 5.1B active per token), served by Databricks as a pay-per-token Foundation Model API.
# MAGIC
# MAGIC One SQL statement sends every training ticket to it with `ai_query`. Its answers become the training data for the
# MAGIC small student model. We also label the 100 test tickets, so we can compare teacher and student later.
# MAGIC
# MAGIC Why an open teacher? The terms of frontier model providers forbid training competing models on their outputs.
# MAGIC gpt-oss is Apache 2.0.
# MAGIC
# MAGIC Compute: serverless (CPU). Time: about 3 minutes.

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

PREFIX = ticket_prompt("")          # the instructions; the ticket text is appended to it
print(PREFIX)

LABEL_SCHEMA = json.dumps({"type": "json_schema", "json_schema": {"name": "route", "strict": True, "schema": {
    "type": "object", "required": ["queue", "reply"],
    "properties": {"queue": {"type": "string", "enum": list(QUEUES)}, "reply": {"type": "string"}}}}})
sql_str = lambda s: "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"

# COMMAND ----------

# MAGIC %md
# MAGIC ### Label the 400 training tickets

# COMMAND ----------

import time
t0 = time.time()
spark.sql(f"""
CREATE OR REPLACE TABLE {NS}.teacher_labels AS
SELECT ticket_id, split, queue AS true_queue, ticket,
       ai_query('{TEACHER}', concat({sql_str(PREFIX)}, ticket), responseFormat => '{LABEL_SCHEMA}') AS teacher_output
FROM {NS}.tickets
WHERE split = 'train'
""")
train_seconds = round(time.time() - t0, 1)
print(f"400 training tickets labelled in {train_seconds} s")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Label the 100 test tickets (for the comparison in step 4)

# COMMAND ----------

t0 = time.time()
spark.sql(f"""
INSERT INTO {NS}.teacher_labels
SELECT ticket_id, split, queue AS true_queue, ticket,
       ai_query('{TEACHER}', concat({sql_str(PREFIX)}, ticket), responseFormat => '{LABEL_SCHEMA}') AS teacher_output
FROM {NS}.tickets
WHERE split = 'test'
""")
test_seconds = round(time.time() - t0, 1)

# COMMAND ----------

labels = spark.sql(f"""
SELECT *, from_json(teacher_output, 'queue string, reply string') AS t FROM {NS}.teacher_labels
""").selectExpr("ticket_id", "split", "true_queue", "ticket", "t.queue AS teacher_queue", "t.reply AS teacher_reply")
labels.createOrReplaceTempView("labels")
display(spark.sql("""
SELECT split, count(*) AS tickets, count(teacher_queue) AS valid_labels,
       round(100 * avg(CASE WHEN teacher_queue = true_queue THEN 1 ELSE 0 END), 1) AS teacher_accuracy_pct
FROM labels GROUP BY split ORDER BY split DESC
"""))

# COMMAND ----------

display(spark.sql("SELECT true_queue, teacher_queue, ticket, teacher_reply FROM labels WHERE split = 'train' ORDER BY ticket_id LIMIT 10"))

# COMMAND ----------

stats = {r.split: dict(tickets=r.n, valid=r.v, acc=r.acc) for r in spark.sql(
    "SELECT split, count(*) n, count(teacher_queue) v, round(100*avg(int(teacher_queue = true_queue)),1) acc FROM labels GROUP BY split").collect()}
dbutils.notebook.exit(json.dumps({"train_seconds": train_seconds, "test_seconds": test_seconds, **stats}))
