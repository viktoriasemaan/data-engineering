#!/usr/bin/env python3
"""Show what the session store saved for one conversation: every message, tool call and result.

    python history.py --user maya --session mon-1

Reads the LangGraph checkpoints back from the session store (AGENT_SESSION_STORE) with the SDK's
read_history helper, the same data the agent reloads when the conversation continues.
"""
import argparse
import asyncio
import os
import pathlib
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
ROOT = pathlib.Path(__file__).resolve().parent
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from rich.console import Console  # noqa: E402

from databricks_agentkit.langgraph import read_history  # noqa: E402

con = Console(width=min(Console().width, 86), highlight=False)
KIND = {"human": ("user", "cyan"), "ai": ("assistant", "white"), "tool": ("tool result", "dim")}


def one_line(text, n=58):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="maya")
    ap.add_argument("--session", required=True)
    a = ap.parse_args()
    store = os.getenv("AGENT_SESSION_STORE")
    if not store:
        sys.exit("AGENT_SESSION_STORE is not set: history only lives inside the running process.")
    items = asyncio.run(read_history(a.session, a.user))["session_items"]
    con.print(f"[bold]session {a.session}[/]  [dim]·[/]  session store [green]{store}[/] [dim](Lakebase)[/]\n")
    counts = {}
    for item in items:
        d = item["data"]
        kind = d.get("type")
        if kind == "ai" and d.get("tool_calls"):
            for c in d["tool_calls"]:
                detail = c["args"].get("query") or c["args"].get("fact") or ", ".join(map(str, c["args"].values()))
                con.print(f"  [yellow]tool call  [/]  {c['name']} [dim]{one_line(detail, 46)}[/]")
                counts["tool calls"] = counts.get("tool calls", 0) + 1
            continue
        if kind not in KIND or not isinstance(d.get("content"), str) or not d["content"].strip():
            continue
        label, color = KIND[kind]
        con.print(f"  [{color}]{label:<11}[/]  [{color}]{one_line(d['content'])}[/]")
        counts[label] = counts.get(label, 0) + 1
    con.print("\n  [dim]" + " · ".join(f"{v} {k}" for k, v in counts.items()) + "[/]")


if __name__ == "__main__":
    main()
