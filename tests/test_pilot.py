"""Pilot CLI checks and orchestration use synthetic stores and temporary artifacts."""

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from beautyads.domain import CollectionStat, Creative, JobResult, JobStatus, Source
from beautyads.eval import pilot_run as pilot
from beautyads.llm import CostCapExceeded, DailyLimitReached, ErrorKind
from beautyads.obs.ledger import LedgerEntry, append_entry
from beautyads.pipeline import analyze
from beautyads.pipeline.media_flow import AxisRecord, CreativeOutcome, MediaDeps
from beautyads.sources.split import BrandSplit, ResplitRule, VolumeConstraints
from beautyads.store import StoreConnectError

NOW = datetime(2026, 11, 12, tzinfo=UTC)
NOTICE = "키 파일(pilot_key.json)은 라벨링을 마치기 전에 열지 마세요"
ROOT = Path(__file__).resolve().parents[1]


class Store:
    def __init__(self, items):
        self.items = {item.key: item for item in items}
        self.jobs = {}
        self.stats = [
            CollectionStat(
                source=source,
                brand=brand,
                account=f"account-{i}",
                total=count,
                analyzable_true=count,
                analyzable_false=0,
                analyzable_null=0,
                last_collected_at=NOW,
            )
            for i, (source, brand, count) in enumerate(
                [
                    (Source.youtube, "BRAND_SENTINEL", 30),
                    (Source.instagram, "BRAND_SENTINEL", 30),
                    (Source.youtube, "test", 150),
                    (Source.instagram, "test", 150),
                ]
            )
        ]
        self.queries = []
        self.enqueues = []
        self.result_queries = []

    def collection_stats(self):
        return self.stats

    def list_creatives(self, **kwargs):
        self.queries.append(kwargs)
        return [
            item
            for item in self.items.values()
            if item.brand in kwargs["brands"]
            and item.source in kwargs["sources"]
            and item.analyzable is True
        ]

    def enqueue_analysis(self, kind, items):
        self.enqueues.append((kind, [item.key for item in items]))
        for item in items:
            self.jobs.setdefault(
                (kind, item.key),
                JobResult(
                    key=item.key,
                    kind=kind,
                    status=JobStatus.pending,
                    labels=None,
                    error_code=None,
                    model=None,
                    thinking_level=None,
                    prompt_version=None,
                    raw_output=None,
                    attempts=0,
                    updated_at=None,
                ),
            )
        return len(items)

    def job_counts(self, kind):
        counts = dict.fromkeys((status.value for status in JobStatus), 0)
        counts.update(
            Counter(
                job.status.value for (axis, _), job in self.jobs.items() if axis == kind
            )
        )
        return counts

    def next_pending(self, kind, limit):
        return [
            self.items[key]
            for (axis, key), job in self.jobs.items()
            if axis == kind and job.status == JobStatus.pending
        ][:limit]

    def get_job_results(self, kind, keys):
        self.result_queries.append((kind, set(keys)))
        return [
            job
            for (axis, key), job in self.jobs.items()
            if axis == kind and key in keys
        ]

    def record_analysis(self, kind, key, **kwargs):
        self.jobs[kind, key] = self.jobs[kind, key].model_copy(update=kwargs)

    def requeue_jobs(self, kind, error_codes):
        count = 0
        for (axis, key), job in list(self.jobs.items()):
            if (
                axis == kind
                and job.status == JobStatus.failed
                and job.error_code in error_codes
            ):
                self.jobs[axis, key] = job.model_copy(
                    update={"status": JobStatus.pending}
                )
                count += 1
        return count


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    split = BrandSplit(
        registered_on="2026-11-12",
        seed=17,
        attempt=0,
        dev_size=1,
        brands=["BRAND_SENTINEL", "test"],
        dev=["BRAND_SENTINEL"],
        test=["test"],
        static_constraints=[],
        volume=VolumeConstraints(),
        resplit=ResplitRule(),
    )
    split_path = tmp_path / "config/brand_split.yaml"
    split_path.parent.mkdir()
    split_path.write_text(split.model_dump_json(), encoding="utf-8")
    items = [
        Creative(
            source=Source.youtube if i % 2 else Source.instagram,
            source_id=str(i),
            brand="BRAND_SENTINEL" if i < 8 else "test",
            account="account",
            analyzable=True,
            title="synthetic title",
            collected_at=NOW,
            url=f"https://example.invalid/public/{i}",
        )
        for i in range(10)
    ]
    store = Store(items)
    model = Mock()
    analysis_deps = analyze.AnalysisDeps(
        store,
        MediaDeps(*(Mock() for _ in range(4))),
        Mock(return_value={}),
        Mock(return_value=None),
        Mock(),
        lambda: NOW,
    )
    deps = pilot.PilotDeps(analysis_deps, store, lambda: NOW)
    factory = Mock(return_value=deps)
    ledger = tmp_path / "costs.jsonl"
    env = {
        name: "SENSITIVE_SENTINEL"
        for name in (
            "GEMINI_API_KEY",
            "POSTGRES_PASSWORD",
            "INSTAGRAM_ACCESS_TOKEN",
            "INSTAGRAM_USER_ID",
        )
    }
    env["BEAUTYADS_LEDGER_PATH"] = str(ledger)
    docker = Mock(return_value=True)
    tcp = Mock(return_value=True)
    fake = Mock()

    def outcome(item, *, run, **kwargs):
        model(run.run_tag)
        return CreativeOutcome(
            key=item.key,
            cleanup="none",
            mark_not_analyzable=False,
            records=[
                AxisRecord(
                    kind=f"{axis}@{run.run_tag}",
                    status=JobStatus.done,
                    labels={"synthetic": "LABEL_SENTINEL"},
                    model="MODEL_SENTINEL",
                    thinking_level=run.thinking_level,
                    prompt_version="v0",
                    raw_output=None,
                    error_code=None,
                )
                for axis in analyze.AXES
            ],
        )

    fake.side_effect = outcome
    monkeypatch.setattr(analyze, "analyze_creative", fake)
    return SimpleNamespace(
        deps=deps,
        factory=factory,
        store=store,
        items=items,
        split=split,
        split_path=split_path,
        ledger=ledger,
        env=env,
        docker=docker,
        tcp=tcp,
        out=StringIO(),
        model=model,
        fake=fake,
        tmp=tmp_path,
    )


