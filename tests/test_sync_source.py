from datetime import UTC, datetime

import pytest

from beautyads.domain import CreativeKey
from beautyads.store.sync_source import SYNC_COLUMNS, PostgresGraphSyncSource

NOW = datetime(2026, 11, 15, tzinfo=UTC)


class Connection:
    def __init__(self, rows=()):
        self.rows = rows
        self.calls = []
        self.commits = self.rollbacks = 0

    def execute(self, query, params=()):
        self.calls.append((query, params))
        return self

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return next(iter(self.rows), None)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_changed_query_uses_both_timestamps_and_bound_parameters():
    values = {
        "source": "youtube",
        "source_id": "marker",
        "updated_at": NOW,
        "latest_view_count": "9",
    }
    conn = Connection([tuple(values.get(c) for c in SYNC_COLUMNS)])
    source = PostgresGraphSyncSource(conn)
    rows = source.read_changed(since=NOW, limit=50, run_tag="v1")
    query, params = conn.calls[0]
    assert "c.updated_at" in query and "j.updated_at" in query
    assert "GREATEST" in query and "> %s" in query
    assert "LIMIT %s" in query
    assert params == (["content_type@v1", "hook@v1", "full@v1"], NOW, 50)
    assert NOW.isoformat() not in query and "@v1" not in query
    assert "properties_set" not in query
    assert rows[0].updated_at == NOW
    assert rows[0].properties["latest_view_count"] == "9"
    assert "updated_at" not in rows[0].properties
    assert conn.rollbacks == 1


def test_full_read_has_no_cutoff():
    conn = Connection()
    assert (
        PostgresGraphSyncSource(conn).read_changed(since=None, limit=None, run_tag="v1")
        == []
    )
    query, params = conn.calls[0]
    assert "> %s" not in query and "LIMIT" not in query
    assert params == (["content_type@v1", "hook@v1", "full@v1"],)


def test_labels_select_only_done_final_jobs_by_key():
    conn = Connection(
        [("hook@v1", "done", '{"hook_description":"marker","hook_type":"question"}')]
    )
    source = PostgresGraphSyncSource(conn)
    rows = source.read_labels(
        CreativeKey(source="youtube", source_id="marker"), run_tag="v1"
    )
    query, params = conn.calls[0]
    assert "kind = ANY(%s)" in query and "status = %s" in query
    assert params == (
        "youtube",
        "marker",
        ["content_type@v1", "hook@v1", "full@v1"],
        "done",
    )
    assert "marker" not in query
    assert rows[0].labels == {"hook_type": "question", "hook_description": "marker"}
    assert rows[0].kind == "hook@v1"
    assert conn.rollbacks == 1


def test_watermark_is_persisted_monotonically_and_missing_is_none():
    conn = Connection()
    source = PostgresGraphSyncSource(conn)
    assert source.get_watermark() is None
    conn.rows = [(NOW,)]
    assert source.get_watermark() == NOW
    source.set_watermark(NOW)
    query, params = conn.calls[-1]
    assert "ON CONFLICT" in query and "GREATEST" in query
    assert params[-1] == NOW
    assert conn.commits == 1 and conn.rollbacks == 2


@pytest.mark.parametrize(
    "method", ["read_changed", "read_labels", "get_watermark", "set_watermark"]
)
def test_failed_database_operations_rollback(method):
    conn = Connection()

    def broken(*args, **kwargs):
        raise RuntimeError("synthetic failure")

    conn.execute = broken
    source = PostgresGraphSyncSource(conn)
    arguments = {
        "read_changed": lambda: source.read_changed(since=NOW, limit=1, run_tag="v1"),
        "read_labels": lambda: source.read_labels(
            CreativeKey(source="youtube", source_id="marker"), run_tag="v1"
        ),
        "get_watermark": source.get_watermark,
        "set_watermark": lambda: source.set_watermark(NOW),
    }
    with pytest.raises(RuntimeError):
        arguments[method]()
    assert conn.rollbacks == 1 and conn.commits == 0
