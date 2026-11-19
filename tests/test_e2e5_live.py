"""E2/E5 orchestration is exercised with temporary data and offline boundaries."""

import ast
import asyncio
import csv
import json
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_api_assembly

from beautyads.api import assembly as api_assembly
from beautyads.domain.research import ResearchBrief
from beautyads.domain.supervisor import RequestLimits
from beautyads.domain.tools import ToolContext
from beautyads.eval import e2e5_live as live
from beautyads.eval import single_agent
from beautyads.eval.e2_scoring import ArmRecord, analyze, blind_items, score_plans
from beautyads.eval.evalset import RequestItem, write_jsonl
from beautyads.eval.freeze_guard import FreezeError, RunIdentity
from beautyads.llm.errors import ErrorKind, LlmCallError
from beautyads.llm.structured import StructuredStats
from beautyads.obs.ledger import CostCapExceeded, LedgerEntry, append_entry
from beautyads.settings import Settings

assembly_rig = test_api_assembly.rig


def request(index=0, split="dev"):
    return {
        "id": f"req-{index}",
        "split": split,
        "tenant_id": f"{split}-workspace",
        "source_cq": "synthetic",
        "axes_used": [],
        "needs_human_review": False,
        "reviewed": True,
        "message": "synthetic request",
    }


def result():
    return {
        "kind": "plan",
        "plans": [{"plan": test_api_assembly.synthetic_plan(), "report": {}}],
        "handoff": {
            "evidence_ids": [test_api_assembly.EID],
            "pattern_context": {"distribution": [{"axis": "format"}]},
        },
        "prompt_versions": {"planning": "synthetic-version"},
    }


@pytest.fixture
def rig(tmp_path, monkeypatch):
    root = tmp_path / "results"
    requests = tmp_path / "requests.jsonl"
    write_jsonl(requests, [request(i) for i in range(3)])
    monkeypatch.setattr(live, "RESULT_ROOT", root)
    monkeypatch.setattr(live, "REQUESTS_PATH", requests)
    state = SimpleNamespace(
        root=root,
        requests=requests,
        calls=[],
        assemblies=[],
        single_options=[],
        closed=[],
        guards=[],
        structured_calls=[],
        models=[],
        problems=[],
        settings=Settings(ledger_path=tmp_path / "ledger.jsonl"),
        behavior=lambda *args, **kw: result(),
    )
    tenants = SimpleNamespace(
        register_thread=lambda *args: None,
        list_feedback=lambda *args, **kw: [],
    )

    async def assemble(**kw):
        state.assemblies.append(kw)
        return SimpleNamespace(
            ask=ask,
            tenants=tenants,
            allowed_tenants=frozenset({"dev-workspace", "test-workspace"}),
            workspaces={"dev-workspace": {}, "test-workspace": {}},
            as_of=date(2026, 1, 1),
            last_collected_at=None,
            price_bands={},
            hydrate=lambda ids: [
                {
                    "evidence_id": eid,
                    "title": "synthetic",
                    "brand": "brand",
                    "url": "https://example.invalid/SENTINEL_LINK",
                }
                for eid in ids
            ],
            close=lambda: state.closed.append("assembly"),
        )

    def ask(*args, **kw):
        state.calls.append((args, kw))
        return state.behavior(*args, **kw)

    def single_builder(**kw):
        state.single_options.append(kw)

        def run(**options):
            state.calls.append((options, {"single": True}))
            return {
                "kind": "plan",
                "plan": test_api_assembly.synthetic_plan(),
                "check_report": {},
                "evidence_pool": [test_api_assembly.EID],
                "tool_calls": 0,
                "prompt_version": "synthetic-version",
            }

        return SimpleNamespace(run=run, close=lambda: state.closed.append("single"))

    class Structured:
        def __init__(self, model):
            self.model, self.stats = model, StructuredStats()
            state.models.append(model)

        def generate(self, spec, **kw):
            state.structured_calls.append((self.model, kw))
            return SimpleNamespace(
                ok=True,
                value=spec.validate(
                    {"request_fit": 3, "distinctiveness": 3, "rationale": "synthetic"}
                ),
                cost_usd=0,
            )

    def guard(**kw):
        state.guards.append(kw)
        return RunIdentity("a" * 40, "b" * 40, None, None)

    def invoke(*args, **kwargs):
        out = StringIO()
        code = live.main(
            list(args),
            out=out,
            settings=state.settings,
            assemble=assemble,
            single_builder=single_builder,
            structured_factory=kwargs.pop("structured_override", Structured),
            chat_fn=kwargs.pop(
                "chat_override", lambda **kw: pytest.fail("unexpected chat")
            ),
            guard_fn=kwargs.pop("guard_override", guard),
            check=lambda **kw: state.problems,
            workspace_loader=lambda path: [
                SimpleNamespace(tenant_id=f"{s}-workspace", group=s)
                for s in ("dev", "test")
            ],
            environ={},
            env_file=None,
            **kwargs,
        )
        return code, out.getvalue()

    state.invoke, state.guard = invoke, guard
    return state


