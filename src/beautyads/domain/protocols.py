"""Synchronous persistence contracts, independent of storage SDKs."""

from collections.abc import Collection, Mapping, Sequence
from typing import Any, Protocol

from beautyads.domain.creative import (
    CollectionStat,
    Creative,
    CreativeKey,
    JobStatus,
    Source,
)
from beautyads.domain.jobs import JobResult


class CreativeRepository(Protocol):
    def upsert_creatives(self, creatives: Sequence[Creative]) -> int: ...

    def get_creative(self, key: CreativeKey) -> Creative | None: ...

    def collection_stats(self) -> list[CollectionStat]: ...

    def list_creatives(
        self,
        *,
        brands: Collection[str] | None = None,
        sources: Collection[Source] | None = None,
        analyzable_only: bool = False,
        limit: int | None = None,
    ) -> list[Creative]:
        """Newest first, NULL dates last, then source and source_id to break ties."""
        ...


class AnalysisRepository(Protocol):
    def enqueue_analysis(self, kind: str, creatives: Sequence[Creative]) -> int:
        """Enqueue only is_analyzable creatives and return the number enqueued."""
        ...

    def next_pending(self, kind: str, limit: int) -> list[Creative]: ...

    def requeue_jobs(self, kind: str, error_codes: Collection[str]) -> int:
        """Return failed jobs with selected error codes to pending, refreshing time."""
        ...

    def job_counts(self, kind: str) -> dict[str, int]:
        """Count all four statuses, including zero counts."""
        ...

    def get_job_results(
        self, kind: str, keys: Sequence[CreativeKey]
    ) -> list[JobResult]:
        """Return existing jobs with the latest output for the same creative and kind."""
        ...

    def record_analysis(
        self,
        kind: str,
        key: CreativeKey,
        *,
        status: JobStatus,
        model: str | None,
        thinking_level: str | None,
        prompt_version: str | None,
        raw_output: str | None,
        labels: Mapping[str, Any] | None,
        error_code: str | None,
    ) -> None: ...
