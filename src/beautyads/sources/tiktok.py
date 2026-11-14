"""TikTok EU ad collection; signed media URLs exist only during explicit refresh."""

import time
from collections.abc import Callable, Collection, Iterator, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any, NamedTuple

from beautyads.domain import Creative, Source
from beautyads.sources.config import Retailers, TikTokBrand, TikTokConfig
from beautyads.sources.instagram import RefreshResult
from beautyads.sources.youtube import CollectResult

TIKTOK_BASE_URL = "https://open.tiktokapis.com"
QUERY_FIELDS = (
    "ad.id,ad.first_shown_date,ad.last_shown_date,ad.status,ad.videos,"
    "ad.image_urls,ad.reach,advertiser.business_id,advertiser.business_name,"
    "advertiser.paid_for_by"
)
_TIMEOUT_S = 30.0
_STOP_ERRORS = {"TIKTOK_TOKEN_INVALID", "TIKTOK_INVALID_PARAMS"}
# 500·502·503·504는 간헐적이라 대기 후 재시도한다(계약: 서버 오류가 간헐적으로 난다).
_RETRY_STATUSES = frozenset({500, 502, 503, 504})
_BACKOFF_S = (2.0, 5.0, 15.0)
# 쪽 상한에서 끊긴 조회는 "없음"을 증명하지 못한다. 브랜드 하나의 일시 실패일 뿐이다.
PAGES_INCOMPLETE = "TIKTOK_PAGES_INCOMPLETE"


class TikTokHttpResponse(NamedTuple):
    status: int
    body: Any | None


TikTokPost = Callable[
    [str, Mapping[str, str], Mapping[str, Any] | None, Mapping[str, str] | None, float],
    TikTokHttpResponse,
]


