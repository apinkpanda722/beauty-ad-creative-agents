"""Chat paths use measured response shapes and injected, offline calls."""

import inspect
import json
import traceback
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from beautyads.llm import (
    ChatResult,
    CostCapExceeded,
    DailyLimitReached,
    ErrorKind,
    LlmCallError,
    PriceUnknown,
    ToolCall,
    cache_system_block,
    chat,
    chat_complete,
    chat_stream,
    precheck_call,
    record_usage,
)
from beautyads.obs import LedgerEntry, append_entry, read_entries

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
STAMP = datetime(2026, 11, 17, tzinfo=UTC)
MODELS = ("gpt-6-luna", "gpt-6.1-terra", "claude-haiku-5-5", "claude-sonnet-5-5")


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def probe(name="basic_luna"):
    item = load("litellm_openai_anthropic_probe.json").get("results").get(name)
    raw = deepcopy(item.get("response"))
    for choice in raw.get("choices") or []:
        message = choice.get("message") or {}
        if isinstance(message.get("content"), str):
            message["content"] = "synthetic answer"
    raw["_hidden_params"] = {"response_cost": item.get("hidden").get("response_cost")}
    return raw


@pytest.fixture
def args(tmp_path):
    return {
        "model": MODELS[0],
        "messages": [{"role": "user", "content": "synthetic prompt"}],
        "purpose": "chat-test",
        "ledger_path": tmp_path / "costs.jsonl",
        "caps": {"openai": 10.0, "anthropic": 8.0},
        "reasoning_effort": "low",
        "api_key": uuid4().hex,
        "now": lambda: STAMP,
    }


@pytest.mark.parametrize("fn", [chat_complete, chat_stream])
def test_no_temperature_argument(fn):
    assert "temperature" not in inspect.signature(fn).parameters
    assert all(
        p.kind != inspect.Parameter.VAR_KEYWORD
        for p in inspect.signature(fn).parameters.values()
    )


@pytest.mark.parametrize("model", MODELS[:2])
@pytest.mark.parametrize("effort", ["none", "low", "medium", "high"])
def test_openai_arguments_and_recorded_reasoning(args, model, effort):
    args.update(model=model, reasoning_effort=effort)
    fn = Mock(return_value=probe())
    tools = [{"type": "function", "function": {"name": "synthetic"}}]
    fmt = {"type": "json_object"}
    result = chat_complete(
        **args,
        tools=tools,
        tool_choice="auto",
        response_format=fmt,
        max_tokens=20,
        timeout_s=42,
        completion_fn=fn,
    )
    assert isinstance(result, ChatResult)
    kwargs = fn.call_args.kwargs
    assert kwargs.get("model") == f"openai/{model}"
    assert kwargs.get("reasoning_effort") == effort
    assert kwargs.get("messages") == args.get("messages")
    assert kwargs.get("tools") == tools
    assert kwargs.get("tool_choice") == "auto"
    assert kwargs.get("response_format") == fmt
    assert kwargs.get("max_tokens") == 20
    assert kwargs.get("timeout") == 42
    assert kwargs.get("num_retries") == 0
    assert "temperature" not in kwargs and "thinking" not in kwargs
    row = read_entries(args.get("ledger_path")).entries[0]
    assert row.reasoning_effort == effort
    assert row.ts == STAMP
    assert row.provider == "openai"
    assert row.purpose == args.get("purpose")
    assert row.cost_usd == result.cost_usd
    assert row.cost_source == result.cost_source


@pytest.mark.parametrize("model", MODELS[:2])
@pytest.mark.parametrize("effort", [None, "minimal", "invalid", 1, []])
def test_invalid_openai_effort_never_calls(args, model, effort):
    args.update(model=model, reasoning_effort=effort)
    fn = Mock()
    with pytest.raises(ValueError):
        chat_complete(**args, completion_fn=fn)
    fn.assert_not_called()


def test_missing_effort_never_calls(args):
    args.pop("reasoning_effort")
    fn = Mock()
    with pytest.raises(ValueError):
        chat_complete(**args, completion_fn=fn)
    fn.assert_not_called()


@pytest.mark.parametrize("model", MODELS[2:])
def test_anthropic_has_no_reasoning_or_thinking(args, model):
    args.update(model=model, reasoning_effort=None)
    fn = Mock(return_value=probe("basic_haiku"))
    chat_complete(**args, completion_fn=fn)
    assert fn.call_args.kwargs.get("model") == f"anthropic/{model}"
    for name in ("reasoning_effort", "thinking", "temperature"):
        assert name not in fn.call_args.kwargs
    assert read_entries(args.get("ledger_path")).entries[0].reasoning_effort is None
    args["reasoning_effort"] = "low"
    fn.reset_mock()
    with pytest.raises(ValueError):
        chat_complete(**args, completion_fn=fn)
    fn.assert_not_called()


