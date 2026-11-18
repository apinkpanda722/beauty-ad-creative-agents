"""Interchangeable structured-output adapters with one validation correction."""

import asyncio
import json
import re
import time
from collections.abc import Callable, Coroutine, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from math import fsum
from pathlib import Path
from typing import Any, Protocol

import litellm
from pydantic import ValidationError

from beautyads.obs import CostCapExceeded
from beautyads.settings import require_setting

from .chat import (
    _MODELS,
    _UNSET,
    ChatResult,
    _call_error,
    _dict,
    chat_complete,
    precheck_call,
    record_usage,
)
from .errors import ErrorKind, LlmCallError, classify_error


@dataclass(frozen=True)
class StructuredSpec:
    name: str
    description: str
    schema: dict
    validate: Callable[[dict], Any]


class StructuredFailure(StrEnum):
    PARSE_FAILED = "PARSE_FAILED"
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
    TOOL_NOT_CALLED = "TOOL_NOT_CALLED"


@dataclass(frozen=True)
class StructuredResult:
    ok: bool
    value: Any | None
    failure: StructuredFailure | None
    attempts: int
    cost_usd: float
    # ChatResult summaries retain usage, finish_reason and costs, not response bodies.
    calls: list[ChatResult]


@dataclass
class StructuredStats:
    """Counts completed generate results, independently of transport retries.

    호출 수가 적으면(20호출 미만) 실패율이 우연일 수 있어 판단 근거로 쓰지 않는다.
    """

    calls: int = 0
    failed_after_retry: int = 0
    first_attempt_failures: dict[StructuredFailure, int] = field(
        default_factory=lambda: dict.fromkeys(StructuredFailure, 0)
    )
    first_attempt_failure_details: dict[str, int] = field(default_factory=dict)

    @property
    def failure_rate(self) -> float | None:
        return self.failed_after_retry / self.calls if self.calls else None

    def merge(self, other: "StructuredStats") -> "StructuredStats":
        """Return an independent sum without changing either source."""
        return StructuredStats(
            calls=self.calls + other.calls,
            failed_after_retry=self.failed_after_retry + other.failed_after_retry,
            first_attempt_failures={
                kind: self.first_attempt_failures.get(kind, 0)
                + other.first_attempt_failures.get(kind, 0)
                for kind in StructuredFailure
            },
            first_attempt_failure_details={
                key: self.first_attempt_failure_details.get(key, 0)
                + other.first_attempt_failure_details.get(key, 0)
                for key in self.first_attempt_failure_details
                | other.first_attempt_failure_details
            },
        )


class StructuredGenerator(Protocol):
    stats: StructuredStats

    def generate(
        self,
        spec: StructuredSpec,
        *,
        messages: Sequence[dict],
        purpose: str,
        ledger_path: Path,
        caps: Mapping[str, float],
        reasoning_effort: str | None = _UNSET,
        max_tokens: int | None = None,
        api_key: str | None = None,
        timeout_s: float = 120.0,
        max_attempts: int = 3,
        backoff_s: Sequence[float] = (2.0, 5.0, 15.0),
        completion_fn=None,
        acreate_fn=None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
    ) -> StructuredResult: ...