class TikTokError(Exception):
    """Only stable codes; provider messages and credential-bearing URLs are omitted."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def tiktok_httpx_post(
    url: str,
    params: Mapping[str, str],
    json_body: Mapping[str, Any] | None,
    form_body: Mapping[str, str] | None,
    timeout_s: float,
) -> TikTokHttpResponse:
    """Sole HTTP boundary: the reserved Authorization entry becomes a header.

    The five-argument transport has no separate headers parameter. Authorization
    is removed from params here, so credentials never enter the query string.
    httpx encodes data as application/x-www-form-urlencoded for the token call.
    """
    import httpx

    query = {key: value for key, value in params.items() if key != "Authorization"}
    auth = params.get("Authorization")
    headers = {"Authorization": auth} if auth is not None else {}
    try:
        response = httpx.post(
            url,
            params=query,
            headers=headers,
            json=json_body,
            data=form_body,
            timeout=timeout_s,
        )
    except httpx.RequestError:
        raise TikTokError("TIKTOK_REQUEST_FAILED") from None
    try:
        body = response.json()
    except ValueError:
        body = None
    return TikTokHttpResponse(response.status_code, body)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _http_error(status: int) -> TikTokError:
    if status == 400:
        return TikTokError("TIKTOK_INVALID_PARAMS")
    if status == 401:
        return TikTokError("TIKTOK_TOKEN_INVALID")
    return TikTokError(f"TIKTOK_HTTP_{status}")


class TokenProvider:
    """Client-credentials token cache; default object repr excludes all fields."""

    def __init__(
        self,
        post: TikTokPost,
        *,
        base_url: str = TIKTOK_BASE_URL,
        client_key: str,
        client_secret: str,
        now: Callable[[], datetime],
    ):
        self._post = post
        self._base_url = base_url.rstrip("/")
        self._client_key = client_key
        self._client_secret = client_secret
        self._now = now
        self._access_token: str | None = None
        self._expires_at: datetime | None = None

    def token(self) -> str:
        now = self._now()
        if (
            self._access_token is not None
            and self._expires_at is not None
            and now < self._expires_at - timedelta(seconds=60)
        ):
            return self._access_token
        self.invalidate()
        response = self._post(
            f"{self._base_url}/v2/oauth/token/",
            {},
            None,
            {
                "client_key": self._client_key,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            },
            _TIMEOUT_S,
        )
        if response.status != 200:
            raise _http_error(response.status)
        body = _mapping(response.body)
        access_token = body.get("access_token")
        expires_in = body.get("expires_in")
        if (
            not isinstance(access_token, str)
            or not access_token
            or type(expires_in) is not int
            or expires_in <= 0
        ):
            raise TikTokError("TIKTOK_INVALID_RESPONSE")
        try:
            expires_at = now + timedelta(seconds=expires_in)
        except OverflowError:
            raise TikTokError("TIKTOK_INVALID_RESPONSE") from None
        self._access_token = access_token
        self._expires_at = expires_at
        return access_token

    def invalidate(self) -> None:
        self._access_token = None
        self._expires_at = None


def build_query_body(
    brand: TikTokBrand,
    config: TikTokConfig,
    *,
    today: date,
    search_id: str | None,
) -> dict[str, Any]:
    """All requests, including refreshes, use this measured query shape."""
    body: dict[str, Any] = {
        "filters": {
            "ad_published_date_range": {
                "min": (today - timedelta(days=config.lookback_days)).strftime(
                    "%Y%m%d"
                ),
                "max": (today - timedelta(days=1)).strftime("%Y%m%d"),
            },
            "country_code_list": list(config.countries),
        },
        "search_term": brand.search_term,
        "search_type": config.search_type,
        "max_count": 10,
    }
    if search_id is not None:
        body["search_id"] = search_id
    return body


def _tokens(name: str) -> list[str]:
    return "".join(char if char.isalnum() else " " for char in name.lower()).split()


def _contains(tokens: list[str], name: str) -> bool:
    candidate = _tokens(name)
    return bool(candidate) and any(
        tokens[start : start + len(candidate)] == candidate
        for start in range(len(tokens) - len(candidate) + 1)
    )


def classify_executor(
    advertiser: Mapping[str, Any],
    *,
    brand_names: Collection[str],
    retailers: Retailers,
) -> str:
    name = advertiser.get("business_name")
    if not isinstance(name, str) or not name.strip() or name.strip().isdigit():
        return "unknown"
    tokens = _tokens(name)
    if any(_contains(tokens, brand) for brand in brand_names):
        return "brand_direct"
    if any(_contains(tokens, retailer) for retailer in retailers.names):
        return "retailer"
    return "unknown"


def _ad_id(item: Mapping[str, Any]) -> str:
    value = _mapping(item.get("ad")).get("id")
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value):
        raise TikTokError("TIKTOK_INVALID_RESPONSE")
    return str(value)


def _videos(ad: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    videos = ad.get("videos")
    return (
        [v for v in videos if isinstance(v, Mapping)]
        if isinstance(videos, list)
        else []
    )


def ad_to_creative(
    item: Mapping[str, Any], *, brand: str, collected_at: datetime, executor: str
) -> Creative:
    ad = _mapping(item.get("ad"))
    advertiser = _mapping(item.get("advertiser"))
    first_shown = ad.get("first_shown_date")
    published_at = None
    if isinstance(first_shown, str):
        try:
            published_at = datetime.strptime(first_shown, "%Y%m%d").replace(tzinfo=UTC)
        except ValueError:
            raise TikTokError("TIKTOK_INVALID_RESPONSE") from None
    business_id = advertiser.get("business_id")
    return Creative(
        source=Source.tiktok,
        source_id=_ad_id(item),
        published_at=published_at,
        brand=brand,
        account=str(business_id) if business_id is not None else None,
        analyzable=any("url" in video for video in _videos(ad)),
        collected_at=collected_at,
        attributes={
            "first_shown_date": first_shown,
            "last_shown_date": ad.get("last_shown_date"),
            "status": ad.get("status"),
            "reach_unique_users_seen": _mapping(ad.get("reach")).get(
                "unique_users_seen"
            ),
            "advertiser_business_id": business_id,
            "advertiser_business_name": advertiser.get("business_name"),
            "advertiser_paid_for_by": advertiser.get("paid_for_by"),
            "executor": executor,
            "has_image_urls": bool(ad.get("image_urls")),
        },
    )


def _query(
    post: TikTokPost,
    token: TokenProvider,
    body: Mapping[str, Any],
    *,
    base_url: str,
    sleep: Callable[[float], None] = time.sleep,
) -> Mapping[str, Any]:
    token_retried = False
    server_retries = 0
    while True:
        response = post(
            f"{base_url.rstrip('/')}/v2/research/adlib/ad/query/",
            {"fields": QUERY_FIELDS, "Authorization": f"Bearer {token.token()}"},
            body,
            None,
            _TIMEOUT_S,
        )
        if response.status != 200:
            code = _mapping(_mapping(response.body).get("error")).get("code")
            if (
                response.status == 401
                and code == "access_token_invalid"
                and not token_retried
            ):
                token.invalidate()
                token_retried = True
                continue
            if response.status in _RETRY_STATUSES and server_retries < len(_BACKOFF_S):
                sleep(_BACKOFF_S[server_retries])
                server_retries += 1
                continue
            raise _http_error(response.status)
        if _mapping(_mapping(response.body).get("error")).get("code") != "ok":
            raise TikTokError("TIKTOK_INVALID_RESPONSE")
        data = _mapping(response.body).get("data")
        if not isinstance(data, Mapping):
            raise TikTokError("TIKTOK_INVALID_RESPONSE")
        return data


def _pages_flagged(
    post: TikTokPost,
    token: TokenProvider,
    config: TikTokConfig,
    brand: TikTokBrand,
    *,
    base_url: str,
    today: date,
    max_pages: int,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[tuple[list[Mapping[str, Any]], bool]]:
    search_id = None
    for _ in range(max_pages):
        data = _query(
            post,
            token,
            build_query_body(brand, config, today=today, search_id=search_id),
            base_url=base_url,
            sleep=sleep,
        )
        ads = data.get("ads")
        has_more = data.get("has_more")
        if (
            not isinstance(ads, list)
            or any(not isinstance(ad, Mapping) for ad in ads)
            or type(has_more) is not bool
        ):
            raise TikTokError("TIKTOK_INVALID_RESPONSE")
        yield ads, has_more
        if has_more is False:
            break
        search_id = data.get("search_id")
        if not isinstance(search_id, str) or not search_id:
            raise TikTokError("TIKTOK_INVALID_RESPONSE")


def _pages(
    post: TikTokPost,
    token: TokenProvider,
    config: TikTokConfig,
    brand: TikTokBrand,
    *,
    base_url: str,
    today: date,
    max_pages: int,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[list[Mapping[str, Any]]]:
    for ads, _has_more in _pages_flagged(
        post,
        token,
        config,
        brand,
        base_url=base_url,
        today=today,
        max_pages=max_pages,
        sleep=sleep,
    ):
        yield ads


def collect_tiktok(
    post: TikTokPost,
    token: TokenProvider,
    config: TikTokConfig,
    retailers: Retailers,
    *,
    base_url: str = TIKTOK_BASE_URL,
    max_pages: int,
    collected_at: datetime,
    brands: Collection[str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> CollectResult:
    creatives: list[Creative] = []
    errors: dict[str, str] = {}
    seen: set[str] = set()
    for brand in config.brands:
        if brands is not None and brand.brand not in brands:
            continue
        try:
            for ads in _pages(
                post,
                token,
                config,
                brand,
                base_url=base_url,
                today=collected_at.date(),
                max_pages=max_pages,
                sleep=sleep,
            ):
                for item in ads:
                    source_id = _ad_id(item)
                    if source_id in seen:
                        continue
                    executor = classify_executor(
                        _mapping(item.get("advertiser")),
                        brand_names=(brand.brand, brand.search_term),
                        retailers=retailers,
                    )
                    creatives.append(
                        ad_to_creative(
                            item,
                            brand=brand.brand,
                            collected_at=collected_at,
                            executor=executor,
                        )
                    )
                    seen.add(source_id)
        except TikTokError as error:
            errors[brand.brand] = error.code
            if error.code in _STOP_ERRORS:
                return CollectResult(creatives, errors, error.code)
    return CollectResult(creatives, errors, None)


def refresh_tiktok_video_urls(
    post: TikTokPost,
    token: TokenProvider,
    config: TikTokConfig,
    brand: TikTokBrand,
    wanted_ids: Collection[str],
    *,
    base_url: str = TIKTOK_BASE_URL,
    today: date,
    max_pages: int,
    sleep: Callable[[float], None] = time.sleep,
) -> RefreshResult:
    """Use at least the collection's max_pages; signed URLs must never be persisted.

    `stopped` is None only when the scan ended with `has_more` false (or every wanted
    id was found). A scan cut by `max_pages` or by an error never proves absence.
    """
    urls: dict[str, str] = {}
    gone: set[str] = set()
    missing = set(wanted_ids)
    if not missing:
        return RefreshResult(urls, gone, missing, None)
    complete = False
    try:
        for ads, has_more in _pages_flagged(
            post,
            token,
            config,
            brand,
            base_url=base_url,
            today=today,
            max_pages=max_pages,
            sleep=sleep,
        ):
            complete = has_more is False
            for item in ads:
                source_id = _ad_id(item)
                if source_id not in missing:
                    continue
                missing.remove(source_id)
                url = next(
                    (
                        v.get("url")
                        for v in _videos(_mapping(item.get("ad")))
                        if isinstance(v.get("url"), str) and v.get("url")
                    ),
                    None,
                )
                if url is None:
                    gone.add(source_id)
                else:
                    urls[source_id] = url
            if not missing:
                return RefreshResult(urls, gone, missing, None)
    except TikTokError as error:
        return RefreshResult(urls, gone, missing, error.code)
    return RefreshResult(urls, gone, missing, None if complete else PAGES_INCOMPLETE)
