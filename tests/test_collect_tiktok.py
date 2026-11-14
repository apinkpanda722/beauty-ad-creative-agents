"""Separate TikTok runner: contract-derived HTTP bodies and local fakes only."""

import io
import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from beautyads.pipeline import collect_tiktok as cli
from beautyads.sources.tiktok import TikTokError, TikTokHttpResponse
from beautyads.store import StoreConnectError

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/contracts"
NOW = datetime(2026, 11, 14, tzinfo=UTC)
REQUIRED = ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "POSTGRES_PASSWORD")


def body(name):
    return json.loads((FIXTURES / name).read_text()).get("response")


def page(*, names=("Mixsoon Limited", "Etos B.V.", "12345"), more=False):
    response = body("tiktok_ad_query.json")
    response["data"]["ads"] = response["data"]["ads"][: len(names)]
    response["data"]["has_more"] = more
    for item, name in zip(response["data"]["ads"], names, strict=True):
        item["advertiser"]["business_name"] = name
        # Replace all fixture media with ephemeral, noncredential sentinels.
        item["ad"]["videos"] = [{"url": "https://example.invalid/" + uuid4().hex}]
        item["ad"].pop("image_urls", None)
    return TikTokHttpResponse(200, response)


def failure(status):
    response = body("tiktok_error_bad_token.json")
    response["error"]["message"] = uuid4().hex
    if status != 401:
        response["error"]["code"] = (
            "invalid_params" if status == 400 else "internal_error"
        )
    return TikTokHttpResponse(status, response)


class FakePost:
    def __init__(self, *responses):
        self.responses = deque(responses)
        self.calls = []
        self.before_call = lambda: None

    def __call__(self, url, params, json_body, form_body, timeout_s):
        self.before_call()
        self.calls.append((json_body.get("search_term"), json_body.get("search_id")))
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


class MemoryStore:
    def __init__(self):
        self.batches = []

    def upsert_creatives(self, creatives):
        self.batches.append(list(creatives))
        return len(creatives)

    @property
    def creatives(self):
        return [item for batch in self.batches for item in batch]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    sources = tmp_path / "sources.yaml"
    sources.write_text(
        "tiktok:\n  countries: [DE, FR]\n  lookback_days: 330\n"
        "  search_type: exact_phrase\n  brands:\n"
        "    - {brand: mixsoon, search_term: mixsoon}\n"
        "    - {brand: dalba, search_term: dalba}\n"
        "    - {brand: anua, search_term: anua}\n"
    )
    retailers = tmp_path / "retailers.yaml"
    retailers.write_text("retailers: [etos, sephora]\n")
    monkeypatch.setattr(cli, "SOURCES_PATH", sources)
    monkeypatch.setattr(cli, "RETAILERS_PATH", retailers)
    providers = []

    class FakeProvider:
        def __init__(self, post, *, client_key, client_secret, now):
            self.calls = 0
            self.value = uuid4().hex
            self.error = None
            providers.append(self)

        def token(self):
            self.calls += 1
            if self.error:
                raise TikTokError(self.error)
            return self.value

        def invalidate(self):
            pass

    monkeypatch.setattr(cli, "TokenProvider", FakeProvider)
    monkeypatch.setattr(cli, "tiktok_httpx_post", forbidden)
    monkeypatch.setattr(cli, "connect", forbidden)
    return sources, retailers, providers


def forbidden(*args, **kwargs):
    pytest.fail("unexpected dependency creation or live access")


@pytest.fixture
def environment():
    return {name: uuid4().hex for name in REQUIRED}


def invoke(environment, post, store, args=(), **kwargs):
    out = io.StringIO()
    code = cli.main(
        args,
        environ=environment,
        out=out,
        docker_check=kwargs.pop("docker_check", lambda: True),
        tcp_check=kwargs.pop("tcp_check", lambda *args: True),
        deps_factory=kwargs.pop(
            "deps_factory", lambda: cli.TikTokCollectDeps(post, store, lambda: NOW)
        ),
        **kwargs,
    )
    return code, out.getvalue()


def records(text):
    return [json.loads(line) for line in text.splitlines()]


@pytest.mark.parametrize("name", REQUIRED)
@pytest.mark.parametrize("value", [None, "", " \t "])
def test_missing_settings_before_any_dependencies(setup, environment, name, value):
    if value is None:
        environment.pop(name)
    else:
        environment[name] = value
    post = FakePost()
    code, text = invoke(
        environment,
        post,
        MemoryStore(),
        deps_factory=forbidden,
        docker_check=forbidden,
        tcp_check=forbidden,
    )
    assert code == 2 and f"PREFLIGHT_FAILED ENV_MISSING:{name}" in text
    assert not post.calls and not setup[2]
    assert all(v.strip() not in text for v in environment.values() if v.strip())


