"""Business Discovery collection and transient video URL refresh via injected HTTP."""

import json
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import UTC, datetime
from math import isfinite
from typing import Any, NamedTuple
from urllib.parse import parse_qs, urlsplit

from pydantic import ValidationError

from beautyads.domain import Creative, Metrics, Source
from beautyads.sources.config import InstagramAccount
from beautyads.sources.youtube import CollectResult

_TIMEOUT_S = 30.0
_STOP_ERRORS = {"INSTAGRAM_TOKEN_INVALID", "INSTAGRAM_RATE_LIMITED"}


class InstagramHttpResponse(NamedTuple):
    status: int
    body: Any | None
    headers: Mapping[str, str]


InstagramGet = Callable[[str, Mapping[str, str], float], InstagramHttpResponse]


class InstagramError(Exception):
    """Stable codes only; never retain provider messages or request diagnostics."""

    def __init__(
        self,
        code: str,
        *,
        usage_pct: float | None = None,
        usage: dict[str, float] | None = None,
    ):
        self.code = code
        self.usage_pct = usage_pct
        self.usage = usage
        super().__init__(code)


def instagram_httpx_get(
    url: str, params: Mapping[str, str], timeout_s: float
) -> InstagramHttpResponse:
    """The sole httpx boundary; discard credential-bearing transport errors."""
    import httpx

    try:
        response = httpx.get(url, params=params, timeout=timeout_s)
    except httpx.RequestError:
        raise InstagramError("INSTAGRAM_REQUEST_FAILED") from None
    try:
        body = response.json()
    except ValueError:
        body = None
    return InstagramHttpResponse(
        response.status_code,
        body,
        {key.lower(): value for key, value in response.headers.items()},
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def business_discovery_fields(
    username: str, *, limit: int = 100, after: str | None = None
) -> str:
    limit = min(100, max(1, limit))
    media = "media" if after is None else f"media.after({after})"
    return (
        f"business_discovery.username({username})"
        f"{{followers_count,media_count,{media}.limit({limit})"
        "{id,media_type,media_product_type,media_url,permalink,timestamp,caption,"
        "like_count,comments_count,view_count}}"
    )


def parse_usage(headers: Mapping[str, str]) -> dict[str, float] | None:
    """Per-metric `x-app-usage` values; the stop check uses their maximum."""
    raw = headers.get("x-app-usage")
    if not isinstance(raw, str):
        return None
    try:
        usage = _mapping(json.loads(raw))
    except ValueError:
        return None
    values = {
        key: float(value)
        for key in ("call_count", "total_cputime", "total_time")
        if isinstance(value := usage.get(key), (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
    }
    return values or None


def parse_usage_pct(headers: Mapping[str, str]) -> float | None:
    values = parse_usage(headers)
    return max(values.values()) if values else None


def _published_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return stamp if stamp.utcoffset() is not None else None


def media_to_creative(
    post: Mapping[str, Any], *, account: InstagramAccount, collected_at: datetime
) -> Creative:
    media_type = post.get("media_type")
    analyzable = None
    if media_type == "VIDEO":
        analyzable = "media_url" in post
    elif media_type in ("IMAGE", "CAROUSEL_ALBUM"):
        analyzable = False
    source_id = post.get("id")
    if not isinstance(source_id, (str, int)) or isinstance(source_id, bool):
        raise InstagramError("INSTAGRAM_INVALID_RESPONSE")
    try:
        return Creative(
            source=Source.instagram,
            source_id=str(source_id),
            url=post.get("permalink"),
            caption=post.get("caption"),
            published_at=_published_at(post.get("timestamp")),
            duration_s=None,
            language=None,
            analyzable=analyzable,
            brand=account.brand,
            account=account.username,
            collected_at=collected_at,
            metrics=Metrics(
                view_count=post.get("view_count"),
                like_count=post.get("like_count"),
                comment_count=post.get("comments_count"),
            ),
        )
    except ValidationError:
        raise InstagramError("INSTAGRAM_INVALID_RESPONSE") from None


class AccountPage(NamedTuple):
    posts: list[Mapping[str, Any]]
    next_after: str | None
    followers_count: int | None
    media_count: int | None
    usage_pct: float | None
    usage: dict[str, float] | None = None


def fetch_account_page(
    get: InstagramGet,
    token: str,
    ig_user_id: str,
    account: InstagramAccount,
    *,
    base_url: str,
    after: str | None = None,
    limit: int = 100,
) -> AccountPage:
    response = get(
        f"{base_url.rstrip('/')}/{ig_user_id}",
        {
            "fields": business_discovery_fields(
                account.username, limit=limit, after=after
            ),
            "access_token": token,
        },
        _TIMEOUT_S,
    )
    if response.status != 200:
        code = _mapping(_mapping(response.body).get("error")).get("code")
        # Only numeric provider codes may enter diagnostics, never arbitrary text.
        code = code if type(code) is int else None
        if response.status == 400 and code == 110:
            reason = "INSTAGRAM_ACCOUNT_NOT_FOUND"
        elif code == 190:
            reason = "INSTAGRAM_TOKEN_INVALID"
        elif code in (4, 17, 32, 613):
            reason = "INSTAGRAM_RATE_LIMITED"
        else:
            reason = f"INSTAGRAM_ERROR_{code if code is not None else response.status}"
        raise InstagramError(
            reason,
            usage_pct=parse_usage_pct(response.headers),
            usage=parse_usage(response.headers),
        )

    usage = parse_usage(response.headers)
    usage_pct = max(usage.values()) if usage else None
    discovery = _mapping(response.body).get("business_discovery")
    if not isinstance(discovery, Mapping):
        raise InstagramError(
            "INSTAGRAM_INVALID_RESPONSE", usage_pct=usage_pct, usage=usage
        )
    media = _mapping(discovery.get("media"))
    posts = media.get("data", [])
    after = _mapping(_mapping(media.get("paging")).get("cursors")).get("after")
    if (
        not isinstance(posts, list)
        or any(not isinstance(post, Mapping) for post in posts)
        or (after is not None and not isinstance(after, str))
    ):
        raise InstagramError(
            "INSTAGRAM_INVALID_RESPONSE", usage_pct=usage_pct, usage=usage
        )
    followers = discovery.get("followers_count")
    count = discovery.get("media_count")
    return AccountPage(
        posts,
        after or None,
        followers if type(followers) is int else None,
        count if type(count) is int else None,
        usage_pct,
        usage,
    )


def _usage_high(usage_pct: float | None, threshold: float) -> bool:
    return usage_pct is not None and usage_pct >= threshold


def collect_instagram(
    get: InstagramGet,
    token: str,
    ig_user_id: str,
    accounts: Sequence[InstagramAccount],
    *,
    base_url: str,
    max_posts_per_account: int,
    collected_at: datetime,
    usage_stop_pct: float = 80.0,
    usage_sink: dict[str, float] | None = None,
) -> CollectResult:
    creatives: list[Creative] = []
    errors: dict[str, str] = {}
    for account in accounts:
        after = None
        seen: set[str] = set()
        collected = 0
        usage_pct = None
        try:
            while collected < max_posts_per_account:
                if after is not None:
                    if after in seen:
                        raise InstagramError("INSTAGRAM_INVALID_RESPONSE")
                    seen.add(after)
                page = fetch_account_page(
                    get, token, ig_user_id, account, base_url=base_url, after=after
                )
                usage_pct = page.usage_pct
                if usage_sink is not None and page.usage:
                    usage_sink.clear()
                    usage_sink.update(page.usage)
                for post in page.posts[: max_posts_per_account - collected]:
                    creatives.append(
                        media_to_creative(
                            post, account=account, collected_at=collected_at
                        )
                    )
                    collected += 1
                if _usage_high(usage_pct, usage_stop_pct):
                    return CollectResult(creatives, errors, "INSTAGRAM_USAGE_HIGH")
                after = page.next_after
                if after is None:
                    break
        except InstagramError as error:
            errors[account.username] = error.code
            if usage_sink is not None and error.usage:
                usage_sink.clear()
                usage_sink.update(error.usage)
            if error.code in _STOP_ERRORS:
                return CollectResult(creatives, errors, error.code)
            if _usage_high(error.usage_pct, usage_stop_pct) or _usage_high(
                usage_pct, usage_stop_pct
            ):
                return CollectResult(creatives, errors, "INSTAGRAM_USAGE_HIGH")
    return CollectResult(creatives, errors, None)


def parse_oe_expiry(url: str) -> datetime | None:
    try:
        values = parse_qs(urlsplit(url).query).get("oe")
        value = next(iter(values), None) if values else None
        return datetime.fromtimestamp(int(value, 16), tz=UTC) if value else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def needs_refresh(
    url: str | None, now: datetime, *, min_remaining_s: float = 21600.0
) -> bool:
    expiry = parse_oe_expiry(url) if url is not None else None
    return expiry is None or (expiry - now).total_seconds() < min_remaining_s


class RefreshResult(NamedTuple):
    urls: dict[str, str]
    gone: set[str]
    missing: set[str]
    stopped: str | None


def refresh_media_urls(
    get: InstagramGet,
    token: str,
    ig_user_id: str,
    account: InstagramAccount,
    wanted_ids: Collection[str],
    *,
    base_url: str,
    now: datetime,
    max_pages: int = 5,
    usage_stop_pct: float = 80.0,
) -> RefreshResult:
    """Rescan an account; URLs remain transient even if their expiry is unchanged."""
    urls: dict[str, str] = {}
    gone: set[str] = set()
    missing = set(wanted_ids)
    after = None
    seen: set[str] = set()
    for _ in range(max_pages):
        if not missing:
            break
        try:
            if after is not None:
                if after in seen:
                    raise InstagramError("INSTAGRAM_INVALID_RESPONSE")
                seen.add(after)
            page = fetch_account_page(
                get, token, ig_user_id, account, base_url=base_url, after=after
            )
        except InstagramError as error:
            stopped = error.code
            if error.code not in _STOP_ERRORS and _usage_high(
                error.usage_pct, usage_stop_pct
            ):
                stopped = "INSTAGRAM_USAGE_HIGH"
            return RefreshResult(urls, gone, missing, stopped)
        for post in page.posts:
            source_id = post.get("id")
            if not isinstance(source_id, (str, int)):
                continue
            source_id = str(source_id)
            if source_id not in missing:
                continue
            missing.remove(source_id)
            url = post.get("media_url")
            if "media_url" not in post:
                gone.add(source_id)
            elif post.get("media_type") == "VIDEO" and isinstance(url, str) and url:
                urls[source_id] = url
        if _usage_high(page.usage_pct, usage_stop_pct):
            return RefreshResult(urls, gone, missing, "INSTAGRAM_USAGE_HIGH")
        after = page.next_after
        if after is None:
            break
    return RefreshResult(urls, gone, missing, None)
