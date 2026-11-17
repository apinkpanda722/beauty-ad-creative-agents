"""One-time cleanup: delete ingredient rows left past a product's latest ingredient count.

Before the whole-set replacement, a shorter re-parse left the old tail rows. The
latest run report (records.json) knows each stored product's ingredient count n, so
rows whose order is greater than n are stale. Products the run did not store
(held, pending, failed) are never touched. The report must be the run that last
stored those products, and no run needs to be repeated.
"""

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import TextIO

import yaml

from beautyads.domain.products import ProductKey
from beautyads.settings import DEFAULT_ENV_FILE, SettingError, get_setting
from beautyads.store import StoreConnectError, apply_migrations, connect, postgres_dsn
from beautyads.store.product_repository import PostgresProductStore

CANDIDATES_PATH = Path("config/product_candidates.yaml")
REPORT_PATH = Path("data/interim/products/records.json")


def cleanup(
    products: Sequence[Mapping], candidates: Sequence[Mapping], store, out: TextIO
) -> dict:
    by_index = {number: item for number, item in enumerate(candidates, 1)}
    checked = trimmed = before = after = 0
    for product in products:
        if product.get("status") != "done":
            continue
        item = by_index.get(product.get("index"))
        if item is None:
            continue
        key = ProductKey(brand=item["brand"], source_url=item["url"])
        keep = len(product.get("ingredients") or [])
        stored = store.count_ingredients(key)
        checked += 1
        before += stored
        if stored > keep:
            store.trim_ingredients(key, keep)
            trimmed += 1
            after += keep
            print(
                f"TRIMMED index={product['index']} before={stored} after={keep}",
                file=out,
            )
        else:
            after += stored
    return {
        "products_checked": checked,
        "products_trimmed": trimmed,
        "rows_before": before,
        "rows_after": after,
        "rows_deleted": before - after,
        "ok": checked > 0,
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    deps_factory: Callable[[], tuple] | None = None,
) -> int:
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        products = json.loads(args.report.read_text(encoding="utf-8"))["products"]
        env_file = DEFAULT_ENV_FILE if environ is None else None
        with ExitStack() as stack:
            if deps_factory:
                candidates, store = deps_factory()
            else:
                candidates = yaml.safe_load(
                    CANDIDATES_PATH.read_text(encoding="utf-8")
                )["candidates"]
                get_setting("POSTGRES_PASSWORD", environ=environ, env_file=env_file)
                connection = connect(postgres_dsn(environ=environ, env_file=env_file))
                stack.callback(connection.close)
                apply_migrations(connection)
                store = PostgresProductStore(connection)
            summary = cleanup(products, candidates, store, out)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, yaml.YAMLError):
        print("CLEANUP_INPUT_INVALID", file=out)
        return 2
    except (SettingError, StoreConnectError) as exc:
        print(f"PREFLIGHT_FAILED {getattr(exc, 'code', 'STORE')}", file=out)
        return 2
    print("SUMMARY " + json.dumps(summary, ensure_ascii=False), file=out)
    return 0 if summary["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
