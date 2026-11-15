"""Offline MFDS adapters, using recorded contracts and explicit edge mutations."""

import json
from collections import deque
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
import pytest

from beautyads import settings
from beautyads.domain.mfds import (
    CertStatus,
    FunctionalKind,
    FunctionalReport,
    IngredientStandard,
    functional_kinds,
)
from beautyads.sources.mfds import MFDSClient, MFDSError, MFDSHttpResponse

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"


def recorded(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def body(name):
    return recorded(f"mfds_{name}.json").get("response")


def page(name, items=None, total=None):
    result = body(name)
    content = result.get("body")
    if items is not None:
        content["items"] = items
    if total is not None:
        content["totalCount"] = total
    return MFDSHttpResponse(200, result)


class FakeGet:
    def __init__(self, *responses):
        self.responses = deque(responses)
        self.calls = []

    def __call__(self, url, params, timeout_s):
        assert not urlsplit(url).query
        assert timeout_s > 0
        self.calls.append((url, dict(params)))
        result = self.responses.popleft()
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture(autouse=True)
def fake_setting(monkeypatch):
    sentinel = uuid4().hex + "/+="

    def require(name):
        assert name == "DATA_GO_KR_SERVICE_KEY"
        return sentinel

    monkeypatch.setattr(settings, "require_setting", require)
    return sentinel


def client(get, **kwargs):
    return MFDSClient(
        get=get,
        max_requests=kwargs.pop("max_requests", 10),
        clock=kwargs.pop("clock", lambda: 0.0),
        sleep=kwargs.pop("sleep", lambda _: None),
        **kwargs,
    )


def test_ingredient_exact_match_and_whitespace_request():
    get = FakeGet(page("ingredient_query", total=3))
    result = client(get).search_ingredients(" 병풀\t추출물 ")
    assert result.stopped is None and result.error is None
    assert len(result.items) == 1
    item = next(iter(result.items))
    assert isinstance(item, IngredientStandard)
    assert item.name_ko == "병풀추출물"
    original = next(iter(body("ingredient_query").get("body").get("items")))
    assert (item.name_en, item.cas_no) == (
        original.get("INGR_ENG_NAME"),
        original.get("CAS_NO"),
    )
    url, params = next(iter(get.calls))
    assert url == (
        "https://apis.data.go.kr/1471000/CsmtcsIngdCpntInfoService01/"
        "getCsmtcsIngdCpntInfoService01"
    )
    assert params.get("INGR_KOR_NAME") == "병풀추출물"
    assert params.get("type") == "json"
    assert params.get("pageNo") == "1"
    assert params.get("numOfRows") is not None


def test_partial_matches_are_never_substituted():
    items = body("ingredient_query").get("body").get("items")
    partials = [row for row in items if row.get("INGR_KOR_NAME") != "병풀추출물"]
    result = client(
        FakeGet(page("ingredient_query", partials, len(partials)))
    ).search_ingredients("병풀추출물")
    assert result.items == [] and result.stopped is None


@pytest.mark.parametrize(
    "method,fixture",
    [
        ("search_ingredients", "ingredient_query_no_match"),
        ("search_screenings", "screening_query_no_match"),
        ("search_reports", "screening_query_no_match"),
    ],
)
def test_no_match_without_items(method, fixture):
    result = getattr(client(FakeGet(page(fixture))), method)("없는품목")
    assert result.items == [] and result.stopped is None


def test_ingredient_pagination_finds_exact_on_later_page():
    rows = body("ingredient_query").get("body").get("items")
    exact = [row for row in rows if row.get("INGR_KOR_NAME") == "병풀추출물"]
    partial = [row for row in rows if row.get("INGR_KOR_NAME") != "병풀추출물"]
    get = FakeGet(
        page("ingredient_query", partial, 3), page("ingredient_query", exact, 3)
    )
    result = client(get).search_ingredients("병풀추출물", max_pages=2)
    assert len(result.items) == 1 and result.stopped is None
    assert [params.get("pageNo") for _, params in get.calls] == ["1", "2"]


@pytest.mark.parametrize(
    "method,fixture",
    [
        ("search_ingredients", "ingredient_query"),
        ("search_reports", "functional_report_query"),
        ("search_screenings", "screening_query"),
    ],
)
def test_page_cap_is_unresolved(method, fixture):
    get = FakeGet(page(fixture, total=100))
    result = getattr(client(get), method)("없는정확일치", max_pages=1)
    assert result.stopped == "MFDS_PAGE_CAP"
    assert len(get.calls) == 1


def test_report_conversion_and_request_fields():
    get = FakeGet(page("functional_report_query", total=3))
    result = client(get).search_reports("선 크림")
    assert len(result.items) == 3 and result.stopped is None
    for converted, original in zip(
        result.items,
        body("functional_report_query").get("body").get("items"),
        strict=True,
    ):
        assert isinstance(converted, FunctionalReport)
        assert converted.source == "report"
        assert converted.item_name == original.get("ITEM_NAME")
        assert converted.entp_name == original.get("ENTP_NAME")
        assert converted.report_date == original.get("REPORT_DATE")
        assert converted.effect_text == original.get("EE_NAME")
        assert converted.cancelled is False and converted.cancelled_raw == "N"
        assert (
            functional_kinds(converted).get(FunctionalKind.sun_protection)
            == CertStatus.unknown
        )
    url, params = next(iter(get.calls))
    assert url.endswith("/1471000/FtnltCosmRptPrdlstInfoService01/getRptPrdlstInq01")
    assert params.get("item_name") == "선크림"
    assert "entp_name" not in params


@pytest.mark.parametrize(
    "raw,kept,cancelled",
    [
        ("Y", False, True),
        ("N", True, False),
        ("y", True, None),
        ("other", True, None),
        (None, True, None),
    ],
)
def test_cancellation_only_uppercase_y(raw, kept, cancelled):
    original = next(iter(body("functional_report_query").get("body").get("items")))
    original["CANCEL_APPROVAL_YN"] = raw
    result = client(
        FakeGet(page("functional_report_query", [original], 1))
    ).search_reports("선크림")
    assert bool(result.items) is kept
    if kept:
        item = next(iter(result.items))
        assert item.cancelled_raw == raw and item.cancelled is cancelled


def test_suncare_probe_preserves_values_and_unknowns():
    probe = recorded("instagram_mfds_youtube_probe.json").get("mfds_sun")
    rows = [
        {"ITEM_NAME": name, "SPF": spf, "PA": pa, "CANCEL_APPROVAL_YN": cancel}
        for group in probe.values()
        for name, spf, pa, cancel in group.get("spf_pa_sample")
    ]
    result = client(
        FakeGet(page("functional_report_query", rows, len(rows)))
    ).search_reports("선")
    statuses = set()
    for item, row in zip(result.items, rows, strict=True):
        assert (item.spf, item.pa) == (row.get("SPF"), row.get("PA"))
        status = functional_kinds(item).get(FunctionalKind.sun_protection)
        assert status == (
            CertStatus.certified if item.spf or item.pa else CertStatus.unknown
        )
        statuses.add(status)
    assert statuses == {CertStatus.unknown, CertStatus.certified}


@pytest.mark.parametrize(
    "text,kinds",
    [
        ("피부의 미백에 도움을 준다.", {FunctionalKind.brightening}),
        ("피부의 주름 개선에 도움을 준다.", {FunctionalKind.anti_aging}),
        (
            "피부의 미백과 주름개선에 도움을 준다.",
            {FunctionalKind.brightening, FunctionalKind.anti_aging},
        ),
        (None, set()),
        ("", set()),
        ("효능 미확인", set()),
    ],
)
def test_functional_kind_detection_from_synthetic_effect(text, kinds):
    report = FunctionalReport(source="report", effect_text=text)
    statuses = functional_kinds(report)
    assert set(statuses) == set(FunctionalKind)
    assert {
        kind for kind, status in statuses.items() if status == CertStatus.certified
    } == kinds
    assert all(
        status == CertStatus.unknown
        for kind, status in statuses.items()
        if kind not in kinds
    )


@pytest.mark.parametrize(
    "spf,pa", [("50+", None), (None, "0"), ("", " "), (None, None)]
)
def test_sun_requires_nonblank_field_values(spf, pa):
    report = FunctionalReport(
        source="report", spf=spf, pa=pa, item_name="SPF50+", effect_text="자외선 차단"
    )
    assert functional_kinds(report).get(FunctionalKind.sun_protection) == (
        CertStatus.certified
        if (spf or "").strip() or (pa or "").strip()
        else CertStatus.unknown
    )


def test_screening_xml_contract_and_different_agency():
    get = FakeGet(page("screening_query"))
    result = client(get).search_screenings("코스 알엑스")
    assert result.stopped is None and len(result.items) == 2
    for item in result.items:
        assert item.source == "screening"
        assert isinstance(item.effect_text, str) and item.effect_text.strip()
        assert "<PARAGRAPH" not in item.effect_text
        assert item.spf is None and item.pa is None and item.cancelled is None
        assert (
            functional_kinds(item).get(FunctionalKind.sun_protection)
            == CertStatus.unknown
        )
    url, params = next(iter(get.calls))
    assert url.endswith("/1471057/FtnltCosmSrngPrdlstInfoService05/getSrngPrdlstInq05")
    assert params.get("item_name") == "코스알엑스"


@pytest.mark.parametrize(
    "xml",
    [
        None,
        "<DOC><PARAGRAPH>앞<![CDATA[중간]]><B>뒤</B></PARAGRAPH><PARAGRAPH>둘째</PARAGRAPH></DOC>",
    ],
)
def test_screening_null_and_paragraph_text(xml):
    row = next(iter(body("screening_query").get("body").get("items")))
    row["EE_DOC_DATA"] = xml
    result = client(FakeGet(page("screening_query", [row], 1))).search_screenings(
        "품목"
    )
    item = next(iter(result.items))
    assert item.effect_text == (None if xml is None else "앞중간뒤\n둘째")


@pytest.mark.parametrize(
    "xml",
    [
        "<!DOCTYPE DOC><DOC/>",
        '<!ENTITY x "boom"><DOC/>',
        "<!doctype DOC><DOC/>",
        "<DOC>",
    ],
)
def test_untrusted_xml_rejected(xml):
    row = next(iter(body("screening_query").get("body").get("items")))
    row["EE_DOC_DATA"] = xml
    result = client(FakeGet(page("screening_query", [row], 1))).search_screenings(
        "품목"
    )
    assert result.stopped == "MFDS_XML_REJECTED" and result.items == []


@pytest.mark.parametrize(
    "status,code", [(403, "MFDS_KEY_NOT_REGISTERED"), (400, "MFDS_OPERATION_UNKNOWN")]
)
def test_gateway_error_shape_and_no_retry(status, code):
    response = body("error_key_not_registered")
    if status == 400:
        response.get("OpenAPI_ServiceResponse").get("cmmMsgHeader")["errMsg"] = (
            "NO_OPENAPI_SERVICE_ERROR"
        )
    get = FakeGet(MFDSHttpResponse(status, response))
    result = client(get).search_reports("품목")
    assert result.stopped == code and result.error.code == code
    assert result.error.provider_code == "30"
    assert result.error.provider_message
    assert result.error.http_status == status
    assert len(get.calls) == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 502])
