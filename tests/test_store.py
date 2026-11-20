"""Store contracts exercised only with scripted connections, never a database."""

import json
import re
import traceback
from collections import deque
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlparse

import psycopg
import pytest

from beautyads.domain import (
    CollectionStat,
    Creative,
    CreativeKey,
    JobStatus,
    Metrics,
    Source,
)
from beautyads.settings import MissingSetting
from beautyads.store.connection import StoreConnectError, connect, postgres_dsn
from beautyads.store.repository import CREATIVE_COLUMNS, PostgresCreativeStore
from beautyads.store.schema import (
    CHANGE_COLUMNS,
    INSERT_COLUMNS,
    MIGRATIONS,
    apply_migrations,
    build_upsert_sql,
)

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


def test_brand_account_migration_is_additive_version_two():
    [(version, name, sql)] = [item for item in MIGRATIONS if item[0] == 2]
    assert version == 2 and name == "creative_brand_account"
    for column in ("brand", "account"):
        assert re.search(
            rf"ALTER TABLE creatives ADD COLUMN IF NOT EXISTS {column} text",
            sql,
            re.IGNORECASE,
        )
    assert not re.search(r"\b(DROP|TRUNCATE|UPDATE|INSERT)\b", sql, re.IGNORECASE)
    [(_, _, first_sql)] = [item for item in MIGRATIONS if item[0] == 1]
    assert not re.search(r"\b(brand|account)\b", first_sql)


def test_existing_version_one_only_applies_later_migrations():
    conn = FakeConnection([FakeCursor(), FakeCursor([(1,)])])
    remaining = [(version, name) for version, name, _ in MIGRATIONS if version > 1]
    assert apply_migrations(conn) == [version for version, _ in remaining]
    assert [
        params for _, params in calls_for(conn, "INSERT INTO schema_migrations")
    ] == remaining
    assert conn.commits == len(remaining) and conn.rollbacks == 0
    assert not calls_for(conn, "CREATE TABLE IF NOT EXISTS creatives")


def test_attributes_migration_is_additive_version_three():
    [(version, name, sql)] = [item for item in MIGRATIONS if item[0] == 3]
    assert version == 3 and name == "creative_attributes"
    assert re.fullmatch(
        r"\s*ALTER TABLE creatives ADD COLUMN IF NOT EXISTS attributes jsonb;\s*",
        sql,
        re.IGNORECASE,
    )
    assert not re.search(r"\b(DROP|TRUNCATE|UPDATE|INSERT)\b", sql, re.IGNORECASE)
    for prior_version, _, prior_sql in MIGRATIONS:
        if prior_version < 3:
            assert not re.search(r"\battributes\b", prior_sql)


def test_existing_version_two_only_applies_later_migrations():
    conn = FakeConnection([FakeCursor(), FakeCursor([(1,), (2,)])])
    remaining = [(version, name) for version, name, _ in MIGRATIONS if version > 2]
    assert apply_migrations(conn) == [version for version, _ in remaining]
    assert [
        params for _, params in calls_for(conn, "INSERT INTO schema_migrations")
    ] == remaining
    assert conn.commits == len(remaining) and conn.rollbacks == 0
    assert not calls_for(conn, "CREATE TABLE IF NOT EXISTS creatives")
    assert not calls_for(conn, "ADD COLUMN IF NOT EXISTS brand")
    assert not calls_for(conn, "ADD COLUMN IF NOT EXISTS account")


