"""The live CLI is assembled entirely with local fakes in these tests."""

import io
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from beautyads.domain import HookType, JobStatus
from beautyads.llm import (
    CostCapExceeded,
    DailyLimitReached,
    ErrorKind,
    InteractionResult,
    LlmCallError,
    UsageInfo,
)
from beautyads.obs import LedgerEntry, append_entry
from beautyads.pipeline import preflight as checks
from beautyads.pipeline import slice as cli
from beautyads.sources.config import YouTubeChannel
from beautyads.sources.youtube import HttpResponse
from beautyads.store import StoreConnectError

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/contracts"
STAMP = datetime(2026, 11, 12, tzinfo=UTC)
REQUIRED = ("YOUTUBE_API_KEY", "GEMINI_API_KEY", "POSTGRES_PASSWORD")


def body(name):
    return json.loads((FIXTURES / f"youtube_{name}.json").read_text()).get("response")


@pytest.fixture
def environment(tmp_path):
    return {
        **{name: uuid4().hex for name in REQUIRED},
        "BEAUTYADS_LEDGER_PATH": str(tmp_path / "manifest/costs.jsonl"),
    }


def preflight(environment, **kwargs):
    return checks.preflight(
        environ=environment,
        env_file=None,
        ledger_path=Path(environment["BEAUTYADS_LEDGER_PATH"]),
        caps={"gemini": 12.0},
        **{"docker_check": lambda: True, "tcp_check": lambda *args: True, **kwargs},
    )


@pytest.mark.parametrize("name", REQUIRED)
@pytest.mark.parametrize("value", [None, "", " \t "])
def test_preflight_missing_and_blank_settings(environment, name, value):
    if value is None:
        environment.pop(name)
    else:
        environment[name] = value
    assert preflight(environment) == [checks.Problem(f"ENV_MISSING:{name}")]


def test_preflight_collects_all_problems_without_values(environment):
    environment.pop("GEMINI_API_KEY")
    problems = preflight(
        environment, docker_check=lambda: False, tcp_check=lambda *args: False
    )
    assert [p.code for p in problems] == [
        "ENV_MISSING:GEMINI_API_KEY",
        "DOCKER_DOWN",
        "POSTGRES_UNREACHABLE",
    ]
    assert all(
        environment[name] not in repr(problems)
        for name in REQUIRED
        if name in environment
    )


def test_preflight_honors_settings_file_and_postgres_port(tmp_path):
    env_file = tmp_path / "settings"
    env_file.write_text("\n".join(f"{name}={uuid4().hex}" for name in REQUIRED))
    calls = []
    assert (
        checks.preflight(
            environ={"BEAUTYADS_POSTGRES_PORT": "15433"},
            env_file=env_file,
            ledger_path=tmp_path / "ledger/costs.jsonl",
            caps={"gemini": 12},
            docker_check=lambda: True,
            tcp_check=lambda *args: calls.append(args) or True,
        )
        == []
    )
    assert calls == [("127.0.0.1", 15433, 1.0)]


@pytest.mark.parametrize("total", [12.0, 13.0])
def test_preflight_checks_cumulative_cap(environment, total):
    path = Path(environment["BEAUTYADS_LEDGER_PATH"])
    for cost in (total / 2, total / 2):
        append_entry(
            path,
            LedgerEntry(
                ts=STAMP,
                provider="gemini",
                model="fake",
                purpose="test",
                cost_usd=cost,
                cost_source="computed",
            ),
        )
    assert preflight(environment) == [checks.Problem("COST_CAP:gemini")]


def test_preflight_normal_creates_writable_parent_and_checks_default_port(environment):
    calls = []
    assert (
        preflight(environment, tcp_check=lambda *args: calls.append(args) or True) == []
    )
    assert Path(environment["BEAUTYADS_LEDGER_PATH"]).parent.is_dir()
    assert calls == [("127.0.0.1", 5433, 1.0)]


