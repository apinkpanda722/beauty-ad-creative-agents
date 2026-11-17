"""Additive migrations and the single definition of creative change columns."""

from beautyads.store.connection import SqlConnection

CHANGE_COLUMNS: tuple[str, ...] = (
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

MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "creative_source_of_truth",
        """
        CREATE TABLE IF NOT EXISTS creatives (
            source text,
            source_id text,
            url text,
            title text,
            caption text,
            published_at timestamptz,
            duration_s double precision,
            language text,
            analyzable boolean,
            latest_view_count bigint,
            latest_like_count bigint,
            latest_comment_count bigint,
            metrics_collected_at timestamptz,
            first_seen_at timestamptz DEFAULT now(),
            collected_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (source, source_id)
        );
        CREATE TABLE IF NOT EXISTS metrics_history (
            source text,
            source_id text,
            collected_at timestamptz,
            view_count bigint,
            like_count bigint,
            comment_count bigint,
            PRIMARY KEY (source, source_id, collected_at)
        );
        CREATE TABLE IF NOT EXISTS model_outputs (
            id bigserial PRIMARY KEY,
            source text,
            source_id text,
            kind text,
            model text,
            thinking_level text,
            prompt_version text,
            raw_output text,
            created_at timestamptz DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS analysis_jobs (
            source text,
            source_id text,
            kind text,
            status text CHECK (status IN ('pending','done','held','failed')),
            attempts int DEFAULT 0,
            error_code text,
            labels jsonb,
            updated_at timestamptz DEFAULT now(),
            PRIMARY KEY (source, source_id, kind)
        );
        CREATE TABLE IF NOT EXISTS sync_state (
            name text PRIMARY KEY,
            last_synced_at timestamptz
        );
        """,
    ),
    (
        2,
        "creative_brand_account",
        """
        ALTER TABLE creatives ADD COLUMN IF NOT EXISTS brand text;
        ALTER TABLE creatives ADD COLUMN IF NOT EXISTS account text;
        """,
    ),
    (
        3,
        "creative_attributes",
        """
        ALTER TABLE creatives ADD COLUMN IF NOT EXISTS attributes jsonb;
        """,
    ),
    (
        4,
        "product_source_of_truth",
        """
        CREATE TABLE IF NOT EXISTS products (
            brand text NOT NULL,
            source_url text NOT NULL,
            category text NOT NULL
                CHECK (category IN ('mask_pack', 'serum_ampoule', 'sun_care')),
            name_ko text NOT NULL,
            name_en text,
            aliases jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(aliases) = 'array'),
            volume numeric CHECK (volume > 0),
            volume_unit text CHECK (volume_unit IN ('ml', 'g', '매', '입', 'ea')),
            list_price numeric CHECK (list_price >= 0),
            sale_price numeric CHECK (sale_price >= 0),
            price_basis text NOT NULL
                CHECK (price_basis IN ('list_price', 'sale_price_fallback')),
            price_collected_at timestamptz,
            form text,
            skin_types jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(skin_types) = 'array'),
            efficacy_texts jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(efficacy_texts) = 'array'),
            functional_texts jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(functional_texts) = 'array'),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (brand, source_url)
        );
        CREATE TABLE IF NOT EXISTS product_prices (
            id bigserial PRIMARY KEY,
            brand text NOT NULL,
            source_url text NOT NULL,
            collected_at timestamptz NOT NULL,
            list_price numeric CHECK (list_price >= 0),
            sale_price numeric CHECK (sale_price >= 0),
            price_basis text NOT NULL
                CHECK (price_basis IN ('list_price', 'sale_price_fallback')),
            FOREIGN KEY (brand, source_url) REFERENCES products (brand, source_url)
        );
        CREATE TABLE IF NOT EXISTS product_ingredients (
            brand text NOT NULL,
            source_url text NOT NULL,
            ingredient_order int NOT NULL CHECK (ingredient_order >= 1),
            raw_name text NOT NULL,
            standard_name text,
            status text NOT NULL CHECK (status IN ('resolved', 'unresolved')),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (brand, source_url, ingredient_order),
            CHECK ((status = 'resolved' AND standard_name IS NOT NULL)
                OR (status = 'unresolved' AND standard_name IS NULL)),
            FOREIGN KEY (brand, source_url) REFERENCES products (brand, source_url)
        );
        CREATE TABLE IF NOT EXISTS ingredient_standards (
            name_ko text PRIMARY KEY,
            name_en text,
            cas_no text,
            queried_at timestamptz NOT NULL
        );
        CREATE TABLE IF NOT EXISTS product_certs (
            brand text NOT NULL,
            source_url text NOT NULL,
            kind text NOT NULL
                CHECK (kind IN ('brightening', 'anti_aging', 'sun_protection')),
            status text NOT NULL CHECK (status IN ('certified', 'unknown')),
            evidence_item_name text,
            evidence_api text NOT NULL CHECK (evidence_api IN ('report', 'screening')),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (brand, source_url, kind),
            FOREIGN KEY (brand, source_url) REFERENCES products (brand, source_url)
        );
        CREATE TABLE IF NOT EXISTS product_extractions (
            id bigserial PRIMARY KEY,
            brand text NOT NULL,
            source_url text NOT NULL,
            prompt_version text NOT NULL,
            raw_output text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (brand, source_url) REFERENCES products (brand, source_url)
        );
        CREATE INDEX IF NOT EXISTS products_updated_at_idx
            ON products (updated_at, brand, source_url);
        CREATE INDEX IF NOT EXISTS product_ingredients_updated_at_idx
            ON product_ingredients (updated_at, brand, source_url, ingredient_order);
        CREATE INDEX IF NOT EXISTS product_certs_updated_at_idx
            ON product_certs (updated_at, brand, source_url, kind);
        CREATE INDEX IF NOT EXISTS product_prices_product_idx
            ON product_prices (brand, source_url, collected_at, id);
        CREATE INDEX IF NOT EXISTS product_extractions_product_idx
            ON product_extractions (brand, source_url, id);
        """,
    ),
    (
        5,
        "ingredient_lookup_cache",
        """
        CREATE TABLE IF NOT EXISTS ingredient_lookups (
            query_key text NOT NULL,
            kind text NOT NULL CHECK (kind IN ('kor_exact', 'eng_exact')),
            standard_name text,
            queried_at timestamptz NOT NULL,
            PRIMARY KEY (query_key, kind)
        );
        """,
    ),
    (
        6,
        "ingredient_catalog_and_match_source",
        """
        CREATE TABLE IF NOT EXISTS mfds_ingredient_catalog (
            page_no int NOT NULL CHECK (page_no >= 1),
            row_no int NOT NULL CHECK (row_no >= 0),
            name_ko text NOT NULL,
            name_en text,
            cas_no text,
            source_total int NOT NULL CHECK (source_total >= 1),
            fetched_at timestamptz NOT NULL,
            PRIMARY KEY (page_no, row_no)
        );
        ALTER TABLE product_ingredients ADD COLUMN IF NOT EXISTS matched_by text
            CHECK (matched_by IN ('kor_exact', 'eng_name_exact'));
        """,
    ),
    (
        7,
        "tenant_memory",
        """
        CREATE TABLE IF NOT EXISTS tenant_profiles (
            tenant_id text NOT NULL PRIMARY KEY,
            display_name text NOT NULL,
            brand text NOT NULL,
            own_product_url text NOT NULL,
            tone text NOT NULL,
            forbidden_terms jsonb NOT NULL
                CHECK (jsonb_typeof(forbidden_terms) = 'array'),
            price_band_pct double precision NOT NULL DEFAULT 30.0
                CHECK (price_band_pct > 0 AND price_band_pct <= 100)
        );
        CREATE TABLE IF NOT EXISTS tenant_plans (
            tenant_id text NOT NULL,
            plan_id text NOT NULL,
            thread_id text NOT NULL,
            payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            created_at timestamptz NOT NULL,
            PRIMARY KEY (tenant_id, plan_id)
        );
        CREATE TABLE IF NOT EXISTS tenant_feedback (
            id bigserial PRIMARY KEY,
            tenant_id text NOT NULL,
            plan_id text NOT NULL,
            decision text NOT NULL CHECK (decision IN ('approved', 'rejected')),
            reason text NOT NULL,
            hook_type text,
            claims jsonb NOT NULL CHECK (jsonb_typeof(claims) = 'array'),
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS tenant_feedback_tenant_created_idx
            ON tenant_feedback (tenant_id, created_at);
        CREATE TABLE IF NOT EXISTS tenant_threads (
            thread_id text NOT NULL PRIMARY KEY,
            tenant_id text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        """,
    ),
]

