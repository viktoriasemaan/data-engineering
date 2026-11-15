# Databricks notebook source
# MAGIC %md
# MAGIC # Step 3 · Fine-tune the student with LoRA
# MAGIC The student is **Qwen3.5 0.8B** (base model, 0.8 billion parameters, about 150 times smaller than the teacher).
# MAGIC We teach it one job, routing tickets, from the teacher's 400 answers.
# MAGIC
# MAGIC 1. Measure the base model on the 100 test tickets, prompted with the full instructions.
# MAGIC 2. Train small **LoRA** adapters on the teacher's labels. The base weights stay frozen.
# MAGIC 3. Measure the student on the same test tickets. Its prompt is only the ticket: it learned the rules.
# MAGIC 4. Merge the adapters, test the model in vLLM, and register it in Unity Catalog for Model Serving.
# MAGIC
# MAGIC **Compute: AI Runtime (serverless GPU).** In the compute menu choose *Serverless GPU*, accelerator **H100**,
# MAGIC base environment **AI v6**. Time: about 15 minutes, most of it registering the model.
# MAGIC
# MAGIC Based on the Databricks tutorial *Fine-tune Qwen3.5-0.8B on AI Runtime and serve it*.

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

import os, time, torch, mlflow
from datasets import Dataset
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import LoraConfig
from trl import SFTTrainer, SFTConfig

ME = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{ME}/llm-distill-student")

train = spark.sql(f"""SELECT ticket_id, ticket, from_json(teacher_output, 'queue string, reply string') AS t
                      FROM {NS}.teacher_labels WHERE split = 'train' ORDER BY ticket_id""").toPandas()
test = spark.sql(f"SELECT ticket_id, ticket, queue AS true_queue FROM {NS}.tickets WHERE split = 'test' ORDER BY ticket_id").toPandas()
print(len(train), "training examples ·", len(test), "test tickets")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Load the base model
# MAGIC We give the student a minimal chat format, `User: …` / `Assistant: …`, and keep Qwen's own template
# MAGIC to give the base model its best shot. The prompt ends with `Assistant:` and no trailing space: the space
# MAGIC belongs to the answer's first token, so training and inference see the same tokens.

# COMMAND ----------

tokenizer = AutoTokenizer.from_pretrained(STUDENT_BASE)
model = AutoModelForCausalLM.from_pretrained(STUDENT_BASE, dtype=torch.bfloat16).to("cuda")
NATIVE_TEMPLATE = tokenizer.chat_template          # Qwen's own chat format
tokenizer.chat_template = (
    "{% for m in messages %}"
    "{% if m['role'] == 'system' %}System: {{ m['content'] }}\n"
    "{% elif m['role'] == 'user' %}User: {{ m['content'] }}\n"
    "{% elif m['role'] == 'assistant' %}Assistant: {{ m['content'] }}{{ eos_token }}\n"
    "{% endif %}{% endfor %}"
    "{% if add_generation_prompt %}Assistant:{% endif %}")
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token
total_params = sum(p.numel() for p in model.parameters())
print(f"{STUDENT_BASE}: {total_params:,} parameters")

def render(p, native=False):
    if native:
        return tokenizer.apply_chat_template([{"role": "user", "content": p}], tokenize=False, add_generation_prompt=True,
                                             chat_template=NATIVE_TEMPLATE, enable_thinking=False)
    return tokenizer.apply_chat_template([{"role": "user", "content": p}], tokenize=False, add_generation_prompt=True)

def generate(model, prompts, max_new_tokens=160, batch=16, native=False):
    """Greedy generation for a list of prompts (batched, left-padded)."""
    tokenizer.padding_side = "left"; outs = []
    for i in range(0, len(prompts), batch):
        texts = [render(p, native) for p in prompts[i:i + batch]]
        enc = tokenizer(texts, return_tensors="pt", padding=True).to(model.device)
        with torch.no_grad():
            g = model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False,
                               pad_token_id=tokenizer.pad_token_id, eos_token_id=tokenizer.eos_token_id)
        outs += tokenizer.batch_decode(g[:, enc["input_ids"].shape[1]:], skip_special_tokens=True)
    tokenizer.padding_side = "right"
    return outs

def accuracy(outputs, truth):
    return round(100 * sum(parse_output(o)[0] == t for o, t in zip(outputs, truth)) / len(truth), 1)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Before training: the base model, with the full instructions

# COMMAND ----------

