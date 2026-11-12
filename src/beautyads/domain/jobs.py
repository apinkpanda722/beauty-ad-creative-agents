"""Persisted analysis jobs together with their latest model output."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from beautyads.domain.creative import CreativeKey, JobStatus


class JobResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: CreativeKey
    kind: str
    status: JobStatus
    labels: dict[str, Any] | None
    error_code: str | None
    model: str | None
    thinking_level: str | None
    prompt_version: str | None
    raw_output: str | None
    attempts: int
    updated_at: datetime | None
