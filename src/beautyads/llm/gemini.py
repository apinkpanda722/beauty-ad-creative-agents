"""Synchronous Gemini Interactions calls, retries, and immediate cost recording."""

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple, Protocol

import litellm

from beautyads.obs import LedgerEntry, append_entry, check_cap
from beautyads.settings import ThinkingLevel, require_setting

from .errors import (
    DailyLimitReached,
    ErrorKind,
    LlmCallError,
    LlmResponseError,
    classify_error,
    retry_after_seconds,
)


class GeminiInteractionsFn(Protocol):
    def __call__(self, **kwargs: Any) -> Any: ...


def text_part(text: str) -> dict:
    return {"type": "text", "text": text}


def video_part(
    uri: str,
    *,
    start_s: float | None = None,
    end_s: float | None = None,
    fps: float | None = None,
) -> dict:
    part = {"type": "video", "uri": uri}
    processing = {}
    if start_s is not None:
        processing["start_offset"] = f"{start_s:g}s"
    if end_s is not None:
        processing["end_offset"] = f"{end_s:g}s"
    if fps is not None:
        processing["fps"] = fps
    if processing:
        part["processing"] = {"type": "static", **processing}
    return part


def json_schema_format(schema: Mapping[str, Any]) -> dict:
    return {"type": "text", "mime_type": "application/json", "schema": dict(schema)}


def _response_dict(response: Any) -> dict:
    return response if isinstance(response, dict) else response.model_dump()


def extract_output_text(response: Any) -> str:
    raw = _response_dict(response)
    outputs = [
        step
        for step in (raw.get("steps") or [])
        if isinstance(step, Mapping) and step.get("type") == "model_output"
    ]
    if not outputs:
        raise LlmResponseError("NO_MODEL_OUTPUT")
    return "".join(
        part.get("text")
        for step in outputs
        for part in (step.get("content") or [])
        if isinstance(part, Mapping) and isinstance(part.get("text"), str)
    )


def parse_json_output(text: str) -> Any:
    text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fenced is not None:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise LlmResponseError("INVALID_JSON") from None


class UsageInfo(NamedTuple):
    model: str
    input_tokens: int
    output_tokens: int
    thought_tokens: int
    cached_tokens: int
    cost_usd: float | None


def usage_from_response(response: Any) -> UsageInfo:
    raw = _response_dict(response)
    usage = raw.get("usage") or {}
    hidden = (
        getattr(response, "_hidden_params", None) or raw.get("_hidden_params") or {}
    )
    return UsageInfo(
        model=raw.get("model", ""),
        input_tokens=usage.get("total_input_tokens") or 0,
        output_tokens=usage.get("total_output_tokens") or 0,
        thought_tokens=usage.get("total_thought_tokens") or 0,
        cached_tokens=usage.get("total_cached_tokens") or 0,
        cost_usd=hidden.get("response_cost"),
    )


class InteractionResult(NamedTuple):
    text: str
    usage: UsageInfo
    raw: dict


def gemini_interact(
    *,
    model: str,
    input_parts: Sequence[Mapping[str, Any]],
    thinking_level: ThinkingLevel,
    purpose: str,
    ledger_path: Path,
    caps: Mapping[str, float],
    response_format: Mapping[str, Any] | None = None,
    api_key: str | None = None,
    timeout_s: float = 180.0,
    max_attempts: int = 3,
    backoff_s: Sequence[float] = (2.0, 5.0, 15.0),
    interactions_fn: GeminiInteractionsFn | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] | None = None,
) -> InteractionResult:
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    if max_attempts > 1 and not backoff_s:
        raise ValueError("backoff_s must not be empty when retrying")
    key = api_key if api_key is not None else require_setting("GEMINI_API_KEY")
    call = (
        interactions_fn if interactions_fn is not None else litellm.interactions.create
    )
    kwargs = {
        "model": f"gemini/{model}",
        "input": list(input_parts),
        "api_key": key,
        "timeout": timeout_s,
    }
    if thinking_level != "default":
        kwargs["generation_config"] = {"thinking_level": thinking_level}
    if response_format is not None:
        kwargs["response_format"] = response_format
    for attempt in range(max_attempts):
        check_cap(ledger_path, provider="gemini", caps=caps)
        try:
            response = call(**kwargs)
        except Exception as exc:  # noqa: BLE001 -- unknown call errors are fatal too
            kind = classify_error(exc)
            if kind == ErrorKind.RETRYABLE and attempt + 1 < max_attempts:
                sleep(backoff_s[min(attempt, len(backoff_s) - 1)])
                continue
            message = str(exc).replace(key, "[redacted]") if key else str(exc)
            error_type = (
                DailyLimitReached if kind == ErrorKind.DAILY_LIMIT else LlmCallError
            )
            raise error_type(
                kind=kind,
                code="RETRIES_EXHAUSTED" if kind == ErrorKind.RETRYABLE else kind.value,
                message=message,
                retry_after_s=retry_after_seconds(exc),
            ) from None
        usage = usage_from_response(response)
        append_entry(
            ledger_path,
            LedgerEntry(
                ts=now() if now is not None else datetime.now(UTC),
                provider="gemini",
                model=usage.model,
                requested_model=model,
                purpose=purpose,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                thought_tokens=usage.thought_tokens,
                cached_tokens=usage.cached_tokens,
                cost_usd=usage.cost_usd if usage.cost_usd is not None else 0.0,
                cost_source="response_cost"
                if usage.cost_usd is not None
                else "missing",
            ),
        )
        return InteractionResult(
            extract_output_text(response), usage, _response_dict(response)
        )
    raise AssertionError("unreachable")
