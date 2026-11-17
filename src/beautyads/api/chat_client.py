"""One in-process request, with lifespan entered and exited by TestClient."""

import json
from dataclasses import dataclass

from fastapi.testclient import TestClient


@dataclass(frozen=True)
class ChatOutcome:
    events: list[tuple[str, dict]]
    final_text: str
    status_code: int


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    name = None
    data = []
    for line in [*text.splitlines(), ""]:
        if not line:
            if name and data:
                value = json.loads("\n".join(data))
                if isinstance(value, dict):
                    events.append((name, value))
            name, data = None, []
        elif line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    return events


def run_chat_once(app, *, tenant_id, message, thread_id=None) -> ChatOutcome:
    body = {"message": message}
    if thread_id is not None:
        body["thread_id"] = thread_id
    with TestClient(app) as client:
        response = client.post("/chat", headers={"X-Tenant-Id": tenant_id}, json=body)
        events = parse_sse(response.text) if response.status_code == 200 else []
        final_text = "".join(
            body.get("text", "") for name, body in events if name == "token"
        )
        return ChatOutcome(events, final_text, response.status_code)
