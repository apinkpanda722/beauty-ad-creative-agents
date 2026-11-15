"""Read PostgreSQL changes and completed final labels without model outputs."""

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from beautyads.domain.creative import CreativeKey
from beautyads.domain.sync import GraphSyncSource, SyncCreative, SyncLabel
from beautyads.store.connection import SqlConnection

SYNC_COLUMNS = (
    "source",
    "source_id",
    "url",
    "published_at",
    "duration_s",
    "language",
    "brand",
    "latest_view_count",
    "latest_like_count",
    "latest_comment_count",
    "metrics_collected_at",
    "updated_at",
)
# Keep the shared legacy columns unchanged: layer-two SQL reuses them.
ADVERTISER_SYNC_COLUMNS = (*SYNC_COLUMNS, "advertiser_name")
_ADVERTISER_COLUMN = (
    "CASE WHEN c.source = 'tiktok' THEN "
    "c.attributes->>'advertiser_business_name' ELSE NULL END AS advertiser_name"
)


def _creative_properties(row):
    # The optional new column also accepts legacy source rows without it.
    names = (
        ADVERTISER_SYNC_COLUMNS
        if len(row) == len(ADVERTISER_SYNC_COLUMNS)
        else SYNC_COLUMNS
    )
    properties = dict(zip(names, row, strict=True))
    properties.setdefault("advertiser_name", None)
    return properties


SYNC_NAME = "public_creatives_v1"


def _kinds(run_tag: str) -> list[str]:
    return [f"{axis}@{run_tag}" for axis in ("content_type", "hook", "full")]


class PostgresGraphSyncSource(GraphSyncSource):
    def __init__(self, conn: SqlConnection):
        self.conn = conn

    def _read(self, query: str, params: Sequence[Any]):
        try:
            rows = self.conn.execute(query, params).fetchall()
        except Exception:
            self.conn.rollback()
            raise
        self.conn.rollback()
        return rows

    def read_changed(
        self, *, since: datetime | None, limit: int | None, run_tag: str
    ) -> list[SyncCreative]:
        columns = ", ".join(f"c.{column}" for column in SYNC_COLUMNS[:-1])
        query = f"""
            WITH changed AS (
                SELECT {columns}, {_ADVERTISER_COLUMN},
                    GREATEST(c.updated_at, COALESCE(
                        (SELECT max(j.updated_at) FROM analysis_jobs AS j
                         WHERE j.source = c.source AND j.source_id = c.source_id
                           AND j.kind = ANY(%s)), c.updated_at)) AS updated_at
                FROM creatives AS c
            )
            SELECT {", ".join(ADVERTISER_SYNC_COLUMNS)} FROM changed
        """
        params: list[Any] = [_kinds(run_tag)]
        if since is not None:
            query += " WHERE updated_at > %s"
            params.append(since)
        query += " ORDER BY updated_at, source, source_id"
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        result = []
        for row in self._read(query, tuple(params)):
            properties = _creative_properties(row)
            result.append(SyncCreative(properties, properties.pop("updated_at")))
        return result

    def read_sample(self, *, limit: int, run_tag: str) -> list[SyncCreative]:
        columns = ", ".join(f"c.{column}" for column in SYNC_COLUMNS[:-1])
        done = "done"
        query = f"""
            WITH ranked AS (
                SELECT {columns}, {_ADVERTISER_COLUMN},
                    GREATEST(c.updated_at, COALESCE(
                        (SELECT max(j.updated_at) FROM analysis_jobs AS j
                         WHERE j.source = c.source AND j.source_id = c.source_id
                           AND j.kind = ANY(%s)), c.updated_at)) AS updated_at,
                    EXISTS (SELECT 1 FROM analysis_jobs AS j
                            WHERE j.source = c.source AND j.source_id = c.source_id
                              AND j.kind = ANY(%s) AND j.status = %s) AS has_axis,
                    EXISTS (SELECT 1 FROM analysis_jobs AS j
                            WHERE j.source = c.source AND j.source_id = c.source_id
                              AND j.kind = ANY(%s) AND j.status = %s) AS has_label
                FROM creatives AS c
            )
            SELECT {", ".join(ADVERTISER_SYNC_COLUMNS)} FROM ranked
            ORDER BY has_axis DESC, has_label DESC, updated_at, source, source_id
            LIMIT %s
        """
        axis_kinds = [f"{axis}@{run_tag}" for axis in ("hook", "full")]
        params = (_kinds(run_tag), axis_kinds, done, _kinds(run_tag), done, limit)
        result = []
        for row in self._read(query, params):
            properties = _creative_properties(row)
            result.append(SyncCreative(properties, properties.pop("updated_at")))
        return result

    def read_labels(self, key: CreativeKey, *, run_tag: str) -> list[SyncLabel]:
        rows = self._read(
            """SELECT kind, status, labels FROM analysis_jobs
               WHERE source = %s AND source_id = %s
                 AND kind = ANY(%s) AND status = %s ORDER BY kind""",
            (key.source.value, key.source_id, _kinds(run_tag), "done"),
        )
        return [
            SyncLabel(
                kind,
                status,
                json.loads(labels) if isinstance(labels, str) else labels,
            )
            for kind, status, labels in rows
        ]

    def get_watermark(self) -> datetime | None:
        rows = self._read(
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
