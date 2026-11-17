"""SQL shape plus a stateful fake; no PostgreSQL connection is opened."""

import json
import re
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest
from test_products_domain import product_data
from test_store import FakeConnection, FakeCursor

from beautyads.domain.mfds import CertStatus
from beautyads.domain.products import (
    CachedIngredientStandard,
    IngredientCatalogEntry,
    IngredientLookup,
    Product,
    ProductCert,
    ProductExtraction,
    ProductIngredient,
    ProductRepository,
)
from beautyads.store.product_repository import PostgresProductStore

NOW = datetime(2026, 11, 15, tzinfo=UTC)


class MemoryConnection(FakeConnection):
    """Emulate conflict comparisons, not a substitute for a live SQL check."""

    KEYS: ClassVar[dict[str, tuple[str, ...]]] = {
        "products": ("brand", "source_url"),
        "product_ingredients": ("brand", "source_url", "ingredient_order"),
        "product_certs": ("brand", "source_url", "kind"),
        "ingredient_standards": ("name_ko",),
        "ingredient_lookups": ("query_key", "kind"),
        "mfds_ingredient_catalog": ("page_no", "row_no"),
    }

    def __init__(self, *, native_json=True):
        super().__init__()
        self.tables = {}
        self.native_json = native_json

    def execute(self, query, params=None):
        self.calls.append((query, params))
        insert = re.search(r"INSERT INTO (\w+) \(([^)]+)\)", query)
        if insert:
            table, columns = insert.groups()
            columns = [column.strip() for column in columns.split(",")]
            assert len(columns) == len(params) == query.count("%s")
            row = dict(zip(columns, params, strict=True))
            for column in (
                "aliases",
                "skin_types",
                "efficacy_texts",
                "functional_texts",
            ):
                if column in row:
                    assert isinstance(row[column], str)
                    assert isinstance(json.loads(row[column]), list)
                    if self.native_json:
                        row[column] = json.loads(row[column])
            rows = self.tables.setdefault(table, [])
            keys = self.KEYS.get(table)
            existing = next(
                (old for old in rows if keys and all(old[k] == row[k] for k in keys)),
                None,
            )
            if keys and table not in {
                "ingredient_standards",
                "ingredient_lookups",
                "mfds_ingredient_catalog",
            }:
                assert "updated_at = now()" in query
                assert "IS DISTINCT FROM" in query
                for column in columns:
                    if column not in keys:
                        assert f"{table}.{column}" in query.split("WHERE", 1)[1]
                        assert f"EXCLUDED.{column}" in query.split("WHERE", 1)[1]
            if existing is not None:
                if all(existing[column] == row[column] for column in columns):
                    return FakeCursor(rowcount=0)
                existing.update(row)
                existing["updated_at"] = NOW + timedelta(seconds=len(self.calls))
            else:
                if table in {"products", "product_ingredients", "product_certs"}:
                    row["updated_at"] = NOW + timedelta(seconds=len(self.calls))
                rows.append(row)
            return FakeCursor()
        delete = re.search(
            r"DELETE FROM (\w+) WHERE brand = %s AND source_url = %s"
            r" AND ingredient_order > %s",
            " ".join(query.split()),
        )
        if delete:
            table = delete.group(1)
            brand, url, keep = params
            rows = self.tables.get(table, [])
            kept = [
                row
                for row in rows
                if not (
                    (row["brand"], row["source_url"]) == (brand, url)
                    and row["ingredient_order"] > keep
                )
            ]
            removed = len(rows) - len(kept)
            self.tables[table] = kept
            return FakeCursor(rowcount=removed)
        select = re.search(r"SELECT (.+?) FROM (\w+)", " ".join(query.split()))
        if select:
            columns, table = select.groups()
            columns = [column.strip() for column in columns.split(",")]
            rows = self.tables.get(table, [])
            if "WHERE brand = %s AND source_url = %s" in query:
                rows = [
                    row
                    for row in rows
                    if (row["brand"], row["source_url"]) == tuple(params)
                ]
            if "WHERE name_ko = %s" in query:
                rows = [row for row in rows if row["name_ko"] == params[0]]
            if "WHERE query_key = %s AND kind = %s" in query:
                rows = [
                    row
                    for row in rows
                    if (row["query_key"], row["kind"]) == tuple(params)
                ]
            if "updated_at > %s" in query:
                rows = [row for row in rows if row["updated_at"] > params[0]]
            return FakeCursor(
                [tuple(row[column] for column in columns) for row in rows]
            )
        raise AssertionError(f"Unexpected SQL: {query}")


