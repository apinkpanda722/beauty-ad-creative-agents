"""Offline YouTube contracts using copies of recorded response bodies."""

import json
import sys
import traceback
from collections import deque
from copy import deepcopy
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from beautyads.domain import Source
from beautyads.sources.config import YouTubeChannel
from beautyads.sources.youtube import (
    HttpResponse,
    YouTubeError,
    collect_youtube,
    fetch_videos,
    find_uploads_playlist,
    httpx_get,
    list_upload_video_ids,
    parse_duration_seconds,
)

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
STAMP = datetime(2026, 11, 12, tzinfo=UTC)


def body(name):
    raw = json.loads((FIXTURES / f"youtube_{name}.json").read_text(encoding="utf-8"))
    return raw.get("response")


def channel(**changes):
    item = body("channels_forhandle").get("items")[0]
    return YouTubeChannel(
        **{
            "brand": "torriden",
            "handle": item.get("snippet").get("customUrl"),
            "channel_id": item.get("id"),
            "verified": "owner_watched_video",
            **changes,
        }
    )


def upload_ids():
    return [
        item.get("contentDetails").get("videoId")
        for item in body("playlistitems").get("items")
    ]


def last_page():
    result = body("playlistitems")
    result.pop("nextPageToken", None)
    return result


class FakeGet:
    def __init__(self, *responses):
        self.responses = deque(responses)
        self.calls = []

    def __call__(self, url, params, timeout_s):
        assert "/search" not in url
        assert not urlsplit(url).query
        assert timeout_s > 0
        self.calls.append((url, dict(params), timeout_s))
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def api_key():
    return uuid4().hex


def fetch(get, api_key, ids=None, *, cut=600):
    return fetch_videos(
        get,
        api_key,
        upload_ids() if ids is None else ids,
        collected_at=STAMP,
        video_length_cut_s=cut,
    )


def collect(get, api_key, channels):
    return collect_youtube(
        get,
        api_key,
        channels,
        max_items_per_channel=10,
        collected_at=STAMP,
        video_length_cut_s=600,
    )


def test_forhandle_resolves_and_checks_id(api_key):
    response = body("channels_forhandle")
    get = FakeGet(HttpResponse(200, response))
    result = find_uploads_playlist(get, api_key, channel())
    expected = response.get("items")[0].get("contentDetails").get("relatedPlaylists")
    assert result == expected.get("uploads")
    url, params, _ = get.calls[0]
    assert url.endswith("/channels")
    assert params == {
        "key": api_key,
        "part": "contentDetails",
        "forHandle": channel().handle,
    }


@pytest.mark.parametrize(
    ("fixture", "changes", "code"),
    [
        ("channels_forhandle_missing", {}, "CHANNEL_NOT_FOUND"),
        ("channels_forhandle", {"channel_id": "UC-other"}, "CHANNEL_MISMATCH"),
    ],
)
def test_channel_resolution_errors(api_key, fixture, changes, code):
    get = FakeGet(HttpResponse(200, body(fixture)))
    with pytest.raises(YouTubeError) as caught:
        find_uploads_playlist(get, api_key, channel(**changes))
    assert caught.value.code == code
    assert api_key not in str(caught.value)


def test_pagination_stops_when_token_key_is_absent(api_key):
    first = body("playlistitems")
    second = last_page()
    assert first.get("nextPageToken") and "nextPageToken" not in second
    get = FakeGet(HttpResponse(200, first), HttpResponse(200, second))
    ids = list_upload_video_ids(get, api_key, "uploads", max_items=100)
    assert ids == upload_ids() * 2
    assert len(get.calls) == 2
    for url, params, _ in get.calls:
        assert url.endswith("/playlistItems")
        assert params.get("part") == "contentDetails"
        assert params.get("playlistId") == "uploads"
        assert params.get("maxResults") == "50"
        assert params.get("key") == api_key
    assert "pageToken" not in get.calls[0][1]
    assert get.calls[1][1].get("pageToken") == first.get("nextPageToken")


