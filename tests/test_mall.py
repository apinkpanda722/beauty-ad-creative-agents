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
        page("discontinued_404.html", 403),
        page("discontinued_404.html", 401),
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


@pytest.mark.parametrize("status", [404, 410])
def test_missing_robots_allows_access_and_ignores_the_error_body(status):
    # An image host whose /robots.txt does not exist has no rules (RFC 9309:
    # unavailable means allowed). Its HTML error page must not be read as rules.
    disallow_all = MallHttpResponse(status, b"User-agent: *\nDisallow: /\n")
    data = b"synthetic image bytes"
    get = FakeGet(disallow_all, MallHttpResponse(200, data))
    result = download_detail_image(
        "https://cosrxinc.jpg3.kr/detail/image.jpg",
        client=client(get),
        brand="cosrx",
        max_bytes=len(data),
    )
    assert result == data
    assert [urlsplit(url).path for url, _ in get.calls] == [
        "/robots.txt",
        "/detail/image.jpg",
    ]


def test_missing_robots_is_cached_per_origin_and_the_interval_still_applies():
    clock = Clock()
    data = b"synthetic image bytes"
    get = FakeGet(
        MallHttpResponse(404, b"<html></html>"),
        MallHttpResponse(200, data),
        MallHttpResponse(200, data),
    )
    mall = client(get, clock=clock)
    for name in ("one.jpg", "two.jpg"):
        assert (
            download_detail_image(
                f"https://cosrxinc.jpg3.kr/detail/{name}",
                client=mall,
                brand="cosrx",
                max_bytes=len(data),
            )
            == data
        )
    paths = [urlsplit(url).path for url, _ in get.calls]
    assert paths == ["/robots.txt", "/detail/one.jpg", "/detail/two.jpg"]
    # The 404 does not remove politeness: consecutive requests keep the interval.
    assert clock.waits == [6, 6]


def test_missing_robots_on_one_host_does_not_relax_another_host():
    data = b"synthetic image bytes"
    get = FakeGet(
        MallHttpResponse(404, b""),
        MallHttpResponse(200, data),
        robots(),  # the mall's own host still has real rules
    )
    mall = client(get)
    download_detail_image(
        "https://cosrxinc.jpg3.kr/detail/image.jpg",
        client=mall,
        brand="cosrx",
        max_bytes=len(data),
    )
    with pytest.raises(MallError, match="MALL_ROBOTS_DISALLOWED"):
        download_detail_image(
            "https://www.cosrx.co.kr/admin/image.jpg",
            client=mall,
            brand="cosrx",
            max_bytes=len(data),
        )


def _product(fixture, brand, url, body=None):
    page_response = MallHttpResponse(200, body) if body is not None else page(fixture)
    mall = client(FakeGet(robots(), page_response))
    return mall.fetch_product(brand, url)


def _first_image_source(fixture_name):
    text = recorded(fixture_name).decode("utf-8")
    return re.search(r'<img\b[^>]*?\s(?:ec-data-src|src)="([^"]+)"', text).group(1)


def test_detail_images_in_a_tab_container_use_plain_src_and_skip_icons():
    # Real isntree structure: #prdDetail is a tab container, images use plain src
    # (there is no ec-data-src) and an icon sits at the end of the section.
    product = _product(
        "cafe24_tab_src.html", "isntree", "https://www.isntree.com/product/x/46/"
    )
    urls = product.detail_image_urls
    assert len(urls) == 5
    assert all(url.startswith("https://") for url in urls)
    assert urls[0].startswith("https://www.isntree.com/web/upload/NNEditor/20260428/")
    assert urlsplit(urls[3]).hostname == "isntree01.openhost.cafe24.com"
    assert not any("icon_basket" in url for url in urls)


