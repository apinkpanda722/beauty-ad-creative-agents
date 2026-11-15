"""Assemble official-mall product facts and exact MFDS matches, after preflight.

Images remain in memory. The run report preserves pending product/ingredient
work for a later invocation; repeating a run uses cached standards and upserts.
Original full@v1 labels are immutable inputs to ingredient-matches@v1 jobs.
"""

import argparse
import json
import re
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from functools import partial
from math import fsum
from pathlib import Path
from typing import NamedTuple, TextIO, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from beautyads.analysis.product_detail import extract_product_detail
from beautyads.domain import JobStatus
from beautyads.domain.labels import Category
from beautyads.domain.mfds import CertStatus, FunctionalKind, functional_kinds
from beautyads.domain.products import (
    CachedIngredientStandard,
    Product,
    ProductCert,
    ProductIngredient,
    ProductKey,
    ProductRepository,
)
from beautyads.domain.protocols import AnalysisRepository, CreativeRepository
from beautyads.llm import CostCapExceeded, ErrorKind, LlmCallError, ThinkingLevel
from beautyads.obs.ledger import check_cap, read_entries
from beautyads.settings import (
    DEFAULT_ENV_FILE,
    SettingError,
    get_setting,
    load_settings,
)
from beautyads.sources.mall import _HTML as MallHTML
from beautyads.sources.mall import MallClient, MallError, download_detail_image
from beautyads.sources.mfds import MFDSClient
from beautyads.store import (
    PostgresCreativeStore,
    StoreConnectError,
    apply_migrations,
    connect,
    postgres_dsn,
)
from beautyads.store.product_repository import PostgresProductStore

from .preflight import docker_running, tcp_reachable

CANDIDATES_PATH = Path("config/product_candidates.yaml")
BRAND_POOL_PATH = Path("config/brand_product_pool.yaml")
INGREDIENT_ALIASES_PATH = Path("config/ingredient_aliases.yaml")
PRODUCT_ALIASES_PATH = Path("config/product_aliases.yaml")
REPORT_PATH = Path("data/interim/products/records.json")
ASSUMED_PIECES_PER_IMAGE = 4
ASSUMED_COST_PER_PIECE_USD = 0.0009
MATCH_KIND = "ingredient-matches@v1"
_MAX_IMAGE_BYTES = 32 * 1024 * 1024


class ProductsError(Exception):
    def __init__(self, code: str, *, extractions=(), issues=()):
        self.code = code
        self.extractions = extractions
        # Per-image error codes, kept so a failed product can be diagnosed later.
        self.issues = list(issues)
        super().__init__(code)


class _Stop(ProductsError):
    def __init__(self, code: str, *, detail: dict | None = None, **kwargs):
        super().__init__(code, **kwargs)
        # Provider diagnostics (already credential-redacted by the adapter).
        self.detail = detail


_DETAIL_MESSAGE_MAX = 200


def _mfds_detail(error) -> dict | None:
    """Bounded one-line provider diagnostics for a system stop, or None."""
    if error is None:
        return None
    message = getattr(error, "provider_message", None)
    if message is not None:
        message = " ".join(str(message).split())[:_DETAIL_MESSAGE_MAX] or None
    detail = {
        "provider_code": getattr(error, "provider_code", None),
        "http_status": getattr(error, "http_status", None),
        "provider_message": message,
    }
    detail = {key: value for key, value in detail.items() if value is not None}
    return detail or None


class _Retry(ProductsError):
    pass


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand: str = Field(min_length=1)
    title: str = Field(min_length=1)
    category: Category
    url: str
    hits_A: int = Field(default=0, ge=0)
    hits_B: int = Field(default=0, ge=0)
    index: int = Field(default=1, ge=1)

    @property
    def key(self) -> ProductKey:
        return ProductKey(brand=self.brand, source_url=self.url)


class _CreativeStore(CreativeRepository, AnalysisRepository):
    """Both existing persistence contracts, supplied by one connection."""


