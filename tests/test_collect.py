"""Collection runner contracts; all HTTP, clocks and persistence are local fakes."""

import io
import json
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from beautyads.domain import CollectionStat
from beautyads.pipeline import collect as cli
from beautyads.pipeline import preflight as checks
from beautyads.sources.config import InstagramAccount, YouTubeChannel
from beautyads.sources.instagram import InstagramError, InstagramHttpResponse
from beautyads.sources.split import BrandSplit, ResplitRule, VolumeConstraints
from beautyads.sources.youtube import HttpResponse, YouTubeError
from beautyads.store import StoreConnectError

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/contracts"
STAMP = datetime(2026, 11, 12, tzinfo=UTC)
REQUIRED = (
    "YOUTUBE_API_KEY",
    "INSTAGRAM_ACCESS_TOKEN",
    "INSTAGRAM_USER_ID",
    "POSTGRES_PASSWORD",
)


def body(name):
    return json.loads((FIXTURES / f"{name}.json").read_text()).get("response")


def channel(handle="@one", brand="dev-brand"):
    item = body("youtube_channels_forhandle").get("items")[0]
    return YouTubeChannel(
        brand=brand, handle=handle, channel_id=item.get("id"), verified="yes"
    )


def account(username="one", brand="test-brand"):
    return InstagramAccount(brand=brand, username=username)


@pytest.fixture
def split():
    return BrandSplit(
        registered_on="2026-11-12",
        seed=1,
        attempt=0,
        dev_size=1,
        brands=["dev-brand", "test-brand"],
        dev=["dev-brand"],
        test=["test-brand"],
        static_constraints=[],
        volume=VolumeConstraints(),
        resplit=ResplitRule(),
    )


class FakeGet:
    def __init__(self, *responses):
        self.responses = deque(responses)
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        response = self.responses.popleft()
        if isinstance(response, BaseException):
            raise response
        return response


def youtube_success():
    playlist = body("youtube_playlistitems")
    playlist.pop("nextPageToken", None)
    videos = body("youtube_videos")
    # Synthesize all eligibility cases while retaining the recorded structure.
    items = videos.get("items")
    for index, duration in enumerate(("PT30S", "PT20M", None)):
        item = json.loads(json.dumps(items[0]))
        item["id"] = f"clip-{index}"
        item["contentDetails"]["duration"] = duration
        item["snippet"]["liveBroadcastContent"] = "none"
        if index < len(items):
            items[index] = item
        else:
            items.append(item)
    videos["items"] = items[:3]
    return [
        HttpResponse(200, body("youtube_channels_forhandle")),
        HttpResponse(200, playlist),
        HttpResponse(200, videos),
    ]


def instagram_success():
    response = body("instagram_business_discovery_with_media_url")
    media = response.get("business_discovery").get("media")
    media.get("paging").get("cursors").pop("after", None)
    for post in media.get("data"):
        if "media_url" in post:
            post["media_url"] = "https://example.invalid/" + uuid4().hex
    return InstagramHttpResponse(200, response, {})


class MemoryStore:
    def __init__(self, stats=()):
        self.creatives = {}
        self.batches = []
        self.initial_stats = list(stats)

    def upsert_creatives(self, creatives):
        self.batches.append(list(creatives))
        self.creatives.update((item.key, item) for item in creatives)
        return len(creatives)

    def collection_stats(self):
        groups = {}
        for item in self.creatives.values():
            key = (item.source, item.brand, item.account)
            groups.setdefault(key, []).append(item)
        return self.initial_stats + [
            CollectionStat(
                source=source,
                brand=brand,
                account=account,
                total=len(items),
                analyzable_true=sum(item.analyzable is True for item in items),
                analyzable_false=sum(item.analyzable is False for item in items),
                analyzable_null=sum(item.analyzable is None for item in items),
                last_collected_at=max(item.collected_at for item in items),
            )
            for (source, brand, account), items in groups.items()
        ]


def stat(source="youtube", brand="dev-brand", account="@one", count=2, hours=1):
    return CollectionStat(
        source=source,
        brand=brand,
        account=account,
        total=count,
        analyzable_true=count,
        analyzable_false=0,
        analyzable_null=0,
        last_collected_at=STAMP - timedelta(hours=hours),
    )


