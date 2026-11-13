"""Final-tag execution uses synthetic repositories, media, models and ledgers."""

import json
from datetime import UTC, datetime
from io import StringIO
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_analyze_runner import Store, creative
from test_media_flow import FakeInteract, FakeMedia, responses

from beautyads.analysis.models import ANALYSIS_MODEL_ID, PROMPT_VERSIONS
from beautyads.domain import JobStatus, Source
from beautyads.llm import CostCapExceeded, DailyLimitReached, ErrorKind
from beautyads.obs.ledger import LedgerEntry, append_entry
from beautyads.pipeline import analyze_target as cli
from beautyads.pipeline.analyze import AnalysisDeps, AnalysisReport
from beautyads.pipeline.media_flow import RETRYABLE_ERROR_CODES, UrlPlan
from beautyads.store import StoreConnectError

NOW = datetime(2026, 11, 13, tzinfo=UTC)


class TrackingStore(Store):
    def __init__(self, items):
        super().__init__(items)
        self.kinds = []
        self.enqueued = []

    def __getattribute__(self, name):
        method = super().__getattribute__(name)
        if name in {
            "enqueue_analysis",
            "next_pending",
            "get_job_results",
            "job_counts",
            "record_analysis",
            "requeue_jobs",
        }:

            def track(kind, *args, **kwargs):
                self.kinds.append(kind)
                return method(kind, *args, **kwargs)

            return track
        return method

    def enqueue_analysis(self, kind, creatives):
        self.enqueued.extend(item.key for item in creatives)
        return super().enqueue_analysis(kind, creatives)


@pytest.fixture
def rig(tmp_path):
    prereg = tmp_path / "prereg.md"
    prereg.write_text(
        "全\n- 전체 v1 동결: 2026-11-13\n"
        + ANALYSIS_MODEL_ID
        + "\n"
        + " / ".join(PROMPT_VERSIONS.values()),
        encoding="utf-8",
    )
    env = {
        name: "synthetic-private-setting"
        for name in (
            "GEMINI_API_KEY",
            "POSTGRES_PASSWORD",
            "INSTAGRAM_ACCESS_TOKEN",
            "INSTAGRAM_USER_ID",
        )
    }
    env["BEAUTYADS_LEDGER_PATH"] = str(tmp_path / "costs.jsonl")
    store = TrackingStore([creative(i) for i in range(5)])
    model = FakeInteract(responses() * 20)
    analysis = AnalysisDeps(
        store,
        FakeMedia().deps(),
        Mock(return_value={}),
        Mock(return_value=None),
        Mock(),
        lambda: NOW,
    )
    deps = cli.TargetDeps(analysis, model, [])
    return SimpleNamespace(
        env=env,
        prereg=prereg,
        store=store,
        model=model,
        deps=deps,
        out=StringIO(),
        factory=Mock(return_value=deps),
        docker=Mock(return_value=True),
        tcp=Mock(return_value=True),
    )


def execute(rig, args=(), **kwargs):
    return cli.main(
        args,
        environ=rig.env,
        preregistration_path=rig.prereg,
        out=rig.out,
        deps_factory=rig.factory,
        docker_check=rig.docker,
        tcp_check=rig.tcp,
        **kwargs,
    )


def events(rig, event):
    return [
        row
        for line in rig.out.getvalue().splitlines()
        if line.startswith("{") and (row := json.loads(line)).get("event") == event
    ]


@pytest.mark.parametrize(
    "name",
    [
        "GEMINI_API_KEY",
        "POSTGRES_PASSWORD",
        "INSTAGRAM_ACCESS_TOKEN",
        "INSTAGRAM_USER_ID",
    ],
)
def test_missing_credentials_never_construct_dependencies(rig, name):
    rig.env[name] = " "
    assert execute(rig) == 2
    assert f"PREFLIGHT_FAILED ENV_MISSING:{name}" in rig.out.getvalue()
    rig.factory.assert_not_called()
    rig.docker.assert_not_called()
    rig.tcp.assert_not_called()
    assert not rig.model.calls
    assert "synthetic-private-setting" not in rig.out.getvalue()
    assert "postgresql://" not in rig.out.getvalue()


