"""Same-run TikTok collection and analysis, with synthetic stores and media only."""

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest.mock import Mock

import pytest

from beautyads.domain import Creative, JobResult, JobStatus, Source
from beautyads.llm import DailyLimitReached, ErrorKind
from beautyads.pipeline import analyze as runner
from beautyads.pipeline import tiktok_collect_analyze as mod
from beautyads.pipeline.analyze_target import PER_BRAND_SAMPLE_SEED, select_per_brand
from beautyads.pipeline.media_flow import (
    AnalysisRun,
    AxisRecord,
    CreativeOutcome,
    MediaDeps,
    UrlPlan,
)
from beautyads.sources.config import TikTokBrand
from beautyads.sources.tiktok import BrandCollection

NOW = datetime(2026, 11, 14, tzinfo=UTC)
URL_SENTINEL = "https://example.invalid/PRIVATE_SIGNED_URL_SENTINEL"
KIND = "content_type@v1"


def creative(brand, index):
    return Creative(
        source=Source.tiktok,
        source_id=f"{brand}-{index:03}",
        url=None,
        collected_at=NOW,
        analyzable=True,
        brand=brand,
        account=None,
    )


class Store:
    def __init__(self):
        self.creatives = {}
        self.jobs = {}
        self.upserts = []

    def upsert_creatives(self, creatives):
        self.upserts.append(list(creatives))
        self.creatives.update((c.key, c) for c in creatives)
        return len(creatives)

    def get_creative(self, key):
        return self.creatives.get(key)

    def collection_stats(self):
        return []

    def list_creatives(
        self, *, brands=None, sources=None, analyzable_only=False, limit=None
    ):
        return [
            c
            for c in self.creatives.values()
            if (brands is None or c.brand in brands)
            and (sources is None or c.source in sources)
            and (not analyzable_only or c.analyzable is True)
        ][:limit]

    def enqueue_analysis(self, kind, creatives):
        for c in creatives:
            if (kind, c.key) not in self.jobs:
                self.jobs[kind, c.key] = JobResult(
                    key=c.key,
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
                )
        return len(creatives)

    def next_pending(self, kind, limit):
        return [
            self.creatives[key]
            for (k, key), job in self.jobs.items()
            if k == kind and job.status == JobStatus.pending
        ][:limit]

    def requeue_jobs(self, kind, error_codes):
        return 0

    def job_counts(self, kind):
        counts = dict.fromkeys((s.value for s in JobStatus), 0)
        for (k, _), job in self.jobs.items():
            if k == kind:
                counts[job.status.value] += 1
        return counts

    def get_job_results(self, kind, keys):
        keys = set(keys)
        return [job for (k, key), job in self.jobs.items() if k == kind and key in keys]

    def record_analysis(self, kind, key, **kwargs):
        job = self.jobs[kind, key]
        self.jobs[kind, key] = job.model_copy(
            update={**kwargs, "attempts": job.attempts + 1}
        )


def put_job(store, item, status, code=None):
    store.creatives[item.key] = item
    store.enqueue_analysis(KIND, [item])
    store.jobs[KIND, item.key] = store.jobs[KIND, item.key].model_copy(
        update={"status": status, "error_code": code}
    )


def done_outcome(item, run, status=JobStatus.done, code=None):
    return CreativeOutcome(
        key=item.key,
        records=[
            AxisRecord(
                kind=f"content_type@{run.run_tag}",
                status=status,
                labels=None,
                model=None,
                thinking_level=run.thinking_level,
                prompt_version=None,
                raw_output=None,
                error_code=code,
            )
        ],
        cleanup="none",
        mark_not_analyzable=False,
    )