def deps(youtube=None, instagram=None, store=None):
    return cli.CollectDeps(
        youtube or FakeGet(*youtube_success()),
        instagram or FakeGet(instagram_success()),
        store or MemoryStore(),
        lambda: STAMP,
        lambda _: None,
    )


def run(dependencies, split, **kwargs):
    options = {
        "sources": ["youtube", "instagram"],
        "youtube_api_key": uuid4().hex,
        "instagram_token": uuid4().hex,
        "ig_user_id": "caller",
        "instagram_base_url": "https://example.invalid/v21.0",
        "youtube_channels": [channel()],
        "instagram_accounts": [account()],
        "max_per_account": 150,
        "skip_recent_hours": 0,
        "only_accounts": None,
        "video_length_cut_s": 600,
        "split": split,
        "out": io.StringIO(),
    }
    options.update(kwargs)
    return cli.run_collect(dependencies, **options)


@pytest.mark.parametrize(
    "failures",
    [
        [HttpResponse(503, None), HttpResponse(503, None)],
        [
            InstagramError("INSTAGRAM_REQUEST_FAILED"),
            InstagramError("INSTAGRAM_REQUEST_FAILED"),
        ],
        [
            YouTubeError("YOUTUBE_REQUEST_FAILED"),
            YouTubeError("YOUTUBE_REQUEST_FAILED"),
        ],
    ],
)
def test_retry_then_success(failures):
    response = HttpResponse(200, {})
    get = FakeGet(*failures, response)
    sleeps = []
    wrapped = cli.with_retries(get, backoff_s=(0.1, 0.4, 0.9), sleep=sleeps.append)
    assert wrapped("url", {}, 30) is response
    assert len(get.calls) == 3
    assert sleeps == [0.1, 0.4]
    assert get.calls[0] == (("url", {}, 30), {})


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 200])
def test_nonretry_status(status):
    response = HttpResponse(status, {})
    get = FakeGet(response)
    assert (
        cli.with_retries(get, sleep=lambda _: pytest.fail("slept"))(1, 2, 3) is response
    )
    assert len(get.calls) == 1


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_retry_exhaustion_returns_last_response(status):
    responses = [HttpResponse(status, {"attempt": i}) for i in range(3)]
    get = FakeGet(*responses)
    sleeps = []
    assert cli.with_retries(get, sleep=sleeps.append)(1, 2, 3) is responses[-1]
    assert sleeps == [2.0, 5.0]


@pytest.mark.parametrize(
    "error", [ValueError("unexpected"), InstagramError("INSTAGRAM_TOKEN_INVALID")]
)
def test_other_exceptions_are_not_retried(error):
    get = FakeGet(error)
    with pytest.raises(type(error)) as caught:
        cli.with_retries(get, sleep=lambda _: pytest.fail("slept"))(1, 2, 3)
    assert caught.value is error
    assert len(get.calls) == 1


@pytest.mark.parametrize(
    "error_type,code",
    [
        (YouTubeError, "YOUTUBE_REQUEST_FAILED"),
        (InstagramError, "INSTAGRAM_REQUEST_FAILED"),
    ],
)
def test_last_exception_is_reraised(error_type, code):
    errors = [error_type(code) for _ in range(3)]
    get = FakeGet(*errors)
    with pytest.raises(error_type) as caught:
        cli.with_retries(get, sleep=lambda _: None)(1, 2, 3)
    assert caught.value is errors[-1]
    assert len(get.calls) == 3


def test_account_failure_isolated_and_counts_match(split):
    get = FakeGet(
        HttpResponse(200, body("youtube_channels_forhandle_missing")),
        *youtube_success(),
    )
    dependencies = deps(youtube=get)
    out = io.StringIO()
    report = run(
        dependencies, split, youtube_channels=[channel("@missing"), channel()], out=out
    )
    assert report.accounts[0].error == "CHANNEL_NOT_FOUND"
    assert len(dependencies.store.creatives) > 0
    assert len(dependencies.store.batches) >= 2
    for result in report.accounts[1:]:
        items = [
            item
            for item in dependencies.store.creatives.values()
            if item.source.value == result.source and item.account == result.account
        ]
        assert result.fetched == len(items)
        assert result.analyzable_true == sum(item.analyzable is True for item in items)
        assert result.analyzable_false == sum(
            item.analyzable is False for item in items
        )
        assert result.analyzable_null == sum(item.analyzable is None for item in items)
        assert all(item.brand and item.account for item in items)
    assert report.accounts[1].analyzable_true == 1
    assert report.accounts[1].analyzable_false == 1
    assert report.accounts[1].analyzable_null == 1
    events = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [event["event"] for event in events] == [
        "account",
        "account",
        "account",
        "summary",
    ]


