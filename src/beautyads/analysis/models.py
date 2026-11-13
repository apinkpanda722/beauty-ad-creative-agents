"""Shared analysis identity, video inputs, and validated axis outcomes."""

from typing import Any, NamedTuple

from pydantic import BaseModel

from beautyads.domain import Creative, CreativeKey, JobStatus, Source

ANALYSIS_MODEL_ID = "gemini-3.6-flash"
PROMPT_VERSIONS = {
    "content_type": "content-type-v0",
    "hook": "hook-v0",
    "full": "full-v0",
}
FINAL_RUN_TAG = "v1"


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
