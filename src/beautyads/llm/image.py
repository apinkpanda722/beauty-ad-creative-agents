"""Text-only image generation, immediate accounting, and bounded byte validation."""

import base64
import binascii
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path

import litellm

from beautyads.obs import LedgerEntry, append_entry, check_cap, check_purpose_cap
from beautyads.settings import require_setting

from .chat import _call_error
from .errors import ErrorKind, classify_error

# Google Gemini API pricing, 1K image, checked 2026-11-17 (CONTRACTS.md P5 step 0).
# Source: https://ai.google.dev/gemini-api/docs/pricing
IMAGE_PRICE_USD = 0.0336
MAX_IMAGE_BYTES = 10_485_760
_MODEL = "gemini-3.1-flash-lite-image"
_monotonic = time.monotonic


@dataclass(frozen=True)
class ImageOutcome:
    ok: bool
    image_bytes: bytes | None = field(repr=False)
    mime: str | None
    size: int | None
    sha256: str | None
    cost_usd: float
    model: str
    code: str | None


def _get(value, name, default=None):
    """Read only selected fields, without dumping SDK objects or copying signatures."""
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _tokens(usage, name) -> int:
    value = _get(usage, name)
    return value if type(value) is int and value >= 0 else 0


def _decode(url: str) -> tuple[bytes | None, str | None]:
    header, separator, body = url.partition(",")
    if (
        not separator
        or not header.startswith("data:")
        or not header.endswith(";base64")
    ):
        return None, "IMAGE_DECODE_FAILED"
    if not body:
        return None, "IMAGE_MISSING"
    try:
        payload = base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError):
        # Never retain the data URL or the decoder's exception text.
        return None, "IMAGE_DECODE_FAILED"
    return payload, None


def _extract(response, *, cost: float, model: str) -> ImageOutcome:
    payload, code = None, "IMAGE_MISSING"
    for choice in _get(response, "choices") or []:
        message = _get(choice, "message")
        for item in _get(message, "images") or []:
            if _get(item, "type") != "image_url":
                continue
            url = _get(_get(item, "image_url"), "url")
            if not isinstance(url, str) or not url:
                continue
            payload, code = _decode(url)
            break
        if payload is not None or code != "IMAGE_MISSING":
            break

    mime = None
    if payload is not None:
        if len(payload) > MAX_IMAGE_BYTES:
            code = "IMAGE_TOO_LARGE"
        elif payload.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif payload.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
            mime = "image/webp"
        else:
            code = "IMAGE_MIME_UNSUPPORTED"
    if mime is None:
        return ImageOutcome(False, None, None, None, None, cost, model, code)
    return ImageOutcome(
        True,
        payload,
        mime,
        len(payload),
        sha256(payload).hexdigest(),
        cost,
        model,
        None,
    )


def generate_image(
    *,
    prompt: str,
    purpose_suffix: str = "plan",
    ledger_path: Path,
    caps: Mapping[str, float],
    purpose_caps: Mapping[str, float],
    model: str = _MODEL,
    api_key: str | None = None,
    timeout_s: float = 120.0,
    max_attempts: int = 3,
    backoff_s: Sequence[float] = (2.0, 5.0, 15.0),
    completion_fn=None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] | None = None,
) -> ImageOutcome:
    """Accept one text prompt; never replay a returned, potentially paid response."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("PROMPT_INVALID")
    if model != _MODEL:
        raise ValueError("IMAGE_MODEL_INVALID")
    if not isinstance(purpose_suffix, str) or not purpose_suffix.strip():
        raise ValueError("IMAGE_PURPOSE_INVALID")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    if max_attempts > 1 and not backoff_s:
        raise ValueError("backoff_s must not be empty when retrying")
    call = completion_fn if completion_fn is not None else litellm.completion
    kwargs = {
        "model": f"gemini/{model}",
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
        "timeout": timeout_s,
        "num_retries": 0,
    }
    for attempt in range(max_attempts):
        check_cap(ledger_path, "gemini", caps, additional_usd=IMAGE_PRICE_USD)
        check_purpose_cap(
            ledger_path, "image", purpose_caps["image"], additional_usd=IMAGE_PRICE_USD
        )
        if "api_key" not in kwargs:
            kwargs["api_key"] = (
                api_key if api_key is not None else require_setting("GEMINI_API_KEY")
            )
        try:
            started = _monotonic()
            response = call(**kwargs)
        except Exception as exc:  # noqa: BLE001 -- retry only classified dispatch errors
            kind = classify_error(exc)
            if kind == ErrorKind.RETRYABLE and attempt + 1 < max_attempts:
                sleep(backoff_s[min(attempt, len(backoff_s) - 1)])
                continue
            raise _call_error(exc, exhausted=kind == ErrorKind.RETRYABLE) from None
        duration_ms = int((_monotonic() - started) * 1000)
        break

    # Accounting and decoding are deliberately outside the dispatch retry loop.
    try:
        usage = _get(response, "usage")
        hidden = _get(response, "_hidden_params")
        response_cost = _get(hidden, "response_cost")
        measured = (
            type(response_cost) in (int, float)
            and isfinite(response_cost)
            and response_cost > 0
        )
        cost = response_cost if measured else IMAGE_PRICE_USD
        append_entry(
            ledger_path,
            LedgerEntry(
                ts=now() if now is not None else datetime.now(UTC),
                provider="gemini",
                model=model,
                requested_model=model,
                purpose="image-" + purpose_suffix,
                input_tokens=_tokens(usage, "prompt_tokens"),
                output_tokens=_tokens(usage, "completion_tokens"),
                cost_usd=cost,
                cost_source="response_cost" if measured else "price_table",
                reasoning_effort=None,
                duration_ms=duration_ms,
            ),
        )
        return _extract(response, cost=cost, model=model)
    except Exception as exc:  # noqa: BLE001 -- no raw response in errors or paid-call replay
        raise _call_error(exc) from None