@pytest.mark.parametrize("command", ["run", "score", "sheet", "report"])
@pytest.mark.parametrize(
    "code", ["PREREG_NOT_COMMITTED", "EVALSET_HASH_MISMATCH", "FROZEN_VALUE_MISMATCH"]
)
def test_final_guards_precede_all_reads_and_calls(rig, monkeypatch, command, code):
    def reject(**kw):
        assert kw["mode"] == "final" and kw["groups"] == {"test"}
        assert len(kw["extra"]) >= 2
        raise FreezeError(code)

    monkeypatch.setattr(
        live, "read_jsonl", lambda path: pytest.fail("read before guard")
    )
    status, output = rig.invoke(
        command, "--mode", "final", "--run-id", "trial", guard_override=reject
    )
    assert status != 0 and code in output
    assert (
        not rig.calls
        and not rig.assemblies
        and not rig.structured_calls
        and not rig.models
    )


def test_final_rejects_candidate_option_before_guard(rig):
    code, output = rig.invoke("run", "--mode", "final", "--requests", str(rig.requests))
    assert code != 0 and "ARGUMENT_ERROR" in output
    assert not rig.guards and not rig.calls


@pytest.mark.parametrize("change", ["split", "workspace"])
def test_dev_rejects_test_inputs(rig, change):
    row = (
        request(split="test")
        if change == "split"
        else {**request(), "tenant_id": "test-workspace"}
    )
    write_jsonl(rig.requests, [row])
    code, output = rig.invoke(
        "run", "--requests", str(rig.requests), "--run-id", "trial"
    )
    assert code != 0 and "WORKSPACE_GROUP_INVALID" in output
    assert not rig.calls and not rig.assemblies


def test_context_matches_http_construction(rig):
    service = SimpleNamespace(
        as_of=date(2026, 1, 1),
        last_collected_at=None,
        price_bands={"dev-workspace": {"price_min": 10, "price_max": 20}},
    )
    expected = ToolContext(
        tenant_id="dev-workspace",
        as_of=service.as_of,
        last_collected_at=service.last_collected_at,
        price_band=service.price_bands.get("dev-workspace"),
    )
    assert live.tool_context(service, "dev-workspace") == expected


