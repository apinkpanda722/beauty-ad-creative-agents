"""Synchronous persistence contracts, independent of storage SDKs."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from beautyads.domain.creative import CollectionStat, Creative, CreativeKey, JobStatus


class CreativeRepository(Protocol):
    def upsert_creatives(self, creatives: Sequence[Creative]) -> int: ...

    def get_creative(self, key: CreativeKey) -> Creative | None: ...

    def collection_stats(self) -> list[CollectionStat]: ...


class AnalysisRepository(Protocol):
    def enqueue_analysis(self, kind: str, creatives: Sequence[Creative]) -> int:
        """Enqueue only is_analyzable creatives and return the number enqueued."""
        ...

    def next_pending(self, kind: str, limit: int) -> list[Creative]: ...

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
        labels: Mapping[str, str] | None,
        error_code: str | None,
    ) -> None: ...
