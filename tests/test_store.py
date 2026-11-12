"""Store contracts exercised only with scripted connections, never a database."""

import json
import re
import traceback
from collections import deque
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlparse

import psycopg
import pytest
from beautyads.store.connection import StoreConnectError, connect, postgres_dsn
from beautyads.store.repository import CREATIVE_COLUMNS, PostgresCreativeStore
from beautyads.store.schema import (
    CHANGE_COLUMNS,
    MIGRATIONS,
    apply_migrations,
    build_upsert_sql,
)

from beautyads.domain import Creative, CreativeKey, JobStatus, Metrics, Source
from beautyads.settings import MissingSetting

NOW = datetime(2026, 11, 12, tzinfo=UTC)


class FakeCursor:
    def __init__(self, rows=(), rowcount=1):
        self.rows = list(rows)
        self.rowcount = rowcount

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return next(iter(self.rows), None)


class FakeConnection:
    def __init__(self, replies=(), *, fail_on=None):
        self.replies = deque(replies)
        self.fail_on = fail_on
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query, params=None):
        self.calls.append((query, params))
        if self.fail_on and self.fail_on(query):
            raise RuntimeError("scripted SQL failure")
        return self.replies.popleft() if self.replies else FakeCursor()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def creative(**changes):
    return Creative.model_validate(
        {"source": "youtube", "source_id": "video-1", "collected_at": NOW, **changes}
    )


def calls_for(conn, fragment):
    return [(query, params) for query, params in conn.calls if fragment in query]


def creative_row(item):
    values = item.model_dump(exclude={"metrics"})
    values.update(
        {f"latest_{key}": value for key, value in item.metrics.model_dump().items()}
    )
    return tuple(values[column] for column in CREATIVE_COLUMNS)


def test_migrations_apply_once_and_commit_each_version():
    conn = FakeConnection([FakeCursor(), FakeCursor()])
    versions = [version for version, _, _ in MIGRATIONS]
    assert versions == sorted(set(versions))
    assert versions[0] == 1
    assert apply_migrations(conn) == versions
    assert conn.commits == len(versions)
    recorded = calls_for(conn, "INSERT INTO schema_migrations")
    assert [params for _, params in recorded] == [
        (version, name) for version, name, _ in MIGRATIONS
    ]
    for _, name, _ in MIGRATIONS:
        assert all(name not in query for query, _ in recorded)
    conn.replies.extend(
        [FakeCursor(), FakeCursor([(version,) for version in versions])]
    )
    before = len(conn.calls)
    assert apply_migrations(conn) == []
    assert conn.commits == len(versions) + 1  # finish the read/bootstrap transaction
    assert not calls_for_queries(conn.calls[before:], "INSERT INTO schema_migrations")


def calls_for_queries(calls, fragment):
    return [(query, params) for query, params in calls if fragment in query]