@pytest.mark.parametrize("payload", ["success", "invalid"])
def test_http_status_precedes_body(status, payload):
    response = body("ingredient_query_no_match") if payload == "success" else None
    get = FakeGet(MFDSHttpResponse(status, response))
    result = client(get).search_ingredients("품목")
    assert result.stopped == f"MFDS_HTTP_{status}"
    assert len(get.calls) == 1


def test_nonzero_result_code_preserved():
    response = body("ingredient_query_no_match")
    # An account-level provider code (22: request limit exceeded) stops the run.
    response.get("header").update(resultCode="22", resultMsg="synthetic failure")
    result = client(FakeGet(MFDSHttpResponse(200, response))).search_reports("품목")
    assert result.stopped == "MFDS_API_ERROR"
    assert result.error.provider_code == "22"
    assert result.error.provider_message == "synthetic failure"


@pytest.mark.parametrize(
    "failure",
    [
        MFDSHttpResponse(503, None),
        ConnectionError(),
        TimeoutError(),
        httpx.ConnectError("offline"),
        httpx.ReadTimeout("offline"),
    ],
)
def test_only_transient_failures_retry(failure):
    get = FakeGet(failure, page("ingredient_query_no_match"))
    result = client(get).search_ingredients("품목")
    assert result.stopped is None and len(get.calls) == 2


