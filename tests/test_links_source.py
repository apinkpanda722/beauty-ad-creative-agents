import json
from unittest.mock import Mock

import pytest
from test_links_domain import NOW, product

from beautyads.domain import links as links_domain
from beautyads.store.links_source import LINK_COLUMNS, SYNC_NAME, PostgresLinksSource
from beautyads.store.product_repository import _PRODUCT_COLUMNS


class Connection:
    def __init__(self):
        self.calls = []
        self.commits = self.rollbacks = 0

    def execute(self, query, params=()):
        self.calls.append((query, params))
        rows = []
        if "FROM changed" in query:
            data = {
                "source": "youtube",
                "source_id": "1",
                "brand": "dev",
                "title": "合成",
                "caption": "caption",
                "updated_at": NOW,
            }
            rows = [tuple(data.get(c) for c in LINK_COLUMNS)]
        elif "FROM products ORDER BY" in query:
            data = product().model_dump()
            data["updated_at"] = NOW
            data["aliases"] = json.dumps(["stored alias"])
            rows = [tuple(data.get(c) for c in (*_PRODUCT_COLUMNS, "updated_at"))]
        elif "FROM analysis_jobs" in query:
            rows = [
                (
                    "youtube",
                    "1",
                    "content_type@v1",
                    "done",
                    '{"content_type":"product_creative"}',
                ),
                (
                    "youtube",
                    "1",
                    "full@v1",
                    "done",
                    {"claims": ["hydration"], "ingredients": ["raw"]},
                ),
                ("youtube", "1", "ingredient-matches@v1", "done", {"ingredients": []}),
            ]
        elif "SELECT last_synced_at" in query:
            rows = [(NOW,)]
        return Mock(fetchall=lambda: rows)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_snapshot_reads_text_products_final_labels_and_product_changes_together():
    conn = Connection()
    snapshot = PostgresLinksSource(conn).read_snapshot(since=NOW, limit=3)
    queries = [(q, p) for q, p in conn.calls if "FROM changed" in q]
    changed, params = queries[0]
    assert "c.title" in changed and "c.caption" in changed
    assert (
        "GREATEST" in changed
        and "c.updated_at" in changed
        and "j.updated_at" in changed
    )
    assert "p.updated_at" in changed and "p.brand = c.brand" in changed
    assert "kind = ANY(%s)" in changed and "updated_at > %s" in changed
    assert "ORDER BY updated_at, source, source_id" in changed and "LIMIT %s" in changed
    assert params[-2:] == (NOW, 3)
    assert set(params[0]) == {
        "content_type@v1",
        "hook@v1",
        "full@v1",
        "ingredient-matches@v1",
    }
    assert len(queries) == 1
    assert snapshot.changed[0].creative.properties["title"] == "合成"
    assert snapshot.changed[0].creative.properties["caption"] == "caption"
    assert snapshot.changed[0].creative.updated_at == NOW
    assert snapshot.products[0].aliases == ["stored alias"]
    assert len(snapshot.changed[0].labels) == 3
    label_query, label_params = next(
        (q, p) for q, p in conn.calls if "SELECT source, source_id, kind" in q
    )
    assert "status = %s" in label_query and label_params[-1] == "done"
    assert "raw_output" not in " ".join(q for q, _ in conn.calls)
    assert conn.calls[0][0].startswith(
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
    )
    assert conn.rollbacks == 1 and conn.commits == 0


def test_full_snapshot_and_separate_monotonic_checkpoint():
    conn = Connection()
    source = PostgresLinksSource(conn)
    snapshot = source.read_snapshot(since=None, limit=None)
    queries = [(q, p) for q, p in conn.calls if "FROM changed" in q]
    assert len(queries) == 1 and "updated_at >" not in queries[0][0]
    assert "LIMIT" not in queries[0][0] and len(queries[0][1]) == 1
    assert len(snapshot.changed) == 1
    assert source.get_watermark() == NOW and conn.calls[-1][1] == (SYNC_NAME,)
    assert SYNC_NAME not in {"public_products_layer1_v1", "public_creatives_v1"}
    source.set_watermark(NOW)
    assert "GREATEST" in conn.calls[-1][0] and conn.calls[-1][1] == (SYNC_NAME, NOW)
    assert conn.commits == 1


@pytest.mark.parametrize("method", ["read_snapshot", "get_watermark", "set_watermark"])
def test_source_failure_rolls_back_without_committing(method):
    conn = Connection()
    conn.execute = Mock(side_effect=RuntimeError("synthetic failure"))
    source = PostgresLinksSource(conn)
    with pytest.raises(RuntimeError):
        if method == "read_snapshot":
            source.read_snapshot(since=NOW, limit=1)
        elif method == "get_watermark":
            source.get_watermark()
        else:
            source.set_watermark(NOW)
    assert conn.rollbacks == 1 and conn.commits == 0


def test_failure_mid_snapshot_rolls_back_and_does_not_return_partial_input():
    conn = Connection()
    execute = conn.execute

    def fail_labels(query, params=()):
        if "SELECT source, source_id, kind" in query:
            raise RuntimeError("synthetic label failure")
        return execute(query, params)

    conn.execute = fail_labels
    with pytest.raises(RuntimeError):
        PostgresLinksSource(conn).read_snapshot(since=None, limit=None)
    assert conn.rollbacks == 1 and conn.commits == 0


def test_video_job_is_read_and_participates_in_incremental_change_time(monkeypatch):
    monkeypatch.setattr(links_domain, "PRODUCT_ID_APPROVED_TAG", "v2")
    conn = Connection()
    execute = conn.execute

    def with_video(query, params=()):
        cursor = execute(query, params)
        if "SELECT source, source_id, kind" in query:
            rows = cursor.fetchall()
            rows.append(
                (
                    "youtube",
                    "1",
                    "product-id@v2",
                    "done",
                    {"products": [product().key.model_dump()]},
                )
            )
            return Mock(fetchall=lambda: rows)
        return cursor

    conn.execute = with_video
    snapshot = PostgresLinksSource(conn).read_snapshot(since=NOW, limit=None)
    assert snapshot.changed[0].final_labels("product-id@v2")["products"]
    for query, params in conn.calls:
        if "FROM changed" in query or "SELECT source, source_id, kind" in query:
            assert "product-id@v2" in params[0]


def test_unapproved_video_jobs_are_not_read_or_part_of_change_time():
    assert links_domain.PRODUCT_ID_APPROVED_TAG == ""
    conn = Connection()
    PostgresLinksSource(conn).read_snapshot(since=NOW, limit=None)
    for query, params in conn.calls:
        assert "product-id" not in query
        assert not any(
            isinstance(p, list) and any("product-id" in str(k) for k in p)
            for p in params
        )
