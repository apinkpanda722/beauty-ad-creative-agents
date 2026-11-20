"""한국어 효능 되묻기 인수 점검. 실제 호출은 사용자가 실행한다."""

import inspect
import math
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from beautyads.agents.supervisor import run_request
from beautyads.analysis.prompts import CLAIM_DISPLAY_NAMES
from beautyads.api.app import Assembly, create_app
from beautyads.api.assembly import assemble_full
from beautyads.api.chat_client import run_ask_once
from beautyads.domain.labels import Claim
from beautyads.domain.supervisor import RequestLimits
from beautyads.domain.tenant import TenantMismatch, make_thread_id
from beautyads.eval.agents_live import _STOP_CODES, _ArgumentError, _Parser, _write_json
from beautyads.eval.live_agent import preflight
from beautyads.llm.chat import chat_complete
from beautyads.llm.structured import make_structured
from beautyads.obs.ledger import provider_total
from beautyads.obs.trace import append_trace, build_trace, read_traces
from beautyads.settings import SettingError, get_setting, load_settings
from beautyads.sources.workspaces import load_workspaces

OUTPUT_ROOT = Path("data/interim/clarify_demo")
SESSION_CAP_USD = 0.40
_CONFIGS = {"dev": "claude-haiku-5-5", "official": "claude-sonnet-5-5"}
_MEASURED = {
    "dev-mixsoon": ["hydration", "brightening", "barrier", "anti_aging"],
    "dev-cosrx": ["hydration", "brightening", "anti_aging", "sun_protection"],
}
_PRODUCTS = {
    "dev-mixsoon": "히알레배 포어 버블 세럼 70ml",
    "dev-cosrx": "울트라 라이트 인비저블 선세럼 50ml",
}


def _choice(mode, claims=(), requested=None):
    return {"mode": mode, "claims": list(claims), "requested_claim": requested}


def _scenario(id, tenant, message, requested, *, lookup="real", reason=None):
    options, branches = [], []
    if reason == "requested_not_confirmed":
        options = ["keep_requested"]
        branches = [_choice("keep_requested", requested=requested)]
        if lookup != "fake_empty":
            options.append("select_confirmed")
            branches.append(_choice("selected", _MEASURED[tenant][:1], requested))
        options.append("none")
        branches.append(_choice("none", requested=requested))
    elif reason == "no_claim_requested":
        options = ["select_one", "select_many", "none"]
        branches = [_choice("selected", _MEASURED[tenant][:n]) for n in (1, 2)]
        branches.append(_choice("none"))
    elif reason == "no_efficacy_confirmed":
        options, branches = ["none", "cancel"], [_choice("none")]
    return {
        "id": id,
        "tenant_id": tenant,
        "message": message,
        "requested_claim": requested,
        "lookup": lookup,
        "expected": {
            "kind": "efficacy_unavailable"
            if lookup == "fake_failed"
            else "needs_clarification"
            if reason
            else "plan",
            "reason": "failed" if lookup == "fake_failed" else reason,
            "options": options,
        },
        "branches": branches,
    }