@pytest.mark.parametrize(
    "damage",
    ["missing", "date", "placeholder", "invalid_date", "model", *PROMPT_VERSIONS],
)
def test_preregistration_gate(rig, damage):
    text = rig.prereg.read_text()
    if damage == "missing":
        rig.prereg.unlink()
    else:
        old = {
            "date": "- 전체 v1 동결: 2026-11-13",
            "placeholder": "2026-11-13",
            "invalid_date": "2026-11-13",
            "model": ANALYSIS_MODEL_ID,
        }.get(damage, PROMPT_VERSIONS.get(damage))
        replacement = "2026-99-99" if damage == "invalid_date" else "미기록"
        rig.prereg.write_text(text.replace(old, replacement))
    assert execute(rig) == 2
    assert "PREFLIGHT_FAILED PREREGISTRATION_NOT_UPDATED" in rig.out.getvalue()
    rig.factory.assert_not_called()
    rig.docker.assert_not_called()
    assert not rig.model.calls


@pytest.mark.parametrize(
    ("probe", "code"), [("docker", "DOCKER_DOWN"), ("tcp", "POSTGRES_UNREACHABLE")]
)
def test_service_probes_are_injected(rig, probe, code):
    getattr(rig, probe).return_value = False
    assert execute(rig) == 2
    assert f"PREFLIGHT_FAILED {code}" in rig.out.getvalue()
    rig.factory.assert_not_called()
    assert not rig.model.calls


def entry(purpose, cost=0.01, **kwargs):
    return LedgerEntry(
        ts=NOW,
        provider="gemini",
        model=ANALYSIS_MODEL_ID,
        purpose=purpose,
        cost_usd=cost,
        cost_source="response_cost",
        input_tokens=100,
        output_tokens=20,
        thought_tokens=4,
        cached_tokens=10,
        **kwargs,
    )


def test_cap_and_unwritable_ledger_gate(rig):
    append_entry(Path(rig.env["BEAUTYADS_LEDGER_PATH"]), entry("earlier", 12))
    assert execute(rig) == 2
    assert "PREFLIGHT_FAILED COST_CAP:gemini" in rig.out.getvalue()
    rig.factory.assert_not_called()
    rig.env["BEAUTYADS_LEDGER_PATH"] = str(rig.prereg / "ledger")
    assert execute(rig) == 2
    assert "PREFLIGHT_FAILED LEDGER_NOT_WRITABLE" in rig.out.getvalue()
    rig.factory.assert_not_called()


@pytest.mark.parametrize("code", ["POSTGRES_AUTH_FAILED", "POSTGRES_CONNECT_FAILED"])
def test_store_connection_errors_are_codes_only(rig, code):
    rig.factory.side_effect = StoreConnectError(code)
    assert execute(rig) == 2
    assert rig.out.getvalue().strip() == f"PREFLIGHT_FAILED {code}"


def test_youtube_needs_no_instagram_or_youtube_api_key(rig):
    rig.env.pop("INSTAGRAM_ACCESS_TOKEN")
    rig.env.pop("INSTAGRAM_USER_ID")
    assert execute(rig, ["--sources", "youtube"]) == 0
    assert len(rig.model.calls) == 15


def test_batches_resume_and_never_access_pilot_jobs(rig):
    pilot = next(iter(rig.store.creatives.values()))
    for tag in ("minimal", "default"):
        rig.store.enqueue_analysis(f"content_type@{tag}", [pilot])
    pilot_jobs = {key: job.model_copy(deep=True) for key, job in rig.store.jobs.items()}
    rig.store.kinds.clear()
    assert execute(rig, ["--batch-size", "2"]) == 0
    batches = events(rig, "batch")
    assert [b["processed"] for b in batches] == [2, 2, 1]
    assert all(
        a["cumulative_cost_usd"] <= b["cumulative_cost_usd"]
        for a, b in pairwise(batches)
    )
    calls = len(rig.model.calls)
    assert calls == 15
    assert execute(rig, ["--retry-failed"]) == 0
    assert len(rig.model.calls) == calls
    assert all(kind.endswith("@v1") for kind in rig.store.kinds)
    assert all(rig.store.jobs[key] == job for key, job in pilot_jobs.items())
    assert {c["purpose"] for c in rig.model.calls} == {
        f"analyze-target-{axis}" for axis in PROMPT_VERSIONS
    }