@pytest.mark.parametrize("model", ["unknown", "openai/gpt-6-luna"])
def test_unknown_model(args, model):
    args["model"] = model
    fn = Mock()
    with pytest.raises(ValueError):
        chat_complete(**args, completion_fn=fn)
    fn.assert_not_called()


def test_unknown_price_fails_before_key_or_call(args, monkeypatch):
    monkeypatch.setattr(chat, "price_for", lambda _: None)
    args.pop("api_key")
    require, fn = Mock(), Mock()
    monkeypatch.setattr(chat, "require_setting", require)
    with pytest.raises(PriceUnknown) as caught:
        chat_complete(**args, completion_fn=fn)
    assert isinstance(caught.value, LlmCallError)
    assert caught.value.code == "PRICE_UNKNOWN"
    require.assert_not_called()
    fn.assert_not_called()


def spend(args, cost):
    append_entry(
        args.get("ledger_path"),
        LedgerEntry(
            ts=STAMP,
            provider="openai",
            model=MODELS[0],
            purpose="synthetic",
            cost_usd=cost,
            cost_source="response_cost",
        ),
    )


@pytest.mark.parametrize("cost", [10.0, 11.0])
def test_cap_prevents_call(args, cost):
    spend(args, cost)
    fn = Mock()
    with pytest.raises(CostCapExceeded):
        chat_complete(**args, completion_fn=fn)
    fn.assert_not_called()


def error(status=None, message="synthetic failure"):
    exc = RuntimeError(message)
    exc.status_code = status
    return exc


def sdk_error(name):
    return getattr(chat.litellm, name)(
        message="synthetic failure", model=MODELS[0], llm_provider="openai"
    )


@pytest.mark.parametrize(
    "exc", [error(503), sdk_error("APIConnectionError"), sdk_error("Timeout")]
)
def test_retryable_errors_recheck_caps(args, exc, monkeypatch):
    check = Mock(wraps=chat.precheck_call)
    monkeypatch.setattr(chat, "precheck_call", check)
    fn = Mock(side_effect=[exc, exc, probe()])
    sleep = Mock()
    chat_complete(**args, completion_fn=fn, sleep=sleep, backoff_s=(0.1, 0.2))
    assert fn.call_count == 3
    assert check.call_count == 3
    assert [call.args for call in sleep.call_args_list] == [(0.1,), (0.2,)]
    assert len(read_entries(args.get("ledger_path")).entries) == 1


def test_cap_rechecked_after_wait(args):
    fn = Mock(side_effect=error(503))
    with pytest.raises(CostCapExceeded):
        chat_complete(**args, completion_fn=fn, sleep=lambda _: spend(args, 10.0))
    fn.assert_called_once()


@pytest.mark.parametrize(
    ("exc", "code", "kind", "cls"),
    [
        (
            error(429, "daily quota"),
            "DAILY_LIMIT",
            ErrorKind.DAILY_LIMIT,
            DailyLimitReached,
        ),
        (error(402), "CREDITS_DEPLETED", ErrorKind.CREDITS_DEPLETED, DailyLimitReached),
        (error(429), "RATE_LIMIT", ErrorKind.RATE_LIMIT, LlmCallError),
        (error(401), "FATAL", ErrorKind.FATAL, LlmCallError),
        (error(404), "FATAL", ErrorKind.FATAL, LlmCallError),
        (error(), "FATAL", ErrorKind.FATAL, LlmCallError),
    ],
)
def test_nonretryable_failure(args, exc, code, kind, cls):
    fn, sleep = Mock(side_effect=exc), Mock()
    with pytest.raises(cls) as caught:
        chat_complete(**args, completion_fn=fn, sleep=sleep)
    assert caught.value.code == code and caught.value.kind == kind
    fn.assert_called_once()
    sleep.assert_not_called()
    assert not args.get("ledger_path").exists()


def test_retry_exhaustion(args):
    fn, sleep = Mock(side_effect=error(503)), Mock()
    with pytest.raises(LlmCallError) as caught:
        chat_complete(**args, completion_fn=fn, sleep=sleep)
    assert caught.value.code == "RETRIES_EXHAUSTED"
    assert fn.call_count == 3 and sleep.call_count == 2
    assert not args.get("ledger_path").exists()