def product(**changes):
    return Product.model_validate(
        product_data(
            list_price="10000",
            sale_price="8000",
            price_basis="list_price",
            price_collected_at=NOW,
            skin_types=["건성", "민감성"],
            **changes,
        )
    )


@pytest.mark.parametrize("native_json", [True, False])
def test_upsert_noop_changed_value_and_json_roundtrip(native_json):
    conn = MemoryConnection(native_json=native_json)
    store: ProductRepository = PostgresProductStore(conn)
    item = product()
    store.upsert_product(item)
    first = store.get_product(item.key)
    store.upsert_product(item)
    second = store.get_product(item.key)
    assert first.updated_at == second.updated_at
    assert second.aliases == item.aliases and second.skin_types == item.skin_types
    assert len(conn.tables["products"]) == 1
    changed = product(name_ko="새 합성성분 세럼")
    store.upsert_product(changed)
    third = store.get_product(item.key)
    assert third.name_ko == changed.name_ko and third.updated_at > first.updated_at
    assert (
        len([q for q, _ in conn.calls if q.lstrip().startswith("INSERT INTO products")])
        == 3
    )
    assert conn.commits == 3 and conn.rollbacks == 3


def test_price_history_keeps_two_collections_and_latest_product():
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    first = product()
    second = first.model_copy(
        update={
            "sale_price": first.sale_price - 1000,
            "price_collected_at": NOW + timedelta(days=1),
        }
    )
    store.upsert_product(first)
    store.upsert_product(second)
    prices = store.get_prices(first.key)
    assert len(prices) == 2
    assert [price.collected_at for price in prices] == [NOW, NOW + timedelta(days=1)]
    assert [price.sale_price for price in prices] == [
        first.sale_price,
        second.sale_price,
    ]
    assert store.get_product(first.key).sale_price == second.sale_price
    assert all(
        "ON CONFLICT" not in query
        for query, _ in conn.calls
        if "INSERT INTO product_prices" in query
    )


def test_mechanically_empty_aliases_survive_storage():
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    item = Product.model_validate(
        product_data(name_ko="X 선 세럼"),
        context={"brand_products": ["X 선 세럼", "X 선 세럼 B"]},
    )
    store.upsert_product(item)
    assert store.get_product(item.key).aliases == []
    assert "product_prices" not in conn.tables


@pytest.mark.parametrize(
    "record_type,write,read,table,changes",
    [
        (
            ProductIngredient,
            "upsert_ingredients",
            "get_ingredients",
            "product_ingredients",
            {"order": 1, "raw_name": "미해결 원문", "status": "unresolved"},
        ),
        (
            ProductCert,
            "upsert_certs",
            "get_certs",
            "product_certs",
            {"kind": "brightening", "status": "unknown", "evidence_api": "screening"},
        ),
    ],
)
def test_related_upsert_noop_changes_and_evidence(
    record_type, write, read, table, changes
):
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    key = product().key
    item = record_type(product=key, **changes)
    getattr(store, write)([item])
    first = getattr(store, read)(key)[0]
    getattr(store, write)([item])
    second = getattr(store, read)(key)[0]
    assert first.updated_at == second.updated_at
    if table == "product_ingredients":
        assert second.standard_name is None and second.raw_name == "미해결 원문"
        changed = item.model_copy(
            update={"standard_name": "합성 표준명", "status": "resolved"}
        )
    else:
        assert second.status == "unknown" and second.evidence_item_name is None
        changed = item.model_copy(
            update={"status": CertStatus.certified, "evidence_item_name": "근거 원문"}
        )
    getattr(store, write)([changed])
    third = getattr(store, read)(key)[0]
    assert third.updated_at > first.updated_at
    assert len(conn.tables[table]) == 1