def test_arm_order_keyword_image_identity_and_resume(rig):
    code, _ = rig.invoke(
        "run", "--run-id", "trial", "--arms", "off,single,supervisor", "--limit", "2"
    )
    assert code == 0
    assert len(rig.calls) == 6
    for start in (0, 3):
        assert rig.calls[start][1] == {}
        assert rig.calls[start][0][4] is False
        assert rig.calls[start + 1][1] == {"single": True}
        assert rig.calls[start + 2][1] == {"context_mode": "off"}
        assert rig.calls[start + 2][0][4] is False
    rows = [
        json.loads(s)
        for s in (rig.root / "trial" / "records.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 6
    for row in rows:
        assert row["code_commit"] and row["evalset_hash"] and row["prereg_commit"]
        assert row["prompt_versions"]
        ArmRecord.model_validate({k: row[k] for k in ArmRecord.model_fields})
    assert rig.invoke("run", "--run-id", "trial", "--limit", "2")[0] == 0
    assert len(rig.calls) == 6
    assert all(x["limits"] == RequestLimits() for x in rig.assemblies)
    assert rig.single_options[0]["limits"] == rig.assemblies[0]["limits"]


def test_one_failure_continues_and_never_leaks_exception(rig):
    def behavior(*args, **kwargs):
        if len(rig.calls) == 1:
            raise ValueError("SENTINEL_KEY_SENTINEL_BODY")
        return result()

    rig.behavior = behavior
    code, output = rig.invoke("run", "--run-id", "trial", "--arms", "supervisor")
    text = (rig.root / "trial" / "records.jsonl").read_text()
    assert len(rig.calls) == 3
    assert json.loads(text.splitlines()[0])["status"] == "failed"
    assert code != 0 and "SENTINEL_" not in output + text


@pytest.mark.parametrize(
    "error",
    [
        CostCapExceeded("openai", 1, 1),
        LlmCallError(kind=ErrorKind.DAILY_LIMIT, code="daily"),
    ],
)
def test_batch_stops_on_provider_limits(rig, error):
    def behavior(*args, **kw):
        raise error

    rig.behavior = behavior
    code, output = rig.invoke("run", "--run-id", "trial")
    assert code != 0 and len(rig.calls) == 1 and "STOPPED" in output
    assert len((rig.root / "trial" / "records.jsonl").read_text().splitlines()) == 1


def test_budget_stops_before_next_arm_and_resume_counts_previous_spend(rig):
    def behavior(*args, **kw):
        append_entry(
            rig.settings.ledger_path, entry(cost=live.DEFAULT_BUDGET_USD["dev"])
        )
        return result()

    rig.behavior = behavior
    assert rig.invoke("run", "--run-id", "trial")[0] != 0
    assert len(rig.calls) == 1
    assert rig.invoke("run", "--run-id", "trial")[0] != 0
    assert len(rig.calls) == 1


def entry(*, cost=0.01, purpose="single-agent", tokens=11):
    return LedgerEntry(
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        provider="openai",
        model="synthetic",
        purpose=purpose,
        cost_usd=cost,
        cost_source="computed",
        input_tokens=tokens,
    )


def test_ledger_delta_and_axes_are_code_derived(tmp_path):
    path = tmp_path / "ledger"
    for row in [
        entry(cost=1),
        entry(cost=2),
        entry(cost=3, purpose="image-plan"),
        entry(cost=4, purpose="imagery"),
    ]:
        append_entry(path, row)
    assert live.ledger_delta(path, 1) == {
        "input_tokens": 33,
        "model_calls": 3,
        "spent_usd": 6,
    }
    assert set(
        live.observed_axes(
            result(), [{"arguments": {"axis": "angle"}}, {"axis": "SENTINEL_BODY"}]
        )
    ) == {"format", "angle"}


@pytest.mark.parametrize("command", ["run", "score", "sheet", "report"])
def test_dry_run_does_not_assemble_or_check_network(rig, command):
    rig.problems = ["DOCKER_DOWN"]
    code, output = rig.invoke(command, "--dry-run", "--run-id", "trial")
    assert code == 0 and "scoring_calls" in output and "미실측" in output
    assert not rig.calls and not rig.assemblies and not rig.models
    assert not rig.root.exists()


def test_preflight_failure_and_dev_budget_rejection_are_call_free(rig):
    rig.problems = ["DOCKER_DOWN"]
    assert "DOCKER_DOWN" in rig.invoke("run", "--run-id", "trial")[1]
    rig.problems = []
    code, output = rig.invoke(
        "score", "--budget-usd", str(live.DEFAULT_BUDGET_USD["dev"] + 0.01)
    )
    assert code != 0 and "DEV_BUDGET_INVALID" in output
    assert not rig.calls and not rig.models and not rig.assemblies


@pytest.mark.parametrize("budget,accepted", [("0.40", True), ("0.41", False)])
def test_dev_budget_boundary_is_call_free(rig, budget, accepted):
    rig.problems = ["DOCKER_DOWN"]
    code, output = rig.invoke(
        "run", "--mode", "dev", "--run-id", "trial", "--budget-usd", budget
    )
    assert code != 0
    if accepted:
        assert "PREFLIGHT_FAILED DOCKER_DOWN" in output
        assert "DEV_BUDGET_INVALID" not in output
    else:
        assert "DEV_BUDGET_INVALID" in output
        assert "PREFLIGHT_FAILED" not in output
        assert not rig.guards
    assert not rig.calls and not rig.models and not rig.assemblies
    assert not rig.structured_calls and not rig.root.exists()


@pytest.mark.parametrize("mode", ["dev", "final"])
def test_default_budget_is_passed_to_batch_without_calls(rig, monkeypatch, mode):
    write_jsonl(rig.requests, [request(split="test" if mode == "final" else "dev")])
    budgets = []

    async def batch(args, *positional, **kwargs):
        budgets.append(args.budget_usd)
        return 0

    monkeypatch.setattr(live, "_run_batch", batch)
    code, _ = rig.invoke("run", "--mode", mode, "--run-id", "trial")
    assert code == 0
    assert budgets == [live.DEFAULT_BUDGET_USD[mode]]
    assert not rig.calls and not rig.models and not rig.assemblies
    assert not rig.structured_calls


@pytest.mark.parametrize("budget", ["3.0", "3.01"])
def test_final_budget_reaches_preflight_above_dev_cap_without_calls(rig, budget):
    assert live.DEFAULT_BUDGET_USD["final"] == 3.0
    write_jsonl(rig.requests, [request(split="test")])
    rig.problems = ["DOCKER_DOWN"]
    code, output = rig.invoke(
        "run", "--mode", "final", "--run-id", "trial", "--budget-usd", budget
    )
    assert code != 0 and "PREFLIGHT_FAILED DOCKER_DOWN" in output
    assert "DEV_BUDGET_INVALID" not in output
    assert len(rig.guards) == 1 and rig.guards[0]["mode"] == "final"
    assert not rig.calls and not rig.models and not rig.assemblies
    assert not rig.structured_calls and not rig.root.exists()


@pytest.mark.parametrize("mode", ["dev", "final"])
def test_scoring_all_arms_share_sonnet_scoring_run(rig, mode):
    write_jsonl(
        rig.requests,
        [request(i, "test" if mode == "final" else "dev") for i in range(2)],
    )
    assert rig.invoke("run", "--mode", mode, "--run-id", "trial")[0] == 0
    code, _ = rig.invoke("score", "--mode", mode, "--run-id", "trial")
    assert code == 0
    assert len(rig.structured_calls) == 6
    assert {model for model, _ in rig.structured_calls} == {"claude-sonnet-5-5"}
    scores = json.loads((rig.root / "trial" / "scores.json").read_text())
    assert (
        len({s["scoring_run_id"] for arms in scores.values() for s in arms.values()})
        == 1
    )
    with pytest.raises(ValueError, match="SCORING_MODEL_INVALID"):
        score_plans(
            [],
            structured=SimpleNamespace(model="claude-haiku-5-5"),
            ledger_path=rig.settings.ledger_path,
        )


def test_dev_score_refuses_seven_or_more_items_without_model_creation(rig):
    assert live.DEV_SCORE_MAX_ITEMS == 6
    assert rig.invoke("run", "--run-id", "trial")[0] == 0
    code, output = rig.invoke("score", "--run-id", "trial")
    assert code != 0 and "DEV_SCORE_MAX_ITEMS" in output
    assert not rig.models and not rig.structured_calls


def test_sheet_hydrates_title_brand_only_and_report_has_conditions(rig):
    assert rig.invoke("run", "--run-id", "trial", "--limit", "1")[0] == 0
    assert rig.invoke("sheet", "--run-id", "trial")[0] == 0
    text = (rig.root / "trial" / "claim_sheet.csv").read_text()
    assert "SENTINEL_LINK" not in text and "https://" not in text
    sheet = rig.root / "trial" / "claim_sheet.csv"
    with sheet.open(newline="") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    assert rows
    with sheet.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({**row, "claim_match": "partial"} for row in rows)
    assert rig.invoke("score", "--run-id", "trial")[0] == 0
    code, output = rig.invoke("report", "--run-id", "trial")
    assert code == 0
    for marker in (
        "1인 라벨링",
        "한 에이전트 대 한 시스템",
        "verdict_e2",
        "verdict_e5",
        "a" * 40,
        "b" * 40,
    ):
        assert marker in output


def test_single_and_supervisor_read_same_tool_and_cost_limits(
    assembly_rig, monkeypatch
):
    limits = RequestLimits()
    briefs, loop_limits, singles = [], [], []
    original_research = api_assembly.run_research
    original_loop = single_agent.run_tool_loop

    def research(brief, *args, **kw):
        briefs.append(ResearchBrief.model_validate(brief).max_tool_calls)
        return original_research(brief, *args, **kw)

    def loop(**kw):
        loop_limits.append(kw["max_tool_calls"])
        return original_loop(**kw)

    monkeypatch.setattr(api_assembly, "run_research", research)
    monkeypatch.setattr(single_agent, "run_tool_loop", loop)
    monkeypatch.setattr(
        live,
        "run_single_agent",
        lambda **kw: (singles.append(kw), single_agent.run_single_agent(**kw))[1],
    )
    options = []

    class Structured:
        model = "gpt-6.1-terra"

        def generate(self, *args, **kw):
            options.append(kw)
            return SimpleNamespace(ok=False)

    def chat(**kw):
        options.append(kw)
        return SimpleNamespace(tool_calls=[])

    async def run():
        service = await assembly_rig.start(limits=limits)
        try:
            test_api_assembly.invoke(service)
            arm = live.build_single_arm(
                settings=assembly_rig.settings,
                limits=limits,
                graph_fn=lambda **kw: assembly_rig.graph,
                chat_fn=chat,
                structured_factory=lambda model: Structured(),
                environ={},
                env_file=None,
            )
            try:
                tenant = next(iter(service.allowed_tenants))
                arm.run(
                    message="synthetic",
                    ctx=live.tool_context(service, tenant),
                    profile={},
                    feedback={},
                )
            finally:
                arm.close()
        finally:
            await service.close()

    asyncio.run(run())
    assert briefs and loop_limits and singles and options
    assert (
        loop_limits[0]
        == ResearchBrief.model_fields["max_tool_calls"].default
        == briefs[0]
    )
    assert singles[0]["limits"].max_text_cost_usd == limits.max_text_cost_usd
    assert options[0]["caps"] == assembly_rig.settings.provider_caps_usd
    assert options[0]["ledger_path"] == assembly_rig.settings.ledger_path
    tree = ast.parse(Path(live.__file__).read_text())
    assert not any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "min"
        for n in ast.walk(tree)
    )


def test_record_uses_nested_code_checks_and_preserves_limits(rig):
    payload = result()
    checks = {
        "passed": False,
        "issues": [{"code": "EVIDENCE_NOT_FOUND", "field": "evidence_ids[0]"}],
    }
    payload["plans"][0]["report"] = {"check_report": checks, "scores": {}}
    payload["limit_hit"] = True
    payload["handoff"]["result_counts"] = [{"tool": "synthetic"}, {"tool": "synthetic"}]
    rig.behavior = lambda *args, **kw: payload
    assert (
        rig.invoke("run", "--run-id", "trial", "--arms", "supervisor", "--limit", "1")[
            0
        ]
        == 0
    )
    row = json.loads((rig.root / "trial" / "records.jsonl").read_text())
    assert row["check_report"] == checks
    assert row["limit_hit"] is True
    assert row["tool_calls"] == len(payload["handoff"]["result_counts"])


@pytest.mark.parametrize("which", ["chat", "structured"])
def test_watch_remembers_swallowed_daily_limit_and_never_retries(which):
    watch, calls = live._Watch(), []

    def fail(*args, **kwargs):
        calls.append(True)
        raise LlmCallError(
            kind=ErrorKind.DAILY_LIMIT, code="synthetic", message="SENTINEL_BODY"
        )

    if which == "structured":
        fn = watch.structured(
            lambda model: SimpleNamespace(model=model, generate=fail), "gpt-6-luna"
        ).generate
    else:
        fn = lambda: watch.call(fail)
    for _ in range(2):
        with pytest.raises((LlmCallError, live._Stopped)):
            fn()
    assert len(calls) == 1 and watch.stopped == "DAILY_LIMIT"


def test_watch_extracts_tool_axes_without_retaining_tool_arguments():
    watch = live._Watch()
    from beautyads.llm.chat import ToolCall

    response = SimpleNamespace(
        tool_calls=[
            ToolCall(
                "call",
                "compare_axis_by_category",
                {"axis": "angle", "other": "SENTINEL_BODY"},
                None,
            )
        ]
    )
    assert watch.call(lambda: response) is response
    assert live.observed_axes({}, watch.tool_logs) == ["angle"]
    assert "SENTINEL" not in json.dumps(watch.tool_logs)


@pytest.mark.parametrize("factor", [0.5, 2])
def test_single_configured_wrappers_follow_changed_settings(
    tmp_path, monkeypatch, factor
):
    settings = Settings(
        ledger_path=tmp_path / "ledger",
        provider_caps_usd={
            k: v * factor for k, v in Settings().provider_caps_usd.items()
        },
    )
    seen = []
    monkeypatch.setattr(
        live,
        "run_single_agent",
        lambda **kw: (
            kw["chat"](model="gpt-6.1-terra"),
            kw["structured"].generate(None),
        ),
    )
    arm = live.build_single_arm(
        settings=settings,
        limits=RequestLimits(),
        graph_fn=lambda **kw: SimpleNamespace(close=lambda: None),
        chat_fn=lambda **kw: seen.append(kw),
        structured_factory=lambda model: SimpleNamespace(
            model=model, generate=lambda *args, **kw: seen.append(kw)
        ),
        environ={},
        env_file=None,
    )
    try:
        arm.run()
    finally:
        arm.close()
    assert len(seen) == 2
    for kw in seen:
        assert kw["caps"] == settings.provider_caps_usd
        assert kw["caps"] is not settings.provider_caps_usd
        assert kw["ledger_path"] == settings.ledger_path


def test_preflight_checks_keys_ledger_services_with_only_fakes(tmp_path, monkeypatch):
    settings = Settings(ledger_path=tmp_path / "ledger")
    config = {"settings": settings, "command": "run", "environ": {}, "env_file": None}
    assert live._preflight(**config) == ["ENV_MISSING:OPENAI_API_KEY"]
    environ = {
        key: "SENTINEL_PRIVATE_VALUE"
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "POSTGRES_PASSWORD")
    }
    config["environ"] = environ
    monkeypatch.setattr(live, "cq_preflight", lambda **kw: "DOCKER_DOWN")
    assert live._preflight(**config) == ["DOCKER_DOWN"]
    monkeypatch.setattr(live, "cq_preflight", lambda **kw: None)
    monkeypatch.setattr(live, "tcp_reachable", lambda *args: False)
    assert live._preflight(**config) == ["POSTGRES_UNREACHABLE"]
    monkeypatch.setattr(live, "tcp_reachable", lambda *args: True)
    assert live._preflight(**config) == []
    settings.ledger_path.write_text("SENTINEL_MALFORMED\n")
    assert live._preflight(**config) == ["LEDGER_INVALID"]


