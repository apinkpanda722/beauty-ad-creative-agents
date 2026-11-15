"""Certification-only re-matching of stored products; MFDS calls only, no mall or model."""

from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

from beautyads.domain.mfds import FunctionalReport
from beautyads.domain.products import ProductKey
from beautyads.pipeline import cert_recheck as c
from beautyads.sources.mfds import MFDSError, MFDSResult


class Store:
    def __init__(self, products):
        self.products = products
        self.certs = {}
        self.listed = 0

    def list_products(self):
        self.listed += 1
        return self.products

    def upsert_certs(self, certs):
        self.certs[certs[0].product] = certs


def stored(brand, title, n):
    url = f"https://{brand}.example/p/{n}"
    return SimpleNamespace(
        brand=brand,
        name_ko=title,
        source_url=url,
        key=ProductKey(brand=brand, source_url=url),
    )


def report(name, *, spf="50+", effect="피부의 미백에 도움을 준다."):
    return FunctionalReport(
        item_name=name, spf=spf, effect_text=effect, source="report"
    )


def mfds(reports=(), screenings=()):
    return SimpleNamespace(
        search_reports=Mock(side_effect=lambda q: MFDSResult(list(reports))),
        search_screenings=Mock(side_effect=lambda q: MFDSResult(list(screenings))),
        requests_made=0,
    )


NAMES = {"mixsoon": "믹순", "anua": "아누아"}


def run(store, client, names=NAMES):
    out = StringIO()
    return c.recheck_certs(store, client, names, out), out.getvalue()


def test_recheck_matches_stored_names_and_counts_each_kind():
    store = Store(
        [stored("mixsoon", "콩 선세럼 50ml", 1), stored("anua", "다른 제품", 2)]
    )
    summary, _ = run(store, mfds(reports=[report("믹순콩선세럼")]))
    assert summary["products"] == 2 and summary["certified_products"] == 1
    assert summary["by_kind"]["sun_protection"] == {"certified": 1, "unknown": 1}
    assert summary["by_kind"]["brightening"] == {"certified": 1, "unknown": 1}
    assert summary["by_kind"]["anti_aging"] == {"certified": 0, "unknown": 2}
    assert summary["stopped"] is None and summary["pending"] == 0
    # Every stored product's certifications were rewritten, certified or not.
    assert set(store.certs) == {p.key for p in store.products}


def test_recheck_uses_only_the_mfds_client_and_the_store():
    client = mfds()
    store = Store([stored("mixsoon", "콩 선세럼", 1)])
    run(store, client)
    assert store.listed == 1
    client.search_reports.assert_called_once()


def test_a_retryable_failure_keeps_the_stored_certs_and_continues():
    store = Store([stored("mixsoon", "콩 선세럼", 1), stored("anua", "x 크림", 2)])
    calls = []

    def search_reports(query):
        calls.append(query)
        if len(calls) == 1:
            return MFDSResult([], "MFDS_LOOKUP_FAILED", MFDSError("MFDS_LOOKUP_FAILED"))
        return MFDSResult([])

    client = mfds()
    client.search_reports = Mock(side_effect=search_reports)
    summary, _ = run(store, client)
    assert summary["pending"] == 1 and summary["products"] == 2
    assert store.products[0].key not in store.certs  # left as it was
    assert store.products[1].key in store.certs


def test_a_system_stop_ends_the_run_and_leaves_the_rest_untouched():
    store = Store([stored("mixsoon", "콩 선세럼", 1), stored("anua", "x 크림", 2)])
    client = mfds()
    client.search_reports = Mock(
        return_value=MFDSResult(
            [],
            "MFDS_API_ERROR",
            MFDSError("MFDS_API_ERROR", provider_code="22", http_status=200),
        )
    )
    summary, text = run(store, client)
    assert summary["stopped"] == "MFDS_API_ERROR"
    assert summary["stopped_detail"]["provider_code"] == "22"
    assert store.certs == {} and client.search_reports.call_count == 1
    assert "STOPPED MFDS_API_ERROR" in text


def test_an_empty_store_is_not_a_clean_pass():
    summary, _ = run(Store([]), mfds())
    assert summary["products"] == 0 and summary["ok"] is False


def test_main_runs_with_injected_deps_and_prints_a_summary():
    store = Store([stored("mixsoon", "콩 선세럼", 1)])
    out = StringIO()
    code = c.main(
        ["--max-mfds-requests", "9"],
        environ={
            "DATA_GO_KR_SERVICE_KEY": "synthetic",
            "POSTGRES_PASSWORD": "synthetic",
        },
        out=out,
        deps_factory=lambda: (mfds(), store, NAMES),
    )
    assert code == 0 and "SUMMARY" in out.getvalue()
    assert "synthetic" not in out.getvalue()


def test_main_without_the_service_key_refuses_to_start():
    out = StringIO()
    code = c.main(
        ["--max-mfds-requests", "9"],
        environ={"POSTGRES_PASSWORD": "synthetic"},
        out=out,
        deps_factory=lambda: (mfds(), Store([]), NAMES),
    )
    assert code == 2 and "ENV_MISSING:DATA_GO_KR_SERVICE_KEY" in out.getvalue()
