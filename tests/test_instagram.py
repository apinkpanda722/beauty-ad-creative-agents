"""Offline Instagram contracts derived from recorded Business Discovery bodies."""

import json
import sys
import traceback
from collections import deque
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from beautyads.domain import Source
from beautyads.sources.config import InstagramAccount
from beautyads.sources.instagram import (
    InstagramError,
    InstagramHttpResponse,
    business_discovery_fields,
    collect_instagram,
    fetch_account_page,
    instagram_httpx_get,
    media_to_creative,
    needs_refresh,
    parse_oe_expiry,
    parse_usage_pct,
    refresh_media_urls,
)
from beautyads.sources.youtube import CollectResult

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
STAMP = datetime(2026, 11, 12, tzinfo=UTC)
BASE_URL = "https://example.invalid/v21.0"


def body(name="business_discovery_with_media_url"):
    raw = json.loads((FIXTURES / f"instagram_{name}.json").read_text(encoding="utf-8"))
    return raw.get("response")


def media(response):
    return response.get("business_discovery").get("media")


def posts(response):
    return media(response).get("data")


def last_page(name="business_discovery_with_media_url"):
    response = body(name)
    media(response).get("paging").get("cursors").pop("after")
    return response


def account(**changes):
    discovery = body().get("business_discovery")
    return InstagramAccount(
        **{"brand": "torriden", "username": discovery.get("username"), **changes}
    )


def reply(response=None, *, status=200, headers=None):
    return InstagramHttpResponse(
        status, last_page() if response is None else response, headers or {}
    )


class FakeGet:
    def __init__(self, *responses):
        self.responses = deque(responses)
        self.calls = []

    def __call__(self, url, params, timeout_s):
        assert "?" not in url
        assert timeout_s > 0
        self.calls.append((url, dict(params), timeout_s))
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def token():
    return uuid4().hex


def collect(get, token, accounts=None, *, maximum=1000, **kwargs):
    return collect_instagram(
        get,
        token,
        "caller-id",
        [account()] if accounts is None else accounts,
        base_url=BASE_URL,
        max_posts_per_account=maximum,
        collected_at=STAMP,
        **kwargs,
    )


def refresh(get, token, wanted, **kwargs):
    return refresh_media_urls(
        get,
        token,
        "caller-id",
        account(),
        wanted,
        base_url=BASE_URL,
        now=STAMP,
        **kwargs,
    )


def test_original_posts_convert_without_persisting_media_urls():
    configured = account()
    for post in posts(body()):
        creative = media_to_creative(post, account=configured, collected_at=STAMP)
        assert creative.source == Source.instagram
        assert creative.source_id == str(post.get("id"))
        assert creative.brand == configured.brand
        assert creative.account == configured.username
        assert creative.url == post.get("permalink")
        assert creative.caption == post.get("caption")
        assert creative.published_at == datetime.fromisoformat(post.get("timestamp"))
        assert creative.published_at.utcoffset() is not None
        assert creative.collected_at == STAMP
        assert creative.duration_s is None
        assert creative.language is None
        assert creative.metrics.model_dump() == {
            "view_count": post.get("view_count"),
            "like_count": post.get("like_count"),
            "comment_count": post.get("comments_count"),
        }
        assert "media_url" not in creative.model_dump_json()
        assert post.get("media_url") not in creative.model_dump_json()


def test_optional_metrics_and_metadata_remain_none():
    post = deepcopy(posts(body())[0])
    for key in (
        "view_count",
        "like_count",
        "comments_count",
        "permalink",
        "timestamp",
        "caption",
    ):
        post.pop(key, None)
    creative = media_to_creative(post, account=account(), collected_at=STAMP)
    assert all(value is None for value in creative.metrics.model_dump().values())
    assert creative.url is None
    assert creative.published_at is None
    assert creative.caption is None
    for key in ("view_count", "like_count", "comments_count"):
        post[key] = 0
    creative = media_to_creative(post, account=account(), collected_at=STAMP)
    assert all(value == 0 for value in creative.metrics.model_dump().values())


@pytest.mark.parametrize("timestamp", [None, "invalid", "2026-11-12T00:00:00", 123])
def test_bad_or_naive_timestamp_is_none(timestamp):
    post = deepcopy(posts(body())[0])
    post["timestamp"] = timestamp
    assert (
        media_to_creative(post, account=account(), collected_at=STAMP).published_at
        is None
    )