SCENARIOS = (
    _scenario(
        "1",
        "dev-mixsoon",
        "보습을 내세운 세럼 광고 기획안 1안을 만들어 주세요.",
        "hydration",
    ),
    _scenario(
        "2",
        "dev-mixsoon",
        "피부 장벽 강화를 내세운 세럼 광고 기획안 1안을 만들어 주세요.",
        "barrier",
    ),
    _scenario(
        "3",
        "dev-cosrx",
        "자외선 차단을 내세운 선케어 광고 기획안 1안을 만들어 주세요.",
        "sun_protection",
    ),
    _scenario(
        "4",
        "dev-mixsoon",
        "진정 효과를 내세운 세럼 광고 기획안 1안을 만들어 주세요.",
        "soothing",
        reason="requested_not_confirmed",
    ),
    _scenario(
        "5",
        "dev-cosrx",
        "모공과 피지 관리를 내세운 선케어 광고 기획안 1안을 만들어 주세요.",
        "pore_sebum",
        reason="requested_not_confirmed",
    ),
    _scenario(
        "6",
        "dev-mixsoon",
        "이 세럼의 광고 기획안 1안을 만들어 주세요.",
        None,
        reason="no_claim_requested",
    ),
    _scenario(
        "7",
        "dev-cosrx",
        "이 선세럼 제품의 광고 기획안 1안을 만들어 주세요.",
        None,
        reason="no_claim_requested",
    ),
    _scenario(
        "8",
        "dev-mixsoon",
        "보습을 내세운 세럼 광고 기획안 1안을 만들어 주세요.",
        "hydration",
        lookup="fake_failed",
    ),
    _scenario(
        "9a",
        "dev-mixsoon",
        "이 세럼의 광고 기획안 1안을 만들어 주세요.",
        None,
        lookup="fake_empty",
        reason="no_efficacy_confirmed",
    ),
    _scenario(
        "9b",
        "dev-mixsoon",
        "진정 효과를 내세운 세럼 광고 기획안 1안을 만들어 주세요.",
        "soothing",
        lookup="fake_empty",
        reason="requested_not_confirmed",
    ),
)


class _MemoryTenants:
    def __init__(self):
        self.threads, self.plans = {}, {}

    def register_thread(self, tenant_id, thread_id):
        self.threads.setdefault(thread_id, tenant_id)
        self.assert_thread_access(tenant_id, thread_id)

    def assert_thread_access(self, tenant_id, thread_id):
        if self.threads.get(thread_id) != tenant_id:
            raise TenantMismatch()

    def list_feedback(self, tenant_id, *, limit):
        return []

    def save_plan(self, tenant_id, plan):
        self.plans[tenant_id, plan.plan_id] = plan

    def get_plan(self, tenant_id, plan_id):
        return self.plans.get((tenant_id, plan_id))


def _fake_assembly(scenario, trace_path):
    """Fake inputs only: Supervisor policy, API, SSE and screen projection are real."""
    decisions = {s["message"]: s["requested_claim"] for s in SCENARIOS}

    def ask(
        message, ctx, profile, feedback, with_image, on_event=None, *, claim_choice=None
    ):
        def decide(text):
            return {
                "intent": "plan",
                "category": "sun_care"
                if ctx.tenant_id == "dev-cosrx"
                else "serum_ampoule",
                "claim": decisions[text],
                "hook_type": None,
                "angle": None,
                "format": None,
                "skin_concern": None,
                "plan_count": 1,
                "goal": "제품 홍보",
            }

        def claims(profile):
            if scenario["lookup"] == "fake_failed":
                return [], "failed"
            return (
                []
                if scenario["lookup"] == "fake_empty"
                else list(_MEASURED[ctx.tenant_id])
            ), "ok"

        def research(brief, raw_store):
            return {
                "conclusion": "가짜 리서치",
                "evidence_ids": ["youtube:demo"],
                "aggregates": {},
                "confidence": "low",
                "unresolved": [],
                "status": "ok",
                "no_evidence_tools": [],
                "basis_notes": [],
                "structured_failure_rate": None,
            }

        def plan(brief, handoff, profile, feedback, *, max_reworks):
            choice = handoff["claim_choice"]
            efficacy = choice["claims"] if choice["mode"] == "selected" else []
            return {
                "status": "done",
                "rework_count": 0,
                "plan": {
                    "title": "제품을 만나는 순간",
                    "hook_text": "나의 일상에 더하는 한 단계",
                    "hook_type": "question",
                    "scenes": ["제품과 사용 순서를 보여준다"],
                    "copy_lines": ["제품의 사용감을 살펴보세요"],
                    "image_brief": None,
                    "cta_type": "learn_more",
                    "angle": "how_to",
                    "format": "demo",
                    "category": brief["category"],
                    "product_url": None,
                    "claimed_efficacy": efficacy,
                    "evidence_ids": handoff["evidence_ids"],
                },
                "efficacy_status": dict.fromkeys(efficacy, "supported"),
                "unknown_count": 0,
            }

        result = run_request(
            message=message,
            ctx=ctx,
            profile=profile,
            feedback=feedback,
            decide_fn=decide,
            claims_fn=claims,
            research_fn=research,
            plan_eval_fn=plan,
            spent_fn=lambda: 0,
            on_event=on_event,
            claim_choice=claim_choice,
        )
        if scenario["id"] == "8":
            append_trace(
                trace_path,
                build_trace(
                    tenant_id=ctx.tenant_id,
                    started_at=datetime.now(UTC),
                    duration_ms=0,
                    message=message,
                    result=result,
                    failure=None,
                    ledger_entries=[],
                    structured={},
                ),
            )
        return result

    return Assembly(
        graph=None,
        tenants=_MemoryTenants(),
        allowed_tenants=frozenset(_PRODUCTS),
        as_of=datetime(2026, 11, 20, tzinfo=UTC).date(),
        last_collected_at=None,
        chat=None,
        tool_runner=None,
        close=lambda: None,
        workspaces={
            tenant: {"brand": tenant.removeprefix("dev-"), "product_name": product}
            for tenant, product in _PRODUCTS.items()
        },
        ask=ask,
        hydrate=lambda ids: [],
    )


