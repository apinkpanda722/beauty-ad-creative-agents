"""The only PostgreSQL SDK boundary; configuration stays in settings."""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import quote

import psycopg

from beautyads.settings import DEFAULT_ENV_FILE, get_setting, require_setting


class SqlCursor(Protocol):
    rowcount: int

    def fetchall(self) -> list[Sequence[Any]]: ...

    def fetchone(self) -> Sequence[Any] | None: ...


class SqlConnection(Protocol):
    def execute(self, query: str, params: Sequence[Any] | None = None) -> SqlCursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def postgres_dsn(
    *,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = DEFAULT_ENV_FILE,
) -> str:
    password = require_setting("POSTGRES_PASSWORD", environ=environ, env_file=env_file)
    port = get_setting(
        "BEAUTYADS_POSTGRES_PORT", "5433", environ=environ, env_file=env_file
    )
    host = get_setting(
        "BEAUTYADS_POSTGRES_HOST", "127.0.0.1", environ=environ, env_file=env_file
    )
    return f"postgresql://beautyads:{quote(password, safe='')}@{host}:{port}/beautyads"


class StoreConnectError(Exception):
    """A stable public reason without driver diagnostics or credentials."""

    def __init__(
        self, code: Literal["POSTGRES_AUTH_FAILED", "POSTGRES_CONNECT_FAILED"]
    ):
        self.code = code
        super().__init__(code)


def connect(
    dsn: str, *, connect_fn: Callable[[str], Any] | None = None
) -> SqlConnection:
    driver_connect = psycopg.connect if connect_fn is None else connect_fn
    try:
        return driver_connect(dsn)
    except psycopg.OperationalError as error:
        if (
            "password authentication failed" in str(error).lower()
            or error.sqlstate == "28P01"
        ):
            raise StoreConnectError("POSTGRES_AUTH_FAILED") from None
        raise StoreConnectError("POSTGRES_CONNECT_FAILED") from None
