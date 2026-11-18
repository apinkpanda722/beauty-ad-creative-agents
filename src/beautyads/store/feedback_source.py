"""Read the minimal feedback projection; private text stays in PostgreSQL."""

import json
from datetime import datetime

from beautyads.domain.feedback_sync import FeedbackSyncSource, SyncFeedback
from beautyads.store.connection import SqlConnection
from beautyads.store.sync_source import PostgresGraphSyncSource

SYNC_NAME = "tenant_feedback_layer3_v1"


class PostgresFeedbackSource(FeedbackSyncSource):
    def __init__(self, conn: SqlConnection):
        self.conn = conn

    def read_changed(
        self, *, since: datetime | None, limit: int | None
    ) -> list[SyncFeedback]:
        query = """SELECT tenant_id, id, plan_id, decision, hook_type, claims,
                          created_at, updated_at FROM tenant_feedback"""
        params = []
        if since is not None:
            query += " WHERE updated_at > %s"
            params.append(since)
        query += " ORDER BY updated_at, id"
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        rows = PostgresGraphSyncSource(self.conn)._read(query, tuple(params))
        return [
            SyncFeedback(
                tenant_id=tenant_id,
                feedback_id=str(feedback_id),
                plan_id=plan_id,
                decision=decision,
                hook_type=hook_type,
                claims=tuple(json.loads(claims) if isinstance(claims, str) else claims),
                created_at=created_at,
                updated_at=updated_at,
            )
            for tenant_id, feedback_id, plan_id, decision, hook_type, claims, created_at, updated_at in rows
        ]

    def get_watermark(self) -> datetime | None:
        rows = PostgresGraphSyncSource(self.conn)._read(
            "SELECT last_synced_at FROM sync_state WHERE name = %s", (SYNC_NAME,)
        )
        return rows[0][0] if rows else None

    def set_watermark(self, value: datetime) -> None:
        try:
            self.conn.execute(
                """INSERT INTO sync_state (name, last_synced_at) VALUES (%s, %s)
                   ON CONFLICT (name) DO UPDATE SET last_synced_at =
                       GREATEST(sync_state.last_synced_at, EXCLUDED.last_synced_at)""",
                (SYNC_NAME, value),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