@pytest.mark.parametrize(
    ("fixture", "kind", "expected"),
    [
        ("business_discovery_with_media_url", "VIDEO", True),
        ("business_discovery_without_media_url", "VIDEO", False),
        ("business_discovery_with_media_url", "CAROUSEL_ALBUM", False),
        ("business_discovery_with_media_url", "IMAGE", False),
        ("business_discovery_with_media_url", "future-type", None),
        ("business_discovery_with_media_url", None, None),
    ],
)
def test_analysis_eligibility_uses_type_and_url_key(fixture, kind, expected):
    post = deepcopy(
        next(post for post in posts(body(fixture)) if post.get("media_type") == "VIDEO")
    )
    if kind is None:
        post.pop("media_type")
    else:
        post["media_type"] = kind
    assert (
        media_to_creative(post, account=account(), collected_at=STAMP).analyzable
        is expected
    )


def test_fetch_page_metadata_and_request_fields(token):
    response = body()
    get = FakeGet(reply(response))
    page = fetch_account_page(
        get, token, "caller-id", account(), base_url=BASE_URL, limit=17
    )
    discovery = response.get("business_discovery")
    assert page.posts == posts(response)
    assert page.next_after == media(response).get("paging").get("cursors").get("after")
    assert page.followers_count == discovery.get("followers_count")
    assert page.media_count == discovery.get("media_count")
    assert page.usage_pct is None
    url, params, _ = get.calls[0]
    assert url == f"{BASE_URL}/caller-id"
    assert params == {
        "access_token": token,
        "fields": business_discovery_fields(account().username, limit=17),
    }
    assert business_discovery_fields(account().username, limit=17) == (
        f"business_discovery.username({account().username})"
        "{followers_count,media_count,media.limit(17){id,media_type,media_product_type,"
        "media_url,permalink,timestamp,caption,like_count,comments_count,view_count}}"
    )


def test_after_pagination_stops_at_absent_cursor_and_ignores_media_count(token):
    first, second = body(), last_page()
    for response in (first, second):
        response.get("business_discovery")["media_count"] = 1
    get = FakeGet(reply(first), reply(second))
    result = collect(get, token)
    assert isinstance(result, CollectResult)
    assert len(result.creatives) == len(posts(first)) + len(posts(second))
    assert result.errors == {}
    assert result.stopped is None
    assert len(get.calls) == 2
    cursor = media(first).get("paging").get("cursors").get("after")
    assert "media.limit(100){" in get.calls[0][1].get("fields")
    assert f"media.after({cursor}).limit(100){{" in get.calls[1][1].get("fields")
    assert "permalink" in get.calls[1][1].get("fields")


@pytest.mark.parametrize("maximum", [0, 1, 3, 5, 8])
def test_collection_limit_truncates_and_stops(token, maximum):
    first, second = body(), last_page()
    get = FakeGet(reply(first), reply(second))
    result = collect(get, token, maximum=maximum)
    expected = (posts(first) + posts(second))[:maximum]
    assert [item.source_id for item in result.creatives] == [
        post.get("id") for post in expected
    ]
    assert len(get.calls) == (
        0 if maximum == 0 else 1 if maximum <= len(posts(first)) else 2
    )


def test_full_hundred_item_page_and_different_account_identity(token):
    response = last_page()
    template = deepcopy(posts(response)[0])
    media(response)["data"] = [
        {**deepcopy(template), "id": str(index)} for index in range(100)
    ]
    accounts = [account(), account(brand="other-brand", username="other-account")]
    get = FakeGet(reply(response), reply(response))
    result = collect(get, token, accounts)
    assert len(result.creatives) == 200
    for index, configured in enumerate(accounts):
        batch = result.creatives[index * 100 : (index + 1) * 100]
        assert [item.source_id for item in batch] == [
            str(value) for value in range(100)
        ]
        assert all(
            item.brand == configured.brand and item.account == configured.username
            for item in batch
        )


def error_reply(code, token, *, status=400, headers=None):
    response = body("error_bad_token")
    response.get("error")["code"] = code
    response.get("error")["message"] = (
        f"{token} https://example.invalid/?access_token={token}"
    )
    return reply(response, status=status, headers=headers)


