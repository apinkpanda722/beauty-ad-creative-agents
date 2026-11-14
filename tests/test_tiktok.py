"""Contract-derived TikTok responses and injected transports only; no network."""

import copy
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from beautyads.sources.config import (
    Retailers,
    TikTokBrand,
    TikTokConfig,
    load_retailers,
)
from beautyads.sources.tiktok import (
    QUERY_FIELDS,
    TIKTOK_BASE_URL,
    TikTokError,
    TikTokHttpResponse,
    TokenProvider,
    ad_to_creative,
    build_query_body,
    classify_executor,
    collect_tiktok,
    refresh_tiktok_video_urls,
    tiktok_httpx_post,
)

FIXTURES = Path(__file__).parent / "fixtures/contracts"
NOW = datetime(2026, 11, 13, 12, tzinfo=UTC)


def response(name="tiktok_ad_query.json"):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["response"]


def page(name="tiktok_ad_query.json", *, last=False):
    body = response(name)
    if last:
        body["data"]["has_more"] = False
    return TikTokHttpResponse(200, body)


class FakePost:
    def __init__(self, replies=()):
        self.replies = iter(replies)
        self.calls = []
        self.token_calls = 0
        self.secret = uuid4().hex
        self.key = uuid4().hex
        self.access_token = response("tiktok_oauth_token.json").get("access_token")

    def __call__(self, url, params, json_body, form_body, timeout_s):
        if url.endswith("/oauth/token/"):
            self.token_calls += 1
            assert json_body is None
            assert form_body == {
                "client_key": self.key,
                "client_secret": self.secret,
                "grant_type": "client_credentials",
            }
            return TikTokHttpResponse(200, response("tiktok_oauth_token.json"))
        # Never retain bearer credentials in the test's call history.
        self.calls.append(
            (
                url,
                {k: v for k, v in params.items() if k != "Authorization"},
                copy.deepcopy(json_body),
                form_body,
                timeout_s,
            )
        )
        return next(self.replies)


def provider(post, now=lambda: NOW):
    return TokenProvider(
        post,
        base_url=TIKTOK_BASE_URL,
        client_key=post.key,
        client_secret=post.secret,
        now=now,
    )


def config(*names):
    return TikTokConfig(
        countries=["DE", "FR"],
        lookback_days=330,
        search_type="exact_phrase",
        brands=[TikTokBrand(brand=n, search_term=n) for n in names or ("mixsoon",)],
    )


def retailers():
    return load_retailers(Path(__file__).resolve().parents[1] / "config/retailers.yaml")


def collect(post, *, cfg=None, max_pages=5, brands=None, sleep=lambda _s: None):
    return collect_tiktok(
        post,
        provider(post),
        cfg or config(),
        retailers(),
        base_url=TIKTOK_BASE_URL,
        max_pages=max_pages,
        collected_at=NOW,
        brands=brands,
        sleep=sleep,
    )


def test_token_cache_refresh_and_invalidate():
    post = FakePost()
    clock = [NOW]
    token = provider(post, lambda: clock[0])
    assert token.token() == post.access_token
    clock[0] += timedelta(seconds=7139)
    assert token.token() == post.access_token
    assert post.token_calls == 1
    clock[0] += timedelta(seconds=1)
    assert token.token() == post.access_token
    assert post.token_calls == 2
    token.invalidate()
    assert token.token() == post.access_token
    assert post.token_calls == 3
    assert post.secret not in repr(token)
    assert post.key not in repr(token)
    assert post.access_token not in repr(token)


@pytest.mark.parametrize(
    "status,body",
    [
        (401, response("tiktok_error_bad_token.json")),
        (500, None),
        (200, {}),
        (200, {"expires_in": 7200}),
    ],
)
def test_token_errors_are_safe(status, body):
    post = FakePost()
    token = provider(post)
    token._post = lambda *args: TikTokHttpResponse(status, body)
    with pytest.raises(TikTokError) as caught:
        token.token()
    assert post.secret not in str(caught.value)
    assert post.secret not in repr(caught.value)
    assert post.access_token not in str(caught.value)


