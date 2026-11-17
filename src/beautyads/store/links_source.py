"""Coherent PostgreSQL inputs for links, including same-brand product changes."""

import json
from datetime import datetime

from beautyads.domain.links import LinkCreative, LinksSnapshot, LinksSource
from beautyads.domain.products import Product
from beautyads.domain.sync import SyncCreative, SyncLabel
from beautyads.store.connection import SqlConnection
from beautyads.store.product_repository import _PRODUCT_COLUMNS, _restore
from beautyads.store.sync_source import SYNC_COLUMNS, PostgresGraphSyncSource

SYNC_NAME = "public_links_layer2_v1"
LINK_COLUMNS = (*SYNC_COLUMNS[:-1], "title", "caption", "updated_at")
KINDS = ("content_type@v1", "hook@v1", "full@v1", "ingredient-matches@v1")


class PostgresLinksSource(LinksSource):
    def __init__(self, conn: SqlConnection):
        self.conn = conn

    def read_snapshot(
        self, *, since: datetime | None, limit: int | None
    ) -> LinksSnapshot:
        query = f"""
            WITH changed AS (
                SELECT {", ".join(f"c.{column}" for column in LINK_COLUMNS[:-1])},
                    GREATEST(c.updated_at,
                        (SELECT max(j.updated_at) FROM analysis_jobs AS j
                         WHERE j.source = c.source AND j.source_id = c.source_id
                           AND (j.kind = ANY(%s) OR j.kind = 'product-id@v1')),
                        (SELECT max(p.updated_at) FROM products AS p
                         WHERE p.brand = c.brand)) AS updated_at
                FROM creatives AS c
            )
            SELECT {", ".join(LINK_COLUMNS)} FROM changed
        """
        ordered = " ORDER BY updated_at, source, source_id"
        changed_query = query
        params = [list(KINDS)]
        if since is not None:
            changed_query += " WHERE updated_at > %s"
            params.append(since)
        changed_query += ordered
        if limit is not None:
            changed_query += " LIMIT %s"
            params.append(limit)
        try:
            self.conn.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            changed = self.conn.execute(changed_query, tuple(params)).fetchall()
            # Products, labels and changed creatives share this one snapshot.
            # Reporting uses the applied batch; --full provides global coverage.
            product_rows = self.conn.execute(
                f"SELECT {', '.join((*_PRODUCT_COLUMNS, 'updated_at'))} FROM products ORDER BY brand, source_url"
            ).fetchall()
            products = [
                _restore(Product, (*_PRODUCT_COLUMNS, "updated_at"), row)
                for row in product_rows
            ]
            labels = self.conn.execute(
                """SELECT source, source_id, kind, status, labels FROM analysis_jobs
                   WHERE (kind = ANY(%s) OR kind = 'product-id@v1') AND status = %s
                   ORDER BY source, source_id, kind""",
                (list(KINDS), "done"),
            ).fetchall()
            by_key = {}
            for source, source_id, kind, status, data in labels:
                by_key.setdefault((source, source_id), []).append(
                    SyncLabel(
                        kind,
                        status,
                        json.loads(data) if isinstance(data, str) else data,
                    )
                )

            def restore(rows):
                result = []
                for row in rows:
                    properties = dict(zip(LINK_COLUMNS, row, strict=True))
                    updated_at = properties.pop("updated_at")
                    result.append(
                        LinkCreative(
                            SyncCreative(properties, updated_at),
                            by_key.get(
                                (properties.get("source"), properties.get("source_id")),
                                (),
                            ),
                        )
                    )
                return result

            snapshot = LinksSnapshot(restore(changed), products)
        except Exception:
            self.conn.rollback()
            raise
        self.conn.rollback()
        return snapshot

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
