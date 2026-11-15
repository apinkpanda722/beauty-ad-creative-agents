"""Download the MFDS ingredient list once and match ingredient names against it.

The ingredient API has no English-name search (a request with INGR_ENG_NAME returns
the whole list), so the full list (about 220 pages) is stored in PostgreSQL and every
Korean or English match is a lookup in that copy. The download resumes by page and
stops for the day on any provider stop; progress is never discarded.
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from typing import TextIO

from beautyads.domain.products import IngredientCatalogEntry
from beautyads.settings import DEFAULT_ENV_FILE, SettingError, get_setting
from beautyads.sources.mfds import MFDSClient
from beautyads.store import (
    StoreConnectError,
    apply_migrations,
    connect,
    postgres_dsn,
)
from beautyads.store.product_repository import PostgresProductStore

from .preflight import docker_running, tcp_reachable

CATALOG_PAGE_SIZE = 100
_EDGE_PUNCTUATION = " .,;:*·•'\"`-_()[]"
# A line break or semicolon means several names share one cell; it is no match key.
_MIXED_NAMES = re.compile(r"[\r\n;]")
_LATIN = re.compile(r"[A-Za-z]")


def _stop_detail(error) -> dict | None:
    detail = {
        "provider_code": getattr(error, "provider_code", None),
        "http_status": getattr(error, "http_status", None),
    }
    detail = {key: value for key, value in detail.items() if value is not None}
    return detail or None


def sync_catalog(mfds, store, now: Callable[[], datetime], out: TextIO) -> dict:
    """Fetch the next missing pages. complete is True only after the last page."""
    page_no = store.catalog_last_page() + 1
    pages = stored = skipped = 0
    stopped = detail = None
    complete = False
    while True:
        page = mfds.fetch_ingredient_page(page_no, num_of_rows=CATALOG_PAGE_SIZE)
        if page.stopped:
            stopped, detail = page.stopped, _stop_detail(page.error)
            break
        pages += 1
        total = page.total or 0
        entries = []
        for row_no, item in enumerate(page.items):
            if not item.name_ko or not item.name_ko.strip():
                skipped += 1
                continue
            entries.append(
                IngredientCatalogEntry(
                    page_no=page_no,
                    row_no=row_no,
                    name_ko=item.name_ko,
                    name_en=item.name_en,
                    cas_no=item.cas_no,
                    source_total=total,
                    fetched_at=now(),
                )
            )
        store.upsert_catalog_page(entries)
        stored += len(entries)
        if not page.items or page_no * CATALOG_PAGE_SIZE >= total:
            complete = True
            break
        page_no += 1
    summary = {
        "pages_fetched": pages,
        "stored": stored,
        "skipped_without_name": skipped,
        "complete": complete,
        "stopped": stopped,
        "stopped_detail": detail,
    }
    if stopped:
        text = f" {json.dumps(detail, ensure_ascii=False)}" if detail else ""
        print(f"STOPPED {stopped}{text}", file=out)
    return summary


def catalog_complete(entries: Sequence[IngredientCatalogEntry]) -> bool:
    """True when pages up to the recorded total were stored (a partial copy is not)."""
    if not entries:
        return False
    last = max(entry.page_no for entry in entries)
    total = max(entry.source_total for entry in entries)
    return last * CATALOG_PAGE_SIZE >= total


def _compact(name: str) -> str:
    return "".join(name.split())


def normalize_english(name: str) -> str:
    """Case, whitespace and edge punctuation only; nothing inside the name changes."""
    text = " ".join(unicodedata.normalize("NFKC", name).casefold().split())
    return text.strip(_EDGE_PUNCTUATION)


class CatalogIndex:
    """Exact Korean and English lookups with every ambiguity left unresolved."""

    def __init__(self, entries: Sequence[IngredientCatalogEntry]):
        korean: dict[str, set[str]] = defaultdict(set)
        english: dict[str, set[str]] = defaultdict(set)
        with_english = usable_english = 0
        for entry in entries:
            korean[_compact(entry.name_ko)].add(entry.name_ko)
            name = entry.name_en
            if name is None or not name.strip():
                continue
            with_english += 1
            if _MIXED_NAMES.search(name):
                continue
            key = normalize_english(name)
            if key:
                usable_english += 1
                english[key].add(entry.name_ko)
        self._korean = dict(korean)
        self._english = dict(english)
        self.stats = {
            "rows": len(entries),
            "with_english": with_english,
            "usable_english": usable_english,
            "ambiguous_english": sum(len(v) > 1 for v in english.values()),
            "ambiguous_korean": sum(len(v) > 1 for v in korean.values()),
        }

    def match(self, name: str) -> tuple[str, str | None] | None:
        """(source, standard name), ("ambiguous", None), or None for no match."""
        found = self._korean.get(_compact(name))
        if found is not None:
            if len(found) > 1:
                return ("ambiguous", None)
            return ("kor_exact", next(iter(found)))
        if not _LATIN.search(name):
            return None
        found = self._english.get(normalize_english(name))
        if found is None:
            return None
        if len(found) > 1:
            return ("ambiguous", None)
        return ("eng_name_exact", next(iter(found)))


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
                mfds, store = deps_factory()
            else:
                connection = connect(postgres_dsn(environ=environ, env_file=env_file))
                stack.callback(connection.close)
                apply_migrations(connection)
                mfds = MFDSClient(max_requests=args.max_mfds_requests)
                store = PostgresProductStore(connection)
            summary = sync_catalog(mfds, store, lambda: datetime.now(UTC), out)
            entries = store.list_catalog()
            summary["catalog"] = CatalogIndex(entries).stats
            summary["catalog_complete"] = catalog_complete(entries)
        print("SUMMARY " + json.dumps(summary, ensure_ascii=False), file=out)
        return 0 if summary["complete"] else 3
    except SettingError as exc:
        print(f"PREFLIGHT_FAILED {exc.code}:{exc.name}", file=out)
    except (StoreConnectError, ValueError, OSError):
        print("PREFLIGHT_FAILED CATALOG_IO_FAILED", file=out)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