def test_each_account_is_saved_before_next_request_and_interrupt(split):
    dependencies = deps()
    original = dependencies.youtube_get

    def get(url, params, timeout_s):
        if params.get("forHandle") == "@second":
            assert dependencies.store.batches
            assert dependencies.store.creatives
            raise KeyboardInterrupt()
        return original(url, params, timeout_s)

    dependencies = dependencies._replace(youtube_get=get)
    with pytest.raises(KeyboardInterrupt):
        run(dependencies, split, youtube_channels=[channel(), channel("@second")])
    assert len(dependencies.store.creatives) == 3


def test_unexpected_account_exception_is_safe_and_continues(split):
    secret = uuid4().hex
    dependencies = deps(youtube=FakeGet(RuntimeError(secret), *youtube_success()))
    out = io.StringIO()
    report = run(
        dependencies, split, youtube_channels=[channel("@bad"), channel()], out=out
    )
    assert report.accounts[0].error
    assert report.accounts[1].fetched == 3
    assert secret not in out.getvalue() + report.model_dump_json()


def test_youtube_quota_only_stops_youtube(split):
    error = body("youtube_error_bad_key")
    error["error"]["errors"] = [{"reason": "quotaExceeded"}]
    dependencies = deps(youtube=FakeGet(HttpResponse(403, error)))
    report = run(dependencies, split, youtube_channels=[channel(), channel("@later")])
    assert report.stopped == {"youtube": "YOUTUBE_QUOTA"}
    assert len(dependencies.youtube_get.calls) == 1
    assert any(
        item.source.value == "instagram"
        for item in dependencies.store.creatives.values()
    )


@pytest.mark.parametrize(
    "code,status,reason",
    [(4, 429, "INSTAGRAM_RATE_LIMITED"), (190, 400, "INSTAGRAM_TOKEN_INVALID")],
)
def test_instagram_stop_does_not_stop_youtube_or_call_later_accounts(
    split, code, status, reason
):
    error = body("instagram_error_bad_token")
    error["error"]["code"] = code
    dependencies = deps(instagram=FakeGet(InstagramHttpResponse(status, error, {})))
    report = run(
        dependencies,
        split,
        sources=["instagram", "youtube"],
        instagram_accounts=[account(), account("later")],
    )
    assert report.stopped == {"instagram": reason}
    assert len(dependencies.instagram_get.calls) == 1
    assert any(
        item.source.value == "youtube" for item in dependencies.store.creatives.values()
    )


def test_usage_high_stops_next_and_discards_partial_account(split):
    usage = {"call_count": 12, "total_cputime": 80, "total_time": 31}
    response = instagram_success()._replace(headers={"x-app-usage": json.dumps(usage)})
    dependencies = deps(instagram=FakeGet(response))
    out = io.StringIO()
    report = run(
        dependencies,
        split,
        sources=["instagram"],
        instagram_accounts=[account(), account("later")],
        out=out,
    )
    assert report.stopped == {"instagram": "INSTAGRAM_USAGE_HIGH"}
    assert len(dependencies.instagram_get.calls) == 1
    last = report.accounts[-1]
    # 받았지만 불완전하므로 저장하지 않는다(skip-recent가 완료로 오인하지 않게).
    assert last.fetched > 0 and last.stored is False
    assert not dependencies.store.creatives
    # 세 지표를 각각 기록해 어느 지표가 한도를 채웠는지 다음 실행에서 볼 수 있다.
    assert last.usage == {key: float(value) for key, value in usage.items()}
    summary = json.loads(out.getvalue().splitlines()[-1])
    assert summary["instagram_last_usage"] == last.usage


def test_partial_account_is_collected_again_with_skip_recent(split):
    usage_high = instagram_success()._replace(
        headers={"x-app-usage": json.dumps({"call_count": 90})}
    )
    first = deps(instagram=FakeGet(usage_high))
    run(first, split, sources=["instagram"], instagram_accounts=[account()])
    # 첫 실행이 남긴 저장 상태(없음)를 다음 실행의 store로 넘겨도 계정을 건너뛰지 않는다.
    second = deps(
        instagram=FakeGet(instagram_success()),
        store=MemoryStore(first.store.collection_stats()),
    )
    report = run(
        second,
        split,
        sources=["instagram"],
        instagram_accounts=[account()],
        skip_recent_hours=24,
    )
    assert report.accounts[0].skipped is False
    assert report.accounts[0].stored is True
    assert second.instagram_get.calls