def test_detail_images_after_an_empty_anchor_extend_past_the_review_anchor():
    # Real abib structure: #prdDetail is empty and a review anchor follows it
    # immediately; the detail images come later, before #prdRelated. An image that
    # precedes the #prdDetail anchor is not part of the detail section.
    # The real abib page also lists its ingredients as text (read as text since
    # that path wins); relabel it so this test exercises the image structure.
    body = recorded("cafe24_empty_anchor.html").replace(
        "전성분".encode(), "성분정보".encode()
    )
    product = _product(None, "abib", "https://abib.com/product/x/721/", body=body)
    urls = product.detail_image_urls
    assert len(urls) == 4
    before_anchor = "https:" + _first_image_source("cafe24_empty_anchor.html")
    assert before_anchor not in urls
    assert all(urlsplit(url).hostname == "cafe24.poxo.com" for url in urls)


def test_detail_images_in_a_content_block_use_plain_src():
    product = _product(
        "cafe24_tab_cont.html", "round_lab", "https://roundlab.co.kr/product/x/1/"
    )
    urls = product.detail_image_urls
    assert len(urls) == 5
    assert all(urlsplit(url).hostname == "gi.esmplus.com" for url in urls)


def test_godomall_detail_section_images_are_read():
    # Real dalba structure: #detail section, plain src, ends at #delivery.
    product = _product(
        "godomall_detail.html",
        "dalba",
        "https://dalba.co.kr/goods/goods_view.php?goodsNo=1000000043",
    )
    urls = product.detail_image_urls
    assert len(urls) == 5
    assert urlsplit(urls[0]).hostname == "cdn-saas-web-116-52.cdn-nhncommerce.com"
    # Root-relative sources resolve against the page, not an unrelated host.
    assert any(url.startswith("https://dalba.co.kr/data/img/notice/") for url in urls)


def test_lazy_placeholder_src_does_not_hide_the_real_image():
    original = _product(
        "cafe24_image_only.html", "cosrx", "https://www.cosrx.co.kr/product/732/"
    ).detail_image_urls
    body = recorded("cafe24_image_only.html").replace(
        b" ec-data-src=", b' src="/web/img/blank.gif" ec-data-src='
    )
    lazy = _product(
        None, "cosrx", "https://www.cosrx.co.kr/product/732/", body=body
    ).detail_image_urls
    assert lazy == original and len(lazy) > 0


def test_icons_and_banners_inside_the_section_are_not_detail_images():
    body = recorded("cafe24_tab_cont.html")
    real = b'<img src="https://gi.esmplus.com/roundlab/DOKDO/DWM30/DWM30_01.jpg"'
    assert real in body  # a real detail image inside the #prdDetail section
    body = body.replace(
        real,
        b'<img src="/skin/front/icon_cart.png"><img src="/web/img/btn_buy.png">' + real,
        1,
    )
    urls = _product(
        None, "round_lab", "https://roundlab.co.kr/product/x/1/", body=body
    ).detail_image_urls
    assert not any("icon_cart" in url or "btn_buy" in url for url in urls)
    assert len(urls) == 5


def test_page_without_a_detail_anchor_has_no_detail_images_not_an_error():
    body = (
        b"<html><head>"
        b'<meta property="product:price:amount" content="1000"></head><body>'
        b'<img src="/a.jpg"></body></html>'
    )
    product = _product(None, "cosrx", "https://www.cosrx.co.kr/product/9/", body=body)
    assert product.detail_image_urls == ()


HTML_ERROR_PAGE = MallHttpResponse(
    200,
    b"<!doctype html><html><body>error</body></html>",
    content_type="text/html; charset=utf-8",
)


def redirect(location, status=302):
    return MallHttpResponse(status, b"", location=location)


def _urls(get):
    return [url for url, _ in get.calls]


