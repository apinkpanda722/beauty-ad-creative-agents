"""Acceptance demo tests use only temporary output and injected local services."""

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from beautyads.api.chat_client import AskOutcome, run_ask_once
from beautyads.domain.supervisor import (
    EFFICACY_UNAVAILABLE_TEXT,
    ClarifyOption,
    ClarifyReason,
    clarification_texts,
)
from beautyads.eval import clarify_demo as demo
from beautyads.sources.workspaces import load_workspaces

MESSAGES = {
    "1": "보습을 내세운 세럼 광고 기획안 1안을 만들어 주세요.",
    "2": "피부 장벽 강화를 내세운 세럼 광고 기획안 1안을 만들어 주세요.",
    "3": "자외선 차단을 내세운 선케어 광고 기획안 1안을 만들어 주세요.",
    "4": "진정 효과를 내세운 세럼 광고 기획안 1안을 만들어 주세요.",
    "5": "모공과 피지 관리를 내세운 선케어 광고 기획안 1안을 만들어 주세요.",
    "6": "이 세럼의 광고 기획안 1안을 만들어 주세요.",
    "7": "이 선세럼 제품의 광고 기획안 1안을 만들어 주세요.",
    "8": "보습을 내세운 세럼 광고 기획안 1안을 만들어 주세요.",
    "9a": "이 세럼의 광고 기획안 1안을 만들어 주세요.",
    "9b": "진정 효과를 내세운 세럼 광고 기획안 1안을 만들어 주세요.",
}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "OUTPUT_ROOT", tmp_path)
    return SimpleNamespace(
        root=tmp_path, settings=SimpleNamespace(ledger_path=tmp_path / "costs.jsonl")
    )


def invoke(*args, **kwargs):
    out = StringIO()
    code = demo.main(list(args), out=out, **kwargs)
    return code, out.getvalue()


def summary(rig):
    files = [p for p in rig.root.glob("*.json")]
    assert len(files) == 1
    return json.loads(files[0].read_text())


def forbidden(*args, **kwargs):
    pytest.fail("dry-run must not touch settings, models, or services")


def test_scenarios_are_closed_and_exact():
    assert {s["id"] for s in demo.SCENARIOS} == set(MESSAGES)
    dev = {
        w.tenant_id
        for w in load_workspaces(Path("config/workspaces.yaml"))
        if w.group == "dev"
    }
    checked = 0
    for s in demo.SCENARIOS:
        checked += 1
        assert s["message"] == MESSAGES[s["id"]]
        assert s["tenant_id"] in dev
        assert s["lookup"] in {"real", "fake_failed", "fake_empty"}
        if s["expected"]["kind"] == "needs_clarification":
            assert s["expected"]["reason"] in {v.value for v in ClarifyReason}
        assert set(s["expected"]["options"]) <= {v.value for v in ClarifyOption}
    assert checked == 10


