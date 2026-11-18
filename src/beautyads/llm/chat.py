"""Synchronous LiteLLM chat calls with explicit reasoning and immediate accounting."""

import json
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

import litellm

from beautyads.obs import LedgerEntry, append_entry, check_cap
from beautyads.settings import require_setting

from .errors import (
    DailyLimitReached,
    ErrorKind,
    LlmCallError,
    classify_error,
    retry_after_seconds,
)
from .prices import CostSource, PriceUnknown, _usage_tokens, price_for, resolve_cost

_MODELS = frozenset(
    {"gpt-6-luna", "gpt-6.1-terra", "claude-haiku-5-5", "claude-sonnet-5-5"}
)
_UNSET = object()


class ToolCall(NamedTuple):
    id: str | None
    name: str | None
    arguments: dict | None
    arguments_error: str | None


class ChatResult(NamedTuple):
    text: str | None
    tool_calls: list[ToolCall]
    finish_reason: str | None
    usage: dict
    cost_usd: float
    cost_source: CostSource
    raw: dict


def cache_system_block(text: str) -> dict:
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}


def precheck_call(model: str, *, ledger_path: Path, caps: Mapping[str, float]) -> None:
    price = price_for(model)
    if price is None:
        raise PriceUnknown()
    check_cap(ledger_path, provider=price.provider, caps=caps)


def record_usage(
    *,
    model: str,
    purpose: str,
    ledger_path: Path,
    usage: Mapping[str, Any],
    response_cost: float | None,
    reasoning_effort: str | None,
    now: Callable[[], datetime] | None,
) -> tuple[float, CostSource]:
    cost, source = resolve_cost(model, response_cost=response_cost, usage=usage)
    price = price_for(model)
    if price is None:
        raise PriceUnknown()
    tokens = _usage_tokens(model, usage)
    append_entry(
        ledger_path,
        LedgerEntry(
            ts=now() if now is not None else datetime.now(UTC),
            provider=price.provider,
            model=model,
            requested_model=model,
            purpose=purpose,
            input_tokens=tokens.total_input,
            output_tokens=tokens.output,
            cached_tokens=tokens.read,
            thought_tokens=(usage.get("completion_tokens_details") or {}).get(
                "reasoning_tokens"
            )
            or 0,
            cost_usd=cost,
            cost_source=source,
            reasoning_effort=reasoning_effort if price.provider == "openai" else None,
        ),
    )
    return cost, source


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else value.model_dump()


def _tool_call(raw: Mapping[str, Any]) -> ToolCall:
    function = raw.get("function") or {}
    arguments, arguments_error = None, None
    try:
        parsed = json.loads(function.get("arguments"))
    except (ValueError, TypeError):
        arguments_error = "INVALID_TOOL_ARGUMENTS"
    else:
        if isinstance(parsed, dict):
            arguments = parsed
        else:
            arguments_error = "TOOL_ARGUMENTS_NOT_OBJECT"
    return ToolCall(raw.get("id"), function.get("name"), arguments, arguments_error)


