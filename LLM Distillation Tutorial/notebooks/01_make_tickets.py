# Databricks notebook source
# MAGIC %md
# MAGIC # Step 1 · Make the support tickets
# MAGIC We need examples of the job we want the small model to learn. Here we generate them: realistic app support tickets
# MAGIC for **Bean & Byte**, a made-up New York coffee chain, each written for one of 5 queues, with an ideal reply.
# MAGIC
# MAGIC - One SQL statement with `ai_query` calls an open model (Qwen3.5 122B A10B) 60 times: 5 queues × 12 writing styles × 10 tickets.
# MAGIC - We keep 100 tickets per queue, then hold back 20 per queue as a **test set** nobody trains on.
# MAGIC
# MAGIC Want to skip this step? Load `data/tickets.csv` from the repo instead (last cell).
# MAGIC
# MAGIC Compute: serverless (CPU). Time: about 2 minutes.

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {NS}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {NS}.files")

STYLES = [
    "short and frustrated, typed quickly on a phone",
    "polite and detailed, with an order number like #BB-48213",
    "long, with a lot of backstory before the actual problem",
    "all lowercase, with typos and almost no punctuation",
    "mentions a specific store and the time of day",
    "two issues in one ticket, where one is clearly the main request",
    "vague: the customer never uses the obvious keywords",
    "written by someone whose first language isn't English",
    "calm but firm, from a regular customer",
    "with an emoji or two and exclamation marks",
    "sarcastic",
    "very short, under 10 words",
]

def gen_prompt(queue, style):
    rules = "\n".join(f"{i}. {r}" for i, r in enumerate(RULES, 1))
    return (f"You write realistic customer support tickets for Bean & Byte, a New York coffee chain with a mobile ordering "
            f"and delivery app and 7 stores (Park Slope, Williamsburg, SoHo, Astoria, Harlem, Chelsea, DUMBO).\n"
            f"Support routes tickets with these rules, in order (the first one that fits wins):\n{rules}\n\n"
            f"Write 10 different tickets that these rules route to the queue '{queue}': {QUEUES[queue]}.\n"
            f"Style for this batch: {style}.\nMake each ticket about a different situation, and don't name the queue. "
            f"A few may mention a second topic, but the rules must still route the ticket to '{queue}'.\n"
            f"For each ticket, also write the ideal support reply: 1-2 sentences, polite, specific to the ticket, with a concrete next step.\n"
            f"Return JSON only.")

rows = [(q, s, gen_prompt(q, s)) for q in QUEUES for s in STYLES]
spark.createDataFrame(rows, "queue string, style string, prompt string").createOrReplaceTempView("gen_prompts")
print(len(rows), "generation prompts")

# COMMAND ----------

# MAGIC %md
# MAGIC ### One SQL statement writes all of them
# MAGIC `responseFormat` asks for structured JSON, so every answer parses.

# COMMAND ----------

SCHEMA_JSON = json.dumps({"type": "json_schema", "json_schema": {"name": "tickets", "strict": True, "schema": {
    "type": "object", "required": ["tickets"], "properties": {"tickets": {"type": "array", "items": {
        "type": "object", "required": ["ticket", "reply"],
        "properties": {"ticket": {"type": "string"}, "reply": {"type": "string"}}}}}}}})

spark.sql(f"""
CREATE OR REPLACE TABLE {NS}.raw_tickets AS
SELECT queue, style,
       ai_query('{GENERATOR}', prompt, responseFormat => '{SCHEMA_JSON}') AS response
FROM gen_prompts
""")
display(spark.sql(f"SELECT queue, style, left(response, 200) AS response FROM {NS}.raw_tickets LIMIT 5"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Parse, de-duplicate, balance and split
# MAGIC 100 tickets per queue: 80 to train on, 20 held out for the test.

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {NS}.tickets AS
WITH parsed AS (
  SELECT queue, style, t.ticket, t.reply AS reference_reply
  FROM {NS}.raw_tickets
  LATERAL VIEW explode(from_json(response, 'struct<tickets: array<struct<ticket: string, reply: string>>>').tickets) x AS t
  WHERE t.ticket IS NOT NULL AND length(t.ticket) > 3
),
dedup AS (
  SELECT *, row_number() OVER (PARTITION BY lower(trim(ticket)) ORDER BY style) AS dup FROM parsed
),
ranked AS (
  SELECT *, row_number() OVER (PARTITION BY queue ORDER BY xxhash64(ticket)) AS k FROM dedup WHERE dup = 1
)
SELECT row_number() OVER (ORDER BY queue, k) AS ticket_id, queue, ticket, reference_reply, style,
       CASE WHEN k <= 20 THEN 'test' ELSE 'train' END AS split
FROM ranked WHERE k <= 100
""")
display(spark.sql(f"SELECT queue, split, count(*) AS tickets FROM {NS}.tickets GROUP BY ALL ORDER BY queue, split"))

# COMMAND ----------

display(spark.sql(f"SELECT queue, ticket, reference_reply FROM {NS}.tickets WHERE split = 'train' ORDER BY rand(7) LIMIT 8"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Or load the tickets we generated for the video
# MAGIC Upload `data/tickets.csv` from the repo to the volume, then run this cell instead of the ones above.

# COMMAND ----------

# import pandas as pd
# pdf = pd.read_csv(f"{VOLUME}/tickets.csv")
# spark.createDataFrame(pdf).write.mode("overwrite").saveAsTable(f"{NS}.tickets")

# COMMAND ----------

n = spark.sql(f"SELECT count(*) FROM {NS}.tickets").first()[0]
dbutils.notebook.exit(json.dumps({"tickets": n, "by_split": {r.split: r.n for r in spark.sql(f"SELECT split, count(*) n FROM {NS}.tickets GROUP BY split").collect()}}))
