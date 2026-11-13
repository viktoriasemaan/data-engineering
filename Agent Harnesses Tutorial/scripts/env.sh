# Sourced by the other scripts: loads .env and points each harness at its isolated config home.
cd "$(dirname "${BASH_SOURCE[0]}")/.."; ROOT=$PWD
set -a; [ -f .env ] && . ./.env; set +a
export CLAUDE_CONFIG_DIR=$ROOT/.homes/claude CODEX_HOME=$ROOT/.homes/codex
HP="-p harnesstutorial"
OPEN_MODEL=${OPEN_MODEL:-system.ai.kimi-k3}; HERMES_OPEN_MODEL=${HERMES_OPEN_MODEL:-databricks-kimi-k3}
CLAUDE_MODEL=${CLAUDE_MODEL:-system.ai.claude-opus-5-5}; CODEX_MODEL=${CODEX_MODEL:-system.ai.gpt-6-1-sol}
HERMES_FRONTIER_MODEL=${HERMES_FRONTIER_MODEL:-databricks-claude-opus-5-5}
model_for() {  # model_for <harness> <open|frontier>
  case "$2:$1" in
    open:claude|open:codex) echo "$OPEN_MODEL" ;;  open:hermes) echo "$HERMES_OPEN_MODEL" ;;
    frontier:claude) echo "$CLAUDE_MODEL" ;;  frontier:codex) echo "$CODEX_MODEL" ;;  frontier:hermes) echo "$HERMES_FRONTIER_MODEL" ;;
  esac
}
tags() { echo "{\"harness\":\"$1\",\"tier\":\"$2\",\"run\":\"$3\",\"mode\":\"$4\",\"video\":\"harness-tutorial\"}"; }
