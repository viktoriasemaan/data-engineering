"""What the agent can look up: the Bean & Byte point-of-sale database (read-only SQLite)."""
import pathlib
import sqlite3

from langchain_core.tools import tool

DB = pathlib.Path(__file__).resolve().parent.parent / "data" / "bean_byte.db"
MAX_ROWS = 50


def _query(sql: str, params: tuple = ()) -> tuple[list[str], list[tuple]]:
    if not DB.exists():                                       # first run: build the sample data (about 2 s)
        import importlib.util
        spec = importlib.util.spec_from_file_location("make_data", DB.parent / "make_data.py")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); mod.main()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)   # read-only: the agent can't change the data
    try:
        cur = con.execute(sql, params)
        cols = [d[0] for d in cur.description or []]
        return cols, cur.fetchmany(MAX_ROWS)
    finally:
        con.close()


def _table(cols: list[str], rows: list[tuple]) -> str:
    out = [" | ".join(cols)] + [" | ".join(str(v) for v in r) for r in rows]
    return "\n".join(out) if rows else " | ".join(cols) + "\n(no rows)"


@tool
def list_tables() -> str:
    """List the tables in the Bean & Byte point-of-sale database."""
    _, rows = _query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return ", ".join(r[0] for r in rows)


@tool
def describe_table(table: str) -> str:
    """Show a table's columns and three sample rows.

    Args:
        table: The table name, as returned by list_tables.
    """
    names = {r[0] for r in _query("SELECT name FROM sqlite_master WHERE type='table'")[1]}
    if table not in names:
        return f"No table named {table!r}. Tables: {', '.join(sorted(names))}"
    cols = [f"{r[1]} {r[2]}" for r in _query(f"PRAGMA table_info({table})")[1]]
    c, rows = _query(f"SELECT * FROM {table} LIMIT 3")
    return f"columns: {', '.join(cols)}\nsample rows:\n{_table(c, rows)}"


@tool
def run_sql(query: str) -> str:
    """Run one read-only SQLite SELECT query and return up to 50 rows.

    Args:
        query: A single SQLite SELECT statement.
    """
    try:
        return _table(*_query(query))
    except sqlite3.Error as e:
        return f"SQL error: {e}"


DATA_TOOLS = [list_tables, describe_table, run_sql]
