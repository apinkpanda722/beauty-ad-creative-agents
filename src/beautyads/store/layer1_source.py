"""Read coherent product snapshots using PostgreSQL change times, not graph counts."""

from datetime import datetime

from beautyads.domain.layer1 import Layer1SyncSource, SyncProduct
from beautyads.domain.mfds import IngredientStandard
from beautyads.domain.products import Product, ProductCert, ProductIngredient
from beautyads.store.connection import SqlConnection
from beautyads.store.product_repository import (
    _CERT_COLUMNS,
    _INGREDIENT_COLUMNS,
    _PRODUCT_COLUMNS,
    _restore,
)
from beautyads.store.sync_source import PostgresGraphSyncSource

SYNC_NAME = "public_products_layer1_v1"


class PostgresLayer1Source(Layer1SyncSource):
    def __init__(self, conn: SqlConnection):
        self.conn = conn

    def read_changed(
        self, *, since: datetime | None, limit: int | None
    ) -> list[SyncProduct]:
        query = f"""
            WITH changed AS (
                SELECT {", ".join(f"p.{c}" for c in _PRODUCT_COLUMNS)},
                    GREATEST(p.updated_at,
                        (SELECT max(i.updated_at) FROM product_ingredients AS i
                         WHERE i.brand = p.brand AND i.source_url = p.source_url),
                        (SELECT max(c.updated_at) FROM product_certs AS c
                         WHERE c.brand = p.brand AND c.source_url = p.source_url),
                        (SELECT max(e.created_at) FROM product_extractions AS e
                         WHERE e.brand = p.brand AND e.source_url = p.source_url)
                    ) AS updated_at
                FROM products AS p
            )
            SELECT {", ".join((*_PRODUCT_COLUMNS, "updated_at"))} FROM changed
        """
        params = []
        if since is not None:
            query += " WHERE updated_at > %s"
            params.append(since)
        query += " ORDER BY updated_at, brand, source_url"
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        try:
            # The cutoff and the complete ingredient/cert sets must see the same
            # snapshot even when a product is being re-parsed concurrently.
            self.conn.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            rows = self.conn.execute(query, tuple(params)).fetchall()
            entries = []
            for row in rows:
                product = _restore(Product, (*_PRODUCT_COLUMNS, "updated_at"), row)
                key_params = (product.brand, product.source_url)

                def children(model, table, columns, order, key_params=key_params):
                    results = self.conn.execute(
                        f"SELECT {', '.join((*columns, 'updated_at'))} FROM {table} "
                        f"WHERE brand = %s AND source_url = %s ORDER BY {order}",
                        key_params,
                    ).fetchall()
                    return [
                        _restore(model, (*columns, "updated_at"), item)
                        for item in results
                    ]

                ingredients = children(
                    ProductIngredient,
                    "product_ingredients",
                    _INGREDIENT_COLUMNS,
                    "ingredient_order",
                )
                certs = children(ProductCert, "product_certs", _CERT_COLUMNS, "kind")
                names = sorted(
                    {i.standard_name for i in ingredients if i.standard_name}
                )
                # The catalog is the source used by product-records; the older
                # exact-lookup cache is a fallback. Never match by partial names.
                standards = self.conn.execute(
                    """SELECT DISTINCT ON (name_ko) name_ko, name_en, cas_no
                       FROM (
                         SELECT name_ko, name_en, cas_no, 1 AS priority,
                                0 AS page_no, 0 AS row_no
                         FROM ingredient_standards WHERE name_ko = ANY(%s)
                         UNION ALL
                         SELECT name_ko, name_en, cas_no, 0 AS priority, page_no, row_no
                         FROM mfds_ingredient_catalog WHERE name_ko = ANY(%s)
                       ) AS standards ORDER BY name_ko, priority, page_no, row_no""",
                    (names, names),
                ).fetchall()
                entries.append(
                    SyncProduct(
                        product=product,
                        updated_at=product.updated_at,
                        ingredients=ingredients,
                        certs=certs,
                        standards=[
                            IngredientStandard(name_ko=ko, name_en=en, cas_no=cas)
                            for ko, en, cas in standards
                        ],
                    )
                )
        except Exception:
            self.conn.rollback()
            raise
        self.conn.rollback()
        return entries

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
