"""YouTube metadata collection with an injectable, synchronous HTTP boundary."""

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from math import isfinite
from typing import Any, NamedTuple

from pydantic import ValidationError

from beautyads.domain import Creative, Metrics, Source
from beautyads.sources.config import YouTubeChannel

_BASE_URL = "https://www.googleapis.com/youtube/v3"
_TIMEOUT_S = 30.0
_DURATION = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?")


class HttpResponse(NamedTuple):
    status: int
    body: Any | None


HttpGet = Callable[[str, Mapping[str, str], float], HttpResponse]


class YouTubeError(Exception):
    """A stable reason code without response messages or credential-bearing URLs."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def httpx_get(url: str, params: Mapping[str, str], timeout_s: float) -> HttpResponse:
    """The sole httpx boundary; never expose driver diagnostics to the collector."""
    import httpx

    try:
        response = httpx.get(url, params=params, timeout=timeout_s)
    except httpx.RequestError:
        raise YouTubeError("YOUTUBE_REQUEST_FAILED") from None
    try:
        body = response.json()
    except ValueError:
        body = None
    return HttpResponse(response.status_code, body)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(body: Mapping[str, Any]) -> list[Any]:
    items = body.get("items")
    return items if isinstance(items, list) else []


def _get(get: HttpGet, api_key: str, endpoint: str, **params: str) -> Mapping[str, Any]:
    response = get(f"{_BASE_URL}/{endpoint}", {"key": api_key, **params}, _TIMEOUT_S)
    if response.status != 200:
        error = _mapping(_mapping(response.body).get("error"))
        errors = error.get("errors")
        first = next(iter(errors), None) if isinstance(errors, list) else None
        reason = _mapping(first).get("reason")
        message = error.get("message")
        if (
            response.status == 400
            and isinstance(message, str)
            and "api key" in message.lower()
        ):
            raise YouTubeError("YOUTUBE_KEY_INVALID")
        if (
            response.status == 403
            and isinstance(reason, str)
            and reason.lower()
            in {"quotaexceeded", "dailylimitexceeded", "ratelimitexceeded"}
        ):
            raise YouTubeError("YOUTUBE_QUOTA")
        raise YouTubeError(f"YOUTUBE_HTTP_{response.status}")
    if not isinstance(response.body, Mapping):
        raise YouTubeError("YOUTUBE_INVALID_RESPONSE")
    return response.body


def find_uploads_playlist(get: HttpGet, api_key: str, channel: YouTubeChannel) -> str:
    body = _get(
        get, api_key, "channels", part="contentDetails", forHandle=channel.handle
    )
    item = next(iter(_items(body)), None)
    if item is None:
        raise YouTubeError("CHANNEL_NOT_FOUND")
    item = _mapping(item)
    if item.get("id") != channel.channel_id:
        raise YouTubeError("CHANNEL_MISMATCH")
    details = _mapping(item.get("contentDetails"))
    uploads = _mapping(details.get("relatedPlaylists")).get("uploads")
    if not isinstance(uploads, str) or not uploads:
        raise YouTubeError("YOUTUBE_INVALID_RESPONSE")
    return uploads


def list_upload_video_ids(
    get: HttpGet, api_key: str, playlist_id: str, *, max_items: int
) -> list[str]:
    ids: list[str] = []
    params = {
        "part": "contentDetails",
        "playlistId": playlist_id,
        "maxResults": "50",
    }
    seen_tokens: set[str] = set()
    while len(ids) < max_items:
        body = _get(get, api_key, "playlistItems", **params)
        for item in _items(body):
            video_id = _mapping(_mapping(item).get("contentDetails")).get("videoId")
            if isinstance(video_id, str) and video_id:
                ids.append(video_id)
        if len(ids) >= max_items:
            break
        token = body.get("nextPageToken")
        if not token:
            break
        if not isinstance(token, str) or token in seen_tokens:
            raise YouTubeError("YOUTUBE_INVALID_RESPONSE")
        seen_tokens.add(token)
        params["pageToken"] = token
    return ids[:max_items] if max_items > 0 else []


def parse_duration_seconds(iso: str | None) -> float | None:
    if not isinstance(iso, str):
        return None
    match = _DURATION.fullmatch(iso)
    if match is None or not any(part is not None for part in match.groups()):
        return None
    hours, minutes, seconds = (float(part or 0) for part in match.groups())
    duration = hours * 3600 + minutes * 60 + seconds
    return duration if isfinite(duration) else None


def _metric(stats: Mapping[str, Any], name: str) -> int | None:
    value = stats.get(name)
    return int(value) if value is not None else None


def _creative(
    item: Mapping[str, Any], collected_at: datetime, video_length_cut_s: float
) -> Creative:
    snippet = _mapping(item.get("snippet"))
    stats = _mapping(item.get("statistics"))
    duration = parse_duration_seconds(
        _mapping(item.get("contentDetails")).get("duration")
    )
    analyzable = None if duration is None else 0 < duration <= video_length_cut_s
    if snippet.get("liveBroadcastContent") in ("live", "upcoming"):
        analyzable = False
    video_id = item.get("id")
    return Creative(
        source=Source.youtube,
        source_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        title=snippet.get("title"),
        caption=snippet.get("description"),
        published_at=snippet.get("publishedAt"),
        language=snippet.get("defaultLanguage"),
        duration_s=duration,
        analyzable=analyzable,
        metrics=Metrics(
            view_count=_metric(stats, "viewCount"),
            like_count=_metric(stats, "likeCount"),
            comment_count=_metric(stats, "commentCount"),
        ),
        collected_at=collected_at,
    )


def fetch_videos(
    get: HttpGet,
    api_key: str,
    video_ids: Sequence[str],
    *,
    collected_at: datetime,
    video_length_cut_s: float,
) -> list[Creative]:
    creatives = []
    for offset in range(0, len(video_ids), 50):
        body = _get(
            get,
            api_key,
            "videos",
            part="snippet,statistics,contentDetails,status",
            id=",".join(video_ids[offset : offset + 50]),
        )
        try:
            creatives.extend(
                _creative(_mapping(item), collected_at, video_length_cut_s)
                for item in _items(body)
            )
        except (ValidationError, TypeError, ValueError, OverflowError):
            raise YouTubeError("YOUTUBE_INVALID_RESPONSE") from None
    return creatives


class CollectResult(NamedTuple):
    creatives: list[Creative]
    errors: dict[str, str]
    stopped: str | None


def collect_youtube(
    get: HttpGet,
    api_key: str,
    channels: Sequence[YouTubeChannel],
    *,
    max_items_per_channel: int,
    collected_at: datetime,
    video_length_cut_s: float,
) -> CollectResult:
    creatives: list[Creative] = []
    errors: dict[str, str] = {}
    for channel in channels:
        try:
            playlist_id = find_uploads_playlist(get, api_key, channel)
            ids = list_upload_video_ids(
                get, api_key, playlist_id, max_items=max_items_per_channel
            )
            creatives.extend(
                fetch_videos(
                    get,
                    api_key,
                    ids,
                    collected_at=collected_at,
                    video_length_cut_s=video_length_cut_s,
                )
            )
        except YouTubeError as error:
            errors[channel.handle] = error.code
            if error.code in {"YOUTUBE_KEY_INVALID", "YOUTUBE_QUOTA"}:
                return CollectResult(creatives, errors, error.code)
    return CollectResult(creatives, errors, None)