@pytest.mark.parametrize(
    "docker,tcp,reason",
    [(False, True, "DOCKER_DOWN"), (True, False, "POSTGRES_UNREACHABLE")],
)
def test_infrastructure_preflight(setup, environment, docker, tcp, reason):
    post = FakePost()
    code, text = invoke(
        environment,
        post,
        MemoryStore(),
        docker_check=lambda: docker,
        tcp_check=(lambda *args: tcp) if docker else forbidden,
        deps_factory=forbidden,
    )
    assert code == 2 and text == f"PREFLIGHT_FAILED {reason}\n"
    assert not post.calls and not setup[2]


@pytest.mark.parametrize("port", ["no", "0", "65536"])
def test_invalid_postgres_port(setup, environment, port):
    environment["BEAUTYADS_POSTGRES_PORT"] = port
    code, text = invoke(
        environment,
        FakePost(),
        MemoryStore(),
        tcp_check=forbidden,
        deps_factory=forbidden,
    )
    assert code == 2 and "POSTGRES_UNREACHABLE" in text
    assert not setup[2]


@pytest.mark.parametrize(
    "index,contents,reason",
    [
        (0, None, "TIKTOK_CONFIG_UNREADABLE"),
        (0, "tiktok: {brands: []}", "TIKTOK_CONFIG_INVALID"),
        (0, "[", "TIKTOK_CONFIG_UNREADABLE"),
        (1, None, "RETAILERS_CONFIG_UNREADABLE"),
        (1, "retailers: [null]", "RETAILERS_CONFIG_INVALID"),
    ],
)
def test_config_preflight(setup, environment, index, contents, reason):
    if contents is None:
        setup[index].unlink()
    else:
        setup[index].write_text(contents)
    post = FakePost()
    code, text = invoke(
        environment,
        post,
        MemoryStore(),
        deps_factory=forbidden,
        docker_check=forbidden,
        tcp_check=forbidden,
    )
    assert code == 2 and text == f"PREFLIGHT_FAILED {reason}\n"
    assert not post.calls and not setup[2]


@pytest.mark.parametrize("reason", ["POSTGRES_AUTH_FAILED", "POSTGRES_CONNECT_FAILED"])
def test_store_connect_error_is_safe(setup, environment, reason):
    def factory():
        raise StoreConnectError(reason) from RuntimeError(
            "postgresql://" + environment["POSTGRES_PASSWORD"]
        )

    code, text = invoke(environment, FakePost(), MemoryStore(), deps_factory=factory)
    assert code == 2 and text == f"PREFLIGHT_FAILED {reason}\n"
    assert environment["POSTGRES_PASSWORD"] not in text and not setup[2]


def test_only_complete_brands_saved_and_progress_is_immediate(
    setup, environment, monkeypatch
):
    # a 500 is retried three times before the brand fails (no real waiting here)
    monkeypatch.setattr("beautyads.sources.tiktok._BACKOFF_S", (0.0, 0.0, 0.0))
    store = MemoryStore()
    good, partial = page(), page(more=True)
    post = FakePost(
        good,
        partial,
        *[failure(500) for _ in range(4)],
        page(names=("Anua Limited",)),
    )

    def check_progress():
        if post.calls:
            assert len(store.batches) >= 1

    post.before_call = check_progress
    code, text = invoke(environment, post, store, ["--max-pages", "2"])
    assert code == 3
    assert [c.brand for c in store.creatives] == ["mixsoon"] * 3
    # The overlapping ad in anua was already stored; failed dalba stores nothing.
    assert all(
        batch and all(c.brand != "dalba" for c in batch) for batch in store.batches
    )
    rows = records(text)
    assert [r["brand"] for r in rows[:-1]] == ["mixsoon", "dalba", "anua"]
    assert rows[1]["error"] == "TIKTOK_HTTP_500" and rows[1]["stored"] == 0
    assert rows[-1]["errors"] == {"dalba": "TIKTOK_HTTP_500"}
    assert rows[-1]["stopped"] is None


def test_deduplication_brand_and_no_media_persistence(setup, environment):
    first, second = page(more=True), page()
    markers = [item["ad"]["videos"][0]["url"] for item in first.body["data"]["ads"]]
    store = MemoryStore()
    code, text = invoke(
        environment,
        FakePost(first, second),
        store,
        ["--brands", "mixsoon", "--max-pages", "2"],
    )
    assert code == 0 and len(store.creatives) == 3
    assert len({c.key for c in store.creatives}) == 3
    assert all(c.brand == "mixsoon" and c.url is None for c in store.creatives)
    serialized = text + "".join(c.model_dump_json() for c in store.creatives)
    assert all(marker not in serialized for marker in markers)


