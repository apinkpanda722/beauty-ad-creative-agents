from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_links_domain import product
from test_product_identify import material, response

from beautyads.domain import JobStatus
from beautyads.llm import (
    DailyLimitReached,
    ErrorKind,
    FileError,
    LlmCallError,
    UploadedFile,
)
from beautyads.pipeline.analyze import AnalysisDeps
from beautyads.pipeline.media_flow import MediaDeps, UrlPlan
from beautyads.pipeline.product_identify import IdentifyDeps, main, run_identification
from beautyads.sources.media import DownloadedMedia


class Store:
    def __init__(self, creatives):
        self.creatives = creatives
        self.jobs = {
            (c.key, "content_type@v1"): SimpleNamespace(
                key=c.key,
                kind="content_type@v1",
                status=JobStatus.done,
                labels={"content_type": "product_creative"},
            )
            for c in creatives
        }
        self.writes = []
        self.attempts = {}

    def list_creatives(self, **kwargs):
        return self.creatives

    def get_job_results(self, kind, keys):
        return [self.jobs[(key, kind)] for key in keys if (key, kind) in self.jobs]

    def enqueue_analysis(self, kind, creatives):
        for c in creatives:
            self.jobs.setdefault(
                (c.key, kind), SimpleNamespace(status=JobStatus.pending, labels=None)
            )

    def record_analysis(self, kind, key, **kwargs):
        self.writes.append((kind, key, kwargs))
        self.jobs[(key, kind)] = SimpleNamespace(key=key, kind=kind, **kwargs)
        self.attempts[key] = self.attempts.get(key, 0) + 1


def deps_for(creatives, interact=None):
    store = Store(creatives)
    media = MediaDeps(
        Mock(return_value=DownloadedMedia(b"synthetic", "video/mp4", 9)),
        Mock(return_value=UploadedFile("files/synthetic", 9)),
        Mock(),
        Mock(return_value=True),
    )
    analysis = AnalysisDeps(
        store,
        media,
        Mock(
            return_value={
                c.key: UrlPlan("https://example.test/transient", "ok")
                for c in creatives
                if c.source == "instagram"
            }
        ),
        Mock(return_value=None),
        Mock(),
        Mock(),
    )
    return IdentifyDeps(
        analysis,
        [product()],
        interact or Mock(return_value=response({"candidates": ["C1"]})),
    )


def run(tmp_path, deps, **kwargs):
    out = StringIO()
    report = run_identification(
        deps, ledger_path=tmp_path / "costs", caps={"gemini": 12}, out=out, **kwargs
    )
    return report, out.getvalue()


def test_sample_is_reproducible_bounded_and_reports_review_pairs(tmp_path):
    creatives = [material(id=str(i), caption="x" * 130) for i in range(30)]
    deps = deps_for(creatives)
    first, _ = run(tmp_path, deps, sample=23, seed=7, sample_pairs=20)
    other = deps_for(list(reversed(creatives)))
    second, _ = run(tmp_path, other, sample=23, seed=7, sample_pairs=20)
    assert deps.interact.call_count == other.interact.call_count == 23
    assert first["target_count"] == 30 and first["processed"] == 23
    assert first["done"] == first["newly_linked"] == 23
    assert first["video_multi_product"] == 0
    assert first["sample_pairs"] == second["sample_pairs"]
    assert len(first["sample_pairs"]) == 20
    assert all(
        len(p["caption"]) == 120 and p["url"].startswith("https://")
        for p in first["sample_pairs"]
    )
    assert all(kind == "product-id@v1" for kind, _, _ in deps.analysis.store.writes)
    # A second run never reopens completed product identification jobs.
    repeated, _ = run(tmp_path, deps, sample=23)
    assert repeated["processed"] == 7 and deps.interact.call_count == 30


def test_dry_run_has_count_and_assumption_without_calls_or_writes(tmp_path):
    deps = deps_for([material()])
    report, text = run(tmp_path, deps, dry_run=True)
    assert report["target_count"] == 1 and "가정(미실측)" in text
    assert report["estimate"]["video_tokens"] == 60 * 91
    assert report["estimate"]["cost_usd"] > 0
    deps.interact.assert_not_called()
    deps.analysis.plans.assert_not_called()
    assert deps.analysis.store.writes == []


@pytest.mark.parametrize("kind", [ErrorKind.DAILY_LIMIT, ErrorKind.CREDITS_DEPLETED])
def test_global_quota_stops_batch_with_pending_jobs(tmp_path, kind):
    deps = deps_for([material(id=str(i)) for i in range(3)])
    deps.interact.side_effect = DailyLimitReached(kind=kind, code=kind.value)
    report, _ = run(tmp_path, deps)
    assert report["processed"] == report["failed"] == 0 and report["pending"] == 3
    assert report["stopped"] == kind.value and deps.interact.call_count == 1
    assert deps.analysis.store.writes == []


