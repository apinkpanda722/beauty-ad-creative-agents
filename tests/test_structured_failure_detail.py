"""Synthetic failures check instrumentation, not the cause of live Sonnet failures."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from threading import Barrier
from unittest.mock import Mock

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from beautyads.domain.evaluation import EvaluationScores
from beautyads.eval.agents_live import _structured
from beautyads.llm import structured
from beautyads.llm.chat import ChatResult, ToolCall
from beautyads.llm.structured import (
    InstructionJsonStructured,
    StructuredSpec,
    ToolCallStructured,
)
from beautyads.obs.trace import append_trace, build_trace, summarize_by_tenant

SECRET = "SYNTHETIC-SECRET-invalid-value"
GOOD = {"differentiation": 3, "fit": 3, "rationale": ""}


def evaluation_spec():
    return StructuredSpec(
        "evaluation_scores",
        "Synthetic validation only.",
        EvaluationScores.model_json_schema(),
        EvaluationScores.model_validate,
    )


def response(value=None, *, text=None, tool=True):
    return ChatResult(
        text,
        [ToolCall("synthetic", "evaluation_scores", value, None)] if tool else [],
        "stop",
        {},
        0.01,
        "price_table",
        {},
    )


def generate(adapter, spec, tmp_path):
    return adapter.generate(
        spec,
        messages=[{"role": "user", "content": "synthetic"}],
        purpose="synthetic-detail",
        ledger_path=tmp_path / "costs.jsonl",
        caps={},
        reasoning_effort=None,
    )


@pytest.mark.parametrize(
    "invalid,path,kind",
    [
        ({**GOOD, "rationale": SECRET * 10}, "rationale", "string_too_long"),
        ({**GOOD, "differentiation": 6}, "differentiation", "less_than_equal"),
        ({**GOOD, "differentiation": 0}, "differentiation", "greater_than_equal"),
        ({**GOOD, "differentiation": SECRET}, "differentiation", "int_type"),
        ({k: v for k, v in GOOD.items() if k != "fit"}, "fit", "missing"),
        ({**GOOD, "unknown": SECRET}, "unknown", "extra_forbidden"),
    ],
)
def test_synthetic_evaluation_errors_separate_paths_and_types_not_live_causes(
    monkeypatch, tmp_path, invalid, path, kind
):
    fn = Mock(side_effect=[response(invalid), response(GOOD)])
    monkeypatch.setattr(structured, "chat_complete", fn)
    adapter = ToolCallStructured("claude-sonnet-5-5")
    result = generate(adapter, evaluation_spec(), tmp_path)
    assert result.ok and result.attempts == 2
    assert adapter.stats.first_attempt_failure_details == {
        f"evaluation_scores|{path}|{kind}": 1
    }
    # FP-C14: inspect what the second fake model call actually receives.
    retry = fn.call_args_list[1].kwargs["messages"][-1]
    assert retry["role"] == "user"
    assert (
        f"Previous submission failed: SCHEMA_VIOLATION ({path}: {kind}). "
        "Correct it and submit again."
    ) in retry["content"]
    assert SECRET not in retry["content"] + repr(adapter.stats)
    record = build_trace(
        tenant_id="synthetic",
        started_at=datetime(2026, 11, 18, tzinfo=UTC),
        duration_ms=1,
        message="synthetic",
        result=None,
        failure=None,
        ledger_entries=[],
        structured={
            adapter.model: {
                "calls": adapter.stats.calls,
                "first_attempt_failure_details": adapter.stats.first_attempt_failure_details,
            }
        },
    )
    trace_path = tmp_path / "trace.jsonl"
    append_trace(trace_path, record)
    assert SECRET not in trace_path.read_text() + json.dumps(
        [summarize_by_tenant([record]), _structured([record])]
    )


@pytest.mark.parametrize("mode", ["parse", "tool", "not_object", "arguments"])
def test_nonvalidation_failures_are_counted_without_output_values(
    monkeypatch, tmp_path, mode
):
    if mode in {"parse", "not_object"}:
        adapter = InstructionJsonStructured("claude-sonnet-5-5")
        first = response(text=SECRET if mode == "parse" else "[]", tool=False)
        second = response(text=json.dumps(GOOD), tool=False)
        detail = "parse_failed" if mode == "parse" else "not_object"
    else:
        adapter = ToolCallStructured("claude-sonnet-5-5")
        first = response(tool=False) if mode == "tool" else response()
        second = response(GOOD)
        detail = "tool_not_called" if mode == "tool" else "parse_failed"
    fn = Mock(side_effect=[first, second])
    monkeypatch.setattr(structured, "chat_complete", fn)
    assert generate(adapter, evaluation_spec(), tmp_path).ok
    assert adapter.stats.first_attempt_failure_details == {
        f"evaluation_scores|-|{detail}": 1
    }
    retry = fn.call_args.kwargs["messages"][-1]["content"]
    if detail == "parse_failed":
        assert retry.startswith(
            "Previous submission failed: PARSE_FAILED. Correct it and submit again."
        )
    assert SECRET not in retry + repr(adapter.stats)


def test_only_first_attempt_details_count_even_when_second_failure_differs(
    monkeypatch, tmp_path
):
    fn = Mock(
        side_effect=[response({**GOOD, "fit": SECRET}), response({"unknown": SECRET})]
    )
    monkeypatch.setattr(structured, "chat_complete", fn)
    adapter = ToolCallStructured("claude-sonnet-5-5")
    result = generate(adapter, evaluation_spec(), tmp_path)
    assert not result.ok and result.attempts == 2
    assert adapter.stats.first_attempt_failure_details == {
        "evaluation_scores|fit|int_type": 1
    }
    assert adapter.stats.calls == adapter.stats.failed_after_retry == 1


def test_details_record_only_when_generate_completes(monkeypatch, tmp_path):
    def interrupted(**kwargs):
        if len(kwargs["messages"]) > 2:
            raise RuntimeError(SECRET)
        return response({**GOOD, "fit": SECRET})

    monkeypatch.setattr(structured, "chat_complete", interrupted)
    adapter = ToolCallStructured("claude-sonnet-5-5")
    with pytest.raises(RuntimeError):
        generate(adapter, evaluation_spec(), tmp_path)
    assert adapter.stats.calls == 0
    assert adapter.stats.first_attempt_failure_details == {}


def test_nested_indices_root_locations_sanitization_and_error_limits(
    monkeypatch, tmp_path
):
    class Nested(BaseModel):
        model_config = ConfigDict(extra="forbid")
        items: list[int] = Field(strict=True)

    spec = StructuredSpec("bad /name", "synthetic", {}, Nested.model_validate)
    invalid = {"items": [SECRET] * 7}
    fn = Mock(
        side_effect=[response(text=json.dumps(invalid)), response(text='{"items":[]}')]
    )
    monkeypatch.setattr(structured, "chat_complete", fn)
    adapter = InstructionJsonStructured("claude-sonnet-5-5")
    assert generate(adapter, spec, tmp_path).ok
    assert adapter.stats.first_attempt_failure_details == {
        "bad__name|items.*|int_parsing": 5
    }
    retry = fn.call_args.kwargs["messages"][-1]["content"]
    assert retry.count("items.*: int_parsing") == 3
    assert SECRET not in retry + repr(adapter.stats)

    # Locations and types only: a root error and an unusually long field alias.
    error = ValidationError.from_exception_data(
        "synthetic",
        [
            {"type": "missing", "loc": (), "input": SECRET},
            {"type": "int_type", "loc": ("bad /" + "x" * 160,), "input": SECRET},
        ],
    )

    def validate(value):
        raise error

    spec = StructuredSpec("evaluation_scores", "synthetic", {}, validate)
    fn = Mock(return_value=response({}))
    monkeypatch.setattr(structured, "chat_complete", fn)
    adapter = ToolCallStructured("claude-sonnet-5-5")
    assert not generate(adapter, spec, tmp_path).ok
    details = adapter.stats.first_attempt_failure_details
    assert details["evaluation_scores|-|missing"] == 1
    long_key = next(key for key in details if "bad" in key)
    assert long_key.startswith("evaluation_scores|bad__") and len(long_key) == 120
    assert all(re.fullmatch(r"[A-Za-z0-9_.*:|-]{1,120}", key) for key in details)
    assert SECRET not in repr(details) + repr(fn.call_args_list)


def test_nonpydantic_validator_exception_never_copies_message(monkeypatch, tmp_path):
    def validate(value):
        raise ValueError(SECRET)

    spec = StructuredSpec("evaluation_scores", "synthetic", {}, validate)
    fn = Mock(return_value=response({}))
    monkeypatch.setattr(structured, "chat_complete", fn)
    adapter = ToolCallStructured("claude-sonnet-5-5")
    assert not generate(adapter, spec, tmp_path).ok
    assert adapter.stats.first_attempt_failure_details == {
        "evaluation_scores|-|exception:ValueError": 1
    }
    assert SECRET not in repr(adapter.stats) + repr(fn.call_args_list)


def test_parallel_requests_keep_retry_details_local(monkeypatch, tmp_path):
    barrier = Barrier(2)
    messages = []

    def complete(**kwargs):
        request = kwargs["messages"]
        field = request[1]["content"]
        if len(request) == 2:
            barrier.wait(timeout=5)
            return response({**GOOD, field: SECRET})
        messages.append((field, deepcopy(request[-1])))
        return response(GOOD)

    monkeypatch.setattr(structured, "chat_complete", complete)
    adapter = ToolCallStructured("claude-sonnet-5-5")

    def run(field):
        return adapter.generate(
            evaluation_spec(),
            messages=[{"role": "user", "content": field}],
            purpose="synthetic",
            ledger_path=tmp_path / "costs.jsonl",
            caps={},
            reasoning_effort=None,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ("fit", "differentiation")))
    assert all(result.ok and result.attempts == 2 for result in results)
    for field, message in messages:
        assert f"({field}: int_type)" in message["content"]
        assert SECRET not in message["content"]
