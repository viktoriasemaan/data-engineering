# Sourced: run_harness <harness> <model> <tags-json> <prompt>   (runs in the current directory, output on stdout)
run_harness() {
  local h=$1 m=$2 t=$3 p=$4
  case "$h" in
    claude)
      ANTHROPIC_CUSTOM_HEADERS="x-databricks-use-coding-agent-mode: true
Databricks-Ai-Gateway-Request-Tags: $t" \
      ANTHROPIC_MODEL=$m ANTHROPIC_DEFAULT_OPUS_MODEL=$m ANTHROPIC_DEFAULT_SONNET_MODEL=$m ANTHROPIC_DEFAULT_HAIKU_MODEL=$m CLAUDE_CODE_SUBAGENT_MODEL=$m \
        claude -p "$p" --model "$m" --output-format json --dangerously-skip-permissions < /dev/null ;;
    codex)
      codex exec --json --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox -m "$m" \
        -c "model_providers.gateway.http_headers.Databricks-Ai-Gateway-Request-Tags='$t'" "$p" < /dev/null ;;
    hermes)
      local cfg; cfg=$(hermes $HP config path 2>/dev/null)
      python3 - "$cfg" "$t" <<'PY'
import re, sys
p, t = sys.argv[1], sys.argv[2]; s = open(p).read()
open(p, "w").write(re.sub(r"Databricks-Ai-Gateway-Request-Tags: .*", "Databricks-Ai-Gateway-Request-Tags: '" + t + "'", s))
PY
      hermes $HP chat -q "$p" -m "$m" --provider unity --yolo < /dev/null ;;
  esac
}