def cli(rig, args=()):
    return pilot.main(
        args,
        environ=rig.env,
        out=rig.out,
        docker_check=rig.docker,
        tcp_check=rig.tcp,
        deps_factory=rig.factory,
    )


def run(rig, **kwargs):
    return pilot.run_pilot(
        rig.deps,
        n=kwargs.pop("n", 3),
        seed=17,
        content_type_window_s=2,
        full_window_s=4,
        split=rig.split,
        split_sha256="HASH_SENTINEL",
        ledger_path=rig.ledger,
        caps={"gemini": 12},
        interact=rig.model,
        out_dir=rig.tmp / "data/interim/pilot",
        out=rig.out,
        **kwargs,
    )


@pytest.mark.parametrize(
    "name",
    [
        "GEMINI_API_KEY",
        "POSTGRES_PASSWORD",
        "INSTAGRAM_ACCESS_TOKEN",
        "INSTAGRAM_USER_ID",
    ],
)
@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_credentials_never_construct_dependencies(rig, name, value):
    rig.env.pop(name)
    if value is not None:
        rig.env[name] = value
    assert cli(rig) == 2
    assert f"PREFLIGHT_FAILED ENV_MISSING:{name}" in rig.out.getvalue()
    rig.factory.assert_not_called()
    rig.model.assert_not_called()
    rig.tcp.assert_not_called()
    assert "SENSITIVE_SENTINEL" not in rig.out.getvalue()
    assert "postgresql://" not in rig.out.getvalue()


@pytest.mark.parametrize(
    "failure",
    [
        "DOCKER_DOWN",
        "POSTGRES_UNREACHABLE",
        "COST_CAP:gemini",
        "LEDGER_NOT_WRITABLE",
        "PILOT_SPLIT_FILE_INVALID",
    ],
)
def test_preflight_reasons_do_not_touch_store_or_model(rig, failure):
    if failure == "DOCKER_DOWN":
        rig.docker.return_value = False
    elif failure == "POSTGRES_UNREACHABLE":
        rig.tcp.return_value = False
    elif failure == "COST_CAP:gemini":
        rig.env["BEAUTYADS_CAP_GEMINI_USD"] = "0"
    elif failure == "LEDGER_NOT_WRITABLE":
        rig.ledger.mkdir()
    else:
        rig.split_path.write_text("not a split", encoding="utf-8")
    assert cli(rig) == 2
    assert f"PREFLIGHT_FAILED {failure}" in rig.out.getvalue()
    rig.factory.assert_not_called()
    rig.model.assert_not_called()
    if failure != "POSTGRES_UNREACHABLE":
        rig.tcp.assert_not_called()
    assert "SENSITIVE_SENTINEL" not in rig.out.getvalue()