def test_cache_and_raw_extractions_are_preserved_and_queryable():
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    standard = CachedIngredientStandard(
        name_ko="합성 표준명",
        name_en="Synthetic",
        cas_no="synthetic-cas",
        queried_at=NOW,
    )
    assert store.get_ingredient_standard(standard.name_ko) is None
    store.upsert_ingredient_standard(standard)
    assert store.get_ingredient_standard(standard.name_ko) == standard
    changed = standard.model_copy(update={"queried_at": NOW + timedelta(days=1)})
    store.upsert_ingredient_standard(changed)
    assert store.get_ingredient_standard(standard.name_ko) == changed
    key = product().key
    outputs = [
        ProductExtraction(
            product=key, prompt_version=f"synthetic-{i}", raw_output=f"  raw\n{i}  "
        )
        for i in range(2)
    ]
    for output in outputs:
        store.add_extraction(output)
    assert store.get_extractions(key) == outputs


@pytest.mark.parametrize(
    "method,table",
    [
        ("read_changed_products", "products"),
        ("read_changed_ingredients", "product_ingredients"),
        ("read_changed_certs", "product_certs"),
    ],
)
def test_incremental_reads_use_strict_postgres_timestamp_only(method, table):
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    store.upsert_product(product())
    store.upsert_ingredients(
        [
            ProductIngredient(
                product=product().key, order=1, raw_name="원문", status="unresolved"
            )
        ]
    )
    store.upsert_certs(
        [
            ProductCert(
                product=product().key,
                kind="anti_aging",
                status="unknown",
                evidence_api="report",
            )
        ]
    )
    timestamp = conn.tables[table][0]["updated_at"]
    assert len(getattr(store, method)(since=None)) == 1
    assert len(getattr(store, method)(since=timestamp - timedelta(microseconds=1))) == 1
    assert getattr(store, method)(since=timestamp) == []
    query, params = conn.calls[-1]
    assert "WHERE updated_at > %s" in query and params == (timestamp,)
    assert "neo4j" not in query.lower() and "counter" not in query.lower()
    assert "ORDER BY updated_at" in query


@pytest.mark.parametrize(
    "operation",
    [
        "get_product",
        "list_products",
        "get_prices",
        "get_ingredients",
        "get_certs",
        "get_extractions",
        "get_ingredient_standard",
        "read_changed_products",
        "read_changed_ingredients",
        "read_changed_certs",
    ],
)
@pytest.mark.parametrize("failure", [None, "execute", "fetch"])
def test_reads_fetch_before_rollback_empty_and_failure(operation, failure):
    conn = FakeConnection(fail_on=lambda query: failure == "execute")

    class Cursor(FakeCursor):
        def fetchall(self):
            assert conn.rollbacks == 0
            if failure == "fetch":
                raise RuntimeError("scripted fetch failure")
            return []

    conn.replies.append(Cursor())
    store = PostgresProductStore(conn)
    if operation.startswith("read_changed"):
        kwargs, args = {"since": NOW}, ()
    else:
        kwargs = {}
        args = (
            ()
            if operation == "list_products"
            else (
                "synthetic"
                if operation == "get_ingredient_standard"
                else product().key,
            )
        )
    if failure:
        with pytest.raises(RuntimeError, match="scripted"):
            getattr(store, operation)(*args, **kwargs)
    else:
        result = getattr(store, operation)(*args, **kwargs)
        assert result == (
            None if operation in {"get_product", "get_ingredient_standard"} else []
        )
    assert conn.rollbacks == 1 and conn.commits == 0


@pytest.mark.parametrize(
    "operation",
    [
        "upsert_product",
        "upsert_ingredients",
        "upsert_certs",
        "add_price",
        "add_extraction",
        "upsert_ingredient_standard",
    ],
)
def test_writes_rollback_on_sql_failure(operation):
    conn = FakeConnection(fail_on=lambda query: True)
    store = PostgresProductStore(conn)
    key = product().key
    from beautyads.domain.products import ProductPrice

    values = {
        "upsert_product": product(),
        "upsert_ingredients": [
            ProductIngredient(
                product=key, order=1, raw_name="원문", status="unresolved"
            )
        ],
        "upsert_certs": [
            ProductCert(
                product=key, kind="brightening", status="unknown", evidence_api="report"
            )
        ],
        "add_price": ProductPrice(
            product=key, collected_at=NOW, list_price=1000, price_basis="list_price"
        ),
        "add_extraction": ProductExtraction(
            product=key, prompt_version="synthetic", raw_output="raw"
        ),
        "upsert_ingredient_standard": CachedIngredientStandard(
            name_ko="합성", queried_at=NOW
        ),
    }
    with pytest.raises(RuntimeError, match="scripted"):
        getattr(store, operation)(values[operation])
    assert conn.commits == 0 and conn.rollbacks == 1