def test_failure_isolated_and_validation_attempts_persist(tmp_path):
    deps = deps_for([material(id=str(i)) for i in range(3)])
    deps.interact.side_effect = [
        RuntimeError("synthetic"),
        response({"candidates": ["outside"]}),
        response({"candidates": []}),
        response({"candidates": ["C1"]}),
    ]
    report, _ = run(tmp_path, deps)
    assert report["processed"] == 3 and report["failed"] == 1 and report["done"] == 2
    assert sorted(deps.analysis.store.attempts.values()) == [1, 1, 2]
    assert report["newly_linked"] == 1


@pytest.mark.parametrize("failure", [None, "wait", "model", "quota"])
def test_instagram_reuses_media_and_deletes_even_on_failure(tmp_path, failure):
    deps = deps_for([material(source="instagram")])
    if failure == "wait":
        deps.analysis.media.wait.side_effect = FileError("FILE_STATUS_ERROR")
    if failure == "model":
        deps.interact.side_effect = RuntimeError("synthetic")
    if failure == "quota":
        deps.interact.side_effect = DailyLimitReached(
            kind=ErrorKind.DAILY_LIMIT, code="DAILY_LIMIT"
        )
    report, _ = run(tmp_path, deps)
    deps.analysis.plans.assert_called_once()
    deps.analysis.media.download.assert_called_once_with(
        "https://example.test/transient"
    )
    assert deps.analysis.media.upload.call_args.args == (b"synthetic",)
    deps.analysis.media.delete.assert_called_once_with("files/synthetic")
    assert list(tmp_path.iterdir()) == []
    if failure is None:
        assert report["done"] == 1
        parts = deps.interact.call_args.kwargs["input_parts"]
        assert parts[1]["uri"] == "files/synthetic"
        assert report["sample_pairs"][0]["url"] == material(source="instagram").url


def test_no_candidates_never_prepares_or_calls(tmp_path):
    deps = deps_for([material()])._replace(products=[])
    report, _ = run(tmp_path, deps)
    assert report["target_count"] == report["processed"] == 0
    deps.interact.assert_not_called()
    deps.analysis.plans.assert_not_called()


def test_authentication_stops_without_failed_jobs(tmp_path):
    deps = deps_for([material(id="a"), material(id="b")])
    deps.interact.side_effect = LlmCallError(
        kind=ErrorKind.FATAL, code="FATAL", message="API key not valid"
    )
    report, _ = run(tmp_path, deps)
    assert report["stopped"] == "AUTH_FAILED" and report["pending"] == 2
    assert report["failed"] == 0 and deps.interact.call_count == 1


def test_main_requires_explicit_full_cost_approval_and_preflight_is_offline(tmp_path):
    deps = deps_for([material()])
    out = StringIO()
    factory = Mock(return_value=deps)
    assert main([], environ={}, out=out, deps_factory=factory) == 2
    assert "COST_APPROVAL_REQUIRED" in out.getvalue()
    factory.assert_not_called()
    out = StringIO()
    assert (
        main(
            ["--sample", "1"],
            environ={},
            out=out,
            deps_factory=factory,
            docker_check=lambda: False,
            tcp_check=lambda *_: False,
        )
        == 2
    )
    assert "ENV_MISSING:GEMINI_API_KEY" in out.getvalue()
    assert "DOCKER_DOWN" in out.getvalue() and "POSTGRES_UNREACHABLE" in out.getvalue()
    factory.assert_not_called()


def test_make_target_is_added_without_live_verification():
    from pathlib import Path

    makefile = Path("Makefile").read_text()
    assert (
        "live-product-identify:\n\tuv run python -m beautyads.pipeline.product_identify $(ARGS)"
        in makefile
    )
    assert "live-" not in makefile.split("verify:\n", 1)[1].split("\n\n", 1)[0]


def test_cap_stops_before_media_or_model_and_leaves_pending(tmp_path):
    from datetime import UTC, datetime

    from beautyads.analysis.models import ANALYSIS_MODEL_ID
    from beautyads.obs.ledger import LedgerEntry, append_entry

    append_entry(
        tmp_path / "costs",
        LedgerEntry(
            ts=datetime.now(UTC),
            provider="gemini",
            model=ANALYSIS_MODEL_ID,
            purpose="synthetic",
            cost_usd=12,
            cost_source="response_cost",
        ),
    )
    deps = deps_for([material(source="instagram")])
    report, _ = run(tmp_path, deps)
    assert report["stopped"] == "COST_CAP:gemini" and report["pending"] == 1
    deps.interact.assert_not_called()
    deps.analysis.plans.assert_not_called()