def test_product_migration_v4_is_additive_repeatable_and_preserves_prior_versions():
    import hashlib

    assert [
        (version, name, hashlib.sha256(sql.encode()).hexdigest())
        for version, name, sql in MIGRATIONS
        if version <= 3
    ] == [
        (
            1,
            "creative_source_of_truth",
            "8baf3f2382951c0e20ca5bdf88761931728603c5f80b3c3724617046022c5c53",
        ),
        (
            2,
            "creative_brand_account",
            "4d36a1f91e86c749dcff01adb580eb39704538c60f7f206477430fb278b22ebe",
        ),
        (
            3,
            "creative_attributes",
            "9f5343670f2a756e2d415e0b7599caec33705cb16b383869411232567866873e",
        ),
    ]
    [(_, _, sql)] = [migration for migration in MIGRATIONS if migration[0] == 4]
    statements = [part.strip() for part in sql.split(";") if part.strip()]
    assert statements and all(
        re.match(r"CREATE (TABLE|INDEX) IF NOT EXISTS ", part) for part in statements
    )
    for table in (
        "products",
        "product_prices",
        "product_ingredients",
        "ingredient_standards",
        "product_certs",
        "product_extractions",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "PRIMARY KEY (brand, source_url)" in sql
    assert "aliases jsonb" in sql and "skin_types jsonb" in sql
    assert "raw_output text" in sql and "prompt_version text" in sql
    assert not re.search(
        r"\b(creatives|analysis_jobs|DROP|TRUNCATE|DELETE|UPDATE)\b", sql
    )
    executed = []
    for _ in range(2):
        conn = FakeConnection([FakeCursor(), FakeCursor([(1,), (2,), (3,)])])
        assert apply_migrations(conn) == [4, 5, 6, 7]
        executed.append([query for query, _ in conn.calls if query == sql])
        assert conn.commits == 4 and conn.rollbacks == 0
    assert executed == [[sql], [sql]]
    conn = FakeConnection(
        [FakeCursor(), FakeCursor([(1,), (2,), (3,), (4,), (5,), (6,), (7,)])]
    )
    assert apply_migrations(conn) == []
    assert not calls_for(conn, "CREATE TABLE IF NOT EXISTS products")


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
    expected = (
        "url",
        "title",
        "caption",
        "published_at",
        "duration_s",
        "language",
        "analyzable",
        "brand",
        "account",
        "latest_view_count",
        "latest_like_count",
        "latest_comment_count",
        "attributes",
    )
    assert isinstance(CHANGE_COLUMNS, tuple)
    assert len(CHANGE_COLUMNS) == len(expected)
    assert CHANGE_COLUMNS == expected
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
        assert column not in CHANGE_COLUMNS
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


@pytest.mark.parametrize(
    "brand, account", [(None, None), ("O'Brien; --", "@brand'handle")]
)
def test_upsert_parameterizes_brand_and_account_as_text_or_null(brand, account):
    conn = FakeConnection()
    PostgresCreativeStore(conn).upsert_creatives(
        [creative(brand=brand, account=account)]
    )
    [(query, params)] = calls_for(conn, "INSERT INTO creatives")
    assert len(params) == len(INSERT_COLUMNS) == query.count("%s")
    values = dict(zip(INSERT_COLUMNS, params, strict=True))
    assert values["brand"] == brand
    assert values["account"] == account
    casts = re.findall(r"%s::([a-z ]+?)(?=,|\))", query)
    assert len(casts) == len(INSERT_COLUMNS)
    types = dict(zip(INSERT_COLUMNS, casts, strict=True))
    assert types["brand"] == types["account"] == "text"
    for value in (brand, account):
        if value is not None:
            assert all(value not in sql for sql, _ in conn.calls)
    assert conn.commits == 1 and conn.rollbacks == 0


@pytest.mark.parametrize(
    "attributes",
    [
        {},
        {
            "reach": "600K-700K",
            "advertiser": {"business_name": "O'Brien\"; --", "business_id": 42},
            "observations": ["synthetic", 1.5, {"enabled": True, "missing": None}],
        },
    ],
)
def test_upsert_parameterizes_attributes_as_jsonb(attributes):
    conn = FakeConnection()
    PostgresCreativeStore(conn).upsert_creatives([creative(attributes=attributes)])
    [(query, params)] = calls_for(conn, "INSERT INTO creatives")
    assert len(params) == len(INSERT_COLUMNS) == query.count("%s")
    values = dict(zip(INSERT_COLUMNS, params, strict=True))
    assert isinstance(values["attributes"], str)
    assert json.loads(values["attributes"]) == attributes
    casts = re.findall(r"%s::([a-z ]+?)(?=,|\))", query)
    assert len(casts) == len(INSERT_COLUMNS)
    assert dict(zip(INSERT_COLUMNS, casts, strict=True))["attributes"] == "jsonb"
    assert "attributes = EXCLUDED.attributes" in query
    assert all(values["attributes"] not in sql for sql, _ in conn.calls)
    assert all("O'Brien" not in sql for sql, _ in conn.calls)
    assert conn.commits == 1 and conn.rollbacks == 0


def test_upsert_attributes_key_order_does_not_change_comparison_values():
    first_attributes = {"reach": "600K-700K", "advertiser": {"name": "合成", "id": 42}}
    reordered_attributes = {
        "advertiser": {"id": 42, "name": "合成"},
        "reach": "600K-700K",
    }
    conn = FakeConnection()
    store = PostgresCreativeStore(conn)
    store.upsert_creatives([creative(attributes=first_attributes)])
    store.upsert_creatives([creative(attributes=reordered_attributes)])
    first, second = calls_for(conn, "INSERT INTO creatives")
    assert first == second
    values = dict(zip(INSERT_COLUMNS, first[1], strict=True))
    assert values["attributes"] == json.dumps(first_attributes, sort_keys=True)
    comparison = first[0].split("WHERE", 1)[1]
    assert "IS DISTINCT FROM" in comparison
    assert "creatives.attributes" in comparison
    assert "EXCLUDED.attributes" in comparison


@pytest.mark.parametrize(
    "operation", ["get_creative", "list_creatives", "next_pending"]
)
@pytest.mark.parametrize(
    "stored_attributes",
    [None, {}, {"reach": "600K-700K", "nested": {"items": [1, None]}}],
)
def test_creative_reads_restore_attributes_and_legacy_nulls(
    operation, stored_attributes
):
    item = creative(
        attributes=stored_attributes if stored_attributes is not None else {}
    )
    values = dict(zip(CREATIVE_COLUMNS, creative_row(item), strict=True))
    values["attributes"] = stored_attributes
    row = tuple(values[column] for column in CREATIVE_COLUMNS)
    conn = FakeConnection([FakeCursor([row])])
    store = PostgresCreativeStore(conn)
    if operation == "get_creative":
        result = store.get_creative(item.key)
    elif operation == "list_creatives":
        [result] = store.list_creatives()
    else:
        [result] = store.next_pending("hook", 7)
    assert result == item
    assert type(result.attributes) is dict
    assert "attributes" in conn.calls[0][0]
    assert conn.rollbacks == 1 and conn.commits == 0


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
    assert conn.rollbacks == 1 and conn.commits == 0


def test_get_missing_creative_returns_none():
    conn = FakeConnection()
    assert PostgresCreativeStore(conn).get_creative(creative().key) is None


def test_get_creative_restores_brand_and_account():
    item = creative(brand="브랜드", account="@brand_handle")
    conn = FakeConnection([FakeCursor([creative_row(item)])])
    assert PostgresCreativeStore(conn).get_creative(item.key) == item
    query, params = conn.calls[0]
    assert "brand" in query and "account" in query
    assert params == (item.source.value, item.source_id)
    assert conn.rollbacks == 1 and conn.commits == 0


@pytest.mark.parametrize("has_rows", [False, True])
def test_collection_stats_restores_groups_and_closes_read_transaction(has_rows):
    brand = "O'Brien; --"
    account = "@brand'handle"
    rows = (
        [
            ("instagram", None, None, 3, 0, 1, 2, None),
            ("youtube", brand, account, 6, 1, 2, 3, NOW),
        ]
        if has_rows
        else []
    )
    conn = FakeConnection()

    class TransactionCursor(FakeCursor):
        def fetchall(self):
            assert conn.rollbacks == 0, "fetchall called after rollback"
            return super().fetchall()

    conn.replies.append(TransactionCursor(rows))
    result = PostgresCreativeStore(conn).collection_stats()
    assert all(isinstance(stat, CollectionStat) for stat in result)
    assert [
        (
            stat.source.value,
            stat.brand,
            stat.account,
            stat.total,
            stat.analyzable_true,
            stat.analyzable_false,
            stat.analyzable_null,
            stat.last_collected_at,
        )
        for stat in result
    ] == rows
    assert len(conn.calls) == 1
    query, params = conn.calls[0]
    normalized = " ".join(query.upper().split())
    assert "FROM CREATIVES" in normalized
    assert "GROUP BY SOURCE, BRAND, ACCOUNT" in normalized
    assert "ORDER BY SOURCE, BRAND, ACCOUNT" in normalized
    assert "COUNT(*)" in normalized and normalized.count("FILTER") == 3
    assert normalized.count("FILTER (WHERE ANALYZABLE = %S)") == 2
    assert "FILTER (WHERE ANALYZABLE IS NULL)" in normalized
    assert "MAX(COLLECTED_AT)" in normalized
    assert params == (True, False)
    assert query.count("%s") == len(params)
    assert brand not in query and account not in query
    assert conn.rollbacks == 1 and conn.commits == 0


@pytest.mark.parametrize("failure_stage", ["execute", "fetch"])
def test_collection_stats_rolls_back_and_propagates_read_failure(failure_stage):
    failure = RuntimeError("scripted stats read failure")

    def fail_on(query):
        raise failure

    class FailingCursor(FakeCursor):
        def fetchall(self):
            raise failure

    conn = FakeConnection(
        [FailingCursor()], fail_on=fail_on if failure_stage == "execute" else None
    )
    with pytest.raises(RuntimeError) as caught:
        PostgresCreativeStore(conn).collection_stats()
    assert caught.value is failure
    assert conn.rollbacks == 1 and conn.commits == 0


def test_next_pending_restores_rows_and_parameterizes_selection():
    items = [
        creative(),
        creative(
            source_id="second",
            brand="브랜드",
            account="@brand_handle",
            metrics=Metrics(view_count=0, like_count=2**40),
        ),
    ]
    conn = FakeConnection([FakeCursor([creative_row(item) for item in items])])
    assert PostgresCreativeStore(conn).next_pending("hook", 7) == items
    query, params = conn.calls[0]
    assert params == ("hook", "pending", 7)
    assert "ORDER BY" in query and "published_at DESC NULLS LAST" in query
    assert "LIMIT %s" in query
    assert "source_id" in query and "source" in query
    assert "c.brand" in query and "c.account" in query
    assert conn.rollbacks == 1 and conn.commits == 0
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


@pytest.mark.parametrize("host", [None, "", " \t ", "postgres"])
@pytest.mark.parametrize("port", [None, "6543"])
def test_postgres_dsn_host_preserves_defaults_and_password_encoding(host, port):
    environ = {"POSTGRES_PASSWORD": "synthetic /@:'?#% value"}
    if host is not None:
        environ["BEAUTYADS_POSTGRES_HOST"] = host
    if port is not None:
        environ["BEAUTYADS_POSTGRES_PORT"] = port
    expected_host = "postgres" if host == "postgres" else "127.0.0.1"
    assert postgres_dsn(environ=environ, env_file=None) == (
        "postgresql://beautyads:synthetic%20%2F%40%3A%27%3F%23%25%20value@"
        f"{expected_host}:{port or '5433'}/beautyads"
    )


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


@pytest.mark.parametrize("operation", ["get_creative", "next_pending"])
@pytest.mark.parametrize("has_rows", [False, True])
def test_reads_close_transaction_without_committing(operation, has_rows):
    item = creative()
    rows = [creative_row(item)] if has_rows else []
    conn = FakeConnection([FakeCursor(rows)])
    store = PostgresCreativeStore(conn)
    if operation == "get_creative":
        assert store.get_creative(item.key) == (item if has_rows else None)
    else:
        assert store.next_pending("hook", 7) == ([item] if has_rows else [])
    assert conn.rollbacks == 1 and conn.commits == 0


@pytest.mark.parametrize("operation", ["get_creative", "next_pending"])
def test_reads_fetch_results_before_rollback(operation):
    conn = FakeConnection()

    class TransactionCursor(FakeCursor):
        def fetchone(self):
            assert conn.rollbacks == 0, "fetchone called after rollback"
            return super().fetchone()

        def fetchall(self):
            assert conn.rollbacks == 0, "fetchall called after rollback"
            return super().fetchall()

    items = [creative(), creative(source_id="second")]
    conn.replies.append(TransactionCursor([creative_row(item) for item in items]))
    store = PostgresCreativeStore(conn)
    if operation == "get_creative":
        assert store.get_creative(items[0].key) == items[0]
    else:
        assert store.next_pending("hook", 7) == items
    assert conn.rollbacks == 1 and conn.commits == 0


@pytest.mark.parametrize("operation", ["get_creative", "next_pending"])
def test_reads_rollback_and_propagate_execute_failure(operation):
    failure = RuntimeError("scripted read SQL failure")

    def fail_on(query):
        assert query.startswith("SELECT ")
        raise failure

    conn = FakeConnection(fail_on=fail_on)
    store = PostgresCreativeStore(conn)
    with pytest.raises(RuntimeError) as caught:
        if operation == "get_creative":
            store.get_creative(creative().key)
        else:
            store.next_pending("hook", 7)
    assert caught.value is failure
    assert conn.rollbacks == 1 and conn.commits == 0


@pytest.mark.parametrize("operation", ["get_creative", "next_pending"])
def test_reads_rollback_and_propagate_fetch_failure(operation):
    failure = RuntimeError("scripted fetch failure")

    class FailingCursor(FakeCursor):
        def fetchone(self):
            raise failure

        def fetchall(self):
            raise failure

    conn = FakeConnection([FailingCursor()])
    store = PostgresCreativeStore(conn)
    with pytest.raises(RuntimeError) as caught:
        if operation == "get_creative":
            store.get_creative(creative().key)
        else:
            store.next_pending("hook", 7)
    assert caught.value is failure
    assert conn.rollbacks == 1 and conn.commits == 0


def job_result_row(key, *, labels=None, status="done", output=True):
    return (
        key.source.value,
        key.source_id,
        "hook@minimal",
        status,
        labels,
        "SYNTHETIC_ERROR" if status == "failed" else None,
        "synthetic-model" if output else None,
        "minimal" if output else None,
        "test-v1" if output else None,
        "unparsed output" if output else None,
        2,
        NOW,
    )


def test_requeue_jobs_targets_only_failed_selected_codes_and_parameterizes_values():
    kind = "hook@minimal'; --"
    codes = ["OVERLOADED'; --", "TIMEOUT"]
    conn = FakeConnection([FakeCursor(rowcount=3)])
    assert PostgresCreativeStore(conn).requeue_jobs(kind, codes) == 3
    [(query, params)] = conn.calls
    normalized = " ".join(query.split())
    assert "UPDATE analysis_jobs SET status='pending', updated_at=now()" in normalized
    assert "WHERE kind=%s AND status='failed' AND error_code = ANY(%s)" in normalized
    assert "held" not in query and "done" not in query
    assert params == (kind, codes)
    assert query.count("%s") == len(params)
    assert kind not in query and all(code not in query for code in codes)
    assert conn.commits == 1 and conn.rollbacks == 0


def test_requeue_jobs_empty_codes_skip_database():
    conn = FakeConnection()
    assert PostgresCreativeStore(conn).requeue_jobs("hook@minimal", []) == 0
    assert conn.calls == []
    assert conn.commits == conn.rollbacks == 0


def test_requeue_jobs_rolls_back_write_failure():
    conn = FakeConnection(fail_on=lambda query: True)
    with pytest.raises(RuntimeError, match="scripted SQL failure"):
        PostgresCreativeStore(conn).requeue_jobs("hook@minimal", ["OVERLOADED"])
    assert conn.commits == 0 and conn.rollbacks == 1


@pytest.mark.parametrize("rows", [[], [("failed", 3), ("done", 5)]])
def test_job_counts_fills_all_statuses_and_closes_read_transaction(rows):
    conn = FakeConnection([FakeCursor(rows)])
    result = PostgresCreativeStore(conn).job_counts("hook@minimal")
    expected = {status.value: 0 for status in JobStatus}
    expected.update(rows)
    assert result == expected
    assert all(type(key) is str for key in result)
    [(query, params)] = conn.calls
    assert "GROUP BY status" in query and "count(*)" in query.lower()
    assert "WHERE kind = %s" in query
    assert params == ("hook@minimal",) and "hook@minimal" not in query
    assert conn.rollbacks == 1 and conn.commits == 0


@pytest.mark.parametrize("as_json", [False, True])
def test_get_job_results_restores_jobs_and_latest_output_without_missing_jobs(as_json):
    from beautyads.domain import JobResult

    keys = [creative(source_id=name).key for name in ("one'", "two", "missing")]
    labels = {"items": ["synthetic", {"enabled": True}], "flag": False}
    stored_labels = json.dumps(labels) if as_json else labels
    conn = FakeConnection(
        [
            FakeCursor(
                [
                    job_result_row(keys[0], labels=stored_labels),
                    job_result_row(keys[1], status="failed", output=False),
                ]
            )
        ]
    )
    results = PostgresCreativeStore(conn).get_job_results("hook@minimal", keys)
    assert all(isinstance(result, JobResult) for result in results)
    assert [result.key for result in results] == keys[:2]
    first, second = results
    assert first.kind == "hook@minimal" and first.status is JobStatus.done
    assert first.labels == labels and type(first.labels) is dict
    assert first.error_code is None
    assert first.model == "synthetic-model" and first.thinking_level == "minimal"
    assert first.prompt_version == "test-v1" and first.raw_output == "unparsed output"
    assert first.attempts == 2 and first.updated_at == NOW
    assert second.labels is None and second.status is JobStatus.failed
    assert second.error_code == "SYNTHETIC_ERROR"
    assert second.model is second.thinking_level is second.prompt_version is None
    assert second.raw_output is None
    [(query, params)] = conn.calls
    normalized = " ".join(query.lower().split())
    assert (
        "from analysis_jobs" in normalized and "left join model_outputs" in normalized
    )
    assert re.search(r"max\((?:\w+\.)?id\)", normalized)
    for column in ("source", "source_id", "kind"):
        assert re.search(rf"\w+\.{column}\s*=\s*\w+\.{column}", query)
    assert "hook@minimal" not in query and "one'" not in query
    assert params == (
        "hook@minimal",
        *(value for key in keys for value in (key.source.value, key.source_id)),
    )
    assert query.count("%s") == len(params)
    assert conn.rollbacks == 1 and conn.commits == 0


def test_get_job_results_empty_keys_skip_database():
    conn = FakeConnection()
    assert PostgresCreativeStore(conn).get_job_results("hook@minimal", []) == []
    assert conn.calls == [] and conn.rollbacks == conn.commits == 0


def test_get_job_results_batches_large_key_lists():
    keys = [creative(source_id=f"key-{index}").key for index in range(1201)]
    conn = FakeConnection()
    assert PostgresCreativeStore(conn).get_job_results("hook@minimal", keys) == []
    assert 1 < len(conn.calls) < len(keys)
    actual_keys = []
    for query, params in conn.calls:
        assert params[0] == "hook@minimal"
        assert query.count("%s") == len(params)
        actual_keys.extend(zip(params[1::2], params[2::2], strict=True))
    assert actual_keys == [(key.source.value, key.source_id) for key in keys]
    assert conn.rollbacks == len(conn.calls) and conn.commits == 0


@pytest.mark.parametrize("brands", [None, ["O'Brien; --"]])
@pytest.mark.parametrize("sources", [None, [Source.youtube, Source.instagram]])
@pytest.mark.parametrize("analyzable_only", [False, True])
@pytest.mark.parametrize("limit", [None, 0, 7])
def test_list_creatives_filter_combinations_and_restore_metadata(
    brands, sources, analyzable_only, limit
):
    items = [
        creative(brand="O'Brien; --", account="@brand"),
        creative(source_id="nullable", brand=None, account=None),
    ]
    conn = FakeConnection([FakeCursor([creative_row(item) for item in items])])
    assert (
        PostgresCreativeStore(conn).list_creatives(
            brands=brands, sources=sources, analyzable_only=analyzable_only, limit=limit
        )
        == items
    )
    [(query, params)] = conn.calls
    assert ("brand = ANY(%s)" in query) is (brands is not None)
    assert ("source = ANY(%s)" in query) is (sources is not None)
    assert ("analyzable IS TRUE" in query) is analyzable_only
    assert ("LIMIT %s" in query) is (limit is not None)
    assert "ORDER BY published_at DESC NULLS LAST, source, source_id" in query
    expected = []
    if brands is not None:
        expected.append(brands)
    if sources is not None:
        expected.append([source.value for source in sources])
    if limit is not None:
        expected.append(limit)
    assert tuple(params) == tuple(expected)
    assert query.count("%s") == len(params)
    assert "O'Brien; --" not in query
    assert conn.rollbacks == 1 and conn.commits == 0


@pytest.mark.parametrize("filters", [{"brands": []}, {"sources": []}])
def test_list_creatives_empty_filters_skip_database(filters):
    conn = FakeConnection()
    assert PostgresCreativeStore(conn).list_creatives(**filters) == []
    assert conn.calls == [] and conn.rollbacks == conn.commits == 0


@pytest.mark.parametrize(
    "operation", ["job_counts", "get_job_results", "list_creatives"]
)
@pytest.mark.parametrize("failure_stage", [None, "execute", "fetch"])
def test_new_reads_fetch_before_single_rollback_and_propagate_failures(
    operation, failure_stage
):
    conn = FakeConnection(fail_on=lambda query: failure_stage == "execute")

    class TransactionCursor(FakeCursor):
        def fetchall(self):
            assert conn.rollbacks == 0, "fetchall called after rollback"
            if failure_stage == "fetch":
                raise RuntimeError("scripted fetch failure")
            return super().fetchall()

    conn.replies.append(TransactionCursor())
    store = PostgresCreativeStore(conn)

    def read():
        if operation == "job_counts":
            return store.job_counts("hook@minimal")
        if operation == "get_job_results":
            return store.get_job_results("hook@minimal", [creative().key])
        return store.list_creatives()

    if failure_stage:
        with pytest.raises(RuntimeError, match="scripted"):
            read()
    else:
        result = read()
        assert result == (
            {status.value: 0 for status in JobStatus}
            if operation == "job_counts"
            else []
        )
    assert len(conn.calls) == 1
    assert conn.rollbacks == 1 and conn.commits == 0


@pytest.mark.parametrize("kind", ["hook@minimal", "hook@default"])
def test_existing_analysis_methods_preserve_run_tag_and_serialize_general_labels(kind):
    item = creative(analyzable=True)
    conn = FakeConnection([FakeCursor(), FakeCursor([creative_row(item)])])
    store = PostgresCreativeStore(conn)
    assert store.enqueue_analysis(kind, [item]) == 1
    assert store.next_pending(kind, 7) == [item]
    labels = {"items": ["synthetic", {"nested": None}], "flag": True}
    store.record_analysis(
        kind,
        item.key,
        status=JobStatus.done,
        model="synthetic-model",
        thinking_level="minimal",
        prompt_version="test-v1",
        raw_output="raw",
        labels=labels,
        error_code=None,
    )
    [(_, enqueue_params)] = calls_for(conn, "INSERT INTO analysis_jobs")
    assert enqueue_params == ("youtube", "video-1", kind, "pending")
    [(_, pending_params)] = calls_for(conn, "JOIN analysis_jobs")
    assert pending_params == (kind, "pending", 7)
    [(_, output_params)] = calls_for(conn, "INSERT INTO model_outputs")
    assert output_params[2] == kind
    [(_, update_params)] = calls_for(conn, "UPDATE analysis_jobs")
    assert update_params[-1] == kind
    assert isinstance(update_params[2], str)
    assert json.loads(update_params[2]) == labels
    assert all(kind not in query for query, _ in conn.calls)
    assert conn.commits == 2 and conn.rollbacks == 1


def test_migration_5_only_adds_the_ingredient_lookup_cache():
    [(version, name, sql)] = [item for item in MIGRATIONS if item[0] == 5]
    assert version == 5 and name == "ingredient_lookup_cache"
    normalized = " ".join(sql.split()).upper()
    assert "CREATE TABLE IF NOT EXISTS INGREDIENT_LOOKUPS" in normalized
    assert "PRIMARY KEY (QUERY_KEY, KIND)" in normalized
    # Additive: nothing is removed or altered, and no other table is touched.
    assert "DR" + "OP " not in normalized and "ALT" + "ER " not in normalized
    assert normalized.count("CREATE TABLE") == 1


def test_migration_6_adds_the_catalog_and_match_source_without_removing_anything():
    [(version, name, sql)] = [item for item in MIGRATIONS if item[0] == 6]
    assert version == 6 and name == "ingredient_catalog_and_match_source"
    normalized = " ".join(sql.split()).upper()
    assert "CREATE TABLE IF NOT EXISTS MFDS_INGREDIENT_CATALOG" in normalized
    assert "PRIMARY KEY (PAGE_NO, ROW_NO)" in normalized
    assert (
        "ALTER TABLE PRODUCT_INGREDIENTS ADD COLUMN IF NOT EXISTS MATCHED_BY"
        in normalized
    )
    assert "'KOR_EXACT'" in normalized and "'ENG_NAME_EXACT'" in normalized
    assert "DR" + "OP " not in normalized and "TRUNCATE" not in normalized
    assert (
        normalized.count("CREATE TABLE") == 1 and normalized.count("ALTER TABLE") == 1
    )