@pytest.mark.parametrize(
    "code",
    sorted(
        RETRYABLE_ERROR_CODES
        | {"MEDIA_URL_GONE", "MEDIA_URL_MISSING", "INVALID_OUTPUT"}
    ),
)
def test_retry_only_eligible_failed_once(rig, code):
    item = next(iter(rig.store.creatives.values()))
    rig.store.enqueue_analysis("content_type@v1", [item])
    job = rig.store.jobs["content_type@v1", item.key]
    job.status = JobStatus.held if code == "MEDIA_URL_GONE" else JobStatus.failed
    job.error_code = code
    assert execute(rig, ["--retry-failed", "--batch-size", "1"]) == 0
    assert rig.store.jobs["content_type@v1", item.key].status == (
        JobStatus.done if code in RETRYABLE_ERROR_CODES else job.status
    )
    assert len(rig.store.requeues) == 3
    assert all(codes == RETRYABLE_ERROR_CODES for _, codes in rig.store.requeues)


@pytest.mark.parametrize(
    "stop",
    [
        DailyLimitReached(kind=ErrorKind.DAILY_LIMIT, code="DAILY_LIMIT"),
        CostCapExceeded("gemini", 12, 12),
    ],
)
def test_quota_stops_keep_pending_and_do_not_repeat(rig, stop):
    rig.model.replies = iter([stop])
    assert execute(rig, ["--batch-size", "2"]) == 3
    assert len(rig.model.calls) == 1
    assert rig.store.job_counts("content_type@v1")["pending"] == 5
    assert len(events(rig, "batch")) == 1
    assert "STOPPED " in rig.out.getvalue()


def test_instagram_usage_stops_after_one_batch(rig):
    items = [
        item.model_copy(update={"source": Source.instagram})
        for item in rig.store.creatives.values()
    ]
    rig.store.creatives = {item.key: item for item in items}

    def plans(targets):
        rig.deps.scan_log.append(
            {
                "account": "synthetic-account",
                "usage": {"total_time": 80},
                "stopped": "INSTAGRAM_USAGE_HIGH",
            }
        )
        return {item.key: UrlPlan(None, "refresh_stopped") for item in targets}

    rig.deps.analysis.plans.side_effect = plans
    assert execute(rig, ["--batch-size", "2", "--retry-failed"]) == 3
    assert rig.deps.analysis.plans.call_count == 1
    assert not rig.model.calls
    summary = events(rig, "summary")[-1]
    assert summary["error_codes"]["MEDIA_REFRESH_STOPPED"] == 2
    assert summary["instagram_last_usage"] == {"total_time": 80}
    assert summary["refresh_by_account"] == {"synthetic-account": 1}
    assert summary["pending"] == 3


def test_zero_processing_breaks_loop(rig, monkeypatch):
    run = Mock(
        return_value=AnalysisReport(
            processed=0,
            by_status={},
            error_codes={},
            cleanup_failed=0,
            not_analyzable_marked=0,
            stopped=None,
            gemini_cost_usd=0,
            elapsed_s=0,
        )
    )
    monkeypatch.setattr(cli, "run_analysis", run)
    assert execute(rig) == 0
    assert run.call_count == 1


def keyfile(tmp_path, name, items):
    path = tmp_path / name
    path.write_text(
        json.dumps({"items": {str(i): item for i, item in enumerate(items)}})
    )
    return path


def keyitem(item):
    return {
        "source": item.source.value,
        "source_id": item.source_id,
        "brand": "BLIND_SENTINEL",
        "url": "BLIND_SENTINEL",
        "human_label": "BLIND_SENTINEL",
    }