def test_full_dry_run_real_policy_api_view_and_choices(rig, monkeypatch):
    for name in ("assemble_full", "load_settings", "get_setting", "_preflight"):
        monkeypatch.setattr(demo, name, forbidden)
    sent, outcomes = [], []
    original = demo.create_app

    def create(assemble):
        app = original(assemble)

        @app.middleware("http")
        async def capture(request, call_next):
            sent.append((request.headers.get("X-Tenant-Id"), await request.json()))
            return await call_next(request)

        return app

    real_run = demo.run_ask_once

    def run(*a, **kw):
        outcome = real_run(*a, **kw)
        outcomes.append(outcome)
        return outcome

    monkeypatch.setattr(demo, "create_app", create)
    monkeypatch.setattr(demo, "run_ask_once", run)
    code, output = invoke("--dry-run")
    assert code == 0
    assert "불일치" not in output
    assert output.count("요청:") == output.count("기대:") == 10
    for number, s in enumerate(demo.SCENARIOS, 1):
        assert f"[{number}/10]" in output
        assert s["message"] in output
    assert "측정값(2026-11-20), 실제 조회 아님" in output
    assert "가짜 기획(dry-run)" in output
    assert "코드 판정: 일치" in output
    assert "화면에서 취소" in output and "서버 요청 없음" in output
    assert EFFICACY_UNAVAILABLE_TEXT["failed"] in output
    for outcome in outcomes:
        for event, body in outcome.events:
            if event == "needs_clarification":
                clarification = {
                    **body,
                    "available_efficacy": [v["claim"] for v in body["available"]],
                    "options": [v["id"] for v in body["options"]],
                }
                expected = clarification_texts(clarification, demo.CLAIM_DISPLAY_NAMES)
                assert expected["text"] in output
                for index, option in enumerate(expected["options"], 1):
                    assert f"{index}. {option['label']}" in output
    assert len(sent) == 10 + 15  # ②③ branches, including 9a/9b; cancel sends nothing.
    offset = 0
    for s in demo.SCENARIOS:
        tenant, first = sent[offset]
        assert tenant == s["tenant_id"] and "claim_choice" not in first
        for index, choice in enumerate(s["branches"], 1):
            body = sent[offset + index][1]
            assert body == {**first, "claim_choice": choice}
            assert set(body["claim_choice"]) == {"mode", "claims", "requested_claim"}
        offset += 1 + len(s["branches"])
    saved = summary(rig)
    assert not saved["pending"] and len(saved["scenarios"]) == 10
    assert "리서치 0회 · 기획 0회" in output
    assert "trace 확인: 작업 공간·제품·상태 기록, 요청 본문 없음" in output
    for s in demo.SCENARIOS:
        assert s["message"] not in json.dumps(saved, ensure_ascii=False)


def live_options(rig, behavior=None):
    calls, assemblies = [], []

    def assemble(**kwargs):
        assemblies.append(kwargs)
        return demo._fake_assembly(
            demo.SCENARIOS[0], rig.root / "injected-traces.jsonl"
        )

    def run(app, **kwargs):
        calls.append(kwargs)
        return behavior(app, **kwargs) if behavior else run_ask_once(app, **kwargs)

    return (
        {
            "settings": rig.settings,
            "check": list,
            "assemble": assemble,
            "run": run,
            "totals": lambda _: {"openai": 0.0, "anthropic": 0.0},
        },
        calls,
        assemblies,
    )


def test_live_real_scenarios_use_injected_services_only(rig):
    opts, calls, assemblies = live_options(rig)
    code, _ = invoke(**opts)
    assert code == 0
    assert len(calls) == 19 and len(assemblies) == len(calls)
    assert all(
        a["group"] == "dev"
        and a["evaluation_model"] == "claude-haiku-5-5"
        and a["with_image_enabled"] is False
        for a in assemblies
    )
    assert len(summary(rig)["scenarios"]) == 10


def test_preflight_prevents_start(rig):
    code, output = invoke(
        settings=rig.settings,
        check=lambda: ["DOCKER_DOWN"],
        assemble=forbidden,
        run=forbidden,
    )
    assert code == 2 and "PREFLIGHT_FAILED DOCKER_DOWN" in output
    assert not list(rig.root.glob("*.json"))


def test_workspace_group_checked_even_for_dry_run(rig, monkeypatch):
    monkeypatch.setattr(demo, "load_workspaces", lambda _: [])
    code, output = invoke("--dry-run")
    assert code == 2 and "PREFLIGHT_FAILED WORKSPACE_GROUP_INVALID" in output


def test_budget_checked_before_branch_and_marks_current_pending(rig):
    opts, calls, _ = live_options(rig)
    opts["totals"] = lambda _: {"openai": 8.0 + 0.4 * len(calls), "anthropic": 2.0}
    code, output = invoke("--only", "4", "5", **opts)
    assert code == 2 and len(calls) == 1
    assert "STOPPED BUDGET_REACHED" in output
    assert summary(rig)["pending"] == ["4", "5"]
    assert summary(rig)["cost_by_provider"]["openai"] == 0.4


@pytest.mark.parametrize(
    "error", ["DAILY_LIMIT", "RATE_LIMIT", "HTTP_429", "CREDITS_DEPLETED"]
)
def test_stop_codes_do_not_retry(rig, error):
    opts, calls, _ = live_options(
        rig, lambda *a, **k: AskOutcome([("error", {"error_code": error})], [], "", 200)
    )
    code, output = invoke("--only", "1", "2", **opts)
    assert code == 2 and len(calls) == 1
    assert f"STOPPED {error}" in output
    assert summary(rig)["pending"] == ["2"]