def test_preflight_unwritable_ledger(environment, tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")
    environment["BEAUTYADS_LEDGER_PATH"] = str(blocked / "costs.jsonl")
    assert preflight(environment) == [checks.Problem("LEDGER_NOT_WRITABLE")]


@pytest.mark.parametrize("port", ["bad", "0", "65536"])
def test_preflight_invalid_port_is_safe(environment, port):
    environment["BEAUTYADS_POSTGRES_PORT"] = port
    calls = []
    assert preflight(environment, tcp_check=lambda *args: calls.append(args)) == [
        checks.Problem("POSTGRES_UNREACHABLE")
    ]
    assert calls == []


@pytest.mark.parametrize(
    "result", [0, 1, FileNotFoundError(), subprocess.TimeoutExpired("docker", 2)]
)
def test_docker_check_is_bounded_and_silent(monkeypatch, result):
    def run(*args, **kwargs):
        assert args == (["docker", "info"],)
        assert 0 < kwargs["timeout"] <= 5
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(returncode=result)

    monkeypatch.setattr(checks.subprocess, "run", run)
    assert checks.docker_running() is (result == 0)


@pytest.mark.parametrize("reachable", [False, True])
def test_tcp_check_uses_timeout_and_closes_socket(monkeypatch, reachable):
    closed = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed.append(True)

    def connect(address, timeout):
        assert address == ("127.0.0.1", 5433) and timeout == 0.1
        if not reachable:
            raise OSError()
        return Connection()

    monkeypatch.setattr(checks.socket, "create_connection", connect)
    assert checks.tcp_reachable("127.0.0.1", 5433, 0.1) is reachable
    assert closed == ([True] if reachable else [])


def main(environment, argv=(), **kwargs):
    out = io.StringIO()
    calls = []
    code = cli.main(
        argv,
        environ=environment,
        out=out,
        docker_check=lambda: True,
        tcp_check=lambda *args: True,
        **{"deps_factory": lambda: calls.append(True), **kwargs},
    )
    return code, out.getvalue(), calls


def test_main_missing_keys_never_builds_dependencies(environment):
    missing = {"BEAUTYADS_LEDGER_PATH": environment["BEAUTYADS_LEDGER_PATH"]}
    code, output, calls = main(missing)
    assert code == 2 and calls == []
    assert output.splitlines() == [
        f"PREFLIGHT_FAILED ENV_MISSING:{name}" for name in REQUIRED
    ]


@pytest.mark.parametrize("count", ["0", "6", "not-an-int"])
def test_main_rejects_count_before_checks(environment, count):
    code, _, calls = main(environment, ["--count", count])
    assert code == 2 and calls == []


def test_main_preflight_only_does_not_build_dependencies(environment):
    assert main(environment, ["--preflight-only"]) == (0, "", [])


@pytest.mark.parametrize("reason", ["POSTGRES_AUTH_FAILED", "POSTGRES_CONNECT_FAILED"])
def test_main_connection_failures_are_sanitized(environment, reason):
    sentinel_dsn = f"postgresql://beautyads:{environment['POSTGRES_PASSWORD']}@127.0.0.1:5433/beautyads"

    def fail():
        raise StoreConnectError(reason) from RuntimeError(sentinel_dsn)

    code, output, _ = main(environment, deps_factory=fail)
    assert code == 2
    assert output == f"PREFLIGHT_FAILED {reason}\n"
    assert sentinel_dsn not in output
    assert all(environment[name] not in output for name in REQUIRED)


class MemoryStore:
    def __init__(self):
        self.creatives = {}
        self.jobs = {}
        self.enqueued = []
        self.records = []

    def upsert_creatives(self, creatives):
        self.creatives.update((c.key, c) for c in creatives)
        return len(creatives)

    def get_creative(self, key):
        return self.creatives.get(key)

    def enqueue_analysis(self, kind, creatives):
        assert kind == "hook"
        assert all(c.analyzable is True for c in creatives)
        self.enqueued.extend(creatives)
        for c in creatives:
            self.jobs.setdefault(c.key, JobStatus.pending)
        return len(creatives)

    def next_pending(self, kind, limit):
        assert kind == "hook"
        return [
            self.creatives[key]
            for key, status in self.jobs.items()
            if status == JobStatus.pending
        ][:limit]

    def record_analysis(self, kind, key, **kwargs):
        assert kind == "hook"
        self.records.append((key, kwargs))
        self.jobs[key] = kwargs["status"]


class FakeGet:
    def __init__(self, *, first_error=None, unknown=False, oversized=False):
        self.calls = []
        self.first_error = first_error
        self.unknown = unknown
        self.oversized = oversized

    def __call__(self, url, params, timeout):
        self.calls.append((url, dict(params)))
        endpoint = url.rsplit("/", 1)[-1]
        if len(self.calls) == 1 and self.first_error:
            return self.first_error
        name = {
            "channels": "channels_forhandle",
            "playlistItems": "playlistitems",
            "videos": "videos",
        }[endpoint]
        response = body(name)
        if endpoint == "videos":
            if not self.oversized:
                response["items"] = [
                    item
                    for item in response.get("items")
                    if item.get("id") in params["id"].split(",")
                ]
            if self.unknown:
                response["items"][0].pop("contentDetails", None)
        return HttpResponse(200, response)


class FakeInteract:
    def __init__(self, *errors):
        self.calls = []
        self.errors = iter(errors)

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        error = next(self.errors, None)
        if error is not None:
            raise error
        return InteractionResult(
            json.dumps({"hook_type": next(iter(HookType)).value}),
            UsageInfo("fake", 0, 0, 0, 0, 0),
            {},
        )


def dependencies(get=None, interact=None, channels=1):
    item = body("channels_forhandle").get("items")[0]
    return cli.SliceDeps(
        get or FakeGet(),
        MemoryStore(),
        interact or FakeInteract(),
        [
            YouTubeChannel(
                brand="fixture",
                handle=f"@fixture-{i}",
                channel_id=item.get("id"),
                verified="fixture",
            )
            for i in range(channels)
        ],
        lambda: STAMP,
    )


def run(deps, environment, count=1, **kwargs):
    out = io.StringIO()
    report = cli.run_slice(
        deps,
        count=count,
        youtube_api_key=environment["YOUTUBE_API_KEY"],
        thinking_level="minimal",
        window_max_s=60,
        length_cut_s=600,
        ledger_path=Path(environment["BEAUTYADS_LEDGER_PATH"]),
        caps={"gemini": 12},
        out=out,
        **kwargs,
    )
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert lines[-1] == {"event": "summary", **report.model_dump(exclude={"items"})}
    assert lines[:-1] == report.items
    assert all(environment[name] not in out.getvalue() for name in REQUIRED)
    assert "googleapis.com" not in out.getvalue()
    assert all(
        set(item)
        == {"event", "source", "source_id", "url", "status", "hook_type", "error_code"}
        for item in report.items
    )
    return report


def test_slice_saves_metadata_and_queues_only_eligible(environment):
    deps = dependencies(FakeGet(unknown=True))
    report = run(deps, environment, count=3)
    assert report.collected == len(deps.store.creatives) == 3
    assert len(deps.store.enqueued) == len(deps.interact.calls) == 1
    assert {c.analyzable for c in deps.store.creatives.values()} == {True, False, None}
    assert report.analyzed["done"] == 1 and report.stopped is None
    assert all(c.collected_at == STAMP for c in deps.store.creatives.values())
    assert deps.interact.calls[0]["thinking_level"] == "minimal"


@pytest.mark.parametrize("count", [1, 2, 3, 5])
def test_slice_respects_count_even_if_response_is_oversized(environment, count):
    deps = dependencies(FakeGet(oversized=True), channels=2)
    report = run(deps, environment, count=count)
    assert report.collected == len(deps.store.creatives) <= count
    assert len(deps.interact.calls) <= count


def test_slice_forwards_collection_length_cut(environment):
    deps = dependencies()
    out = io.StringIO()
    report = cli.run_slice(
        deps,
        count=1,
        youtube_api_key=environment["YOUTUBE_API_KEY"],
        thinking_level="default",
        window_max_s=2,
        length_cut_s=10,
        ledger_path=Path(environment["BEAUTYADS_LEDGER_PATH"]),
        caps={"gemini": 12},
        out=out,
    )
    assert report.collected == 1 and not deps.interact.calls
    assert next(iter(deps.store.creatives.values())).analyzable is False


def test_slice_continues_after_channel_error(environment):
    deps = dependencies(
        FakeGet(first_error=HttpResponse(404, body("channels_forhandle_missing"))),
        channels=2,
    )
    report = run(deps, environment)
    assert report.collected == 1
    assert report.items[0]["error_code"] == "YOUTUBE_HTTP_404"
    handles = [
        params["forHandle"]
        for url, params in deps.http_get.calls
        if url.endswith("/channels")
    ]
    assert handles == [channel.handle for channel in deps.channels]


@pytest.mark.parametrize(
    "error,reason",
    [
        (
            DailyLimitReached(kind=ErrorKind.DAILY_LIMIT, code="DAILY_LIMIT"),
            "DAILY_LIMIT",
        ),
        (CostCapExceeded("gemini", 12, 12), "COST_CAP:gemini"),
        (LlmCallError(kind=ErrorKind.RATE_LIMIT, code="RATE_LIMIT"), "RATE_LIMITED"),
    ],
)
def test_slice_stop_retains_pending_and_emits_json(environment, error, reason):
    deps = dependencies(interact=FakeInteract(error))
    report = run(deps, environment, count=2)
    assert report.stopped == reason
    assert report.analyzed["pending"] == 2
    assert set(deps.store.jobs.values()) == {JobStatus.pending}
    assert not deps.store.records


def test_slice_key_error_stops_collection_and_paid_calls(environment):
    raw = json.loads((FIXTURES / "youtube_error_bad_key.json").read_text())
    deps = dependencies(
        FakeGet(first_error=HttpResponse(400, raw.get("response"))), channels=2
    )
    report = run(deps, environment)
    assert report.stopped == "YOUTUBE_KEY_INVALID"
    assert len(deps.http_get.calls) == 1 and not deps.interact.calls


@pytest.mark.parametrize("stopped", [False, True])
def test_main_runs_and_returns_stop_exit_code(environment, stopped):
    interact = (
        FakeInteract(DailyLimitReached(kind=ErrorKind.DAILY_LIMIT, code="DAILY_LIMIT"))
        if stopped
        else FakeInteract()
    )
    deps = dependencies(interact=interact)
    code, output, _ = main(environment, deps_factory=lambda: deps)
    assert code == (3 if stopped else 0)
    assert ("STOPPED DAILY_LIMIT" in output) is stopped
    assert len(deps.store.creatives) == 1


def test_main_default_factory_assembles_wrappers_and_closes_connection(
    environment, monkeypatch
):
    deps = dependencies()
    calls = []

    class Connection:
        def close(self):
            calls.append("closed")

    connection = Connection()

    def channels(path):
        assert path == Path("config/sources.yaml")
        calls.append("channels")
        return deps.channels

    def connect(dsn):
        assert environment["POSTGRES_PASSWORD"] in dsn
        calls.append("connect")
        return connection

    def migrate(conn):
        assert conn is connection
        calls.append("migrations")

    def store(conn):
        assert conn is connection
        calls.append("store")
        return deps.store

    def interact(**kwargs):
        assert kwargs.pop("api_key") == environment["GEMINI_API_KEY"]
        return deps.interact(**kwargs)

    monkeypatch.setattr(cli, "load_youtube_channels", channels)
    monkeypatch.setattr(cli, "connect", connect)
    monkeypatch.setattr(cli, "apply_migrations", migrate)
    monkeypatch.setattr(cli, "PostgresCreativeStore", store)
    monkeypatch.setattr(cli, "httpx_get", deps.http_get)
    monkeypatch.setattr(cli, "gemini_interact", interact)
    code, output, _ = main(environment, ["--count", "5"], deps_factory=None)
    assert code == 0
    assert calls == ["channels", "connect", "migrations", "store", "closed"]
    assert len(deps.store.creatives) == 3
    assert all(environment[name] not in output for name in REQUIRED)


def test_slice_partial_completion_preserves_remaining_jobs_and_total(environment):
    path = Path(environment["BEAUTYADS_LEDGER_PATH"])
    append_entry(
        path,
        LedgerEntry(
            ts=STAMP,
            provider="gemini",
            model="fake",
            purpose="test",
            cost_usd=0.25,
            cost_source="computed",
        ),
    )
    deps = dependencies(
        interact=FakeInteract(
            None, DailyLimitReached(kind=ErrorKind.DAILY_LIMIT, code="DAILY_LIMIT")
        )
    )
    report = run(deps, environment, count=2)
    assert report.analyzed == {"pending": 1, "done": 1, "held": 0, "failed": 0}
    assert report.gemini_total_usd == 0.25
    assert list(deps.store.jobs.values()) == [JobStatus.done, JobStatus.pending]
    completed = [item for item in report.items if item["status"] == "done"]
    assert len(completed) == 1
    assert completed[0]["hook_type"] in {member.value for member in HookType}


def test_makefile_keeps_live_out_of_verify():
    text = (ROOT / "Makefile").read_text()
    lines = text.splitlines()
    assert (
        "live-slice"
        in next(line for line in lines if line.startswith(".PHONY:")).split()
    )
    assert "live-slice:\n\tuv run python -m beautyads.pipeline.slice" in text
    recipe = text.split("verify:\n", 1)[1].split("\n\n", 1)[0]
    assert "live-" not in recipe