@pytest.fixture
def rig(tmp_path, monkeypatch):
    store = Store()
    seen_plans = {}

    def fake_analyze(item, *, plan, run, **kwargs):
        seen_plans[item.source_id] = plan
        return done_outcome(item, run)

    fake = Mock(side_effect=fake_analyze)
    monkeypatch.setattr(runner, "analyze_creative", fake)
    run = AnalysisRun(
        "minimal",
        "v1",
        "analyze-target",
        tmp_path / "costs.jsonl",
        {"gemini": 12},
        60,
        60,
        3,
        Mock(),
        purpose_by_axis=True,
    )
    brands = [TikTokBrand(brand=n, search_term=n) for n in ("alpha", "beta", "gamma")]

    def make(collections):
        collected = []

        def collect_brand(brand):
            collected.append(brand.brand)
            result = collections[brand.brand]
            if isinstance(result, Exception):
                raise result
            return result

        analysis = runner.AnalysisDeps(
            store,
            MediaDeps(*(Mock() for _ in range(4))),
            Mock(),
            Mock(),
            Mock(),
            Mock(side_effect=lambda: NOW + timedelta(seconds=len(collected))),
        )
        return mod.TiktokRunDeps(analysis, Mock(), collect_brand, brands), collected

    return type(
        "Rig",
        (),
        {
            "store": store,
            "fake": fake,
            "run": run,
            "make": staticmethod(make),
            "plans": seen_plans,
        },
    )


def full(brand, count, *, urls=True):
    items = [creative(brand, i) for i in range(count)]
    return BrandCollection(
        items, {c.source_id: URL_SENTINEL for c in items} if urls else {}, None
    )


def go(rig, collections, *, limit=5, brands=None):
    deps, collected = rig.make(collections)
    out = StringIO()
    code = mod.run_collect_analyze(
        deps,
        run=rig.run,
        brands=brands,
        per_brand_limit=limit,
        ledger_start=0,
        out=out,
    )
    return code, out.getvalue(), collected


def analyzed(rig):
    return {c.args[0].source_id for c in rig.fake.call_args_list}


def test_selects_the_seeded_prefix_of_what_this_run_returned(rig):
    pool = full("alpha", 10)
    code, _out, _ = go(
        rig, {"alpha": pool, "beta": full("beta", 0), "gamma": full("gamma", 0)}
    )
    expected = {
        c.source_id for c in select_per_brand(pool.creatives, 5, PER_BRAND_SAMPLE_SEED)
    }
    assert code == 0 and analyzed(rig) == expected and len(expected) == 5
    # the earlier, smaller sample is a prefix of the larger one (not newest-first)
    first_two = {
        c.source_id for c in select_per_brand(pool.creatives, 2, PER_BRAND_SAMPLE_SEED)
    }
    assert first_two <= expected


def test_already_analyzed_items_count_toward_the_brand_target(rig):
    pool = full("alpha", 10)
    for item in pool.creatives[:3]:
        put_job(rig.store, item, JobStatus.done)
    go(
        rig,
        {"alpha": pool, "beta": full("beta", 0), "gamma": full("gamma", 0)},
        limit=5,
    )
    # 3 done already: only 2 more are analyzed, and never one of the done ones
    new = analyzed(rig)
    assert len(new) == 2
    assert not new & {c.source_id for c in pool.creatives[:3]}
    # a second identical run has nothing left to do
    rig.fake.reset_mock()
    go(
        rig,
        {"alpha": pool, "beta": full("beta", 0), "gamma": full("gamma", 0)},
        limit=5,
    )
    assert rig.fake.call_count == 0


def test_failed_items_are_left_alone(rig):
    pool = full("alpha", 6)
    stale = pool.creatives[0]
    put_job(rig.store, stale, JobStatus.failed, "MEDIA_URL_MISSING_UNCONFIRMED")
    go(
        rig,
        {"alpha": pool, "beta": full("beta", 0), "gamma": full("gamma", 0)},
        limit=6,
    )
    assert stale.source_id not in analyzed(rig)
    assert rig.store.jobs[KIND, stale.key].error_code == "MEDIA_URL_MISSING_UNCONFIRMED"
    assert rig.store.jobs[KIND, stale.key].attempts == 0


def test_urls_exist_only_in_memory_and_plans_use_them_without_a_refresh(rig):
    pool = full("alpha", 4)
    _code, out, _ = go(
        rig,
        {"alpha": pool, "beta": full("beta", 0), "gamma": full("gamma", 0)},
        limit=4,
    )
    assert all(plan == UrlPlan(URL_SENTINEL, "ok") for plan in rig.plans.values())
    assert rig.plans
    stored = json.dumps(
        [c.model_dump(mode="json") for b in rig.store.upserts for c in b]
    )
    assert URL_SENTINEL not in stored and URL_SENTINEL not in out
    assert all(c.url is None for c in rig.store.creatives.values())