class ProductsDeps(NamedTuple):
    mall: MallClient
    mfds: MFDSClient
    store: ProductRepository
    creatives: _CreativeStore
    download: Callable
    extract: Callable
    now: Callable[[], datetime]


def _yaml(path: Path, code: str, *, optional: bool = False):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if optional:
            return None
        raise ProductsError(code) from None
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ProductsError(code) from None


def _nonblank(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_candidates(path: Path) -> list[Candidate]:
    doc = _yaml(path, "PRODUCT_CANDIDATES_INVALID")
    try:
        if not isinstance(doc, dict) or not isinstance(doc.get("candidates"), list):
            raise TypeError
        result = []
        seen = set()
        for index, row in enumerate(doc.get("candidates"), 1):
            item = Candidate.model_validate({**row, "index": index})
            # Validate category, name and absolute, credential-free URL offline.
            Product.model_validate(
                {
                    "brand": item.brand,
                    "name_ko": item.title,
                    "source_url": item.url,
                    "category": item.category,
                }
            )
            if item.key in seen:
                raise ValueError
            seen.add(item.key)
            result.append(item)
        if not result:
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise ProductsError("PRODUCT_CANDIDATES_INVALID") from None


def load_brand_pool(path: Path) -> dict[str, list[str]]:
    doc = _yaml(path, "BRAND_POOL_UNREADABLE")
    brands = doc.get("brands") if isinstance(doc, dict) else None
    if (
        not isinstance(brands, dict)
        or not brands
        or any(
            not _nonblank(brand)
            or not isinstance(names, list)
            or not names
            or any(not _nonblank(name) for name in names)
            for brand, names in brands.items()
        )
    ):
        raise ProductsError("BRAND_POOL_UNREADABLE")
    return brands


def _alias_rows(path: Path) -> list[dict]:
    doc = _yaml(path, "ALIAS_INVALID", optional=True)
    if doc is None:
        return []
    if not isinstance(doc, dict) or set(doc) != {"aliases"}:
        raise ProductsError("ALIAS_INVALID")
    rows = doc.get("aliases")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ProductsError("ALIAS_INVALID")
    return rows


def load_ingredient_aliases(path: Path) -> dict[str, str]:
    result = {}
    for row in _alias_rows(path):
        if set(row) != {"alias", "standard_name", "source"} or any(
            not _nonblank(value) for value in row.values()
        ):
            raise ProductsError("ALIAS_INVALID")
        name = row.get("alias")
        target = row.get("standard_name")
        if name in result:
            raise ProductsError("ALIAS_INVALID")
        result[name] = target
    return result


def load_product_aliases(path: Path) -> dict[tuple[str, str], dict]:
    result = {}
    for row in _alias_rows(path):
        if not {"brand", "name_ko"} <= set(row) or set(row) - {
            "brand",
            "name_ko",
            "extra",
            "drop",
        }:
            raise ProductsError("ALIAS_INVALID")
        if any(not _nonblank(row.get(key)) for key in ("brand", "name_ko")):
            raise ProductsError("ALIAS_INVALID")
        for key in ("extra", "drop"):
            values = row.get(key, [])
            if not isinstance(values, list) or any(not _nonblank(v) for v in values):
                raise ProductsError("ALIAS_INVALID")
        key = (row.get("brand"), row.get("name_ko"))
        if key in result:
            raise ProductsError("ALIAS_INVALID")
        result[key] = {name: row.get(name, []) for name in ("extra", "drop")}
    return result


def _mfds_system(result) -> None:
    error = result.error
    code = result.stopped
    if error and (
        error.http_status in {401, 402, 403, 429} or error.provider_code == "30"
    ):
        raise _Stop(code or "MFDS_ACCOUNT_STOPPED", detail=_mfds_detail(error))
    if code in {
        "MFDS_REQUEST_CAP",
        "MFDS_HTTP_401",
        "MFDS_HTTP_402",
        "MFDS_HTTP_403",
        "MFDS_HTTP_429",
        "MFDS_KEY_NOT_REGISTERED",
        "MFDS_API_ERROR",
        "ENV_MISSING:DATA_GO_KR_SERVICE_KEY",
    }:
        raise _Stop(code, detail=_mfds_detail(error))


class IngredientResolver:
    def __init__(self, mfds, store, aliases, now):
        self.mfds = mfds
        self.store = store
        self.aliases = aliases
        self.now = now
        self.memo: dict[str, str | None] = {}

    def match(self, names: Sequence[str]) -> list[dict]:
        rows = []
        for raw in names:
            row = {
                "raw_name": raw,
                "standard_name": None,
                "status": "pending",
                "error_code": None,
            }
            # Strip printed amount annotations only; retain the untouched raw name.
            name = re.sub(
                r"\(\s*[\d.,]+\s*(?:%|ppm|ppb|mg|g|ml)\s*\)",
                "",
                raw,
                flags=re.IGNORECASE,
            ).strip()
            name = self.aliases.get(name, name)
            try:
                if name not in self.memo:
                    cached = self.store.get_ingredient_standard(name)
                    if cached is not None and cached.name_ko == name:
                        self.memo[name] = name
                    elif not name:
                        self.memo[name] = None
                    else:
                        result = self.mfds.search_ingredients(name)
                        _mfds_system(result)
                        if result.stopped:
                            row["error_code"] = result.stopped
                            rows.append(row)
                            continue
                        # Never trust a fake or a future adapter to filter partial matches.
                        standard = next(
                            (item for item in result.items if item.name_ko == name),
                            None,
                        )
                        self.memo[name] = standard.name_ko if standard else None
                        if standard:
                            self.store.upsert_ingredient_standard(
                                CachedIngredientStandard(
                                    **standard.model_dump(), queried_at=self.now()
                                )
                            )
                row["standard_name"] = self.memo[name]
                row["status"] = "resolved" if self.memo[name] else "unresolved"
            except _Stop:
                raise
            except Exception:  # noqa: BLE001 -- one ingredient cannot discard later facts
                row["error_code"] = "INGREDIENT_LOOKUP_FAILED"
            rows.append(row)
        return rows


def match_certs(item: Candidate, mfds) -> list[ProductCert]:
    matched = []
    query = "".join(item.title.split())
    for search in (mfds.search_reports, mfds.search_screenings):
        result = search(query)
        _mfds_system(result)
        if result.stopped:
            raise _Retry(result.stopped)
        matched.extend(
            row
            for row in result.items
            if row.cancelled is not True
            and row.cancelled_raw != "Y"
            and "".join((row.item_name or "").split()) == query
        )
    certs = []
    for kind in FunctionalKind:
        evidence = next(
            (
                row
                for row in matched
                if functional_kinds(row)[kind] == CertStatus.certified
            ),
            None,
        )
        certs.append(
            ProductCert(
                product=item.key,
                kind=kind,
                status=CertStatus.certified if evidence else CertStatus.unknown,
                evidence_item_name=evidence.item_name if evidence else None,
                evidence_api=evidence.source if evidence else "report",
            )
        )
    return certs


def _retry_mall(call, *args):
    for attempt in range(3):
        try:
            return call(*args)
        except MallError as exc:
            # Retry only 503, connection failures and timeouts, never arbitrary 5xx.
            if (
                attempt == 2
                or not exc.retryable
                or exc.code not in {"MALL_HTTP_503", "MALL_REQUEST_FAILED"}
            ):
                raise
            time.sleep(1)


def _product_facts(deps, item, report):
    page = _retry_mall(deps.mall.fetch_product, item.brand, item.url)
    if page.ingredients_text and page.ingredients_text.strip():
        # Commas within parenthesized amounts are not ingredient delimiters.
        names = []
        start = depth = 0
        for index, char in enumerate(page.ingredients_text):
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif char in ",，;\n" and depth == 0:
                raw = page.ingredients_text[start:index]
                if raw.strip():
                    names.append(raw)
                start = index + 1
        raw = page.ingredients_text[start:]
        if raw.strip():
            names.append(raw)
        return page, names, {}, [], []
    extractions, issues = [], []
    fields = {}
    names = []
    held = False
    successful = False
    for url in reversed(page.detail_image_urls):
        try:
            data = _retry_mall(deps.download, item.brand, url)
            try:
                outcome = deps.extract(item.key, [data])
            finally:
                del data
            extractions.extend(outcome.extractions)
            report["extractions"] = [row.model_dump(mode="json") for row in extractions]
            issues.extend(issue.error_code for issue in outcome.issues)
            held |= outcome.status == JobStatus.held
            if outcome.result is not None and outcome.status == JobStatus.done:
                successful = True
                facts = outcome.result.model_dump(mode="json")
                for name, value in facts.items():
                    if name == "ingredients":
                        continue
                    if isinstance(value, list):
                        fields.setdefault(name, [])
                        fields[name].extend(v for v in value if v not in fields[name])
                    elif fields.get(name) is None:
                        fields[name] = value
                names = [
                    i.raw_name + (i.amount_text or "")
                    for i in outcome.result.ingredients
                ]
                if names:
                    break
        except MallError as exc:
            if exc.code in {
                "MALL_HTTP_401",
                "MALL_HTTP_402",
                "MALL_HTTP_403",
                "MALL_HTTP_429",
            }:
                raise _Stop(exc.code) from None
            issues.append(exc.code)
    if held or not successful:
        raise ProductsError(
            "PRODUCT_DETAIL_HELD" if held else "PRODUCT_DETAIL_FAILED",
            extractions=extractions,
            issues=issues,
        )
    return page, names, fields, extractions, issues


def ingredient_frequency(products: Sequence[Sequence[dict]], top_n: int) -> list[dict]:
    counts = Counter()
    for rows in products:
        counts.update(
            {
                row.get("standard_name")
                for row in rows
                if row.get("status") == "resolved" and row.get("standard_name")
            }
        )
    return [
        {"standard_name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[
            :top_n
        ]
    ]


def _ad_matches(deps, resolver):
    creatives = deps.creatives.list_creatives()
    by_key = {creative.key: creative for creative in creatives}
    jobs = deps.creatives.get_job_results("full@v1", list(by_key))
    deps.creatives.enqueue_analysis(
        MATCH_KIND, [by_key[job.key] for job in jobs if job.status == JobStatus.done]
    )
    counts = Counter()
    errors = Counter()
    for job in jobs:
        if job.status != JobStatus.done:
            continue
        labels = job.labels or {}
        names = labels.get("ingredients", [])
        if not isinstance(names, list) or any(
            not isinstance(name, str) or not name.strip() for name in names
        ):
            errors["AD_INGREDIENTS_INVALID"] += 1
            continue
        try:
            rows = resolver.match(names)
            pending = any(row["status"] == "pending" for row in rows)
            code = next((row["error_code"] for row in rows if row["error_code"]), None)
            deps.creatives.record_analysis(
                MATCH_KIND,
                job.key,
                status=JobStatus.pending if pending else JobStatus.done,
                model=None,
                thinking_level=None,
                prompt_version=None,
                raw_output=None,
                labels={"ingredients": rows},
                error_code=code,
            )
            counts.update(row["status"] for row in rows)
            errors.update(row["error_code"] for row in rows if row["error_code"])
        except _Stop:
            raise
        except Exception:  # noqa: BLE001 -- isolate one creative's persistence failure
            errors["AD_INGREDIENTS_FAILED"] += 1
    return dict(counts), dict(errors)


def _llm_stop(exc):
    status = getattr(exc.__context__, "status_code", None)
    if exc.kind in {
        ErrorKind.DAILY_LIMIT,
        ErrorKind.RATE_LIMIT,
        ErrorKind.CREDITS_DEPLETED,
    } or status in {401, 402, 403}:
        return (
            f"LLM_{exc.kind.value}" if status not in {401, 403} else "LLM_AUTH_FAILED"
        )
    return None


def run_products(
    deps: ProductsDeps,
    items: Sequence[Candidate],
    *,
    brand_pool,
    ingredient_aliases,
    product_aliases,
    report_path: Path,
    out: TextIO,
    ledger_path: Path | None = None,
    ledger_start: int = 0,
    top_n: int = 50,
) -> dict:
    reports = [
        {"index": item.index, "status": "pending", "error_code": None} for item in items
    ]
    resolver = IngredientResolver(deps.mfds, deps.store, ingredient_aliases, deps.now)
    ingredients = []
    cert_products = Counter()
    cert_by_kind = {kind.value: Counter() for kind in FunctionalKind}
    stopped = None
    stopped_detail = None
    alias_count = 0
    for item, report in zip(items, reports, strict=True):
        try:
            definition = deps.mall.config.malls.get(item.brand)
            if definition and definition.excluded:
                report["status"] = "skipped"
                report["error_code"] = "MALL_EXCLUDED"
                continue
            if item.brand not in brand_pool:
                raise ProductsError("BRAND_POOL_UNREADABLE")
            page, raw, fields, extractions, issues = _product_facts(deps, item, report)
            report["extractions"] = [row.model_dump(mode="json") for row in extractions]
            matches = resolver.match(raw)
            report["ingredients"] = matches
            if any(row["status"] == "pending" for row in matches):
                report["error_code"] = "INGREDIENT_RETRY_REQUIRED"
                continue
            certs = match_certs(item, deps.mfds)
            product = Product.model_validate(
                dict(
                    brand=item.brand,
                    name_ko=item.title,
                    category=item.category,
                    source_url=item.url,
                    list_price=page.list_price,
                    sale_price=page.sale_price,
                    price_basis=page.price_basis,
                    price_collected_at=deps.now(),
                    **fields,
                ),
                context={"brand_products": brand_pool[item.brand]},
            )
            overrides = product_aliases.get((item.brand, item.title), {})
            aliases = list(
                dict.fromkeys([*product.aliases, *overrides.get("extra", [])])
            )
            aliases = [
                a
                for a in aliases
                if a not in overrides.get("drop", [])
                and "".join(a.split()).casefold()
                != "".join(item.brand.split()).casefold()
            ]
            product = product.model_copy(update={"aliases": aliases})
            deps.store.upsert_product(product)
            deps.store.upsert_ingredients(
                [
                    ProductIngredient(
                        product=item.key,
                        order=index,
                        raw_name=row["raw_name"],
                        standard_name=row["standard_name"],
                        status=row["status"],
                    )
                    for index, row in enumerate(matches, 1)
                ]
            )
            deps.store.upsert_certs(certs)
            for extraction in extractions:
                deps.store.add_extraction(extraction)
            ingredients.append(matches)
            cert_products[
                "certified"
                if any(cert.status == CertStatus.certified for cert in certs)
                else "unknown"
            ] += 1
            for cert in certs:
                cert_by_kind[cert.kind.value][cert.status.value] += 1
            alias_count += len(product.aliases)
            report.update(status="done", issues=issues)
        except CostCapExceeded:
            stopped = "COST_CAP:gemini"
        except _Stop as exc:
            stopped = exc.code
            stopped_detail = exc.detail
        except _Retry as exc:
            report["error_code"] = exc.code
        except LlmCallError as exc:
            stopped = _llm_stop(exc)
            if not stopped:
                report.update(status="failed", error_code="PRODUCT_MODEL_FAILED")
        except MallError as exc:
            if exc.code in {
                "MALL_HTTP_401",
                "MALL_HTTP_402",
                "MALL_HTTP_403",
                "MALL_HTTP_429",
            }:
                stopped = exc.code
            else:
                report.update(
                    status="skipped" if exc.code == "MALL_EXCLUDED" else "failed",
                    error_code=exc.code,
                )
        except ProductsError as exc:
            report.update(
                status="held" if exc.code == "PRODUCT_DETAIL_HELD" else "failed",
                error_code=exc.code,
            )
            report["extractions"] = [
                row.model_dump(mode="json") for row in exc.extractions
            ]
            report["issues"] = list(exc.issues)
        except Exception:  # noqa: BLE001 -- suppress unsafe diagnostics and continue
            report.update(status="failed", error_code="PRODUCT_FAILED")
        if stopped:
            report["error_code"] = stopped
            break
    ads, ad_errors = {}, {}
    if not stopped:
        try:
            ads, ad_errors = _ad_matches(deps, resolver)
        except _Stop as exc:
            stopped = exc.code
            stopped_detail = exc.detail
        except Exception:  # noqa: BLE001 -- source/persistence diagnostics are private
            ad_errors = {"AD_READ_FAILED": 1}
    entries = read_entries(ledger_path).entries[ledger_start:] if ledger_path else []
    costs = {"product-detail": {"calls": 0, "cost_usd": 0.0}}
    for purpose in {
        entry.purpose for entry in entries if entry.purpose == "product-detail"
    }:
        rows = [
            entry
            for entry in entries
            if entry.purpose == purpose and entry.provider == "gemini"
        ]
        costs[purpose] = {
            "calls": len(rows),
            "cost_usd": fsum(entry.cost_usd for entry in rows),
        }
    all_rows = [row for report in reports for row in report.get("ingredients", [])]
    resolved = sum(row["status"] == "resolved" for row in all_rows)
    summary = {
        "event": "summary",
        "product_count": len(items),
        "by_status": dict(Counter(row["status"] for row in reports)),
        "ingredient_count": len(all_rows),
        "resolved_ratio": resolved / len(all_rows) if all_rows else None,
        "unresolved": sum(row["status"] == "unresolved" for row in all_rows),
        "ingredient_pending": sum(row["status"] == "pending" for row in all_rows),
        "certification": {
            "certified": cert_products["certified"],
            "unknown": cert_products["unknown"],
            "coverage": cert_products["certified"] / len(items) if items else None,
            "by_kind": {
                kind: {status.value: counts[status.value] for status in CertStatus}
                for kind, counts in cert_by_kind.items()
            },
        },
        "ad_ingredients": ads,
        "ad_errors": ad_errors,
        "cost_by_purpose": costs,
        "alias_count": {
            "ingredient": len(ingredient_aliases),
            "product": alias_count,
            "extra": sum(len(row.get("extra", [])) for row in product_aliases.values()),
            "drop": sum(len(row.get("drop", [])) for row in product_aliases.values()),
        },
        "error_codes": dict(
            Counter(row["error_code"] for row in reports if row["error_code"])
        ),
        "stopped": stopped,
        "stopped_detail": stopped_detail,
    }
    report = {**summary, "products": reports}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    temporary.replace(report_path)
    if stopped:
        detail_text = "".join(
            f" {key}={stopped_detail[key]}"
            for key in ("provider_code", "http_status", "provider_message")
            if stopped_detail and key in stopped_detail
        )
        print(f"STOPPED {stopped}{detail_text}", file=out)
    print(json.dumps(summary, ensure_ascii=False), file=out)
    print(
        json.dumps(
            {
                "event": "ingredient_frequency",
                "rows": ingredient_frequency(ingredients, top_n),
            },
            ensure_ascii=False,
        ),
        file=out,
    )
    return report


def _preflight(*, environ, env_file, settings, docker_check, tcp_check, database=True):
    problems = [
        f"ENV_MISSING:{name}"
        for name in ("DATA_GO_KR_SERVICE_KEY", "GEMINI_API_KEY", "POSTGRES_PASSWORD")
        if get_setting(name, environ=environ, env_file=env_file) is None
    ]
    if problems:
        return problems
    try:
        check_cap(settings.ledger_path, "gemini", settings.provider_caps_usd)
    except CostCapExceeded:
        return ["COST_CAP:gemini"]
    except (OSError, UnicodeError):
        return ["LEDGER_UNREADABLE"]
    if not database:
        return []
    if not docker_check():
        return ["DOCKER_DOWN"]
    try:
        port = int(
            get_setting(
                "BEAUTYADS_POSTGRES_PORT", "5433", environ=environ, env_file=env_file
            )
        )
        reachable = 1 <= port <= 65535 and tcp_check("127.0.0.1", port, 1.0)
    except (TypeError, ValueError, OSError):
        reachable = False
    return [] if reachable else ["POSTGRES_UNREACHABLE"]


def _live_deps(*, environ, env_file, stack, maximum, thinking, settings):
    connection = connect(postgres_dsn(environ=environ, env_file=env_file))
    stack.callback(connection.close)
    apply_migrations(connection)
    mall = MallClient()
    return ProductsDeps(
        mall,
        MFDSClient(max_requests=maximum),
        PostgresProductStore(connection),
        PostgresCreativeStore(connection),
        lambda brand, url: download_detail_image(
            url, brand=brand, client=mall, max_bytes=_MAX_IMAGE_BYTES
        ),
        partial(
            extract_product_detail,
            thinking_level=thinking,
            ledger_path=settings.ledger_path,
            caps=settings.provider_caps_usd,
        ),
        lambda: datetime.now(UTC),
    )


def _positive(value):
    try:
        number = int(value)
        if number > 0:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("expected a positive integer")


class _ScanMallClient(MallClient):
    """Reuse the adapter's HTTP/robots/parser boundary to count all HTML images.

    Its normal product result intentionally omits image addresses when text is
    available. Scan needs that count too, without downloading any image.
    """

    def __init__(self, client):
        super().__init__(
            config=client.config,
            get=client._get,
            clock=client._clock,
            sleep=client._sleep,
        )
        self.image_count = 0

    def _request(self, url, *, max_bytes, timeout_s):
        response = super()._request(url, max_bytes=max_bytes, timeout_s=timeout_s)
        if response.status == 200 and not url.endswith("/robots.txt"):
            parser = MallHTML()
            parser.feed(response.body.decode("utf-8-sig", errors="replace"))
            self.image_count = sum(
                1
                for detail in parser.root.walk()
                if detail.attrs.get("id") == "prdDetail"
                for node in detail.walk()
                if node.tag == "img" and (node.attrs.get("ec-data-src") or "").strip()
            )
        return response


def _scan(items, mall, out):
    mall = _ScanMallClient(mall)
    errors = False
    for item in items:
        try:
            page = _retry_mall(mall.fetch_product, item.brand, item.url)
            count = mall.image_count
            print(
                json.dumps(
                    {
                        "event": "scan",
                        "index": item.index,
                        "list_price": str(page.list_price)
                        if page.list_price is not None
                        else None,
                        "sale_price": str(page.sale_price)
                        if page.sale_price is not None
                        else None,
                        "price_basis": page.price_basis,
                        "has_ingredients_text": bool(page.ingredients_text),
                        "detail_image_count": count,
                        "assumed_pieces_per_image": ASSUMED_PIECES_PER_IMAGE,
                        "assumed_cost_per_piece_usd": ASSUMED_COST_PER_PIECE_USD,
                        "estimated_upper_cost_usd": count
                        * ASSUMED_PIECES_PER_IMAGE
                        * ASSUMED_COST_PER_PIECE_USD,
                        "assumptions": "두 상수는 각각 가정(미실측); 관측 1건 기반 이미지당 조각 수와 합성 이미지 비용. 전성분을 찾으면 멈추므로 상한 추정이며 판정 기준이 아님",
                    },
                    ensure_ascii=False,
                ),
                file=out,
            )
        except MallError as exc:
            print(
                json.dumps(
                    {"event": "scan", "index": item.index, "error_code": exc.code}
                ),
                file=out,
            )
            errors |= exc.code != "MALL_EXCLUDED"
    return 3 if errors else 0


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    docker_check=docker_running,
    tcp_check=tcp_reachable,
    deps_factory: Callable[[], ProductsDeps] | None = None,
    mall_factory: Callable[[], MallClient] | None = None,
) -> int:
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--scan", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--products")
    parser.add_argument("--max-mfds-requests", required=True, type=_positive)
    parser.add_argument(
        "--thinking-level", choices=get_args(ThinkingLevel), default="minimal"
    )
    parser.add_argument("--top-n", type=_positive, default=50)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        items = load_candidates(CANDIDATES_PATH)
        pool = load_brand_pool(BRAND_POOL_PATH)
        ingredient_aliases = load_ingredient_aliases(INGREDIENT_ALIASES_PATH)
        product_aliases = load_product_aliases(PRODUCT_ALIASES_PATH)
        if args.products is not None:
            wanted = {part.strip() for part in args.products.split(",")}
            selected = [
                item
                for item in items
                if wanted.intersection(
                    {
                        str(item.index),
                        item.title,
                        item.url,
                        f"{item.brand}:{item.title}",
                    }
                )
            ]
            matched = {
                identifier
                for item in selected
                for identifier in (
                    str(item.index),
                    item.title,
                    item.url,
                    f"{item.brand}:{item.title}",
                )
            }
            if not wanted or not wanted <= matched:
                raise ProductsError("PRODUCT_SELECTION_INVALID")
            items = selected
        if any(item.brand not in pool for item in items):
            raise ProductsError("BRAND_POOL_UNREADABLE")
        if args.dry_run:
            print(
                "ESTIMATE "
                + json.dumps(
                    {
                        "products": len(items),
                        "base_calls_min": len(items),
                        "base_calls_max": len(items) * 3,
                        "call_kinds": {
                            "mall_product": [0, len(items)],
                            "mfds_report_screening": [0, len(items) * 2],
                            "mfds_all_request_cap": args.max_mfds_requests,
                            "model": [0, None],
                            "image_download": [0, None],
                        },
                        "assumptions": "후보 수 × 호출 종류(기본 페이지 1회); robots·쪽 넘김·성분 수·이미지 조각·재요청은 별도. 호출당 시간·비용은 가정(미실측); 이미지·모델 상한은 scan 전 미계산",
                    },
                    ensure_ascii=False,
                ),
                file=out,
            )
            return 0
        env_file = DEFAULT_ENV_FILE if environ is None else None
        settings = load_settings(environ=environ, env_file=env_file)
        problems = _preflight(
            environ=environ,
            env_file=env_file,
            settings=settings,
            docker_check=docker_check,
            tcp_check=tcp_check,
            database=not args.scan,
        )
        if problems:
            for problem in problems:
                print(f"PREFLIGHT_FAILED {problem}", file=out)
            return 2
        if args.scan:
            return _scan(items, mall_factory() if mall_factory else MallClient(), out)
        start = len(read_entries(settings.ledger_path).entries)
        with ExitStack() as stack:
            deps = (
                deps_factory()
                if deps_factory
                else _live_deps(
                    environ=environ,
                    env_file=env_file,
                    stack=stack,
                    maximum=args.max_mfds_requests,
                    thinking=args.thinking_level,
                    settings=settings,
                )
            )
            report = run_products(
                deps,
                items,
                brand_pool=pool,
                ingredient_aliases=ingredient_aliases,
                product_aliases=product_aliases,
                report_path=REPORT_PATH,
                out=out,
                ledger_path=settings.ledger_path,
                ledger_start=start,
                top_n=args.top_n,
            )
        return (
            3
            if report["stopped"]
            or report["ad_errors"]
            or any(
                row["status"] in {"failed", "held", "pending"}
                for row in report["products"]
            )
            else 0
        )
    except SettingError as exc:
        print(f"PREFLIGHT_FAILED {exc.code}:{exc.name}", file=out)
    except (ProductsError, StoreConnectError, MallError) as exc:
        print(f"PREFLIGHT_FAILED {exc.code}", file=out)
    except (OSError, UnicodeError, ValidationError):
        print("PREFLIGHT_FAILED PRODUCT_IO_FAILED", file=out)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
