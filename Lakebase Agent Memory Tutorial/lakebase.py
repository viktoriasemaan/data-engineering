#!/usr/bin/env python3
"""Look under the hood: the Postgres tables in Lakebase behind the memory and session stores.

    python lakebase.py memories --user maya      the memory store's rows (one per memory file)
    python lakebase.py sessions                  the session store's conversations and item counts
    python lakebase.py sql "<select ...>"        any read-only query on the memory store's database

Read-only. Each store is its own Postgres database on a Lakebase branch; this connects as you with a
short-lived OAuth credential. The table layout is an internal detail of the managed stores and can
change, so build on the SDK, not on these tables.
"""
import argparse
import os
import pathlib
import warnings

warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parent
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
import psycopg  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from databricks_agentkit import AgentKitClient, workspace_client  # noqa: E402

con = Console(width=min(Console().width, 86), highlight=False)
w = workspace_client()


def connect(database_path: str):
    """database_path: projects/<project>/branches/<branch>/databases/<db>"""
    branch, db = database_path.split("/databases/")
    ep = next(iter(w.postgres.list_endpoints(parent=branch)))
    cred = w.postgres.generate_database_credential(endpoint=ep.name)
    con.print(f"[dim]Lakebase project[/]  {branch.split('/')[1]}  [dim]branch[/] {branch.split('/')[-1]}")
    con.print(f"[dim]database        [/]  [green]{db}[/]\n")
    return psycopg.connect(host=ep.status.hosts.host, dbname=db, user=w.current_user.me().user_name,
                           password=cred.token, sslmode="require", options="-c default_transaction_read_only=on")


def memory_db() -> str:
    store = AgentKitClient(w).memory_stores.get(os.environ["AGENT_MEMORY_STORE"])
    return store.storage_backend["backend_id"]


def session_db() -> str:
    return memory_db().rsplit("/databases/", 1)[0] + "/databases/session-" + os.environ["AGENT_SESSION_STORE"]


def show(cur, title: str) -> None:
    t = Table(title=title, title_justify="left", header_style="bold", show_lines=False, pad_edge=False)
    for d in cur.description:
        t.add_column(d.name, no_wrap=True, overflow="ellipsis")
    for row in cur.fetchall():
        t.add_row(*["" if v is None else " ".join(str(v).split()) for v in row])
    con.print(t)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["memories", "sessions", "sql"])
    ap.add_argument("query", nargs="?")
    ap.add_argument("--user", default="maya")
    a = ap.parse_args()
    if a.what == "memories":
        with connect(memory_db()) as c:
            show(c.execute("""SELECT path, CASE WHEN source_type LIKE '%%DREAMER' OR session_id IS NOT NULL THEN 'dreamer' ELSE 'agent' END AS last_written_by,
                                     coalesce(session_id, '-') AS session,
                                     length(content) AS chars,
                                     content_vector IS NOT NULL AS embedding,
                                     content_tsvector IS NOT NULL AS keyword_index
                              FROM memory.memory_entries WHERE actor_id = %s ORDER BY create_time_ms""", (a.user,)),
                 "memory.memory_entries")
    elif a.what == "sessions":
        with connect(session_db()) as c:
            show(c.execute("""SELECT s.session_id, s.actor_id, count(i.item_id) AS items
                              FROM sessions s LEFT JOIN session_items i USING (session_id)
                              GROUP BY 1, 2 ORDER BY max(i.create_time)"""), "sessions + session_items")
    else:
        with connect(memory_db()) as c:
            show(c.execute(a.query), "result")


if __name__ == "__main__":
    main()
