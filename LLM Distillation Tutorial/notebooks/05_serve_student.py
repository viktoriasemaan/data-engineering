# Databricks notebook source
# MAGIC %md
# MAGIC # Step 5 · Serve the student with Model Serving
# MAGIC 1. Create a **Model Serving** endpoint for the registered student. It runs the same vLLM command we tested in
# MAGIC    step 3, on one A10G GPU, with an OpenAI-compatible chat API. Scale-to-zero is on, so it costs nothing while idle
# MAGIC    (the first request after idle waits a few minutes).
# MAGIC 2. Query it like any chat model.
# MAGIC 3. Turn on usage tracking, so every request is counted in `system.serving.endpoint_usage`.
# MAGIC
# MAGIC The teacher, a pay-per-token foundation model, is reached through **Unity Gateway** (`system.ai.gpt-oss-120b`).
# MAGIC Unity Gateway routes to foundation models (pay-per-token or provisioned throughput) and external models; a custom
# MAGIC vLLM endpoint like this one is called directly at `/serving-endpoints`.
# MAGIC
# MAGIC Compute: serverless (CPU). Time: up to 40 minutes for the first deployment.

# COMMAND ----------

# MAGIC %pip install -q -U "databricks-sdk>=0.102" "mlflow[databricks]>=3.12" openai
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

from datetime import timedelta
import mlflow, time
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import EndpointCoreConfigInput, ServedEntityInput, ServingModelWorkloadType

w = WorkspaceClient()
client = mlflow.MlflowClient(registry_uri="databricks-uc")
version = max(int(v.version) for v in client.search_model_versions(f"name='{STUDENT_MODEL}'"))
print(f"serving {STUDENT_MODEL} version {version} as endpoint '{STUDENT_ENDPOINT}'")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Create (or update) the endpoint

# COMMAND ----------

entities = [ServedEntityInput(entity_name=STUDENT_MODEL, entity_version=str(version),
                              workload_type=ServingModelWorkloadType.GPU_MEDIUM,   # 1x A10G, 24 GB
                              workload_size="Small", scale_to_zero_enabled=True)]
t0 = time.time()
def serving_version(name):
    cfg = w.serving_endpoints.get(name).config
    return {e.entity_version for e in (cfg.served_entities if cfg else [])}

if STUDENT_ENDPOINT not in {e.name for e in w.serving_endpoints.list()}:
    try:
        w.serving_endpoints.create(name=STUDENT_ENDPOINT, config=EndpointCoreConfigInput(name=STUDENT_ENDPOINT, served_entities=entities))
    except Exception as e:                       # a retried create can report a conflict: the first one already worked
        print("create returned:", str(e)[:120])
elif str(version) not in serving_version(STUDENT_ENDPOINT):
    w.serving_endpoints.wait_get_serving_endpoint_not_updating(STUDENT_ENDPOINT, timeout=timedelta(minutes=40))
    w.serving_endpoints.update_config(name=STUDENT_ENDPOINT, served_entities=entities)
w.serving_endpoints.wait_get_serving_endpoint_not_updating(STUDENT_ENDPOINT, timeout=timedelta(minutes=40))
state = w.serving_endpoints.get(STUDENT_ENDPOINT).state
assert state.ready.value == "READY", state
deploy_minutes = round((time.time() - t0) / 60, 1)
print(f"endpoint ready in {deploy_minutes} min")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Query it with the OpenAI client

# COMMAND ----------

from openai import OpenAI
ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
HOST, TOKEN = ctx.apiUrl().get(), ctx.apiToken().get()

serving = OpenAI(base_url=f"{HOST}/serving-endpoints", api_key=TOKEN)
ticket = "ordered two lattes to park slope 40 min ago, app says delivered but nothing here"
r = serving.chat.completions.create(model=STUDENT_ENDPOINT, messages=[{"role": "user", "content": student_prompt(ticket)}],
                                    max_tokens=120, temperature=0)
print(r.choices[0].message.content)
print(r.usage)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Count every request: usage tracking on the endpoint

# COMMAND ----------

from databricks.sdk.service.serving import AiGatewayUsageTrackingConfig
w.serving_endpoints.put_ai_gateway(name=STUDENT_ENDPOINT, usage_tracking_config=AiGatewayUsageTrackingConfig(enabled=True))
print("usage tracking on: rows land in system.serving.endpoint_usage")

# COMMAND ----------

dbutils.notebook.exit(json.dumps({"endpoint": STUDENT_ENDPOINT, "version": version, "deploy_minutes": deploy_minutes,
                                  "answer": r.choices[0].message.content}))
