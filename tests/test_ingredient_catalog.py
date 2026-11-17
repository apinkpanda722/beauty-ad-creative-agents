"""Catalog download (resumable) and exact Korean/English matching; no network."""

from datetime import UTC, datetime
from io import StringIO

import pytest

from beautyads.domain.mfds import IngredientStandard
from beautyads.domain.products import IngredientCatalogEntry
from beautyads.pipeline import ingredient_catalog as c
from beautyads.sources.mfds import MFDSError, MFDSPage

NOW = datetime(2026, 11, 15, tzinfo=UTC)


class Store:
    def __init__(self):
        self.entries = {}

    def upsert_catalog_page(self, entries):
        for entry in entries:
            self.entries[(entry.page_no, entry.row_no)] = entry

    def catalog_last_page(self):
        return max((page for page, _ in self.entries), default=0)

    def list_catalog(self):
        return [self.entries[key] for key in sorted(self.entries)]


def row(ko, en=None, cas=None):
    return IngredientStandard(name_ko=ko, name_en=en, cas_no=cas)


class Mfds:
    """Serve fixed pages of a fixed list; record which pages were requested."""

    def __init__(self, rows, *, size=2, fail_on=None, code="MFDS_API_ERROR"):
        self.rows = rows
        self.size = size
        self.requested = []
        self.fail_on = fail_on
        self.code = code

    def fetch_ingredient_page(self, page_no, *, num_of_rows=100):
        assert num_of_rows == c.CATALOG_PAGE_SIZE
        self.requested.append(page_no)
        if page_no == self.fail_on:
            error = MFDSError(self.code, provider_code="22")
            return MFDSPage([], None, self.code, error)
        start = (page_no - 1) * self.size
        return MFDSPage(self.rows[start : start + self.size], len(self.rows))


@pytest.fixture(autouse=True)
def small_pages(monkeypatch):
    monkeypatch.setattr(c, "CATALOG_PAGE_SIZE", 2)


def sync(mfds, store):
    out = StringIO()
    return c.sync_catalog(mfds, store, lambda: NOW, out), out.getvalue()


def test_sync_stores_every_page_and_reports_completion():
    rows = [row("가", "A"), row("나"), row("다", "C"), row("라"), row("마", "E")]
    store, mfds = Store(), Mfds(rows)
    summary, _ = sync(mfds, store)
    assert summary["complete"] is True and summary["stopped"] is None
    assert summary["stored"] == 5 and summary["pages_fetched"] == 3
    assert [e.name_ko for e in store.list_catalog()] == ["가", "나", "다", "라", "마"]
    assert {e.source_total for e in store.list_catalog()} == {5}
    assert mfds.requested == [1, 2, 3]


def test_sync_resumes_after_a_stop_without_refetching_stored_pages():
    rows = [row(name) for name in "가나다라마바"]
    store = Store()
    first = Mfds(rows, fail_on=2)
    summary, text = sync(first, store)
    assert summary["complete"] is False and summary["stopped"] == "MFDS_API_ERROR"
    assert summary["stopped_detail"] == {"provider_code": "22"}
    assert store.catalog_last_page() == 1 and "STOPPED MFDS_API_ERROR" in text
    second = Mfds(rows)
    summary, _ = sync(second, store)
    assert summary["complete"] is True and second.requested == [2, 3]
    assert len(store.list_catalog()) == 6


def test_sync_on_an_already_complete_catalog_asks_once_and_stores_nothing():
    rows = [row(name) for name in "가나다라"]
    store = Store()
    sync(Mfds(rows), store)
    again = Mfds(rows)
    summary, _ = sync(again, store)
    assert summary["complete"] is True and summary["stored"] == 0
    assert again.requested == [3]


def test_rows_without_a_korean_name_are_skipped_and_counted():
    rows = [row(None, "No Korean"), row("가", "A")]
    store = Store()
    summary, _ = sync(Mfds(rows), store)
    assert summary["stored"] == 1 and summary["skipped_without_name"] == 1


def test_catalog_completeness_needs_every_page_of_the_recorded_total():
    entries = [
        IngredientCatalogEntry(
            page_no=1, row_no=0, name_ko="가", source_total=5, fetched_at=NOW
        )
    ]
    assert c.catalog_complete(entries) is False
    assert c.catalog_complete([]) is False
    full = entries + [
        IngredientCatalogEntry(
            page_no=3, row_no=0, name_ko="나", source_total=5, fetched_at=NOW
        )
    ]
    assert c.catalog_complete(full) is True