@pytest.mark.parametrize("code", ["POSTGRES_AUTH_FAILED", "POSTGRES_CONNECT_FAILED"])
def test_store_connect_error_is_safe(rig, code):
    rig.factory.side_effect = StoreConnectError(code)
    assert cli(rig) == 2
    assert rig.out.getvalue() == f"PREFLIGHT_FAILED {code}\n"
    rig.model.assert_not_called()


def test_volume_check_is_before_selection_and_analysis(rig, monkeypatch):
    rig.store.stats = []
    selector = Mock(side_effect=AssertionError("must not select"))
    monkeypatch.setattr(pilot, "select_pilot", selector)
    assert cli(rig) == 2
    assert "PILOT_SPLIT_NOT_VERIFIED" in rig.out.getvalue()
    assert rig.store.queries == rig.store.enqueues == []
    selector.assert_not_called()
    rig.fake.assert_not_called()


def test_volume_counts_aggregate_accounts(rig):
    stat = rig.store.stats[0]
    rig.store.stats[0] = stat.model_copy(update={"analyzable_true": 15})
    rig.store.stats.append(
        stat.model_copy(update={"analyzable_true": 15, "account": "other"})
    )
    assert cli(rig, ["--n", "1"]) == 0


def test_no_analyzable_dev_collection(rig):
    for item in rig.items[:8]:
        item.analyzable = False
    assert cli(rig) == 2
    assert "PILOT_NO_COLLECTION" in rig.out.getvalue()
    assert rig.store.enqueues == []
    rig.model.assert_not_called()


def test_two_runs_only_selected_keys_and_blind_files(rig):
    for tag in pilot.RUN_TAGS:
        rig.store.enqueue_analysis(f"content_type@{tag}", rig.items)
    rig.store.enqueues.clear()
    report = run(rig)
    calls = rig.fake.call_args_list
    assert [call.kwargs["run"].run_tag for call in calls] == ["minimal"] * 3 + [
        "default"
    ] * 3
    selected = {call.args[0].key for call in calls}
    assert len(selected) == 3
    assert len(rig.store.enqueues[0][1]) == 3
    assert all(key in selected for _, keys in rig.store.enqueues for key in keys)
    for call in calls:
        run_info = call.kwargs["run"]
        assert run_info.thinking_level == run_info.run_tag
        assert run_info.purpose == f"pilot-{run_info.run_tag}"
        assert (
            run_info.content_type_window_s,
            run_info.full_window_s,
            run_info.hook_window_max_s,
        ) == (2, 4, 3)
    assert all(
        job.status == JobStatus.pending
        for (_, key), job in rig.store.jobs.items()
        if key not in selected
    )
    assert rig.store.queries == [
        {
            "brands": rig.split.dev,
            "sources": (Source.youtube, Source.instagram),
            "analyzable_only": True,
        }
    ]
    paths = report.files
    assert {path.name for path in paths.values()} == {
        "pilot_sheet.csv",
        "pilot_codebook.csv",
        "pilot_instructions.md",
        "pilot_key.json",
    }
    assert all(path.is_file() for path in paths.values())
    sheet_text = paths["sheet"].read_text(encoding="utf-8")
    for sentinel in (
        "BRAND_SENTINEL",
        "LABEL_SENTINEL",
        "MODEL_SENTINEL",
        "pilot_key.json",
    ):
        assert sentinel not in sheet_text
        if sentinel != "pilot_key.json":
            assert sentinel not in rig.out.getvalue()
    # Only synthetic key content in this temporary directory is inspected.
    key = json.loads(paths["key"].read_text(encoding="utf-8"))
    assert all(
        set(item["runs"]) == set(pilot.RUN_TAGS) for item in key["items"].values()
    )
    for tag in pilot.RUN_TAGS:
        assert all(report.by_status[tag][axis]["done"] == 3 for axis in analyze.AXES)
    assert "HASH_SENTINEL" in rig.out.getvalue() and NOTICE in rig.out.getvalue()
    assert all(keys == selected for _, keys in rig.store.result_queries[-6:])


