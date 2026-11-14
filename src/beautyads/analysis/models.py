"""Shared analysis identity, video inputs, and validated axis outcomes."""

import logging
import re
from typing import Any, NamedTuple

from pydantic import BaseModel

from beautyads.domain import Creative, CreativeKey, JobStatus, Source

ANALYSIS_MODEL_ID = "gemini-3.6-flash"
PROMPT_VERSIONS = {
    "content_type": "content-type-v1",
    "hook": "hook-v1",
    "full": "full-v1",
}
FINAL_RUN_TAG = "v1"

_logger = logging.getLogger("beautyads.analysis")
_URL = re.compile(r"https?://\S+")
# Key-like strings are masked before anything reaches a log (the wrapper only
# redacts the exact configured key).
_SECRETS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]+"),
    re.compile(
        r"(?i)\b(authorization|x-goog-api-key|api[_-]?key|access[_-]?token|token|secret|key)"
        r"\s*[=:]\s*\S+"
    ),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\bya29\.[A-Za-z0-9._\-]+"),
)


def _sanitize(text: str) -> str:
    text = _URL.sub("[url]", text)
    for pattern in _SECRETS:
        text = pattern.sub(
            lambda m: (m.group(1) + "=[redacted]") if m.lastindex else "[redacted]",
            text,
        )
    return text


def log_llm_failure(axis: str, exc: Exception) -> None:
    """Keep the reason a call failed (job rows only keep the code); URLs are dropped."""
    detail = _sanitize(str(exc))[:300]
    _logger.warning(
        "LLM_CALL_FAILED axis=%s kind=%s detail=%s",
        axis,
        getattr(exc, "kind", ""),
        detail,
    )


class VideoInput(NamedTuple):
    uri: str
    mime_type: str | None


def video_input_for(creative: Creative) -> VideoInput:
    """Only YouTube can supply its original URL without an upload."""
    if creative.source != Source.youtube:
        raise ValueError("UNSUPPORTED_SOURCE")
    if not creative.url:
        raise ValueError("NO_URL")
    return VideoInput(creative.url, None)


def models_match(requested: str, actual: str | None) -> bool:
    return actual is not None and (
        actual == requested or actual.startswith(requested + "-")
    )


class AxisOutcome(BaseModel):
    key: CreativeKey
    axis: str
    status: JobStatus
    labels: dict[str, Any] | None
    raw_output: str | None
    model: str | None
    model_matches_request: bool | None
    error_code: str | None
    attempts: int
    prompt_version: str
