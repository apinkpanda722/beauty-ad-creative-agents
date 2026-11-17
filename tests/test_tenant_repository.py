"""Every tenant operation is checked against recorded SQL, without PostgreSQL."""

import hashlib
import inspect
import json
import re

import pytest
from test_store import FakeConnection, FakeCursor
from test_tenant_domain import NOW, feedback, plan, profile

from beautyads.domain.tenant import (
    TenantContextMissing,
    TenantMismatch,
    TenantRepository,
)
from beautyads.store import PostgresTenantRepository
from beautyads.store.schema import MIGRATIONS

OPERATIONS = (
    "save_profile",
    "get_profile",
    "save_plan",
    "get_plan",
    "add_feedback",
    "list_feedback",
    "register_thread",
    "assert_thread_access",
)


def invoke(store, operation, tenant_id="brand-a"):
    args, kwargs = {
        "save_profile": ((profile(),), {}),
        "get_profile": ((), {}),
        "save_plan": ((plan(),), {}),
        "get_plan": (("plan-1",), {}),
        "add_feedback": ((feedback(),), {}),
        "list_feedback": ((), {"decision": "rejected", "since": NOW, "limit": 5}),
        "register_thread": (("brand-a:synthetic",), {}),
        "assert_thread_access": (("brand-a:synthetic",), {}),
    }[operation]
    return getattr(store, operation)(tenant_id, *args, **kwargs)


def test_protocol_and_implementation_have_tenant_first_and_explicit_limit():
    assert issubclass(PostgresTenantRepository, TenantRepository)
    for operation in OPERATIONS:
        for cls in (TenantRepository, PostgresTenantRepository):
            parameters = list(inspect.signature(getattr(cls, operation)).parameters)
            assert parameters[:2] == ["self", "tenant_id"]
    with pytest.raises(TypeError):
        PostgresTenantRepository(FakeConnection()).list_feedback("brand-a")


@pytest.mark.parametrize("operation", OPERATIONS)
def test_every_method_binds_tenant_in_each_statement_without_vacuous_success(operation):
    # Replies cover the INSERT then scoped ownership read in register_thread.
    conn = FakeConnection([FakeCursor([("brand-a",)]), FakeCursor([("brand-a",)])])
    if operation not in {"register_thread", "assert_thread_access"}:
        conn = FakeConnection()
    invoke(PostgresTenantRepository(conn), operation)
    statements = [
        (part.strip(), params)
        for query, params in conn.calls
        for part in query.split(";")
        if part.strip()
    ]
    assert statements, operation
    for query, params in statements:
        assert query.count("%s") == len(params)
        assert "brand-a" not in query
        if re.match(r"(SELECT|UPDATE|DELETE)\b", query, re.IGNORECASE):
            assert re.search(r"\bWHERE\s+(?:\w+\.)?tenant_id = %s", query)
            position = query[: query.index("tenant_id = %s")].count("%s")
            assert params[position] == "brand-a"
        else:
            match = re.match(r"INSERT INTO \w+\s*\(([^)]+)\)", query)
            assert match, query
            columns = [column.strip() for column in match[1].split(",")]
            assert "tenant_id" in columns
            assert params[columns.index("tenant_id")] == "brand-a"
            if "DO UPDATE" in query:
                condition = query.split("DO UPDATE", 1)[1]
                assert "tenant_id = %s" in condition
                assert params[-1] == "brand-a"


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("tenant_id", [None, "", " ", "UPPER", "a" * 33, "a/b"])
def test_invalid_tenant_runs_no_sql(operation, tenant_id):
    conn = FakeConnection()
    with pytest.raises(TenantContextMissing) as caught:
        invoke(PostgresTenantRepository(conn), operation, tenant_id)
    assert caught.value.code == "TENANT_CONTEXT_MISSING"
    assert conn.calls == [] and conn.commits == conn.rollbacks == 0