def test_retries_bounded_and_count_toward_request_cap():
    get = FakeGet(*(MFDSHttpResponse(503, None) for _ in range(3)))
    result = client(get, max_requests=2).search_reports("품목")
    assert result.stopped == "MFDS_REQUEST_CAP" and len(get.calls) == 2
    get = FakeGet(*(MFDSHttpResponse(503, None) for _ in range(3)))
    result = client(get).search_reports("품목")
    assert result.stopped == "MFDS_HTTP_503" and len(get.calls) == 3


def test_request_cap_shared_across_three_operations():
    get = FakeGet(page("ingredient_query_no_match"), page("screening_query_no_match"))
    adapter = client(get, max_requests=2)
    assert adapter.search_ingredients("성분").stopped is None
    assert adapter.search_reports("품목").stopped is None
    assert adapter.search_screenings("품목").stopped == "MFDS_REQUEST_CAP"
    assert len(get.calls) == 2


def test_cap_required_and_zero_never_calls():
    with pytest.raises(TypeError):
        MFDSClient(get=FakeGet())
    get = FakeGet()
    assert (
        client(get, max_requests=0).search_reports("품목").stopped == "MFDS_REQUEST_CAP"
    )
    assert get.calls == []


def test_rate_interval_uses_injected_clock_and_sleep():
    now = 0.0
    waits = []

    def sleep(delay):
        nonlocal now
        waits.append(delay)
        now += delay

    get = FakeGet(
        MFDSHttpResponse(503, None),
        page("ingredient_query_no_match"),
        page("screening_query_no_match"),
    )
    adapter = client(get, min_interval_s=0.75, clock=lambda: now, sleep=sleep)
    assert adapter.search_ingredients("성분").stopped is None
    now += 0.25
    assert adapter.search_screenings("품목").stopped is None
    assert waits == [0.75, 0.5]


