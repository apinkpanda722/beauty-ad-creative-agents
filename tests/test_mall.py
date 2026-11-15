"""Offline official-mall contracts; edge cases mutate recorded minimal originals."""

import gzip
import re
from collections import deque
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit
from uuid import uuid4

import httpx
import pytest
import yaml

from beautyads.domain.mall import MallProduct
from beautyads.sources.mall import (
    MallClient,
    MallError,
    MallHttpResponse,
    download_detail_image,
    httpx_mall_get,
    load_mall_config,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "contracts"


def recorded(name):
    return (FIXTURES / f"mall_{name}").read_bytes()


def page(name="cafe24_image_only.html", status=200):
    return MallHttpResponse(status, recorded(name))


def robots(name="mixsoon"):
    return page(f"robots_{name}.txt")


class FakeGet:
    def __init__(self, *responses):
        self.responses = deque(responses)
        self.calls = []

    def __call__(self, url, headers, timeout_s, max_bytes):
        assert timeout_s > 0 and max_bytes > 0
        self.calls.append((url, dict(headers)))
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []

    def __call__(self):
        return self.now

    def sleep(self, delay):
        self.waits.append(delay)
        self.now += delay


def client(get, **kwargs):
    clock = kwargs.pop("clock", Clock())
    return MallClient(
        config=kwargs.pop("config", load_mall_config(ROOT / "config/malls.yaml")),
        get=get,
        clock=clock,
        sleep=clock.sleep,
        **kwargs,
    )


@pytest.mark.parametrize("name", ["text_div", "table_empty", "image_only"])
def test_cafe24_prices_are_numeric_and_ordered(name):
    get = FakeGet(robots(), page(f"cafe24_{name}.html"))
    result = client(get).fetch_product("cosrx", "https://www.cosrx.co.kr/product/732/")
    assert isinstance(result, MallProduct)
    assert isinstance(result.list_price, Decimal)
    assert isinstance(result.sale_price, Decimal)
    assert result.list_price >= result.sale_price > 0
    assert result.currency == "KRW"
    assert result.price == result.list_price
    assert result.price_basis == "list_price"


def test_godomall_string_price_and_zero_list_price():
    get = FakeGet(robots("dalba"), page("godomall_product.html"))
    result = client(get).fetch_product(
        "dalba", "https://dalba.co.kr/goods/goods_view.php?goodsNo=1000000043"
    )
    assert isinstance(result.sale_price, Decimal) and result.sale_price > 0
    assert result.list_price == 0
    assert result.price == result.sale_price
    assert result.price_basis == "sale_price_fallback"
    assert result.currency == "KRW"
    assert result.ingredients_text is None


@pytest.mark.parametrize("remove", ["list", "sale", "all_meta"])
def test_missing_price_fields_use_recorded_json_ld(remove):
    body = recorded("cafe24_image_only.html").decode()
    pattern = {
        "list": r'<meta property="product:price:amount"[^>]*>',
        "sale": r'<meta property="product:sale_price:amount"[^>]*>',
        "all_meta": r'<meta property="product:[^>]*>',
    }.get(remove)
    body = re.sub(pattern, "", body)
    result = client(
        FakeGet(robots(), MallHttpResponse(200, body.encode()))
    ).fetch_product("cosrx", "https://www.cosrx.co.kr/product/732/")
    assert result.sale_price > 0
    if remove != "sale":
        assert result.price_basis == "sale_price_fallback"
    else:
        assert result.price_basis == "list_price"


@pytest.mark.parametrize(
    "name,has_text", [("text_div", True), ("table_empty", False), ("image_only", False)]
)
def test_ingredients_require_a_populated_value_cell(name, has_text):
    result = client(FakeGet(robots(), page(f"cafe24_{name}.html"))).fetch_product(
        "anua", "https://anua.kr/product/390/"
    )
    assert bool(result.ingredients_text) is has_text
    if not has_text:
        assert result.ingredients_text is None
    if has_text:
        assert result.detail_image_urls == ()


def test_populated_table_and_blank_div_are_value_based():
    table = recorded("cafe24_table_empty.html").decode()
    div = recorded("cafe24_text_div.html").decode()
    value = re.search(
        r'<div class="info-content ingredients">(.*?)</div>', div, re.DOTALL
    ).group(1)
    table = re.sub(
        r"(표시하여야 하는 모든 성분\s*</th>\s*<td>)(</td>)",
        lambda m: m.group(1) + value + m.group(2),
        table,
    )
    result = client(
        FakeGet(robots(), MallHttpResponse(200, table.encode()))
    ).fetch_product("isntree", "https://www.isntree.com/product/46/")
    assert result.ingredients_text and result.ingredients_text.strip()
    empty_div = div.replace(value, " \n <br> \t ")
    result = client(
        FakeGet(robots(), MallHttpResponse(200, empty_div.encode()))
    ).fetch_product("anua", "https://anua.kr/product/390/")
    assert result.ingredients_text is None and result.detail_image_urls


def test_image_addresses_keep_page_order_and_resolve_relative_paths():
    body = recorded("cafe24_image_only.html").decode()
    original = re.findall(r'ec-data-src="([^"]+)"', body)
    first = next(iter(original))
    body = body.replace(first, "/detail/성분.jpg", 1)
    url = "https://www.cosrx.co.kr/product/732/"
    result = client(
        FakeGet(robots(), MallHttpResponse(200, body.encode()))
    ).fetch_product("cosrx", url)
    expected = (urljoin(url, "/detail/성분.jpg"), *original[1:])
    assert result.ingredients_text is None
    assert result.detail_image_urls == expected
    assert all(urlsplit(item).scheme == "https" for item in result.detail_image_urls)


@pytest.mark.parametrize("status", [200, 404])
def test_discontinued_status_and_missing_price(status):
    get = FakeGet(robots(), page("discontinued_404.html", status))
    with pytest.raises(MallError) as caught:
        client(get).fetch_product(
            "mixsoon", "https://mixsoon.co.kr/product/detail.html?product_no=552"
        )
    assert caught.value.code == "MALL_PRODUCT_GONE"
    assert not caught.value.retryable


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_http_status_precedes_body_and_transient_errors_stay_retryable(status):
    get = FakeGet(robots(), page("discontinued_404.html", status))
    with pytest.raises(MallError) as caught:
        client(get).fetch_product("mixsoon", "https://mixsoon.co.kr/product/552/")
    assert caught.value.code == f"MALL_HTTP_{status}"
    assert caught.value.retryable is (status >= 500)


@pytest.mark.parametrize(
    "failure", [ConnectionError, TimeoutError, httpx.ConnectError, httpx.ReadTimeout]
)
def test_connection_failures_are_retryable_and_redacted(failure):
    sentinel = uuid4().hex
    get = FakeGet(robots(), failure(sentinel))
    with pytest.raises(MallError) as caught:
        client(get).fetch_product("mixsoon", "https://mixsoon.co.kr/product/552/")
    assert caught.value.code == "MALL_REQUEST_FAILED" and caught.value.retryable
    assert sentinel not in str(caught.value)


@pytest.mark.parametrize("path", ["/admin/", "/order/", "/api/", "/myshop/"])
def test_robots_blocks_without_sending_the_blocked_request(path):
    get = FakeGet(robots())
    mall = client(get)
    for _ in range(2):
        with pytest.raises(MallError, match="MALL_ROBOTS_DISALLOWED"):
            mall.fetch_product("mixsoon", f"https://mixsoon.co.kr{path}")
    assert [urlsplit(url).path for url, _ in get.calls] == ["/robots.txt"]


def test_dalba_crlf_named_bot_delay_and_host_independence():
    assert b"\r\n" in recorded("robots_dalba.txt")
    clock = Clock()
    get = FakeGet(
        robots("dalba"),
        page("godomall_product.html"),
        page("godomall_product.html"),
        robots(),
        page(),
    )
    mall = client(get, clock=clock)
    url = "https://dalba.co.kr/goods/goods_view.php?goodsNo=1000000043"
    mall.fetch_product("dalba", url)
    clock.waits.clear()
    mall.fetch_product("dalba", url)
    assert clock.waits and min(clock.waits) >= 10
    start = clock.now
    mall.fetch_product("cosrx", "https://www.cosrx.co.kr/product/732/")
    assert clock.now - start == 6  # only robots -> product for the new host
    assert sum(urlsplit(url).path == "/robots.txt" for url, _ in get.calls) == 2


def test_named_delay_is_read_even_when_config_has_only_default_interval():
    config = load_mall_config(ROOT / "config/malls.yaml")
    config.malls.get("dalba").min_interval_s = None
    clock = Clock()
    mall = client(
        FakeGet(
            robots("dalba"),
            page("godomall_product.html"),
            page("godomall_product.html"),
        ),
        config=config,
        clock=clock,
    )
    url = "https://dalba.co.kr/goods/goods_view.php?goodsNo=1000000043"
    mall.fetch_product("dalba", url)
    mall.fetch_product("dalba", url)
    assert clock.waits and min(clock.waits) >= 10


@pytest.mark.parametrize(
    "response",
    [
        page("discontinued_404.html", 500),
        ConnectionError("private"),
        page("discontinued_404.html", 404),
    ],
)
def test_unreadable_robots_fails_closed(response):
    get = FakeGet(response)
    with pytest.raises(MallError, match="MALL_ROBOTS_UNREADABLE"):
        client(get).fetch_product("mixsoon", "https://mixsoon.co.kr/product/552/")
    assert len(get.calls) == 1 and urlsplit(get.calls[0][0]).path == "/robots.txt"


@pytest.mark.parametrize("brand", ["torriden", "numbuzin"])
def test_excluded_malls_never_make_even_a_robots_request(brand):
    get = FakeGet()
    mall = client(get)
    with pytest.raises(MallError, match="MALL_EXCLUDED"):
        mall.fetch_product(brand, "https://unused.invalid/product/")
    with pytest.raises(MallError, match="MALL_EXCLUDED"):
        download_detail_image(
            "https://unused.invalid/image.jpg", client=mall, brand=brand, max_bytes=1
        )
    assert get.calls == []


def test_image_download_is_bounded_memory_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = recorded("cafe24_image_only.html")
    mall = client(FakeGet(robots(), MallHttpResponse(200, data)))
    result = download_detail_image(
        "https://www.cosrx.co.kr/detail/성분.jpg",
        client=mall,
        brand="cosrx",
        max_bytes=len(data),
    )
    assert result == data and isinstance(result, bytes)
    assert list(tmp_path.iterdir()) == []
    mall = client(FakeGet(robots(), MallHttpResponse(200, data)))
    with pytest.raises(MallError, match="MALL_IMAGE_TOO_LARGE"):
        download_detail_image(
            "https://www.cosrx.co.kr/detail/image.jpg",
            client=mall,
            brand="cosrx",
            max_bytes=len(data) - 1,
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("encoded", [False, True])
def test_httpx_gzip_and_korean_urls_use_mock_transport(monkeypatch, encoded):
    from beautyads.sources import mall as module

    data = recorded("cafe24_image_only.html")
    requests = []
    original_stream = httpx.stream

    def handle(request):
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=recorded("robots_mixsoon.txt"))
        return httpx.Response(
            200, content=gzip.compress(data), headers={"Content-Encoding": "gzip"}
        )

    def stream(method, url, **kwargs):
        mock_client = httpx.Client(transport=httpx.MockTransport(handle))
        # The adapter owns the response context; this context also closes the client.
        from contextlib import contextmanager

        @contextmanager
        def response():
            with mock_client, mock_client.stream(method, url, **kwargs) as result:
                yield result

        return response()

    assert original_stream is not stream
    monkeypatch.setattr(module.httpx, "stream", stream)
    path = "/detail/성분.jpg"
    url = "https://www.cosrx.co.kr" + (quote(path) if encoded else path)
    mall = client(httpx_mall_get)
    assert (
        download_detail_image(url, client=mall, brand="cosrx", max_bytes=len(data))
        == data
    )
    assert requests[-1].url.raw_path == quote(path).encode()
    with pytest.raises(MallError, match="MALL_IMAGE_TOO_LARGE"):
        download_detail_image(url, client=mall, brand="cosrx", max_bytes=len(data) - 1)


def test_product_url_is_encoded_once_and_user_agent_does_not_include_environment(
    monkeypatch,
):
    sentinel = "person-" + uuid4().hex
    monkeypatch.setenv("USER", sentinel)
    monkeypatch.setenv("EMAIL", sentinel + "@example.invalid")
    get = FakeGet(robots(), page(), page())
    mall = client(get)
    url = "https://www.cosrx.co.kr/product/성분/732/"
    mall.fetch_product("cosrx", url)
    mall.fetch_product("cosrx", quote(url, safe=":/"))
    assert get.calls[-1][0] == get.calls[-2][0]
    configured = load_mall_config(ROOT / "config/malls.yaml").user_agent
    assert all(headers.get("User-Agent") == configured for _, headers in get.calls)
    assert all(sentinel not in str(call) and "@" not in str(call) for call in get.calls)


@pytest.mark.parametrize(
    "user_agent", ["person@example.invalid", "Private Person", "private-person/1.0"]
)
def test_private_user_agents_are_rejected_without_echoing_them(tmp_path, user_agent):
    config = yaml.safe_load((ROOT / "config/malls.yaml").read_text())
    config["user_agent"] = user_agent
    path = tmp_path / "malls.yaml"
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(MallError) as caught:
        load_mall_config(path)
    assert caught.value.code == "MALL_CONFIG_INVALID"
    assert user_agent not in str(caught.value)


def test_config_covers_source_brands_and_defaults():
    config = load_mall_config(ROOT / "config/malls.yaml")
    sources = yaml.safe_load((ROOT / "config/sources.yaml").read_text())
    brands = {row.get("brand") for row in sources.get("tiktok", {}).get("brands", [])}
    assert set(config.malls) == brands
    assert config.default_interval_s >= 6
    assert {brand for brand, mall in config.malls.items() if mall.excluded} == {
        "torriden",
        "numbuzin",
    }


def test_images_and_hidden_fields_cannot_establish_a_live_product_price():
    for name in ("cafe24_image_only.html", "godomall_product.html"):
        body = recorded(name).decode()
        body = re.sub(
            r'<meta property="product:(?:sale_)?price:amount"[^>]*>', "", body
        )
        body = re.sub(r'"price"\s*:\s*(?:"[^"]*"|[0-9.]+)', '"price": null', body)
        # Image attributes are opaque to pricing, including any promotional text.
        body = body.replace("<img ", '<img alt="행사 가격" ', 1)
        get = FakeGet(robots(), MallHttpResponse(200, body.encode()))
        with pytest.raises(MallError, match="MALL_PRODUCT_GONE"):
            client(get).fetch_product("cosrx", "https://www.cosrx.co.kr/product/732/")
        assert len(get.calls) == 2  # robots + HTML; no detail-image request


def test_hidden_sale_price_is_used_when_json_price_is_missing():
    body = recorded("godomall_product.html").decode()
    body = re.sub(r'"price"\s*:\s*"[^"]*"', '"price": null', body)
    # Retain a recorded meta price as the live-page anchor, then verify the
    # independent hidden-input sale-price path rather than inventing a contract.
    meta = re.search(
        r'<meta property="product:price:amount"[^>]*>',
        recorded("cafe24_image_only.html").decode(),
    ).group(0)
    body = body.replace("</head>", meta + "</head>")
    result = client(
        FakeGet(robots(), MallHttpResponse(200, body.encode()))
    ).fetch_product(
        "dalba", "https://dalba.co.kr/goods/goods_view.php?goodsNo=1000000043"
    )
    assert isinstance(result.sale_price, Decimal) and result.sale_price > 0


def test_image_requests_obey_shared_robots_and_delay():
    clock = Clock()
    data = recorded("cafe24_image_only.html")
    get = FakeGet(robots(), page(), MallHttpResponse(200, data))
    mall = client(get, clock=clock)
    mall.fetch_product("cosrx", "https://www.cosrx.co.kr/product/732/")
    clock.waits.clear()
    assert (
        download_detail_image(
            "https://www.cosrx.co.kr/detail/image.jpg",
            client=mall,
            brand="cosrx",
            max_bytes=len(data),
        )
        == data
    )
    assert clock.waits == [6]
    with pytest.raises(MallError, match="MALL_ROBOTS_DISALLOWED"):
        download_detail_image(
            "https://www.cosrx.co.kr/admin/image.jpg",
            client=mall,
            brand="cosrx",
            max_bytes=len(data),
        )
    assert len(get.calls) == 3


@pytest.mark.parametrize("max_bytes", [0, -1, True, 1.5])
def test_invalid_image_limits_fail_before_requests(max_bytes):
    get = FakeGet()
    with pytest.raises(MallError, match="MALL_INVALID_MAX_BYTES"):
        download_detail_image(
            "https://www.cosrx.co.kr/detail/image.jpg",
            client=client(get),
            brand="cosrx",
            max_bytes=max_bytes,
        )
    assert not get.calls


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_image_timeouts_fail_before_requests(timeout):
    get = FakeGet()
    with pytest.raises(MallError, match="MALL_INVALID_TIMEOUT"):
        download_detail_image(
            "https://www.cosrx.co.kr/detail/image.jpg",
            client=client(get),
            brand="cosrx",
            max_bytes=1,
            timeout_s=timeout,
        )
    assert not get.calls


@pytest.mark.parametrize("status", [404, 500])
def test_image_http_status_is_checked_before_oversized_error_body(status):
    get = FakeGet(robots(), page("discontinued_404.html", status))
    with pytest.raises(MallError) as caught:
        download_detail_image(
            "https://www.cosrx.co.kr/detail/image.jpg",
            client=client(get),
            brand="cosrx",
            max_bytes=1,
        )
    assert caught.value.code == f"MALL_HTTP_{status}"
    assert caught.value.retryable is (status == 500)