# Fixed identifiers and SQL types, never caller input. Explicit casts preserve
# parameter types even when the VALUES row contains only NULLs for a column.
INSERT_COLUMNS: tuple[str, ...] = (
    "source",
    "source_id",
    *CHANGE_COLUMNS,
    "metrics_collected_at",
    "collected_at",
)
_INSERT_TYPES: tuple[str, ...] = (
    "text",
    "text",
    "text",
    "text",
    "text",
    "timestamptz",
    "double precision",
    "text",
    "boolean",
    "text",
    "text",
    "bigint",
    "bigint",
    "bigint",
    "jsonb",
    "timestamptz",
    "timestamptz",
)
_METRIC_COLUMNS = ("latest_view_count", "latest_like_count", "latest_comment_count")


def build_upsert_sql() -> str:
    """Compare effective values only, so stale metrics and recollection are no-ops.

    Choose the latest metric snapshot before the conflict comparison. A separate
    metadata update advances the collection watermark even when values match.
    Only fixed schema identifiers are interpolated; data uses placeholders.
    """
    columns = ", ".join(INSERT_COLUMNS)
    placeholders = ", ".join(f"%s::{sql_type}" for sql_type in _INSERT_TYPES)
    selected = []
    for column in INSERT_COLUMNS:
        if column in _METRIC_COLUMNS:
            selected.append(
                "CASE WHEN creatives.metrics_collected_at IS NULL "
                "OR incoming.metrics_collected_at >= creatives.metrics_collected_at "
                f"THEN incoming.{column} ELSE creatives.{column} END"
            )
        elif column in {"metrics_collected_at", "collected_at"}:
            selected.append(f"GREATEST(incoming.{column}, creatives.{column})")
        else:
            selected.append(f"incoming.{column}")
    assignments = ",\n            ".join(
        f"{column} = EXCLUDED.{column}" for column in INSERT_COLUMNS[2:]
    )
    old = ", ".join(f"creatives.{column}" for column in CHANGE_COLUMNS)
    new = ", ".join(f"EXCLUDED.{column}" for column in CHANGE_COLUMNS)
    return f"""
        WITH incoming ({columns}) AS (VALUES ({placeholders}))
        INSERT INTO creatives ({columns})
        (SELECT {", ".join(selected)}
         FROM incoming LEFT JOIN creatives
         ON creatives.source = incoming.source
            AND creatives.source_id = incoming.source_id)
        ON CONFLICT (source, source_id) DO UPDATE SET
            {assignments},
            updated_at = now()
        WHERE ({old}) IS DISTINCT FROM ({new})
    """


def apply_migrations(conn: SqlConnection) -> list[int]:
    applied = []
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version int PRIMARY KEY,
                name text,
                applied_at timestamptz DEFAULT now()
            )
        """)
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        existing = {row[0] for row in rows}
        for version, name, sql in sorted(MIGRATIONS):
            if version in existing:
                continue
            conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                (version, name),
            )
            conn.commit()
            applied.append(version)
        if not applied:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return applied
