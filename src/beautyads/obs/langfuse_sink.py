"""Optional metadata-only export of completed JSONL traces via public ingestion."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypedDict
from uuid import NAMESPACE_URL, uuid4, uuid5

from langfuse import Langfuse
from langfuse.api import (
    CreateEventBody,
    CreateGenerationBody,
    CreateSpanBody,
    TraceBody,
)
from langfuse.api.resources.ingestion.types.ingestion_event import (
    IngestionEvent_EventCreate,
    IngestionEvent_GenerationCreate,
    IngestionEvent_SpanCreate,
    IngestionEvent_TraceCreate,
)

from beautyads.obs.trace import TraceRecord
from beautyads.settings import LangfuseSettings


class Observation(TypedDict):
    id: str
    kind: Literal["span", "generation", "event"]
    name: str
    start: datetime | None
    end: datetime | None
    parent_id: str | None
    attrs: dict[str, Any]


def build_timeline(record: TraceRecord) -> list[Observation]:
    """Project recorded boundaries only; legacy observations remain untimed."""
    observations: list[Observation] = []
    intervals = [
        (
            call.ended_at - timedelta(milliseconds=call.duration_ms),
            call.ended_at,
        )
        if call.duration_ms is not None and call.ended_at is not None
        else (None, None)
        for call in record.calls
    ]
    timed = any(step.at is not None for step in record.steps) or any(
        start is not None for start, _ in intervals
    )

    def add(kind, name, start, end, parent_id, attrs=None):
        observation: Observation = {
            "id": str(len(observations)),
            "kind": kind,
            "name": name,
            "start": start,
            "end": end,
            "parent_id": parent_id,
            "attrs": attrs or {},
        }
        observations.append(observation)
        return observation

    root = add(
        "span",
        "ask",
        record.started_at if timed else None,
        record.started_at + timedelta(milliseconds=record.duration_ms)
        if timed
        else None,
        None,
        {
            "metadata": {
                "rework_count": sum(step.agent == "rework" for step in record.steps)
            }
        },
    )
    previous = record.started_at
    for name in ("supervisor", "research"):
        end = next(
            (
                step.at
                for step in record.steps
                if step.agent == name and step.phase == "end" and step.at is not None
            ),
            None,
        )
        if previous is not None and end is not None and previous <= end:
            add("span", name, previous, end, root["id"])
        previous = end

    image_count = sum(
        call.purpose.startswith("image") and start is not None
        for call, (start, _) in zip(record.calls, intervals, strict=True)
    )
    counts = {"planning": 0, "evaluation": 0, "image": 0}
    call_stages = {}
    for index, (call, (start, end)) in enumerate(
        zip(record.calls, intervals, strict=True)
    ):
        if start is None:
            continue
        name = {"plan": "planning", "evaluate": "evaluation"}.get(call.purpose)
        if call.purpose.startswith("image"):
            name = "image"
        if name is not None:
            counts[name] += 1
            label = (
                name
                if name == "image" and image_count == 1
                else f"{name} #{counts[name]}"
            )
            call_stages[index] = add("span", label, start, end, root["id"])

    if not any(call.purpose.startswith("image") for call in record.calls):
        for step in record.steps:
            if step.agent == "image" and step.status == "failed":
                add("event", "image_failed", None, None, root["id"])

    stages = [row for row in observations if row["kind"] == "span" and row is not root]
    for index, (call, (start, end)) in enumerate(
        zip(record.calls, intervals, strict=True)
    ):
        parent = root
        if start is not None:
            containing = [
                row
                for row in stages
                if row["start"] is not None
                and row["end"] is not None
                and row["start"] <= start
                and end <= row["end"]
            ]
            if containing:
                parent = min(
                    containing,
                    key=lambda row: (
                        row["end"] - row["start"],
                        not row["name"].startswith(("planning", "evaluation", "image")),
                        row is not call_stages.get(index),
                    ),
                )
        usage = {
            "input": call.input_tokens,
            "output": call.output_tokens,
            "total": call.input_tokens + call.output_tokens,
        }
        if call.cached_tokens:
            usage["cache_read_input_tokens"] = call.cached_tokens
        add(
            "generation",
            call.purpose,
            start,
            end,
            parent["id"],
            {
                "model": call.model,
                "usage_details": usage,
                "cost_details": {"total": call.cost_usd},
                "metadata": {
                    "purpose": call.purpose,
                    "reasoning_effort": call.reasoning_effort,
                    "cost_source": call.cost_source,
                    "thought_tokens": call.thought_tokens,
                },
            },
        )
    # Assign UUID5 ordinals only after ordering spans and their generations.
    ordered = [
        root,
        *sorted(
            observations[1:],
            key=lambda row: (row["start"] is None, row["start"], row["kind"] != "span"),
        ),
    ]
    ids = {
        row["id"]: uuid5(NAMESPACE_URL, f"{record.trace_id}:{index}").hex
        for index, row in enumerate(ordered)
    }
    for row in ordered:
        row["id"] = ids[row["id"]]
        if row["parent_id"] is not None:
            row["parent_id"] = ids[row["parent_id"]]
    return ordered


def export_trace(
    record: TraceRecord,
    *,
    settings: LangfuseSettings | None,
    client_factory=Langfuse,
) -> bool:
    """Send one batch; failures never expose diagnostics or affect JSONL/results."""
    if settings is None:
        return False
    try:
        client = client_factory(
            public_key=settings.public_key,
            secret_key=settings.secret_key,
            host=settings.host,
            tracing_enabled=False,
            timeout=3,
        )
        timestamp = datetime.now(UTC).isoformat()
        batch = [
            IngestionEvent_TraceCreate(
                type="trace-create",
                id=str(uuid4()),
                timestamp=timestamp,
                body=TraceBody(
                    id=record.trace_id,
                    name="ask",
                    user_id=record.tenant_id,
                    timestamp=record.started_at,
                    tags=[f"kind:{record.kind}", f"outcome:{record.outcome}"],
                    metadata={
                        "kind": record.kind,
                        "intent": record.intent,
                        "outcome": record.outcome,
                        "cost_total_usd": record.cost_total_usd,
                        "text_spent_usd": record.text_spent_usd,
                        "limit_hit": record.limit_hit,
                        "prompt_versions": record.prompt_versions,
                    },
                ),
            )
        ]
        event_types = {
            "span": (IngestionEvent_SpanCreate, CreateSpanBody),
            "generation": (IngestionEvent_GenerationCreate, CreateGenerationBody),
            "event": (IngestionEvent_EventCreate, CreateEventBody),
        }
        for observation in build_timeline(record):
            event_type, body_type = event_types[observation["kind"]]
            body = {
                "id": observation["id"],
                "trace_id": record.trace_id,
                "name": observation["name"],
                "start_time": observation["start"],
                "parent_observation_id": observation["parent_id"],
                **observation["attrs"],
            }
            if observation["kind"] != "event":
                body["end_time"] = observation["end"]
            batch.append(
                event_type(
                    type=f"{observation['kind']}-create",
                    id=str(uuid4()),
                    timestamp=timestamp,
                    body=body_type(**body),
                )
            )
        response = client.api.ingestion.batch(batch=batch)
        errors = (
            response.get("errors")
            if isinstance(response, dict)
            else getattr(response, "errors", None)
        )
        return errors == []
    except Exception:  # noqa: BLE001 -- SDK diagnostics may contain secrets
        return False
