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
from beautyads.eval.e2_scoring import ArmRecord, score_plans
from beautyads.eval.evalset import write_jsonl
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
