"""Synthetic timelines and injected clients; no environment file or service."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from beautyads.obs.langfuse_sink import build_timeline, export_trace
from beautyads.obs.trace import TraceRecord, build_trace
from beautyads.settings import LangfuseSettings, langfuse_settings

START = datetime(2026, 11, 20, tzinfo=UTC)
PRIVATE = "SYNTHETIC_PRIVATE_BODY"


def at(seconds):
    return START + timedelta(seconds=seconds)


def timeline_record():
    return TraceRecord(
        trace_id="a" * 32,
        tenant_id="synthetic",
        started_at=START,
        duration_ms=10000,
        outcome="ok",
        kind="plan",
        intent="plan",
        message_chars=0,
        cost_total_usd=0.02,
        text_spent_usd=0.02,
        prompt_versions={"planning": "2026-11-20-1"},
        steps=[
            {"agent": agent, "phase": phase, "status": "ok", "at": at(t)}
            for agent, phase, t in [
                ("supervisor", "end", 1),
                ("research", "end", 3),
                ("planning", "start", 4),
                ("evaluation", "end", 8),
            ]
        ],
        calls=[
            {
                "purpose": purpose,
                "model": "synthetic-model",
                "reasoning_effort": "low",
                "input_tokens": 11,
                "output_tokens": 7,
                "cached_tokens": cache,
                "thought_tokens": 2,
                "cost_usd": cost,
                "cost_source": "price_table",
                "duration_ms": duration,
                "ended_at": at(end),
            }
            for purpose, cache, cost, duration, end in [
                ("research", 3, 0.02, 1000, 2),
                ("planning", 0, 0, 2000, 7),
            ]
        ],
    )


def configured():
    # Synthetic configuration never reaches an SDK client in these tests.
    return LangfuseSettings(
        public_key="synthetic-public", secret_key="synthetic-secret"
    )


@pytest.mark.parametrize("key", ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"])
@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_or_blank_keys_disable_sink(key, value):
    env = {"LANGFUSE_PUBLIC_KEY": "synthetic", "LANGFUSE_SECRET_KEY": "synthetic"}
    env.pop(key)
    if value is not None:
        env[key] = value
    assert langfuse_settings(environ=env, env_file=None) is None


@pytest.mark.parametrize("host", [None, "", " \t", "http://synthetic.invalid"])
def test_settings_host_default_and_safe_representation(host):
    env = {
        "LANGFUSE_PUBLIC_KEY": "synthetic-public",
        "LANGFUSE_SECRET_KEY": "synthetic-secret",
    }
    if host is not None:
        env["LANGFUSE_HOST"] = host
    settings = langfuse_settings(environ=env, env_file=None)
    assert settings.host == (host if host and host.strip() else "http://127.0.0.1:3001")
    assert all(value not in repr(settings) for value in env.values() if value.strip())


def test_timeline_boundaries_smallest_parent_and_deterministic_ids():
    record = timeline_record()
    timeline = build_timeline(record)
    assert timeline and timeline == build_timeline(record)
    spans = {row["name"]: row for row in timeline if row["kind"] == "span"}
    assert set(spans) == {"ask", "supervisor", "research", "plan"}
    for name, start, end in [
        ("ask", 0, 10),
        ("supervisor", 0, 1),
        ("research", 1, 3),
        ("plan", 4, 8),
    ]:
        assert (spans[name]["start"], spans[name]["end"]) == (at(start), at(end))
    generations = [row for row in timeline if row["kind"] == "generation"]
    assert len(generations) == 2
    for row, start, end, parent in zip(
        generations, [1, 5], [2, 7], ["research", "plan"], strict=True
    ):
        assert (row["start"], row["end"]) == (at(start), at(end))
        assert row["parent_id"] == spans[parent]["id"]
    assert len({row["id"] for row in timeline}) == len(timeline)
    for row in timeline:
        assert row["start"] <= row["end"]
        assert row["parent_id"] is None or row["parent_id"] in {
            item["id"] for item in timeline
        }


def test_multiple_plans_rework_image_and_done():
    record = timeline_record()
    step = type(record.steps[0])
    record.steps.extend(
        [
            step(agent="rework", phase="end", status="ok", at=at(8)),
            step(agent="planning", phase="start", status="ok", at=at(8)),
            step(agent="evaluation", phase="end", status="ok", at=at(9)),
            step(agent="image", phase="end", status="ok", at=at(10)),
            step(agent="supervisor", phase="done", status="ok", at=at(10)),
        ]
    )
    timeline = build_timeline(record)
    plans = [row for row in timeline if row["name"] == "plan"]
    assert [(row["start"], row["end"]) for row in plans] == [
        (at(4), at(8)),
        (at(8), at(9)),
    ]
    rework = [row for row in timeline if row["kind"] == "event"]
    assert len(rework) == 1 and rework[0]["start"] == at(8)
    image = next(row for row in timeline if row["name"] == "image")
    assert (image["start"], image["end"]) == (at(9), at(10))
    assert len([row for row in timeline if row["name"] == "supervisor"]) == 1


def test_legacy_and_partially_timed_calls_do_not_invent_times():
    record = timeline_record()
    for step in record.steps:
        step.at = None
    for call in record.calls:
        call.duration_ms = call.ended_at = None
    timeline = build_timeline(record)
    assert timeline
    assert all(row["start"] is row["end"] is None for row in timeline)
    record = timeline_record()
    record.calls[0].duration_ms = None
    record.calls[1].ended_at = None
    generations = [row for row in build_timeline(record) if row["kind"] == "generation"]
    assert len(generations) == 2
    assert all(row["start"] is row["end"] is None for row in generations)
    assert all(
        row["parent_id"] == build_timeline(record)[0]["id"] for row in generations
    )


def test_generation_attrs_always_include_ledger_cost_and_only_metadata():
    record = timeline_record()
    attrs = [
        row["attrs"] for row in build_timeline(record) if row["kind"] == "generation"
    ]
    assert len(attrs) == len(record.calls) == 2
    for values, call in zip(attrs, record.calls, strict=True):
        assert values["cost_details"] == {"total": call.cost_usd}
        assert values["model"] == call.model
        assert values["metadata"] == {
            "purpose": call.purpose,
            "reasoning_effort": "low",
            "cost_source": "price_table",
            "thought_tokens": 2,
        }
        assert values["usage_details"] == {
            "input": 11,
            "output": 7,
            "total": 18,
            **({"cache_read_input_tokens": 3} if call.cached_tokens else {}),
        }
        assert not {"input", "output", "prompt", "messages"} & values.keys()
    stripped = build_trace(
        tenant_id="synthetic",
        started_at=START,
        duration_ms=0,
        message=PRIVATE,
        result={"kind": "plan", "answer": PRIVATE},
        failure=None,
        ledger_entries=[],
        structured={},
    )
    assert PRIVATE not in str(build_timeline(stripped))


class FakeClient:
    def __init__(self, *, fail=False, errors=None):
        self.calls = []
        self.fail, self.errors = fail, errors or []
        self.api = SimpleNamespace(ingestion=SimpleNamespace(batch=self.batch))

    def batch(self, *, batch):
        self.calls.append(batch)
        if self.fail:
            raise RuntimeError(PRIVATE)
        return SimpleNamespace(errors=self.errors)


def test_disabled_export_never_constructs_client():
    def forbidden(**kwargs):
        pytest.fail("disabled export constructed a client")

    assert (
        export_trace(timeline_record(), settings=None, client_factory=forbidden)
        is False
    )


def test_export_single_typed_batch_and_payload():
    client, options = FakeClient(), []

    def factory(**kwargs):
        options.append(kwargs)
        return client

    record = timeline_record()
    record.steps.append(
        type(record.steps[0])(agent="rework", phase="end", status="ok", at=at(8))
    )
    assert export_trace(record, settings=configured(), client_factory=factory) is True
    assert len(client.calls) == 1
    assert options == [
        {
            "public_key": configured().public_key,
            "secret_key": configured().secret_key,
            "host": configured().host,
            "tracing_enabled": False,
            "timeout": 3,
        }
    ]
    batch = client.calls[0]
    assert {event.type for event in batch} == {
        "trace-create",
        "span-create",
        "generation-create",
        "event-create",
    }
    wire = [event.dict(by_alias=True, exclude_unset=True) for event in batch]
    trace = next(event["body"] for event in wire if event["type"] == "trace-create")
    assert trace == {
        "id": record.trace_id,
        "name": "ask",
        "userId": record.tenant_id,
        "timestamp": START,
        "tags": ["kind:plan", "outcome:ok"],
        "metadata": {
            "kind": "plan",
            "intent": "plan",
            "outcome": "ok",
            "cost_total_usd": 0.02,
            "text_spent_usd": 0.02,
            "limit_hit": False,
            "prompt_versions": {"planning": "2026-11-20-1"},
        },
    }
    for event in wire:
        assert not {"input", "output", "sessionId"} & event["body"].keys()
        if event["type"] == "generation-create":
            assert event["body"]["costDetails"]["total"] in {0, 0.02}
            assert event["body"]["startTime"] < event["body"]["endTime"]
    first_ids = [event.body.id for event in batch]
    assert export_trace(record, settings=configured(), client_factory=factory)
    assert first_ids == [event.body.id for event in client.calls[1]]
    assert {event.id for event in batch}.isdisjoint(
        event.id for event in client.calls[1]
    )
    assert PRIVATE not in json.dumps(wire, default=str)


@pytest.mark.parametrize("failure", ["construct", "batch", "response"])
def test_export_swallows_failures_without_diagnostics(failure, capsys, caplog):
    def factory(**kwargs):
        if failure == "construct":
            raise RuntimeError(PRIVATE)
        return FakeClient(
            fail=failure == "batch",
            errors=[{"message": PRIVATE}] if failure == "response" else [],
        )

    assert (
        export_trace(timeline_record(), settings=configured(), client_factory=factory)
        is False
    )
    assert PRIVATE not in caplog.text + str(capsys.readouterr())


def test_check_preflight_reports_only_missing_names(capsys):
    from beautyads.obs.langfuse_check import OBS_REQUIRED_ENV, main

    assert main(["preflight"], environ={}, env_file=None) == 2
    lines = capsys.readouterr().out.splitlines()
    assert set(lines) == {
        f"PREFLIGHT_FAILED OBS_ENV_MISSING:{name}" for name in OBS_REQUIRED_ENV
    }
    assert (
        main(
            ["preflight"],
            environ=dict.fromkeys(OBS_REQUIRED_ENV, PRIVATE),
            env_file=None,
        )
        == 0
    )
    assert PRIVATE not in str(capsys.readouterr())


@pytest.mark.parametrize("mode", ["ok", "missing", "parent", "cost", "time", "error"])
def test_check_polls_and_validates_readback_with_fake_sdk(mode, capsys):
    from beautyads.obs.langfuse_check import main

    client = FakeClient()
    reads = []

    def get(trace_id, **kwargs):
        reads.append(trace_id)
        if mode == "error":
            raise RuntimeError(PRIVATE)
        observations = []
        for event in client.calls[0]:
            if event.type == "trace-create":
                continue
            body = event.body
            observations.append(
                {
                    "id": body.id,
                    "type": "GENERATION"
                    if event.type == "generation-create"
                    else "SPAN",
                    "name": body.name,
                    "startTime": body.start_time,
                    "endTime": body.end_time,
                    "latency": (body.end_time - body.start_time).total_seconds(),
                    "costDetails": getattr(body, "cost_details", {}),
                    "parentObservationId": body.parent_observation_id,
                }
            )
        if mode == "missing":
            observations.pop()
        elif mode == "parent":
            observations[-1]["parentObservationId"] = "wrong"
        elif mode == "cost":
            observations[-1]["costDetails"] = {}
        elif mode == "time":
            observations[-1]["startTime"] = None
        return {"observations": observations}

    client.api.trace = SimpleNamespace(get=get)
    ticks = iter([0, 0, 16])
    code = main(
        [],
        environ={"LANGFUSE_PUBLIC_KEY": PRIVATE, "LANGFUSE_SECRET_KEY": PRIVATE},
        env_file=None,
        client_factory=lambda **kwargs: client,
        clock=lambda: next(ticks),
        sleep_fn=lambda seconds: None,
    )
    assert code == (0 if mode == "ok" else 3)
    assert len(client.calls) == 1 and reads
    output = capsys.readouterr().out
    assert PRIVATE not in output and "127.0.0.1" not in output
    if mode == "ok":
        assert "OBS_CHECK_OK" in output
        assert (
            "startTime" in output
            and "endTime" in output
            and "latency" in output
            and "costDetails" in output
            and "parent" in output
        )
