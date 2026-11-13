#!/bin/bash
# Step 5 · one graded run: copy the task, run one harness on it, then grade with the visible and the hidden tests.
#   usage: bash scripts/run_one.sh <claude|codex|hermes> <open|frontier> <run-id>
#   e.g.   bash scripts/run_one.sh codex open 1
set -u; H=$1; TIER=$2; N=$3; RUN=task-$H-$TIER-$N
. "$(dirname "$0")/env.sh"; . scripts/harness.sh
PROMPT='Implement refunds as described in docs/REFUNDS.md. Run the tests with `.venv/bin/python -m pytest -q` until they all pass. Keep the change small and in the style of the code. End with a one-line summary.'
W=runs/$RUN; rm -rf "$W"; mkdir -p "$W"
cp -R task "$W/repo"; ln -s "$ROOT/task/.venv" "$W/repo/.venv"         # the agent only ever sees task/, never hidden_tests/
(cd "$W/repo" && git init -q && git add -A && git -c core.hooksPath=/dev/null -c user.email=t@t -c user.name=t commit -qm start)
START=$(date +%s)
(cd "$W/repo" && run_harness $H "$(model_for $H $TIER)" "$(tags $H $TIER $RUN task)" "$PROMPT" > ../harness.out 2> ../harness.err)
SECS=$(( $(date +%s) - START ))
VIS=$(cd "$W/repo" && .venv/bin/python -m pytest -q -p no:cacheprovider tests 2>&1 | tail -1)
HID=$(cd "$W/repo" && PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider "$ROOT/hidden_tests" 2>&1 | tail -1)
DIFF=$(cd "$W/repo" && git add -A && git diff --cached --shortstat | sed 's/^ //')
python3 -c "import json,sys; print(json.dumps(dict(zip(['harness','tier','run','seconds','visible','hidden','diff'], sys.argv[1:]))))" \
  "$H" "$TIER" "$RUN" "$SECS" "$VIS" "$HID" "$DIFF" | tee -a results/runs.jsonl
