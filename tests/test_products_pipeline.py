"""Offline product assembly from recorded contracts and synthetic domain facts."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from beautyads.domain import JobStatus
from beautyads.domain.mfds import FunctionalReport
from beautyads.domain.products import IngredientCatalogEntry, Product
from beautyads.pipeline import products as p
from beautyads.sources.mall import MallClient, MallHttpResponse, load_mall_config
from beautyads.sources.mfds import MFDSError, MFDSResult

FIXTURES = Path(__file__).parent / "fixtures/contracts"
NOW = datetime(2026, 11, 15, tzinfo=UTC)


def recorded(name):
    return json.loads((FIXTURES / name).read_text())["response"]["body"]["items"]


class Store:
    def __init__(self):
        self.products = []
        self.ingredients = []
        self.certs = []
        self.extractions = []
        self.catalog = []
        self.replaced = []
        self.lookups = {}

    def upsert_product(self, product):
        self.products.append(product)

    def upsert_ingredients(self, rows):
        self.ingredients.extend(rows)

    def replace_ingredients(self, key, rows):
        self.replaced.append((key, len(rows)))
        self.ingredients = [r for r in self.ingredients if r.product != key]
        self.ingredients.extend(rows)

    def upsert_certs(self, rows):
        self.certs.extend(rows)

    def add_extraction(self, row):
        self.extractions.append(row)

    def list_catalog(self):
        return list(self.catalog)

    def get_ingredient_lookup(self, query_key, kind):
        return self.lookups.get((query_key, kind))

    def upsert_ingredient_lookup(self, lookup):
        self.lookups[(lookup.query_key, lookup.kind)] = lookup


def candidate(title="합성 세럼", brand="cosrx", index=1):
    return p.Candidate(
        brand=brand,
        title=title,
        category="serum_ampoule",
        url=f"https://www.cosrx.co.kr/product/{index}/",
        index=index,
    )


def mall(name="image_only", *, extra=None):
    calls = []
    body = (FIXTURES / f"mall_cafe24_{name}.html").read_bytes()
    if extra:
        body = extra(body)

    def get(url, headers, timeout, maximum):
        calls.append(url)
        if url.endswith("robots.txt"):
            return MallHttpResponse(
                200, (FIXTURES / "mall_robots_mixsoon.txt").read_bytes()
            )
        return MallHttpResponse(200, body)

    client = MallClient(config=load_mall_config(), get=get, sleep=lambda _: None)
    return client, calls


def deps(name="text_div"):
    client, calls = mall(name)
    rows = recorded("mfds_ingredient_query.json")
    mfds = SimpleNamespace(
        search_reports=Mock(return_value=MFDSResult([])),
        search_screenings=Mock(return_value=MFDSResult([])),
    )
    creatives = SimpleNamespace(
        list_creatives=Mock(return_value=[]),
        get_job_results=Mock(return_value=[]),
        enqueue_analysis=Mock(),
        record_analysis=Mock(),
    )
    store = Store()
    store.catalog = [
        IngredientCatalogEntry(
            page_no=1,
            row_no=index,
            name_ko=r.get("INGR_KOR_NAME"),
            name_en=r.get("INGR_ENG_NAME"),
            cas_no=r.get("CAS_NO"),
            source_total=len(rows),
            fetched_at=NOW,
        )
        for index, r in enumerate(rows)
    ]
    return p.ProductsDeps(
        client,
        mfds,
        store,
        creatives,
        Mock(return_value=b"synthetic image bytes"),
        Mock(),
        lambda: NOW,
    ), calls


def run(tmp_path, dep, items=None, **kwargs):
    out = StringIO()
    report = p.run_products(
        dep,
        items or [candidate()],
        brand_pool={"cosrx": ["합성 세럼"], "anua": ["다른 제품"]},
        ingredient_aliases={},
        product_aliases={},
        brand_korean_names=kwargs.pop(
            "brand_korean_names", {"cosrx": "합성", "anua": "합성"}
        ),
        out=out,
        report_path=tmp_path / "state.json",
        **kwargs,
    )
    return report, out.getvalue()


def test_exact_matching_alias_cache_and_no_discard(tmp_path):
    dep, _ = deps()
    resolver = p.IngredientResolver(dep.store, {"합성 통용명": "병풀추출물"}, dep.now)
    rows = resolver.match(["병풀추출물", "병풀", "합성 통용명", "미등재", "병풀추출물"])
    assert [(r["raw_name"], r["standard_name"], r["status"]) for r in rows] == [
        ("병풀추출물", "병풀추출물", "resolved"),
        ("병풀", None, "unresolved"),
        ("합성 통용명", "병풀추출물", "resolved"),
        ("미등재", None, "unresolved"),
        ("병풀추출물", "병풀추출물", "resolved"),
    ]
    assert len(rows) == 5
    assert [r["matched_by"] for r in rows] == [
        "kor_exact",
        None,
        "kor_exact",
        None,
        "kor_exact",
    ]
    # Three distinct names reach the catalog; the alias and the repeat hit memory.
    assert dict(resolver.stats) == {"memo_hits": 2, "db_hits": 0, "catalog_lookups": 3}


def test_incomplete_catalog_is_a_system_stop_never_unresolved(tmp_path):
    dep, _ = deps()
    dep.store.catalog = [
        e.model_copy(update={"source_total": 500}) for e in dep.store.catalog
    ]
    report, output = run(tmp_path, dep, [candidate(index=1), candidate(index=2)])
    assert report["stopped"] == "INGREDIENT_CATALOG_INCOMPLETE"
    assert [r["status"] for r in report["products"]] == ["pending", "pending"]
    assert not dep.store.products and not dep.store.ingredients
    assert "STOPPED INGREDIENT_CATALOG_INCOMPLETE" in output


def test_empty_catalog_is_a_system_stop_never_unresolved(tmp_path):
    dep, _ = deps()
    dep.store.catalog = []
    report, _ = run(tmp_path, dep)
    assert report["stopped"] == "INGREDIENT_CATALOG_INCOMPLETE"
    assert report["products"][0]["status"] == "pending"


def test_english_ingredient_matches_only_exactly_and_records_the_source():
    dep, _ = deps()
    resolver = p.IngredientResolver(dep.store, {}, dep.now)
    rows = resolver.match(
        [
            "Centella Asiatica Extract",
            " centella  asiatica EXTRACT.",
            "Centella Asiatica",
        ]
    )
    assert [(r["standard_name"], r["matched_by"], r["status"]) for r in rows] == [
        ("병풀추출물", "eng_name_exact", "resolved"),
        ("병풀추출물", "eng_name_exact", "resolved"),
        (None, None, "unresolved"),
    ]
    assert dep.store.lookups[("Centella Asiatica Extract", "eng_exact")].standard_name


def test_ambiguous_english_name_stays_unresolved_and_is_counted():
    dep, _ = deps()
    first = dep.store.catalog[0]
    dep.store.catalog.append(
        first.model_copy(update={"row_no": 99, "name_ko": "다른표준명"})
    )
    resolver = p.IngredientResolver(dep.store, {}, dep.now)
    rows = resolver.match([first.name_en])
    assert rows[0]["status"] == "unresolved" and rows[0]["matched_by"] is None
    assert resolver.ambiguous == {first.name_en}
    assert not dep.store.lookups


def test_alias_loaders_empty_missing_and_source_required(tmp_path):
    path = tmp_path / "aliases.yaml"
    assert p.load_ingredient_aliases(path) == {}
    assert p.load_product_aliases(path) == {}
    path.write_text("# empty\n")
    assert p.load_ingredient_aliases(path) == {}
    path.write_text(
        yaml.safe_dump({"aliases": [{"alias": "합성", "standard_name": "병풀추출물"}]})
    )
    with pytest.raises(p.ProductsError, match="ALIAS_INVALID"):
        p.load_ingredient_aliases(path)
    path.write_text(
        yaml.safe_dump(
            {
                "aliases": [
                    {
                        "alias": "합성",
                        "standard_name": "병풀추출물",
                        "source": "synthetic-source",
                    }
                ]
            }
        )
    )
    assert p.load_ingredient_aliases(path) == {"합성": "병풀추출물"}


@pytest.mark.parametrize(
    "content",
    ["brands: []", "brands: {cosrx: []}", "[broken", "brands: {cosrx: [null]}"],
)
def test_brand_pool_fail_closed(tmp_path, content):
    path = tmp_path / "pool.yaml"
    path.write_text(content)
    with pytest.raises(p.ProductsError, match="BRAND_POOL_UNREADABLE"):
        p.load_brand_pool(path)


def test_pool_missing(tmp_path):
    with pytest.raises(p.ProductsError, match="BRAND_POOL_UNREADABLE"):
        p.load_brand_pool(tmp_path / "missing")


def test_text_bypasses_model_and_preserves_all_ingredients(tmp_path):
    dep, _ = deps()
    report, output = run(tmp_path, dep)
    dep.extract.assert_not_called()
    dep.download.assert_not_called()
    assert report["products"][0]["status"] == "done"
    assert report["cost_by_purpose"]["product-detail"] == {"calls": 0, "cost_usd": 0.0}
    assert dep.store.products and dep.store.ingredients
    assert "summary" in output and "ingredient_frequency" in output
    assert all(i.raw_name for i in dep.store.ingredients)


def test_reverse_download_stop_and_raw_extractions(tmp_path):
    from beautyads.analysis.product_detail import ProductDetailOutcome
    from beautyads.domain.products import ProductDetailResult, ProductExtraction

    dep, _ = deps("image_only")
    facts = {
        "ingredients": [{"raw_name": "병풀추출물", "amount_text": None}],
        "volume": None,
        "volume_unit": None,
        "form": None,
        "skin_types": [],
        "efficacy_texts": [],
        "functional_texts": [],
    }
    dep.extract.return_value = ProductDetailOutcome(
        status=JobStatus.done,
        result=ProductDetailResult.model_validate(facts),
        extractions=[
            ProductExtraction(
                product=candidate().key, prompt_version="synthetic", raw_output="{}"
            )
        ],
    )
    urls = dep.mall.fetch_product("cosrx", candidate().url).detail_image_urls
    report, _ = run(tmp_path, dep)
    assert report["products"][0]["status"] == "done"
    dep.download.assert_called_once_with("cosrx", urls[-1])
    assert dep.store.extractions[0].raw_output == "{}"


def test_excluded_mall_has_no_requests(tmp_path):
    dep, calls = deps()
    report, _ = run(tmp_path, dep, [candidate(brand="torriden")])
    assert not calls
    assert report["products"][0]["status"] == "skipped"
    dep.mfds.search_reports.assert_not_called()


def test_product_failure_does_not_block_next(tmp_path):
    dep, _ = deps()
    original = dep.mall.fetch_product
    dep.mall.fetch_product = Mock(
        side_effect=[
            RuntimeError("sensitive sentinel"),
            original("cosrx", candidate().url),
        ]
    )
    report, output = run(tmp_path, dep, [candidate(index=1), candidate(index=2)])
    assert [r["status"] for r in report["products"]] == ["failed", "done"]
    assert "sensitive sentinel" not in output


def test_system_error_leaves_current_and_remaining_pending(tmp_path):
    dep, _ = deps()
    dep.mfds.search_reports.return_value = MFDSResult(
        [], "MFDS_HTTP_402", MFDSError("MFDS_HTTP_402", http_status=402)
    )
    report, _ = run(tmp_path, dep, [candidate(index=1), candidate(index=2)])
    assert report["stopped"] == "MFDS_HTTP_402"
    assert [r["status"] for r in report["products"]] == ["pending", "pending"]
    assert not dep.store.products
    assert (
        json.loads((tmp_path / "state.json").read_text())["stopped"] == "MFDS_HTTP_402"
    )


def test_ad_ingredients_use_same_dictionary_keep_full_unchanged(tmp_path):
    from beautyads.domain import CreativeKey

    dep, _ = deps()
    original = {"ingredients": ["병풀추출물", "병풀", "미등재"]}
    job = SimpleNamespace(
        key=CreativeKey(source="youtube", source_id="synthetic"),
        status=JobStatus.done,
        labels=deepcopy(original),
    )
    dep.creatives.list_creatives.return_value = [SimpleNamespace(key=job.key)]
    dep.creatives.get_job_results.return_value = [job]
    run(tmp_path, dep)
    call = dep.creatives.record_analysis.call_args
    assert call.args[0] == "ingredient-matches@v1"
    assert [r["status"] for r in call.kwargs["labels"]["ingredients"]] == [
        "resolved",
        "unresolved",
        "unresolved",
    ]
    assert job.labels == original


def test_frequency_hand_count_unique_per_product():
    rows = [
        [{"standard_name": "합성A", "status": "resolved"}] * 2
        + [{"standard_name": "합성B", "status": "resolved"}],
        [
            {"standard_name": "합성A", "status": "resolved"},
            {"standard_name": None, "status": "unresolved"},
        ],
    ]
    assert p.ingredient_frequency(rows, 50) == [
        {"standard_name": "합성A", "count": 2},
        {"standard_name": "합성B", "count": 1},
    ]


@pytest.fixture
def cli(tmp_path, monkeypatch):
    candidates = tmp_path / "candidates.yaml"
    candidates.write_text(
        yaml.safe_dump(
            {
                "candidates": [
                    {
                        "brand": "cosrx",
                        "category": "serum_ampoule",
                        "title": "합성 세럼",
                        "url": candidate().url,
                    }
                ]
            }
        )
    )
    pool = tmp_path / "pool.yaml"
    pool.write_text(yaml.safe_dump({"brands": {"cosrx": ["합성 세럼"]}}))
    monkeypatch.setattr(p, "CANDIDATES_PATH", candidates)
    monkeypatch.setattr(p, "BRAND_POOL_PATH", pool)
    monkeypatch.setattr(p, "INGREDIENT_ALIASES_PATH", tmp_path / "ingredients.yaml")
    monkeypatch.setattr(p, "PRODUCT_ALIASES_PATH", tmp_path / "products.yaml")
    monkeypatch.setattr(p, "REPORT_PATH", tmp_path / "report.json")
    return {
        "DATA_GO_KR_SERVICE_KEY": "watch-secret-mfds",
        "GEMINI_API_KEY": "watch-secret-gemini",
        "POSTGRES_PASSWORD": "watch-secret-db",
        "BEAUTYADS_LEDGER_PATH": str(tmp_path / "costs.jsonl"),
    }


def test_dry_run_no_calls_and_single_estimate(cli):
    out = StringIO()
    never = Mock(side_effect=AssertionError("must not be called"))
    assert (
        p.main(
            ["--dry-run", "--max-mfds-requests", "7"],
            environ={},
            out=out,
            docker_check=never,
            tcp_check=never,
            deps_factory=never,
            mall_factory=never,
        )
        == 0
    )
    assert out.getvalue().startswith("ESTIMATE ")
    assert len(out.getvalue().splitlines()) == 1
    assert "가정(미실측)" in out.getvalue()


def test_required_mfds_maximum(cli):
    never = Mock(side_effect=AssertionError("must not be called"))
    assert p.main([], environ=cli, deps_factory=never, mall_factory=never) == 2
    never.assert_not_called()


@pytest.mark.parametrize(
    "missing", ["DATA_GO_KR_SERVICE_KEY", "GEMINI_API_KEY", "POSTGRES_PASSWORD"]
)
def test_preflight_missing_stops_before_probes_or_connections(cli, missing):
    cli[missing] = "   "
    out = StringIO()
    never = Mock(side_effect=AssertionError("must not be called"))
    assert (
        p.main(
            ["--max-mfds-requests", "7"],
            environ=cli,
            out=out,
            docker_check=never,
            tcp_check=never,
            deps_factory=never,
            mall_factory=never,
        )
        == 2
    )
    assert f"PREFLIGHT_FAILED ENV_MISSING:{missing}" in out.getvalue()
    assert not any(
        value in out.getvalue() for value in cli.values() if value.startswith("watch-")
    )


@pytest.mark.parametrize(
    "docker,tcp,code",
    [(False, True, "DOCKER_DOWN"), (True, False, "POSTGRES_UNREACHABLE")],
)
def test_preflight_service_codes(cli, docker, tcp, code):
    out = StringIO()
    never = Mock(side_effect=AssertionError("must not be called"))
    assert (
        p.main(
            ["--max-mfds-requests", "7"],
            environ=cli,
            out=out,
            docker_check=lambda: docker,
            tcp_check=lambda *args: tcp,
            deps_factory=never,
        )
        == 2
    )
    assert f"PREFLIGHT_FAILED {code}" in out.getvalue()
    never.assert_not_called()


def test_cost_cap_before_connections(cli):
    cli["BEAUTYADS_CAP_GEMINI_USD"] = "0"
    out = StringIO()
    never = Mock(side_effect=AssertionError("must not be called"))
    assert (
        p.main(
            ["--max-mfds-requests", "7"],
            environ=cli,
            out=out,
            docker_check=never,
            tcp_check=never,
            deps_factory=never,
        )
        == 2
    )
    assert "PREFLIGHT_FAILED COST_CAP:gemini" in out.getvalue()
    never.assert_not_called()


def test_scan_only_mall_no_images_models_mfds_db(cli):
    client, calls = mall()
    out = StringIO()
    never = Mock(side_effect=AssertionError("must not be called"))
    assert (
        p.main(
            ["--scan", "--max-mfds-requests", "7"],
            environ=cli,
            out=out,
            docker_check=never,
            tcp_check=never,
            deps_factory=never,
            mall_factory=lambda: client,
        )
        == 0
    )
    scan = json.loads(out.getvalue().splitlines()[0])
    assert scan["detail_image_count"] > 0
    assert "가정(미실측)" in out.getvalue()
    assert len(calls) == 2 and all(
        not u.endswith((".jpg", ".png", ".gif")) for u in calls
    )


def test_aliases_only_same_brand_and_optional_overrides(tmp_path):
    dep, _ = deps()
    extra = {("cosrx", "합성 세럼"): {"extra": ["추가 별칭"], "drop": ["합성 세럼"]}}
    out = StringIO()
    report = p.run_products(
        dep,
        [candidate()],
        brand_pool={"cosrx": ["합성 세럼"], "anua": ["합성 세럼 다른 제품"]},
        ingredient_aliases={},
        product_aliases=extra,
        report_path=tmp_path / "state.json",
        out=out,
    )
    assert dep.store.products[0].aliases == ["추가 별칭"]
    assert report["alias_count"]["product"] == 1
    assert isinstance(dep.store.products[0], Product)


def test_makefile_target_verify_unchanged():
    makefile = Path("Makefile").read_text()
    assert (
        "live-products:\n\tuv run python -m beautyads.pipeline.products $(ARGS)"
        in makefile
    )
    assert "live-products" in makefile.splitlines()[0]
    assert "live-" not in makefile.split("verify:\n")[1].split("\n\n")[0]


def test_scan_counts_images_even_when_text_available(cli):
    images = (FIXTURES / "mall_cafe24_image_only.html").read_bytes()
    client, _ = mall("text_div", extra=lambda body: body + images)
    out = StringIO()
    assert (
        p.main(
            ["--scan", "--max-mfds-requests", "7"],
            environ=cli,
            out=out,
            deps_factory=Mock(side_effect=AssertionError()),
            mall_factory=lambda: client,
        )
        == 0
    )
    scan = json.loads(out.getvalue().splitlines()[0])
    assert scan["has_ingredients_text"]
    assert scan["detail_image_count"] > 0


def test_model_402_is_pending_and_stops_downloads(tmp_path):
    from beautyads.llm import ErrorKind, LlmCallError

    dep, _ = deps("image_only")
    dep.extract.side_effect = LlmCallError(
        kind=ErrorKind.CREDITS_DEPLETED,
        code="RESOURCE_EXHAUSTED",
        message="private-token-and-image-bytes",
    )
    report, output = run(tmp_path, dep, [candidate(index=1), candidate(index=2)])
    assert [row["status"] for row in report["products"]] == ["pending", "pending"]
    assert report["stopped"] == "LLM_CREDITS_DEPLETED"
    assert "private-token-and-image-bytes" not in output
    dep.download.assert_called_once()
    assert not dep.store.products


def test_cert_page_cap_is_pending_not_failed(tmp_path):
    dep, _ = deps()
    dep.mfds.search_reports.return_value = MFDSResult([], "MFDS_PAGE_CAP")
    report, _ = run(tmp_path, dep)
    assert report["products"][0]["status"] == "pending"
    assert report["products"][0]["error_code"] == "MFDS_PAGE_CAP"
    assert not dep.store.certs


def test_model_contract_cost_summary_and_bytes_never_written(tmp_path):
    from io import BytesIO

    from PIL import Image

    from beautyads.analysis.product_detail import extract_product_detail

    dep, _ = deps("image_only")
    fixture = json.loads(
        (FIXTURES / "gemini_interactions_image_input.json").read_text()
    )
    body = deepcopy(fixture["probes"][0]["response"])
    body["_hidden_params"] = {
        "response_cost": fixture["probes"][0]["usage_summary"]["cost_usd"]
    }
    facts = {
        "ingredients": [{"raw_name": "병풀추출물", "amount_text": None}],
        "volume": None,
        "volume_unit": None,
        "form": None,
        "skin_types": [],
        "efficacy_texts": [],
        "functional_texts": [],
    }
    for step in body.get("steps", []):
        if step.get("type") == "model_output":
            step["content"] = [{"type": "text", "text": json.dumps(facts)}]
    image_buffer = BytesIO()
    Image.new("RGB", (20, 20), "white").save(image_buffer, format="PNG")
    dep = dep._replace(
        download=Mock(return_value=image_buffer.getvalue()),
        extract=lambda key, images: extract_product_detail(
            key,
            images,
            thinking_level="minimal",
            ledger_path=tmp_path / "ledger.jsonl",
            caps={"gemini": 100},
            interactions_fn=lambda **kwargs: body,
        ),
    )
    report, output = run(tmp_path, dep, ledger_path=tmp_path / "ledger.jsonl")
    assert report["cost_by_purpose"]["product-detail"]["calls"] == 1
    assert report["cost_by_purpose"]["product-detail"]["cost_usd"] > 0
    assert "PNG" not in output
    assert not list(tmp_path.glob("*.png"))
    assert len(dep.store.extractions) == 1


def test_held_output_preserves_raw_in_report(tmp_path):
    from beautyads.analysis.product_detail import ProductDetailOutcome
    from beautyads.domain.products import ProductExtraction

    dep, _ = deps("image_only")
    dep.extract.return_value = ProductDetailOutcome(
        status=JobStatus.held,
        extractions=[
            ProductExtraction(
                product=candidate().key,
                prompt_version="synthetic",
                raw_output="{invalid}",
            )
        ],
    )
    report, output = run(tmp_path, dep)
    assert report["products"][0]["status"] == "held"
    assert report["products"][0]["extractions"]
    assert "{invalid}" not in output
    assert not dep.store.ingredients


def test_product_selection_limits_work(cli):
    dep, _ = deps()
    out = StringIO()
    assert (
        p.main(
            ["--products", "1", "--max-mfds-requests", "7"],
            environ=cli,
            out=out,
            docker_check=lambda: True,
            tcp_check=lambda *args: True,
            deps_factory=lambda: dep,
        )
        == 0
    )
    assert len(dep.store.products) == 1
    assert "watch-secret" not in out.getvalue()


def test_product_alias_loader_valid_and_malformed(tmp_path):
    path = tmp_path / "aliases.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "aliases": [
                    {
                        "brand": "cosrx",
                        "name_ko": "합성 세럼",
                        "extra": ["추가"],
                        "drop": [],
                    }
                ]
            }
        )
    )
    assert p.load_product_aliases(path)[("cosrx", "합성 세럼")]["extra"] == ["추가"]
    path.write_text(
        yaml.safe_dump(
            {
                "aliases": [
                    {"brand": "cosrx", "name_ko": "합성 세럼", "extra": "invalid"}
                ]
            }
        )
    )
    with pytest.raises(p.ProductsError, match="ALIAS_INVALID"):
        p.load_product_aliases(path)


def test_ingredient_parentheses_only_amount_is_removed():
    dep, _ = deps()
    resolver = p.IngredientResolver(dep.store, {}, dep.now)
    rows = resolver.match(["병풀추출물(1,000 ppm)", "병풀추출물(다른 성분)"])
    assert [row["status"] for row in rows] == ["resolved", "unresolved"]


def test_scan_preflight_missing_credentials_never_constructs_mall(cli):
    out = StringIO()
    never = Mock(side_effect=AssertionError("must not be called"))
    cli.pop("GEMINI_API_KEY")
    assert (
        p.main(
            ["--scan", "--max-mfds-requests", "7"],
            environ=cli,
            out=out,
            docker_check=never,
            tcp_check=never,
            deps_factory=never,
            mall_factory=never,
        )
        == 2
    )
    assert "ENV_MISSING:GEMINI_API_KEY" in out.getvalue()


def test_failed_product_records_each_image_error_code(tmp_path):
    # PRODUCT_DETAIL_FAILED used to drop the per-image causes, so a live failure
    # could not be diagnosed afterwards.
    from beautyads.sources.mall import MallError

    dep, _ = deps("image_only")
    dep.download.side_effect = MallError("MALL_IMAGE_TOO_LARGE")
    urls = dep.mall.fetch_product("cosrx", candidate().url).detail_image_urls
    report, _ = run(tmp_path, dep)
    row = report["products"][0]
    assert row["status"] == "failed"
    assert row["error_code"] == "PRODUCT_DETAIL_FAILED"
    assert row["issues"] == ["MALL_IMAGE_TOO_LARGE"] * len(urls)
    saved = json.loads((tmp_path / "state.json").read_text())["products"][0]
    assert saved["issues"] == row["issues"]
    dep.extract.assert_not_called()


def test_held_product_records_chunk_issue_codes(tmp_path):
    from beautyads.analysis.product_detail import DetailIssue, ProductDetailOutcome

    dep, _ = deps("image_only")
    dep.extract.return_value = ProductDetailOutcome(
        status=JobStatus.held,
        issues=[DetailIssue(image_index=0, top=0, error_code="INVALID_OUTPUT")],
    )
    report, _ = run(tmp_path, dep)
    row = report["products"][0]
    assert row["status"] == "held" and row["error_code"] == "PRODUCT_DETAIL_HELD"
    assert "INVALID_OUTPUT" in row["issues"]


def test_product_with_no_ingredients_is_held_not_done(tmp_path):
    # An empty ingredient list must not quietly become a product record.
    from beautyads.analysis.product_detail import ProductDetailOutcome
    from beautyads.domain.products import ProductDetailResult, ProductExtraction

    dep, _ = deps("image_only")
    facts = {
        "ingredients": [],
        "volume": None,
        "volume_unit": None,
        "form": None,
        "skin_types": [],
        "efficacy_texts": [],
        "functional_texts": [],
    }
    dep.extract.return_value = ProductDetailOutcome(
        status=JobStatus.done,
        result=ProductDetailResult.model_validate(facts),
        extractions=[
            ProductExtraction(
                product=candidate().key, prompt_version="synthetic", raw_output="{}"
            )
        ],
    )
    report, _ = run(tmp_path, dep)
    row = report["products"][0]
    assert row["status"] == "held"
    assert row["error_code"] == "PRODUCT_INGREDIENTS_EMPTY"
    assert row["hold_reason"] == "성분 없음"
    # Every image was read (the list stays empty) and each raw output is kept.
    urls = dep.mall.fetch_product("cosrx", candidate().url).detail_image_urls
    assert len(row["extractions"]) == len(urls) >= 1
    assert not dep.store.products and not dep.store.ingredients
    assert report["by_status"] == {"held": 1}
    dep.mfds.search_reports.assert_not_called()  # no certification work for it


def test_summary_counts_every_ingredient_lookup_by_source(tmp_path):
    dep, _ = deps()
    report, _ = run(tmp_path, dep, [candidate(index=1), candidate(index=2)])
    cache = report["ingredient_cache"]
    assert set(cache) == {"catalog_lookups", "memo_hits", "db_hits"}
    assert cache["catalog_lookups"] > 0 and cache["memo_hits"] > 0
    assert sum(cache.values()) == report["ingredient_count"]
    assert report["ingredient_catalog"]["rows"] == len(dep.store.catalog)
    assert report["ingredient_ambiguous"] == []


def test_resolved_lookups_are_cached_across_runs_and_unresolved_are_not():
    dep, _ = deps()
    first = p.IngredientResolver(dep.store, {}, dep.now)
    first.match(["병풀추출물", "미등재"])
    assert set(dep.store.lookups) == {("병풀추출물", "kor_exact")}
    dep.store.catalog = []  # the next resolver must not need the catalog for a hit
    second = p.IngredientResolver(dep.store, {}, dep.now)
    rows = second.match(["병풀추출물"])
    assert rows[0]["status"] == "resolved" and rows[0]["matched_by"] == "kor_exact"
    assert dict(second.stats) == {"memo_hits": 0, "db_hits": 1, "catalog_lookups": 0}


def test_the_catalog_is_only_loaded_when_a_name_misses_every_cache():
    dep, _ = deps()
    resolver = p.IngredientResolver(dep.store, {}, dep.now)
    assert resolver.catalog_stats is None
    resolver.match(["병풀추출물"])
    assert resolver.catalog_stats["rows"] == len(dep.store.catalog)


def test_certification_stop_still_reports_provider_code_and_message(tmp_path):
    dep, _ = deps()
    dep.mfds.search_reports.return_value = MFDSResult(
        [],
        "MFDS_API_ERROR",
        MFDSError(
            "MFDS_API_ERROR",
            provider_code="22",
            provider_message="LIMITED\nNUMBER " + "x" * 400,
            http_status=200,
        ),
    )
    report, output = run(tmp_path, dep, [candidate(index=1), candidate(index=2)])
    assert report["stopped"] == "MFDS_API_ERROR"
    detail = report["stopped_detail"]
    assert detail["provider_code"] == "22" and detail["http_status"] == 200
    assert "\n" not in detail["provider_message"]
    assert len(detail["provider_message"]) <= 200
    stopped_line = next(
        line for line in output.splitlines() if line.startswith("STOPPED ")
    )
    assert stopped_line.startswith("STOPPED MFDS_API_ERROR provider_code=22 ")


def test_matched_by_is_saved_with_each_product_ingredient(tmp_path):
    dep, _ = deps()
    run(tmp_path, dep)
    saved = dep.store.ingredients
    assert saved and all(
        (row.status == "resolved") == (row.matched_by is not None) for row in saved
    )


def _empty_detail(dep):
    from beautyads.analysis.product_detail import ProductDetailOutcome
    from beautyads.domain.products import ProductDetailResult, ProductExtraction

    facts = {
        "ingredients": [],
        "volume": None,
        "volume_unit": None,
        "form": None,
        "skin_types": [],
        "efficacy_texts": [],
        "functional_texts": [],
    }
    dep.extract.side_effect = lambda *_: ProductDetailOutcome(
        status=JobStatus.done,
        result=ProductDetailResult.model_validate(facts),
        extractions=[
            ProductExtraction(
                product=candidate().key, prompt_version="synthetic", raw_output="{}"
            )
        ],
    )


def test_image_read_cap_holds_the_product_and_reads_no_more_images(
    tmp_path, monkeypatch
):
    dep, _ = deps("image_only")
    urls = dep.mall.fetch_product("cosrx", candidate().url).detail_image_urls
    assert len(urls) > 2
    monkeypatch.setattr(p, "_MAX_IMAGES_PER_PRODUCT", 2)
    _empty_detail(dep)
    report, _ = run(tmp_path, dep)
    row = report["products"][0]
    assert row["status"] == "held" and row["error_code"] == "PRODUCT_IMAGE_READ_CAP"
    assert row["hold_reason"] == "이미지 읽기 상한"
    assert dep.extract.call_count == 2 and len(row["extractions"]) == 2
    assert dep.download.call_count == 2
    assert not dep.store.products and not dep.store.ingredients
    dep.mfds.search_reports.assert_not_called()


def test_ingredients_found_before_the_cap_are_not_held(tmp_path, monkeypatch):
    # The cap only applies while nothing was found.
    dep, _ = deps("image_only")
    monkeypatch.setattr(p, "_MAX_IMAGES_PER_PRODUCT", 1)
    from beautyads.analysis.product_detail import ProductDetailOutcome
    from beautyads.domain.products import ProductDetailResult

    facts = {
        "ingredients": [{"raw_name": "병풀추출물", "amount_text": None}],
        "volume": None,
        "volume_unit": None,
        "form": None,
        "skin_types": [],
        "efficacy_texts": [],
        "functional_texts": [],
    }
    dep.extract.return_value = ProductDetailOutcome(
        status=JobStatus.done, result=ProductDetailResult.model_validate(facts)
    )
    report, _ = run(tmp_path, dep)
    assert report["products"][0]["status"] == "done"


def _report(name, *, spf="50+", entp="다른 회사", **changes):
    return FunctionalReport(
        item_name=name,
        entp_name=entp,
        spf=spf,
        effect_text="피부의 미백에 도움을 준다.",
        source="report",
        **changes,
    )


def _cert(items, title="콩 선세럼 50ml", brand_name="믹순", screenings=()):
    dep, _ = deps()
    dep.mfds.search_reports.return_value = MFDSResult(list(items))
    dep.mfds.search_screenings.return_value = MFDSResult(list(screenings))
    certs = p.match_certs(candidate(title=title), dep.mfds, brand_name)
    return {c.kind.value: c for c in certs}, dep


def test_cert_matches_only_brand_prefixed_name_equal_after_normalizing_the_mall_name():
    certs, dep = _cert([_report("믹순콩선세럼")])
    assert certs["sun_protection"].status.value == "certified"
    assert certs["sun_protection"].evidence_item_name == "믹순콩선세럼"
    # The query is the mall name without SPF/PA, volume and symbols, spaces removed.
    assert dep.mfds.search_reports.call_args.args == ("콩선세럼",)


def test_cert_name_with_spf_suffix_is_not_the_normalized_name():
    # Real MFDS data has "믹순콩선세럼" and "믹순콩선세럼SPF50+PA++++" side by side;
    # only the first equals brand + normalized name, so it is a single candidate.
    certs, _ = _cert([_report("믹순콩선세럼SPF50+PA++++"), _report("믹순콩선세럼")])
    assert certs["sun_protection"].evidence_item_name == "믹순콩선세럼"


def test_two_different_matching_item_names_are_ambiguous_and_stay_unknown():
    certs, _ = _cert([_report("믹순콩선세럼"), _report("믹순 콩 선세럼")])
    assert {c.status.value for c in certs.values()} == {"unknown"}
    assert all(c.evidence_item_name is None for c in certs.values())


def test_the_same_item_name_in_both_apis_is_one_candidate():
    certs, _ = _cert(
        [_report("믹순콩선세럼")],
        screenings=[
            FunctionalReport(
                item_name="믹순콩선세럼",
                source="screening",
                effect_text="피부의 미백에 도움을 준다.",
            )
        ],
    )
    assert certs["sun_protection"].status.value == "certified"
    assert certs["brightening"].status.value == "certified"


@pytest.mark.parametrize(
    "name",
    [
        "단하나콩선세럼",  # another brand's prefix
        "콩선세럼",  # no brand prefix at all
        "믹순콩선세럼추가",  # longer than the normalized name
        "콩선세럼믹순",  # brand is not a prefix
    ],
)
def test_names_without_the_exact_brand_prefix_are_never_accepted(name):
    certs, _ = _cert([_report(name)])
    assert {c.status.value for c in certs.values()} == {"unknown"}


def test_company_name_never_decides_the_brand_or_the_match():
    certs, _ = _cert([_report("다른제품", entp="믹순콩선세럼")])
    assert {c.status.value for c in certs.values()} == {"unknown"}
    certs, _ = _cert([_report("콩선세럼", entp="믹순")])
    assert {c.status.value for c in certs.values()} == {"unknown"}


def test_cancelled_reports_are_ignored():
    certs, _ = _cert(
        [
            _report("믹순콩선세럼", cancelled=True),
            _report("믹순콩선세럼", cancelled_raw="Y"),
        ]
    )
    assert {c.status.value for c in certs.values()} == {"unknown"}


def test_a_brand_without_a_korean_name_is_unknown_without_any_request():
    certs, dep = _cert([_report("믹순콩선세럼")], brand_name=None)
    assert {c.status.value for c in certs.values()} == {"unknown"}
    dep.mfds.search_reports.assert_not_called()
    dep.mfds.search_screenings.assert_not_called()


@pytest.mark.parametrize(
    "title,core",
    [
        (
            "어성초 마일드 선크림 릴리프 튜브 SPF50+ PA++++",
            "어성초마일드선크림릴리프튜브",
        ),
        ("인삼선세럼 (SPF 50+ PA++++)", "인삼선세럼"),
        (
            "맑은쌀선크림 : 쌀추출물+나이아신아마이드 (SPF 50+ PA++++)",
            "맑은쌀선크림쌀추출물나이아신아마이드",
        ),
        ("워터풀 에센스 선크림 50ml", "워터풀에센스선크림"),
        ("PANTHENOL PA 크림 20g", "PANTHENOL크림"),
        ("PDRN 실키 선 스틱", "PDRN실키선스틱"),
    ],
)
def test_mall_name_normalization(title, core):
    assert p._cert_core(title) == core.casefold()


def test_brand_korean_names_loader_requires_nonblank_text(tmp_path):
    path = tmp_path / "names.yaml"
    path.write_text(
        yaml.safe_dump({"brands": {"cosrx": "코스알엑스"}}), encoding="utf-8"
    )
    assert p.load_brand_korean_names(path) == {"cosrx": "코스알엑스"}
    for bad in [{"brands": {"cosrx": " "}}, {"brands": []}, {"other": {}}, {}]:
        path.write_text(yaml.safe_dump(bad), encoding="utf-8")
        with pytest.raises(p.ProductsError, match="BRAND_NAMES_INVALID"):
            p.load_brand_korean_names(path)
    with pytest.raises(p.ProductsError, match="BRAND_NAMES_INVALID"):
        p.load_brand_korean_names(tmp_path / "missing.yaml")


def test_the_real_brand_name_table_covers_every_candidate_brand():
    names = p.load_brand_korean_names(p.BRAND_NAMES_PATH)
    brands = {item.brand for item in p.load_candidates(p.CANDIDATES_PATH)}
    assert brands <= set(names)


def test_cert_coverage_counts_products_and_each_kind(tmp_path):
    dep, _ = deps()
    dep.mfds.search_reports.side_effect = lambda name: (
        MFDSResult(
            [
                FunctionalReport(
                    item_name="합성" + name,
                    source="report",
                    effect_text="피부의 미백에 도움을 준다.",
                )
            ]
        )
        if name == "합성세럼"
        else MFDSResult([])
    )
    report, _ = run(
        tmp_path,
        dep,
        [candidate(index=1, title="합성 세럼"), candidate(index=2, title="다른 제품")],
        brand_korean_names={"cosrx": "합성", "anua": "합성"},
    )
    cert = report["certification"]
    assert cert["certified"] == 1 and cert["unknown"] == 1
    assert cert["by_kind"]["brightening"] == {"certified": 1, "unknown": 1}
    assert cert["by_kind"]["sun_protection"] == {"certified": 0, "unknown": 2}
    assert cert["coverage"] == 0.5


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "정제수, 1,2-헥산다이올, 글리세린",
            ["정제수", " 1,2-헥산다이올", " 글리세린"],
        ),
        ("Water, 1,2-Hexanediol, Glycerin", ["Water", " 1,2-Hexanediol", " Glycerin"]),
        (
            "2,4-다이메틸, C12,13알킬벤조에이트",
            ["2,4-다이메틸", " C12,13알킬벤조에이트"],
        ),
        ("글리세린,1,2-헥산다이올,정제수", ["글리세린", "1,2-헥산다이올", "정제수"]),
        # Existing rules stay: parenthesized commas, full-width comma, semicolon, newline.
        (
            "에스에이치-올리고펩타이드-1(2.5ppm, a), 정제수",
            ["에스에이치-올리고펩타이드-1(2.5ppm, a)", " 정제수"],
        ),
        ("가，나;다\n라", ["가", "나", "다", "라"]),
        # A comma next to a space or a letter is still a delimiter.
        ("비타민 B6, 3 글리세린", ["비타민 B6", " 3 글리세린"]),
        ("a1, 2b", ["a1", " 2b"]),
    ],
)
def test_ingredient_text_splits_on_commas_but_not_between_digits(text, expected):
    assert p._split_ingredients(text) == expected


def test_product_ingredients_are_saved_as_a_whole_set_replacement(tmp_path):
    dep, _ = deps()
    run(tmp_path, dep)
    key = candidate().key
    saved = [row for row in dep.store.ingredients if row.product == key]
    assert dep.store.replaced == [(key, len(saved))]
    # A second run of the same product replaces the set, never appends to it.
    run(tmp_path, dep)
    assert len([row for row in dep.store.ingredients if row.product == key]) == len(
        saved
    )
