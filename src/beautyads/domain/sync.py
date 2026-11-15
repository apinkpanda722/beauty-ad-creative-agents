"""Storage-independent input and source contract for the public graph skeleton."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from beautyads.domain.creative import CreativeKey

SYNC_OVERLAP = timedelta(minutes=10)


@dataclass(frozen=True)
class SyncCreative:
    properties: Mapping[str, Any]
    # Maximum PostgreSQL change time of this creative and its final analysis jobs.
    updated_at: datetime

    @property
    def key(self) -> CreativeKey:
        return CreativeKey(
            source=self.properties.get("source"),
            source_id=self.properties.get("source_id"),
        )


@dataclass(frozen=True)
class SyncLabel:
    kind: str
    status: str
    labels: Mapping[str, Any] | None


class GraphSyncSource(Protocol):
    def read_changed(
        self, *, since: datetime | None, limit: int | None, run_tag: str
    ) -> list[SyncCreative]:
        """Return source changes strictly after since, or all rows if it is None."""
        ...

    def read_labels(self, key: CreativeKey, *, run_tag: str) -> list[SyncLabel]: ...

    def get_watermark(self) -> datetime | None: ...

    def set_watermark(self, value: datetime) -> None:
        """Persist only after all graph writes succeed, never moving backwards."""
        ...