def test_build_query_body():
    cfg = config()
    body = build_query_body(cfg.brands[0], cfg, today=NOW.date(), search_id=None)
    assert body == {
        "filters": {
            "ad_published_date_range": {
                "min": (NOW.date() - timedelta(days=330)).strftime("%Y%m%d"),
                "max": "20261112",
            },
            "country_code_list": ["DE", "FR"],
        },
        "search_term": "mixsoon",
        "search_type": "exact_phrase",
        "max_count": 10,
    }
    assert all(
        isinstance(v, str) for v in body["filters"]["ad_published_date_range"].values()
    )
    assert isinstance(body["filters"]["country_code_list"], list)
    assert body["max_count"] <= 10
    assert (
        build_query_body(
            cfg.brands[0], cfg, today=date(2026, 1, 1), search_id="cursor"
        )["search_id"]
        == "cursor"
    )
    changed = cfg.model_copy(update={"search_type": "invalid"})
    assert (
        build_query_body(cfg.brands[0], changed, today=NOW.date(), search_id=None)[
            "search_type"
        ]
        == "invalid"
    )


def test_two_pages_deduplicate_and_finish_with_search_id():
    first = page()
    last = page(last=True)
    last.body["data"]["ads"] = last.body["data"]["ads"][:9]
    assert last.body["data"]["search_id"]
    post = FakePost([first, last])
    result = collect(post)
    assert len(post.calls) == 2
    assert len(result.creatives) == 10
    assert len({c.source_id for c in result.creatives}) == 10
    assert post.calls[1][2]["search_id"] == first.body["data"]["search_id"]
    assert post.calls[0][1] == {"fields": QUERY_FIELDS}
    assert post.calls[0][0] == TIKTOK_BASE_URL + "/v2/research/adlib/ad/query/"
    assert not result.errors and result.stopped is None


def test_real_contract_pagination():
    pages = [
        page(),
        page("tiktok_ad_query_mixsoon_page2.json"),
        page("tiktok_ad_query_mixsoon_last.json"),
    ]
    expected = {str(item["ad"]["id"]) for p in pages for item in p.body["data"]["ads"]}
    post = FakePost(pages)
    result = collect(post)
    assert {c.source_id for c in result.creatives} == expected
    assert len(result.creatives) == len(expected)
    assert len(post.calls) == 3
    assert post.calls[2][2]["search_id"] == pages[1].body["data"]["search_id"]


def test_max_pages_and_brand_filter():
    post = FakePost([page()])
    result = collect(
        post, cfg=config("dalba", "mixsoon"), max_pages=1, brands={"mixsoon"}
    )
    assert len(post.calls) == 1
    assert all(c.brand == "mixsoon" for c in result.creatives)
    empty = FakePost()
    assert not collect(empty, max_pages=0).creatives
    assert empty.token_calls == 0
    assert not collect(empty, brands=set()).creatives


def test_bad_token_is_reissued_once():
    bad = TikTokHttpResponse(401, response("tiktok_error_bad_token.json"))
    post = FakePost([bad, page(last=True), page(last=True)])
    result = collect(post, cfg=config("mixsoon", "dalba"))
    assert post.token_calls == 2 and len(post.calls) == 3
    assert result.stopped is None and not result.errors
    failing = FakePost([bad, bad])
    result = collect(failing, cfg=config("mixsoon", "dalba"))
    assert result.stopped == "TIKTOK_TOKEN_INVALID"
    assert failing.token_calls == 2 and len(failing.calls) == 2


@pytest.mark.parametrize(
    "filename",
    [
        "tiktok_error_date_as_number.json",
        "tiktok_error_missing_filter.json",
        "tiktok_error_date_max_not_before_today.json",
    ],
)
def test_invalid_params_stop_all_brands(filename):
    post = FakePost([TikTokHttpResponse(400, response(filename))])
    result = collect(post, cfg=config("mixsoon", "dalba"))
    assert result.stopped == "TIKTOK_INVALID_PARAMS"
    assert result.errors == {"mixsoon": "TIKTOK_INVALID_PARAMS"}
    assert len(post.calls) == 1