def test_multi_product_gain_and_cost_use_ledger_not_model_accuracy(tmp_path):
    from datetime import UTC, datetime

    from beautyads.analysis.models import ANALYSIS_MODEL_ID
    from beautyads.obs.ledger import LedgerEntry, append_entry

    products = [product(url="a"), product("합성 다른 앰플", url="b")]
    deps = deps_for([material()])._replace(products=products)

    def interact(**kwargs):
        assert kwargs["purpose"] == "product-identify"
        candidate_ids = kwargs["response_format"]["schema"]["properties"]["candidates"][
            "items"
        ]["enum"]
        append_entry(
            tmp_path / "costs",
            LedgerEntry(
                ts=datetime.now(UTC),
                provider="gemini",
                model=ANALYSIS_MODEL_ID,
                purpose=kwargs["purpose"],
                input_tokens=1000,
                cost_usd=0.002,
                cost_source="response_cost",
            ),
        )
        return response({"candidates": candidate_ids})

    deps = deps._replace(interact=interact)
    report, _ = run(tmp_path, deps)
    assert report["newly_linked"] == report["video_multi_product"] == 1
    assert report["by_basis"] == {"title": 0, "caption": 0, "video": len(products)}
    assert report["cost_usd"] == 0.002
    estimate, _ = run(tmp_path, deps_for([material(id="other")]), dry_run=True)
    assert estimate["estimate"]["effective_usd_per_input_token"] == 0.002 / 1000
    assert "원장 실측" in estimate["estimate"]["rate_source"]


def test_instagram_reuses_expired_download_rerefresh_and_redacts_uris(tmp_path):
    from beautyads.sources.media import MediaError

    deps = deps_for([material(source="instagram")])
    deps.analysis.media.download.side_effect = [
        MediaError("MEDIA_URL_UNAVAILABLE"),
        DownloadedMedia(b"synthetic", "video/mp4", 9),
    ]
    refresh = Mock(return_value="https://example.test/refreshed")
    deps.analysis.rerefresh.return_value = refresh
    deps.interact.return_value = response(
        {
            "candidates": [
                "files/synthetic https://example.test/refreshed https://example.test/transient"
            ]
        }
    )
    report, text = run(tmp_path, deps)
    assert report["held"] == 1
    refresh.assert_called_once()
    deps.analysis.media.delete.assert_called_once()
    assert "files/synthetic" not in str(deps.analysis.store.writes)
    assert "https://example.test/transient" not in str(deps.analysis.store.writes)
    assert "https://example.test/refreshed" not in str(deps.analysis.store.writes)
    assert "files/synthetic" not in text


def test_cli_dry_run_with_fake_dependencies_passes_all_options(tmp_path):
    deps = deps_for([material(id=str(i)) for i in range(10)])
    out = StringIO()
    assert (
        main(
            [
                "--dry-run",
                "--sample",
                "5",
                "--max-videos",
                "3",
                "--seed",
                "9",
                "--sample-pairs",
                "2",
                "--thinking-level",
                "low",
                "--window-max-s",
                "10",
            ],
            environ={
                "GEMINI_API_KEY": "synthetic",
                "POSTGRES_PASSWORD": "synthetic",
                "BEAUTYADS_LEDGER_PATH": str(tmp_path / "ledger"),
            },
            out=out,
            deps_factory=lambda: deps,
            docker_check=lambda: True,
            tcp_check=lambda *_: True,
        )
        == 0
    )
    import json

    report = json.loads(out.getvalue())
    assert report["target_count"] == 10 and report["selected"] == 3
    assert report["seed"] == 9 and report["estimate"]["video_tokens"] == 3 * 10 * 91
    deps.interact.assert_not_called()
    deps.analysis.plans.assert_not_called()


def test_file_permission_failure_is_isolated_from_authentication(tmp_path):
    deps = deps_for([material(id="a"), material(id="b")])
    deps.interact.side_effect = [
        LlmCallError(
            kind=ErrorKind.FATAL, code="FILE_NOT_FOUND", message="403 permission_denied"
        ),
        response({"candidates": []}),
    ]
    report, _ = run(tmp_path, deps)
    assert report["failed"] == 1 and report["done"] == 1 and report["stopped"] is None