def test_one_failure_continues_and_diagnostics_do_not_leak(rig):
    private = "SYNTHETIC-private-title-hook-copy"

    def behavior(app, **kw):
        if len(calls) == 1:
            raise ValueError(private)
        result = run_ask_once(app, **kw)
        for command in result.ui_commands:
            if command.get("kind") == "show_plan":
                command["data"]["plan"].update(
                    title=private, hook_text=private, copy_lines=[private]
                )
                command["data"]["efficacy_status"][private] = private
        return result

    opts, calls, _ = live_options(rig, behavior)
    code, output = invoke("--only", "1", "2", **opts)
    assert code == 3 and len(calls) == 2
    saved = json.dumps(summary(rig), ensure_ascii=False)
    assert private not in saved and all(
        s["message"] not in saved for s in demo.SCENARIOS
    )
    assert private in output  # plan prose is terminal-only


@pytest.mark.parametrize(
    "args",
    [
        ["--unknown", "private-argument"],
        ["--only", "private-argument"],
        ["--config", "private-argument"],
    ],
)
def test_arguments_hide_values(args, rig):
    code, output = invoke(*args)
    assert code == 2 and output.strip() == "ARGUMENT_ERROR"


def test_make_target_leaves_verify_offline():
    text = Path("Makefile").read_text()
    assert (
        ".PHONY: demo-clarify\ndemo-clarify:\n\tuv run python -m beautyads.eval.clarify_demo $(ARGS)"
        in text
    )
    verify = text.split("verify:\n", 1)[1].split("\n\n", 1)[0]
    assert "demo-" not in verify


def test_model_boundary_blocks_inside_multi_call_generator(rig):
    current = {"openai": 3.0, "anthropic": 2.0}
    session = demo._Session(rig.settings, lambda _: current.copy())
    calls = []

    def generator(*, caps):
        # Like the SDK's provider precheck, repeat the cap read for each call.
        for _ in range(2):
            assert caps["openai"] == 10
            calls.append(True)
            current["anthropic"] += 0.4

    with pytest.raises(demo._Stopped):
        session.call(generator, caps={"openai": 10, "anthropic": 8})
    assert len(calls) == 1 and session.stopped == "BUDGET_REACHED"


def test_model_error_survives_supervisor_swallowing(rig, monkeypatch):
    from beautyads.llm.errors import ErrorKind, LlmCallError

    calls = []

    def chat(**kwargs):
        calls.append(True)
        raise LlmCallError(kind=ErrorKind.DAILY_LIMIT, code="DAILY_LIMIT")

    monkeypatch.setattr(demo, "chat_complete", chat)
    session = demo._Session(rig.settings, lambda _: {"openai": 0.0, "anthropic": 0.0})
    with pytest.raises(LlmCallError):
        session.models()["chat"]()
    assert session.stopped == "DAILY_LIMIT" and len(calls) == 1
    with pytest.raises(demo._Stopped):
        session.models()["chat"]()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "case,code",
    [
        ("kind", "KIND_MISMATCH"),
        ("reason", "REASON_MISMATCH"),
        ("options", "OPTIONS_MISMATCH"),
        ("early", "EARLY_WORK"),
        ("subset", "UNCONFIRMED_CLAIM"),
        ("keep", "REQUESTED_CLAIM_ASSERTED"),
        ("missing", "PLAN_MISSING"),
    ],
)
def test_verdict_rejects_structural_policy_regressions(case, code):
    expected = {"kind": "plan", "reason": None, "options": []}
    raw = {"kind": "plan", "available_efficacy": [], "available_efficacy_status": "ok"}
    choice = None
    plans = [{"kind": "show_plan", "data": {"plan": {"claimed_efficacy": []}}}]
    events = []
    if case in {"kind", "missing"}:
        plans = []
        if case == "kind":
            raw["kind"] = "failed"
    if case in {"reason", "options", "early"}:
        expected = {
            "kind": "needs_clarification",
            "reason": "no_claim_requested",
            "options": ["none"],
        }
        plans = []
        body = {"reason": "no_claim_requested", "options": [{"id": "none"}]}
        if case == "reason":
            body["reason"] = "requested_not_confirmed"
        if case == "options":
            body["options"] = []
        events = [("needs_clarification", body)]
        if case == "early":
            events.append(("step", {"agent": "research", "phase": "end"}))
    if case in {"subset", "keep"}:
        plans[0]["data"]["plan"]["claimed_efficacy"] = ["soothing"]
        if case == "keep":
            raw["available_efficacy"] = ["soothing"]
            choice = {
                "mode": "keep_requested",
                "claims": [],
                "requested_claim": "soothing",
            }
    row = demo._inspect(AskOutcome(events, plans, "", 200), raw, expected, choice)[0]
    assert row["code_verdict"] == "mismatch" and code in row["mismatch_codes"]