def test_skip_recent_and_account_filter(split):
    dependencies = deps(store=MemoryStore([stat()]))
    report = run(
        dependencies,
        split,
        skip_recent_hours=2,
        only_accounts=["@one", "one"],
        youtube_channels=[channel(), channel("@excluded")],
        instagram_accounts=[account(), account("excluded")],
    )
    assert [(r.account, r.skipped) for r in report.accounts] == [
        ("@one", True),
        ("one", False),
    ]
    assert not dependencies.youtube_get.calls
    assert dependencies.instagram_get.calls


@pytest.mark.parametrize("hours", [0, 0.5])
def test_resume_disabled_or_old_collects_again(split, hours):
    dependencies = deps(store=MemoryStore([stat()]))
    report = run(dependencies, split, sources=["youtube"], skip_recent_hours=hours)
    assert not report.accounts[0].skipped
    assert dependencies.youtube_get.calls


def test_reports_never_include_credentials_or_media_urls(split):
    key, token, marker = uuid4().hex, uuid4().hex, uuid4().hex
    response = instagram_success()
    for post in response.body.get("business_discovery").get("media").get("data"):
        post["media_url"] = f"https://example.invalid/video?secret={marker}"
    out = io.StringIO()
    report = run(
        deps(instagram=FakeGet(response)),
        split,
        youtube_api_key=key,
        instagram_token=token,
        out=out,
    )
    rendered = out.getvalue() + report.model_dump_json()
    assert all(
        value not in rendered for value in (key, token, marker, "media_url", "?secret=")
    )


@pytest.mark.parametrize(
    "maximum,yt,ig",
    [(1, 3, 1), (50, 3, 1), (51, 5, 1), (100, 5, 1), (101, 7, 2), (150, 7, 2)],
)
def test_estimate_hand_calculations(maximum, yt, ig):
    result = cli.estimate(
        youtube_accounts=2, instagram_accounts=3, max_per_account=maximum
    )
    assert result["youtube_calls"] == yt * 2
    assert result["instagram_calls"] == ig * 3
    assert result["total_calls"] == yt * 2 + ig * 3
    assert result["estimated_minutes"] == pytest.approx((yt * 2 + ig * 6) / 60)
    assert result["instagram_app_usage_pct"] == ig * 1.5


@pytest.fixture
def environment():
    return {name: uuid4().hex for name in REQUIRED}


@pytest.fixture
def config(monkeypatch, split):
    monkeypatch.setattr(cli, "load_youtube_channels", lambda _: [channel()])
    monkeypatch.setattr(cli, "load_instagram_accounts", lambda _: [account()])
    monkeypatch.setattr(cli, "load_brand_split", lambda _: split)


def main(args=(), **kwargs):
    return cli.main(
        args, docker_check=lambda: True, tcp_check=lambda *args: True, **kwargs
    )


def test_dry_run_calls_no_dependencies_or_checks(config):
    out = io.StringIO()

    def forbidden(*args):
        pytest.fail("dry run touched a live dependency")

    assert (
        cli.main(
            ["--dry-run"],
            environ={},
            out=out,
            deps_factory=forbidden,
            docker_check=forbidden,
            tcp_check=forbidden,
        )
        == 0
    )
    text = out.getvalue()
    assert len(text.splitlines()) == 1 and text.startswith("ESTIMATE ")
    assert "호출당 시간은 가정(미실측)" in text
    assert "YouTube 쿼터 사용량은 미확인(Cloud 콘솔에서 확인)" in text
    assert "호출당 앱 사용량 0.5%는 과소추정이었다" in text


def test_dry_run_filters_sources_and_accounts(config):
    out = io.StringIO()
    assert (
        main(
            [
                "--dry-run",
                "--sources",
                "youtube",
                "--accounts",
                "@one",
                "--max-per-account",
                "51",
            ],
            environ={},
            out=out,
        )
        == 0
    )
    payload = json.loads(out.getvalue().removeprefix("ESTIMATE "))
    assert payload["youtube_calls"] == 5
    assert payload["instagram_calls"] == 0


