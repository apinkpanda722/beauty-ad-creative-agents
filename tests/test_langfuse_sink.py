"""Synthetic timelines and injected clients; no environment file or service."""

import json
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

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
                ("evaluation", "end", 10),
                ("rework", "end", 10),
                ("image", "end", 10),
                ("supervisor", "done", 10),
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
                ("supervisor", 0, 0, 1000, 1),
                ("research", 3, 0.02, 2000, 3),
                ("plan", 0, 0, 1000, 5),
                ("evaluate", 0, 0, 1000, 6),
                ("plan", 0, 0, 1000, 7),
                ("evaluate", 0, 0, 1000, 8),
                ("image-plan", 0, 0, 2000, 10),
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
    boundaries = [
        ("ask", 0, 10),
        ("supervisor", 0, 1),
        ("research", 1, 3),
        ("planning #1", 4, 5),
        ("evaluation #1", 5, 6),
        ("planning #2", 6, 7),
        ("evaluation #2", 7, 8),
        ("image", 8, 10),
    ]
    assert list(spans) == [name for name, _, _ in boundaries]
    for name, start, end in boundaries:
        assert (spans[name]["start"], spans[name]["end"]) == (at(start), at(end))
        assert spans[name]["parent_id"] == (
            None if name == "ask" else spans["ask"]["id"]
        )
    stages = list(spans.values())[1:]
    assert all(left["end"] <= right["start"] for left, right in pairwise(stages))
    generations = [row for row in timeline if row["kind"] == "generation"]
    assert len(generations) == len(record.calls) == 7
    for row, call, stage in zip(generations, record.calls, stages, strict=True):
        assert row["name"] == call.purpose
        assert (row["start"], row["end"]) == (stage["start"], stage["end"])
        assert row["parent_id"] == stage["id"]
    assert generations[-1]["parent_id"] == spans["image"]["id"]
    assert spans["image"]["end"] - spans["image"]["start"] == timedelta(
        milliseconds=2000
    )
    assert not [row for row in timeline if row["kind"] == "event"]
    assert spans["ask"]["attrs"]["metadata"]["rework_count"] == 1
    assert [row["name"] for row in timeline] == [
        "ask",
        "supervisor",
        "supervisor",
        "research",
        "research",
        "planning #1",
        "plan",
        "evaluation #1",
        "evaluate",
        "planning #2",
        "plan",
        "evaluation #2",
        "evaluate",
        "image",
        "image-plan",
    ]
    assert len({row["id"] for row in timeline}) == len(timeline)
    for index, row in enumerate(timeline):
        assert row["id"] == uuid5(NAMESPACE_URL, f"{record.trace_id}:{index}").hex
        assert row["start"] <= row["end"]
        assert row["parent_id"] is None or row["parent_id"] in {
            item["id"] for item in timeline
        }


def test_multiple_plans_rework_image_and_done():
    record = timeline_record()
    step = type(record.steps[0])
    record.steps = [item for item in record.steps if item.agent != "rework"]
    record.steps.insert(3, step(agent="evaluation", phase="end", status="ok", at=at(6)))
    record.steps.insert(4, step(agent="planning", phase="start", status="ok", at=at(6)))
    timeline = build_timeline(record)
    attempts = [
        row for row in timeline if row["kind"] == "span" and " #" in row["name"]
    ]
    assert [(row["name"], row["start"], row["end"]) for row in attempts] == [
        ("planning #1", at(4), at(5)),
        ("evaluation #1", at(5), at(6)),
        ("planning #2", at(6), at(7)),
        ("evaluation #2", at(7), at(8)),
    ]
    assert not [row for row in timeline if row["kind"] == "event"]
    assert timeline[0]["attrs"]["metadata"]["rework_count"] == 0
    image = next(row for row in timeline if row["name"] == "image")
    assert (image["start"], image["end"]) == (at(8), at(10))
    assert (
        len(
            [
                row
                for row in timeline
                if row["kind"] == "span" and row["name"] == "supervisor"
            ]
        )
        == 1
    )


@pytest.mark.parametrize(
    "index, name", [(2, "planning #1"), (3, "evaluation #1"), (6, "image")]
)
def test_call_span_wins_equal_interval_parent_tie(index, name):
    record = timeline_record()
    record.calls[index].duration_ms = 2000
    record.calls[index].ended_at = at(3)
    timeline = build_timeline(record)
    stage = next(row for row in timeline if row["name"] == name)
    generation = next(
        row
        for row in timeline
        if row["kind"] == "generation" and row["name"] == record.calls[index].purpose
    )
    assert (stage["start"], stage["end"]) == (at(1), at(3))
    assert generation["parent_id"] == stage["id"]