def test_invalid_account_isolated_using_original_error(token):
    get = FakeGet(reply(body("error_invalid_user"), status=400), reply())
    failed, good = account(username="missing-account"), account()
    result = collect(get, token, [failed, good])
    assert result.errors == {failed.username: "INSTAGRAM_ACCOUNT_NOT_FOUND"}
    assert result.stopped is None
    assert len(result.creatives) == len(posts(last_page()))
    assert len(get.calls) == 2


def test_original_token_error_stops_collection(token):
    get = FakeGet(reply(body("error_bad_token"), status=400))
    result = collect(get, token, [account(), account(username="never-called")])
    assert result.stopped == "INSTAGRAM_TOKEN_INVALID"
    assert result.errors == {account().username: result.stopped}
    assert len(get.calls) == 1


@pytest.mark.parametrize("code", [4, 17, 32, 613, 190])
def test_global_errors_stop_without_retry_and_preserve_partial_results(token, code):
    get = FakeGet(reply(), error_reply(code, token))
    failed = account(username="failed")
    result = collect(get, token, [account(), failed, account(username="never-called")])
    expected = "INSTAGRAM_TOKEN_INVALID" if code == 190 else "INSTAGRAM_RATE_LIMITED"
    assert result.stopped == expected
    assert result.errors == {failed.username: expected}
    assert len(result.creatives) == len(posts(last_page()))
    assert len(get.calls) == 2
    assert token not in repr(result)


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (400, 100, "INSTAGRAM_ERROR_100"),
        (500, 110, "INSTAGRAM_ERROR_110"),
        (503, None, "INSTAGRAM_ERROR_503"),
    ],
)
def test_other_errors_are_isolated_and_sanitized(token, status, code, expected):
    get = FakeGet(error_reply(code, token, status=status), reply())
    failed = account(username="failed")
    result = collect(get, token, [failed, account()])
    assert result.errors == {failed.username: expected}
    assert result.stopped is None
    assert result.creatives
    assert token not in repr(result)
    with pytest.raises(InstagramError) as caught:
        fetch_account_page(
            FakeGet(error_reply(code, token, status=status)),
            token,
            "caller",
            failed,
            base_url=BASE_URL,
        )
    assert caught.value.code == expected
    assert str(caught.value) == expected
    assert token not in repr(caught.value)
    assert token not in "".join(traceback.format_exception(caught.value))


def test_transport_error_isolated(token):
    get = FakeGet(InstagramError("INSTAGRAM_REQUEST_FAILED"), reply())
    result = collect(get, token, [account(username="failed"), account()])
    assert result.errors == {"failed": "INSTAGRAM_REQUEST_FAILED"}
    assert result.stopped is None
    assert result.creatives
    assert len(get.calls) == 2


@pytest.mark.parametrize(
    "shape",
    ["none", "list", "missing_error", "null_error", "missing_code", "unsafe_code"],
)
def test_error_body_may_be_missing_or_malformed(token, shape):
    response = body("error_bad_token")
    if shape == "none":
        response = None
    elif shape == "list":
        response = [response]
    elif shape == "missing_error":
        response.pop("error")
    elif shape == "null_error":
        response["error"] = None
    elif shape == "missing_code":
        response.get("error").pop("code")
    else:
        response.get("error")["code"] = token
    with pytest.raises(InstagramError, match="^INSTAGRAM_ERROR_502$"):
        fetch_account_page(
            FakeGet(InstagramHttpResponse(502, response, {})),
            token,
            "caller",
            account(),
            base_url=BASE_URL,
        )


@pytest.mark.parametrize(
    "headers", [{}, {"x-app-usage": "broken"}, {"x-app-usage": "null"}]
)
def test_missing_or_bad_usage_allows_next_page(token, headers):
    get = FakeGet(reply(body(), headers=headers), reply())
    result = collect(get, token)
    assert result.stopped is None
    assert len(get.calls) == 2


def test_usage_parser_uses_maximum_of_all_three_values():
    for key in ("call_count", "total_cputime", "total_time"):
        usage = dict.fromkeys(("call_count", "total_cputime", "total_time"), 2)
        usage[key] = 83.5
        assert parse_usage_pct({"x-app-usage": json.dumps(usage)}) == 83.5


