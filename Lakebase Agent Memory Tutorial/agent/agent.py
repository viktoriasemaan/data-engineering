"""The Bean & Byte ops assistant: a LangGraph agent with optional sessions and long-term memory.

The code is the same at every stage of the demo. What changes is the environment:

    (nothing set)              no memory: history lives in this process only
    AGENT_SESSION_STORE=...    + sessions: each conversation is saved to a Lakebase-backed session store
    AGENT_MEMORY_STORE=...     + memory: facts about the user persist across all conversations
    AGENT_MEMORY_WRITES=pipeline   the agent only reads memory; a memory pipeline writes it later
"""
import os
from typing import Optional

from databricks_langchain import ChatDatabricks
from databricks_agentkit.langgraph import checkpointer, memory_tools
from databricks_agentkit.langgraph.messages import gateway_messages
from langchain.agents import create_agent
from langchain_core.tools import StructuredTool

from agent.tools import DATA_TOOLS

MODEL = "system.ai.claude-sonnet-5-5"


class Model(ChatDatabricks):
    """ChatDatabricks that sends Claude 5.x reasoning blocks back on the next call (as the
    agentbricks template does), so multi-step tool use keeps each reasoning signature."""

    def _prepare_inputs(self, messages, *args, **kwargs):
        return super()._prepare_inputs(gateway_messages(messages), *args, **kwargs)

BASE_PROMPT = """You are the Bean & Byte ops assistant. Bean & Byte is a coffee chain in New York.
You help store managers answer questions about their store from the point-of-sale database.
Today is Thursday, November 12, 2026. Weeks run Monday to Sunday, so last week is Nov 2 to Nov 8.
Look things up with the database tools. Never guess a number. Keep answers brief."""

MEMORY_PROMPT = """
You have long-term memory about this user. It persists across conversations.
- Before you explore the database or ask the user something, call recall once, with one broad
  query for everything you need: their store, how their team defines the metric, a query recipe,
  and how they like answers.
- If memory has a recipe for the task, follow it directly instead of exploring the schema again.
- If the user says something that contradicts a memory, the user wins: use what they just said.
{writes}
Memory index for this user (loaded at session start):
{index}"""

WRITE_PROMPT = """- When the user tells you something durable (who they are, their store, a definition, a preference),
  call remember right away, one fact per call.
- When the user confirms a query is right, remember the recipe under topic "workflows", written so it
  works for any store: keep the store itself in the user's profile, not in the recipe.
- If a new fact replaces a remembered one, forget the old fact, then remember the new one.
"""

READ_ONLY_PROMPT = """- You can read memory but not write it. A memory pipeline updates it from your conversations later.
"""


def _safe(tool):
    """Hand a failed memory call back to the model as text instead of ending the chat."""
    def run(**kwargs):
        try:
            return tool.invoke(kwargs)
        except Exception as e:  # e.g. an entry that another call just removed
            return f"{tool.name} failed: {e}"
    return StructuredTool.from_function(func=run, name=tool.name, description=tool.description,
                                        args_schema=tool.args_schema)


def memory_prompt(index: str) -> str:
    pipeline = os.getenv("AGENT_MEMORY_WRITES") == "pipeline"
    return MEMORY_PROMPT.format(index=index, writes=READ_ONLY_PROMPT if pipeline else WRITE_PROMPT)


def build_agent(actor: str, index: Optional[str] = None):
    """actor: the signed-in user whose memory is used. Never from the model."""
    memory = [_safe(t) for t in memory_tools(actor)]   # [] if no memory store
    if os.getenv("AGENT_MEMORY_WRITES") == "pipeline":  # read-only memory
        memory = [t for t in memory if t.name in ("recall", "list_memories")]
    prompt = BASE_PROMPT + f"\nThe signed-in user is {actor!r}."
    if index is not None:                       # memory index, loaded at start
        prompt += memory_prompt(index)
    return create_agent(
        model=Model(endpoint=MODEL, use_ai_gateway=True),
        tools=[*DATA_TOOLS, *memory],
        system_prompt=prompt,
        checkpointer=checkpointer(),            # session store, when set
    )
