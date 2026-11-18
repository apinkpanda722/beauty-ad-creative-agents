"""Structured adapters validate shapes using offline calls and measured envelopes."""

import asyncio
import inspect
import json
import threading
import traceback
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from beautyads.llm import (
    ChatResult,
    CostCapExceeded,
    DailyLimitReached,
    ErrorKind,
    InstructionJsonStructured,
    JsonSchemaStructured,
    LlmCallError,
    NativeAnthropicStructured,
    PriceUnknown,
    StructuredFailure,
    StructuredResult,
    StructuredSpec,
    StructuredStats,
    ToolCall,
    ToolCallStructured,
    make_structured,
    structured,
)
from beautyads.obs import LedgerEntry, append_entry, read_entries

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
STAMP = datetime(2026, 11, 17, tzinfo=UTC)
ANTHROPIC = "claude-sonnet-5-5"
OPENAI = "gpt-6-luna"
ADAPTERS = (
    ToolCallStructured,
    InstructionJsonStructured,
    JsonSchemaStructured,
    NativeAnthropicStructured,
)


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: int


@pytest.fixture
def spec():
    return StructuredSpec(
        name="answer",
        description="Submit a synthetic integer payload.",
        schema=Payload.model_json_schema(),
        validate=Payload.model_validate,
    )


@pytest.fixture
def args(tmp_path):
    return {
        "messages": [{"role": "user", "content": "synthetic request"}],
        "purpose": "structured-test",
        "ledger_path": tmp_path / "costs.jsonl",
        "caps": {"openai": 10.0, "anthropic": 8.0},
        "reasoning_effort": None,
        "api_key": uuid4().hex,
        "now": lambda: STAMP,
    }


def load(filename):
    return json.loads((FIXTURES / filename).read_text(encoding="utf-8"))


def measured_chat(name):
    return deepcopy(load("litellm_p5_sonnet_structured.json").get(name).get("raw"))


def native_response():
    measured = load("litellm_p5_sonnet_native.json").get("b2_native_acreate")
    input_tokens, output_tokens = measured.get("tokens")
    return {
        "content": deepcopy(measured.get("content_blocks")),
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "stop_reason": measured.get("stop_reason"),
    }


def chat_result(text=None, calls=None):
    return ChatResult(text, calls or [], "stop", {}, 0.01, "price_table", {})


def tool_payload(arguments=None, error=None, name="answer"):
    return chat_result(calls=[ToolCall("synthetic-id", name, arguments, error)])


def setup_adapter(cls, args):
    model = OPENAI if cls is JsonSchemaStructured else ANTHROPIC
    args["reasoning_effort"] = "low" if cls is JsonSchemaStructured else None
    return cls(model)


def inject_results(monkeypatch, cls, outputs):
    if cls is NativeAnthropicStructured:
        responses = []
        for output in outputs:
            if isinstance(output, Exception):
                responses.append(output)
            else:
                responses.append(
                    {
                        "content": [{"type": "text", "text": output.text}],
                        "usage": {"input_tokens": 10, "output_tokens": 5},
                    }
                )
        fn = AsyncMock(side_effect=responses)
        monkeypatch.setattr(structured.litellm.anthropic.messages, "acreate", fn)
    else:
        fn = Mock(side_effect=outputs)
        monkeypatch.setattr(structured, "chat_complete", fn)
    return fn


@pytest.mark.parametrize("cls", ADAPTERS)
def test_success_uses_validator_return_and_preserves_messages(
    args, spec, cls, monkeypatch
):
    adapter = setup_adapter(cls, args)
    good = (
        tool_payload({"value": 7})
        if cls is ToolCallStructured
        else chat_result('{"value":7}')
    )
    fn = inject_results(monkeypatch, cls, [good])
    original = deepcopy(args.get("messages"))
    result = adapter.generate(spec, **args)
    assert isinstance(result, StructuredResult)
    assert result.ok and isinstance(result.value, Payload)
    assert result.attempts == 1 and result.failure is None
    assert len(result.calls) == 1 and result.cost_usd > 0
    assert result.cost_usd == sum(call.cost_usd for call in result.calls)
    assert args.get("messages") == original
    assert fn.call_count == 1
    assert adapter.stats.calls == 1 and adapter.stats.failure_rate == 0.0
    assert not hasattr(result, "cache_note")