@pytest.mark.parametrize("status", [429, 403])
def test_http_failure_isolated_without_retry(status):
    body = response("tiktok_error_bad_token.json")
    body["error"].update(code="internal_error", message=uuid4().hex)
    post = FakePost([TikTokHttpResponse(status, body), page(last=True)])
    result = collect(post, cfg=config("mixsoon", "dalba"))
    assert result.errors == {"mixsoon": f"TIKTOK_HTTP_{status}"}
    assert result.stopped is None
    assert result.creatives and all(c.brand == "dalba" for c in result.creatives)
    assert len(post.calls) == 2


@pytest.mark.parametrize(
    "body",
    [None, {}, {"error": {"code": "not_ok"}}, {"error": {"code": "ok"}, "data": {}}],
)
def test_200_requires_ok_and_valid_data(body):
    result = collect(FakePost([TikTokHttpResponse(200, body)]))
    assert result.errors == {"mixsoon": "TIKTOK_INVALID_RESPONSE"}
    assert result.stopped is None


def test_ad_conversion_contract_and_no_signed_urls():
    items = (
        response()["data"]["ads"]
        + response("tiktok_ad_query_dalba_last.json")["data"]["ads"]
    )
    for item in items:
        ad, advertiser = item["ad"], item["advertiser"]
        creative = ad_to_creative(
            item, brand="queried_brand", collected_at=NOW, executor="unknown"
        )
        assert creative.source == "tiktok"
        assert creative.source_id == str(ad["id"])
        assert creative.account == str(advertiser["business_id"])
        assert creative.published_at == datetime.strptime(
            ad["first_shown_date"], "%Y%m%d"
        ).replace(tzinfo=UTC)
        assert creative.brand == "queried_brand"
        assert creative.analyzable is any("url" in v for v in ad.get("videos", []))
        assert all(v is None for v in creative.metrics.model_dump().values())
        assert all(
            getattr(creative, key) is None
            for key in ("url", "title", "caption", "duration_s", "language")
        )
        assert creative.attributes == {
            "first_shown_date": ad.get("first_shown_date"),
            "last_shown_date": ad.get("last_shown_date"),
            "status": ad.get("status"),
            "reach_unique_users_seen": ad.get("reach", {}).get("unique_users_seen"),
            "advertiser_business_id": advertiser.get("business_id"),
            "advertiser_business_name": advertiser.get("business_name"),
            "advertiser_paid_for_by": advertiser.get("paid_for_by"),
            "executor": "unknown",
            "has_image_urls": bool(ad.get("image_urls")),
        }
        for video in ad.get("videos", []):
            for key in ("url", "cover_image_url"):
                if video.get(key):
                    assert video[key] not in creative.model_dump_json()
        for url in ad.get("image_urls", []):
            assert url not in creative.model_dump_json()
        if "image_urls" not in ad:
            assert creative.attributes["has_image_urls"] is False
    no_video = copy.deepcopy(items[0])
    no_video["ad"]["videos"] = [{"cover_image_url": "transient-cover-sentinel"}]
    creative = ad_to_creative(
        no_video, brand="mixsoon", collected_at=NOW, executor="retailer"
    )
    assert creative.analyzable is False
    assert "transient-cover-sentinel" not in creative.model_dump_json()


