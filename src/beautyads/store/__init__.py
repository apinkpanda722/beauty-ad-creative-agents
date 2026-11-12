"""PostgreSQL source-of-truth storage, with injectable SQL connections."""

from beautyads.store.connection import (
    SqlConnection,
    SqlCursor,
    StoreConnectError,
    connect,
    postgres_dsn,
)
from beautyads.store.repository import PostgresCreativeStore
from beautyads.store.schema import apply_migrations

__all__ = [
    "PostgresCreativeStore",
    "SqlConnection",
    "SqlCursor",
    "StoreConnectError",
    "apply_migrations",
    "connect",
    "postgres_dsn",
]