def test_only_keys_union_skip_resume_and_blind_output(rig, tmp_path, monkeypatch):
    items = list(rig.store.creatives.values())
    rig.store.creatives[items[2].key] = items[2].model_copy(
        update={"analyzable": False}
    )
    first = keyfile(
        tmp_path,
        "first.json",
        [
            keyitem(items[0]),
            keyitem(items[1]),
            keyitem(items[2]),
            {"source": "youtube", "source_id": "absent"},
        ],
    )
    second = keyfile(tmp_path, "second.json", [keyitem(items[0])])
    real_run = cli.run_analysis
    calls = Mock(wraps=real_run)
    monkeypatch.setattr(cli, "run_analysis", calls)
    assert (
        execute(rig, ["--only-keys-file", str(first), "--only-keys-file", str(second)])
        == 0
    )
    assert set(rig.store.enqueued) == {i.key for i in items[:2]}
    assert set(calls.call_args.kwargs["only_keys"]) == {i.key for i in items[:2]}
    assert len(rig.model.calls) == 6
    assert "KEY_NOT_ANALYZABLE 2" in rig.out.getvalue()
    assert "BLIND_SENTINEL" not in rig.out.getvalue()
    assert all(i.source_id not in rig.out.getvalue().splitlines() for i in items)
    assert execute(rig) == 0
    assert len(rig.model.calls) == 12


def test_only_keys_source_intersection(rig, tmp_path):
    item = next(iter(rig.store.creatives.values()))
    path = keyfile(
        tmp_path,
        "key.json",
        [keyitem(item), {"source": "instagram", "source_id": "unselected"}],
    )
    assert execute(rig, ["--only-keys-file", str(path), "--sources", "youtube"]) == 0
    assert len(rig.model.calls) == 3
    assert "KEY_NOT_ANALYZABLE 0" in rig.out.getvalue()


@pytest.mark.parametrize("extra", [["--brands", "brand"], ["--limit", "1"]])
def test_only_keys_conflict_before_dependencies(rig, tmp_path, extra):
    assert execute(rig, ["--only-keys-file", str(tmp_path / "missing"), *extra]) == 2
    assert "ONLY_KEYS_CONFLICT" in rig.out.getvalue()
    rig.factory.assert_not_called()
    rig.docker.assert_not_called()


@pytest.mark.parametrize(
    "contents",
    [
        None,
        "not json",
        "{}",
        '{"items": []}',
        '{"items":{"1":{}}}',
        '{"items":{"1":{"source":"unknown","source_id":"a"}}}',
        '{"items":{"1":{"source":"youtube","source_id":" "}}}',
    ],
)
def test_bad_keys_fail_before_dependencies(rig, tmp_path, contents):
    path = tmp_path / "key.json"
    if contents is not None:
        path.write_text(contents)
    assert execute(rig, ["--only-keys-file", str(path)]) == 2
    code = "ONLY_KEYS_FILE_MISSING" if contents is None else "ONLY_KEYS_FILE_INVALID"
    assert code in rig.out.getvalue()
    rig.factory.assert_not_called()
    rig.docker.assert_not_called()
    assert not rig.model.calls


def test_dry_run_is_local_and_counts_without_disclosing_keys(rig, tmp_path):
    item = next(iter(rig.store.creatives.values()))
    path = keyfile(tmp_path, "key.json", [keyitem(item)])
    rig.env = {}
    assert (
        execute(rig, ["--dry-run", "--items", "7", "--only-keys-file", str(path)]) == 0
    )
    preview = json.loads(rig.out.getvalue().removeprefix("ESTIMATE "))
    assert preview["calls_min"] == 7 and preview["calls_max"] == 21
    assert preview["key_count"] == 1
    assert preview["run_tag"] == "v1"
    assert preview["model"] == ANALYSIS_MODEL_ID
    assert preview["prompt_versions"] == PROMPT_VERSIONS
    assert preview["batch_size"] == 100 and preview["concurrency"] == 1
    assert "BLIND_SENTINEL" not in rig.out.getvalue()
    rig.factory.assert_not_called()
    rig.docker.assert_not_called()
    rig.tcp.assert_not_called()


