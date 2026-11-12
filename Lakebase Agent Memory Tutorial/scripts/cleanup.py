#!/usr/bin/env python3
"""Delete everything the walkthrough created: memory pipelines, the memory store, and the session stores.

    python scripts/cleanup.py                 # stores and pipelines named bean-byte-*
    python scripts/cleanup.py --prefix my-    # a different prefix
Deleting a session store does not delete memories already distilled from it; this deletes both.
"""
import argparse
import pathlib

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env")
from databricks_agentkit import AgentKitClient, workspace_client  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--prefix", default="bean-byte")
prefix = ap.parse_args().prefix
ak = AgentKitClient(workspace_client())
api = ak.session_stores._api

pipes, token = [], None
while True:
    page = api.list_memory_pipelines(page_size=100, page_token=token)
    pipes += page.get("memory_pipelines", [])
    token = page.get("next_page_token")
    if not token:
        break
for p in pipes:
    if p.get("memory_store", "").startswith(f"memory-stores/{prefix}"):
        api.delete_memory_pipeline(p["name"])
        print("deleted memory pipeline", p["name"])
for m in ak.memory_stores.list():
    if m.id.startswith(prefix):
        m.delete()
        print("deleted memory store", m.id)
for s in ak.session_stores.list():
    if s.name.startswith(prefix):
        for session in s.list():
            session.delete(force=True)
        s.delete()
        print("deleted session store", s.name)
