"""Re-match certifications for stored products using only the MFDS APIs.

Reads each stored product's name from PostgreSQL and runs the certification matching
again. No mall page, image or model is used, so it costs no Gemini calls. A product
whose lookup fails for a retryable reason keeps its stored certifications; a system
stop ends the run and leaves the remaining products untouched.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from typing import NamedTuple, TextIO

from beautyads.domain.mfds import CertStatus, FunctionalKind
from beautyads.domain.products import ProductKey
from beautyads.settings import DEFAULT_ENV_FILE, SettingError, get_setting
from beautyads.sources.mfds import MFDSClient
from beautyads.store import StoreConnectError, apply_migrations, connect, postgres_dsn
from beautyads.store.product_repository import PostgresProductStore

from .preflight import docker_running, tcp_reachable
from .products import (
    BRAND_NAMES_PATH,
    ProductsError,
    _Retry,
    _Stop,
    load_brand_korean_names,
    match_certs,
)


class _Target(NamedTuple):
    title: str
    key: ProductKey


def recheck_certs(store, mfds, brand_names: Mapping[str, str], out: TextIO) -> dict:
    products = store.list_products()
    by_kind = {kind.value: Counter() for kind in FunctionalKind}
    certified_products = checked = pending = 0
    stopped = detail = None
    retry_codes: Counter = Counter()
    for product in products:
        try:
            certs = match_certs(
                _Target(product.name_ko, product.key),
                mfds,
                brand_names.get(product.brand),
            )
        except _Retry as exc:
            pending += 1
            retry_codes[exc.code] += 1
            continue
        except _Stop as exc:
            stopped, detail = exc.code, exc.detail
            break
        store.upsert_certs(certs)
        checked += 1
        certified_products += any(c.status == CertStatus.certified for c in certs)
        for cert in certs:
            by_kind[cert.kind.value][
                "certified" if cert.status == CertStatus.certified else "unknown"
            ] += 1
    if stopped:
        text = " " + " ".join(f"{k}={v}" for k, v in detail.items()) if detail else ""
        print(f"STOPPED {stopped}{text}", file=out)
    requests = getattr(mfds, "requests_made", None)
    return {
        "products": len(products),
        "rechecked": checked,
        "certified_products": certified_products,
        "by_kind": {
            kind: {"certified": c["certified"], "unknown": c["unknown"]}
            for kind, c in by_kind.items()
        },
        "pending": pending,
        "retry_codes": dict(retry_codes),
        "stopped": stopped,
        "stopped_detail": detail,
        "mfds_requests": requests if isinstance(requests, int) else None,
        "ok": bool(products) and stopped is None,
    }


def _positive(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    if number < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    docker_check=docker_running,
    tcp_check=tcp_reachable,
    deps_factory: Callable[[], tuple] | None = None,
) -> int:
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-mfds-requests", required=True, type=_positive)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    env_file = DEFAULT_ENV_FILE if environ is None else None
    try:
        problems = [
            f"ENV_MISSING:{name}"
            for name in ("DATA_GO_KR_SERVICE_KEY", "POSTGRES_PASSWORD")
            if get_setting(name, environ=environ, env_file=env_file) is None
        ]
        if not problems and deps_factory is None:
            if not docker_check():
                problems = ["DOCKER_DOWN"]
            else:
                port = int(
                    get_setting(
                        "BEAUTYADS_POSTGRES_PORT",
                        "5433",
                        environ=environ,
                        env_file=env_file,
                    )
                )
                if not (1 <= port <= 65535 and tcp_check("127.0.0.1", port, 1.0)):
                    problems = ["POSTGRES_UNREACHABLE"]
        if problems:
            for problem in problems:
                print(f"PREFLIGHT_FAILED {problem}", file=out)
            return 2
        with ExitStack() as stack:
            if deps_factory:
                mfds, store, names = deps_factory()
            else:
                names = load_brand_korean_names(BRAND_NAMES_PATH)
                connection = connect(postgres_dsn(environ=environ, env_file=env_file))
                stack.callback(connection.close)
                apply_migrations(connection)
                mfds = MFDSClient(max_requests=args.max_mfds_requests)
                store = PostgresProductStore(connection)
            summary = recheck_certs(store, mfds, names, out)
        print("SUMMARY " + json.dumps(summary, ensure_ascii=False), file=out)
        return 0 if summary["ok"] else 3
    except SettingError as exc:
        print(f"PREFLIGHT_FAILED {exc.code}:{exc.name}", file=out)
    except (ProductsError, StoreConnectError, ValueError, OSError):
        print("PREFLIGHT_FAILED CERT_RECHECK_IO_FAILED", file=out)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