def test_expiring_instagram_url_is_refreshed_before_download(tmp_path):
    from datetime import UTC, datetime, timedelta

    from beautyads.domain import Source

    creative = material(source="instagram")
    deps = deps_for([creative])
    now = datetime(2026, 11, 17, tzinfo=UTC)
    expiring = (
        f"https://example.test/old?oe={int((now + timedelta(hours=1)).timestamp()):x}"
    )
    fresh = (
        f"https://example.test/new?oe={int((now + timedelta(days=1)).timestamp()):x}"
    )
    deps.analysis.now.return_value = now
    deps.analysis.plans.return_value = {creative.key: UrlPlan(expiring, "ok")}
    refresh = Mock(return_value=fresh)
    deps.analysis.rerefresh.return_value = refresh
    report, _ = run(tmp_path, deps)
    assert report["done"] == 1
    deps.analysis.media.download.assert_called_once_with(fresh)
    assert deps.analysis.plans.call_args.args[0][0].source == Source.instagram
    refresh.assert_called_once()


def test_instagram_plans_are_prepared_once_for_the_bounded_selection(tmp_path):
    deps = deps_for([material(source="instagram", id=str(i)) for i in range(8)])
    report, _ = run(tmp_path, deps, sample=3)
    assert report["processed"] == 3
    deps.analysis.plans.assert_called_once()
    assert len(deps.analysis.plans.call_args.args[0]) == 3


def test_missing_instagram_auth_stops_pending_instead_of_failing_materials(tmp_path):
    from beautyads.settings import SettingError

    deps = deps_for([material(source="instagram", id=str(i)) for i in range(3)])
    deps.analysis.plans.side_effect = SettingError(
        name="INSTAGRAM_ACCESS_TOKEN", code="ENV_MISSING"
    )
    report, _ = run(tmp_path, deps)
    assert report["pending"] == 3 and report["failed"] == 0
    assert report["stopped"] == "ENV_MISSING:INSTAGRAM_ACCESS_TOKEN"
    deps.interact.assert_not_called()


@pytest.mark.parametrize("prior_status", [JobStatus.held, JobStatus.failed])
def test_quota_resume_leaves_previously_unsuccessful_selected_jobs_pending(
    tmp_path, prior_status
):
    creative = material()
    deps = deps_for([creative])
    deps.analysis.store.jobs[(creative.key, "product-id@v1")] = SimpleNamespace(
        key=creative.key,
        kind="product-id@v1",
        status=prior_status,
        labels=None,
        model=None,
        thinking_level="minimal",
        prompt_version="product-id-v1",
        error_code="INVALID_OUTPUT",
    )
    deps.interact.side_effect = DailyLimitReached(
        kind=ErrorKind.DAILY_LIMIT, code="DAILY_LIMIT"
    )
    report, _ = run(tmp_path, deps)
    assert report["processed"] == report["failed"] == 0
    assert (
        deps.analysis.store.jobs[(creative.key, "product-id@v1")].status
        == JobStatus.pending
    )
    assert all(
        row[2]["status"] == JobStatus.pending for row in deps.analysis.store.writes
    )


def _ledger_with_gemini_spend(tmp_path, usd):
    from datetime import UTC, datetime

    from beautyads.analysis.models import ANALYSIS_MODEL_ID
    from beautyads.obs.ledger import LedgerEntry, append_entry

    append_entry(
        tmp_path / "ledger",
        LedgerEntry(
            ts=datetime.now(UTC),
            provider="gemini",
            model=ANALYSIS_MODEL_ID,
            purpose="synthetic",
            cost_usd=usd,
            cost_source="response_cost",
        ),
    )


def _cli(tmp_path, cap):
    environ = {
        "GEMINI_API_KEY": "synthetic",
        "POSTGRES_PASSWORD": "synthetic",
        "BEAUTYADS_LEDGER_PATH": str(tmp_path / "ledger"),
    }
    if cap is not None:
        environ["BEAUTYADS_CAP_GEMINI_USD"] = cap
    out = StringIO()
    code = main(
        ["--dry-run", "--sample", "1"],
        environ=environ,
        out=out,
        deps_factory=lambda: deps_for([material()]),
        docker_check=lambda: True,
        tcp_check=lambda *_: True,
    )
    return code, out.getvalue()


def test_the_gemini_cap_comes_from_the_setting_not_a_fixed_ceiling(tmp_path):
    # Spend above the default 12 but below an explicitly raised cap (the same
    # environment override `live-products` uses): the run must start.
    _ledger_with_gemini_spend(tmp_path, 12.5)
    code, text = _cli(tmp_path, "14")
    assert "COST_CAP" not in text and code == 0
    # Without the override the default cap still stops it, and so does a spend
    # above the raised cap.
    code, text = _cli(tmp_path, None)
    assert code == 2 and "PREFLIGHT_FAILED COST_CAP:gemini" in text
    _ledger_with_gemini_spend(tmp_path, 2)
    code, text = _cli(tmp_path, "14")
    assert code == 2 and "PREFLIGHT_FAILED COST_CAP:gemini" in text