@pytest.mark.parametrize("name", REQUIRED)
@pytest.mark.parametrize("value", [None, "", " \t "])
def test_main_missing_env_before_dependencies(environment, name, value):
    if value is None:
        environment.pop(name)
    else:
        environment[name] = value
    out = io.StringIO()
    assert (
        main(
            environ=environment,
            out=out,
            deps_factory=lambda: pytest.fail("created deps"),
        )
        == 2
    )
    assert f"PREFLIGHT_FAILED ENV_MISSING:{name}" in out.getvalue()


@pytest.mark.parametrize(
    "source,required",
    [("youtube", "YOUTUBE_API_KEY"), ("instagram", "INSTAGRAM_ACCESS_TOKEN")],
)
def test_preflight_only_requires_selected_sources(environment, source, required):
    names = [required, "POSTGRES_PASSWORD"]
    if source == "instagram":
        names.append("INSTAGRAM_USER_ID")
    env = {name: environment[name] for name in names}
    assert (
        checks.collect_preflight(
            sources=[source],
            environ=env,
            env_file=None,
            docker_check=lambda: True,
            tcp_check=lambda *args: True,
        )
        == []
    )


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--max-per-account", "0"),
        ("--max-per-account", "1001"),
        ("--skip-recent-hours", "nan"),
        ("--sources", "tiktok"),
    ],
)
def test_invalid_arguments_before_dependencies(flag, value):
    assert (
        main([flag, value], environ={}, deps_factory=lambda: pytest.fail("deps")) == 2
    )


@pytest.mark.parametrize(
    "docker,tcp,reason",
    [(False, True, "DOCKER_DOWN"), (True, False, "POSTGRES_UNREACHABLE")],
)
def test_preflight_infrastructure_before_dependencies(environment, docker, tcp, reason):
    out = io.StringIO()
    assert (
        cli.main(
            environ=environment,
            out=out,
            docker_check=lambda: docker,
            tcp_check=lambda *args: tcp,
            deps_factory=lambda: pytest.fail("deps"),
        )
        == 2
    )
    assert f"PREFLIGHT_FAILED {reason}" in out.getvalue()


@pytest.mark.parametrize("code", ["POSTGRES_AUTH_FAILED", "POSTGRES_CONNECT_FAILED"])
def test_store_connect_error_safe(config, environment, code):
    def factory():
        raise StoreConnectError(code) from RuntimeError(
            "postgresql://" + environment["POSTGRES_PASSWORD"]
        )

    out = io.StringIO()
    assert main(environ=environment, out=out, deps_factory=factory) == 2
    assert out.getvalue() == f"PREFLIGHT_FAILED {code}\n"
    assert environment["POSTGRES_PASSWORD"] not in out.getvalue()


def test_main_stopped_exit_code(config, environment):
    get = FakeGet(HttpResponse(400, body("youtube_error_bad_key")))
    assert (
        main(
            environ=environment,
            out=io.StringIO(),
            deps_factory=lambda: deps(youtube=get),
        )
        == 3
    )


def test_split_summary_uses_all_stats_and_unassigned(config, environment):
    store = MemoryStore(
        [
            stat(count=10),
            stat(source="instagram", brand="test-brand", account="past", count=20),
            stat(brand="test-brand", account="@past", count=30),
            stat(brand="unknown", count=7),
            stat(brand=None, count=4),
        ]
    )
    out = io.StringIO()
    assert (
        main(
            ["--accounts", "absent"],
            environ=environment,
            out=out,
            deps_factory=lambda: deps(store=store),
        )
        == 0
    )
    summary = json.loads(out.getvalue().splitlines()[-1])
    assert summary["split_analyzable_true"] == {"dev": 10, "test": 50, "unassigned": 11}
    assert "SPLIT_VOLUME_INSUFFICIENT" in out.getvalue()
    assert summary["volume_violations"]
    assert sum(row["analyzable_true"] for row in summary["by_source_brand"]) == 71


def test_makefile_only_adds_live_target():
    text = (ROOT / "Makefile").read_text()
    assert "live-collect:\n\tuv run python -m beautyads.pipeline.collect" in text
    assert "live-collect" in text.splitlines()[0].split()
    recipe = text.split("verify:\n", 1)[1].split("\n\n", 1)[0]
    assert "live-" not in recipe
