"""One-line JSON SSE frames. UI commands are reserved for a later step."""

import json
from typing import Literal

EventName = Literal["step", "tool_start", "token", "ui_command", "error"]


def encode_event(name: EventName, body: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"