def test_model_limit_swallowed_by_supervisor_still_stops_batch(rig):
    def behavior(*args, **kw):
        try:
            rig.assemblies[0]["models"]["chat"]()
        except LlmCallError:
            return {"kind": "failed"}
        pytest.fail("model should fail")

    def chat():
        raise LlmCallError(
            kind=ErrorKind.DAILY_LIMIT, code="synthetic", message="SENTINEL_BODY"
        )

    rig.behavior = behavior
    code, output = rig.invoke("run", "--run-id", "trial", chat_override=chat)
    assert code != 0 and "DAILY_LIMIT" in output
    assert len(rig.calls) == 1
    assert "SENTINEL" not in output


def test_score_budget_includes_generation_spend(rig):
    def behavior(*args, **kw):
        append_entry(
            rig.settings.ledger_path, entry(cost=live.DEFAULT_BUDGET_USD["dev"])
        )
        return result()

    rig.behavior = behavior
    rig.invoke("run", "--run-id", "trial", "--arms", "supervisor", "--limit", "1")
    code, output = rig.invoke("score", "--run-id", "trial")
    assert code != 0 and "BUDGET_REACHED" in output
    assert not rig.models and not rig.structured_calls


def test_score_dry_run_counts_actual_records(rig):
    assert (
        rig.invoke("run", "--run-id", "trial", "--arms", "supervisor", "--limit", "1")[
            0
        ]
        == 0
    )
    code, output = rig.invoke("score", "--run-id", "trial", "--dry-run")
    assert code == 0 and json.loads(output)["scoring_calls"] == 1
    assert not rig.structured_calls