def test_multiple_image_calls_have_numbered_spans():
    record = timeline_record()
    record.calls.append(record.calls[-1].model_copy(update={"duration_ms": 0}))
    timeline = build_timeline(record)
    images = [
        row
        for row in timeline
        if row["kind"] == "span" and row["name"].startswith("image")
    ]
    assert [(row["name"], row["start"], row["end"]) for row in images] == [
        ("image #1", at(8), at(10)),
        ("image #2", at(10), at(10)),
    ]
    generations = [
        row
        for row in timeline
        if row["kind"] == "generation" and row["name"] == "image-plan"
    ]
    assert [row["parent_id"] for row in generations] == [row["id"] for row in images]


def test_calls_use_smallest_containing_stage_or_root():
    record = timeline_record()
    record.calls[1].duration_ms = 1000
    record.calls[1].ended_at = at(2)
    record.calls.append(
        record.calls[1].model_copy(
            update={
                "purpose": "other",
                "duration_ms": 500,
                "ended_at": at(4),
            }
        )
    )
    timeline = build_timeline(record)
    spans = {row["name"]: row for row in timeline if row["kind"] == "span"}
    generations = {row["name"]: row for row in timeline if row["kind"] == "generation"}
    assert (generations["research"]["start"], generations["research"]["end"]) == (
        at(1),
        at(2),
    )
    assert generations["research"]["parent_id"] == spans["research"]["id"]
    assert (generations["other"]["start"], generations["other"]["end"]) == (
        at(3.5),
        at(4),
    )
    assert generations["other"]["parent_id"] == spans["ask"]["id"]


def test_missing_image_call_only_emits_untimed_failure_event():
    record = timeline_record()
    record.calls.pop()
    next(step for step in record.steps if step.agent == "image").status = "failed"
    timeline = build_timeline(record)
    events = [row for row in timeline if row["kind"] == "event"]
    assert len(events) == 1
    assert events[0] == {
        "id": uuid5(NAMESPACE_URL, f"{record.trace_id}:{len(timeline) - 1}").hex,
        "kind": "event",
        "name": "image_failed",
        "start": None,
        "end": None,
        "parent_id": timeline[0]["id"],
        "attrs": {},
    }
    assert not [
        row
        for row in timeline
        if row["kind"] == "span" and row["name"].startswith("image")
    ]
    record.calls.append(timeline_record().calls[-1])
    assert not [row for row in build_timeline(record) if row["kind"] == "event"]


def test_timed_calls_without_step_timestamps_keep_their_recorded_intervals():
    record = timeline_record()
    for step in record.steps:
        step.at = None
    timeline = build_timeline(record)
    spans = {row["name"]: row for row in timeline if row["kind"] == "span"}
    assert list(spans) == [
        "ask",
        "planning #1",
        "evaluation #1",
        "planning #2",
        "evaluation #2",
        "image",
    ]
    assert (spans["ask"]["start"], spans["ask"]["end"]) == (at(0), at(10))
    generations = [row for row in timeline if row["kind"] == "generation"]
    assert len(generations) == 7
    for generation, call in zip(generations, record.calls, strict=True):
        assert generation["end"] == call.ended_at
        assert generation["start"] == call.ended_at - timedelta(
            milliseconds=call.duration_ms
        )
    assert [row["parent_id"] for row in generations[:2]] == [spans["ask"]["id"]] * 2


def test_legacy_and_partially_timed_calls_do_not_invent_times():
    record = timeline_record()
    for step in record.steps:
        step.at = None
    for call in record.calls:
        call.duration_ms = call.ended_at = None
    timeline = build_timeline(record)
    assert timeline
    assert all(row["start"] is row["end"] is None for row in timeline)
    assert [(row["kind"], row["name"]) for row in timeline] == [
        ("span", "ask"),
        *[("generation", call.purpose) for call in record.calls],
    ]
    assert all(row["parent_id"] == timeline[0]["id"] for row in timeline[1:])
    record = timeline_record()
    for index, call in enumerate(record.calls):
        if index % 2:
            call.ended_at = None
        else:
            call.duration_ms = None
    timeline = build_timeline(record)
    assert [row["name"] for row in timeline if row["kind"] == "span"] == [
        "ask",
        "supervisor",
        "research",
    ]
    generations = [row for row in timeline if row["kind"] == "generation"]
    assert len(generations) == 7
    assert all(row["start"] is row["end"] is None for row in generations)
    assert all(
        row["parent_id"] == build_timeline(record)[0]["id"] for row in generations
    )