def _preflight():
    problems = preflight()
    if problems:
        return problems
    return (
        ["ENV_MISSING:ANTHROPIC_API_KEY"]
        if get_setting("ANTHROPIC_API_KEY") is None
        else []
    )


def _totals(settings):
    return {
        provider: provider_total(settings.ledger_path, provider)
        for provider in ("openai", "anthropic")
    }


def _error_code(error):
    if getattr(error, "status_code", None) == 429:
        return "HTTP_429"
    for value in (getattr(error, "kind", None), getattr(error, "code", None)):
        if value in _STOP_CODES:
            return str(value)
    return "REQUEST_FAILED"


class _Stopped(Exception):
    pass


class _SessionCaps(Mapping):
    """Preserve provider caps and gate each SDK precheck, including corrections.

    Both chat and native structured adapters read this mapping immediately
    before every paid attempt. No provider ceiling is replaced or reduced.
    """

    def __init__(self, caps, guard):
        self.caps, self.guard = caps, guard

    def __getitem__(self, key):
        self.guard()
        return self.caps[key]

    def __iter__(self):
        return iter(self.caps)

    def __len__(self):
        return len(self.caps)


class _Session:
    def __init__(self, settings, totals):
        self.settings, self.totals = settings, totals
        self.baseline = totals(settings)
        if any(not math.isfinite(v) or v < 0 for v in self.baseline.values()):
            raise ValueError("LEDGER_INVALID")
        self.stopped = None

    def used(self):
        current = self.totals(self.settings)
        if any(
            not math.isfinite(v) or v < self.baseline[p] for p, v in current.items()
        ):
            raise ValueError("LEDGER_INVALID")
        return {
            p: round(current[p] - self.baseline[p], 12) for p in ("openai", "anthropic")
        }

    def guard(self):
        if sum(self.used().values()) >= SESSION_CAP_USD:
            self.stopped = "BUDGET_REACHED"
        if self.stopped:
            raise _Stopped

    def call(self, function, *args, **kwargs):
        self.guard()
        if "caps" in kwargs:
            kwargs["caps"] = _SessionCaps(kwargs["caps"], self.guard)
        try:
            return function(*args, **kwargs)
        except Exception as exc:
            code = _error_code(exc)
            if code in _STOP_CODES:
                self.stopped = code
            raise

    def models(self):
        session = self

        class GuardedStructured:
            def __init__(self, inner):
                self.inner, self.model = inner, inner.model

            @property
            def stats(self):
                return self.inner.stats

            def generate(self, *args, **kwargs):
                return session.call(self.inner.generate, *args, **kwargs)

        return {
            "chat": lambda **kw: self.call(chat_complete, **kw),
            "structured": lambda model: GuardedStructured(make_structured(model)),
        }


