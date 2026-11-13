#!/usr/bin/env python3
"""Step 6 · read the bill: cost per run and per harness from system.ai_gateway.usage, the gateway's own token counts.

    pip install databricks-sdk
    python3 scripts/costs.py                 # graded runs from this tutorial
    python3 scripts/costs.py --mode probe    # the hello test: prompt tokens per harness

input_tokens in the usage table is the whole prompt (new + cache read + cache write), so new = input - read - write.
Prices are USD per 1M tokens, Databricks list prices on the day of the video; change PRICE for your own contract.
"""
import argparse, os, pathlib
from databricks.sdk import WorkspaceClient

PRICE = {  # input, cache read, cache write, output  (USD per 1M tokens)
    "Kimi K3": (3.00, 0.30, 3.00, 15.00),
    "Claude Opus 5.5": (4.00, 0.20, 5.00, 20.00),
    "GPT-6.1 Sol": (2.00, 0.10, 2.50, 10.00),
}
ALIAS = {"kimi-k3": "Kimi K3", "claude-opus-5-5": "Claude Opus 5.5", "gpt-6-1-sol": "GPT-6.1 Sol"}


def norm(model):
    m = (model or "").lower().replace(" ", "-").replace(".", "-")
    return next((v for k, v in ALIAS.items() if k in m), model)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--mode", default="task"); ap.add_argument("--video", default="harness-tutorial")
    a = ap.parse_args()
    for line in (pathlib.Path(__file__).resolve().parent.parent / ".env").read_text().splitlines() if (pathlib.Path(__file__).resolve().parent.parent / ".env").exists() else []:
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
    w = WorkspaceClient(profile=os.environ.get("DATABRICKS_CONFIG_PROFILE"))
    sql = f"""
      SELECT request_tags['harness'] AS harness, request_tags['tier'] AS tier, request_tags['run'] AS run, destination_model AS model,
             count(*) AS calls, sum(input_tokens) AS prompt, coalesce(sum(token_details.cache_read_input_tokens), 0) AS cache_read,
             coalesce(sum(token_details.cache_creation_input_tokens), 0) AS cache_write, sum(output_tokens) AS output
      FROM system.ai_gateway.usage
      WHERE request_tags['video'] = '{a.video}' AND request_tags['mode'] = '{a.mode}'
      GROUP BY ALL ORDER BY tier, harness, run"""
    r = w.statement_execution.execute_statement(warehouse_id=os.environ["WAREHOUSE_ID"], statement=sql, wait_timeout="50s")
    rows = r.result.data_array or [] if r.result else []
    if not rows:
        print("no rows yet: the usage table can lag by a few minutes after a run"); return
    print(f"{'run':<26}{'model':<18}{'calls':>6}{'prompt':>10}{'cached':>9}{'output':>8}{'cost':>9}")
    agg = {}
    for h, tier, run, model, calls, prompt, cr, cw, out in rows:
        calls, prompt, cr, cw, out = (int(x or 0) for x in (calls, prompt, cr, cw, out))
        m = norm(model); p = PRICE.get(m, (0, 0, 0, 0)); new = prompt - cr - cw
        cost = (new * p[0] + cr * p[1] + cw * p[2] + out * p[3]) / 1e6
        print(f"{run:<26}{m:<18}{calls:>6}{prompt:>10,}{cr:>9,}{out:>8,}{cost:>9.3f}")
        agg.setdefault((tier, h, m), []).append((cost, prompt, cr, calls))
    print(f"\n{'harness':<10}{'model':<18}{'runs':>5}{'avg calls':>11}{'cache share':>13}{'avg cost':>10}")
    for (tier, h, m), xs in sorted(agg.items()):
        n = len(xs); share = sum(x[2] for x in xs) / max(1, sum(x[1] for x in xs))
        print(f"{h:<10}{m:<18}{n:>5}{sum(x[3] for x in xs) / n:>11.1f}{share:>12.0%}{sum(x[0] for x in xs) / n:>10.3f}")


if __name__ == "__main__":
    main()