def test_generation_attrs_always_include_ledger_cost_and_only_metadata():
    record = timeline_record()
    attrs = [
        row["attrs"] for row in build_timeline(record) if row["kind"] == "generation"
    ]
    assert len(attrs) == len(record.calls) == 7
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
    record.calls.pop()
    next(step for step in record.steps if step.agent == "image").status = "failed"
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
    root = next(
        event["body"]
        for event in wire
        if event["type"] == "span-create" and event["body"]["name"] == "ask"
    )
    assert root["metadata"] == {"rework_count": 2}
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


@pytest.mark.parametrize(
    "mode", ["ok", "missing", "parent", "cost", "time", "name", "error"]
)
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
        elif mode == "name":
            next(row for row in observations if row["name"] == "planning #1")[
                "name"
            ] = "wrong"
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
            "span_names=ok ask, supervisor, research, planning #1, evaluation #1, planning #2, evaluation #2, image"
            in output.splitlines()
        )
        assert (
            "startTime" in output
            and "endTime" in output
            and "latency" in output
            and "costDetails" in output
            and "parent" in output
        )


def test_check_readback_rejects_empty_expectations():
    from beautyads.obs.langfuse_check import _readback_matches

    assert _readback_matches({"observations": []}, []) is False


@pytest.mark.parametrize(
    "value, expected",
    [(None, True), ("", True), (" \t", True), ("1", True), ("0", False)],
)
def test_io_setting_defaults_and_switch(value, expected):
    env = {"LANGFUSE_PUBLIC_KEY": "synthetic", "LANGFUSE_SECRET_KEY": "synthetic"}
    if value is not None:
        env["BEAUTYADS_LANGFUSE_IO"] = value
    assert langfuse_settings(environ=env, env_file=None).capture_io is expected


@pytest.mark.parametrize("value", ["true", "false", "2", "SYNTHETIC_PRIVATE_SETTING"])
def test_invalid_io_setting_never_exposes_value(value):
    from beautyads.settings import InvalidSetting

    env = {
        "LANGFUSE_PUBLIC_KEY": "synthetic",
        "LANGFUSE_SECRET_KEY": "synthetic",
        "BEAUTYADS_LANGFUSE_IO": value,
    }
    with pytest.raises(InvalidSetting) as caught:
        langfuse_settings(environ=env, env_file=None)
    assert str(caught.value) == "BEAUTYADS_LANGFUSE_IO"
    assert value not in str(caught.value)
    assert (
        langfuse_settings(environ={"BEAUTYADS_LANGFUSE_IO": value}, env_file=None)
        is None
    )


def io_batch(record, io, settings):
    client = FakeClient()
    assert export_trace(
        record, settings=settings, io=io, client_factory=lambda **kw: client
    )
    return [
        event.dict(by_alias=True, exclude_unset=True)["body"]
        for event in client.calls[0]
    ]


def test_none_or_disabled_io_preserves_exact_previous_batch():
    from test_langfuse_io import synthetic_io

    record = timeline_record()
    baseline = io_batch(record, None, configured())
    assert all("input" not in body and "output" not in body for body in baseline)
    assert (
        io_batch(
            record,
            synthetic_io(),
            configured().model_copy(update={"capture_io": False}),
        )
        == baseline
    )
    assert build_timeline(record, None) == build_timeline(record)


def test_enabled_io_sanitizes_root_stages_generations_and_keys():
    from dataclasses import replace

    from test_langfuse_io import synthetic_io

    from beautyads.obs.langfuse_io import Capture

    record = timeline_record()
    secret = "sk-" + "synthetic_" * 3
    payload = secret + " 한국어 " + "가" * 4100
    io = replace(
        synthetic_io(),
        message=payload,
        captures=tuple(
            Capture(call.purpose, call.ended_at, payload, payload)
            for call in record.calls
        ),
    )
    io.result["plans"][0]["plan"]["title"] = payload
    # Also sanitize dictionary keys in model-authored data.
    io.result["plans"][0]["plan"]["copy_lines"] = ["data:image/png;base64,c3ludGhldGlj"]
    bodies = io_batch(record, io, configured())
    assert bodies[0]["input"]["요청"].startswith("[가림] 한국어")
    spans = {
        body["name"]: body
        for body in bodies[1:]
        if body["name"]
        in {
            "ask",
            "supervisor",
            "research",
            "planning #1",
            "planning #2",
            "evaluation #1",
            "evaluation #2",
            "image",
        }
    }
    assert "input" in spans["ask"] and "output" in spans["ask"]
    assert "output" in spans["supervisor"] and "output" in spans["research"]
    assert "output" not in spans["planning #1"]
    assert "output" in spans["planning #2"] and "output" in spans["evaluation #1"]
    assert "input" in spans["image"]
    generations = [body for body in bodies if "model" in body]
    assert len(generations) == len(record.calls)
    assert all(
        body["input"].startswith("[가림]") and body["output"].endswith("(생략됨)")
        for body in generations
    )

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    assert all(len(text) <= 4000 for text in strings(bodies))
    serialized = json.dumps(bodies, default=str, ensure_ascii=False)
    assert secret not in serialized and "c3ludGhldGlj" not in serialized
    assert "rationale" not in json.dumps(spans, default=str)