def _safe_plan(data):
    """Summary allowlist: enum values only; prose is rendered separately."""
    allowed = {v.value for v in Claim if v != Claim.other}
    claims = data.get("plan", {}).get("claimed_efficacy", [])
    return {
        "claimed_efficacy": [v for v in claims if isinstance(v, str) and v in allowed],
        "efficacy_status": {
            k: v
            for k, v in data.get("efficacy_status", {}).items()
            if k in allowed and v in {"supported", "unknown", "unsupported"}
        },
    }


def _inspect(outcome, raw, expected, choice):
    clarification = next(
        (b for n, b in outcome.events if n == "needs_clarification"), {}
    )
    unavailable = next(
        (b for n, b in outcome.events if n == "efficacy_unavailable"), {}
    )
    plans = [
        c.get("data", {}) for c in outcome.ui_commands if c.get("kind") == "show_plan"
    ]
    kind = (
        "needs_clarification"
        if clarification
        else "efficacy_unavailable"
        if unavailable
        else "plan"
        if plans
        else raw.get("kind")
    )
    reason = (clarification or unavailable).get("reason")
    options = [o.get("id") for o in clarification.get("options", [])]
    codes = []
    if outcome.status_code != 200:
        codes.append("HTTP_ERROR")
    if any(n == "error" for n, _ in outcome.events):
        codes.append("REQUEST_FAILED")
    if kind != expected["kind"] or (
        raw.get("kind") is not None and raw.get("kind") != expected["kind"]
    ):
        codes.append("KIND_MISMATCH")
    if reason != expected["reason"]:
        codes.append("REASON_MISMATCH")
    if set(options) != set(expected["options"]):
        codes.append("OPTIONS_MISMATCH")
    if expected["kind"] == "plan" and not plans:
        codes.append("PLAN_MISSING")
    steps = raw.get("steps", []) + [b for n, b in outcome.events if n == "step"]
    counts = {
        agent: len({b.get("phase") for b in steps if b.get("agent") == agent})
        for agent in ("research", "planning")
    }
    if expected["kind"] != "plan" and (any(counts.values()) or plans):
        codes.append("EARLY_WORK")
    if kind == "plan":
        if raw.get("available_efficacy_status") != "ok":
            codes.append("EFFICACY_NOT_AVAILABLE")
        available = raw.get("available_efficacy", [])
        for data in plans:
            claimed = data.get("plan", {}).get("claimed_efficacy", [])
            if not set(claimed) <= set(available):
                codes.append("UNCONFIRMED_CLAIM")
            if (
                choice
                and choice["mode"] == "keep_requested"
                and choice["requested_claim"] in claimed
            ):
                codes.append("REQUESTED_CLAIM_ASSERTED")
    row = {
        "kind": kind
        if kind in {"plan", "needs_clarification", "efficacy_unavailable"}
        else None,
        "reason": reason
        if reason
        in {
            "requested_not_confirmed",
            "no_claim_requested",
            "no_efficacy_confirmed",
            "failed",
            "no_product",
        }
        else None,
        "options": [
            v
            for v in options
            if v
            in {
                "keep_requested",
                "select_confirmed",
                "select_one",
                "select_many",
                "none",
                "cancel",
            }
        ],
        "plans": [_safe_plan(p) for p in plans],
        "code_verdict": "match" if not codes else "mismatch",
        "mismatch_codes": list(dict.fromkeys(codes)),
    }
    return row, clarification, unavailable, plans, counts


