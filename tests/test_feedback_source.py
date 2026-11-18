import json
from datetime import timedelta
from unittest.mock import Mock

import pytest
from test_feedback_sync_domain import NOW

from beautyads.store.feedback_source import SYNC_NAME, PostgresFeedbackSource
from beautyads.store.layer1_source import SYNC_NAME as LAYER1_NAME
from beautyads.store.links_source import SYNC_NAME as LAYER2_NAME
from beautyads.store.sync_source import SYNC_NAME as BASE_NAME


class Connection:
    def __init__(self, claims=None):
        self.calls = []
        self.commits = self.rollbacks = 0
        self.claims = ["hydration"] if claims is None else claims

    def execute(self, query, params=()):
        self.calls.append((query, params))
        rows = []
        if "FROM tenant_feedback" in query:
            dates = [NOW - timedelta(days=1), NOW, NOW + timedelta(seconds=1)]
            dates = [d for d in dates if "WHERE" not in query or d > params[0]]
            if "LIMIT" in query:
                dates = dates[: params[-1]]
            rows = [
                ("brand_a", i, "plan-1", "rejected", "question", self.claims, NOW, d)
                for i, d in enumerate(dates, 1)
            ]
        elif "SELECT last_synced_at" in query:
            rows = [(NOW,)]
        return Mock(fetchall=lambda: rows)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


@pytest.mark.parametrize("claims", [["hydration"], json.dumps(["hydration"])])
def test_changed_rows_use_bound_strict_source_time_and_exclude_private_text(claims):
    conn = Connection(claims)
    rows = PostgresFeedbackSource(conn).read_changed(since=NOW, limit=1)
    query, params = conn.calls[0]
    assert "updated_at > %s" in query and "LIMIT %s" in query
    assert "ORDER BY updated_at, id" in query
    assert params == (NOW, 1) and NOW.isoformat() not in query
    assert len(rows) == 1 and rows[0].updated_at > NOW
    assert rows[0].feedback_id == "1" and rows[0].claims == ("hydration",)
    assert "reason" not in query and "payload" not in query and "SELECT *" not in query
    assert conn.rollbacks == 1 and conn.commits == 0


def test_full_read_and_independent_monotonic_checkpoint():
    conn = Connection()
    source = PostgresFeedbackSource(conn)
    assert len(source.read_changed(since=None, limit=None)) == 3
    assert "WHERE" not in conn.calls[0][0] and "LIMIT" not in conn.calls[0][0]
    assert conn.calls[0][1] == ()
    assert SYNC_NAME not in {BASE_NAME, LAYER1_NAME, LAYER2_NAME}
    assert source.get_watermark() == NOW and conn.calls[-1][1] == (SYNC_NAME,)
    source.set_watermark(NOW)
    query, params = conn.calls[-1]
    assert "GREATEST(sync_state.last_synced_at, EXCLUDED.last_synced_at)" in query
    assert params == (SYNC_NAME, NOW) and SYNC_NAME not in query
    assert conn.commits == 1


@pytest.mark.parametrize("method", ["read_changed", "get_watermark", "set_watermark"])
def test_failure_rolls_back_without_commit(method):
    conn = Connection()
    conn.execute = Mock(side_effect=RuntimeError("synthetic failure"))
    source = PostgresFeedbackSource(conn)
    with pytest.raises(RuntimeError):
        if method == "read_changed":
            source.read_changed(since=None, limit=None)
        elif method == "get_watermark":
            source.get_watermark()
        else:
            source.set_watermark(NOW)
    assert conn.rollbacks == 1 and conn.commits == 0