@pytest.mark.parametrize(
    "args",
    [
        ["--batch-size", "0"],
        ["--batch-size", "501"],
        ["--concurrency", "0"],
        ["--concurrency", "5"],
        ["--full-window-s", "nan"],
        ["--limit", "0"],
        ["--sources", "tiktok"],
    ],
)
def test_invalid_options(rig, args):
    assert execute(rig, args) == 2
    rig.factory.assert_not_called()


def test_axis_ledger_summary_only_new_entries(rig):
    path = Path(rig.env["BEAUTYADS_LEDGER_PATH"])
    append_entry(path, entry("analyze-target-content_type", 5))
    real_factory = rig.factory.side_effect

    def factory():
        for purpose, cost in [
            ("analyze-target-content_type", 0.1),
            ("analyze-target-content_type", 0.3),
            ("analyze-target-hook", 0.02),
            ("unrelated", 0.9),
        ]:
            append_entry(path, entry(purpose, cost))
        append_entry(
            path,
            entry("analyze-target-full", 0.5).model_copy(
                update={"cost_source": "computed", "input_tokens": 300}
            ),
        )
        return rig.deps

    assert real_factory is None
    rig.factory.side_effect = factory
    assert execute(rig) == 0
    summary = events(rig, "summary")[-1]["cost_by_axis"]
    assert summary["content_type"]["calls"] == 2
    assert summary["content_type"]["cost_usd"] == pytest.approx(0.4)
    assert summary["content_type"]["token_means"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "thought_tokens": 4,
        "cached_tokens": 10,
    }
    assert summary["full"]["non_response_cost"] == 1
    assert summary["full"]["token_means"]["input_tokens"] == 300


def test_progress_aggregates_synthetic_jobs(rig):
    items = list(rig.store.creatives.values())
    for item in items:
        rig.store.enqueue_analysis("content_type@v1", [item])
    for index, item in enumerate(items[:3]):
        job = rig.store.jobs["content_type@v1", item.key]
        job.status = JobStatus.done
        job.labels = {"category": "other" if index == 2 else "sun_care"}
        rig.store.enqueue_analysis("full@v1", [item])
        job = rig.store.jobs["full@v1", item.key]
        job.status = JobStatus.done
        job.labels = {
            "angle": "other" if index < 2 else "desire",
            "format": "other" if index == 0 else "demo",
            "talent": "none",
            "cta_type": "none",
            "claims": ["other", "hydration"] if index == 0 else [],
        }
    rig.store.jobs["content_type@v1", items[3].key].status = JobStatus.failed
    rig.store.jobs["content_type@v1", items[3].key].error_code = "MEDIA_URL_MISSING"
    rig.store.jobs["content_type@v1", items[4].key].status = JobStatus.held
    progress = cli.progress(rig.store, [i.key for i in items])
    assert progress["done_by_source"] == {"youtube": 3}
    assert progress["done_by_category"] == {"sun_care": 2, "other": 1}
    assert (
        progress["failed"] == 1 and progress["held"] == 1 and progress["pending"] == 0
    )
    assert progress["failure_rate"] == pytest.approx(2 / 8)
    assert progress["other_by_axis"]["angle"] == {"n": 3, "other": 2, "ratio": 2 / 3}
    assert progress["other_by_axis"]["format"]["ratio"] == 1 / 3
    assert progress["other_by_axis"]["claims"]["ratio"] == 1 / 3
    assert progress["other_by_axis"]["talent"]["ratio"] == 0
    assert progress["error_codes"] == {"MEDIA_URL_MISSING": 1}


def test_makefile_manual_target_only():
    text = Path("Makefile").read_text()
    assert "live-analyze" in text.splitlines()[0].split()
    assert (
        "live-analyze:\n\tuv run python -m beautyads.pipeline.analyze_target $(ARGS)\n"
        in text
    )
    assert "live-" not in text.split("verify:\n", 1)[1].split("\n\n", 1)[0]