def test_robots_redirect_to_an_html_error_page_means_no_valid_robots_and_allows():
    # Real dalba image host: /robots.txt answers 302 to an HTML error page.
    data = b"synthetic image bytes"
    get = FakeGet(
        redirect("https://godomall.example.net/error.html"),
        HTML_ERROR_PAGE,
        MallHttpResponse(200, data),
    )
    result = download_detail_image(
        "https://cdn.example.net/a.jpg",
        client=client(get),
        brand="dalba",
        max_bytes=len(data),
    )
    assert result == data
    assert _urls(get) == [
        "https://cdn.example.net/robots.txt",
        "https://godomall.example.net/error.html",
        "https://cdn.example.net/a.jpg",
    ]


def test_robots_redirect_to_real_robots_rules_still_applies_them():
    data = b"x"
    rules = MallHttpResponse(
        200, b"User-agent: *\nDisallow: /admin/\n", content_type="text/plain"
    )
    get = FakeGet(redirect("/real-robots.txt"), rules, MallHttpResponse(200, data))
    mall = client(get)
    assert (
        download_detail_image(
            "https://cdn.example.net/ok.jpg", client=mall, brand="cosrx", max_bytes=9
        )
        == data
    )
    # A relative Location resolves against the URL that redirected.
    assert _urls(get)[1] == "https://cdn.example.net/real-robots.txt"
    with pytest.raises(MallError, match="MALL_ROBOTS_DISALLOWED"):
        download_detail_image(
            "https://cdn.example.net/admin/x.jpg",
            client=mall,
            brand="cosrx",
            max_bytes=9,
        )


def test_robots_follows_at_most_five_redirects():
    data = b"x"
    five = [redirect(f"https://cdn.example.net/hop{i}") for i in range(5)]
    get = FakeGet(*five, HTML_ERROR_PAGE, MallHttpResponse(200, data))
    assert (
        download_detail_image(
            "https://cdn.example.net/a.jpg",
            client=client(get),
            brand="cosrx",
            max_bytes=9,
        )
        == data
    )
    assert len(get.calls) == 7  # robots + five followed redirects + image
    six = [redirect(f"https://cdn.example.net/hop{i}") for i in range(6)]
    get = FakeGet(*six)
    with pytest.raises(MallError, match="MALL_ROBOTS_UNREADABLE"):
        download_detail_image(
            "https://cdn.example.net/a.jpg",
            client=client(get),
            brand="cosrx",
            max_bytes=9,
        )
    assert len(get.calls) == 6  # the sixth redirect is not followed


@pytest.mark.parametrize(
    "bad",
    [
        MallHttpResponse(302, b""),
        redirect("ftp://cdn.example.net/robots.txt"),
        redirect("file:///etc/passwd"),
        redirect(""),
    ],
)
def test_robots_redirect_without_a_usable_http_location_fails_closed(bad):
    get = FakeGet(bad)
    with pytest.raises(MallError, match="MALL_ROBOTS_UNREADABLE"):
        download_detail_image(
            "https://cdn.example.net/a.jpg",
            client=client(get),
            brand="cosrx",
            max_bytes=9,
        )
    assert len(get.calls) == 1


@pytest.mark.parametrize(
    "final, expected",
    [(MallHttpResponse(404, b""), True), (MallHttpResponse(500, b""), False)],
)
def test_robots_redirect_chain_keeps_the_final_status_rules(final, expected):
    data = b"x"
    responses = [redirect("https://cdn.example.net/gone"), final]
    if expected:
        responses.append(MallHttpResponse(200, data))
    get = FakeGet(*responses)
    call = lambda: download_detail_image(
        "https://cdn.example.net/a.jpg", client=client(get), brand="cosrx", max_bytes=9
    )
    if expected:
        assert call() == data
    else:
        with pytest.raises(MallError, match="MALL_ROBOTS_UNREADABLE"):
            call()


def test_robots_redirect_hops_keep_the_host_interval():
    # Dalba's 10 second interval also spaces a redirected robots request that
    # stays on the same host.
    clock = Clock()
    data = b"x"
    get = FakeGet(
        redirect("https://dalba.co.kr/error.html"),
        HTML_ERROR_PAGE,
        MallHttpResponse(200, data),
    )
    download_detail_image(
        "https://dalba.co.kr/a.jpg",
        client=client(get, clock=clock),
        brand="dalba",
        max_bytes=9,
    )
    assert clock.waits == [10, 10]