def entry(name_ko, name_en=None, page=1, row_no=0):
    return IngredientCatalogEntry(
        page_no=page,
        row_no=row_no,
        name_ko=name_ko,
        name_en=name_en,
        source_total=2,
        fetched_at=NOW,
    )


def test_korean_match_ignores_whitespace_but_returns_the_catalog_name():
    index = c.CatalogIndex([entry("리나칸투스 콤무니스추출물", "Rhinacanthus Extract")])
    assert index.match("리나칸투스콤무니스추출물") == (
        "kor_exact",
        "리나칸투스 콤무니스추출물",
    )
    assert index.match("리나칸투스") is None


def test_english_match_is_exact_after_case_space_and_edge_punctuation_only():
    index = c.CatalogIndex([entry("부틸렌글라이콜", "Butylene Glycol")])
    for raw in [
        "Butylene Glycol",
        " butylene   GLYCOL ",
        "BUTYLENE GLYCOL,",
        "(Butylene Glycol",
    ]:
        assert index.match(raw) == ("eng_name_exact", "부틸렌글라이콜"), raw
    # Not fuzzy: a different token, extra word, or removed space never matches.
    for raw in [
        "Butylene",
        "Butylene Glycol Extract",
        "ButyleneGlycol",
        "Butylen Glycol",
    ]:
        assert index.match(raw) is None, raw


def test_one_english_name_for_two_korean_names_is_ambiguous_and_never_picked():
    index = c.CatalogIndex(
        [entry("가", "Same Name", row_no=0), entry("나", "same name", row_no=1)]
    )
    assert index.match("Same Name") == ("ambiguous", None)
    assert index.stats["ambiguous_english"] == 1


def test_the_same_korean_name_twice_is_not_ambiguous():
    index = c.CatalogIndex(
        [entry("가", "Name", row_no=0), entry("가", "Name", row_no=1)]
    )
    assert index.match("Name") == ("eng_name_exact", "가")


@pytest.mark.parametrize("english", [None, "", "  ", "Alpha\r\nBeta", "Alpha;Beta"])
def test_null_blank_or_mixed_english_names_are_not_match_keys(english):
    index = c.CatalogIndex([entry("가", english)])
    assert index.match("Alpha") is None
    assert index.match("Alpha;Beta") is None
    assert index.stats["usable_english"] == 0


def test_korean_wins_and_a_korean_ambiguity_blocks_the_english_route():
    index = c.CatalogIndex(
        [
            entry("가 나", "Alpha", row_no=0),
            entry("가나", "Alpha Two", row_no=1),
        ]
    )
    assert index.match("가나") == ("ambiguous", None)
    only = c.CatalogIndex([entry("가나", "가나")])
    assert only.match("가나") == ("kor_exact", "가나")


def test_index_stats_count_rows_english_and_ambiguity():
    index = c.CatalogIndex(
        [
            entry("가", "A", row_no=0),
            entry("나", None, row_no=1),
            entry("다", "A", row_no=2),
            entry("라", "B;C", row_no=3),
        ]
    )
    assert index.stats == {
        "rows": 4,
        "with_english": 3,
        "usable_english": 2,
        "ambiguous_english": 1,
        "ambiguous_korean": 0,
    }


def run_main(argv, environ, store=None, mfds=None):
    out = StringIO()
    code = c.main(
        argv,
        environ=environ,
        out=out,
        deps_factory=(lambda: (mfds, store)) if mfds is not None else None,
        docker_check=lambda: True,
        tcp_check=lambda *_: True,
    )
    return code, out.getvalue()


def test_main_reports_a_summary_and_exit_code_for_complete_and_stopped_runs():
    environ = {"DATA_GO_KR_SERVICE_KEY": "synthetic", "POSTGRES_PASSWORD": "synthetic"}
    rows = [row("가", "A"), row("나", "A"), row("다")]
    code, text = run_main(["--max-mfds-requests", "9"], environ, Store(), Mfds(rows))
    assert code == 0 and '"complete": true' in text and '"ambiguous_english": 1' in text
    code, text = run_main(
        ["--max-mfds-requests", "9"], environ, Store(), Mfds(rows, fail_on=1)
    )
    assert code == 3 and "STOPPED MFDS_API_ERROR" in text


def test_main_refuses_to_start_without_the_key_and_prints_no_secret():
    code, text = run_main(
        ["--max-mfds-requests", "9"], {"POSTGRES_PASSWORD": "synthetic"}
    )
    assert code == 2 and "PREFLIGHT_FAILED ENV_MISSING:DATA_GO_KR_SERVICE_KEY" in text
    assert "synthetic" not in text


def test_main_requires_a_request_cap():
    assert run_main([], {})[0] == 2
