# Databricks notebook source
# MAGIC %md
# MAGIC # Shared settings
# MAGIC Every notebook starts with `%run ./_config`. Set your catalog and schema in the widgets at the top of each notebook.

# COMMAND ----------

dbutils.widgets.text("catalog", "main", "Catalog")
dbutils.widgets.text("schema", "llm_distill", "Schema")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
NS = f"{CATALOG}.{SCHEMA}"                      # every table, volume and model lives here
VOLUME = f"/Volumes/{CATALOG}/{SCHEMA}/files"   # adapters, merged weights, predictions

# Models
GENERATOR = "databricks-qwen35-122b-a10b"       # writes the synthetic tickets (open weights, Apache 2.0)
TEACHER = "databricks-gpt-oss-120b"             # labels the tickets (open weights, Apache 2.0)
STUDENT_BASE = "Qwen/Qwen3.5-0.8B-Base"         # the small model we fine-tune
STUDENT_MODEL = f"{NS}.ticket_router"           # Unity Catalog name of the fine-tuned student
STUDENT_ENDPOINT = "ticket-router-student"      # Model Serving endpoint for the student

# The task: sort a Bean & Byte app support ticket into one queue, and suggest a reply.
QUEUES = {
    "delivery": "a problem with a delivered order: late, missing or wrong items, spilled or cold drinks, courier problems, wrong address",
    "billing":  "wrong or unexpected charges: double charges, wrong prices, promo codes or gift cards not applied, receipts, payment methods, subscriptions",
    "refund":   "cancelling an order, or asking about a refund that's already in progress",
    "account":  "signing in and account settings: passwords, verification codes, email or phone changes, loyalty points, deleting the account",
    "app_bug":  "the app or website not working, when it isn't about money: crashes, frozen screens, buttons that do nothing, wrong menu or store hours",
}
# Routing rules, in priority order: the first one that fits wins.
RULES = [
    "A problem with a delivered order is delivery, even if the customer wants a refund or a replacement.",
    "A wrong or extra charge is billing, even if the customer asks for the money back.",
    "Cancelling an order, or the status of a refund, is refund.",
    "Signing in, account settings and loyalty points are account.",
    "Anything else the app gets wrong is app_bug.",
]

def ticket_prompt(ticket: str) -> str:
    """The full prompt for the teacher and the base model: the queues, the rules, the output format, the ticket."""
    queues = "\n".join(f"- {k}: {v}" for k, v in QUEUES.items())
    rules = "\n".join(f"{i}. {r}" for i, r in enumerate(RULES, 1))
    return (f"You route customer support tickets for Bean & Byte, a coffee chain with an ordering and delivery app.\n"
            f"Queues:\n{queues}\nRules, in order (the first one that fits wins):\n{rules}\n\n"
            f'Reply with JSON only: {{"queue": "<one of {", ".join(QUEUES)}>", "reply": "<1-2 polite sentences to the customer with a concrete next step>"}}\n\n'
            f"Ticket: {ticket}")

def student_prompt(ticket: str) -> str:
    """The distilled student learned the queues and rules in training, so its prompt is just the ticket."""
    return f"Route this Bean & Byte support ticket. Ticket: {ticket}"

import json, re
def parse_output(text):
    """Find the JSON object in a model's answer. Returns (queue or None, reply or None)."""
    if text is None: return None, None
    m = re.search(r"\{.*\}", str(text), re.S)
    if not m: return None, None
    try:
        d = json.loads(m.group(0))
        q = str(d.get("queue", "")).strip().lower()
        return (q if q in QUEUES else None), d.get("reply")
    except Exception:
        q = re.search(r'"queue"\s*:\s*"([a-z_]+)"', m.group(0))
        return (q.group(1) if q and q.group(1) in QUEUES else None), None

print(f"tables and models go to {NS}")