def test_io_export_failure_never_emits_diagnostics(capsys, caplog):
    from test_langfuse_io import synthetic_io

    assert (
        export_trace(
            timeline_record(),
            settings=configured(),
            io=synthetic_io(),
            client_factory=lambda **kw: FakeClient(fail=True),
        )
        is False
    )
    assert PRIVATE not in caplog.text + str(capsys.readouterr())


def test_stage_inputs_attach_to_batch_and_pass_existing_sanitization():
    from dataclasses import replace

    from test_langfuse_io import synthetic_io

    from beautyads.obs.langfuse_io import Capture

    secret = "sk-" + "synthetic_" * 3
    payload = secret + " 한국어 " + "가" * 4100
    io = replace(
        synthetic_io(),
        captures=(Capture("image-plan", at(10), payload, "합성 출력"),),
    )
    io.result["brief"]["goal"] = payload
    io.result["brief"]["angle"] = payload
    io.result["claim_choice"]["requested_claim"] = payload
    io.result["plans"][0]["attempts"][0]["failed_check_codes"] = [payload]
    io.result["plans"][0]["plan"]["title"] = payload
    io.result["plans"][0]["plan"]["image_brief"] = payload
    io.result["plans"][0]["efficacy_status"] = {secret: payload}
    bodies = io_batch(timeline_record(), io, configured())
    spans = {
        body["name"]: body
        for body in bodies
        if "startTime" in body and "model" not in body
    }
    clipped = (
        "[가림] 한국어 "
        + "가" * (4000 - len("[가림] 한국어 \n(생략됨)"))
        + "\n(생략됨)"
    )
    assert spans["research"]["input"] == {
        "목표": clipped,
        "카테고리": "serum_ampoule",
        "효능": "hydration",
        "훅 유형": "question",
        "소구": clipped,
        "형식": "demo",
        "피부 고민": "dryness",
        "산출 형식": "both",
    }
    assert spans["planning #1"]["input"] == {
        "소구": clipped,
        "요청 효능": "hydration",
        "효능 선택": {
            "mode": "select",
            "claims": ["hydration"],
            "requested_claim": clipped,
        },
        "확인된 효능": ["hydration"],
        "근거 소재 수": 2,
    }
    assert spans["evaluation #1"]["input"] == {
        "코드 검사": {"통과": True, "실패 코드": [clipped]},
    }
    assert spans["evaluation #2"]["input"]["기획안"]["제목"] == clipped
    assert spans["evaluation #2"]["input"]["효능 상태"] == {"[가림]": clipped}
    assert spans["image"]["input"] == {"장면 묘사": clipped, "이미지 프롬프트": clipped}

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    assert all(len(text) <= 4000 for text in strings(bodies))
    wire = json.dumps(bodies, default=str, ensure_ascii=False)
    assert all(
        value not in wire
        for value in (secret, "SYNTHETIC_NOT_ALLOWED", "rationale", "unknown")
    )


@pytest.mark.parametrize("with_io,capture_io", [(False, True), (True, False)])
def test_disabled_stage_inputs_never_project_io(monkeypatch, with_io, capture_io):
    from test_langfuse_io import synthetic_io

    def forbidden(io):
        pytest.fail("disabled IO projected stage inputs")

    monkeypatch.setattr("beautyads.obs.langfuse_sink.stage_io", forbidden)
    bodies = io_batch(
        timeline_record(),
        synthetic_io() if with_io else None,
        configured().model_copy(update={"capture_io": capture_io}),
    )
    assert all("input" not in body and "output" not in body for body in bodies)


def test_io_sanitizes_even_metadata_strings_and_leaves_unmatched_calls_empty():
    from dataclasses import replace

    from test_langfuse_io import synthetic_io

    from beautyads.obs.langfuse_io import Capture

    record = timeline_record()
    secret = "sk-" + "synthetic_" * 3
    record.tenant_id = secret
    record.calls[0].model = secret
    io = replace(synthetic_io(), captures=(Capture("evaluate", at(6), secret, secret),))
    bodies = io_batch(record, io, configured())
    assert secret not in json.dumps(bodies, default=str)
    generations = [body for body in bodies if "model" in body]
    assert [body["name"] for body in generations if "input" in body] == ["evaluate"]
    assert sum("input" not in body for body in generations) == len(record.calls) - 1