@pytest.mark.parametrize(
    "error,reason",
    [
        (
            DailyLimitReached(kind=ErrorKind.DAILY_LIMIT, code="DAILY_LIMIT"),
            "DAILY_LIMIT",
        ),
        (CostCapExceeded("gemini", 12, 12), "COST_CAP:gemini"),
    ],
)
def test_first_stop_does_not_enqueue_or_start_second_run(rig, error, reason):
    rig.fake.side_effect = error
    report = run(rig)
    assert report.stopped == reason
    assert [kind for kind, _ in rig.store.enqueues] == ["content_type@minimal"]
    assert [call.kwargs["run"].run_tag for call in rig.fake.call_args_list] == [
        "minimal"
    ]
    assert all(
        status == "pending"
        for status in [job.status for job in rig.store.jobs.values()]
    )
    assert report.files["sheet"].is_file()
    assert "STOPPED " + reason in rig.out.getvalue()


def test_main_uses_file_hash_and_reports_shortfall(rig):
    assert cli(rig) == 0
    assert "PILOT_SHORTFALL 12" in rig.out.getvalue()
    assert hashlib.sha256(rig.split_path.read_bytes()).hexdigest() in rig.out.getvalue()
    assert NOTICE in rig.out.getvalue()


def test_current_cost_is_ledger_delta(rig):
    def add(cost):
        append_entry(
            rig.ledger,
            LedgerEntry(
                ts=NOW,
                provider="gemini",
                model="synthetic",
                purpose="test",
                cost_usd=cost,
                cost_source="computed",
            ),
        )

    add(5)
    rig.model.side_effect = lambda *args: add(0.125)
    report = run(rig, n=2)
    assert report.gemini_cost_usd == 0.5
    assert json.loads(rig.out.getvalue().splitlines()[-2])["gemini_cost_usd"] == 0.5


@pytest.mark.parametrize(
    "args",
    [
        ["--n", "0"],
        ["--n", "41"],
        ["--out-dir", "tracked"],
        ["--out-dir", "data/interim/../tracked"],
        ["--full-window-s", "nan"],
        ["--content-type-window-s", "0"],
    ],
)
def test_invalid_options_stop_before_dependencies(rig, args):
    assert cli(rig, args) == 2
    rig.factory.assert_not_called()
    rig.model.assert_not_called()
    rig.tcp.assert_not_called()


def test_no_volume_bypass_option(rig, monkeypatch):
    seen = []
    original = argparse.ArgumentParser.parse_args

    def capture(parser, *args, **kwargs):
        seen.extend(parser._option_string_actions)
        return original(parser, *args, **kwargs)

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", capture)
    assert cli(rig, ["--dry-run"]) == 0
    assert "--skip-volume-check" not in seen
    assert cli(rig, ["--skip-volume-check"]) == 2


def test_dry_run_hand_calculation_and_no_checks(rig, monkeypatch):
    expected = pilot.estimate(
        n=2, runs=2, content_type_window_s=2, full_window_s=4, tokens_per_second=10
    )
    assert expected == {
        "calls_min": 4,
        "calls_max": 12,
        "calls_max_with_retries": 24,
        "input_tokens_min": 80.0,
        "input_tokens_max": 360.0,
        "input_tokens_max_with_retries": 720.0,
    }
    rig.env.clear()
    monkeypatch.setattr(
        pilot, "load_brand_split", Mock(side_effect=AssertionError("no split read"))
    )
    assert (
        cli(
            rig,
            [
                "--dry-run",
                "--n",
                "2",
                "--content-type-window-s",
                "2",
                "--full-window-s",
                "4",
            ],
        )
        == 0
    )
    lines = rig.out.getvalue().splitlines()
    assert len(lines) == 1 and lines[0].startswith("ESTIMATE ")
    document = json.loads(lines[0].removeprefix("ESTIMATE "))
    assert document["calls_min"] == 4 and document["input_tokens_max"] == 3276
    assert (
        "비용은 원장에 기록되며 시범 뒤 `cost-recalc`가 계산한다"
        in document["assumptions"]
    )
    rig.factory.assert_not_called()
    rig.docker.assert_not_called()
    rig.tcp.assert_not_called()
    rig.model.assert_not_called()


