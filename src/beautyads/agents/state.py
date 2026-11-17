"""Checkpoint-safe state: only dictionaries, lists, and JSON scalar values."""

from typing import TypedDict


class AgentState(TypedDict):
    messages: list[dict]
    tenant_id: str
    thread_id: str
    final_text: str
    tool_trace: list[dict]
    step_count: int
    # Server-resolved dates are ISO strings, never datetime/pydantic objects.
    as_of: str
    last_collected_at: str | None