@pytest.mark.parametrize("cls", ADAPTERS)
@pytest.mark.parametrize("recover", [True, False])
def test_retry_once_reports_last_failure(args, spec, cls, recover, monkeypatch):
    adapter = setup_adapter(cls, args)
    if cls is ToolCallStructured:
        first = tool_payload(error="INVALID_TOOL_ARGUMENTS")
        second = tool_payload({"value": 7} if recover else {"value": "invalid"})
    else:
        first = chat_result("{broken synthetic JSON")
        second = chat_result('{"value":7}' if recover else '{"value":"invalid"}')
    fn = inject_results(monkeypatch, cls, [first, second])
    result = adapter.generate(spec, **args)
    assert result.attempts == 2 and result.ok is recover
    assert result.failure == (None if recover else StructuredFailure.SCHEMA_VIOLATION)
    assert isinstance(result.value, Payload) if recover else result.value is None
    assert fn.call_count == 2 and len(result.calls) == 2
    assert result.cost_usd == sum(call.cost_usd for call in result.calls)
    initial, retry = (call.kwargs.get("messages") for call in fn.call_args_list)
    assert "PARSE_FAILED" not in json.dumps(initial)
    assert "PARSE_FAILED" in json.dumps(retry)
    assert "broken synthetic JSON" not in json.dumps(retry)
    assert adapter.stats.calls == 1
    assert adapter.stats.failed_after_retry == (0 if recover else 1)
    assert adapter.stats.first_attempt_failures.get(StructuredFailure.PARSE_FAILED) == 1


@pytest.mark.parametrize(
    ("output", "failure"),
    [
        (tool_payload(error="INVALID_TOOL_ARGUMENTS"), StructuredFailure.PARSE_FAILED),
        (tool_payload(), StructuredFailure.PARSE_FAILED),
        (tool_payload({"value": "bad"}), StructuredFailure.SCHEMA_VIOLATION),
        (chat_result("{}"), StructuredFailure.TOOL_NOT_CALLED),
        (tool_payload({"value": 1}, name="wrong"), StructuredFailure.TOOL_NOT_CALLED),
    ],
)
def test_tool_failures_are_classified(args, spec, output, failure, monkeypatch):
    fn = Mock(return_value=output)
    monkeypatch.setattr(structured, "chat_complete", fn)
    adapter = ToolCallStructured(ANTHROPIC)
    result = adapter.generate(spec, **args)
    assert not result.ok and result.failure == failure and result.attempts == 2
    assert adapter.stats.first_attempt_failures.get(failure) == 1
    assert adapter.stats.failed_after_retry == 1


def test_tool_lookup_is_by_name(args, spec, monkeypatch):
    response = chat_result(
        calls=[
            ToolCall("other", "other", None, "INVALID_TOOL_ARGUMENTS"),
            ToolCall("answer", spec.name, {"value": 7}, None),
        ]
    )
    monkeypatch.setattr(structured, "chat_complete", Mock(return_value=response))
    assert ToolCallStructured(ANTHROPIC).generate(spec, **args).ok


def test_measured_tools_auto(args, spec):
    fn = Mock(return_value=measured_chat("a_tools_auto"))
    result = ToolCallStructured(ANTHROPIC).generate(spec, **args, completion_fn=fn)
    assert result.ok and isinstance(result.value, Payload)
    kwargs = fn.call_args.kwargs
    assert kwargs.get("tool_choice") == "auto"
    assert kwargs.get("tools") == [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.schema,
            },
        }
    ]
    assert kwargs.get("response_format") is None
    assert "반드시" in json.dumps(kwargs.get("messages"), ensure_ascii=False)
    assert all(
        call.raw == {} and call.text is None and not call.tool_calls
        for call in result.calls
    )


