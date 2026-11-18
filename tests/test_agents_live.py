"""The user-run batch is exercised only with temporary metadata and local fakes."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from beautyads.api.chat_client import AskOutcome
from beautyads.eval import agents_live
from beautyads.obs.ledger import LedgerEntry, append_entry
from beautyads.obs.trace import append_trace, build_trace
from beautyads.settings import InvalidSetting, Settings
from beautyads.sources.workspaces import load_workspaces

START = datetime(2026, 11, 18, tzinfo=UTC)
SECRET = "SYNTHETIC-SECRET-private-message-and-diagnostic"


def outcome(*, status=200, code=None):
    return AskOutcome(
        events=[("error", {"error_code": code, "detail": SECRET})]
        if code is not None
        else [("step", {}), ("token", {"text": SECRET})],
        ui_commands=[{"text": SECRET}],
        final_text=SECRET,
        status_code=status,
    )


@pytest.fixture
def rig(tmp_path, monkeypatch):
    root = tmp_path / "data" / "interim" / "agents_live"
    monkeypatch.setattr(agents_live, "OUTPUT_ROOT", root)
    settings = Settings(ledger_path=tmp_path / "costs.jsonl")
    state = SimpleNamespace(
        root=root,
        settings=settings,
        calls=[],
        assemblies=[],
        closed=[],
        now=START,
        behavior=lambda **kw: outcome(),
    )

    def clock():
        state.now += timedelta(milliseconds=10)
        return state.now

    def assemble(**kwargs):
        state.assemblies.append(kwargs)
        return SimpleNamespace(close=lambda: state.closed.append(True))

    def run(app, **kwargs):
        state.calls.append(kwargs)

        async def invoke():
            async with app.router.lifespan_context(app):
                return state.behavior(**kwargs)

        return asyncio.run(invoke())

    def invoke(*args, **kwargs):
        out = StringIO()
        code = agents_live.main(
            list(args) or ["--config", "dev"],
            **{
                "out": out,
                "settings": settings,
                "check": list,
                "run": run,
                "assemble": assemble,
                "clock": clock,
                **kwargs,
            },
        )
        lines = out.getvalue().splitlines()
        summary = json.loads(lines[-1]) if lines and lines[-1].startswith("{") else None
        return code, summary, out.getvalue()

    def spend(provider, cost, purpose="planning"):
        append_entry(
            settings.ledger_path,
            LedgerEntry(
                ts=state.now,
                provider=provider,
                model="synthetic-model",
                purpose=purpose,
                cost_usd=cost,
                cost_source="price_table",
            ),
        )

    state.invoke, state.spend = invoke, spend
    return state


def test_scenario_invariants_and_config_subsets():
    assert agents_live.RUN_CAPS == {"openai": 0.7, "anthropic": 0.6, "image": 0.2}
    scenarios = agents_live.SCENARIOS
    dev_tenants = {
        w.tenant_id
        for w in load_workspaces(Path("config/workspaces.yaml"))
        if w.group == "dev"
    }
    assert len({s["id"] for s in scenarios}) == len(scenarios)
    assert {s["tenant_id"] for s in scenarios} <= dev_tenants
    assert {s["kind"] for s in scenarios} <= {"pattern", "relation", "plan", "boundary"}
    assert all(1 <= len(s["message"]) <= 2000 for s in scenarios)
    assert any(s["kind"] == "boundary" for s in scenarios)
    plans = [s for s in scenarios if s["kind"] == "plan"]
    assert plans
    assert agents_live.select_scenarios("dev") == list(scenarios)
    assert agents_live.select_scenarios("official") == plans
    image = agents_live.select_scenarios("image")
    assert len(image) == 1 and image == plans[:1]


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--config", "unknown"],
        ["--config", "dev", "--only", SECRET],
        ["--config", "dev", "--tenant", SECRET],
        ["--config", "dev", "--max-usd", "9"],
    ],
)
def test_argument_errors_are_two_without_calls_or_raw_arguments(rig, args):
    if not args:
        out = StringIO()
        code = agents_live.main([], out=out)
        text = out.getvalue()
    else:
        code, _, text = rig.invoke(*args, check=lambda: pytest.fail("preflight called"))
    assert code == 2 and not rig.calls and not rig.root.exists()
    assert SECRET not in text


@pytest.mark.parametrize(
    "config,model,image",
    [
        ("dev", "claude-haiku-5-5", False),
        ("official", "claude-sonnet-5-5", False),
        ("image", "claude-sonnet-5-5", True),
    ],
)
def test_fp_c14_arguments_reach_fresh_assembly_and_run(rig, config, model, image):
    code, summary, _ = rig.invoke("--config", config)
    selected = agents_live.select_scenarios(config)
    assert code == 0 and not summary["pending"]
    assert len(rig.assemblies) == len(rig.calls) == len(selected) == len(rig.closed)
    for assembled, call, scenario in zip(
        rig.assemblies, rig.calls, selected, strict=True
    ):
        assert assembled["group"] == "dev"
        assert assembled["settings"] is rig.settings
        assert assembled["evaluation_model"] == model
        assert assembled["with_image_enabled"] is image
        assert assembled["limits"].max_text_cost_usd == min(0.30, 0.7 + 0.6)
        assert call == {
            "tenant_id": scenario["tenant_id"],
            "message": scenario["message"],
            "with_image": image,
        }


def test_only_is_repeatable_and_keeps_config_order(rig):
    plans = agents_live.select_scenarios("official")
    ids = [s["id"] for s in reversed(plans)]
    args = ["--config", "dev"]
    for sid in ids:
        args.extend(["--only", sid])
    code, summary, _ = rig.invoke(*args)
    assert code == 0
    assert [s["id"] for s in summary["scenarios"]] == list(reversed(ids))


def test_baseline_is_created_reused_and_only_explicitly_reset(rig):
    rig.spend("openai", 1.0)
    rig.spend("anthropic", 2.0)
    rig.spend("gemini", 0.5, "image-plan")
    assert rig.invoke("--config", "image")[0] == 0
    path = rig.root / "baseline.json"
    initial_bytes = path.read_bytes()
    initial = json.loads(initial_bytes)
    assert set(initial) == {"created_at", "provider_totals", "image_total"}
    assert initial["provider_totals"] == {"openai": 1.0, "anthropic": 2.0}
    assert initial["image_total"] == 0.5
    rig.spend("openai", 0.02)
    rig.spend("gemini", 0.03, "image")
    code, summary, _ = rig.invoke("--config", "image")
    assert code == 0 and path.read_bytes() == initial_bytes
    assert summary["budget"]["used"] == pytest.approx(
        {"openai": 0.02, "anthropic": 0, "image": 0.03}
    )
    code, summary, _ = rig.invoke("--config", "image", "--reset-baseline")
    assert code == 0 and path.read_bytes() != initial_bytes
    assert all(value == 0 for value in summary["budget"]["used"].values())


@pytest.mark.parametrize("bucket", ["openai", "anthropic", "image"])
@pytest.mark.parametrize("extra", [0, 0.01])
def test_each_cap_stops_before_next_request_and_persists_pending(rig, bucket, extra):
    assert rig.invoke("--config", "image")[0] == 0
    rig.calls.clear()
    rig.assemblies.clear()
    rig.spend(
        "gemini" if bucket == "image" else bucket,
        agents_live.RUN_CAPS[bucket] + extra,
        "image-plan" if bucket == "image" else "unrelated-request",
    )
    code, summary, text = rig.invoke()
    assert code == 2 and "STOPPED BUDGET_REACHED" in text
    assert not rig.calls and not rig.assemblies
    assert summary["pending"] == [s["id"] for s in agents_live.SCENARIOS]
    assert summary["scenarios"] == []
    assert summary["budget"]["remaining"][bucket] == 0


def test_budget_is_checked_each_time_and_remaining_text_cap_is_forwarded(rig):
    rig.invoke("--config", "image")
    rig.assemblies.clear()
    rig.calls.clear()
    rig.spend("openai", 0.65)
    rig.spend("anthropic", 0.50)

    def run(**kw):
        rig.spend("anthropic", 0.10)
        return outcome()

    rig.behavior = run
    code, summary, _ = rig.invoke()
    assert code == 2 and len(rig.calls) == 1
    assert rig.assemblies[0]["limits"].max_text_cost_usd == pytest.approx(0.15)
    assert summary["pending"] == [s["id"] for s in agents_live.SCENARIOS[1:]]


@pytest.mark.parametrize("failure", ["event", "exception", "http"])
def test_request_failure_is_recorded_and_next_request_runs(rig, failure):
    def run(**kw):
        if len(rig.calls) == 1:
            if failure == "exception":
                raise RuntimeError(SECRET)
            return outcome(status=503) if failure == "http" else outcome(code="FATAL")
        return outcome()

    rig.behavior = run
    code, summary, text = rig.invoke()
    assert code == 3 and not summary["pending"]
    assert len(rig.calls) == len(agents_live.SCENARIOS)
    assert summary["scenarios"][0]["error_code"]
    assert all(s["error_code"] is None for s in summary["scenarios"][1:])
    assert SECRET not in text


@pytest.mark.parametrize("channel", ["event", "exception", "http", "trace"])
@pytest.mark.parametrize("error_code", ["DAILY_LIMIT", "RATE_LIMIT"])
def test_429_family_stops_without_retry(rig, channel, error_code):
    def run(**kw):
        if channel == "exception":
            exc = RuntimeError(SECRET)
            exc.code = error_code
            raise exc
        if channel == "trace":
            append_trace(
                rig.settings.ledger_path.with_name("traces.jsonl"),
                trace(rig, kw["tenant_id"], failure={"code": error_code}),
            )
            return outcome(code="AGENT_INTERNAL_ERROR")
        return outcome(status=429) if channel == "http" else outcome(code=error_code)

    rig.behavior = run
    code, summary, text = rig.invoke()
    assert code == 3 and len(rig.calls) == 1
    assert summary["pending"] == [s["id"] for s in agents_live.SCENARIOS[1:]]
    assert summary["scenarios"][0]["error_code"] in {error_code, "HTTP_429"}
    assert SECRET not in text


@pytest.mark.parametrize(
    "problem", ["DOCKER_DOWN", "MIGRATIONS_PENDING", "ENV_MISSING:ANTHROPIC_API_KEY"]
)
def test_preflight_failure_is_two_and_never_reads_ledger_or_assembles(
    rig, monkeypatch, problem
):
    monkeypatch.setattr(
        agents_live, "provider_total", lambda *a: pytest.fail("ledger read")
    )
    code, _, text = rig.invoke(check=lambda: [problem])
    assert code == 2 and f"PREFLIGHT_FAILED {problem}" in text
    assert not rig.calls and not rig.assemblies and not rig.root.exists()


def test_setting_error_reports_name_without_value(rig):
    def check():
        raise InvalidSetting("BEAUTYADS_CAP_OPENAI_USD")

    code, _, text = rig.invoke(check=check)
    assert code == 2
    assert text.strip() == "PREFLIGHT_FAILED INVALID_SETTING:BEAUTYADS_CAP_OPENAI_USD"


def test_setting_error_during_startup_is_a_preflight_failure(rig):
    def assemble(**kwargs):
        raise InvalidSetting("POSTGRES_PASSWORD")

    code, _, text = rig.invoke(assemble=assemble)
    assert code == 2 and len(rig.calls) == 1
    assert text.strip() == "PREFLIGHT_FAILED INVALID_SETTING:POSTGRES_PASSWORD"


@pytest.mark.parametrize("image", [False, True])
def test_default_preflight_reuses_service_checks_and_checks_required_model_keys(
    rig, monkeypatch, image
):
    seen = []
    monkeypatch.setattr(agents_live, "preflight", list)
    monkeypatch.setattr(agents_live, "get_setting", lambda name: seen.append(name))
    code, _, text = rig.invoke("--config", "image" if image else "dev", check=None)
    assert code == 2 and not rig.calls
    assert "PREFLIGHT_FAILED ENV_MISSING:ANTHROPIC_API_KEY" in text
    assert ("GEMINI_API_KEY" in seen) is image


@pytest.mark.parametrize("contents", ["not json", "{}", '{"created_at": "invalid"}'])
def test_invalid_baseline_never_grants_a_fresh_allowance(rig, contents):
    rig.root.mkdir(parents=True)
    path = rig.root / "baseline.json"
    path.write_text(contents)
    code, _, text = rig.invoke()
    assert code == 2 and not rig.calls
    assert "PREFLIGHT_FAILED BUDGET_BASELINE_INVALID:baseline" in text
    assert path.read_text() == contents


def test_absent_trace_does_not_shift_later_same_tenant_request(rig):
    records = []

    def run(**kw):
        if len(rig.calls) > 1:
            record = trace(rig, kw["tenant_id"])
            records.append(record)
            append_trace(rig.settings.ledger_path.with_name("traces.jsonl"), record)
        return outcome()

    rig.behavior = run
    code, summary, _ = rig.invoke()
    assert code == 0 and summary["scenarios"][0]["trace_id"] is None
    assert [s["trace_id"] for s in summary["scenarios"][1:]] == [
        record.trace_id for record in records
    ]


@pytest.mark.parametrize("config", ["dev", "official", "image"])
def test_dry_run_has_only_plan_and_never_reads_costs_or_initializes(
    rig, monkeypatch, config
):
    def forbidden(*args, **kwargs):
        pytest.fail("dry-run dependency called")

    for name in ("provider_total", "purpose_total", "read_traces", "load_settings"):
        monkeypatch.setattr(agents_live, name, forbidden)
    code, plan, text = rig.invoke(
        "--config",
        config,
        "--dry-run",
        "--reset-baseline",
        run=forbidden,
        assemble=forbidden,
        check=forbidden,
    )
    assert code == 0 and plan["config"] == config
    assert plan["budget"]["caps"] == agents_live.RUN_CAPS
    assert [s["id"] for s in plan["scenarios"]] == [
        s["id"] for s in agents_live.select_scenarios(config)
    ]
    assert all("message" not in s for s in plan["scenarios"])
    assert not rig.root.exists() and not rig.calls and SECRET not in text


@pytest.mark.parametrize(
    "cap,expected",
    [
        ("provider:gemini", "provider:gemini"),
        ("purpose:image", "purpose:image"),
        (SECRET, "unknown"),
    ],
)
def test_scenario_summary_copies_trace_limit_detail_without_private_caps(
    rig, cap, expected
):
    records = []

    def run(**kw):
        record = build_trace(
            tenant_id=kw["tenant_id"],
            started_at=rig.now,
            duration_ms=1,
            message=SECRET,
            result={
                "limit_hit": True,
                "limit_kinds": ["image", "text"],
                "limit_detail": [
                    {"kind": "image", "cap": cap},
                    {"kind": "text", "cap": "request:text"},
                ],
            },
            failure=None,
            ledger_entries=[],
            structured={},
        )
        records.append(record)
        append_trace(rig.settings.ledger_path.with_name("traces.jsonl"), record)
        return outcome()

    rig.behavior = run
    code, summary, text = rig.invoke("--config", "image")
    assert code == 0 and len(records) == 1
    expected_detail = [
        {"kind": "image", "cap": expected},
        {"kind": "text", "cap": "request:text"},
    ]
    assert summary["scenarios"][0]["limit_detail"] == expected_detail
    assert summary["scenarios"][0]["limit_detail"] == [
        item.model_dump() for item in records[0].limit_detail
    ]
    assert SECRET not in text
    assert (
        SECRET
        not in next(
            path for path in rig.root.glob("*.json") if path.name != "baseline.json"
        ).read_text()
    )


def test_scenario_without_trace_has_empty_limit_detail(rig):
    code, summary, _ = rig.invoke("--config", "image")
    assert code == 0 and summary["scenarios"][0]["limit_detail"] == []


def trace(rig, tenant, **kwargs):
    return build_trace(
        **{
            "tenant_id": tenant,
            "started_at": rig.now,
            "duration_ms": 123,
            "message": SECRET,
            "result": None,
            "failure": None,
            "ledger_entries": [],
            "structured": {},
            **kwargs,
        }
    )


@pytest.mark.parametrize("calls", [19, 20])
def test_trace_projection_aggregation_order_and_secret_exclusion(
    rig, monkeypatch, calls
):
    path = rig.settings.ledger_path.with_name("traces.jsonl")
    records = []
    scenario = agents_live.SCENARIOS[0]
    append_trace(path, trace(rig, scenario["tenant_id"]))  # older run, same tenant
    result = {
        "kind": "plan",
        "intent": "plan",
        "limit_hit": True,
        "limit_kinds": ["text", "steps"],
        "answer": SECRET,
        "plans": [
            {
                "status": "needs_review",
                "rework_count": 1,
                "unknown_count": 2,
                "efficacy_status": {"hydration": "unknown"},
                "plan": {"title": SECRET},
                "attempts": [
                    {
                        "attempt": 1,
                        "checks_passed": False,
                        "scores": {"fit": 2, "rationale": SECRET},
                        "failed_check_codes": ["EVIDENCE_MISSING"],
                    },
                    {
                        "attempt": 2,
                        "checks_passed": True,
                        "scores": {"fit": 4},
                        "failed_check_codes": [],
                    },
                ],
            }
        ],
    }
    scenarios = tuple({**s, "message": SECRET} for s in agents_live.SCENARIOS)
    monkeypatch.setattr(agents_live, "SCENARIOS", scenarios)

    def run(**kw):
        index = len(records)
        current = trace(
            rig,
            kw["tenant_id"],
            result=result,
            ledger_entries=[
                LedgerEntry(
                    ts=rig.now,
                    provider="anthropic",
                    model="claude-haiku-5-5",
                    purpose="evaluation",
                    cost_usd=0.01,
                    cost_source="price_table",
                )
            ],
            structured={
                "gpt-6-luna": {
                    "calls": calls if index == 0 else 0,
                    "failed_after_retry": 1,
                    "first_attempt_failures": {"PARSE_FAILED": 2},
                },
                "claude-haiku-5-5": {
                    "calls": 0,
                    "first_attempt_failures": {"SCHEMA_VIOLATION": 1},
                },
            },
        )
        records.append(current)
        append_trace(path, current)
        # An unrelated concurrent tenant must not steal a scenario's slot.
        append_trace(path, trace(rig, "unrelated-tenant"))
        with path.open("a") as stream:
            stream.write(SECRET + "\n")
        return outcome()

    rig.behavior = run
    code, summary, text = rig.invoke()
    assert code == 0 and len(text.splitlines()) == 1
    for row, record in zip(summary["scenarios"], records, strict=True):
        assert row["trace_id"] == record.trace_id
        assert row["plans"] == [
            p.model_dump(exclude={"attempts"})
            | {"attempts": [a.model_dump(exclude={"cost_usd"}) for a in p.attempts]}
            for p in record.plans
        ]
        assert row["limit_hit"] and row["limit_kinds"] == record.limit_kinds
        assert row["cost_by_provider"] == {"anthropic": 0.01}
        assert row["duration_ms"] == record.duration_ms
        assert row["event_names"] == ["step", "token"]
        assert "message" not in row
    n = len(records)
    structured = summary["structured"]
    assert structured["calls"] == calls
    assert structured["sample_too_small"] is (calls < 20)
    assert structured["failed_after_retry"] == n
    assert structured["first_attempt_failures"] == {
        "PARSE_FAILED": 2 * n,
        "SCHEMA_VIOLATION": n,
    }
    assert structured["by_model"]["gpt-6-luna"]["calls"] == calls
    assert structured["by_model"]["gpt-6-luna"]["failed_after_retry"] == n
    saved = rig.root / f"{summary['run_id']}.json"
    assert json.loads(saved.read_text()) == summary
    assert SECRET not in saved.read_text() + text


def test_makefile_adds_only_separate_target_and_phony():
    text = Path("Makefile").read_text()
    assert "\n.PHONY: live-agents\n" in text
    assert (
        "\nlive-agents:\n\tuv run python -m beautyads.eval.agents_live $(ARGS)\n"
        in text
    )
    verify = text.split("\nverify:\n", 1)[1].split("\n\n", 1)[0]
    assert "live-" not in verify


@pytest.mark.parametrize("calls", [19, 20])
def test_failure_detail_summary_sums_models_and_saved_output(rig, calls):
    key = "evaluation_scores|rationale|string_too_long"
    other = "research_handoff|aggregates.*.name|missing"
    records = []

    def run(**kwargs):
        record = trace(
            rig,
            kwargs["tenant_id"],
            structured={
                "model_a": {
                    "calls": calls if not records else 0,
                    "first_attempt_failure_details": {key: 1},
                },
                "model_b": {"first_attempt_failure_details": {key: 2, other: 1}},
            },
        )
        records.append(record)
        append_trace(rig.settings.ledger_path.with_name("traces.jsonl"), record)
        return outcome()

    rig.behavior = run
    code, summary, text = rig.invoke()
    assert code == 0
    stats = summary["structured"]
    n = len(records)
    assert n > 0
    assert stats["first_attempt_failure_details"] == {key: 3 * n, other: n}
    assert stats["by_model"]["model_a"]["first_attempt_failure_details"] == {key: n}
    assert stats["by_model"]["model_b"]["first_attempt_failure_details"] == {
        key: 2 * n,
        other: n,
    }
    assert stats["sample_too_small"] is (calls < 20)
    saved = rig.root / f"{summary['run_id']}.json"
    assert json.loads(saved.read_text())["structured"] == stats
    assert SECRET not in saved.read_text() + text


@pytest.mark.parametrize("show", [False, True])
def test_show_rationale_is_sanitized_terminal_only_and_summary_keeps_safe_alignment(
    rig, show
):
    from test_domain_supervisor import comparison_rows

    from beautyads.domain.supervisor import pattern_alignment

    tokens = [
        "sk-" + "SYNTHETICKEY123456789",
        "Bearer " + "SYNTHETIC123456789",
        "AIza" + "SYNTHETIC123456789",
    ]
    rationale = "synthetic reason " + " ".join(tokens) + "\x00\n\t" + "가" * 240
    alignment = pattern_alignment(
        {"hook_type": "question"}, [comparison_rows(("question", 2), total=2)]
    )
    versions = {"planning": "2026-11-18-1", "evaluation": "2026-11-18-1"}
    path = rig.settings.ledger_path.with_name("traces.jsonl")

    def run(**kw):
        private_alignment = {**alignment, "diagnostic": SECRET}
        private_alignment["axes"] = {
            **alignment["axes"],
            "angle": {
                "plan": SECRET,
                "dominant": [SECRET],
                "same": None,
                "share": None,
            },
        }
        attempts = [
            {
                "attempt": 1,
                "checks_passed": True,
                "final_passed": False,
                "scores": {"differentiation": 2, "fit": 3, "rationale": rationale},
            }
        ]
        append_trace(
            path,
            trace(
                rig,
                kw["tenant_id"],
                result={
                    "prompt_versions": versions,
                    "plans": [
                        {"pattern_alignment": private_alignment, "attempts": attempts}
                    ],
                },
                failure={"message": SECRET},
            ),
        )
        return AskOutcome(
            events=[("step", {"detail": SECRET})],
            ui_commands=[
                {
                    "kind": "show_plan",
                    "data": {
                        "pattern_alignment": private_alignment,
                        "attempts": attempts,
                    },
                }
            ],
            final_text=SECRET,
            status_code=200,
        )

    rig.behavior = run
    args = ["--config", "image"] + (["--show-rationale"] if show else [])
    code, summary, output = rig.invoke(*args)
    assert code == 3
    lines = output.splitlines()
    rationale_lines = [line for line in lines if line.startswith("RATIONALE ")]
    assert len(rationale_lines) == int(show)
    if show:
        prefix = "RATIONALE serum-plan attempt 1 differentiation=2 fit=3: "
        assert rationale_lines[0].startswith(prefix)
        displayed = rationale_lines[0][len(prefix) :]
        assert len(displayed) == 200 and displayed.count("[redacted]") == 3
        assert not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in displayed)
    else:
        assert len(lines) == 1
    row = summary["scenarios"][0]
    assert row["prompt_versions"] == versions
    metric = row["plans"][0]["pattern_alignment"]
    assert metric["compared"] == alignment["compared"]
    assert metric["axes"]["hook_type"] == alignment["axes"]["hook_type"]
    attempt = row["plans"][0]["attempts"][0]
    assert attempt["checks_passed"] is True and attempt["final_passed"] is False
    assert "passed" not in attempt
    saved = rig.root / f"{summary['run_id']}.json"
    persisted = saved.read_text() + path.read_text() + lines[-1]
    assert "synthetic reason" not in persisted
    assert SECRET not in persisted + output
    assert all(token not in persisted + output for token in tokens)