# Two tries, and we keep the better one: our simple format, and Qwen's own chat format with thinking off.
base_simple = generate(model, [ticket_prompt(t) for t in test.ticket])
base_native = generate(model, [ticket_prompt(t) for t in test.ticket], native=True)
acc_simple, acc_native = accuracy(base_simple, test.true_queue), accuracy(base_native, test.true_queue)
base_out, base_acc, base_format = (base_native, acc_native, "qwen") if acc_native >= acc_simple else (base_simple, acc_simple, "simple")
print(f"base model: {acc_simple}% with the simple format, {acc_native}% with Qwen's format -> {base_acc}%")
for t, o in list(zip(test.ticket, base_out))[:3]:
    print(f"\nTICKET: {t[:120]}\nBASE:   {o[:200]}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Train LoRA adapters on the teacher's answers
# MAGIC LoRA freezes every original weight and trains two small matrices next to each layer.
# MAGIC The loss is computed only on the answer (the completion), not on the prompt.

# COMMAND ----------

# Plain-text prompt and completion, so the loss covers only the answer
ds = Dataset.from_list([
    {"prompt": render(student_prompt(r.ticket)),
     "completion": " " + json.dumps({"queue": r.t["queue"], "reply": r.t["reply"]}, ensure_ascii=False) + tokenizer.eos_token}
    for r in train.itertuples()])
print(ds[0]["prompt"] + ds[0]["completion"])

lora = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, target_modules="all-linear", task_type="CAUSAL_LM")
cfg = SFTConfig(output_dir="/tmp/student_ckpt", num_train_epochs=3, per_device_train_batch_size=8,
                learning_rate=2e-4, lr_scheduler_type="cosine", warmup_ratio=0.1, bf16=True,
                logging_steps=1, max_length=512, save_strategy="no", report_to=["mlflow"], run_name="student-lora")
trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds, processing_class=tokenizer, peft_config=lora)
trainable, all_params = trainer.model.get_nb_trainable_parameters()
print(f"trainable: {trainable:,} of {all_params:,} parameters ({100 * trainable / all_params:.2f}%)")

torch.cuda.reset_peak_memory_stats()
with mlflow.start_run(run_name="student-lora") as run:
    t0 = time.time(); trainer.train(); train_seconds = round(time.time() - t0, 1)
    peak_gb = round(torch.cuda.max_memory_allocated() / 1e9, 2)
    mlflow.log_params({"base_model": STUDENT_BASE, "teacher": TEACHER, "lora_r": 16, "lora_alpha": 32, "epochs": 3, "train_examples": len(ds)})
    mlflow.log_metrics({"trainable_params": trainable, "total_params": all_params, "train_seconds": train_seconds, "peak_gpu_gb": peak_gb})
    train_run_id = run.info.run_id
losses = [h["loss"] for h in trainer.state.log_history if "loss" in h]
print(f"trained in {train_seconds} s · peak GPU memory {peak_gb} GB · loss {losses[0]:.3f} -> {losses[-1]:.3f} over {len(losses)} steps")

# COMMAND ----------

# MAGIC %md
# MAGIC ### After training: the student, with only the ticket in its prompt

# COMMAND ----------

trainer.model.eval()
student_out = generate(trainer.model, [student_prompt(t) for t in test.ticket])
student_acc = accuracy(student_out, test.true_queue)
print(f"student: {student_acc}% (base model was {base_acc}%)")
for t, o in list(zip(test.ticket, student_out))[:3]:
    print(f"\nTICKET:  {t[:120]}\nSTUDENT: {o[:200]}")

# COMMAND ----------

# Save the adapters (small) to the volume, and the predictions for step 4
adapter_dir = f"{VOLUME}/student_lora_adapter"
trainer.model.save_pretrained(adapter_dir)
import pandas as pd
preds = pd.concat([pd.DataFrame({"system": "base_model", "ticket_id": test.ticket_id, "output": base_out}),
                   pd.DataFrame({"system": "student", "ticket_id": test.ticket_id, "output": student_out})])