def test_makefile_adds_live_pilot_without_changing_verify():
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "live-pilot" in text.splitlines()[0].split()
    assert "live-pilot:\n\tuv run python -m beautyads.eval.pilot_run\n" in text
    verify = text.split("verify:\n", 1)[1].split("\n\n", 1)[0]
    assert "live-" not in verify
    assert (
        verify
        == "\tuv run ruff check .\n\tuv run ruff format --check .\n\tuv run pytest -q"
    )


@pytest.mark.parametrize("mode", ["missing", "overlap", "wrong-size"])
def test_split_file_failures_are_one_public_reason(rig, mode):
    if mode == "missing":
        rig.split_path.unlink()
    else:
        data = rig.split.model_dump()
        data["test" if mode == "overlap" else "dev_size"] = (
            rig.split.dev if mode == "overlap" else 5
        )
        rig.split_path.write_text(json.dumps(data), encoding="utf-8")
    assert cli(rig) == 2
    assert rig.out.getvalue() == "PREFLIGHT_FAILED PILOT_SPLIT_FILE_INVALID\n"
    rig.factory.assert_not_called()
    rig.tcp.assert_not_called()


@pytest.mark.parametrize("port", ["not-a-port", "0", "65536"])
def test_invalid_postgres_port_is_safe(rig, port):
    rig.env["BEAUTYADS_POSTGRES_PORT"] = port
    assert cli(rig) == 2
    assert rig.out.getvalue() == "PREFLIGHT_FAILED POSTGRES_UNREACHABLE\n"
    rig.factory.assert_not_called()
    rig.tcp.assert_not_called()


def test_preflight_accepts_known_youtube_only_without_instagram(rig):
    env = {
        key: value for key, value in rig.env.items() if not key.startswith("INSTAGRAM_")
    }
    assert (
        pilot.preflight_pilot(
            environ=env,
            env_file=None,
            ledger_path=rig.ledger,
            caps={"gemini": 12},
            sources=[Source.youtube],
            docker_check=rig.docker,
            tcp_check=rig.tcp,
        )
        == []
    )
    rig.tcp.assert_called_once_with("127.0.0.1", 5433, 1.0)


@pytest.mark.parametrize("kind", ["parent", "append"])
def test_ledger_write_probe_failures(rig, monkeypatch, kind):
    if kind == "parent":
        rig.ledger.write_text("not a directory", encoding="utf-8")
        rig.env["BEAUTYADS_LEDGER_PATH"] = str(rig.ledger / "costs.jsonl")
    else:
        rig.ledger.touch()
        original = Path.open

        def guarded(path, *args, **kwargs):
            if path == rig.ledger and args and args[0] == "a":
                raise PermissionError("SENSITIVE_SENTINEL")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", guarded)
    assert cli(rig) == 2
    assert "PREFLIGHT_FAILED LEDGER_NOT_WRITABLE" in rig.out.getvalue()
    assert "SENSITIVE_SENTINEL" not in rig.out.getvalue()
    rig.factory.assert_not_called()
    rig.tcp.assert_not_called()


@pytest.mark.parametrize("dry", [False, True])
@pytest.mark.parametrize("target", ["directory", "key"])
def test_symlink_output_escape_stops_before_checks(rig, dry, target):
    outside = rig.tmp / "tracked"
    outside.mkdir()
    root = rig.tmp / "data/interim"
    root.mkdir(parents=True)
    folder = root / "pilot"
    if target == "directory":
        folder.symlink_to(outside, target_is_directory=True)
    else:
        folder.mkdir()
        (folder / "pilot_key.json").symlink_to(outside / "key.json")
    assert cli(rig, ["--out-dir", str(folder)] + (["--dry-run"] if dry else [])) == 2
    assert "OUTPUT_NOT_IGNORED" in rig.out.getvalue()
    assert list(outside.iterdir()) == []
    rig.factory.assert_not_called()
    rig.docker.assert_not_called()
    rig.model.assert_not_called()