def test_request_failure_prints_code_and_class_without_prose(rig):
    def behavior(*args, **kw):
        raise ValueError("SENTINEL_BODY")

    rig.behavior = behavior
    code, output = rig.invoke(
        "run", "--run-id", "trial", "--arms", "supervisor", "--limit", "1"
    )
    assert code != 0 and "REQUEST_FAILED" in output and "ValueError" in output
    assert "SENTINEL" not in output


@pytest.mark.parametrize("mode", ["dev", "final"])
def test_cli_rejects_wrong_scoring_model_with_fixed_code(rig, mode):
    write_jsonl(rig.requests, [request(0, "test" if mode == "final" else "dev")])
    assert rig.invoke("run", "--mode", mode, "--run-id", "trial")[0] == 0
    code, output = rig.invoke(
        "score",
        "--mode",
        mode,
        "--run-id",
        "trial",
        structured_override=lambda model: SimpleNamespace(
            model="claude-haiku-5-5",
            generate=lambda *args, **kw: pytest.fail("wrong model called"),
        ),
    )
    assert code != 0 and "SCORING_MODEL_INVALID" in output
    assert not rig.structured_calls


@pytest.mark.parametrize(
    "provider,scope",
    [
        ("openai", "provider:openai"),
        ("purpose:image", "purpose:image"),
        ("SENTINEL_BODY", "provider:unknown"),
    ],
)
def test_cap_stop_prints_only_safe_scope_and_class(rig, provider, scope):
    def behavior(*args, **kwargs):
        raise CostCapExceeded(provider, 1, 1)

    rig.behavior = behavior
    code, output = rig.invoke("run", "--run-id", "trial", "--arms", "supervisor")
    assert code != 0 and scope in output and "CostCapExceeded" in output
    assert "SENTINEL" not in output