spark.createDataFrame(preds).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{NS}.student_predictions")
json.dump({"base_acc": base_acc, "base_acc_simple": acc_simple, "base_acc_qwen_format": acc_native, "base_format": base_format, "student_acc": student_acc, "trainable": trainable, "total": all_params, "train_seconds": train_seconds,
           "peak_gpu_gb": peak_gb, "steps": len(losses), "loss_first": losses[0], "loss_last": losses[-1], "losses": losses,
           "train_run_id": train_run_id}, open("/tmp/train_metrics.json", "w"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Merge the adapters and save the model for serving
# MAGIC Qwen3.5 0.8B is the text half of a vision-language model, so we save it the way vLLM expects:
# MAGIC the merged text weights, the original processor files, our tokenizer, and the composite config.

# COMMAND ----------

from transformers import AutoConfig, AutoProcessor
WORKDIR = "/tmp/sft_serve"; ARTIFACTS_PATH = "ticket_router"; SAVE_DIR = os.path.join(WORKDIR, ARTIFACTS_PATH)
os.makedirs(SAVE_DIR, exist_ok=True)
merged = trainer.model.merge_and_unload()
merged.save_pretrained(SAVE_DIR)
try:
    AutoProcessor.from_pretrained(STUDENT_BASE).save_pretrained(SAVE_DIR)
except Exception as e:
    print("processor save skipped:", e)
tokenizer.save_pretrained(SAVE_DIR)
cfg_c = AutoConfig.from_pretrained(STUDENT_BASE); cfg_c.architectures = ["Qwen3_5ForCausalLM"]; cfg_c.save_pretrained(SAVE_DIR)
print("saved", SAVE_DIR, sorted(os.listdir(SAVE_DIR)))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Restart Python to free the GPU for vLLM

# COMMAND ----------

# MAGIC %restart_python

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

import os, json, subprocess, time, requests
WORKDIR = "/tmp/sft_serve"; ARTIFACTS_PATH = "ticket_router"; os.chdir(WORKDIR)
SERVED_NAME = "ticket-router"

def entrypoint(port, gpu_util=0.85):
    """The vLLM command. The same string runs here (port 3080) and inside the serving endpoint (port 8080)."""
    return " ".join([
        "VLLM_USE_FLASHINFER_SAMPLER=0", "python", "-u", "-m", "vllm.entrypoints.openai.api_server",
        "--model", ARTIFACTS_PATH, "--served-model-name", SERVED_NAME, "--host", "0.0.0.0", "--port", str(port),
        "--dtype", "float16", "--max-model-len", "4096", "--gpu-memory-utilization", str(gpu_util),
        "--gdn-prefill-backend", "triton", "--limit-mm-per-prompt", "'{\"image\": 0, \"video\": 0}'"])

log = open("vllm.log", "w")
proc = subprocess.Popen(["bash", "-lc", entrypoint(3080)], stdout=log, stderr=subprocess.STDOUT, text=True, start_new_session=True)
for _ in range(120):
    time.sleep(5)
    if "Application startup complete" in open("vllm.log").read(): break
print(open("vllm.log").read()[-1500:])

# COMMAND ----------

# MAGIC %md
# MAGIC ### Try the student in vLLM, the engine Model Serving will run

# COMMAND ----------

test = spark.sql(f"SELECT ticket_id, ticket, queue AS true_queue FROM {NS}.tickets WHERE split = 'test' ORDER BY ticket_id").toPandas()
lat, outs = [], []
for t in test.ticket:
    t0 = time.time()
    r = requests.post("http://localhost:3080/invocations", json={"messages": [{"role": "user", "content": student_prompt(t)}], "max_tokens": 120, "temperature": 0})
    lat.append(time.time() - t0); outs.append(r.json()["choices"][0]["message"]["content"])
vllm_acc = round(100 * sum(parse_output(o)[0] == q for o, q in zip(outs, test.true_queue)) / len(test), 1)
lat_sorted = sorted(lat)
print(f"vLLM on H100: {vllm_acc}% · median {lat_sorted[len(lat) // 2]:.3f} s per ticket, one at a time")
print(outs[0])
subprocess.run(["pkill", "-f", "vllm.entrypoints.openai.api_server"])

# COMMAND ----------

# MAGIC %md
# MAGIC ### Log and register the model in Unity Catalog
# MAGIC Model Serving runs the vLLM command stored in the model's metadata. It must be logged from this GPU runtime.

# COMMAND ----------

import mlflow
from mlflow.pyfunc.model import ChatModel, ChatCompletionResponse

class TicketRouter(ChatModel):
    """Placeholder: Model Serving runs the vLLM entrypoint, not predict()."""
    def predict(self, context, messages, params):
        return ChatCompletionResponse.from_dict({"choices": []})

assert os.environ.get("DATABRICKS_ACCELERATOR"), "log the model from a serverless GPU runtime"
ME = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{ME}/llm-distill-student")
mlflow.set_registry_uri("databricks-uc")
with mlflow.start_run(run_name="ticket-router-model"):
    info = mlflow.pyfunc.log_model(name="ticket_router", python_model=TicketRouter(), artifacts={"model_dir": ARTIFACTS_PATH},
                                   metadata={"task": "llm/v1/chat", "entrypoint": entrypoint(8080)},
                                   extra_pip_requirements=[f"mlflow=={mlflow.__version__}"])
t0 = time.time()
mv = mlflow.register_model(info.model_uri, STUDENT_MODEL, env_pack="databricks_model_serving")
print(f"registered {STUDENT_MODEL} version {mv.version} in {time.time() - t0:.0f} s")

# COMMAND ----------

m = json.load(open("/tmp/train_metrics.json"))
m.update({"vllm_acc": vllm_acc, "vllm_median_s": round(lat_sorted[len(lat) // 2], 3), "vllm_mean_s": round(sum(lat) / len(lat), 3),
          "model": STUDENT_MODEL, "version": mv.version})
dbutils.notebook.exit(json.dumps(m))
