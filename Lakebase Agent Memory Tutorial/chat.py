#!/usr/bin/env python3
"""Chat with the Bean & Byte assistant in the terminal.

    python chat.py --user maya --session mon-1            interactive
    python chat.py --user maya --session tue-1 --ask "How did my store do last week?"

Every tool call is printed as it happens (▸), and each turn ends with its cost:
tool calls, input tokens sent to the model, and seconds.
"""
import argparse
import json
import os
import pathlib
import sys
import time
import warnings

warnings.filterwarnings("ignore")
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.markdown import Markdown  # noqa: E402
from rich.padding import Padding  # noqa: E402

from databricks_agentkit.langgraph import thread_config  # noqa: E402
from databricks_agentkit.langgraph.messages import message_items  # noqa: E402

from agent.agent import build_agent  # noqa: E402
from agent.memory import Transcript, memory_index  # noqa: E402

con = Console(width=min(Console().width, 84), highlight=False)


def short(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def show_call(call: dict) -> None:
    name, args = call["name"], call.get("args", {})
    if name == "run_sql":
        detail = short(args.get("query", ""), 64)
    elif name == "remember":
        detail = f"\"{short(args.get('fact', ''), 48)}\"  [dim]→ {args.get('topic', '')}[/]"
    elif name in ("recall",):
        detail = f"\"{short(args.get('query', ''), 56)}\""
    elif name == "forget":
        detail = f"\"{short(args.get('fact', ''), 52)}\""
    else:
        detail = ", ".join(f"{v}" for v in args.values())
    con.print(f"  [bold yellow]▸ {name}[/] [white]{detail}[/]")


def show_result(msg: ToolMessage) -> None:
    text = str(msg.content)
    if msg.name == "run_sql":
        n = max(0, len(text.splitlines()) - 1)
        summary = text if text.startswith("SQL error") else f"{n} row{'' if n == 1 else 's'}"
    elif msg.name == "recall":
        facts = [line.strip() for line in text.splitlines() if line.startswith("  ")]
        summary = f"{len(facts)} facts: " + short("; ".join(facts), 60) if facts else text
    else:
        summary = text.splitlines()[0] if text else ""
    con.print(f"    [dim]↳ {short(summary, 74)}[/]")


def header(user: str, session: str) -> tuple[str | None, int]:
    ss, ms = os.getenv("AGENT_SESSION_STORE"), os.getenv("AGENT_MEMORY_STORE")
    con.print(f"[bold]Bean & Byte assistant[/]  [dim]·[/]  user [cyan]{user}[/]  [dim]·[/]  session [cyan]{session}[/]")
    con.print(f"  [dim]sessions[/]  " + (f"[green]session store[/] {ss} [dim](Lakebase)[/]" if ss else "[dim]this process only[/]"))
    index = memory_index(user)
    if ms:
        n = 0 if index.startswith("(empty") else len(index.splitlines())
        ro = " · [yellow]read-only[/]" if os.getenv("AGENT_MEMORY_WRITES") == "pipeline" else ""
        con.print(f"  [dim]memory  [/]  [green]memory store[/] {ms} [dim](Lakebase)[/] · {n} file{'' if n == 1 else 's'}{ro}")
        for line in index.splitlines():
            con.print(f"            [dim]{line}[/]")
    else:
        con.print("  [dim]memory    off[/]")
    con.print()
    return index, 0


def text_of(msg: AIMessage) -> str:
    """The answer text of a model reply, without Claude's reasoning blocks."""
    content = message_items(msg)[-1].get("content")
    if isinstance(content, list):
        content = "".join(b if isinstance(b, str) else b.get("text") or "" for b in content
                          if isinstance(b, str) or b.get("type") == "text")
    return (content or "").strip()


def turn(agent, config, text: str, log: list) -> str:
    t0, calls, tok_in, tok_out, answer, pending = time.time(), 0, 0, 0, "", {}
    for update in agent.stream({"messages": [{"role": "user", "content": text}]}, config, stream_mode="updates"):
        for node in update.values():
            for msg in (node or {}).get("messages", []):
                if isinstance(msg, AIMessage):
                    u = msg.usage_metadata or {}
                    tok_in += u.get("input_tokens", 0)
                    tok_out += u.get("output_tokens", 0)
                    said = text_of(msg)
                    if msg.tool_calls:
                        calls += len(msg.tool_calls)
                        pending.update({c["id"]: c for c in msg.tool_calls})
                    elif said:
                        answer = said
                elif isinstance(msg, ToolMessage):
                    show_call(pending.pop(msg.tool_call_id, {"name": msg.name, "args": {}}))
                    show_result(msg)
    secs = time.time() - t0
    con.print(Padding(Markdown(answer or "(no answer)"), (1, 2, 0, 2)))
    con.print(f"  [dim]{calls} tool call{'' if calls == 1 else 's'} · {tok_in:,} tokens in · {secs:.1f} s[/]\n")
    log.append({"user": text, "answer": answer, "tool_calls": calls, "tokens_in": tok_in, "tokens_out": tok_out, "seconds": round(secs, 1)})
    return answer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="maya", help="the actor whose memory is used (trusted, not from the model)")
    ap.add_argument("--session", required=True, help="conversation id")
    ap.add_argument("--ask", action="append", help="send this message and exit (repeatable)")
    a = ap.parse_args()

    index, _ = header(a.user, a.session)
    agent = build_agent(a.user, index if os.getenv("AGENT_MEMORY_STORE") else None)
    config = thread_config(a.session, a.user)
    transcript, log = Transcript(a.user, a.session), []
    try:
        for text in a.ask or iter(lambda: con.input("[bold cyan]you ›[/] "), None):
            if a.ask:
                con.print(f"[bold cyan]you ›[/] {text}")
            if text.strip().lower() in ("exit", "quit"):
                break
            if text.strip():
                transcript.append(text, turn(agent, config, text, log))
    except (EOFError, KeyboardInterrupt):
        con.print()
    finally:
        runs = ROOT / "runs"
        runs.mkdir(exist_ok=True)
        with open(runs / f"{a.session}.jsonl", "a") as f:
            for row in log:
                f.write(json.dumps({"session": a.session, "user_id": a.user,
                                    "sessions": os.getenv("AGENT_SESSION_STORE"), "memory": os.getenv("AGENT_MEMORY_STORE"), **row}) + "\n")


if __name__ == "__main__":
    main()