def test_run_contract_and_retry_flag(rig, monkeypatch):
    spy = Mock(wraps=pilot.run_analysis)
    monkeypatch.setattr(pilot, "run_analysis", spy)
    report = run(rig, n=2)
    assert list(report.runs) == ["minimal", "default"]
    assert spy.call_count == 2
    for call in spy.call_args_list:
        assert call.kwargs["retry_failed"] is False
        assert call.kwargs["limit"] == len(call.kwargs["only_keys"]) == 2
        assert call.kwargs["run"].interact is rig.model
        assert call.args[0].store is rig.store


def test_main_exit_code_on_analysis_limit(rig):
    rig.fake.side_effect = DailyLimitReached(
        kind=ErrorKind.DAILY_LIMIT, code="DAILY_LIMIT"
    )
    assert cli(rig) == 3
    assert "STOPPED DAILY_LIMIT" in rig.out.getvalue()
    assert (rig.tmp / "data/interim/pilot/pilot_sheet.csv").is_file()


def test_real_batch_with_fake_interaction_holds_invalid_schema(rig, monkeypatch):
    from beautyads.llm import InteractionResult, UsageInfo
    from beautyads.pipeline.media_flow import analyze_creative

    # Exercise the actual batch/media/axis path without calling any SDK or API.
    monkeypatch.setattr(analyze, "analyze_creative", analyze_creative)
    for item in rig.items:
        item.source = Source.youtube
    rig.store.items = {item.key: item for item in rig.items}
    rig.model.return_value = InteractionResult(
        "{}", UsageInfo("synthetic", 0, 0, 0, 0, 0.0), {}
    )
    report = run(rig, n=1)
    assert rig.model.call_count == 4  # schema request + one retry, twice
    assert [call.kwargs["thinking_level"] for call in rig.model.call_args_list] == [
        "minimal",
        "minimal",
        "default",
        "default",
    ]
    assert all(
        report.by_status[tag]["content_type"]["held"] == 1 for tag in pilot.RUN_TAGS
    )
    for boundary in rig.deps.analysis.media:
        boundary.assert_not_called()


def test_live_dependencies_wire_only_existing_boundaries(rig, monkeypatch):
    from contextlib import ExitStack

    from beautyads.sources.config import InstagramAccount
    from beautyads.sources.instagram import RefreshResult
    from beautyads.sources.media import DownloadedMedia

    account = InstagramAccount(brand="BRAND_SENTINEL", username="account")
    connection = Mock()
    connect = Mock(return_value=connection)
    migrations = Mock()
    refresh = Mock(
        return_value=RefreshResult(
            {"0": "https://example.invalid/video"}, set(), set(), None
        )
    )
    download = Mock(return_value=DownloadedMedia(b"synthetic video", "video/mp4", 15))
    upload, wait, delete = Mock(), Mock(), Mock(return_value=True)
    for name, fake in {
        "load_instagram_accounts": Mock(return_value=[account]),
        "connect": connect,
        "apply_migrations": migrations,
        "PostgresCreativeStore": Mock(return_value=rig.store),
        "refresh_media_urls": refresh,
        "download_media": download,
        "upload_video": upload,
        "wait_processed": wait,
        "delete_file": delete,
    }.items():
        monkeypatch.setattr(pilot, name, fake)
    with ExitStack() as stack:
        deps = pilot._live_deps(environ=rig.env, env_file=None, stack=stack)
        connect.assert_called_once()
        migrations.assert_called_once_with(connection)
        refresh.assert_not_called()
        item = rig.items[0]
        plans = deps.analysis.plans([item])
        assert plans[item.key].state == "ok"
        assert refresh.call_args.args[3:] == (account, {"0"})
        assert refresh.call_args.kwargs["now"].tzinfo is not None
        assert deps.analysis.rerefresh(item)() == "https://example.invalid/video"
        assert (
            deps.analysis.rerefresh(item.model_copy(update={"account": "unknown"}))
            is None
        )
        deps.analysis.media.download(plans[item.key].url)
        download.assert_called_once_with(pilot.httpx_media_get, plans[item.key].url)
        deps.analysis.media.upload(b"synthetic", filename="video.mp4")
        deps.analysis.media.wait("synthetic-file")
        assert deps.analysis.media.delete("synthetic-file") is True
        assert upload.call_args.kwargs["filename"] == "video.mp4"
        connection.close.assert_not_called()
    connection.close.assert_called_once()


def _fail(rig, key, code, status=JobStatus.failed, tag="default"):
    rig.store.jobs[f"content_type@{tag}", key] = rig.store.jobs[
        f"content_type@{tag}", key
    ].model_copy(update={"status": status, "error_code": code, "labels": None})