def run_coroutine_sync[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run on this thread unless its loop is already running; propagate failures."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


def _provider(model: str) -> str:
    if model.startswith("gpt-"):
        return "openai"
    if model.startswith("claude-"):
        return "anthropic"
    raise ValueError("STRUCTURED_MODEL_INVALID")


class _StructuredBase:
    provider: str | None = None

    def __init__(self, model: str):
        if self.provider is not None and _provider(model) != self.provider:
            raise ValueError("STRUCTURED_STYLE_INVALID")
        self.model = model
        self.stats = StructuredStats()

    def _instruction(self, spec: StructuredSpec) -> str:
        return f"{spec.description}\nSubmit only a JSON object matching the supplied schema."

    def _format(self, spec: StructuredSpec) -> dict:
        return {}

    def _complete(
        self, spec: StructuredSpec, messages: list[dict], options: dict
    ) -> ChatResult:
        chat_options = {
            key: value for key, value in options.items() if key != "acreate_fn"
        }
        return chat_complete(
            model=self.model, messages=messages, **chat_options, **self._format(spec)
        )

    def _parse(
        self, spec: StructuredSpec, result: ChatResult
    ) -> tuple[Any, StructuredFailure | None, list[tuple[str, str]]]:
        text = result.text
        if isinstance(text, str):
            fenced = re.fullmatch(
                r"\s*```(?:json)?\s*\n?(.*?)\s*```\s*", text, re.DOTALL | re.IGNORECASE
            )
            if fenced is not None:
                text = fenced.group(1)
        try:
            value = json.loads(text)
        except (TypeError, ValueError):
            return None, StructuredFailure.PARSE_FAILED, [("-", "parse_failed")]
        return _validate(spec, value)

    def generate(
        self,
        spec: StructuredSpec,
        *,
        messages: Sequence[dict],
        purpose: str,
        ledger_path: Path,
        caps: Mapping[str, float],
        reasoning_effort: str | None = _UNSET,
        max_tokens: int | None = None,
        api_key: str | None = None,
        timeout_s: float = 120.0,
        max_attempts: int = 3,
        backoff_s: Sequence[float] = (2.0, 5.0, 15.0),
        completion_fn=None,
        acreate_fn=None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
    ) -> StructuredResult:
        provider = _provider(self.model)
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
        options = {
            "purpose": purpose,
            "ledger_path": ledger_path,
            "caps": caps,
            "reasoning_effort": reasoning_effort,
            "max_tokens": max_tokens,
            "api_key": api_key,
            "timeout_s": timeout_s,
            "max_attempts": max_attempts,
            "backoff_s": backoff_s,
            "completion_fn": completion_fn,
            "acreate_fn": acreate_fn,
            "sleep": sleep,
            "now": now,
        }
        request = [
            {"role": "system", "content": self._instruction(spec)},
            *deepcopy(messages),
        ]
        calls = []
        first_failure = None
        first_details = []
        for attempt in (1, 2):
            response = self._complete(spec, request, options)
            calls.append(
                response._replace(
                    text=None, tool_calls=[], raw={}, usage=deepcopy(response.usage)
                )
            )
            value, failure, details = self._parse(spec, response)
            if failure is None or attempt == 2:
                result = StructuredResult(
                    ok=failure is None,
                    value=value,
                    failure=failure,
                    attempts=attempt,
                    cost_usd=fsum(call.cost_usd for call in calls),
                    calls=calls,
                )
                self.stats.calls += 1
                self.stats.failed_after_retry += int(not result.ok)
                if first_failure is not None:
                    counts = self.stats.first_attempt_failures
                    counts[first_failure] = counts.get(first_failure, 0) + 1
                    detail_counts = self.stats.first_attempt_failure_details
                    for path, kind in first_details:
                        key = _safe_detail(f"{spec.name}|{path}|{kind}")
                        detail_counts[key] = detail_counts.get(key, 0) + 1
                return result
            first_failure = failure
            first_details = details
            # Only locations and types are repeated, never values or error prose.
            detail_message = (
                " (" + "; ".join(f"{path}: {kind}" for path, kind in details[:3]) + ")"
                if failure == StructuredFailure.SCHEMA_VIOLATION and details
                else ""
            )
            request = [
                *request,
                {
                    "role": "user",
                    "content": f"Previous submission failed: {failure.value}{detail_message}. Correct it and submit again.\n{self._instruction(spec)}",
                },
            ]
        raise AssertionError("unreachable")


def _safe_detail(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.*:|-]", "_", value)[:120]


def _validate(
    spec: StructuredSpec, value: Any
) -> tuple[Any, StructuredFailure | None, list[tuple[str, str]]]:
    if not isinstance(value, dict):
        return None, StructuredFailure.SCHEMA_VIOLATION, [("-", "not_object")]
    try:
        return spec.validate(value), None, []
    except (LlmCallError, CostCapExceeded):
        raise
    except ValidationError as exc:
        details = []
        for error in exc.errors(
            include_url=False, include_context=False, include_input=False
        )[:5]:
            path = (
                ".".join(
                    "*" if isinstance(part, int) else str(part)
                    for part in error.get("loc", ())
                )
                or "-"
            )
            details.append((_safe_detail(path), _safe_detail(error.get("type", "-"))))
        return None, StructuredFailure.SCHEMA_VIOLATION, details
    except Exception as exc:  # noqa: BLE001 -- a caller-supplied validator signals invalid output by raising
        return (
            None,
            StructuredFailure.SCHEMA_VIOLATION,
            [("-", _safe_detail(f"exception:{type(exc).__name__}"))],
        )


class ToolCallStructured(_StructuredBase):
    """Anthropic default: submit through one named tool with automatic choice."""

    provider = "anthropic"

    def _instruction(self, spec: StructuredSpec) -> str:
        return f"{spec.description}\n반드시 {spec.name} 도구를 호출해 제출한다."

    def _format(self, spec: StructuredSpec) -> dict:
        return {
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": deepcopy(spec.schema),
                    },
                }
            ],
            "tool_choice": "auto",
        }

    def _parse(
        self, spec: StructuredSpec, result: ChatResult
    ) -> tuple[Any, StructuredFailure | None, list[tuple[str, str]]]:
        call = next(
            (call for call in result.tool_calls if call.name == spec.name), None
        )
        if call is None:
            return None, StructuredFailure.TOOL_NOT_CALLED, [("-", "tool_not_called")]
        if call.arguments_error is not None or call.arguments is None:
            return None, StructuredFailure.PARSE_FAILED, [("-", "parse_failed")]
        return _validate(spec, call.arguments)


