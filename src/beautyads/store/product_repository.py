"""Product source of truth behind the existing SQL connection protocol."""

import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from beautyads.domain.products import (
    CachedIngredientStandard,
    Product,
    ProductCert,
    ProductExtraction,
    ProductIngredient,
    ProductKey,
    ProductPrice,
    ProductRepository,
)
from beautyads.store.connection import SqlConnection

_PRODUCT_COLUMNS = (
    "brand",
    "source_url",
    "category",
    "name_ko",
    "name_en",
    "aliases",
    "volume",
    "volume_unit",
    "list_price",
    "sale_price",
    "price_basis",
    "price_collected_at",
    "form",
    "skin_types",
    "efficacy_texts",
    "functional_texts",
)
_INGREDIENT_COLUMNS = (
    "brand",
    "source_url",
    "ingredient_order",
    "raw_name",
    "standard_name",
    "status",
)
_CERT_COLUMNS = (
    "brand",
    "source_url",
    "kind",
    "status",
    "evidence_item_name",
    "evidence_api",
)
_PRICE_COLUMNS = (
    "brand",
    "source_url",
    "collected_at",
    "list_price",
    "sale_price",
    "price_basis",
)
_EXTRACTION_COLUMNS = ("brand", "source_url", "prompt_version", "raw_output")
_STANDARD_COLUMNS = ("name_ko", "name_en", "cas_no", "queried_at")
_JSON_COLUMNS = frozenset(
    {"aliases", "skin_types", "efficacy_texts", "functional_texts"}
)
_KEY_CONDITION = " WHERE brand = %s AND source_url = %s"


def _insert_sql(table: str, columns: tuple[str, ...]) -> str:
    # Identifiers come exclusively from the fixed module constants below.
    placeholders = ", ".join(
        "%s::jsonb" if column in _JSON_COLUMNS else "%s" for column in columns
    )
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"


def _upsert_sql(table: str, columns: tuple[str, ...], keys: tuple[str, ...]) -> str:
    changed = tuple(column for column in columns if column not in keys)
    assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in changed)
    old = ", ".join(f"{table}.{column}" for column in changed)
    new = ", ".join(f"EXCLUDED.{column}" for column in changed)
    return (
        _insert_sql(table, columns)
        + f" ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {assignments}, updated_at = now()"
        + f" WHERE ({old}) IS DISTINCT FROM ({new})"
    )


_PRODUCT_UPSERT = _upsert_sql("products", _PRODUCT_COLUMNS, ("brand", "source_url"))
_INGREDIENT_UPSERT = _upsert_sql(
    "product_ingredients",
    _INGREDIENT_COLUMNS,
    ("brand", "source_url", "ingredient_order"),
)
_CERT_UPSERT = _upsert_sql(
    "product_certs", _CERT_COLUMNS, ("brand", "source_url", "kind")
)
_PRICE_INSERT = _insert_sql("product_prices", _PRICE_COLUMNS)
_EXTRACTION_INSERT = _insert_sql("product_extractions", _EXTRACTION_COLUMNS)
_STANDARD_UPSERT = (
    _insert_sql("ingredient_standards", _STANDARD_COLUMNS)
    + " ON CONFLICT (name_ko) DO UPDATE SET name_en = EXCLUDED.name_en,"
    + " cas_no = EXCLUDED.cas_no, queried_at = EXCLUDED.queried_at"
)


def _values(record: BaseModel, columns: tuple[str, ...]) -> tuple[Any, ...]:
    data = record.model_dump()
    key = data.pop("product", None)
    if key is not None:
        data.update(key)
    if "order" in data:
        data["ingredient_order"] = data.pop("order")
    for column in _JSON_COLUMNS.intersection(data):
        data[column] = json.dumps(data[column], ensure_ascii=False)
    return tuple(data[column] for column in columns)


def _restore[Record: BaseModel](
    model: type[Record], columns: tuple[str, ...], row: Sequence[Any]
) -> Record:
    data = dict(zip(columns, row, strict=True))
    for column in _JSON_COLUMNS.intersection(data):
        if isinstance(data[column], str):
            data[column] = json.loads(data[column])
    if model is not Product and "brand" in data:
        data["product"] = {
            "brand": data.pop("brand"),
            "source_url": data.pop("source_url"),
        }
    if "ingredient_order" in data:
        data["order"] = data.pop("ingredient_order")
    return model.model_validate(data, context={"from_store": True})


