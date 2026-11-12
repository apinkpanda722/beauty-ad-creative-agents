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