@pytest.mark.parametrize("limit", [0, 1, 3, 4])
def test_upload_limit_stops_and_truncates(api_key, limit):
    get = FakeGet(
        HttpResponse(200, body("playlistitems")), HttpResponse(200, last_page())
    )
    assert (
        list_upload_video_ids(get, api_key, "uploads", max_items=limit)
        == (upload_ids() * 2)[:limit]
    )
    assert len(get.calls) == ceil(limit / len(upload_ids()))


def test_missing_playlist_items_is_empty(api_key):
    response = last_page()
    response.pop("items")
    get = FakeGet(HttpResponse(200, response))
    assert list_upload_video_ids(get, api_key, "uploads", max_items=10) == []


@pytest.mark.parametrize("count", [0, 1, 49, 50, 51, 100, 123])
def test_video_batches_have_at_most_fifty_ids(api_key, count):
    template = body("videos")
    items = []
    for index in range(count):
        item = deepcopy(template.get("items")[0])
        item["id"] = f"video-{index}"
        items.append(item)
    responses = []
    for offset in range(0, count, 50):
        response = deepcopy(template)
        response["items"] = items[offset : offset + 50]
        responses.append(HttpResponse(200, response))
    get = FakeGet(*responses)
    ids = [item.get("id") for item in items]
    creatives = fetch(get, api_key, ids)
    assert [item.source_id for item in creatives] == ids
    assert len(get.calls) == ceil(count / 50)
    requested = []
    for url, params, _ in get.calls:
        assert url.endswith("/videos")
        assert params.get("part") == "snippet,statistics,contentDetails,status"
        assert params.get("key") == api_key
        batch = params.get("id").split(",")
        assert 0 < len(batch) <= 50
        requested.extend(batch)
    assert requested == ids


def test_creative_metadata_and_integer_metrics(api_key):
    response = body("videos")
    creatives = fetch(FakeGet(HttpResponse(200, response)), api_key)
    for creative, raw in zip(creatives, response.get("items"), strict=True):
        snippet = raw.get("snippet")
        assert creative.source == Source.youtube
        assert creative.source_id == raw.get("id")
        assert creative.url == f"https://www.youtube.com/watch?v={raw.get('id')}"
        assert creative.title == snippet.get("title")
        assert creative.caption == snippet.get("description")
        assert creative.published_at == datetime.fromisoformat(
            snippet.get("publishedAt")
        )
        assert creative.language == snippet.get("defaultLanguage")
        assert creative.collected_at == STAMP
        assert creative.duration_s == parse_duration_seconds(
            raw.get("contentDetails").get("duration")
        )
        for field, key in [
            ("view_count", "viewCount"),
            ("like_count", "likeCount"),
            ("comment_count", "commentCount"),
        ]:
            value = raw.get("statistics").get(key)
            assert isinstance(value, str)
            assert getattr(creative.metrics, field) == int(value)
            assert type(getattr(creative.metrics, field)) is int


def test_hidden_statistics_remain_none_and_zero_is_preserved(api_key):
    response = body("videos")
    items = response.get("items")
    for key in ("likeCount", "commentCount"):
        items[0].get("statistics").pop(key)
    items[1].pop("statistics")
    for key in ("viewCount", "likeCount", "commentCount"):
        items[2].get("statistics")[key] = "0"
    creatives = fetch(FakeGet(HttpResponse(200, response)), api_key)
    assert creatives[0].metrics.like_count is None
    assert creatives[0].metrics.comment_count is None
    assert creatives[0].metrics.view_count is not None
    assert all(value is None for value in creatives[1].metrics.model_dump().values())
    assert all(value == 0 for value in creatives[2].metrics.model_dump().values())


def test_missing_optional_metadata(api_key):
    response = body("videos")
    for item in response.get("items"):
        item.pop("snippet")
        item.pop("contentDetails")
    creatives = fetch(FakeGet(HttpResponse(200, response)), api_key)
    for creative in creatives:
        assert creative.title is None
        assert creative.caption is None
        assert creative.language is None
        assert creative.published_at is None
        assert creative.duration_s is None
        assert creative.analyzable is None