@pytest.mark.parametrize(
    "raw", ["bad", "[]", "null", "{}", '{"call_count": "invalid"}']
)
def test_usage_parser_tolerates_bad_header(raw):
    assert parse_usage_pct({"x-app-usage": raw}) is None
    assert parse_usage_pct({}) is None


@pytest.mark.parametrize("threshold", [80.0, 40.0])
def test_usage_stop_keeps_current_page_and_skips_next_account(token, threshold):
    headers = {
        "x-app-usage": json.dumps(
            {"call_count": threshold, "total_time": 1, "total_cputime": 1}
        )
    }
    get = FakeGet(reply(body(), headers=headers))
    result = collect(
        get,
        token,
        [account(), account(username="never-called")],
        usage_stop_pct=threshold,
    )
    assert result.stopped == "INSTAGRAM_USAGE_HIGH"
    assert len(result.creatives) == len(posts(body()))
    assert result.errors == {}
    assert len(get.calls) == 1


def test_usage_on_failed_request_also_stops_batch(token):
    get = FakeGet(
        error_reply(100, token, headers={"x-app-usage": '{"call_count": 80}'})
    )
    result = collect(get, token, [account(), account(username="never-called")])
    assert result.stopped == "INSTAGRAM_USAGE_HIGH"
    assert result.errors == {account().username: "INSTAGRAM_ERROR_100"}
    assert len(get.calls) == 1


def oe_url(expiry):
    return f"https://example.invalid/v.mp4?oe={int(expiry.timestamp()):X}&oh=x"


def test_parse_oe_expiry_is_aware():
    expiry = STAMP + timedelta(days=2)
    assert parse_oe_expiry(oe_url(expiry)) == expiry


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(-1, True), (21599, True), (21600, False), (21601, False), (86400, False)],
)
def test_refresh_expiry_boundaries(seconds, expected):
    assert needs_refresh(oe_url(STAMP + timedelta(seconds=seconds)), STAMP) is expected


@pytest.mark.parametrize(
    "url",
    [
        None,
        "https://example.invalid/v.mp4",
        "https://example.invalid/v.mp4?oe=not-hex",
        "https://example.invalid/v.mp4?oe=",
        "https://example.invalid/v.mp4?oe=FFFFFFFFFFFFFFFFFFFF",
        "https://[",
    ],
)
def test_unknown_expiry_refreshes_safely(url):
    if url is not None:
        assert parse_oe_expiry(url) is None
    assert needs_refresh(url, STAMP) is True


def test_custom_refresh_window():
    assert (
        needs_refresh(oe_url(STAMP + timedelta(hours=1)), STAMP, min_remaining_s=1800)
        is False
    )


def test_refresh_finds_videos_gone_and_missing_without_returning_images(token):
    first, second = body(), last_page("business_discovery_without_media_url")
    video = next(post for post in posts(first) if post.get("media_type") == "VIDEO")
    gone = next(post for post in posts(second) if post.get("media_type") == "VIDEO")
    image = next(
        post for post in posts(first) if post.get("media_type") == "CAROUSEL_ALBUM"
    )
    wanted = {video.get("id"), gone.get("id"), image.get("id"), "not-found"}
    get = FakeGet(reply(first), reply(second))
    result = refresh(get, token, wanted)
    assert result.urls == {video.get("id"): video.get("media_url")}
    assert result.gone == {gone.get("id")}
    assert result.missing == {"not-found"}
    assert result.stopped is None
    assert len(get.calls) == 2
    assert ".after(" in get.calls[1][1].get("fields")


def test_refresh_stops_early_when_all_ids_found(token):
    response = body()
    video = next(post for post in posts(response) if post.get("media_type") == "VIDEO")
    get = FakeGet(reply(response))
    result = refresh(get, token, [video.get("id")])
    assert result.urls == {video.get("id"): video.get("media_url")}
    assert result.missing == result.gone == set()
    assert result.stopped is None
    assert len(get.calls) == 1


@pytest.mark.parametrize("maximum", [0, 1, 2])
def test_refresh_respects_max_pages(token, maximum):
    get = FakeGet(*(reply(body()) for _ in range(maximum)))
    result = refresh(get, token, ["not-found"], max_pages=maximum)
    assert result.missing == {"not-found"}
    assert result.urls == {}
    assert result.gone == set()
    assert len(get.calls) == maximum