def test_non_robots_requests_never_follow_redirects():
    get = FakeGet(robots(), redirect("https://elsewhere.example.net/"))
    with pytest.raises(MallError, match="MALL_HTTP_302"):
        client(get).fetch_product("mixsoon", "https://mixsoon.co.kr/product/1/")
    assert len(get.calls) == 2


def test_http_boundary_exposes_location_and_content_type_without_following(
    monkeypatch,
):
    from contextlib import contextmanager

    from beautyads.sources import mall as module

    seen = {}

    class Response:
        def __init__(self, status, headers, body=b""):
            self.status_code = status
            self.headers = headers
            self._body = body

        def iter_bytes(self, chunk_size=0):
            yield self._body

    answers = iter(
        [
            Response(302, {"location": "https://x.example.net/error.html"}),
            Response(200, {"content-type": "text/html; charset=utf-8"}, b"<html>"),
        ]
    )

    @contextmanager
    def stream(method, url, **kwargs):
        seen.update(kwargs)
        yield next(answers)

    monkeypatch.setattr(module.httpx, "stream", stream)
    redirected = httpx_mall_get("https://cdn.example.net/robots.txt", {}, 1.0, 10)
    assert redirected.status == 302
    assert redirected.location == "https://x.example.net/error.html"
    assert seen["follow_redirects"] is False
    final = httpx_mall_get("https://x.example.net/error.html", {}, 1.0, 10)
    assert final.status == 200 and final.content_type.startswith("text/html")


def test_accordion_ingredients_are_read_as_text_and_skip_the_image_path():
    # Real abib structure: <li>전성분<ul class="acco-inner"><li class="ingr2">...
    # The list is plain text (INCI names), so no detail image is needed.
    product = _product(
        "cafe24_accordion_ingredients.html",
        "abib",
        "https://abib.com/product/x/721/",
    )
    assert product.ingredients_text
    assert product.ingredients_text.startswith("Water (Aqua)")
    assert "," in product.ingredients_text
    assert product.detail_image_urls == ()


def test_accordion_with_an_empty_ingredient_list_is_not_text():
    body = re.sub(
        rb'(<li class="ingr2">).*?(</li>)',
        rb"\1 \2",
        recorded("cafe24_accordion_ingredients.html"),
        flags=re.DOTALL,
    )
    assert b"Water (Aqua)" not in body
    product = _product(None, "abib", "https://abib.com/product/x/721/", body=body)
    assert product.ingredients_text is None


def test_ingredients_in_a_popup_layer_are_read_as_text():
    # Real medicube structure: the 전성분 link opens <div class="dePop"> whose
    # <div class="depContent"> holds the list; the 주의사항 popup is another dePop.
    product = _product(
        "cafe24_popup_ingredients.html",
        "medicube",
        "https://themedicube.co.kr/product/detail.html?product_no=2698",
    )
    assert product.ingredients_text
    assert product.ingredients_text.startswith("정제수, 부틸렌글라이콜")
    assert "화장품 사용 시" not in product.ingredients_text  # not the caution popup
    assert product.detail_image_urls == ()


def test_an_empty_popup_ingredient_list_is_not_text():
    body = re.sub(
        rb'(<div class="depContent">)[^<]*(</div>\s*</div>\s*<!-- \.dePop -->\s*'
        rb'<div class="bgshadow">&nbsp;</div>\s*</div>\s*<div class="dePop_layer" '
        rb'id="cpopBody2">)',
        rb"\1 \2",
        recorded("cafe24_popup_ingredients.html"),
        count=1,
    )
    assert "정제수".encode() not in body
    product = _product(
        None,
        "medicube",
        "https://themedicube.co.kr/product/detail.html?product_no=2698",
        body=body,
    )
    assert product.ingredients_text is None