@pytest.mark.parametrize("status", [400, 401, 429])
def test_stop_preserves_finished_brand_and_skips_later(setup, environment, status):
    responses = [page(), failure(status)]
    if status == 401:
        responses.append(failure(status))  # Existing adapter's single refresh.
    post, store = FakePost(*responses), MemoryStore()
    code, text = invoke(environment, post, store)
    expected = {
        400: "TIKTOK_INVALID_PARAMS",
        401: "TIKTOK_TOKEN_INVALID",
        429: "TIKTOK_HTTP_429",
    }[status]
    assert code == 3 and records(text)[-1]["stopped"] == expected
    assert all(term != "anua" for term, _ in post.calls)
    assert len(post.calls) == (3 if status == 401 else 2)
    assert len(store.creatives) == 3 and all(
        c.brand == "mixsoon" for c in store.creatives
    )


def test_token_issue_failure_stops_without_post(setup, environment, monkeypatch):
    original = cli.TokenProvider

    def token(*args, **kwargs):
        provider = original(*args, **kwargs)
        provider.error = "TIKTOK_TOKEN_INVALID"
        return provider

    monkeypatch.setattr(cli, "TokenProvider", token)
    post, store = FakePost(), MemoryStore()
    code, text = invoke(environment, post, store)
    assert code == 3 and not post.calls and not store.creatives
    assert records(text)[-1]["stopped"] == "TIKTOK_TOKEN_INVALID"
    assert len(setup[2]) == 1 and setup[2][0].calls == 1


def test_default_one_page_and_brand_filter(setup, environment):
    post, store = FakePost(page(more=True)), MemoryStore()
    code, text = invoke(environment, post, store, ["--brands", " mixsoon,mixsoon "])
    assert code == 0 and post.calls == [("mixsoon", None)]
    assert records(text)[-1]["by_brand"] == {"mixsoon": 3}


@pytest.mark.parametrize("value", ["0", "51", "abc"])
def test_invalid_max_pages_before_checks(setup, value):
    code, _ = invoke(
        {},
        FakePost(),
        MemoryStore(),
        ["--max-pages", value],
        deps_factory=forbidden,
        docker_check=forbidden,
        tcp_check=forbidden,
    )
    assert code == 2 and not setup[2]


def test_reports_counts_and_no_credentials_or_video_urls(setup, environment):
    response = page(names=("Mixsoon Limited", "Etos B.V.", "12345"))
    post, store = FakePost(response), MemoryStore()
    code, text = invoke(environment, post, store, ["--brands", "mixsoon"])
    assert code == 0
    rows = records(text)
    expected = {"brand_direct": 1, "retailer": 1, "unknown": 1}
    assert rows[0]["event"] == "brand" and rows[0]["executor"] == expected
    summary = rows[-1]
    assert summary["event"] == "summary" and summary["executor"] == expected
    assert (
        summary["retailers_path"] == str(setup[1]) and summary["retailers_count"] == 2
    )
    assert summary["elapsed_s"] >= 0
    markers = list(environment.values()) + [setup[2][0].value, "Authorization"]
    markers += [item["ad"]["videos"][0]["url"] for item in response.body["data"]["ads"]]
    assert all(marker not in text for marker in markers)


def test_unexpected_exception_diagnostics_are_not_printed(setup, environment):
    marker = uuid4().hex
    post = FakePost(RuntimeError(marker), page(), page())
    code, text = invoke(environment, post, MemoryStore())
    assert code == 3 and marker not in text
    assert records(text)[0]["error"] == "COLLECTION_BRAND_FAILED"


@pytest.mark.parametrize(
    "args,minimum,maximum",
    [((), 3, 3), (["--brands", "mixsoon", "--max-pages", "4"], 1, 4)],
)
def test_dry_run_without_environment_or_any_dependencies(setup, args, minimum, maximum):
    code, text = invoke(
        {},
        FakePost(),
        MemoryStore(),
        ["--dry-run", *args],
        deps_factory=forbidden,
        docker_check=forbidden,
        tcp_check=forbidden,
    )
    assert code == 0 and len(text.splitlines()) == 1 and text.startswith("ESTIMATE ")
    payload = json.loads(text.removeprefix("ESTIMATE "))
    assert (payload["min_calls"], payload["max_calls"]) == (minimum, maximum)
    assert "호출당 시간은 가정(미실측)" in text and not setup[2]


def test_makefile_new_target_and_verify_contract():
    text = (ROOT / "Makefile").read_text()
    assert (
        "live-tiktok:\n\tuv run python -m beautyads.pipeline.collect_tiktok $(ARGS)"
        in text
    )
    assert "live-tiktok" in text.splitlines()[0].split()
    assert "live-" not in text.split("verify:\n", 1)[1].split("\n\n", 1)[0]