def test_ledger_purpose_totals_counts_only_increment_including_images(tmp_path):
    path = tmp_path / "ledger"
    for purpose, tokens in (
        ("plan", 999),
        ("research", 20),
        ("plan", 7),
        ("research", 30),
        ("image", 3),
        ("image-plan", 4),
        ("plan", 0),
    ):
        append_entry(path, entry(purpose=purpose, tokens=tokens))
    assert live.ledger_purpose_totals(path, 1) == {
        "input_tokens_by_purpose": {
            "research": 50,
            "plan": 7,
            "image": 3,
            "image-plan": 4,
        },
        "model_calls_by_purpose": {
            "research": 2,
            "plan": 2,
            "image": 1,
            "image-plan": 1,
        },
    }
    assert live.ledger_purpose_totals(path, 7) == {
        "input_tokens_by_purpose": {},
        "model_calls_by_purpose": {},
    }


def axis_payload():
    payload = result()
    plan = payload["plans"][0]["plan"]
    payload["brief"] = {
        "goal": "SENTINEL_GOAL",
        "category": "mask_pack",
        "claim": None,
        "skin_concern": None,
        "output": "both",
        "max_tool_calls": 6,
        **{axis: plan[axis] for axis in ("format", "hook_type", "angle")},
    }
    payload["handoff"]["pattern_context"]["dominant_axes"] = [
        {"axis": axis, "values": [plan[axis]], "share": 0.75, "body": "SENTINEL_BODY"}
        for axis in ("format", "hook_type", "angle")
    ]
    return payload


def test_runner_records_only_closed_axes_and_purpose_increment(rig):
    payload = axis_payload()
    append_entry(rig.settings.ledger_path, entry(tokens=999))

    def ask(*args, **kwargs):
        for purpose, tokens in (("research", 10), ("plan", 20), ("research", 30)):
            append_entry(
                rig.settings.ledger_path, entry(purpose=purpose, tokens=tokens)
            )
        return payload

    rig.behavior = ask
    assert rig.invoke("run", "--run-id", "trial", "--limit", "1")[0] == 0
    rows = live._load_records(rig.root / "trial")
    for row in rows:
        if row.arm == "single":
            assert row.brief_axes is row.dominant_axes is None
            assert row.input_tokens_by_purpose == row.model_calls_by_purpose == {}
            continue
        assert row.input_tokens_by_purpose == {"research": 40, "plan": 20}
        assert row.model_calls_by_purpose == {"research": 2, "plan": 1}
        assert row.brief_axes == {
            axis: payload["brief"][axis]
            for axis in (
                "category",
                "claim",
                "hook_type",
                "angle",
                "format",
                "skin_concern",
            )
        }
        assert row.dominant_axes == [
            {key: value[key] for key in ("axis", "values", "share")}
            for value in payload["handoff"]["pattern_context"]["dominant_axes"]
        ]
    text = (rig.root / "trial" / "records.jsonl").read_text()
    assert "SENTINEL" not in text and "synthetic request" not in text