@pytest.mark.parametrize("operation", ["save_profile", "save_plan", "add_feedback"])
def test_record_tenant_cannot_override_session_tenant(operation):
    conn = FakeConnection()
    with pytest.raises(TenantMismatch):
        invoke(PostgresTenantRepository(conn), operation, "brand-b")
    assert conn.calls == []


@pytest.mark.parametrize(
    "write,read,factory",
    [
        ("save_profile", "get_profile", profile),
        ("save_plan", "get_plan", plan),
        ("add_feedback", "list_feedback", feedback),
    ],
)
@pytest.mark.parametrize("native_json", [False, True])
def test_records_roundtrip_and_values_are_bound(write, read, factory, native_json):
    conn = FakeConnection()
    item = factory()
    store = PostgresTenantRepository(conn)
    getattr(store, write)("brand-a", item)
    assert conn.commits == 1 and conn.rollbacks == 0
    query, params = conn.calls[0]
    columns = re.search(r"INSERT INTO \w+\s*\(([^)]+)\)", query)[1].split(",")
    values = dict(
        zip((c.strip() for c in columns), params[: len(columns)], strict=True)
    )
    for column in ("payload", "claims", "forbidden_terms"):
        if column in values:
            assert isinstance(values[column], str)
            if native_json:
                values[column] = json.loads(values[column])
    if write == "add_feedback":
        assert values["reason"] == item.reason and item.reason not in query
    conn.replies.append(FakeCursor([tuple(values.values())]))
    if read == "get_plan":
        result = store.get_plan("brand-a", item.plan_id)
    elif read == "list_feedback":
        [result] = store.list_feedback("brand-a", limit=10)
    else:
        result = store.get_profile("brand-a")
    assert result == item
    assert conn.rollbacks == 1 and conn.commits == 1


def test_other_tenant_plan_is_indistinguishable_from_missing():
    conn = FakeConnection()
    store = PostgresTenantRepository(conn)
    store.save_plan("brand-a", plan())
    assert store.get_plan("brand-b", "plan-1") is None
    assert store.get_plan("brand-b", "missing") is None
    for query, params in conn.calls[1:]:
        assert "WHERE tenant_id = %s AND plan_id = %s" in query
        assert params[0] == "brand-b"


def test_feedback_filters_limit_and_order_are_always_scoped():
    conn = FakeConnection()
    store = PostgresTenantRepository(conn)
    assert store.list_feedback("brand-a", limit=3) == []
    assert store.list_feedback("brand-b", decision="approved", since=NOW, limit=7) == []
    for query, params in conn.calls:
        assert "WHERE tenant_id = %s" in query
        assert "ORDER BY created_at DESC, id DESC" in query and "LIMIT %s" in query
    assert conn.calls[0][1] == ("brand-a", None, None, None, None, 3)
    assert conn.calls[1][1] == ("brand-b", "approved", "approved", NOW, NOW, 7)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_feedback_rejects_invalid_limit_before_sql(limit):
    conn = FakeConnection()
    with pytest.raises(ValueError):
        PostgresTenantRepository(conn).list_feedback("brand-a", limit=limit)
    assert conn.calls == []


def test_register_thread_is_idempotent_and_checks_ownership_in_same_transaction():
    conn = FakeConnection()
    store = PostgresTenantRepository(conn)
    for _ in range(2):
        conn.replies.extend([FakeCursor(), FakeCursor([("brand-a",)])])
        assert store.register_thread("brand-a", "brand-a:synthetic") is None
    assert conn.commits == 2 and conn.rollbacks == 0
    assert conn.calls[:2] == conn.calls[2:]
    assert "ON CONFLICT (thread_id) DO NOTHING" in conn.calls[0][0]
    conn.replies.append(FakeCursor([("brand-a",)]))
    assert store.assert_thread_access("brand-a", "brand-a:synthetic") is None


@pytest.mark.parametrize("operation", ["register_thread", "assert_thread_access"])
@pytest.mark.parametrize("thread_id", ["brand-b:synthetic", "no-prefix", "INVALID:id"])
def test_thread_prefix_mismatch_rejected_before_sql(operation, thread_id):
    conn = FakeConnection()
    with pytest.raises(TenantMismatch):
        getattr(PostgresTenantRepository(conn), operation)("brand-a", thread_id)
    assert conn.calls == []


