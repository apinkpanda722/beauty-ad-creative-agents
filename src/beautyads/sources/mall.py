"""Official-mall HTML facts and bounded, memory-only detail image downloads.

Construction is offline. Every request checks exclusions, robots and host pacing.
Calls make one attempt; MallError.retryable lets the runner retry transient
failures without classifying them as discontinued products. Reuse one client
for product requests, images and retries so host pacing is shared.
"""

import json
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


MallGet = Callable[[str, Mapping[str, str], float, int], MallHttpResponse]


def httpx_mall_get(
    url: str, headers: Mapping[str, str], timeout_s: float, max_bytes: int
) -> MallHttpResponse:
    """Single HTTP boundary, bounded after httpx decompresses gzip.

    Redirects are returned as HTTP errors: automatic following would bypass the
    destination's robots check and host interval. Non-200 bodies are not parsed.
    """
    try:
        with httpx.stream(
            "GET", url, headers=headers, timeout=timeout_s, follow_redirects=False
        ) as response:
            if response.status_code != 200:
                return MallHttpResponse(response.status_code, b"")
            data = bytearray()
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                if len(data) + len(chunk) > max_bytes:
                    raise MallError("MALL_RESPONSE_TOO_LARGE")
                data.extend(chunk)
            return MallHttpResponse(response.status_code, bytes(data))
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
    images = []
    if ingredients is None:
        for detail in nodes:
            if detail.attrs.get("id") == "prdDetail":
                images.extend(
                    urljoin(url, source.strip())
                    for node in detail.walk()
                    if node.tag == "img"
                    and (source := node.attrs.get("ec-data-src"))
                    and source.strip()
                )
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
                response = self._request(
                    f"{origin}/robots.txt",
                    max_bytes=_ROBOTS_MAX_BYTES,
                    timeout_s=_TIMEOUT_S,
                )
            except MallError as error:
                raise MallError(
                    "MALL_ROBOTS_UNREADABLE", retryable=error.retryable
                ) from None
            if response.status != 200 or len(response.body) > _ROBOTS_MAX_BYTES:
                raise MallError(
                    "MALL_ROBOTS_UNREADABLE", retryable=500 <= response.status < 600
                )
            parser = RobotFileParser()
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
