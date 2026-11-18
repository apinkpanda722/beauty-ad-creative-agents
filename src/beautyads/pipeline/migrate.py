"""Apply PostgreSQL migrations only; live execution is performed by the user."""

import argparse
import sys

from beautyads.settings import DEFAULT_ENV_FILE, get_setting
from beautyads.store import apply_migrations, connect, postgres_dsn


def main(
    argv=None,
    *,
    environ=None,
    env_file=DEFAULT_ENV_FILE,
    out=None,
    connect_fn=connect,
    apply_fn=apply_migrations,
) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    out = sys.stdout if out is None else out
    config = {"environ": environ, "env_file": env_file}
    if get_setting("POSTGRES_PASSWORD", **config) is None:
        print("PREFLIGHT_FAILED ENV_MISSING:POSTGRES_PASSWORD", file=out)
        return 2
    try:
        connection = connect_fn(postgres_dsn(**config))
    except Exception:  # noqa: BLE001 -- connection diagnostics can contain credentials
        print("PREFLIGHT_FAILED POSTGRES_UNREACHABLE", file=out)
        return 2
    try:
        versions = apply_fn(connection)
        print(f"MIGRATIONS_APPLIED {versions}", file=out)
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
