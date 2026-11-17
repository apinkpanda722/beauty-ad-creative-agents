"""Text-free PostgreSQL feedback projection and incremental source contract."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

# Kept equal to domain.tenant._TENANT_PATTERN by a contract test; the tenant
# memory contract remains unchanged while graph validation shares this constant.
TENANT_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{1,31}")


@dataclass(frozen=True)
class SyncFeedback:
    tenant_id: str
    feedback_id: str
    plan_id: str
    decision: str
    hook_type: str | None
    claims: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


class FeedbackSyncSource(Protocol):
    def read_changed(
        self, *, since: datetime | None, limit: int | None
    ) -> list[SyncFeedback]:
        """Read changes strictly after since (the caller applies overlap)."""
        ...

    def get_watermark(self) -> datetime | None: ...

    def set_watermark(self, value: datetime) -> None:
        """Advance monotonically only after graph writes succeed."""
        ...
