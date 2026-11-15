# Databricks notebook source
# MAGIC %md
# MAGIC # Step 0 · Run open models on Databricks, and see what you pay for
# MAGIC Three open-weight models, served by Databricks as pay-per-token **Foundation Model APIs**:
# MAGIC
# MAGIC | Model | Parameters in total | Active per token | Kind |
# MAGIC |---|---|---|---|
# MAGIC | gpt-oss-120b (OpenAI) | 117B | 5.1B | mixture of experts |
# MAGIC | Qwen3-Next 80B A3B | 80B | 3B | mixture of experts |
# MAGIC | Llama 3.3 70B (Meta) | 70B | 70B | dense |
# MAGIC
# MAGIC 1. **Speed:** output tokens per second, one prompt, median of 3 runs. Speed follows the *active* parameters.
# MAGIC 2. **The first token:** before writing, the model reads the whole prompt (prefill). Longer prompt, longer wait.
# MAGIC 3. **Caching:** send the same long prompt again, and the start can come from the cache.
# MAGIC
# MAGIC Compute: serverless (CPU). Time: about 3 minutes. Numbers vary with load and serving configuration.

# COMMAND ----------

# MAGIC %pip install -q -U openai
# MAGIC %restart_python

# COMMAND ----------

import json, statistics, time
from openai import OpenAI
ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
client = OpenAI(base_url=f"{ctx.apiUrl().get()}/serving-endpoints", api_key=ctx.apiToken().get())

def stream(model, messages, max_tokens=400, **kw):
    """Stream one answer; return time to first token, total time and token usage."""
    t0 = time.time(); first = None; usage = None
    for ch in client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens, stream=True,
                                             stream_options={"include_usage": True}, **kw):
        if ch.usage: usage = ch.usage
        d = ch.choices[0].delta if ch.choices else None
        if d and (d.content or getattr(d, "reasoning_content", None)) and first is None:
            first = time.time() - t0
    total = time.time() - t0
    return dict(first_token_s=round(first or total, 3), total_s=round(total, 3), usage=usage.model_dump() if usage else {})

# COMMAND ----------

# MAGIC %md
# MAGIC ### 1 · Speed: tokens per second

# COMMAND ----------

PROMPT = [{"role": "user", "content": "Explain in about 250 words how a CPU cache works, for a junior engineer."}]
MODELS = {"databricks-gpt-oss-120b": {"reasoning_effort": "low"}, "databricks-qwen3-next-80b-a3b-instruct": {},
          "databricks-meta-llama-3-3-70b-instruct": {}}
speed = {}
for model, kw in MODELS.items():
    runs = []
    for _ in range(3):
        r = stream(model, PROMPT, 400, **kw)
        out = r["usage"].get("completion_tokens", 0)
        runs.append(round(out / max(.001, r["total_s"] - r["first_token_s"]), 1))
    speed[model] = statistics.median(runs)
    print(f"{model:45s} {speed[model]:6.1f} tokens/s  (runs: {runs})")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 2 · The first token waits for the whole prompt

# COMMAND ----------

PARAGRAPH = ("Bean & Byte store policy: opening hours are 6am to 9pm, delivery covers a two-mile radius, refunds are issued "
             "to the original payment method within five business days, loyalty points expire after twelve months, and "
             "every store keeps a log of temperature checks for milk and pastries. ")
first_token = []
for words in [1500, 12000, 45000]:
    doc = (PARAGRAPH * (words // len(PARAGRAPH.split()) + 1))
    msgs = [{"role": "user", "content": f"{doc}\n\n(request {time.time()}) In one sentence: what are the store hours?"}]
    r = stream("databricks-gpt-oss-120b", msgs, 60, reasoning_effort="low")
    first_token.append(dict(prompt_tokens=r["usage"].get("prompt_tokens"), first_token_s=r["first_token_s"]))
    print(first_token[-1])

# COMMAND ----------

# MAGIC %md
# MAGIC ### 3 · The same long prompt again: prompt caching
# MAGIC The repeated start of the prompt can come from the cache, which skips most of the prefill.
# MAGIC Each server keeps its own cache, so not every repeat is a hit.

# COMMAND ----------

doc = PARAGRAPH * (45000 // len(PARAGRAPH.split()) + 1) + f"\n(document {time.time()})"
caching = []
for call in range(1, 6):
    r = stream("databricks-gpt-oss-120b", [{"role": "user", "content": doc + "\n\nIn one sentence: what are the store hours?"}], 60, reasoning_effort="low")
    det = r["usage"].get("prompt_tokens_details") or {}
    caching.append(dict(call=call, prompt_tokens=r["usage"].get("prompt_tokens"), cached_tokens=det.get("cached_tokens"), first_token_s=r["first_token_s"]))
    print(caching[-1])

# COMMAND ----------

dbutils.notebook.exit(json.dumps({"when": time.strftime("%Y-%m-%d %H:%M"), "speed_tok_s": speed, "first_token": first_token, "caching": caching}))
