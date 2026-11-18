"""One in-process request, with lifespan entered and exited by TestClient."""

import json
from dataclasses import dataclass

from fastapi.testclient import TestClient


@dataclass(frozen=True)
class ChatOutcome:
    events: list[tuple[str, dict]]
    final_text: str
    status_code: int
    detail: str | None = None
    error_code: str | None = None


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
        error = next((body for name, body in events if name == "error"), {})
        return ChatOutcome(
            events,
            final_text,
            response.status_code,
            detail=error.get("detail"),
            error_code=error.get("error_code"),
        )


@dataclass(frozen=True)
class AskOutcome:
    events: list[tuple[str, dict]]
    ui_commands: list[dict]
    final_text: str
    status_code: int


def run_ask_once(
    app, *, tenant_id, message, with_image=False, thread_id=None
) -> AskOutcome:
    body = {"message": message, "with_image": with_image}
    if thread_id is not None:
        body["thread_id"] = thread_id
    with TestClient(app) as client:
        response = client.post("/ask", headers={"X-Tenant-Id": tenant_id}, json=body)
        events = parse_sse(response.text) if response.status_code == 200 else []
        return AskOutcome(
            events=events,
            ui_commands=[body for name, body in events if name == "ui_command"],
            final_text="".join(
                body.get("text", "") for name, body in events if name == "token"
            ),
            status_code=response.status_code,
        )