def test_only_keys_retry_does_not_requeue_outside_selection(rig, tmp_path):
    selected, outside = list(rig.store.creatives.values())[:2]
    rig.store.enqueue_analysis("content_type@v1", [selected, outside])
    for item in (selected, outside):
        job = rig.store.jobs["content_type@v1", item.key]
        job.status = JobStatus.failed
        job.error_code = "MEDIA_REFRESH_STOPPED"
    original = rig.store.jobs["content_type@v1", outside.key].model_copy(deep=True)
    path = keyfile(tmp_path, "key.json", [keyitem(selected)])
    assert execute(rig, ["--only-keys-file", str(path), "--retry-failed"]) == 0
    assert len(rig.model.calls) == 3
    assert rig.store.jobs["content_type@v1", outside.key] == original
    assert rig.store.jobs["content_type@v1", selected.key].status == JobStatus.done


def test_batch_costs_increase_with_model_ledger_entries(rig):
    original_model = rig.model
    path = Path(rig.env["BEAUTYADS_LEDGER_PATH"])
    seen_axes = []

    def model(**kwargs):
        properties = kwargs["response_format"]["schema"]["properties"]
        axis = (
            "content_type"
            if "content_type" in properties
            else "hook"
            if "hook_type" in properties
            else "full"
        )
        seen_axes.append(axis)
        assert kwargs["purpose"] == f"analyze-target-{axis}"
        append_entry(path, entry(kwargs["purpose"], 0.01))
        return original_model(**kwargs)

    rig.factory.return_value = rig.deps._replace(interact=model)
    assert execute(rig, ["--batch-size", "2"]) == 0
    batches = events(rig, "batch")
    assert [row["batch_cost_usd"] for row in batches] == pytest.approx(
        [0.06, 0.06, 0.03]
    )
    assert [row["cumulative_cost_usd"] for row in batches] == pytest.approx(
        [0.06, 0.12, 0.15]
    )
    assert seen_axes == list(PROMPT_VERSIONS) * 5
    for axis in PROMPT_VERSIONS:
        assert events(rig, "summary")[-1]["cost_by_axis"][axis]["calls"] == 5


def test_retry_child_axes_replays_done_axes_across_batches(rig):
    items = list(rig.store.creatives.values())
    # Synthetic persisted outputs come from schema-valid fixture generators.
    for item in items:
        for axis, payload in zip(PROMPT_VERSIONS, responses(), strict=True):
            kind = f"{axis}@v1"
            rig.store.enqueue_analysis(kind, [item])
            job = rig.store.jobs[kind, item.key]
            job.status = JobStatus.failed if axis == "full" else JobStatus.done
            job.labels = None if axis == "full" else payload
            job.error_code = "LLM_RETRYABLE" if axis == "full" else None
    rig.model.replies = iter([responses()[-1]] * 5)
    assert execute(rig, ["--retry-failed", "--batch-size", "2"]) == 0
    assert len(rig.model.calls) == 5
    assert {call["purpose"] for call in rig.model.calls} == {"analyze-target-full"}
    assert len(rig.store.requeues) == 3
    assert [row["processed"] for row in events(rig, "batch")] == [2, 2, 1]
    assert events(rig, "summary")[-1]["pending"] == 0


def test_new_retryable_failure_is_not_reopened_next_batch(rig):
    from beautyads.llm import LlmCallError

    rig.model.replies = iter(
        [LlmCallError(kind=ErrorKind.RETRYABLE, code="UNAVAILABLE")] * 5
    )
    assert execute(rig, ["--retry-failed", "--batch-size", "1"]) == 0
    assert len(rig.model.calls) == 5
    assert rig.store.job_counts("content_type@v1")["failed"] == 5
    assert len(rig.store.requeues) == 3