class InstructionJsonStructured(_StructuredBase):
    """Instruction-only JSON fallback, explicitly selected by the factory."""

    def _instruction(self, spec: StructuredSpec) -> str:
        return f"{spec.description}\nReturn only JSON matching this schema:\n{json.dumps(spec.schema, ensure_ascii=False)}"


class JsonSchemaStructured(_StructuredBase):
    """OpenAI default: strict JSON schema via the common chat wrapper."""

    provider = "openai"

    def _format(self, spec: StructuredSpec) -> dict:
        return {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": spec.name,
                    "description": spec.description,
                    "strict": True,
                    "schema": deepcopy(spec.schema),
                },
            }
        }


class NativeAnthropicStructured(_StructuredBase):
    """Opt-in native async messages API, exposed through the synchronous contract."""

    provider = "anthropic"

    def _complete(
        self, spec: StructuredSpec, messages: list[dict], options: dict
    ) -> ChatResult:
        system, conversation = [], []
        for message in messages:
            if message.get("role") == "system":
                content = message.get("content")
                if isinstance(content, str):
                    system.append({"type": "text", "text": content})
                elif isinstance(content, list):
                    system.extend(deepcopy(content))
            else:
                conversation.append(message)
        # Changing output_config.format invalidates that conversation's prompt cache.
        kwargs = {
            "model": self.model,
            "messages": conversation,
            "system": system,
            "max_tokens": options.get("max_tokens") or 4096,
            "output_config": {
                "format": {"type": "json_schema", "schema": deepcopy(spec.schema)}
            },
            "timeout": options.get("timeout_s"),
            "num_retries": 0,
        }
        call = options.get("acreate_fn")
        if call is None:
            call = litellm.anthropic.messages.acreate
        max_attempts = options.get("max_attempts")
        for attempt in range(max_attempts):
            precheck_call(
                self.model,
                ledger_path=options.get("ledger_path"),
                caps=options.get("caps"),
            )
            if "api_key" not in kwargs:
                key = options.get("api_key")
                kwargs["api_key"] = (
                    key if key is not None else require_setting("ANTHROPIC_API_KEY")
                )
            try:
                response = run_coroutine_sync(call(**kwargs))
            except (LlmCallError, CostCapExceeded):
                raise
            except Exception as exc:  # noqa: BLE001 -- retry only classified transport failures
                kind = classify_error(exc)
                if kind == ErrorKind.RETRYABLE and attempt + 1 < max_attempts:
                    backoff = options.get("backoff_s")
                    options.get("sleep")(backoff[min(attempt, len(backoff) - 1)])
                    continue
                raise _call_error(exc, exhausted=kind == ErrorKind.RETRYABLE) from None
            break
        # Once dispatch returns, parsing/accounting failures must never replay a paid call.
        raw = _dict(response)
        usage = raw.get("usage") or {}
        cost, source = record_usage(
            model=self.model,
            purpose=options.get("purpose"),
            ledger_path=options.get("ledger_path"),
            usage=usage,
            response_cost=None,
            reasoning_effort=None,
            now=options.get("now"),
        )
        text = (
            "".join(
                block.get("text")
                for block in raw.get("content") or []
                if isinstance(block, Mapping)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            )
            or None
        )
        return ChatResult(text, [], raw.get("stop_reason"), usage, cost, source, raw)


def make_structured(model: str, *, style: str = "default") -> StructuredGenerator:
    """Select an adapter without automatic style switching or network calls."""
    if model not in _MODELS:
        raise ValueError("STRUCTURED_MODEL_INVALID")
    provider = _provider(model)
    if style == "default":
        cls = ToolCallStructured if provider == "anthropic" else JsonSchemaStructured
    elif style == "instruction":
        cls = InstructionJsonStructured
    elif style == "native" and provider == "anthropic":
        cls = NativeAnthropicStructured
    else:
        raise ValueError("STRUCTURED_STYLE_INVALID")
    return cls(model)