@pytest.mark.parametrize(
    "text", ['{"value":7}', '```json\n{"value":7}\n```', '```\n{"value":7}\n```']
)
def test_instruction_fenced_and_plain_json(args, spec, text, monkeypatch):
    fn = Mock(return_value=chat_result(text))
    monkeypatch.setattr(structured, "chat_complete", fn)
    result = InstructionJsonStructured(ANTHROPIC).generate(spec, **args)
    assert result.ok and result.attempts == 1
    kwargs = fn.call_args.kwargs
    assert kwargs.get("tools") is None and kwargs.get("tool_choice") is None
    assert json.dumps(spec.schema, ensure_ascii=False) in json.dumps(
        kwargs.get("messages"), ensure_ascii=False
    ).replace('\\"', '"')


def test_measured_instruction(args, spec):
    result = InstructionJsonStructured(ANTHROPIC).generate(
        spec,
        **args,
        completion_fn=Mock(return_value=measured_chat("d_instruction_only")),
    )
    assert result.ok and isinstance(result.value, Payload)


@pytest.mark.parametrize(
    "cls", [InstructionJsonStructured, JsonSchemaStructured, NativeAnthropicStructured]
)
@pytest.mark.parametrize(
    ("text", "failure"),
    [
        (None, StructuredFailure.PARSE_FAILED),
        ("bad", StructuredFailure.PARSE_FAILED),
        ("[]", StructuredFailure.SCHEMA_VIOLATION),
        ("null", StructuredFailure.SCHEMA_VIOLATION),
        ('{"value":"bad"}', StructuredFailure.SCHEMA_VIOLATION),
    ],
)
def test_json_failures(args, spec, cls, text, failure, monkeypatch):
    adapter = setup_adapter(cls, args)
    inject_results(monkeypatch, cls, [chat_result(text), chat_result(text)])
    result = adapter.generate(spec, **args)
    assert not result.ok and result.failure == failure and result.attempts == 2
    assert failure != StructuredFailure.TOOL_NOT_CALLED


@pytest.mark.parametrize("cls", ADAPTERS)
def test_llm_error_propagates_without_structured_retry(args, spec, cls, monkeypatch):
    adapter = setup_adapter(cls, args)
    exc = LlmCallError(kind=ErrorKind.FATAL, code="SYNTHETIC")
    fn = inject_results(monkeypatch, cls, [exc])
    with pytest.raises(LlmCallError) as caught:
        adapter.generate(spec, **args)
    assert caught.value is exc
    assert fn.call_count == 1


@pytest.mark.parametrize("model", [OPENAI, "gpt-6.1-terra"])
def test_openai_strict_schema(args, spec, model):
    raw = (
        load("litellm_openai_anthropic_probe.json")
        .get("results")
        .get("schema_luna")
        .get("response")
    )
    # Preserve the measured envelope; pair it with this test's synthetic schema.
    for choice in raw.get("choices") or []:
        message = choice.get("message") or {}
        if message.get("role") == "assistant":
            message["content"] = '{"value":7}'
    args["reasoning_effort"] = "none"
    fn = Mock(return_value=raw)
    result = JsonSchemaStructured(model).generate(spec, **args, completion_fn=fn)
    assert result.ok and isinstance(result.value, Payload)
    assert fn.call_args.kwargs.get("response_format") == {
        "type": "json_schema",
        "json_schema": {
            "name": spec.name,
            "description": spec.description,
            "strict": True,
            "schema": spec.schema,
        },
    }
    assert fn.call_args.kwargs.get("reasoning_effort") == "none"
    assert read_entries(args.get("ledger_path")).entries[0].reasoning_effort == "none"