def test_product_price_and_product_upsert_share_one_transaction():
    conn = FakeConnection(fail_on=lambda query: "INSERT INTO product_prices" in query)
    with pytest.raises(RuntimeError):
        PostgresProductStore(conn).upsert_product(product())
    assert len(conn.calls) == 2 and conn.commits == 0 and conn.rollbacks == 1


def test_sql_values_are_bound_not_interpolated():
    conn = FakeConnection()
    item = product(brand="O'Brien; --", name_ko="합성성분 '; -- 세럼")
    PostgresProductStore(conn).upsert_product(item)
    for query, params in conn.calls:
        assert item.brand not in query and item.name_ko not in query
        assert query.count("%s") == len(params)


def test_ingredient_lookup_cache_keeps_both_outcomes_per_lookup_kind():
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    assert store.get_ingredient_lookup("합성성분", "kor_exact") is None
    resolved = IngredientLookup(
        query_key="합성성분",
        kind="kor_exact",
        standard_name="합성성분",
        queried_at=NOW,
    )
    absent = IngredientLookup(
        query_key="미등재", kind="kor_exact", standard_name=None, queried_at=NOW
    )
    store.upsert_ingredient_lookup(resolved)
    store.upsert_ingredient_lookup(absent)
    assert store.get_ingredient_lookup("합성성분", "kor_exact") == resolved
    # "Looked up and not found" is stored, not merely missing from the cache.
    assert store.get_ingredient_lookup("미등재", "kor_exact") == absent
    # The same text under another lookup kind is a different cache entry.
    assert store.get_ingredient_lookup("합성성분", "eng_exact") is None
    newer = resolved.model_copy(update={"queried_at": NOW + timedelta(days=1)})
    store.upsert_ingredient_lookup(newer)
    assert store.get_ingredient_lookup("합성성분", "kor_exact") == newer
    assert len(conn.tables["ingredient_lookups"]) == 2


def test_ingredient_lookup_sql_values_are_bound():
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    sentinel = "quoted'; sentinel-statement; --"
    store.upsert_ingredient_lookup(
        IngredientLookup(
            query_key=sentinel, kind="kor_exact", standard_name=None, queried_at=NOW
        )
    )
    store.get_ingredient_lookup(sentinel, "kor_exact")
    assert all(sentinel not in query for query, _ in conn.calls)


def catalog_entry(page_no, row_no, name_ko, name_en=None, **changes):
    return IngredientCatalogEntry(
        page_no=page_no,
        row_no=row_no,
        name_ko=name_ko,
        name_en=name_en,
        cas_no=None,
        source_total=250,
        fetched_at=NOW,
        **changes,
    )


def test_catalog_pages_are_written_idempotently_and_resume_from_the_last_page():
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    assert store.catalog_last_page() == 0 and store.list_catalog() == []
    first = [
        catalog_entry(1, 0, "합성성분", "Synthetic"),
        catalog_entry(1, 1, "영문없음"),
    ]
    second = [catalog_entry(2, 0, "다른성분", "Other")]
    store.upsert_catalog_page(second)
    store.upsert_catalog_page(first)
    assert store.catalog_last_page() == 2
    # Writing the same page again replaces rows instead of duplicating them.
    store.upsert_catalog_page(first)
    listed = store.list_catalog()
    # The in-memory fake does not sort, so the ordering is checked on the SQL.
    assert sorted((e.page_no, e.row_no) for e in listed) == [(1, 0), (1, 1), (2, 0)]
    assert any(
        "FROM mfds_ingredient_catalog ORDER BY page_no, row_no" in " ".join(q.split())
        for q, _ in conn.calls
    )
    assert {(e.page_no, e.row_no): e.name_en for e in listed}[(1, 1)] is None
    assert len(conn.tables["mfds_ingredient_catalog"]) == 3


def test_a_catalog_page_is_one_transaction():
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    store.upsert_catalog_page([catalog_entry(1, i, f"성분{i}") for i in range(3)])
    assert conn.commits == 1


def test_catalog_sql_values_are_bound():
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    sentinel = "quoted'; sentinel-statement; --"
    store.upsert_catalog_page([catalog_entry(1, 0, sentinel, sentinel)])
    assert all(sentinel not in query for query, _ in conn.calls)


