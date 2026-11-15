# Databricks notebook source
# MAGIC %md
# MAGIC # Clean up
# MAGIC Deletes what this tutorial created: the student's serving endpoint, the registered model, the tables and the volume.
# MAGIC Set `confirm` to `yes` to run it. The schema itself is dropped only if `drop_schema` is `yes`.

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

dbutils.widgets.dropdown("confirm", "no", ["no", "yes"]); dbutils.widgets.dropdown("drop_schema", "no", ["no", "yes"])
assert dbutils.widgets.get("confirm") == "yes", "set confirm = yes to delete"
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
if STUDENT_ENDPOINT in {e.name for e in w.serving_endpoints.list()}:
    w.serving_endpoints.delete(STUDENT_ENDPOINT); print("deleted endpoint", STUDENT_ENDPOINT)
try:
    w.registered_models.delete(STUDENT_MODEL); print("deleted model", STUDENT_MODEL)
except Exception as e:
    print("model:", str(e)[:120])
for t in ["raw_tickets", "tickets", "teacher_labels", "student_predictions", "eval_rows"]:
    spark.sql(f"DROP TABLE IF EXISTS {NS}.{t}")
spark.sql(f"DROP VOLUME IF EXISTS {NS}.files")
if dbutils.widgets.get("drop_schema") == "yes":
    spark.sql(f"DROP SCHEMA IF EXISTS {NS} CASCADE")
print("done. MLflow experiments are kept: delete them in the Experiments page if you want.")