@pytest.mark.parametrize("running_loop", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.timeout(10)
def test_native_measured_blocks_and_loop(
    args, spec, running_loop, reverse, monkeypatch
):
    raw = native_response()
    raw["content"].insert(
        0, {"type": "thinking", "thinking": "synthetic ignored block"}
    )
    if reverse:
        raw["content"].reverse()
    threads = []

    async def acreate(**kwargs):
        threads.append(threading.get_ident())
        await asyncio.sleep(0)
        return SimpleNamespace(model_dump=lambda: raw)

    fn = AsyncMock(side_effect=acreate)
    monkeypatch.setattr(structured.litellm.anthropic.messages, "acreate", fn)
    args["messages"].insert(
        0,
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": "synthetic system",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        },
    )
    adapter = NativeAnthropicStructured(ANTHROPIC)

    async def inside_loop():
        return adapter.generate(spec, **args)

    result = (
        asyncio.run(inside_loop()) if running_loop else adapter.generate(spec, **args)
    )
    assert result.ok and isinstance(result.value, Payload) and result.attempts == 1
    assert (threads[0] != threading.get_ident()) is running_loop
    kwargs = fn.call_args.kwargs
    assert kwargs.get("output_config") == {
        "format": {"type": "json_schema", "schema": spec.schema}
    }
    assert all(message.get("role") != "system" for message in kwargs.get("messages"))
    assert any(
        block.get("cache_control") == {"type": "ephemeral"}
        for block in kwargs.get("system")
    )
    assert not {
        "extra_body",
        "tools",
        "tool_choice",
        "temperature",
        "thinking",
        "reasoning_effort",
    }.intersection(kwargs)
    assert kwargs.get("num_retries") == 0
    (entry,) = read_entries(args.get("ledger_path")).entries
    assert entry.cost_source == "price_table" and entry.reasoning_effort is None
    assert entry.cost_usd == result.cost_usd and entry.ts == STAMP
    assert entry.input_tokens == raw.get("usage").get("input_tokens")
    assert entry.output_tokens == raw.get("usage").get("output_tokens")


def spend(args, cost):
    append_entry(
        args.get("ledger_path"),
        LedgerEntry(
            ts=STAMP,
            provider="anthropic",
            model=ANTHROPIC,
            purpose="synthetic",
            cost_usd=cost,
            cost_source="price_table",
        ),
    )


def test_native_unknown_price_before_key_and_call(args, spec, monkeypatch):
    args.pop("api_key")
    require, fn = Mock(), AsyncMock()
    monkeypatch.setattr(structured, "require_setting", require)
    with pytest.raises(PriceUnknown) as caught:
        NativeAnthropicStructured("claude-unpriced").generate(
            spec, **args, acreate_fn=fn
        )
    assert caught.value.code == "PRICE_UNKNOWN"
    require.assert_not_called()
    fn.assert_not_called()


@pytest.mark.parametrize("cost", [8.0, 9.0])
def test_native_cap_prevents_call(args, spec, cost):
    spend(args, cost)
    fn = AsyncMock()
    with pytest.raises(CostCapExceeded):
        NativeAnthropicStructured(ANTHROPIC).generate(spec, **args, acreate_fn=fn)
    fn.assert_not_called()


def sdk_error(name):
    return getattr(structured.litellm, name)(
        message="synthetic failure", model=ANTHROPIC, llm_provider="anthropic"
    )


def error(status=None):
    exc = RuntimeError("synthetic failure")
    exc.status_code = status
    return exc


@pytest.mark.parametrize(
    "exc", [error(503), sdk_error("APIConnectionError"), sdk_error("Timeout")]
)
def test_native_retryable_rechecks(args, spec, monkeypatch, exc):
    check = Mock(wraps=structured.precheck_call)
    monkeypatch.setattr(structured, "precheck_call", check)
    fn = AsyncMock(side_effect=[exc, exc, native_response()])
    sleep = Mock()
    result = NativeAnthropicStructured(ANTHROPIC).generate(
        spec, **args, acreate_fn=fn, sleep=sleep, backoff_s=(0.1, 0.2)
    )
    assert result.ok and result.attempts == 1
    assert fn.call_count == check.call_count == 3
    assert [call.args for call in sleep.call_args_list] == [(0.1,), (0.2,)]
    assert len(read_entries(args.get("ledger_path")).entries) == 1


def test_native_rechecks_cap_after_wait(args, spec):
    fn = AsyncMock(side_effect=error(503))
    with pytest.raises(CostCapExceeded):
        NativeAnthropicStructured(ANTHROPIC).generate(
            spec, **args, acreate_fn=fn, sleep=lambda _: spend(args, 8.0)
        )
    fn.assert_called_once()


def test_native_structured_retry_also_rechecks_cap(args, spec):
    raw = native_response()
    raw["content"] = []
    fn = AsyncMock(return_value=raw)
    args["caps"] = {"anthropic": 0.000001}
    with pytest.raises(CostCapExceeded):
        NativeAnthropicStructured(ANTHROPIC).generate(spec, **args, acreate_fn=fn)
    fn.assert_called_once()


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 429, 500, None])
def test_native_nonretryable(args, spec, status):
    fn, sleep = AsyncMock(side_effect=error(status)), Mock()
    with pytest.raises(LlmCallError):
        NativeAnthropicStructured(ANTHROPIC).generate(
            spec, **args, acreate_fn=fn, sleep=sleep
        )
    fn.assert_called_once()
    sleep.assert_not_called()