class PostgresProductStore(ProductRepository):
    def __init__(self, conn: SqlConnection):
        self.conn = conn

    def _write(self, statements: Iterable[tuple[str, Sequence[Any]]]) -> None:
        try:
            for query, params in statements:
                self.conn.execute(query, params)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _read[Record: BaseModel](
        self,
        model: type[Record],
        table: str,
        columns: tuple[str, ...],
        *,
        condition: str = "",
        params: Sequence[Any] = (),
        order: str,
    ) -> list[Record]:
        # Fetch before rollback. As with the creative store, callers must
        # serialize use of a shared connection, including reads.
        try:
            rows = self.conn.execute(
                f"SELECT {', '.join(columns)} FROM {table}{condition} ORDER BY {order}",
                params,
            ).fetchall()
        except Exception:
            self.conn.rollback()
            raise
        self.conn.rollback()
        return [_restore(model, columns, row) for row in rows]

    def upsert_product(self, product: Product) -> None:
        statements = [(_PRODUCT_UPSERT, _values(product, _PRODUCT_COLUMNS))]
        if product.price_collected_at is not None:
            price = ProductPrice(
                product=product.key,
                collected_at=product.price_collected_at,
                list_price=product.list_price,
                sale_price=product.sale_price,
                price_basis=product.price_basis,
            )
            statements.append((_PRICE_INSERT, _values(price, _PRICE_COLUMNS)))
        self._write(statements)

    def get_product(self, key: ProductKey) -> Product | None:
        rows = self._read(
            Product,
            "products",
            (*_PRODUCT_COLUMNS, "updated_at"),
            condition=_KEY_CONDITION,
            params=(key.brand, key.source_url),
            order="brand, source_url",
        )
        return next(iter(rows), None)

    def list_products(self) -> list[Product]:
        return self._read(
            Product,
            "products",
            (*_PRODUCT_COLUMNS, "updated_at"),
            order="brand, source_url",
        )

    def add_price(self, price: ProductPrice) -> None:
        self._write([(_PRICE_INSERT, _values(price, _PRICE_COLUMNS))])

    def get_prices(self, key: ProductKey) -> list[ProductPrice]:
        return self._read(
            ProductPrice,
            "product_prices",
            _PRICE_COLUMNS,
            condition=_KEY_CONDITION,
            params=(key.brand, key.source_url),
            order="collected_at, id",
        )

    def upsert_ingredients(self, ingredients: Sequence[ProductIngredient]) -> None:
        if ingredients:
            self._write(
                (_INGREDIENT_UPSERT, _values(item, _INGREDIENT_COLUMNS))
                for item in ingredients
            )

    def get_ingredients(self, key: ProductKey) -> list[ProductIngredient]:
        return self._read(
            ProductIngredient,
            "product_ingredients",
            (*_INGREDIENT_COLUMNS, "updated_at"),
            condition=_KEY_CONDITION,
            params=(key.brand, key.source_url),
            order="ingredient_order",
        )

    def upsert_certs(self, certs: Sequence[ProductCert]) -> None:
        if certs:
            self._write((_CERT_UPSERT, _values(item, _CERT_COLUMNS)) for item in certs)

    def get_certs(self, key: ProductKey) -> list[ProductCert]:
        return self._read(
            ProductCert,
            "product_certs",
            (*_CERT_COLUMNS, "updated_at"),
            condition=_KEY_CONDITION,
            params=(key.brand, key.source_url),
            order="kind",
        )

    def add_extraction(self, extraction: ProductExtraction) -> None:
        self._write([(_EXTRACTION_INSERT, _values(extraction, _EXTRACTION_COLUMNS))])

    def get_extractions(self, key: ProductKey) -> list[ProductExtraction]:
        return self._read(
            ProductExtraction,
            "product_extractions",
            _EXTRACTION_COLUMNS,
            condition=_KEY_CONDITION,
            params=(key.brand, key.source_url),
            order="id",
        )

    def get_ingredient_standard(self, name_ko: str) -> CachedIngredientStandard | None:
        rows = self._read(
            CachedIngredientStandard,
            "ingredient_standards",
            _STANDARD_COLUMNS,
            condition=" WHERE name_ko = %s",
            params=(name_ko,),
            order="name_ko",
        )
        return next(iter(rows), None)

    def upsert_ingredient_standard(self, standard: CachedIngredientStandard) -> None:
        self._write([(_STANDARD_UPSERT, _values(standard, _STANDARD_COLUMNS))])

    def _changed[Record: BaseModel](
        self,
        model: type[Record],
        table: str,
        columns: tuple[str, ...],
        *,
        since: datetime | None,
        order: str,
    ) -> list[Record]:
        return self._read(
            model,
            table,
            (*columns, "updated_at"),
            condition="" if since is None else " WHERE updated_at > %s",
            params=() if since is None else (since,),
            order=f"updated_at, {order}",
        )

    def read_changed_products(self, *, since: datetime | None) -> list[Product]:
        return self._changed(
            Product,
            "products",
            _PRODUCT_COLUMNS,
            since=since,
            order="brand, source_url",
        )

    def read_changed_ingredients(
        self, *, since: datetime | None
    ) -> list[ProductIngredient]:
        return self._changed(
            ProductIngredient,
            "product_ingredients",
            _INGREDIENT_COLUMNS,
            since=since,
            order="brand, source_url, ingredient_order",
        )

    def read_changed_certs(self, *, since: datetime | None) -> list[ProductCert]:
        return self._changed(
            ProductCert,
            "product_certs",
            _CERT_COLUMNS,
            since=since,
            order="brand, source_url, kind",
        )