@pytest.mark.parametrize("name", ["tool_luna", "tool_haiku"])
def test_tool_calls_and_malformed_arguments(args, name):
    raw = probe(name)
    args.update(
        model=raw.get("model"), reasoning_effort="none" if name == "tool_luna" else None
    )
    for invalid in (False, True):
        for choice in raw.get("choices"):
            for call in (choice.get("message") or {}).get("tool_calls") or []:
                if invalid:
                    call.get("function")["arguments"] = "{private-invalid-json"
        result = chat_complete(**args, completion_fn=Mock(return_value=raw))
        assert result.tool_calls and all(
            isinstance(call, ToolCall) for call in result.tool_calls
        )
        for call in result.tool_calls:
            assert isinstance(call.id, str) and isinstance(call.name, str)
            if invalid:
                assert call.arguments is None and call.arguments_error
                assert "private-invalid-json" not in call.arguments_error
            else:
                assert isinstance(call.arguments, dict) and call.arguments_error is None


@pytest.mark.parametrize("empty", [True, False])
def test_missing_choices_or_tool_calls_return_result(args, empty):
    raw = probe()
    if empty:
        raw["choices"] = []
    else:
        for choice in raw.get("choices"):
            choice.get("message").pop("tool_calls", None)
        raw["choices"].insert(0, {"message": {"role": "user", "content": "ignore"}})
    result = chat_complete(**args, completion_fn=Mock(return_value=raw))
    assert result.tool_calls == []
    assert result.text == (None if empty else "synthetic answer")
    assert result.finish_reason == ("NO_ASSISTANT_MESSAGE" if empty else "stop")
    assert len(read_entries(args.get("ledger_path")).entries) == 1


@pytest.mark.parametrize("name", ["stream_cost_luna", "stream_cost_haiku"])
def test_stream_builder_uses_measured_usage(args, name, monkeypatch):
    measured = load("litellm_reasoning_effort_and_stream_cost.json").get(name)
    suffix = "luna" if name.endswith("luna") else "haiku"
    args.update(
        model=MODELS[0] if suffix == "luna" else MODELS[2],
        reasoning_effort="none" if suffix == "luna" else None,
    )
    stream = (
        load("litellm_openai_anthropic_probe.json")
        .get("results")
        .get(f"stream_{suffix}")
        .get("response")
    )
    chunks = [deepcopy(stream.get("first")), deepcopy(stream.get("last"))]
    chunks[-1]["usage"] = measured.get("built_usage")
    built = probe(f"basic_{suffix}")
    built["usage"] = measured.get("built_usage")
    built["_hidden_params"] = {"response_cost": 999.0}
    builder = Mock(return_value=built)
    monkeypatch.setattr(chat.litellm, "stream_chunk_builder", builder)
    fn = Mock(return_value=iter(chunks))
    result = chat_stream(**args, completion_fn=fn)
    builder.assert_called_once_with(chunks, messages=args.get("messages"))
    assert fn.call_args.kwargs.get("stream") is True
    assert fn.call_args.kwargs.get("stream_options") == {"include_usage": True}
    assert result.cost_source == "price_table"
    assert result.cost_usd == pytest.approx(
        measured.get("completion_cost_built"), rel=1e-6
    )
    assert read_entries(args.get("ledger_path")).entries[0].cost_source == "price_table"


def test_real_offline_stream_builder(args):
    stream = (
        load("litellm_openai_anthropic_probe.json")
        .get("results")
        .get("stream_luna")
        .get("response")
    )
    chunks = [
        chat.litellm.ModelResponse(**stream.get("first"), stream=True),
        chat.litellm.ModelResponse(**stream.get("last"), stream=True),
    ]
    result = chat_stream(**args, completion_fn=Mock(return_value=iter(chunks)))
    assert result.usage.get("prompt_tokens") == stream.get("last").get("usage").get(
        "prompt_tokens"
    )
    assert result.cost_usd > 0 and result.cost_source == "price_table"


def test_post_response_failure_is_not_retried(args, monkeypatch):
    fn, sleep = Mock(return_value=probe()), Mock()
    monkeypatch.setattr(chat, "record_usage", Mock(side_effect=error(503)))
    with pytest.raises(RuntimeError):
        chat_complete(**args, completion_fn=fn, sleep=sleep)
    fn.assert_called_once()
    sleep.assert_not_called()


def test_stream_failure_after_dispatch_is_not_retried(args):
    def chunks():
        yield SimpleNamespace()
        raise error(503)

    fn, sleep = Mock(return_value=chunks()), Mock()
    with pytest.raises(LlmCallError):
        chat_stream(**args, completion_fn=fn, sleep=sleep)
    fn.assert_called_once()
    sleep.assert_not_called()
    assert not args.get("ledger_path").exists()