def test_native_daily_limit_and_exhaustion(args, spec):
    exc = error(429)
    exc.response = {"headers": {"Retry-After": "7200"}}
    fn = AsyncMock(side_effect=exc)
    with pytest.raises(DailyLimitReached):
        NativeAnthropicStructured(ANTHROPIC).generate(spec, **args, acreate_fn=fn)
    fn.assert_called_once()
    fn = AsyncMock(side_effect=error(503))
    with pytest.raises(LlmCallError, match="RETRIES_EXHAUSTED"):
        NativeAnthropicStructured(ANTHROPIC).generate(
            spec, **args, acreate_fn=fn, sleep=Mock()
        )
    assert fn.call_count == 3


def test_native_post_response_failure_not_retried(args, spec, monkeypatch):
    fn = AsyncMock(return_value=native_response())
    monkeypatch.setattr(structured, "record_usage", Mock(side_effect=error(503)))
    with pytest.raises(RuntimeError):
        NativeAnthropicStructured(ANTHROPIC).generate(spec, **args, acreate_fn=fn)
    fn.assert_called_once()


def test_native_safe_errors_and_setting(args, spec, monkeypatch):
    private = "synthetic-private-payload"
    exc = RuntimeError(args.get("api_key") + private)
    exc.status_code = 401
    with pytest.raises(LlmCallError) as caught:
        NativeAnthropicStructured(ANTHROPIC).generate(
            spec, **args, acreate_fn=AsyncMock(side_effect=exc)
        )
    rendered = "".join(traceback.format_exception(caught.value))
    assert args.get("api_key") not in rendered and private not in rendered
    args.pop("api_key")
    require = Mock(return_value=uuid4().hex)
    monkeypatch.setattr(structured, "require_setting", require)
    NativeAnthropicStructured(ANTHROPIC).generate(
        spec, **args, acreate_fn=AsyncMock(return_value=native_response())
    )
    require.assert_called_once_with("ANTHROPIC_API_KEY")
    assert require.return_value not in args.get("ledger_path").read_text()


def test_stats_merge_sums_without_mutation():
    empty = StructuredStats()
    assert empty.failure_rate is None
    first = StructuredStats(
        calls=3,
        failed_after_retry=1,
        first_attempt_failures={StructuredFailure.PARSE_FAILED: 2},
    )
    second = StructuredStats(
        calls=2,
        failed_after_retry=1,
        first_attempt_failures={
            StructuredFailure.PARSE_FAILED: 1,
            StructuredFailure.TOOL_NOT_CALLED: 1,
        },
    )
    merged = first.merge(second)
    assert merged.calls == 5 and merged.failed_after_retry == 2
    assert merged.failure_rate == 2 / 5
    assert merged.first_attempt_failures.get(StructuredFailure.PARSE_FAILED) == 3
    assert merged.first_attempt_failures.get(StructuredFailure.TOOL_NOT_CALLED) == 1
    assert first.calls == 3 and second.calls == 2
    assert empty.merge(merged) == merged
    assert "20호출 미만" in StructuredStats.__doc__