def _result(raw: dict, usage: dict, cost: float, source: CostSource) -> ChatResult:
    # Match an assistant message, never the position of a choice or a block.
    choice = next(
        (
            choice
            for choice in raw.get("choices") or []
            if isinstance(choice, Mapping)
            and isinstance(choice.get("message"), Mapping)
            and choice.get("message").get("role") == "assistant"
        ),
        None,
    )
    if choice is None:
        return ChatResult(None, [], "NO_ASSISTANT_MESSAGE", usage, cost, source, raw)
    message = choice.get("message")
    content = message.get("content")
    text = content if isinstance(content, str) else None
    if isinstance(content, list):
        parts = [
            block.get("text")
            for block in content
            if isinstance(block, Mapping)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        text = "".join(parts) if parts else None
    calls = [
        _tool_call(call)
        for call in message.get("tool_calls") or []
        if isinstance(call, Mapping) and call.get("type") == "function"
    ]
    return ChatResult(
        text, calls, choice.get("finish_reason"), usage, cost, source, raw
    )


def _call_error(exc: Exception, *, exhausted: bool = False) -> LlmCallError:
    kind = classify_error(exc)
    cls = (
        DailyLimitReached
        if kind in (ErrorKind.DAILY_LIMIT, ErrorKind.CREDITS_DEPLETED)
        else LlmCallError
    )
    # SDK exception bodies may contain the entire request or response: retain codes only.
    return cls(
        kind=kind,
        code="RETRIES_EXHAUSTED" if exhausted else kind.value,
        retry_after_s=retry_after_seconds(exc),
    )


def _chat(
    *,
    stream: bool,
    model,
    messages,
    purpose,
    ledger_path,
    caps,
    reasoning_effort,
    tools,
    tool_choice,
    response_format,
    max_tokens,
    api_key,
    timeout_s,
    max_attempts,
    backoff_s,
    completion_fn,
    sleep,
    now,
) -> ChatResult:
    if model not in _MODELS:
        raise ValueError("CHAT_MODEL_INVALID")
    provider = "openai" if model.startswith("gpt-") else "anthropic"
    if provider == "openai":
        if not isinstance(reasoning_effort, str) or reasoning_effort not in {
            "none",
            "low",
            "medium",
            "high",
        }:
            raise ValueError("REASONING_EFFORT_INVALID")
    elif reasoning_effort is not None:
        raise ValueError("REASONING_EFFORT_INVALID")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    if max_attempts > 1 and not backoff_s:
        raise ValueError("backoff_s must not be empty when retrying")
    if max_tokens is not None and (
        isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or max_tokens <= 0
    ):
        raise ValueError("MAX_TOKENS_INVALID")
    call = completion_fn if completion_fn is not None else litellm.completion
    kwargs = {
        "model": f"{provider}/{model}",
        "messages": messages,
        "timeout": timeout_s,
        "num_retries": 0,
    }
    if provider == "openai":
        kwargs["reasoning_effort"] = reasoning_effort
        if tool_choice is not None:
            kwargs["allowed_openai_params"] = ["tool_choice"]
    for name, value in (
        ("tools", tools),
        ("tool_choice", tool_choice),
        ("response_format", response_format),
        ("max_tokens", max_tokens),
    ):
        if value is not None:
            kwargs[name] = value
    if stream:
        kwargs.update(stream=True, stream_options={"include_usage": True})
    for attempt in range(max_attempts):
        precheck_call(model, ledger_path=ledger_path, caps=caps)
        if "api_key" not in kwargs:
            kwargs["api_key"] = (
                api_key
                if api_key is not None
                else require_setting(f"{provider.upper()}_API_KEY")
            )
        try:
            response = call(**kwargs)
        except Exception as exc:  # noqa: BLE001 -- classify every SDK failure, retry only known safe cases
            kind = classify_error(exc)
            if kind == ErrorKind.RETRYABLE and attempt + 1 < max_attempts:
                sleep(backoff_s[min(attempt, len(backoff_s) - 1)])
                continue
            raise _call_error(exc, exhausted=kind == ErrorKind.RETRYABLE) from None
        break
    if stream:
        # Once dispatch has returned, never retry stream consumption or accounting.
        try:
            chunks = list(response)
            response = litellm.stream_chunk_builder(chunks, messages=messages)
        except Exception as exc:  # noqa: BLE001 -- surface a safe error without replaying a paid call
            raise _call_error(exc) from None
    raw = _dict(response)
    usage = raw.get("usage") or {}
    hidden = (
        getattr(response, "_hidden_params", None) or raw.get("_hidden_params") or {}
    )
    cost, source = record_usage(
        model=model,
        purpose=purpose,
        ledger_path=ledger_path,
        usage=usage,
        response_cost=None if stream else hidden.get("response_cost"),
        reasoning_effort=reasoning_effort,
        now=now,
    )
    return _result(raw, usage, cost, source)


def chat_complete(
    *,
    model: str,
    messages,
    purpose: str,
    ledger_path: Path,
    caps: Mapping[str, float],
    reasoning_effort: str | None = _UNSET,
    tools=None,
    tool_choice=None,
    response_format=None,
    max_tokens=None,
    api_key: str | None = None,
    timeout_s: float = 120.0,
    max_attempts: int = 3,
    backoff_s: Sequence[float] = (2.0, 5.0, 15.0),
    completion_fn=None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] | None = None,
) -> ChatResult:
    """Require an explicit reasoning choice; omission is a pre-call ValueError."""
    return _chat(stream=False, **locals())


def chat_stream(
    *,
    model: str,
    messages,
    purpose: str,
    ledger_path: Path,
    caps: Mapping[str, float],
    reasoning_effort: str | None = _UNSET,
    tools=None,
    tool_choice=None,
    response_format=None,
    max_tokens=None,
    api_key: str | None = None,
    timeout_s: float = 120.0,
    max_attempts: int = 3,
    backoff_s: Sequence[float] = (2.0, 5.0, 15.0),
    completion_fn=None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] | None = None,
) -> ChatResult:
    """Collect chunks and account from merged usage using the pinned price table."""
    return _chat(stream=True, **locals())