def test_missing_setting_becomes_result(monkeypatch):
    def missing(name):
        raise settings.MissingSetting(name)

    monkeypatch.setattr(settings, "require_setting", missing)
    get = FakeGet()
    result = client(get).search_reports("품목")
    assert result.stopped == "ENV_MISSING:DATA_GO_KR_SERVICE_KEY"
    assert get.calls == []


def test_secret_absent_from_results_errors_urls_and_logs(fake_setting, caplog):
    sentinel = fake_setting
    response = body("error_key_not_registered")
    response.get("OpenAPI_ServiceResponse").get("cmmMsgHeader")["returnAuthMsg"] = (
        sentinel + quote(sentinel, safe="")
    )
    get = FakeGet(MFDSHttpResponse(403, response))
    result = client(get).search_reports("품목")
    assert sentinel not in repr(result) + str(result.error) + caplog.text
    assert quote(sentinel, safe="") not in repr(result)
    assert all(sentinel not in url for url, _ in get.calls)
    row = next(iter(body("functional_report_query").get("body").get("items")))
    row["ITEM_NAME"] = sentinel
    result = client(FakeGet(page("functional_report_query", [row], 1))).search_reports(
        "품목"
    )
    assert sentinel not in repr(result)
    get = FakeGet(RuntimeError(sentinel))
    result = client(get).search_reports("품목")
    assert result.stopped == "MFDS_REQUEST_FAILED"
    assert sentinel not in repr(result) + str(result.error) + caplog.text
    assert result.error.__traceback__ is None
    assert result.error.__context__ is None


def test_sanitized_transport_failure_retries():
    get = FakeGet(
        MFDSError("MFDS_TRANSIENT_REQUEST_FAILED"),
        page("ingredient_query_no_match"),
    )
    result = client(get).search_ingredients("성분")
    assert result.stopped is None and len(get.calls) == 2