def synthetic_record(index, arm, *, payload=None, tokens=None, calls=None):
    return live._record(
        RequestItem.model_validate(request(index)),
        arm,
        result() if payload is None else payload,
        run_id="synthetic",
        identity=RunIdentity("a" * 40, "b" * 40, None, None),
        set_hash="synthetic-hash",
        latency=0,
        delta={"input_tokens": 1000, "model_calls": 4, "spent_usd": 0},
        by_purpose={
            "input_tokens_by_purpose": tokens or {},
            "model_calls_by_purpose": calls or {},
        },
    )


def supplemental_report(tmp_path, rows, items):
    (tmp_path / "scores.json").write_text("{}")
    out = StringIO()
    live._report(
        rows,
        [RequestItem.model_validate(item) for item in items],
        tmp_path,
        {
            "mode": "dev",
            "evalset_hash": "synthetic-hash",
            "identity": {},
        },
        out,
    )
    return (
        json.loads((tmp_path / "e5_supplement.json").read_text()),
        json.loads((tmp_path / "axis_adherence.json").read_text()),
        out.getvalue(),
    )


def test_legacy_records_load_and_report_unavailable(tmp_path):
    row = synthetic_record(0, "supervisor").model_dump()
    for key in (
        "input_tokens_by_purpose",
        "model_calls_by_purpose",
        "brief_axes",
        "dominant_axes",
    ):
        row.pop(key)
    write_jsonl(tmp_path / "records.jsonl", [row])
    rows = live._load_records(tmp_path)
    assert rows[0].brief_axes is None and rows[0].dominant_axes is None
    assert rows[0].input_tokens_by_purpose == rows[0].model_calls_by_purpose == {}
    _, axes, output = supplemental_report(tmp_path, rows, [request()])
    assert axes["supervisor"]["unavailable"] == 1
    assert "unavailable" in output


def test_plain_strips_all_runner_fields_and_supplements_cannot_change_verdicts():
    items = [request(i) for i in range(10)]
    rows = [synthetic_record(i, arm) for i in range(10) for arm in live.ARMS_DEFAULT]
    original = live._plain(rows)
    expected = analyze(original, scores={}, requests=items)
    blinded = blind_items(original, requests=items)
    for row in rows:
        row.input_tokens_by_purpose = {"plan": 1 if row.arm == "supervisor" else 9000}
        row.model_calls_by_purpose = {"research": 5}
        row.brief_axes = axis_payload()["brief"]
        row.dominant_axes = []
    plain = live._plain(rows)
    assert all(set(row) == set(ArmRecord.model_fields) for row in plain)
    assert plain == original
    assert blind_items(plain, requests=items) == blinded
    actual = analyze(plain, scores={}, requests=items)
    assert actual["verdict_e2"] == expected["verdict_e2"]
    assert actual["verdict_e5"] == expected["verdict_e5"]
    assert actual["e5"]["token_reduction"] == expected["e5"]["token_reduction"]


def test_e5_supplement_calculates_paired_metrics_without_prose(tmp_path):
    rows = []
    for i, on, off, on_calls, off_calls in (
        (
            0,
            {"plan": 20, "research": 60, "image": 10},
            {"plan": 40, "research": 30, "image": 0},
            3,
            1,
        ),
        (1, {"plan": 40, "research": 20}, {"plan": 80, "research": 50}, 1, 3),
    ):
        for arm, tokens, count in (
            ("supervisor", on, on_calls),
            ("off", off, off_calls),
        ):
            rows.append(
                synthetic_record(
                    i,
                    arm,
                    payload=axis_payload(),
                    tokens=tokens,
                    calls={"research": count},
                )
            )
    rows += [
        synthetic_record(2, "supervisor", tokens={"plan": 99}),
        synthetic_record(2, "off"),
    ]
    # An unpaired request must not enter either the used or missing-value pairs.
    rows.append(synthetic_record(3, "supervisor", tokens={"plan": 999}))
    data, _, output = supplemental_report(
        tmp_path, rows, [request(i) for i in range(4)]
    )
    assert data["pairs_used"] == 2 and data["pairs_unavailable"] == 1
    assert data["purposes"]["plan"] == {
        "supervisor": {"total": 60, "mean_per_request": 30},
        "off": {"total": 120, "mean_per_request": 60},
        "reduction": 0.5,
    }
    assert data["purposes"]["research"]["reduction"] == 0
    assert data["purposes"]["image"]["reduction"] == "해당 없음"
    assert data["plan_per_request"] == [
        {"supervisor": 20, "off": 40, "reduction": 0.5},
        {"supervisor": 40, "off": 80, "reduction": 0.5},
    ]
    for arm in ("supervisor", "off"):
        assert data["research"][arm] == {
            "mean_calls_per_request": 2,
            "input_tokens_per_call": 20,
        }
        assert data["non_research"][arm] == {"total": 1920, "mean_per_request": 960}
    assert "E5 보조 지표(참고용, 판정에 쓰지 않음)" in output
    assert (
        "리서치 호출 수 변동이 합계를 수천 토큰 흔들 수 있다. 판정은 요청당 입력 토큰 합계 기준 그대로다."
        in output
    )
    saved = (tmp_path / "e5_supplement.json").read_text()
    assert (
        "SENTINEL" not in saved
        and "synthetic request" not in saved
        and "goal" not in saved
    )


