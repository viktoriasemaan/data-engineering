#!/bin/bash
# Step 4 · the cost of hello: each harness answers "Reply with exactly: ok" once.
# The prompt tokens it sends are its preamble: system prompt + tool definitions, paid on every call.
#   usage: bash scripts/probe.sh [open|frontier]
set -u; TIER=${1:-open}
. "$(dirname "$0")/env.sh"; . scripts/harness.sh
mkdir -p runs/probe && cd runs/probe
for h in claude codex hermes; do
  printf '%-7s ' "$h"
  run_harness $h "$(model_for $h $TIER)" "$(tags $h $TIER probe-$h probe)" "Reply with exactly: ok" > $h.out 2> $h.err && echo "ok -> runs/probe/$h.out" || echo "failed, see runs/probe/$h.err"
done
echo "Prompt tokens per harness: python3 scripts/costs.py --mode probe  (the usage table can lag by a few minutes)"