@pytest.mark.parametrize(
    ("iso", "seconds"),
    [
        ("PT2M14S", 134.0),
        ("PT1H2M3S", 3723.0),
        ("PT45S", 45.0),
        ("PT0S", 0.0),
        ("PT1H", 3600.0),
        ("PT2M", 120.0),
        ("P0D", None),
        ("", None),
        (None, None),
        ("PT", None),
        ("PT-1S", None),
        ("PT1Sgarbage", None),
    ],
)
def test_duration_parser(iso, seconds):
    result = parse_duration_seconds(iso)
    assert result == seconds
    if seconds is not None:
        assert isinstance(result, float)


@pytest.mark.parametrize(
    ("live", "duration", "expected"),
    [
        ("live", "PT45S", False),
        ("upcoming", "PT45S", False),
        ("live", None, False),
        ("upcoming", "PT0S", False),
        ("none", "PT0S", False),
        ("none", "PT10M1S", False),
        ("none", "PT10M", True),
        ("none", "PT45S", True),
        (None, "PT45S", True),
        ("none", "P0D", None),
        ("none", None, None),
    ],
)
def test_all_analysis_eligibility_branches(api_key, live, duration, expected):
    response = body("videos")
    for item in response.get("items"):
        snippet = item.get("snippet")
        snippet.pop("liveBroadcastContent", None)
        if live is not None:
            snippet["liveBroadcastContent"] = live
        content = item.get("contentDetails")
        content.pop("duration", None)
        if duration is not None:
            content["duration"] = duration
    creatives = fetch(FakeGet(HttpResponse(200, response)), api_key)
    assert all(item.analyzable is expected for item in creatives)


def test_length_cut_is_an_explicit_input(api_key):
    response = body("videos")
    creatives = fetch(FakeGet(HttpResponse(200, response)), api_key, cut=1)
    assert all(item.analyzable is False for item in creatives)


def error_response(status, *, reason=None, message=None):
    response = body("error_bad_key")
    error = response.get("error")
    error["code"] = status
    if reason is not None:
        error.get("errors")[0]["reason"] = reason
    if message is not None:
        error["message"] = message
    return HttpResponse(status, response)


@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        (400, "badRequest", "YOUTUBE_KEY_INVALID"),
        (403, "quotaExceeded", "YOUTUBE_QUOTA"),
        (403, "DAILYLIMITEXCEEDED", "YOUTUBE_QUOTA"),
        (403, "RateLimitExceeded", "YOUTUBE_QUOTA"),
        (403, "forbidden", "YOUTUBE_HTTP_403"),
        (500, "quotaExceeded", "YOUTUBE_HTTP_500"),
        (401, "badRequest", "YOUTUBE_HTTP_401"),
    ],
)
def test_http_status_precedes_body_and_messages_are_sanitized(
    api_key, status, reason, expected
):
    message = f"API key {api_key} https://example.invalid/?key={api_key}"
    get = FakeGet(error_response(status, reason=reason, message=message))
    with pytest.raises(YouTubeError) as caught:
        find_uploads_playlist(get, api_key, channel())
    assert caught.value.code == expected
    assert str(caught.value) == expected
    assert api_key not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    "shape",
    [
        "none",
        "list",
        "string",
        "no_error",
        "null_error",
        "empty_errors",
        "null_errors",
        "bad_reason",
    ],
)
def test_malformed_error_bodies_are_defensive(api_key, shape):
    response = body("error_bad_key")
    error = response.get("error")
    error.pop("message")
    error.pop("status")
    if shape == "none":
        response = None
    elif shape == "list":
        response = [response]
    elif shape == "string":
        response = json.dumps(response)
    elif shape == "no_error":
        response.pop("error")
    elif shape == "null_error":
        response["error"] = None
    elif shape == "empty_errors":
        error["errors"] = []
    elif shape == "null_errors":
        error["errors"] = None
    else:
        error.get("errors")[0]["reason"] = None
    with pytest.raises(YouTubeError) as caught:
        find_uploads_playlist(FakeGet(HttpResponse(403, response)), api_key, channel())
    assert caught.value.code == "YOUTUBE_HTTP_403"