def test_items_without_a_video_url_are_not_invented_as_absent(rig):
    pool = full("alpha", 3, urls=False)
    go(
        rig,
        {"alpha": pool, "beta": full("beta", 0), "gamma": full("gamma", 0)},
        limit=3,
    )
    assert all(plan.state == "missing" for plan in rig.plans.values())


def test_a_failing_brand_is_isolated_and_stores_nothing(rig):
    failed = BrandCollection([], {}, "TIKTOK_HTTP_500")
    code, out, collected = go(
        rig,
        {"alpha": failed, "beta": full("beta", 3), "gamma": full("gamma", 0)},
        limit=3,
    )
    assert collected == ["alpha", "beta", "gamma"]
    assert code == 0
    assert all(c.brand == "beta" for c in rig.store.creatives.values())
    summary = json.loads(out.strip().splitlines()[-1])
    assert summary["errors"] == {"TIKTOK_HTTP_500": 1}


def test_an_account_level_collection_error_stops_every_later_brand(rig):
    code, out, collected = go(
        rig,
        {
            "alpha": BrandCollection([], {}, "TIKTOK_TOKEN_INVALID"),
            "beta": full("beta", 3),
            "gamma": full("gamma", 3),
        },
    )
    assert code == 3 and collected == ["alpha"] and not rig.fake.called
    assert "STOPPED TIKTOK_TOKEN_INVALID" in out


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (
            DailyLimitReached(kind=ErrorKind.DAILY_LIMIT, code="DAILY_LIMIT"),
            "DAILY_LIMIT",
        ),
        (
            DailyLimitReached(kind=ErrorKind.CREDITS_DEPLETED, code="CREDITS_DEPLETED"),
            "CREDITS_DEPLETED",
        ),
    ],
)
def test_a_model_side_stop_ends_the_run_and_leaves_items_pending(rig, error, reason):
    rig.fake.side_effect = error
    code, out, collected = go(
        rig,
        {"alpha": full("alpha", 3), "beta": full("beta", 3), "gamma": full("gamma", 3)},
        limit=3,
    )
    assert code == 3 and collected == ["alpha"]
    assert f"STOPPED {reason}" in out
    assert all(job.status == JobStatus.pending for job in rig.store.jobs.values())


def test_brand_filter_and_output_have_no_category_or_url(rig):
    code, out, collected = go(
        rig,
        {"alpha": full("alpha", 2), "beta": full("beta", 2), "gamma": full("gamma", 2)},
        limit=2,
        brands={"beta"},
    )
    assert collected == ["beta"] and code == 0
    assert "category" not in out and URL_SENTINEL not in out
    summary = json.loads(out.strip().splitlines()[-1])
    assert summary["sampling"]["seed"] == PER_BRAND_SAMPLE_SEED
    assert summary["sampling"]["per_brand_limit"] == 2


def test_missing_tiktok_keys_fail_before_any_connection():
    out = StringIO()
    called = Mock()
    code = mod.main(
        ["--per-brand-limit", "5"],
        environ={"GEMINI_API_KEY": "x", "POSTGRES_PASSWORD": "x"},
        out=out,
        deps_factory=called,
        docker_check=Mock(return_value=True),
        tcp_check=Mock(return_value=True),
    )
    assert (
        code == 2 and "PREFLIGHT_FAILED ENV_MISSING:TIKTOK_CLIENT_KEY" in out.getvalue()
    )
    called.assert_not_called()


def test_dry_run_calls_nothing():
    out = StringIO()
    code = mod.main(["--per-brand-limit", "20", "--dry-run"], environ={}, out=out)
    assert code == 0 and out.getvalue().startswith("ESTIMATE ")
    assert "20261114" in out.getvalue()


def test_make_target_is_manual_only():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
    assert "live-tiktok-analyze" in text.splitlines()[0].split()
    assert (
        "live-tiktok-analyze:\n\tuv run python -m beautyads.pipeline.tiktok_collect_analyze"
        in text
    )
    verify = text.split("verify:\n", 1)[1].split("\n\n", 1)[0]
    assert "live-" not in verify
