#!/bin/bash
# Step 5 · the full experiment: every harness, 3 runs each, on the open-weight model; then each harness on its own model.
#   usage: bash scripts/run_all.sh [runs-per-harness]
N=${1:-3}; cd "$(dirname "$0")/.."
for tier in open frontier; do for i in $(seq 1 $N); do for h in claude codex hermes; do
  bash scripts/run_one.sh $h $tier $i
done; done; done
echo "Graded runs: results/runs.jsonl. Costs: python3 scripts/costs.py  (wait a few minutes for the usage table)"