def test_official_selects_sonnet_and_real_lookup_values(rig):
    opts, calls, assemblies = live_options(rig)
    code, _ = invoke("--config", "official", "--only", "6", **opts)
    assert code == 0 and len(calls) == 4
    assert all(a["evaluation_model"] == "claude-sonnet-5-5" for a in assemblies)
    assert [c.get("claim_choice", {}).get("mode") for c in calls] == [
        None,
        "selected",
        "selected",
        "none",
    ]


def test_fake_only_live_never_uses_paid_injections(rig):
    code, _ = invoke(
        "--only",
        "8",
        "9a",
        "9b",
        settings=rig.settings,
        check=list,
        totals=lambda _: {"openai": 0.0, "anthropic": 0.0},
        run=forbidden,
        assemble=forbidden,
    )
    assert code == 0


def test_summary_excludes_synthetic_key_shapes_and_plan_prose(rig):
    # These are deliberate fake canaries, never credentials.
    canaries = [
        "sk-" + "synthetic_canary_12345",
        "AIza" + "synthetic_canary_98765",
        "Bearer " + "synthetic_canary_55555",
    ]

    def behavior(app, **kw):
        outcome = run_ask_once(app, **kw)
        for command in outcome.ui_commands:
            if command.get("kind") == "show_plan":
                data = command["data"]
                data["plan"].update(
                    title=canaries[0], hook_text=canaries[1], copy_lines=[canaries[2]]
                )
                data["efficacy_status"][canaries[0]] = canaries[1]
        return outcome

    opts, _, _ = live_options(rig, behavior)
    code, _ = invoke("--only", "1", **opts)
    assert code == 0
    saved = json.dumps(summary(rig), ensure_ascii=False)
    assert all(canary not in saved for canary in canaries)


def test_verdict_checks_raw_steps_even_if_callback_event_is_missing():
    expected = {
        "kind": "needs_clarification",
        "reason": "no_claim_requested",
        "options": ["none"],
    }
    outcome = AskOutcome(
        [
            (
                "needs_clarification",
                {"reason": "no_claim_requested", "options": [{"id": "none"}]},
            )
        ],
        [],
        "",
        200,
    )
    row = demo._inspect(
        outcome,
        {
            "kind": "needs_clarification",
            "steps": [{"agent": "research", "phase": "done"}],
        },
        expected,
        None,
    )[0]
    assert row["code_verdict"] == "mismatch" and "EARLY_WORK" in row["mismatch_codes"]


def test_partial_plan_does_not_hide_failed_result_kind():
    row = demo._inspect(
        AskOutcome(
            [],
            [{"kind": "show_plan", "data": {"plan": {"claimed_efficacy": []}}}],
            "",
            200,
        ),
        {"kind": "failed", "available_efficacy_status": "ok"},
        {"kind": "plan", "reason": None, "options": []},
        None,
    )[0]
    assert "KIND_MISMATCH" in row["mismatch_codes"]


def test_preflight_exception_is_an_environment_error(rig):
    def check():
        raise OSError("SYNTHETIC-private-diagnostic")

    code, output = invoke(check=check, run=forbidden, assemble=forbidden)
    assert code == 2 and output.strip() == "PREFLIGHT_FAILED CHECK_FAILED"
