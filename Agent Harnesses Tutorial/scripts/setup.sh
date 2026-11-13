#!/bin/bash
# Install stock Claude Code, Codex CLI and Hermes Agent, and point all three at the same Unity Gateway.
# Each harness gets its own isolated config home inside this folder, so your personal settings,
# plugins, skills and memory are never used (and never changed).
#   usage: bash scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."; ROOT=$PWD
set -a; [ -f .env ] && . ./.env; set +a
: "${DATABRICKS_HOST:?set DATABRICKS_HOST in .env}"
WS=${DATABRICKS_HOST%/}; PROFILE=${DATABRICKS_CONFIG_PROFILE:-DEFAULT}

# 1. the three harnesses (needs Node 20+ for Claude Code and Codex)
command -v claude >/dev/null || npm install -g @anthropic-ai/claude-code
command -v codex  >/dev/null || npm install -g @openai/codex
command -v hermes >/dev/null || curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

# 2. one credential helper: prints a short-lived workspace token from the Databricks CLI. No key is ever written to a file.
mkdir -p .homes/bin
cat > .homes/bin/gw-token <<HELPER
#!/bin/bash
exec databricks auth token --profile $PROFILE 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])"
HELPER
chmod +x .homes/bin/gw-token

# 3. Claude Code -> Anthropic route (isolated with CLAUDE_CONFIG_DIR)
mkdir -p .homes/claude
cat > .homes/claude/settings.json <<JSON
{"env": {"ANTHROPIC_BASE_URL": "$WS/ai-gateway/anthropic", "DISABLE_TELEMETRY": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
 "apiKeyHelper": "$ROOT/.homes/bin/gw-token"}
JSON

# 4. Codex -> Responses route (isolated with CODEX_HOME)
mkdir -p .homes/codex
cat > .homes/codex/config.toml <<TOML
model = "${OPEN_MODEL:-system.ai.kimi-k3}"
model_provider = "gateway"
[model_providers.gateway]
name = "Unity Gateway"
base_url = "$WS/ai-gateway/codex/v1"
wire_api = "responses"
[model_providers.gateway.auth]
command = "$ROOT/.homes/bin/gw-token"
timeout_ms = 60000
refresh_interval_ms = 900000
[model_providers.gateway.http_headers]
x-databricks-use-coding-agent-mode = "true"
TOML

# 5. Hermes -> chat completions route (a fresh profile, so your own Hermes memory and skills are not used)
hermes profile list 2>/dev/null | grep -q harnesstutorial || hermes profile create harnesstutorial --no-alias >/dev/null
HCFG=$(hermes -p harnesstutorial config path 2>/dev/null || echo "$HOME/.hermes/profiles/harnesstutorial/config.yaml")
python3 - "$HCFG" "$WS" "$ROOT" <<'PY'
import pathlib, re, sys
p, ws, root = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
p.parent.mkdir(parents=True, exist_ok=True)
s = p.read_text() if p.exists() else ""
s = re.sub(r"(?ms)^# --- harness-tutorial ---.*?\Z", "", s)
# drop any existing top-level model: / providers: blocks (a block ends at the next unindented line)
out, skip = [], False
for line in s.splitlines():
    if re.match(r"^(model|providers):", line): skip = True; continue
    if skip and line and not line[0].isspace(): skip = False
    if not skip: out.append(line)
s = "\n".join(out).rstrip() + "\n"
s += f"""# --- harness-tutorial ---
model:
  provider: unity
providers:
  unity:
    name: Unity Gateway
    api: {ws}/ai-gateway/mlflow/v1
    transport: chat_completions
    key_cmd: "{root}/.homes/bin/gw-token"
    discover_models: false
    extra_headers:
      x-databricks-use-coding-agent-mode: "true"
      Databricks-Ai-Gateway-Request-Tags: '{{}}'
    default_model: databricks-kimi-k3
    models:
      databricks-kimi-k3: {{context_length: 200000}}
      databricks-claude-opus-5-5: {{context_length: 200000}}
"""
p.write_text(s)
PY

# 6. the task's own Python env (pytest only)
python3 -m venv task/.venv && task/.venv/bin/pip -q install pytest
echo; claude --version; codex --version; hermes --version 2>/dev/null | head -1
echo "setup done: run  bash scripts/probe.sh  next"