def test_empty_selection_has_no_batches_or_model_calls(rig, tmp_path):
    path = keyfile(tmp_path, "empty.json", [])
    assert execute(rig, ["--only-keys-file", str(path)]) == 0
    assert not events(rig, "batch")
    assert not rig.model.calls
    assert events(rig, "summary")[-1]["failure_rate"] is None
    assert all(
        row["ratio"] is None
        for row in events(rig, "summary")[-1]["other_by_axis"].values()
    )


def test_brands_sources_and_limit_apply_to_processing(rig):
    items = list(rig.store.creatives.values())
    rig.store.creatives[items[0].key] = items[0].model_copy(update={"brand": "outside"})
    assert (
        execute(
            rig, ["--brands", "synthetic-brand", "--sources", "youtube", "--limit", "2"]
        )
        == 0
    )
    assert set(rig.store.enqueued) == {item.key for item in items[1:3]}
    assert len(rig.model.calls) == 6


def test_live_assembly_latches_refresh_stop_and_keeps_media_boundaries_fake(
    rig, monkeypatch
):
    from contextlib import ExitStack

    from beautyads.sources.instagram import RefreshResult

    account_a = SimpleNamespace(username="account-a")
    account_b = SimpleNamespace(username="account-b")
    monkeypatch.setattr(
        cli, "load_instagram_accounts", Mock(return_value=[account_a, account_b])
    )
    connection = Mock()
    monkeypatch.setattr(cli, "connect", Mock(return_value=connection))
    monkeypatch.setattr(cli, "apply_migrations", Mock())
    monkeypatch.setattr(cli, "PostgresCreativeStore", Mock(return_value=rig.store))
    transport = Mock(side_effect=AssertionError("must not contact source"))
    monkeypatch.setattr(cli, "instagram_httpx_get", transport)
    for name in (
        "download_media",
        "upload_video",
        "wait_processed",
        "delete_file",
        "gemini_interact",
    ):
        monkeypatch.setattr(
            cli, name, Mock(side_effect=AssertionError("must not call media/model"))
        )

    def refresh(get, token, user, account, wanted, *, scan_log, **kwargs):
        scan_log.append(
            {
                "account": account.username,
                "stopped": "INSTAGRAM_USAGE_HIGH",
                "usage": {"total_time": 80},
            }
        )
        return RefreshResult({}, set(), set(wanted), "INSTAGRAM_USAGE_HIGH")

    refreshed = Mock(side_effect=refresh)
    monkeypatch.setattr(cli, "refresh_media_urls", refreshed)
    first = creative("a").model_copy(
        update={"source": Source.instagram, "account": "account-a"}
    )
    second = creative("b").model_copy(
        update={"source": Source.instagram, "account": "account-b"}
    )
    with ExitStack() as stack:
        deps = cli._live_deps(
            sources={Source.instagram}, environ=rig.env, env_file=None, stack=stack
        )
        plans = deps.analysis.plans([first, second])
        assert all(plan.state == "refresh_stopped" for plan in plans.values())
        assert deps.analysis.rerefresh(first)() is None
        assert refreshed.call_count == 1
        transport.assert_not_called()
        assert len(deps.scan_log) == 1
    connection.close.assert_called_once()


def test_dry_run_no_item_estimate_or_settings_access(rig, monkeypatch):
    monkeypatch.setattr(
        cli, "load_settings", Mock(side_effect=AssertionError("no settings in dry-run"))
    )
    assert execute(rig, ["--dry-run"]) == 0
    preview = json.loads(rig.out.getvalue().removeprefix("ESTIMATE "))
    assert "calls_min" not in preview
    assert "calls_max" not in preview
    assert preview["preregistration_path"] == str(rig.prereg)
    rig.factory.assert_not_called()


@pytest.mark.parametrize("port", ["bad", "0", "65536"])
def test_invalid_postgres_port_has_stable_code(rig, port):
    rig.env["BEAUTYADS_POSTGRES_PORT"] = port
    assert execute(rig) == 2
    assert "PREFLIGHT_FAILED POSTGRES_UNREACHABLE" in rig.out.getvalue()
    rig.factory.assert_not_called()
    rig.tcp.assert_not_called()