def test_empty_inputs_make_no_requests(token):
    get = FakeGet()
    assert collect(get, token, []) == ([], {}, None)
    assert refresh(get, token, []) == ({}, set(), set(), None)
    assert get.calls == []


def test_refresh_usage_stop_keeps_matches(token):
    response = body()
    video = next(post for post in posts(response) if post.get("media_type") == "VIDEO")
    get = FakeGet(reply(response, headers={"x-app-usage": '{"total_time": 80}'}))
    result = refresh(get, token, [video.get("id"), "missing"])
    assert result.urls == {video.get("id"): video.get("media_url")}
    assert result.missing == {"missing"}
    assert result.stopped == "INSTAGRAM_USAGE_HIGH"
    assert len(get.calls) == 1


def test_refresh_scan_log_records_usage_pages_and_stop_point(token):
    usage = '{"call_count": 3, "total_cputime": 2, "total_time": 81}'
    get = FakeGet(
        reply(body()),
        reply(
            last_page("business_discovery_without_media_url"),
            headers={"x-app-usage": usage},
        ),
    )
    log: list = []
    result = refresh(get, token, ["not-found"], scan_log=log)
    assert result.stopped == "INSTAGRAM_USAGE_HIGH"
    assert len(log) == 1
    entry = log[0]
    assert entry["account"] == account().username
    assert entry["pages"] == 2
    assert entry["remaining"] == 1
    assert entry["stopped"] == "INSTAGRAM_USAGE_HIGH"
    assert entry["usage"] == {"call_count": 3, "total_cputime": 2, "total_time": 81}


def test_refresh_scan_log_is_optional_and_records_clean_scans(token):
    video = next(post for post in posts(body()) if post.get("media_type") == "VIDEO")
    log: list = []
    refresh(FakeGet(reply(body())), token, [video.get("id")], scan_log=log)
    assert [(e["pages"], e["remaining"], e["stopped"]) for e in log] == [(1, 0, None)]
    refresh(FakeGet(reply(body())), token, [video.get("id")])


@pytest.mark.parametrize("code", [110, 190, 4, 17, 32, 613, 100])
def test_refresh_returns_sanitized_error_without_retry(token, code):
    get = FakeGet(error_reply(code, token))
    result = refresh(get, token, ["missing"])
    expected = {
        110: "INSTAGRAM_ACCOUNT_NOT_FOUND",
        190: "INSTAGRAM_TOKEN_INVALID",
        100: "INSTAGRAM_ERROR_100",
    }.get(code, "INSTAGRAM_RATE_LIMITED")
    assert result.stopped == expected
    assert result.missing == {"missing"}
    assert result.urls == {}
    assert token not in repr(result)
    assert len(get.calls) == 1


@pytest.mark.parametrize("json_body", [True, False])
@pytest.mark.parametrize("status", [200, 400, 503])
def test_httpx_boundary_normalizes_headers_and_handles_non_json(
    monkeypatch, token, json_body, status
):
    response = body() if status == 200 else body("error_bad_token")
    calls = []

    def decode():
        if not json_body:
            raise ValueError("not JSON")
        return response

    def fake_get(url, *, params, timeout):
        calls.append((url, params, timeout))
        return SimpleNamespace(
            status_code=status,
            json=decode,
            headers={"X-App-Usage": '{"call_count": 2}'},
        )

    monkeypatch.setitem(
        sys.modules, "httpx", SimpleNamespace(get=fake_get, RequestError=OSError)
    )
    params = {"access_token": token}
    result = instagram_httpx_get(BASE_URL, params, 12.5)
    assert result == InstagramHttpResponse(
        status, response if json_body else None, {"x-app-usage": '{"call_count": 2}'}
    )
    assert calls == [(BASE_URL, params, 12.5)]


def test_httpx_transport_failure_never_exposes_query(monkeypatch, token):
    def fail(*args, **kwargs):
        raise OSError(f"https://example.invalid/?access_token={token}")

    monkeypatch.setitem(
        sys.modules, "httpx", SimpleNamespace(get=fail, RequestError=OSError)
    )
    with pytest.raises(InstagramError) as caught:
        instagram_httpx_get(BASE_URL, {"access_token": token}, 10)
    assert caught.value.code == "INSTAGRAM_REQUEST_FAILED"
    assert token not in repr(caught.value)
    assert token not in "".join(traceback.format_exception(caught.value))