def test_executor_names_are_from_original_contracts():
    names = [
        item["advertiser"].get("business_name")
        for name in (
            "tiktok_ad_query.json",
            "tiktok_ad_query_mixsoon_page2.json",
            "tiktok_ad_query_mixsoon_last.json",
            "tiktok_ad_query_dalba_last.json",
        )
        for item in response(name)["data"]["ads"]
    ]
    cases = {
        "Mixsoon Limited": "brand_direct",
        "Etos B.V.": "retailer",
        "Cosibella": "retailer",
        "Pilulka Lékárny a.s.": "retailer",
        "PHARMACONTINENTE - SAÚDE E HIGIENE, S.A.": "retailer",
        "JJ Media Ltd": "unknown",
        "": "unknown",
    }
    for name, expected in cases.items():
        assert name in names
        original = next(n for n in names if n == name)
        assert (
            classify_executor(
                {"business_name": original},
                brand_names=["mixsoon"],
                retailers=retailers(),
            )
            == expected
        )
    numeric = [n for n in names if isinstance(n, str) and n.isdigit()]
    assert numeric
    for name in numeric + [None]:
        assert (
            classify_executor(
                {"business_name": name}, brand_names=["mixsoon"], retailers=retailers()
            )
            == "unknown"
        )


@pytest.mark.parametrize(
    "name,brands,shops,expected",
    [
        ("BEAUTY, OF-JOSEON Limited", ["beauty of joseon"], [], "brand_direct"),
        ("beauty extra of joseon", ["beauty of joseon"], [], "unknown"),
        ("Mixsoon Limited", ["mix"], [], "unknown"),
        ("PILULKA LÉKÁRNY a.s.", ["pilulka lékárny"], [], "brand_direct"),
        ("ÉTOS B.V.", [], ["étos"], "retailer"),
        ("Etos Mixsoon Limited", ["mixsoon"], ["etos"], "brand_direct"),
        ("12345", ["12345"], ["12345"], "unknown"),
    ],
)
def test_executor_token_normalization(name, brands, shops, expected):
    assert (
        classify_executor(
            {"business_name": name},
            brand_names=brands,
            retailers=Retailers(names=frozenset(shops)),
        )
        == expected
    )


def refresh(post, wanted, *, max_pages=5, sleep=lambda _s: None):
    cfg = config()
    return refresh_tiktok_video_urls(
        post,
        provider(post),
        cfg,
        cfg.brands[0],
        wanted,
        base_url=TIKTOK_BASE_URL,
        today=NOW.date(),
        max_pages=max_pages,
        sleep=sleep,
    )


def test_refresh_urls_gone_missing_and_early_exit():
    first = page(last=True)
    items = first.body["data"]["ads"]
    found, gone = (str(item["ad"]["id"]) for item in items[:2])
    url = items[0]["ad"]["videos"][0]["url"]
    items[1]["ad"].pop("videos", None)
    post = FakePost([first])
    result = refresh(post, [found, gone, "absent"])
    assert result.urls == {found: url}
    assert result.gone == {gone} and result.missing == {"absent"}
    assert result.stopped is None and len(post.calls) == 1
    first.body["data"]["has_more"] = True
    early = FakePost([first])
    assert refresh(early, [found]).missing == set()
    assert len(early.calls) == 1
    empty = FakePost()
    assert refresh(empty, []).missing == set()
    assert empty.token_calls == 0


def test_refresh_pagination_max_pages_and_stop():
    first, last = page(), page("tiktok_ad_query_mixsoon_last.json")
    wanted = str(last.body["data"]["ads"][0]["ad"]["id"])
    assert wanted not in {str(i["ad"]["id"]) for i in first.body["data"]["ads"]}
    short = FakePost([first])
    assert refresh(short, [wanted], max_pages=1).missing == {wanted}
    full = FakePost([first, last])
    assert wanted in refresh(full, [wanted], max_pages=2).urls
    assert full.calls[1][2]["search_id"] == first.body["data"]["search_id"]
    bad = TikTokHttpResponse(401, response("tiktok_error_bad_token.json"))
    stopped = refresh(FakePost([bad, bad]), [wanted])
    assert stopped.stopped == "TIKTOK_TOKEN_INVALID" and stopped.missing == {wanted}


