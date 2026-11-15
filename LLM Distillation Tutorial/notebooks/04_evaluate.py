# Databricks notebook source
# MAGIC %md
# MAGIC # Step 4 · Evaluate teacher, base model and student with MLflow
# MAGIC Three systems, the same 100 held-out tickets none of them trained on:
# MAGIC - **teacher**: gpt-oss-120b, full instructions
# MAGIC - **base model**: Qwen3.5 0.8B before training, full instructions
# MAGIC - **student**: Qwen3.5 0.8B after training, only the ticket
# MAGIC
# MAGIC Two kinds of checks:
# MAGIC 1. **A code check** for the queue: exact match against the queue the ticket was written for. Cheap, repeatable, hard to argue with.
# MAGIC 2. **An LLM judge** for the reply, which has no single right answer: is it polite, specific to the ticket, with a concrete next step?
# MAGIC
# MAGIC Compute: serverless (CPU). Time: about 5 minutes.

# COMMAND ----------

# MAGIC %pip install -q -U "mlflow[databricks]>=3.10"
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

import mlflow
from mlflow.genai.scorers import Guidelines, scorer

ME = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{ME}/llm-distill-evals")

test = spark.sql(f"SELECT ticket_id, ticket, queue FROM {NS}.tickets WHERE split = 'test' ORDER BY ticket_id").toPandas()
teacher = spark.sql(f"SELECT ticket_id, teacher_output AS output FROM {NS}.teacher_labels WHERE split = 'test'").toPandas()
students = spark.sql(f"SELECT system, ticket_id, output FROM {NS}.student_predictions").toPandas()
outputs = {"teacher": dict(zip(teacher.ticket_id, teacher.output))}
for system, g in students.groupby("system"):
    outputs[system] = dict(zip(g.ticket_id, g.output))
print({k: len(v) for k, v in outputs.items()})

# COMMAND ----------

# MAGIC %md
# MAGIC ### The two scorers

# COMMAND ----------

@scorer
def queue_match(outputs, expectations):
    """Code check: did the model pick the right queue?"""
    return outputs.get("queue") == expectations["queue"]

good_reply = Guidelines(name="good_reply", guidelines=[
    "The reply is polite.",
    "The reply is specific to the customer's ticket, not generic.",
    "The reply gives the customer a concrete next step.",
])

def eval_data(system):
    rows = []
    for r in test.itertuples():
        q, reply = parse_output(outputs[system].get(r.ticket_id))
        rows.append({"inputs": {"ticket": r.ticket}, "outputs": {"queue": q, "reply": reply},
                     "expectations": {"queue": r.queue}})
    return rows

# COMMAND ----------

# MAGIC %md
# MAGIC ### Run one evaluation per system

# COMMAND ----------

results, rows = {}, []
for system in ["teacher", "base_model", "student"]:
    with mlflow.start_run(run_name=system) as run:
        res = mlflow.genai.evaluate(data=eval_data(system), scorers=[queue_match, good_reply])
    results[system] = {k: round(100 * v, 1) for k, v in res.metrics.items() if k.endswith("/mean")}
    print(system, results[system])
    # keep every verdict and the judge's reason, so you can read them (and query them) later
    for t in mlflow.search_traces(run_id=run.info.run_id, return_type="list"):
        a = {x.name: x for x in (t.info.assessments or [])}
        req = t.data.request if t.data else None
        rows.append({"system": system, "request": str(req)[:2000], "response": str(t.data.response if t.data else "")[:2000],
                     "queue_correct": str(getattr(a.get("queue_match"), "value", None)),
                     "good_reply": str(getattr(a.get("good_reply"), "value", None)),
                     "judge_rationale": (getattr(a.get("good_reply"), "rationale", None) or "")[:2000]})

import pandas as pd
spark.createDataFrame(pd.DataFrame(rows)).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{NS}.eval_rows")

# COMMAND ----------

display(pd.DataFrame(results).T.rename(columns={"queue_match/mean": "queue correct %", "good_reply/mean": "good reply %"}))

# COMMAND ----------

dbutils.notebook.exit(json.dumps(results))