def _print_response(row, clarification, unavailable, plans, counts, *, fake, out):
    labels = {
        "plan": "기획안",
        "efficacy_unavailable": "제품 미등록으로 중단"
        if unavailable.get("reason") == "no_product"
        else "효능 근거 조회 실패로 중단",
        "needs_clarification": "되묻기 ②"
        if row["reason"] == "requested_not_confirmed"
        else "되묻기 ③",
    }
    print("시스템 응답: " + labels.get(row["kind"], "요청 실패"), file=out)
    if clarification:
        print(clarification.get("text", ""), file=out)
        for index, option in enumerate(clarification.get("options", []), 1):
            print(f"{index}. {option.get('label', '')}", file=out)
    if unavailable:
        print(unavailable.get("text", ""), file=out)
    print(f"리서치 {counts['research']}회 · 기획 {counts['planning']}회", file=out)
    for data in plans:
        plan = data.get("plan", {})
        print("기획안 요약:" + (" 가짜 기획(dry-run)" if fake else ""), file=out)
        print(
            f"  제목: {plan.get('title', '')}\n  훅 문구: {plan.get('hook_text', '')}",
            file=out,
        )
        for line in plan.get("copy_lines", []):
            print(f"  카피: {line}", file=out)
        claimed = plan.get("claimed_efficacy", [])
        print(
            "  claimed_efficacy: "
            + (
                ", ".join(f"{CLAIM_DISPLAY_NAMES.get(c, c)}({c})" for c in claimed)
                or "없음"
            ),
            file=out,
        )
        print(
            f"  efficacy_status: {data.get('efficacy_status', {})} · unknown_count: {data.get('unknown_count', 0)}",
            file=out,
        )
        prose = " ".join([plan.get("hook_text", ""), *plan.get("copy_lines", [])])
        suspects = [
            w for w in ("입증", "확실", "보장", "치료", "100%", "완벽") if w in prose
        ]
        print(
            "단정 의심 표현(참고, 코드 판정 아님): " + (", ".join(suspects) or "없음"),
            file=out,
        )
    print(
        "확인 포인트: 소구 방향 · claimed_efficacy 값 · 효능 단정 표현 없음(문장은 직접 확인)",
        file=out,
    )
    print(
        "코드 판정: "
        + (
            "일치"
            if row["code_verdict"] == "match"
            else "불일치 " + ", ".join(row["mismatch_codes"])
        ),
        file=out,
    )


def _trace_check(path, scenario, out):
    records = read_traces(path).records
    record = next(
        (
            r
            for r in reversed(records)
            if r.tenant_id == scenario["tenant_id"]
            and r.efficacy_unavailable is not None
        ),
        None,
    )
    valid = (
        record is not None
        and record.efficacy_unavailable.reason == "failed"
        and record.efficacy_unavailable.brand
        == scenario["tenant_id"].removeprefix("dev-")
        and record.efficacy_unavailable.product_name == _PRODUCTS[scenario["tenant_id"]]
    )
    valid = (
        valid
        and scenario["message"] not in path.read_text(encoding="utf-8")
        and "message" not in record.model_dump()
    )
    print(
        "trace 확인: 작업 공간·제품·상태 기록, 요청 본문 없음"
        if valid
        else "trace 확인: 불일치 TRACE_MISMATCH",
        file=out,
    )
    if valid:
        print(
            f"  작업 공간: {record.tenant_id} · 제품: {record.efficacy_unavailable.brand} / {record.efficacy_unavailable.product_name} · 상태: failed",
            file=out,
        )
    return valid


def _branch_choices(scenario, clarification):
    """Select actual confirmed values in live responses, preserving scenario modes."""
    available = [v["claim"] for v in clarification.get("available", [])]
    for choice in scenario["branches"]:
        if choice["mode"] == "selected":
            yield _choice(
                "selected",
                available[: len(choice["claims"])],
                choice["requested_claim"],
            )
        else:
            yield dict(choice)


def _branch_label(scenario, clarification, choice):
    mode = choice["mode"]
    id = (
        "select_confirmed"
        if mode == "selected" and scenario["requested_claim"]
        else "select_one"
        if mode == "selected" and len(choice["claims"]) == 1
        else "select_many"
        if mode == "selected"
        else mode
    )
    return next(
        (v["label"] for v in clarification.get("options", []) if v["id"] == id), id
    )


