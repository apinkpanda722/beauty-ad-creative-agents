"""Shared creative identity, metadata, metrics, and analysis eligibility."""

from datetime import datetime
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Source(StrEnum):
    youtube = "youtube"
    instagram = "instagram"
    tiktok = "tiktok"


class JobStatus(StrEnum):
    pending = "pending"
    done = "done"
    held = "held"
    failed = "failed"


class Metrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None


class CreativeKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Source
    source_id: str = Field(min_length=1)


class Creative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Source
    source_id: str = Field(min_length=1)
    url: str | None = None
    title: str | None = None
    caption: str | None = None
    published_at: datetime | None = None
    duration_s: float | None = None
    language: str | None = None
    analyzable: bool | None = None
    brand: str | None = None
    account: str | None = None
    metrics: Metrics = Field(default_factory=Metrics)
    collected_at: AwareDatetime

    @property
    def key(self) -> CreativeKey:
        return CreativeKey(source=self.source, source_id=self.source_id)


class CollectionStat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Source
    brand: str | None
    account: str | None
    total: int
    analyzable_true: int
    analyzable_false: int
    analyzable_null: int
    last_collected_at: datetime | None


def is_analyzable(creative: Creative) -> bool:
    """Only an explicit positive decision permits analysis."""
    return creative.analyzable is True