@pytest.mark.parametrize("operation", ["register_thread", "assert_thread_access"])
def test_missing_or_foreign_owner_fails_closed(operation):
    conn = FakeConnection()  # Tenant-filtered lookup returns no owner.
    with pytest.raises(TenantMismatch):
        getattr(PostgresTenantRepository(conn), operation)(
            "brand-a", "brand-a:synthetic"
        )
    assert conn.commits == 0 and conn.rollbacks == 1


@pytest.mark.parametrize("operation", OPERATIONS)
def test_sql_failure_rolls_back(operation):
    conn = FakeConnection(fail_on=lambda query: True)
    with pytest.raises(RuntimeError, match="scripted"):
        invoke(PostgresTenantRepository(conn), operation)
    assert conn.commits == 0 and conn.rollbacks == 1


@pytest.mark.parametrize(
    "operation",
    [
        "get_profile",
        "get_plan",
        "list_feedback",
        "assert_thread_access",
        "register_thread",
    ],
)
def test_fetch_precedes_transaction_end_and_fetch_failure_rolls_back(operation):
    conn = FakeConnection()

    class FailingCursor(FakeCursor):
        def fetchall(self):
            assert conn.commits == conn.rollbacks == 0
            raise RuntimeError("scripted fetch failure")

    if operation == "register_thread":
        conn.replies.append(FakeCursor())
    conn.replies.append(FailingCursor())
    with pytest.raises(RuntimeError, match="scripted fetch"):
        invoke(PostgresTenantRepository(conn), operation)
    assert conn.commits == 0 and conn.rollbacks == 1


def test_tenant_migration_appends_v7_without_changing_any_prior_sql():
    assert [version for version, _, _ in MIGRATIONS] == [1, 2, 3, 4, 5, 6, 7]
    assert [
        hashlib.sha256(sql.encode()).hexdigest() for _, _, sql in MIGRATIONS[:-1]
    ] == [
        "8baf3f2382951c0e20ca5bdf88761931728603c5f80b3c3724617046022c5c53",
        "4d36a1f91e86c749dcff01adb580eb39704538c60f7f206477430fb278b22ebe",
        "9f5343670f2a756e2d415e0b7599caec33705cb16b383869411232567866873e",
        "6c852dafe95197d43263404e9c29f000d3e85e535a5e3b4fb2de3727056e31be",
        "bf30c408b80b1a2b77d6f53aa8311fa824e7340df0b46c6cbaaf723bd6febceb",
        "71c26c70c60002250821d16cee8fcacbf250a87c4b517a10ddbc23f4cba41c41",
    ]
    version, name, sql = MIGRATIONS[-1]
    assert version == MIGRATIONS[-2][0] + 1 and name == "tenant_memory"
    assert not re.search(r"\b(DROP|TRUNCATE|DELETE FROM)\b", sql, re.IGNORECASE)
    statements = [part.strip() for part in sql.split(";") if part.strip()]
    assert statements and all(
        re.match(r"CREATE (TABLE|INDEX) IF NOT EXISTS ", part) for part in statements
    )
    for table in (
        "tenant_profiles",
        "tenant_plans",
        "tenant_feedback",
        "tenant_threads",
    ):
        [statement] = [
            s
            for s in statements
            if s.startswith(f"CREATE TABLE IF NOT EXISTS {table} (")
        ]
        assert re.search(r"\btenant_id text NOT NULL\b", statement)
    assert "PRIMARY KEY (tenant_id, plan_id)" in sql
    assert "ON tenant_feedback (tenant_id, created_at)" in sql
    for fragment in (
        "payload jsonb",
        "claims jsonb",
        "updated_at timestamptz",
        "id bigserial",
        "thread_id text NOT NULL PRIMARY KEY",
    ):
        assert fragment in sql