def test_migrations_are_additive_and_contain_required_schema():
    sql = "\n".join(sql for _, _, sql in MIGRATIONS)
    assert not re.search(r"\b(DROP|TRUNCATE)\b", sql, re.IGNORECASE)
    creates = re.findall(
        r"\bCREATE\s+\w+\s+(?:IF\s+NOT\s+EXISTS\s+)?\w+", sql, re.IGNORECASE
    )
    assert creates and all(
        "IF NOT EXISTS" in statement.upper() for statement in creates
    )
    for table in (
        "creatives",
        "metrics_history",
        "model_outputs",
        "analysis_jobs",
        "sync_state",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert re.search(
        r"updated_at\s+timestamptz\s+not null\s+default now\(\)", sql, re.IGNORECASE
    )
    assert "prompt_version text" in sql
    assert "raw_output text" in sql
    assert "PRIMARY KEY (source, source_id, collected_at)" in sql
    assert "PRIMARY KEY (source, source_id, kind)" in sql
    for status in JobStatus:
        assert f"'{status.value}'" in sql


@pytest.mark.parametrize(
    "fragment",
    [
        "CREATE TABLE IF NOT EXISTS schema_migrations",
        "CREATE TABLE IF NOT EXISTS creatives",
        "INSERT INTO schema_migrations",
    ],
)
def test_migrations_rollback_and_propagate_failure(fragment):
    conn = FakeConnection(fail_on=lambda query: fragment in query)
    with pytest.raises(RuntimeError, match="scripted SQL failure"):
        apply_migrations(conn)
    assert conn.rollbacks == 1
    assert conn.commits == 0


def test_change_columns_exclude_all_collection_timestamps():
    expected = {
        "url",
        "title",
        "caption",
        "published_at",
        "duration_s",
        "language",
        "analyzable",
        "latest_view_count",
        "latest_like_count",
        "latest_comment_count",
    }
    assert isinstance(CHANGE_COLUMNS, tuple)
    assert len(CHANGE_COLUMNS) == len(expected)
    assert set(CHANGE_COLUMNS) == expected
    sql = build_upsert_sql()
    comparison = sql.split("WHERE", 1)[1]
    assert "IS DISTINCT FROM" in comparison
    for column in expected:
        assert f"creatives.{column}" in comparison
        assert f"EXCLUDED.{column}" in comparison
    for column in (
        "collected_at",
        "first_seen_at",
        "metrics_collected_at",
        "updated_at",
    ):
        assert column not in comparison
    assert "updated_at = now()" in sql


def test_upsert_parameters_deduplicate_by_source_and_id_with_last_wins():
    title = "O'Brien\"; DROP TABLE creatives; --"
    old = creative(title="old")
    last = creative(title=title)
    other = creative(source=Source.instagram, title="other")
    conn = FakeConnection()
    assert PostgresCreativeStore(conn).upsert_creatives([old, last, other]) == 2
    inserts = calls_for(conn, "INSERT INTO creatives")
    assert len(inserts) == 2
    assert title in inserts[0][1]
    assert "old" not in inserts[0][1]
    assert all(title not in query for query, _ in conn.calls)
    assert all(0 not in params for _, params in inserts)
    history = calls_for(conn, "INSERT INTO metrics_history")
    assert len(history) == 2
    assert all("ON CONFLICT" in query and "DO NOTHING" in query for query, _ in history)
    assert all(params[-3:] == (None, None, None) for _, params in history)
    assert conn.commits == 1 and conn.rollbacks == 0


def test_recollection_only_timestamps_differ_in_upsert_parameters():
    conn = FakeConnection()
    store = PostgresCreativeStore(conn)
    store.upsert_creatives([creative(metrics=Metrics(view_count=0))])
    later = NOW + timedelta(days=1)
    store.upsert_creatives(
        [creative(metrics=Metrics(view_count=0), collected_at=later)]
    )
    first, second = calls_for(conn, "INSERT INTO creatives")
    assert first[0] == second[0] == build_upsert_sql()
    assert [value for value in first[1] if value != NOW] == [
        value for value in second[1] if value != later
    ]
    # The effective metrics are chosen before the conflict comparison; timestamp
    # advancement also has a separate update that never modifies updated_at.
    assert "incoming.metrics_collected_at >= creatives.metrics_collected_at" in first[0]
    assert "ELSE creatives.latest_view_count" in first[0]
    timestamp_updates = calls_for(conn, "UPDATE creatives SET metrics_collected_at")
    assert len(timestamp_updates) == 2
    assert all("updated_at" not in query for query, _ in timestamp_updates)
    assert all("metrics_collected_at <= %s" in query for query, _ in timestamp_updates)


def test_enqueue_only_explicitly_analyzable_and_preserve_existing_jobs():
    conn = FakeConnection([FakeCursor(rowcount=1), FakeCursor(rowcount=0)])
    items = [
        creative(analyzable=True),
        creative(source_id="unknown"),
        creative(source_id="no", analyzable=False),
        creative(source_id="already", analyzable=True),
    ]
    assert PostgresCreativeStore(conn).enqueue_analysis("hook", items) == 1
    inserts = calls_for(conn, "INSERT INTO analysis_jobs")
    assert len(inserts) == 2
    assert [params for _, params in inserts] == [
        ("youtube", "video-1", "hook", "pending"),
        ("youtube", "already", "hook", "pending"),
    ]
    assert all(
        "ON CONFLICT (source, source_id, kind) DO NOTHING" in query
        for query, _ in inserts
    )
    assert conn.commits == 1


def test_enqueue_returns_inserted_attempt_count_without_conflicts():
    conn = FakeConnection()
    items = [creative(analyzable=True), creative(source_id="second", analyzable=True)]
    assert (
        PostgresCreativeStore(conn).enqueue_analysis("hook", items)
        == len(calls_for(conn, "INSERT INTO analysis_jobs"))
        == 2
    )


@pytest.mark.parametrize("analyzable", [None, False, True])
def test_get_creative_restores_nulls_and_explicit_false(analyzable):
    item = creative(analyzable=analyzable)
    conn = FakeConnection([FakeCursor([creative_row(item)])])
    result = PostgresCreativeStore(conn).get_creative(item.key)
    assert result == item
    assert result.title is None and result.duration_s is None
    assert result.analyzable is analyzable
    assert result.metrics == Metrics()
    assert conn.calls[0][1] == ("youtube", "video-1")
    assert conn.commits == conn.rollbacks == 0


def test_get_missing_creative_returns_none():
    conn = FakeConnection()
    assert PostgresCreativeStore(conn).get_creative(creative().key) is None


def test_next_pending_restores_rows_and_parameterizes_selection():
    items = [
        creative(),
        creative(source_id="second", metrics=Metrics(view_count=0, like_count=2**40)),
    ]
    conn = FakeConnection([FakeCursor([creative_row(item) for item in items])])
    assert PostgresCreativeStore(conn).next_pending("hook", 7) == items
    query, params = conn.calls[0]
    assert params == ("hook", "pending", 7)
    assert "ORDER BY" in query and "published_at DESC NULLS LAST" in query
    assert "LIMIT %s" in query
    assert "source_id" in query and "source" in query
    assert PostgresCreativeStore(FakeConnection()).next_pending("hook", 1) == []


@pytest.mark.parametrize("status", list(JobStatus))
@pytest.mark.parametrize("prompt_version", [None, "hook-v1"])
@pytest.mark.parametrize("raw_output", [None, "", '  {"unparsed": true}\n'])
def test_record_analysis_preserves_raw_output_prompt_and_status(
    status, prompt_version, raw_output
):
    conn = FakeConnection()
    labels = {"classification": "uninterpreted"}
    PostgresCreativeStore(conn).record_analysis(
        "hook",
        creative().key,
        status=status,
        model="model-name",
        thinking_level="minimal",
        prompt_version=prompt_version,
        raw_output=raw_output,
        labels=labels,
        error_code=None,
    )
    inserts = calls_for(conn, "INSERT INTO model_outputs")
    if raw_output is None:
        assert inserts == []
    else:
        assert len(inserts) == 1
        query, params = inserts[0]
        assert "prompt_version" in query
        assert params == (
            "youtube",
            "video-1",
            "hook",
            "model-name",
            "minimal",
            prompt_version,
            raw_output,
        )
    [(query, params)] = calls_for(conn, "UPDATE analysis_jobs")
    assert type(params[0]) is str and params[0] == status.value
    assert params[1] is None
    assert json.loads(params[2]) == labels
    assert params[-3:] == ("youtube", "video-1", "hook")
    assert "attempts = attempts + 1" in query
    assert "updated_at = now()" in query
    assert conn.commits == 1 and conn.rollbacks == 0


def test_record_analysis_null_labels_and_error_code():
    conn = FakeConnection()
    PostgresCreativeStore(conn).record_analysis(
        "hook",
        CreativeKey(source=Source.tiktok, source_id="ad"),
        status=JobStatus.failed,
        model=None,
        thinking_level=None,
        prompt_version=None,
        raw_output=None,
        labels=None,
        error_code="INVALID_SCHEMA",
    )
    [(query, params)] = calls_for(conn, "UPDATE analysis_jobs")
    assert params == ("failed", "INVALID_SCHEMA", None, "tiktok", "ad", "hook")
    assert "INVALID_SCHEMA" not in query


@pytest.mark.parametrize("operation", ["upsert", "enqueue", "record"])
def test_writes_rollback_on_failure(operation):
    fragment = {
        "upsert": "INSERT INTO metrics_history",
        "enqueue": "INSERT INTO analysis_jobs",
        "record": "UPDATE analysis_jobs",
    }[operation]
    conn = FakeConnection(fail_on=lambda query: fragment in query)
    store = PostgresCreativeStore(conn)
    with pytest.raises(RuntimeError, match="scripted SQL failure"):
        if operation == "upsert":
            store.upsert_creatives([creative()])
        elif operation == "enqueue":
            store.enqueue_analysis("hook", [creative(analyzable=True)])
        else:
            store.record_analysis(
                "hook",
                creative().key,
                status=JobStatus.done,
                model=None,
                thinking_level=None,
                prompt_version=None,
                raw_output="raw",
                labels=None,
                error_code=None,
            )
    assert conn.rollbacks == 1 and conn.commits == 0


@pytest.mark.parametrize("password", [None, "", " \t "])
def test_postgres_dsn_requires_nonblank_password(password):
    environ = {} if password is None else {"POSTGRES_PASSWORD": password}
    with pytest.raises(MissingSetting) as caught:
        postgres_dsn(environ=environ, env_file=None)
    assert caught.value.name == "POSTGRES_PASSWORD"


@pytest.mark.parametrize(
    "port, expected", [(None, 5433), ("", 5433), (" \t ", 5433), ("6543", 6543)]
)
def test_postgres_dsn_defaults_and_overridden_port(port, expected):
    password = "synthetic /@:'?#% value"
    environ = {"POSTGRES_PASSWORD": password}
    if port is not None:
        environ["BEAUTYADS_POSTGRES_PORT"] = port
    parsed = urlparse(postgres_dsn(environ=environ, env_file=None))
    assert parsed.hostname == "127.0.0.1" and parsed.port == expected
    assert parsed.username == "beautyads" and parsed.path == "/beautyads"
    assert unquote(parsed.password) == password


def test_connect_uses_injected_or_default_driver(monkeypatch):
    conn = FakeConnection()
    received = []

    def fake_connect(dsn):
        received.append(dsn)
        return conn

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    dsn = "postgresql://synthetic"
    assert connect(dsn) is conn
    assert connect(dsn, connect_fn=fake_connect) is conn
    assert received == [dsn, dsn]


@pytest.mark.parametrize(
    "message, sqlstate, code",
    [
        ("password authentication failed for user", None, "POSTGRES_AUTH_FAILED"),
        ("localized failure", "28P01", "POSTGRES_AUTH_FAILED"),
        ("connection refused", None, "POSTGRES_CONNECT_FAILED"),
    ],
)
def test_connect_errors_are_safe_and_classified(message, sqlstate, code):
    password = "synthetic-secret"
    dsn = f"postgresql://beautyads:{password}@127.0.0.1:5433/beautyads"

    class DriverFailure(psycopg.OperationalError):
        pass

    DriverFailure.sqlstate = sqlstate

    def fail(_dsn):
        raise DriverFailure(f"{message}: {dsn}")

    with pytest.raises(StoreConnectError) as caught:
        connect(dsn, connect_fn=fail)
    assert caught.value.code == code
    for rendered in (
        str(caught.value),
        repr(caught.value),
        "".join(traceback.format_exception(caught.value)),
    ):
        assert dsn not in rendered and password not in rendered


def test_connect_does_not_hide_unrelated_errors():
    def fail(_dsn):
        raise ValueError("programming error")

    with pytest.raises(ValueError, match="programming error"):
        connect("synthetic", connect_fn=fail)
