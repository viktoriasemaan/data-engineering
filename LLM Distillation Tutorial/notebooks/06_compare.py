# Databricks notebook source
# MAGIC %md
# MAGIC # Step 6 · Teacher vs student: speed, tokens and cost
# MAGIC Both models answer the 100 held-out tickets one request at a time, like production traffic:
# MAGIC the teacher through **Unity Gateway**, the student at its **Model Serving** endpoint. Every request carries a tag,
# MAGIC and two system tables count the tokens: `system.ai_gateway.usage` (teacher) and `system.serving.endpoint_usage` (student).
# MAGIC
# MAGIC Then the cost question: the teacher is billed **per token**, the student's GPU is billed **per hour**.
# MAGIC So which is cheaper depends on how many tickets you send. We compute the break-even volume.
# MAGIC
# MAGIC Compute: serverless (CPU). Time: about 10 minutes (plus a few minutes if the student's endpoint is waking from zero).

# COMMAND ----------

# MAGIC %pip install -q -U openai
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

# List prices (check yours): Databricks pricing pages and system.billing.list_prices
dbutils.widgets.text("usd_per_dbu", "0.07", "USD per DBU (serverless real-time inference)")
USD_PER_DBU = float(dbutils.widgets.get("usd_per_dbu"))
TEACHER_DBU_PER_M_IN, TEACHER_DBU_PER_M_OUT = 2.143, 8.571      # gpt-oss-120b pay-per-token, DBU per 1M tokens
STUDENT_GPU_DBU_PER_HOUR = 20.0                                 # Model Serving, 1x A10G (GPU_MEDIUM)
RUN_TAG = f"compare-{int(__import__('time').time())}"

import time, statistics as st, concurrent.futures as cf
from openai import OpenAI
ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
HOST, TOKEN = ctx.apiUrl().get(), ctx.apiToken().get()
gw = OpenAI(base_url=f"{HOST}/ai-gateway/mlflow/v1", api_key=TOKEN)
direct = OpenAI(base_url=f"{HOST}/serving-endpoints", api_key=TOKEN)

TEACHER_MODEL = "system.ai.gpt-oss-120b"
LABEL_FORMAT = {"type": "json_schema", "json_schema": {"name": "route", "strict": True, "schema": {
    "type": "object", "required": ["queue", "reply"],
    "properties": {"queue": {"type": "string", "enum": list(QUEUES)}, "reply": {"type": "string"}}}}}

def ask(system, ticket, tag):
    headers = {"Databricks-Ai-Gateway-Request-Tags": json.dumps({"video": "llm-distill", "run": RUN_TAG, "system": system, "phase": tag})}
    t0 = time.time()
    if system == "teacher":
        r = gw.chat.completions.create(model=TEACHER_MODEL, messages=[{"role": "user", "content": ticket_prompt(ticket)}],
                                       response_format=LABEL_FORMAT, extra_headers=headers)
    else:
        r = direct.chat.completions.create(model=STUDENT_ENDPOINT, messages=[{"role": "user", "content": student_prompt(ticket)}],
                                           max_tokens=120, temperature=0,
                                           extra_body={"usage_context": {"video": "llm-distill", "run": RUN_TAG, "phase": tag}})
    sec = time.time() - t0
    det = getattr(r.usage, "completion_tokens_details", None)
    return dict(seconds=sec, prompt_tokens=r.usage.prompt_tokens, completion_tokens=r.usage.completion_tokens,
                reasoning_tokens=getattr(det, "reasoning_tokens", None) or 0, output=r.choices[0].message.content)

test = spark.sql(f"SELECT ticket_id, ticket, queue FROM {NS}.tickets WHERE split = 'test' ORDER BY ticket_id").toPandas()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Wake the student's endpoint (scale-to-zero)

# COMMAND ----------

t0 = time.time()
for attempt in range(40):
    try:
        ask("student", test.ticket[0], "warmup"); break
    except Exception as e:
        print(f"waiting for the endpoint ({int(time.time() - t0)} s): {str(e)[:80]}"); time.sleep(15)
warmup_seconds = round(time.time() - t0)
ask("teacher", test.ticket[0], "warmup")
print(f"both ready (student warm-up {warmup_seconds} s)")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 100 tickets each, one at a time