def main(
    argv=None,
    *,
    out=None,
    check=None,
    run=None,
    settings=None,
    assemble=None,
    totals=None,
):
    out = sys.stdout if out is None else out
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--config", choices=tuple(_CONFIGS), default="dev")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", nargs="+", default=[])
    try:
        args = parser.parse_args(argv)
        if set(args.only) - {s["id"] for s in SCENARIOS}:
            raise _ArgumentError
    except _ArgumentError:
        print("ARGUMENT_ERROR", file=out)
        return 2
    selected = [s for s in SCENARIOS if not args.only or s["id"] in args.only]
    session = None
    try:
        dev_tenants = {
            w.tenant_id
            for w in load_workspaces(Path("config/workspaces.yaml"))
            if w.group == "dev"
        }
        if any(s["tenant_id"] not in dev_tenants for s in SCENARIOS):
            print("PREFLIGHT_FAILED WORKSPACE_GROUP_INVALID", file=out)
            return 2
        if not args.dry_run:
            try:
                problems = (_preflight if check is None else check)()
            except SettingError:
                raise
            except Exception:  # noqa: BLE001 -- environment diagnostics may contain credentials
                print("PREFLIGHT_FAILED CHECK_FAILED", file=out)
                return 2
            if problems:
                for code in problems:
                    # Only closed diagnostic tokens cross the CLI boundary.
                    safe = (
                        code
                        if re.fullmatch(r"[A-Z][A-Z0-9_:]{0,80}", code)
                        else "CHECK_FAILED"
                    )
                    print(f"PREFLIGHT_FAILED {safe}", file=out)
                return 2
            settings = load_settings() if settings is None else settings
            session = _Session(settings, _totals if totals is None else totals)
        full = sum(
            (1 if s["expected"]["kind"] == "plan" else 0) + len(s["branches"])
            for s in selected
        )
        first = sum(s["expected"]["kind"] == "needs_clarification" for s in selected)
        print(
            f"효능 되묻기 점검: 시나리오 {len(selected)}개 · 전체 실행 {full}회 · 되묻기 첫 호출 {first}회",
            file=out,
        )
        print(
            "개발 구성 예상 비용 약 $0.17 · 세션 상한 $0.40 (단가는 2026-11-20 원장 평균 가정, 실측 아님)",
            file=out,
        )
        print(
            "live 모델 대상 1~7: 전체 실행 15회 · 되묻기 첫 호출 4회; 8·9는 가짜 입력, 모델 호출 없음",
            file=out,
        )
        if args.dry_run:
            print(
                "확인 효능: 측정값(2026-11-20), 실제 조회 아님 · 모델·네트워크·DB·.env 사용 없음",
                file=out,
            )
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex
        trace_path = OUTPUT_ROOT / "traces.jsonl"
        rows, pending, exit_code = [], [], 0
        stop = None
        for index, scenario in enumerate(selected):
            fake = args.dry_run or scenario["lookup"] != "real"
            tenant = scenario["tenant_id"]
            expected = scenario["expected"]
            category = (
                "효능 맞음"
                if expected["kind"] == "plan"
                else "근거 없음 ②"
                if expected["reason"] == "requested_not_confirmed"
                else "조회 실패"
                if scenario["id"] == "8"
                else "확인 효능 0개"
                if scenario["id"] == "9a"
                else "지정 없음 ③"
            )
            print(
                f"\n[{index + 1}/{len(selected)}] {category} · {tenant} · {_PRODUCTS[tenant]} (시나리오 {scenario['id']})",
                file=out,
            )
            print(f"요청: {scenario['message']}", file=out)
            print(
                f"기대: {expected['kind']}"
                + (
                    f" ({expected['reason']})"
                    if expected["reason"]
                    else " · claimed_efficacy ⊆ 확인 효능"
                )
                + (
                    " · 선택지 " + ", ".join(expected["options"])
                    if expected["options"]
                    else ""
                )
                + (
                    " · 첫 호출 리서치·기획 0회"
                    if expected["kind"] != "plan"
                    else " · 되묻기 없음"
                ),
                file=out,
            )
            holder = {}
            thread_id = make_thread_id(tenant)

            async def observed_assembly(
                scenario=scenario,
                fake=fake,
                tenant=tenant,
                thread_id=thread_id,
                holder=holder,
            ):
                services = (
                    _fake_assembly(scenario, trace_path)
                    if fake
                    else (assemble_full if assemble is None else assemble)(
                        settings=settings,
                        group="dev",
                        evaluation_model=_CONFIGS[args.config],
                        with_image_enabled=False,
                        limits=RequestLimits(),
                        models=session.models(),
                    )
                )
                if inspect.isawaitable(services):
                    services = await services
                services.tenants.register_thread(tenant, thread_id)
                original = services.ask

                def observed(*a, **kw):
                    holder["result"] = original(*a, **kw)
                    return holder["result"]

                services.ask = observed
                return services

            app = create_app(observed_assembly)
            runner = run_ask_once if fake or run is None else run
            row = {"id": scenario["id"], "branches": []}
            rows.append(row)

            def request(
                choice,
                expectation,
                *,
                holder=holder,
                fake=fake,
                runner=runner,
                app=app,
                tenant=tenant,
                scenario=scenario,
                thread_id=thread_id,
            ):
                nonlocal stop
                holder.clear()
                try:
                    if session is not None:
                        session.guard()
                    outcome = runner(
                        app,
                        tenant_id=tenant,
                        message=scenario["message"],
                        with_image=False,
                        thread_id=thread_id,
                        **({"claim_choice": choice} if choice is not None else {}),
                    )
                    for name, body in outcome.events:
                        if name == "error":
                            code = body.get("error_code") or body.get("code")
                            if code in _STOP_CODES:
                                stop = code
                    if session and session.stopped:
                        stop = session.stopped
                    inspection = _inspect(
                        outcome, holder.get("result", {}), expectation, choice
                    )
                except _Stopped:
                    stop = session.stopped
                    return None
                except Exception as exc:  # noqa: BLE001 -- discard diagnostics and response bodies
                    code = _error_code(exc)
                    if code in _STOP_CODES:
                        stop = code
                    inspection = (
                        {
                            "kind": None,
                            "reason": None,
                            "options": [],
                            "plans": [],
                            "code_verdict": "mismatch",
                            "mismatch_codes": [code],
                        },
                        {},
                        {},
                        [],
                        {"research": 0, "planning": 0},
                    )
                _print_response(*inspection, fake=fake, out=out)
                return inspection

            initial = request(None, expected)
            if initial is None:
                rows.pop()
                pending = [s["id"] for s in selected[index:]]
                break
            row.update(initial[0])
            if scenario["id"] == "8" and not _trace_check(trace_path, scenario, out):
                row["code_verdict"] = "mismatch"
                row["mismatch_codes"].append("TRACE_MISMATCH")
            if stop:
                pending = [s["id"] for s in selected[index + 1 :]]
                break
            if row["code_verdict"] == "match":
                for choice in _branch_choices(scenario, initial[1]):
                    print(
                        f"선택: {_branch_label(scenario, initial[1], choice)} → 재요청 ({choice['mode']}, {len(choice['claims'])}개)",
                        file=out,
                    )
                    result = request(
                        choice, {"kind": "plan", "reason": None, "options": []}
                    )
                    if result is None:
                        pending = [s["id"] for s in selected[index:]]
                        break
                    row["branches"].append({"claim_choice": choice, **result[0]})
                    if stop:
                        pending = [s["id"] for s in selected[index:]]
                        break
                if "cancel" in expected["options"] and not stop:
                    print(
                        "선택: 중단(cancel) → 화면에서 취소, 서버 요청 없음", file=out
                    )
            if stop:
                break
        if stop:
            print(f"STOPPED {stop}", file=out)
            exit_code = 2
        elif any(
            r["code_verdict"] != "match"
            or any(b["code_verdict"] != "match" for b in r["branches"])
            for r in rows
        ):
            exit_code = 3
        _write_json(
            OUTPUT_ROOT / f"{run_id}.json",
            {
                "scenarios": rows,
                "cost_by_provider": session.used()
                if session
                else dict.fromkeys(("openai", "anthropic"), 0.0),
                "pending": pending,
            },
        )
        return exit_code
    except SettingError as error:
        print(f"PREFLIGHT_FAILED {error.code}:{error.name}", file=out)
        return 2
    except Exception:  # noqa: BLE001 -- no paths, credentials, or exception messages
        print("STOPPED CLARIFY_DEMO_FAILED", file=out)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