def test_missing_item_fields_and_cert_status_contract():
    assert IngredientStandard().name_ko is None
    result = client(FakeGet(page("functional_report_query", [{}], 1))).search_reports(
        "품목"
    )
    item = next(iter(result.items))
    assert item.item_name is None and item.effect_text is None
    assert set(functional_kinds(item).values()) == {CertStatus.unknown}
    assert {status.value for status in CertStatus} == {"certified", "unknown"}
    assert str(MFDSError("MFDS_REQUEST_CAP")) == "MFDS_REQUEST_CAP"


def coded(code, message="synthetic"):
    response = body("ingredient_query_no_match")
    response.get("header").update(resultCode=code, resultMsg=message)
    return MFDSHttpResponse(200, response)


@pytest.mark.parametrize(
    "operation", ["search_ingredients", "search_reports", "search_screenings"]
)
def test_result_code_03_is_no_data_not_an_error(operation):
    get = FakeGet(coded("03", "NODATA_ERROR"))
    result = getattr(client(get), operation)("품목")
    assert result.stopped is None and result.error is None and result.items == []
    assert len(get.calls) == 1  # no retry: "no data" is a complete answer


@pytest.mark.parametrize("code", ["20", "22", "30", "31", "32"])
def test_account_level_codes_stop_without_retry(code):
    get = FakeGet(coded(code, "synthetic account problem"))
    result = client(get, min_interval_s=0).search_reports("품목")
    assert result.stopped == "MFDS_API_ERROR"
    assert result.error.provider_code == code
    assert result.error.provider_message == "synthetic account problem"
    assert len(get.calls) == 1


@pytest.mark.parametrize("code", ["01", "02", "04", "05", "99"])
def test_other_provider_codes_retry_with_backoff_then_become_a_lookup_failure(code):
    waits = []
    get = FakeGet(*(coded(code, "System Error!!") for _ in range(4)))
    result = client(get, min_interval_s=0, sleep=waits.append).search_ingredients(
        "성분"
    )
    assert result.stopped == "MFDS_LOOKUP_FAILED"
    assert result.error.provider_code == code
    assert result.error.provider_message == "System Error!!"
    assert len(get.calls) == 4  # the first try and three retries
    assert waits == [1.0, 2.0, 4.0]


def test_transient_provider_code_recovers_on_a_retry():
    waits = []
    get = FakeGet(coded("01", "System Error!!"), page("ingredient_query_no_match"))
    result = client(get, min_interval_s=0, sleep=waits.append).search_ingredients(
        "성분"
    )
    assert result.stopped is None and len(get.calls) == 2 and waits == [1.0]


def test_provider_retries_count_toward_the_request_cap():
    get = FakeGet(*(coded("01") for _ in range(4)))
    result = client(get, min_interval_s=0, max_requests=2).search_reports("품목")
    assert result.stopped == "MFDS_REQUEST_CAP" and len(get.calls) == 2


def test_twenty_consecutive_lookup_failures_stop_the_run():
    get = FakeGet(*(coded("01") for _ in range(4 * 21)))
    adapter = client(get, min_interval_s=0, max_requests=1000)
    for _ in range(19):
        assert adapter.search_reports("품목").stopped == "MFDS_LOOKUP_FAILED"
    last = adapter.search_reports("품목")
    assert last.stopped == "MFDS_CONSECUTIVE_FAILURES"
    assert last.error.provider_code == "01"
    calls_before = len(get.calls)
    # After the stop, nothing more is sent.
    assert adapter.search_ingredients("성분").stopped == "MFDS_CONSECUTIVE_FAILURES"
    assert len(get.calls) == calls_before


def test_a_success_resets_the_consecutive_failure_count():
    responses = []
    for _ in range(19):
        responses += [coded("01")] * 4
    responses.append(page("ingredient_query_no_match"))
    for _ in range(19):
        responses += [coded("01")] * 4
    get = FakeGet(*responses)
    adapter = client(get, min_interval_s=0, max_requests=1000)
    for _ in range(19):
        assert adapter.search_reports("품목").stopped == "MFDS_LOOKUP_FAILED"
    assert adapter.search_ingredients("성분").stopped is None
    for _ in range(19):
        assert adapter.search_reports("품목").stopped == "MFDS_LOOKUP_FAILED"
