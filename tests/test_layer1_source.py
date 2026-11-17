from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from beautyads.store.layer1_source import SYNC_NAME, PostgresLayer1Source
from beautyads.store.product_repository import _PRODUCT_COLUMNS

NOW = datetime(2026, 11, 15, tzinfo=UTC)


class Connection:
    def __init__(self):
        self.calls = []
        self.commits = self.rollbacks = 0

    def execute(self, query, params=()):
        self.calls.append((query, params))
        rows = []
        if "FROM changed" in query:
            data = {
                "brand": "synthetic",
                "source_url": "https://example.test/p",
                "category": "mask_pack",
                "name_ko": "합성 마스크",
                "aliases": '["stored alias"]',
                "skin_types": '["건성"]',
                "efficacy_texts": [],
                "functional_texts": [],
                "price_basis": "list_price",
                "updated_at": NOW,
            }
            rows = [tuple(data.get(c) for c in (*_PRODUCT_COLUMNS, "updated_at"))]
        elif "FROM product_ingredients" in query:
            rows = [
                (
                    "synthetic",
                    "https://example.test/p",
                    1,
                    "raw",
                    "표준명",
                    "resolved",
                    "kor_exact",
                    NOW,
                )
            ]
        elif "FROM product_certs" in query:
            rows = [
                (
                    "synthetic",
                    "https://example.test/p",
                    "brightening",
                    "unknown",
                    None,
                    "report",
                    NOW,
                )
            ]
        elif "FROM ingredient_standards" in query:
            rows = [("표준명", "INCI", "synthetic CAS")]
        elif "SELECT last_synced_at" in query:
            rows = [(NOW,)]
        return Mock(fetchall=lambda: rows)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_source_uses_product_and_child_change_times_then_reads_complete_sets():
    conn = Connection()
    rows = PostgresLayer1Source(conn).read_changed(since=NOW, limit=3)
    query, params = next((q, p) for q, p in conn.calls if "FROM changed" in q)
    assert (
        "p.updated_at" in query and "i.updated_at" in query and "c.updated_at" in query
    )
    assert "e.created_at" in query and "GREATEST" in query
    assert "updated_at > %s" in query and "LIMIT %s" in query and params == (NOW, 3)
    assert "properties_set" not in query
    children = [
        (q, p)
        for q, p in conn.calls
        if q.lstrip().startswith("SELECT") and "FROM changed" not in q
    ]
    assert all("updated_at >" not in q for q, _ in children)
    assert any(
        "FROM product_ingredients" in q and p == ("synthetic", "https://example.test/p")
        for q, p in children
    )
    assert rows[0].product.aliases == ["stored alias"]
    assert rows[0].ingredients[0].standard_name == "표준명"
    assert rows[0].certs[0].status == "unknown"
    assert rows[0].standards[0].cas_no == "synthetic CAS"
    assert rows[0].updated_at == NOW
    assert conn.rollbacks == 1 and conn.commits == 0
    assert conn.calls[0][0].startswith(
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
    )


def test_full_read_and_layer_specific_monotonic_watermark():
    conn = Connection()
    source = PostgresLayer1Source(conn)
    source.read_changed(since=None, limit=None)
    query, params = next((q, p) for q, p in conn.calls if "FROM changed" in q)
    assert "updated_at > %s" not in query and "LIMIT %s" not in query and params == ()
    assert source.get_watermark() == NOW
    assert conn.calls[-1][1] == (SYNC_NAME,)
    assert SYNC_NAME != "public_creatives_v1"
    source.set_watermark(NOW)
    assert "GREATEST" in conn.calls[-1][0]
    assert conn.calls[-1][1] == (SYNC_NAME, NOW)
    assert conn.commits == 1


@pytest.mark.parametrize("method", ["read_changed", "get_watermark", "set_watermark"])
def test_source_failure_rolls_back(method):
    conn = Connection()
    conn.execute = Mock(side_effect=RuntimeError("synthetic failure"))
    source = PostgresLayer1Source(conn)
    with pytest.raises(RuntimeError):
        if method == "read_changed":
            source.read_changed(since=NOW, limit=None)
        elif method == "set_watermark":
            source.set_watermark(NOW)
        else:
            source.get_watermark()
    assert conn.rollbacks == 1 and conn.commits == 0