def test_failure_detail_merge_sums_union_and_keeps_sources_independent():
    key = "evaluation_scores|rationale|string_too_long"
    other_key = "plan|scenes.*|string_type"
    first = StructuredStats(first_attempt_failure_details={key: 2})
    second = StructuredStats(first_attempt_failure_details={key: 1, other_key: 3})
    merged = first.merge(second)
    assert merged.first_attempt_failure_details == {key: 3, other_key: 3}
    merged.first_attempt_failure_details[key] = 99
    assert first.first_attempt_failure_details == {key: 2}
    assert second.first_attempt_failure_details == {key: 1, other_key: 3}
    assert StructuredStats().first_attempt_failure_details == {}


@pytest.mark.parametrize("cls", ADAPTERS)
def test_failure_details_cover_each_adapter_and_leave_success_empty(
    args, spec, cls, monkeypatch
):
    adapter = setup_adapter(cls, args)
    first = (
        tool_payload({"value": "SYNTHETIC-SECRET-invalid"})
        if cls is ToolCallStructured
        else chat_result('{"value":"SYNTHETIC-SECRET-invalid"}')
    )
    good = (
        tool_payload({"value": 1})
        if cls is ToolCallStructured
        else chat_result('{"value":1}')
    )
    inject_results(monkeypatch, cls, [first, good, good])
    assert adapter.generate(spec, **args).ok
    assert adapter.stats.first_attempt_failure_details == {"answer|value|int_type": 1}
    before = deepcopy(adapter.stats)
    assert adapter.generate(spec, **args).attempts == 1
    assert (
        adapter.stats.first_attempt_failure_details
        == before.first_attempt_failure_details
    )


@pytest.mark.parametrize(
    ("model", "style", "expected"),
    [
        (ANTHROPIC, "default", ToolCallStructured),
        ("claude-haiku-5-5", "default", ToolCallStructured),
        (OPENAI, "default", JsonSchemaStructured),
        ("gpt-6.1-terra", "default", JsonSchemaStructured),
        (ANTHROPIC, "instruction", InstructionJsonStructured),
        (OPENAI, "instruction", InstructionJsonStructured),
        (ANTHROPIC, "native", NativeAnthropicStructured),
    ],
)
def test_factory(model, style, expected):
    assert isinstance(make_structured(model, style=style), expected)
    if style == "default":
        assert isinstance(make_structured(model), expected)


@pytest.mark.parametrize(
    ("model", "style"),
    [
        (OPENAI, "native"),
        (ANTHROPIC, "invalid"),
        ("unknown", "default"),
        ("openai/" + OPENAI, "default"),
    ],
)
def test_factory_rejects_unknown_combinations(model, style):
    with pytest.raises(ValueError):
        make_structured(model, style=style)


@pytest.mark.parametrize(
    ("model", "style", "effort"),
    [
        (OPENAI, "default", None),
        (OPENAI, "instruction", "invalid"),
        (ANTHROPIC, "default", "low"),
        (ANTHROPIC, "instruction", "low"),
        (ANTHROPIC, "native", "low"),
    ],
)
def test_reasoning_rejected_before_dispatch(
    args, spec, model, style, effort, monkeypatch
):
    chat, native = Mock(), AsyncMock()
    monkeypatch.setattr(structured, "chat_complete", chat)
    args["reasoning_effort"] = effort
    with pytest.raises(ValueError, match="REASONING_EFFORT_INVALID"):
        make_structured(model, style=style).generate(spec, **args, acreate_fn=native)
    chat.assert_not_called()
    native.assert_not_called()


@pytest.mark.parametrize("cls", ADAPTERS)
def test_missing_reasoning_and_no_temperature(args, spec, cls):
    adapter = setup_adapter(cls, args)
    args.pop("reasoning_effort")
    with pytest.raises(ValueError, match="REASONING_EFFORT_INVALID"):
        adapter.generate(spec, **args)
    signature = inspect.signature(adapter.generate)
    assert "temperature" not in signature.parameters
    assert all(
        p.kind != inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()
    )
