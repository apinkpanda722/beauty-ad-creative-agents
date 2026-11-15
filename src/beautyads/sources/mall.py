"""Official-mall HTML facts and bounded, memory-only detail image downloads.

Construction is offline. Every request checks exclusions, robots and host pacing.
Calls make one attempt; MallError.retryable lets the runner retry transient
failures without classifying them as discontinued products. Reuse one client
for product requests, images and retries so host pacing is shared.
"""

import json
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from time import monotonic, sleep
from typing import NamedTuple
from urllib.parse import quote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from beautyads.domain.mall import MallProduct

_TIMEOUT_S = 30.0
_HTML_MAX_BYTES = 8 * 1024 * 1024
_ROBOTS_MAX_BYTES = 1024 * 1024
# Statuses meaning the host has no robots.txt at all (not an access denial).
_ROBOTS_ABSENT_STATUSES = frozenset({404, 410})
# robots.txt may redirect (RFC 9309 asks crawlers to follow at least five hops).
_ROBOTS_MAX_REDIRECTS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class MallError(Exception):
    """Stable codes without URLs, personal information or transport diagnostics."""

    def __init__(self, code: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class MallDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    excluded: bool
    min_interval_s: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class MallConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Only a generic client identifier, never a person's name or email address.
    user_agent: str = Field(pattern=r"^beautyads(?:-research)?/[0-9]+(?:\.[0-9]+)*$")
    default_interval_s: float = Field(default=6, gt=0, allow_inf_nan=False)
    malls: dict[str, MallDefinition] = Field(min_length=1)


def load_mall_config(path: Path = Path("config/malls.yaml")) -> MallConfig:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise MallError("MALL_CONFIG_UNREADABLE") from None
    try:
        return MallConfig.model_validate(document)
    except ValidationError:
        raise MallError("MALL_CONFIG_INVALID") from None


class MallHttpResponse(NamedTuple):
    status: int
    body: bytes
    # Redirect target and media type, exposed only so the robots.txt request can
    # follow redirects and tell an HTML error page from a real rules file.
    location: str | None = None
    content_type: str | None = None


MallGet = Callable[[str, Mapping[str, str], float, int], MallHttpResponse]


def httpx_mall_get(
    url: str, headers: Mapping[str, str], timeout_s: float, max_bytes: int
) -> MallHttpResponse:
    """Single HTTP boundary, bounded after httpx decompresses gzip.

    Redirects are returned as HTTP errors with their Location: automatic following
    would bypass the destination's robots check and host interval. Only the
    robots.txt request follows them, by hand, through the client (so every hop keeps
    its host interval). Non-200 bodies are not parsed.
    """
    try:
        with httpx.stream(
            "GET", url, headers=headers, timeout=timeout_s, follow_redirects=False
        ) as response:
            content_type = response.headers.get("content-type")
            if response.status_code != 200:
                return MallHttpResponse(
                    response.status_code,
                    b"",
                    location=response.headers.get("location"),
                    content_type=content_type,
                )
            data = bytearray()
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                if len(data) + len(chunk) > max_bytes:
                    raise MallError("MALL_RESPONSE_TOO_LARGE")
                data.extend(chunk)
            return MallHttpResponse(
                response.status_code, bytes(data), content_type=content_type
            )
    except (httpx.ConnectError, httpx.TimeoutException):
        raise MallError("MALL_REQUEST_FAILED", retryable=True) from None
    except httpx.RequestError:
        raise MallError("MALL_REQUEST_FAILED") from None


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list["_Node | str"] = field(default_factory=list)

    def walk(self) -> Iterator["_Node"]:
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.walk()

    def text(self) -> str:
        return "".join(
            child.text() if isinstance(child, _Node) else child
            for child in self.children
            if not isinstance(child, _Node) or child.tag not in {"script", "style"}
        )

    def has_class(self, value: str) -> bool:
        return value in (self.attrs.get("class") or "").split()


class _HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self.stack.append(node)
        elif tag == "br":
            self.stack[-1].children.append(" ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _number(value: str | float | None) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() and number >= 0 else None


def _ingredients(root: _Node) -> str | None:
    for row in root.walk():
        if row.tag == "tr":
            label = next((n for n in row.walk() if n.tag == "th"), None)
            content = next((n for n in row.walk() if n.tag == "td"), None)
        elif row.tag == "div" and row.has_class("info-row"):
            label = next((n for n in row.walk() if n.has_class("info-label")), None)
            content = next((n for n in row.walk() if n.has_class("info-content")), None)
        elif row.tag == "div" and row.has_class("dePop"):
            # Popup layer opened by the 전성분 link: a header and a depContent block.
            label = next((n for n in row.walk() if n.has_class("pp_header")), None)
            content = next((n for n in row.walk() if n.has_class("depContent")), None)
        elif row.tag == "li":
            # Accordion item: <li>전성분<span/><ul><li>values</li></ul></li>. The
            # label is the item's own text, the value its nested list or block.
            own = "".join(child for child in row.children if isinstance(child, str))
            if len("".join(own.split())) > 12:
                continue
            label = _Node("li", children=[own])
            content = next(
                (
                    child
                    for child in row.children
                    if isinstance(child, _Node) and child.tag in {"ul", "div"}
                ),
                None,
            )
        else:
            continue
        if label is None or content is None:
            continue
        normalized = "".join(label.text().split())
        if any(term in normalized for term in ("모든성분", "전성분")):
            value = " ".join(content.text().split())
            if value:
                return value
    return None


def _parse_product(body: bytes, url: str) -> MallProduct:
    parser = _HTML()
    parser.feed(body.decode("utf-8", errors="replace"))
    parser.close()
    nodes = list(parser.root.walk())
    meta = {
        node.attrs.get("property"): node.attrs.get("content")
        for node in nodes
        if node.tag == "meta"
    }
    hidden = {
        node.attrs.get("name"): node.attrs.get("value")
        for node in nodes
        if node.tag == "input" and node.attrs.get("type") == "hidden"
    }
    offers = {}
    for node in nodes:
        if node.tag != "script" or node.attrs.get("type") != "application/ld+json":
            continue
        try:
            product = json.loads(node.text())
        except ValueError:
            continue
        if isinstance(product, dict) and product.get("@type") == "Product":
            candidate = product.get("offers")
            if isinstance(candidate, dict):
                offers = candidate
                break
    list_meta = _number(meta.get("product:price:amount"))
    sale_meta = _number(meta.get("product:sale_price:amount"))
    json_price = _number(offers.get("price"))
    # Hidden inputs alone are insufficient evidence of a live product page.
    if list_meta is None and sale_meta is None and json_price is None:
        raise MallError("MALL_PRODUCT_GONE")
    list_price = list_meta
    if list_price is None:
        list_price = _number(hidden.get("set_goods_fixedPrice"))
    sale_price = sale_meta if sale_meta is not None else json_price
    if sale_price is None:
        sale_price = _number(hidden.get("set_goods_price"))
    basis = (
        "list_price"
        if list_price is not None and list_price > 0
        else "sale_price_fallback"
    )
    price = list_price if basis == "list_price" else sale_price
    if price is None:
        raise MallError("MALL_PRODUCT_GONE")
    ingredients = _ingredients(parser.root)
    images = _detail_images(nodes, url) if ingredients is None else []
    return MallProduct(
        source_url=url,
        list_price=list_price,
        sale_price=sale_price,
        price=price,
        price_basis=basis,
        currency=meta.get("product:price:currency") or offers.get("priceCurrency"),
        ingredients_text=ingredients,
        detail_image_urls=tuple(images),
    )


# Detail-section anchors seen on real malls: Cafe24 `#prdDetail`, Godomall `#detail`.
_DETAIL_ANCHORS = frozenset({"prdDetail", "detail"})
# Anchors of the sections that follow the detail content on those templates.
_SECTION_ENDS = frozenset(
    {
        "prdInfo",
        "prdReview",
        "prdQna",
        "prdQnA",
        "prdRelated",
        "delivery",
        "exchange",
        "reviews",
        "qna",
    }
)
_IMAGE_ATTRIBUTES = ("ec-data-src", "data-src", "data-original", "src")
# Icons, buttons, spacers and logos are page chrome, not product detail images.
_CHROME_IMAGE = re.compile(
    r"/skin/|/design/|icon|ico_|btn_|blank|spacer|logo|loading|\.svg(?:\?|$)",
    re.IGNORECASE,
)


def _detail_images(nodes: list[_Node], url: str) -> tuple[str, ...]:
    """Detail images in document order after the detail anchor.

    Malls differ: the anchor may be a container, an empty marker, or a tab bar,
    and images may use a lazy-loading attribute or a plain src. The section runs
    from the anchor to the next section anchor; a section with no image (an
    empty anchor followed at once by a review anchor) is extended to the next
    section anchor. Lazy attributes win over a placeholder src.
    """
    start = next(
        (i for i, node in enumerate(nodes) if node.attrs.get("id") in _DETAIL_ANCHORS),
        None,
    )
    if start is None:
        return ()
    ends = [
        i
        for i in range(start + 1, len(nodes))
        if nodes[i].attrs.get("id") in _SECTION_ENDS
    ]
    for end in [*ends, len(nodes)]:
        found: list[str] = []
        for node in nodes[start:end]:
            if node.tag != "img":
                continue
            source = next(
                (
                    value.strip()
                    for attribute in _IMAGE_ATTRIBUTES
                    if (value := node.attrs.get(attribute))
                    and value.strip()
                    and not value.strip().startswith("data:")
                ),
                None,
            )
            if source is None or _CHROME_IMAGE.search(source):
                continue
            absolute = urljoin(url, source)
            if absolute not in found:
                found.append(absolute)
        if found:
            return tuple(found)
    return ()


def _encoded_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            raise ValueError
        # Keep existing escapes intact; UTF-8 paths and queries are encoded once.
        return quote(url, safe=":/?#[]@!$&'()*+,;=%")
    except ValueError:
        raise MallError("MALL_INVALID_URL") from None


class MallClient:
    def __init__(
        self,
        *,
        config: MallConfig | None = None,
        get: MallGet = httpx_mall_get,
        clock: Callable[[], float] = monotonic,
        sleep: Callable[[float], None] = sleep,
    ):
        self.config = config if config is not None else load_mall_config()
        self._get = get
        self._clock = clock
        self._sleep = sleep
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser] = {}
        self._intervals: dict[str, float] = {}

    def _request(
        self, url: str, *, max_bytes: int, timeout_s: float
    ) -> MallHttpResponse:
        host = urlsplit(url).netloc.lower()
        interval = self._intervals.get(host, self.config.default_interval_s)
        previous = self._last_request.get(host)
        if previous is not None:
            delay = interval - (self._clock() - previous)
            if delay > 0:
                self._sleep(delay)
        self._last_request[host] = self._clock()
        try:
            return self._get(
                url, {"User-Agent": self.config.user_agent}, timeout_s, max_bytes
            )
        except (
            ConnectionError,
            TimeoutError,
            httpx.ConnectError,
            httpx.TimeoutException,
        ):
            raise MallError("MALL_REQUEST_FAILED", retryable=True) from None
        except httpx.RequestError:
            raise MallError("MALL_REQUEST_FAILED") from None

    def _fetch_robots(self, url: str) -> MallHttpResponse:
        """Request robots.txt, following redirects by hand (at most five).

        Each hop goes through the shared request path, so its host keeps the
        request interval. Only this request follows redirects; product and image
        requests never do.
        """
        for _ in range(_ROBOTS_MAX_REDIRECTS + 1):
            response = self._request(
                url, max_bytes=_ROBOTS_MAX_BYTES, timeout_s=_TIMEOUT_S
            )
            if response.status not in _REDIRECT_STATUSES:
                return response
            target = urljoin(url, (response.location or "").strip())
            parts = urlsplit(target)
            if (
                not (response.location or "").strip()
                or parts.scheme not in {"http", "https"}
                or not parts.hostname
            ):
                raise MallError("MALL_ROBOTS_UNREADABLE")
            url = target
        raise MallError("MALL_ROBOTS_UNREADABLE")

    def _allowed_url(self, brand: str, url: str) -> str:
        definition = self.config.malls.get(brand)
        if definition is None:
            raise MallError("MALL_UNKNOWN")
        if definition.excluded:
            raise MallError("MALL_EXCLUDED")
        url = _encoded_url(url)
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        host = parts.netloc.lower()
        self._intervals[host] = max(
            self._intervals.get(host, 0),
            definition.min_interval_s or self.config.default_interval_s,
        )
        parser = self._robots.get(origin)
        if parser is None:
            try:
                response = self._fetch_robots(f"{origin}/robots.txt")
            except MallError as error:
                raise MallError(
                    "MALL_ROBOTS_UNREADABLE", retryable=error.retryable
                ) from None
            parser = RobotFileParser()
            html_page = response.status == 200 and (
                (response.content_type or "").lower().startswith("text/html")
            )
            if response.status in _ROBOTS_ABSENT_STATUSES or html_page:
                # No robots.txt exists (RFC 9309: unavailable means no rules), or
                # the host answers with an HTML (error) page, which is not a rules
                # file. That body is never read as rules. The request interval still
                # applies to this host.
                parser.parse([])
            elif response.status != 200 or len(response.body) > _ROBOTS_MAX_BYTES:
                # 401/403, server errors and oversized files stay fail-closed.
                raise MallError(
                    "MALL_ROBOTS_UNREADABLE", retryable=500 <= response.status < 600
                )
            else:
                parser.parse(
                    response.body.decode("utf-8-sig", errors="replace").splitlines()
                )
            delay = parser.crawl_delay(self.config.user_agent)
            # Dalba has no '*' entry. Honor the named bots' delay as well.
            if delay is None and parser.default_entry is None:
                delays = [
                    entry.delay for entry in parser.entries if entry.delay is not None
                ]
                delay = max(delays, default=None)
            if delay is not None:
                self._intervals[host] = max(self._intervals.get(host, 0), delay)
            self._robots[origin] = parser
        if not parser.can_fetch(self.config.user_agent, url):
            raise MallError("MALL_ROBOTS_DISALLOWED")
        return url

    def fetch_product(self, brand: str, url: str) -> MallProduct:
        url = self._allowed_url(brand, url)
        response = self._request(url, max_bytes=_HTML_MAX_BYTES, timeout_s=_TIMEOUT_S)
        _check_status(response.status, product=True)
        if len(response.body) > _HTML_MAX_BYTES:
            raise MallError("MALL_RESPONSE_TOO_LARGE")
        return _parse_product(response.body, url)


def _check_status(status: int, *, product: bool = False) -> None:
    if status == 404 and product:
        raise MallError("MALL_PRODUCT_GONE")
    if status != 200:
        raise MallError(f"MALL_HTTP_{status}", retryable=500 <= status < 600)


def download_detail_image(
    url: str,
    *,
    max_bytes: int,
    client: MallClient,
    brand: str,
    timeout_s: float = _TIMEOUT_S,
) -> bytes:
    """Fetch image bytes only, sharing robots and pacing with product requests."""
    if type(max_bytes) is not int or max_bytes <= 0:
        raise MallError("MALL_INVALID_MAX_BYTES")
    if timeout_s <= 0 or not Decimal(str(timeout_s)).is_finite():
        raise MallError("MALL_INVALID_TIMEOUT")
    url = client._allowed_url(brand, url)
    try:
        response = client._request(url, max_bytes=max_bytes, timeout_s=timeout_s)
    except MallError as error:
        if error.code == "MALL_RESPONSE_TOO_LARGE":
            raise MallError("MALL_IMAGE_TOO_LARGE") from None
        raise
    _check_status(response.status)
    if len(response.body) > max_bytes:
        raise MallError("MALL_IMAGE_TOO_LARGE")
    return response.body