# COMMAND ----------

rows = {"teacher": [], "student": []}
for system in rows:
    for t in test.ticket:
        rows[system].append(ask(system, t, "sequential"))

def summary(rs):
    acc = 100 * sum(parse_output(r["output"])[0] == q for r, q in zip(rs, test.queue)) / len(rs)
    s = sorted(r["seconds"] for r in rs)
    return dict(accuracy_pct=round(acc, 1), median_s=round(s[len(s) // 2], 3), p90_s=round(s[int(len(s) * .9)], 3),
                prompt_tokens=round(st.mean(r["prompt_tokens"] for r in rs), 1), completion_tokens=round(st.mean(r["completion_tokens"] for r in rs), 1),
                reasoning_tokens=round(st.mean(r["reasoning_tokens"] for r in rs), 1))
res = {k: summary(v) for k, v in rows.items()}
import pandas as pd; display(pd.DataFrame(res).T)

# COMMAND ----------

# MAGIC %md
# MAGIC ### How many tickets can one A10G handle? (16 requests at a time)

# COMMAND ----------

def burst(system, n_workers=16, n=200):
    tickets = list(test.ticket) * (n // len(test) + 1)
    t0 = time.time()
    with cf.ThreadPoolExecutor(n_workers) as ex:
        list(ex.map(lambda t: ask(system, t, "burst"), tickets[:n]))
    return round(n / (time.time() - t0), 1)
student_tps = burst("student")
print(f"student: {student_tps} tickets per second with 16 requests in flight -> {int(student_tps * 3600):,} per hour")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Cost per 1,000 tickets, and the break-even volume

# COMMAND ----------

teacher_usd_per_ticket = USD_PER_DBU * (res["teacher"]["prompt_tokens"] * TEACHER_DBU_PER_M_IN + res["teacher"]["completion_tokens"] * TEACHER_DBU_PER_M_OUT) / 1e6
student_usd_per_hour = USD_PER_DBU * STUDENT_GPU_DBU_PER_HOUR
breakeven_per_hour = student_usd_per_hour / teacher_usd_per_ticket
cost = dict(teacher_usd_per_1000=round(1000 * teacher_usd_per_ticket, 3), student_usd_per_hour=round(student_usd_per_hour, 2),
            breakeven_tickets_per_hour=int(breakeven_per_hour), student_capacity_per_hour=int(student_tps * 3600),
            student_usd_per_1000_at_capacity=round(1000 * student_usd_per_hour / (student_tps * 3600), 4))
print(json.dumps(cost, indent=1))
print(f"Below about {int(breakeven_per_hour):,} tickets an hour, the pay-per-token teacher costs less than keeping the student's GPU on.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### The referee: the usage tables
# MAGIC Rows arrive with a delay of several minutes. Re-run these cells later if they're empty.

# COMMAND ----------

display(spark.sql(f"""
SELECT 'teacher (Unity Gateway)' AS system, count(*) AS requests,
       round(avg(input_tokens), 1) AS avg_input_tokens, round(avg(output_tokens), 1) AS avg_output_tokens,
       round(avg(token_details.output_reasoning_tokens), 1) AS avg_reasoning_tokens
FROM system.ai_gateway.usage
WHERE request_tags['run'] = '{RUN_TAG}' AND request_tags['phase'] = 'sequential'
"""))

# COMMAND ----------

display(spark.sql(f"""
SELECT 'student (Model Serving)' AS system, count(*) AS requests,
       round(avg(u.input_token_count), 1) AS avg_input_tokens, round(avg(u.output_token_count), 1) AS avg_output_tokens
FROM system.serving.endpoint_usage u JOIN system.serving.served_entities e USING (served_entity_id)
WHERE e.endpoint_name = '{STUDENT_ENDPOINT}' AND u.usage_context['run'] = '{RUN_TAG}' AND u.usage_context['phase'] = 'sequential'
"""))

# COMMAND ----------

dbutils.notebook.exit(json.dumps({"run_tag": RUN_TAG, "warmup_seconds": warmup_seconds, "results": res, "student_tickets_per_s": student_tps, "cost": cost}))