def test_safe_errors_and_ledger(args):
    private = "private-response-payload"
    fn = Mock(side_effect=error(401, args.get("api_key") + private))
    with pytest.raises(LlmCallError) as caught:
        chat_complete(**args, completion_fn=fn)
    rendered = "".join(traceback.format_exception(caught.value))
    assert args.get("api_key") not in rendered and private not in rendered
    chat_complete(**args, completion_fn=Mock(return_value=probe()))
    ledger = args.get("ledger_path").read_text()
    assert args.get("api_key") not in ledger
    assert "synthetic answer" not in ledger and "synthetic prompt" not in ledger


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_setting_and_sdk_resolved_at_call_time(args, monkeypatch, provider):
    args.pop("api_key")
    if provider == "anthropic":
        args.update(model=MODELS[2], reasoning_effort=None)
    require = Mock(return_value=uuid4().hex)
    fn = Mock(return_value=probe())
    monkeypatch.setattr(chat, "require_setting", require)
    monkeypatch.setattr(chat.litellm, "completion", fn)
    chat_complete(**args)
    require.assert_called_once_with(f"{provider.upper()}_API_KEY")
    assert fn.call_args.kwargs.get("api_key") == require.return_value


def test_cache_block_and_public_helpers(args):
    assert cache_system_block("synthetic system") == {
        "type": "text",
        "text": "synthetic system",
        "cache_control": {"type": "ephemeral"},
    }
    precheck_call(
        args.get("model"), ledger_path=args.get("ledger_path"), caps=args.get("caps")
    )
    cost, source = record_usage(
        model=args.get("model"),
        purpose=args.get("purpose"),
        ledger_path=args.get("ledger_path"),
        usage={"prompt_tokens": 10, "completion_tokens": 20},
        response_cost=None,
        reasoning_effort="low",
        now=lambda: STAMP,
    )
    assert (cost, source) == (0.000011, "price_table")
    assert read_entries(args.get("ledger_path")).entries[0].reasoning_effort == "low"


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("choice", [None, "auto", "none", "required"])
@pytest.mark.parametrize("complete", [chat_complete, chat_stream])
def test_tool_choice_allowance_is_openai_only(
    args, model, choice, complete, monkeypatch
):
    args.update(model=model, reasoning_effort="none" if model in MODELS[:2] else None)
    raw = probe()
    monkeypatch.setattr(chat.litellm, "stream_chunk_builder", Mock(return_value=raw))
    fn = Mock(return_value=iter([]) if complete is chat_stream else raw)
    complete(**args, tool_choice=choice, completion_fn=fn)
    kwargs = fn.call_args.kwargs
    if model in MODELS[:2] and choice is not None:
        assert kwargs.get("allowed_openai_params") == ["tool_choice"]
    else:
        assert "allowed_openai_params" not in kwargs
    if choice is None:
        assert "tool_choice" not in kwargs
    else:
        assert kwargs.get("tool_choice") == choice


@pytest.mark.parametrize("complete", [chat_complete, chat_stream])
def test_successful_call_duration_includes_stream_consumption(
    args, monkeypatch, complete
):
    clock = {"seconds": 1.0}
    monkeypatch.setattr(chat, "_monotonic", lambda: clock["seconds"])
    raw = probe()

    def chunks():
        clock["seconds"] = 2.0
        yield {"synthetic": True}
        clock["seconds"] = 2.25

    def build(chunks, *, messages):
        clock["seconds"] = 2.5
        return raw

    def dispatch(**kwargs):
        if complete is chat_stream:
            return chunks()
        clock["seconds"] = 2.5
        return raw

    monkeypatch.setattr(chat.litellm, "stream_chunk_builder", build)
    complete(**args, completion_fn=dispatch)
    (row,) = read_entries(args["ledger_path"]).entries
    assert row.duration_ms == 1500
    assert row.ts == STAMP


def test_call_duration_excludes_failed_attempt_and_backoff(args, monkeypatch):
    clock = {"seconds": 1.0}
    monkeypatch.setattr(chat, "_monotonic", lambda: clock["seconds"])
    attempts = []

    def dispatch(**kwargs):
        attempts.append(clock["seconds"])
        if len(attempts) == 1:
            clock["seconds"] += 4.0
            raise error(503)
        clock["seconds"] += 1.5
        return probe()

    def sleep(seconds):
        clock["seconds"] += seconds

    chat_complete(**args, completion_fn=dispatch, sleep=sleep, backoff_s=(10.0,))
    assert attempts == [1.0, 15.0]
    (row,) = read_entries(args["ledger_path"]).entries
    assert row.duration_ms == 1500


def test_record_usage_duration_is_optional_keyword(args):
    parameter = inspect.signature(record_usage).parameters["duration_ms"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None
    for duration in (None, 0, 1500):
        record_usage(
            model=args["model"],
            purpose=args["purpose"],
            ledger_path=args["ledger_path"],
            usage={},
            response_cost=0.01,
            reasoning_effort="low",
            now=lambda: STAMP,
            duration_ms=duration,
        )
    assert [row.duration_ms for row in read_entries(args["ledger_path"]).entries] == [
        None,
        0,
        1500,
    ]