def test_match_source_roundtrips_and_only_resolved_rows_carry_one():
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    item = product()
    store.upsert_product(item)
    store.upsert_ingredients(
        [
            ProductIngredient(
                product=item.key,
                order=1,
                raw_name="Synthetic",
                standard_name="합성성분",
                status="resolved",
                matched_by="eng_name_exact",
            ),
            ProductIngredient(
                product=item.key, order=2, raw_name="미등재", status="unresolved"
            ),
        ]
    )
    rows = store.get_ingredients(item.key)
    assert [row.matched_by for row in rows] == ["eng_name_exact", None]
    with pytest.raises(ValueError):
        ProductIngredient(
            product=item.key,
            order=3,
            raw_name="x",
            status="unresolved",
            matched_by="kor_exact",
        )
    with pytest.raises(ValueError):
        ProductIngredient(
            product=item.key,
            order=3,
            raw_name="x",
            standard_name="y",
            status="resolved",
            matched_by="fuzzy",
        )


def ingredient_rows(key, count, **changes):
    return [
        ProductIngredient(
            product=key, order=i, raw_name=f"원문{i}", status="unresolved", **changes
        )
        for i in range(1, count + 1)
    ]


def test_replace_ingredients_drops_surplus_rows_in_the_same_transaction():
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    item = product()
    store.upsert_product(item)
    store.replace_ingredients(item.key, ingredient_rows(item.key, 5))
    commits = conn.commits
    store.replace_ingredients(item.key, ingredient_rows(item.key, 3))
    assert conn.commits == commits + 1  # upserts and the delete are one transaction
    assert [r.order for r in store.get_ingredients(item.key)] == [1, 2, 3]
    delete = next(q for q, _ in conn.calls if q.lstrip().startswith("DELETE"))
    assert "ingredient_order > %s" in delete


def test_replace_with_the_same_rows_keeps_updated_at_and_other_products():
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    item = product()
    other = product(source_url="https://example.com/other")
    store.upsert_product(item)
    store.upsert_product(other)
    store.replace_ingredients(item.key, ingredient_rows(item.key, 3))
    store.replace_ingredients(other.key, ingredient_rows(other.key, 4))
    before = store.get_ingredients(item.key)
    store.replace_ingredients(item.key, ingredient_rows(item.key, 3))
    assert store.get_ingredients(item.key) == before
    assert len(store.get_ingredients(other.key)) == 4


def test_replace_with_an_empty_list_removes_the_product_ingredients():
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    item = product()
    store.upsert_product(item)
    store.replace_ingredients(item.key, ingredient_rows(item.key, 2))
    store.replace_ingredients(item.key, [])
    assert store.get_ingredients(item.key) == []


def test_replace_rejects_rows_of_another_product_and_writes_nothing():
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    item = product()
    other = product(source_url="https://example.com/other")
    with pytest.raises(ValueError):
        store.replace_ingredients(item.key, ingredient_rows(other.key, 2))
    assert not conn.calls


def test_trim_ingredients_returns_the_number_of_rows_deleted():
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    item = product()
    store.upsert_product(item)
    store.replace_ingredients(item.key, ingredient_rows(item.key, 5))
    assert store.trim_ingredients(item.key, 3) == 2
    assert store.trim_ingredients(item.key, 3) == 0
    assert [r.order for r in store.get_ingredients(item.key)] == [1, 2, 3]


def test_replace_and_trim_roll_back_on_sql_failure():
    conn = FakeConnection(fail_on=lambda query: True)
    store = PostgresProductStore(conn)
    key = product().key
    with pytest.raises(Exception):  # noqa: B017 -- any driver error must propagate
        store.replace_ingredients(key, ingredient_rows(key, 1))
    with pytest.raises(Exception):  # noqa: B017
        store.trim_ingredients(key, 1)
    assert conn.rollbacks == 2 and conn.commits == 0


def test_count_ingredients_counts_only_that_product():
    conn = MemoryConnection()
    store = PostgresProductStore(conn)
    item = product()
    other = product(source_url="https://example.com/other")
    store.upsert_product(item)
    store.upsert_product(other)
    store.replace_ingredients(item.key, ingredient_rows(item.key, 3))
    store.replace_ingredients(other.key, ingredient_rows(other.key, 5))
    assert store.count_ingredients(item.key) == 3
