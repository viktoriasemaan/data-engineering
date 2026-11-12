"""Memory helpers on top of the Databricks AgentKit SDK.

Three kinds of state, each in its own Lakebase-backed store:

- Session store (AGENT_SESSION_STORE): LangGraph checkpoints for one conversation, so a conversation
  survives restarts. Handled by `databricks_agentkit.langgraph.checkpointer()`; no code here.
- Memory store (AGENT_MEMORY_STORE): durable facts about the user, shared across all conversations.
  The agent reads and writes it through `memory_tools(actor)`: remember, recall, forget, list_memories.
- Transcript store (AGENT_TRANSCRIPT_STORE): plain user and assistant messages, one session per
  conversation. Memory pipelines read these (they skip tool calls and LangGraph checkpoints).
"""
import os
from typing import Optional

from databricks_agentkit import AgentKitClient, workspace_client

_client: Optional[AgentKitClient] = None


def client() -> AgentKitClient:
    global _client
    if _client is None:
        _client = AgentKitClient(workspace_client())
    return _client


def memory_index(actor: str) -> Optional[str]:
    """The index loaded into the prompt at session start: which memory files exist for this user.

    Only the paths and fact counts, not the facts themselves. The agent calls `recall` for the content.
    Returns None when no memory store is configured.
    """
    store = os.getenv("AGENT_MEMORY_STORE")
    if not store:
        return None
    memories = list(client().memory_stores._handle(store).list(actor_id=actor, page_size=100))
    if not memories:
        return "(empty: nothing remembered yet)"
    lines = []
    for m in sorted(memories, key=lambda m: m.path):
        n = sum(1 for line in (m.content or "").splitlines() if line.strip())
        lines.append(f"{m.path} ({n} fact{'' if n == 1 else 's'})")
    return "\n".join(lines)


class Transcript:
    """Appends each finished turn (user text, assistant text) to the transcript session store."""

    def __init__(self, actor: str, session_id: str):
        self.store_name = os.getenv("AGENT_TRANSCRIPT_STORE")
        self.actor, self.session_id, self._session = actor, session_id, None

    @property
    def enabled(self) -> bool:
        return bool(self.store_name)

    def _get(self):
        if self._session is None:
            store = client().session_stores.get(self.store_name)
            try:
                self._session = store.get(self.session_id)
            except Exception:
                self._session = store.add(actor_id=self.actor, session_id=self.session_id)
        return self._session

    def append(self, user: str, assistant: str) -> None:
        if self.enabled:
            self._get().append_items([
                {"type": "message", "role": "user", "content": user},
                {"type": "message", "role": "assistant", "content": assistant},
            ])