@pytest.mark.parametrize("stage", ["channel", "playlist", "videos"])
def test_one_channel_failure_does_not_stop_other_channels(api_key, stage):
    replies = []
    if stage != "channel":
        replies.append(HttpResponse(200, body("channels_forhandle")))
    if stage == "videos":
        replies.append(HttpResponse(200, last_page()))
    replies.extend(
        [
            error_response(404, message=api_key),
            HttpResponse(200, body("channels_forhandle")),
            HttpResponse(200, last_page()),
            HttpResponse(200, body("videos")),
        ]
    )
    get = FakeGet(*replies)
    failed = channel(handle="@failed")
    result = collect(get, api_key, [failed, channel()])
    assert result.errors == {failed.handle: "YOUTUBE_HTTP_404"}
    assert result.stopped is None
    assert [creative.source_id for creative in result.creatives] == upload_ids()
    assert not get.responses
    assert api_key not in repr(result.errors)
    assert api_key not in str(result.stopped)


@pytest.mark.parametrize("stage", ["channel", "playlist", "videos"])
@pytest.mark.parametrize(
    ("status", "reason", "code"),
    [
        (400, "badRequest", "YOUTUBE_KEY_INVALID"),
        (403, "quotaExceeded", "YOUTUBE_QUOTA"),
    ],
)
def test_key_and_quota_errors_stop_the_batch(api_key, stage, status, reason, code):
    replies = [
        HttpResponse(200, body("channels_forhandle")),
        HttpResponse(200, last_page()),
        HttpResponse(200, body("videos")),
    ]
    before_failure = {"channel": 0, "playlist": 1, "videos": 2}.get(stage)
    replies.extend(
        [
            HttpResponse(200, body("channels_forhandle")),
            HttpResponse(200, last_page()),
        ][:before_failure]
    )
    replies.append(error_response(status, reason=reason, message=f"API key {api_key}"))
    get = FakeGet(*replies)
    failed = channel(handle="@failed")
    result = collect(get, api_key, [channel(), failed, channel(handle="@never-called")])
    assert [item.source_id for item in result.creatives] == upload_ids()
    assert result.stopped == code
    assert result.errors == {failed.handle: code}
    assert len(get.calls) == 3 + before_failure + 1
    assert api_key not in repr(result.errors)
    assert api_key not in result.stopped


def test_empty_channels_make_no_calls(api_key):
    get = FakeGet()
    assert collect(get, api_key, []) == ([], {}, None)
    assert get.calls == []


@pytest.mark.parametrize("status", [200, 400, 503])
@pytest.mark.parametrize("json_body", [True, False])
def test_httpx_boundary_uses_params_and_handles_non_json(
    monkeypatch, api_key, status, json_body
):
    raw = body("videos") if status == 200 else body("error_bad_key")
    calls = []

    def decode():
        if not json_body:
            raise ValueError("not JSON")
        return raw

    def fake_get(url, *, params, timeout):
        calls.append((url, params, timeout))
        return SimpleNamespace(status_code=status, json=decode)

    monkeypatch.setitem(
        sys.modules, "httpx", SimpleNamespace(get=fake_get, RequestError=OSError)
    )
    url = "https://example.invalid/videos"
    params = {"key": api_key}
    assert httpx_get(url, params, 12.5) == HttpResponse(
        status, raw if json_body else None
    )
    assert calls == [(url, params, 12.5)]


def test_httpx_transport_failure_is_sanitized(monkeypatch, api_key):
    def fail(*args, **kwargs):
        raise OSError(f"https://example.invalid/?key={api_key}")

    monkeypatch.setitem(
        sys.modules, "httpx", SimpleNamespace(get=fail, RequestError=OSError)
    )
    with pytest.raises(YouTubeError) as caught:
        httpx_get("https://example.invalid/videos", {"key": api_key}, 10)
    assert api_key not in "".join(traceback.format_exception(caught.value))