def test_httpx_boundary_headers_form_and_safe_failures(monkeypatch):
    access_token, secret = uuid4().hex, uuid4().hex
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json=response())

    monkeypatch.setattr(httpx, "post", fake_post)
    tiktok_httpx_post(
        TIKTOK_BASE_URL,
        {"fields": QUERY_FIELDS, "Authorization": f"Bearer {access_token}"},
        {},
        None,
        30,
    )
    kwargs = calls.pop()[1]
    assert kwargs["params"] == {"fields": QUERY_FIELDS}
    assert kwargs["headers"] == {"Authorization": f"Bearer {access_token}"}
    tiktok_httpx_post(TIKTOK_BASE_URL, {}, None, {"client_secret": secret}, 30)
    kwargs = calls.pop()[1]
    assert kwargs["data"] == {"client_secret": secret} and kwargs.get("json") is None

    def failing(*args, **kwargs):
        raise httpx.ConnectError(secret + access_token)

    monkeypatch.setattr(httpx, "post", failing)
    with pytest.raises(TikTokError, match="^TIKTOK_REQUEST_FAILED$") as caught:
        tiktok_httpx_post(TIKTOK_BASE_URL, {}, None, None, 30)
    assert secret not in repr(caught.value) and access_token not in repr(caught.value)


def test_provider_messages_do_not_escape_results():
    post = FakePost()
    body = response("tiktok_error_bad_token.json")
    body["error"]["message"] = post.secret + post.access_token
    post.replies = iter([TikTokHttpResponse(500, body)] * 4)
    result = collect(post)
    assert post.secret not in repr(result) and post.access_token not in repr(result)


def _failure(status):
    body = response("tiktok_error_bad_token.json")
    body["error"].update(code="internal_error", message=uuid4().hex)
    return TikTokHttpResponse(status, body)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_server_errors_retry_with_backoff_then_succeed(status):
    sleeps = []
    post = FakePost([_failure(status)] * 3 + [page(last=True)])
    result = collect(post, sleep=sleeps.append)
    assert result.errors == {} and result.creatives
    assert len(post.calls) == 4
    assert sleeps == [2.0, 5.0, 15.0]


def test_persistent_server_error_fails_only_that_brand_after_three_retries():
    sleeps = []
    post = FakePost([_failure(500)] * 4 + [page(last=True)])
    result = collect(post, cfg=config("mixsoon", "dalba"), sleep=sleeps.append)
    assert result.errors == {"mixsoon": "TIKTOK_HTTP_500"}
    assert result.stopped is None
    assert result.creatives and all(c.brand == "dalba" for c in result.creatives)
    assert len(post.calls) == 5 and sleeps == [2.0, 5.0, 15.0]


def test_refresh_retries_server_errors_and_reports_the_final_code():
    sleeps = []
    post = FakePost([_failure(502)] * 4)
    result = refresh(post, ["absent"], sleep=sleeps.append)
    assert result.stopped == "TIKTOK_HTTP_502" and result.missing == {"absent"}
    assert len(post.calls) == 4 and sleeps == [2.0, 5.0, 15.0]
    recovered = FakePost([_failure(503), page(last=True)])
    ok = refresh(recovered, ["absent"], sleep=lambda _s: None)
    assert ok.stopped is None and ok.missing == {"absent"}


def test_absence_is_only_reported_after_a_scan_that_ended_with_has_more_false():
    # the result set can differ between runs, so a capped scan proves nothing
    capped = FakePost([page()])
    result = refresh(capped, ["absent"], max_pages=1)
    assert result.stopped == "TIKTOK_PAGES_INCOMPLETE" and result.missing == {"absent"}
    complete = FakePost([page(last=True)])
    done = refresh(complete, ["absent"], max_pages=1)
    assert done.stopped is None and done.missing == {"absent"}
    # has_more false exactly on the last allowed page still counts as complete
    both = FakePost([page(), page("tiktok_ad_query_mixsoon_last.json")])
    exact = refresh(both, ["absent"], max_pages=2)
    assert exact.stopped is None and exact.missing == {"absent"}