def test_axis_adherence_counts_specified_matches_conflicts_and_omissions(tmp_path):
    rows = []
    for arm in ("supervisor", "off"):
        for i in range(3):
            payload = axis_payload()
            if i == 1:
                # Choose a different closed value without asserting any model choice.
                from beautyads.domain.labels import Format

                payload["brief"]["format"] = next(
                    v.value for v in Format if v != payload["brief"]["format"]
                )
            if i == 2:
                payload["brief"]["format"] = None
            rows.append(synthetic_record(i, arm, payload=payload))
        rows.append(synthetic_record(3, arm))
        no_plan = synthetic_record(4, arm, payload=axis_payload())
        rows.append(no_plan.model_copy(update={"plan": None, "status": "failed"}))
    rows.append(synthetic_record(0, "single"))
    items = [
        {**request(i), "axes_used": ["format", "hook_type", "angle"]} for i in range(5)
    ]
    _, data, output = supplemental_report(tmp_path, rows, items)
    for arm in ("supervisor", "off"):
        assert data[arm]["unavailable"] == 1
        assert data[arm]["with_plan"] == 3
        assert data[arm]["axes"]["format"] == {
            "specified": 2,
            "adherent": 1,
            "dominant_conflict": 1,
            "interpretation_missing": 1,
        }
        for axis in ("hook_type", "angle"):
            assert data[arm]["axes"][axis] == {
                "specified": 3,
                "adherent": 3,
                "dominant_conflict": 3,
                "interpretation_missing": 0,
            }
    assert "single" not in data
    assert "지정 축 준수(코드 판정, 참고용)" in output
    saved = (tmp_path / "axis_adherence.json").read_text()
    assert "SENTINEL" not in saved and "synthetic request" not in saved


@pytest.mark.parametrize("payload", [result(), {"kind": "failed"}])
def test_missing_brief_and_pattern_context_record_as_unavailable(payload):
    row = synthetic_record(0, "supervisor", payload=payload)
    assert row.brief_axes is None and row.dominant_axes is None


@pytest.mark.parametrize("arm", ["supervisor", "off", "single"])
def test_axis_record_rejects_prose_and_non_numeric_pattern_values(arm):
    payload = axis_payload()
    payload["brief"]["format"] = "SENTINEL_BODY"
    dominant = payload["handoff"]["pattern_context"]["dominant_axes"]
    retained = len(dominant)
    dominant.extend(
        [
            "SENTINEL_BODY",
            {"axis": "SENTINEL_BODY", "values": [], "share": 0.5},
            {"axis": "format", "values": ["SENTINEL_BODY"], "share": 0.5},
            {"axis": "format", "values": [], "share": "SENTINEL_BODY"},
            {"axis": "format", "values": [], "share": float("nan")},
        ]
    )
    row = synthetic_record(0, arm, payload=payload)
    if arm == "single":
        assert row.brief_axes is row.dominant_axes is None
    else:
        assert row.brief_axes["format"] is None
        assert len(row.dominant_axes) == retained
    assert "SENTINEL" not in row.model_dump_json()


@pytest.mark.parametrize("missing_arm", ["supervisor", "off"])
def test_supplement_excludes_missing_values_on_either_side(tmp_path, missing_arm):
    rows = [
        synthetic_record(0, arm, tokens={} if arm == missing_arm else {"plan": 0})
        for arm in ("supervisor", "off")
    ]
    data, _, _ = supplemental_report(tmp_path, rows, [request()])
    assert data["pairs_used"] == 0 and data["pairs_unavailable"] == 1
    assert data["purposes"] == {} and data["plan_per_request"] == []
    for arm in ("supervisor", "off"):
        assert data["non_research"][arm]["mean_per_request"] is None
        assert data["research"][arm] == {
            "mean_calls_per_request": None,
            "input_tokens_per_call": "해당 없음",
        }


def test_supplement_preserves_negative_changes_and_zero_denominators(tmp_path):
    rows = [
        synthetic_record(0, "supervisor", tokens={"plan": 0, "research": 30}),
        synthetic_record(0, "off", tokens={"plan": 0, "research": 10}),
    ]
    data, _, output = supplemental_report(tmp_path, rows, [request()])
    assert data["pairs_used"] == 1 and data["pairs_unavailable"] == 0
    assert data["purposes"]["research"]["reduction"] == -2
    assert data["plan_per_request"] == [
        {"supervisor": 0, "off": 0, "reduction": "해당 없음"}
    ]
    assert "해당 없음" in output
    for arm in ("supervisor", "off"):
        assert data["research"][arm] == {
            "mean_calls_per_request": 0,
            "input_tokens_per_call": "해당 없음",
        }