def _retry(rig, **kwargs):
    return pilot.retry_pilot(
        rig.deps,
        tag=kwargs.pop("tag", "default"),
        content_type_window_s=2,
        full_window_s=4,
        ledger_path=rig.ledger,
        caps={"gemini": 12},
        interact=rig.model,
        out_dir=rig.tmp / "data/interim/pilot",
        out=rig.out,
        **kwargs,
    )


def test_retry_reruns_only_refresh_failures_and_never_rewrites_sheet_or_key(rig):
    for tag in pilot.RUN_TAGS:
        rig.store.enqueue_analysis(f"content_type@{tag}", rig.items)
    report = run(rig)
    sheet_dir = rig.tmp / "data/interim/pilot"
    selected = sorted(
        {call.args[0].key for call in rig.fake.call_args_list},
        key=lambda key: key.source_id,
    )
    stopped_key, missing_key, gone_key = selected
    _fail(rig, stopped_key, "MEDIA_REFRESH_STOPPED")
    _fail(rig, missing_key, "MEDIA_URL_MISSING")
    _fail(rig, gone_key, "MEDIA_URL_GONE", status=JobStatus.held)
    # 같은 태그가 아닌 minimal 실패는 건드리지 않는다.
    _fail(rig, stopped_key, "MEDIA_REFRESH_STOPPED", tag="minimal")
    before = {
        name: (sheet_dir / name).read_bytes()
        for name in ("pilot_sheet.csv", "pilot_key.json")
    }
    rig.fake.reset_mock()

    result = _retry(rig)

    assert result.retried == 2 and result.stopped is None
    calls = rig.fake.call_args_list
    assert {call.args[0].key for call in calls} == {stopped_key, missing_key}
    assert {call.kwargs["run"].run_tag for call in calls} == {"default"}
    assert all(call.kwargs["run"].purpose == "pilot-default-retry" for call in calls)
    # 시트·기존 키는 바이트 단위로 그대로, 결과는 별도 보충 파일에만 쓴다.
    assert {name: (sheet_dir / name).read_bytes() for name in before} == before
    supplement = json.loads((sheet_dir / "pilot_key_supplement.json").read_text())
    key_items = json.loads((sheet_dir / "pilot_key.json").read_text())["items"]
    assert supplement["run_tag"] == "default"
    assert {
        (value["source"], value["source_id"]) for value in supplement["items"].values()
    } == {(key.source.value, key.source_id) for key in (stopped_key, missing_key)}
    for item_id, value in supplement["items"].items():
        assert item_id in key_items
        assert key_items[item_id]["source_id"] == value["source_id"]
        assert value["runs"]["default"]["content_type"]["status"] == "done"
    # held(MEDIA_URL_GONE)와 minimal 실패는 그대로 남는다.
    assert rig.store.jobs["content_type@default", gone_key].status == JobStatus.held
    assert (
        rig.store.jobs["content_type@minimal", stopped_key].status == JobStatus.failed
    )
    assert report.files["key"].read_bytes() == before["pilot_key.json"]


def test_retry_with_nothing_to_retry_makes_no_call_and_no_file(rig):
    for tag in pilot.RUN_TAGS:
        rig.store.enqueue_analysis(f"content_type@{tag}", rig.items)
    run(rig)
    rig.fake.reset_mock()
    result = _retry(rig)
    assert result.retried == 0 and result.supplement is None
    rig.fake.assert_not_called()
    assert "RETRY_NOTHING" in rig.out.getvalue()
    assert not (rig.tmp / "data/interim/pilot/pilot_key_supplement.json").exists()


def test_retry_requires_the_existing_key_file(rig):
    with pytest.raises(pilot.SheetError) as caught:
        _retry(rig)
    assert caught.value.code == "PILOT_KEY_MISSING"
    rig.fake.assert_not_called()


def test_main_retry_flag_uses_retry_path_and_reports_safely(rig):
    assert cli(rig, ["--retry-missing"]) == 2
    assert "PREFLIGHT_FAILED PILOT_KEY_MISSING" in rig.out.getvalue()
    rig.fake.assert_not_called()
    assert not (rig.tmp / "data/interim/pilot/pilot_sheet.csv").exists()
