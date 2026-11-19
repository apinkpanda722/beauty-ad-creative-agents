"""User-run E2/E5 batches; importing or dry-running never contacts services."""

import argparse
import asyncio
import hashlib
import inspect
import json
import math
import re
import sys
import tempfile
from dataclasses import asdict
from functools import partial
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

from pydantic import Field

from beautyads.agents.lookups import (
    GraphCertLookup,
    GraphEfficacySupport,
    GraphEvidenceIndex,
)
from beautyads.agents.tools import run_tool
from beautyads.api.assembly import assemble_full
from beautyads.api.feedback import feedback_for_prompt
from beautyads.api.session import resolve_session
from beautyads.domain.labels import Angle, Category, Claim, Format, HookType
from beautyads.domain.skin import SkinConcern
from beautyads.domain.supervisor import RequestLimits, cost_exceeded
from beautyads.domain.tools import ToolContext
from beautyads.eval.cq_verify import cq_preflight
from beautyads.eval.e2_scoring import (
    SCORING_SEED,
    ArmRecord,
    analyze,
    blind_items,
    build_claim_sheet,
    e2_rubric_sha256,
    load_claim_matches,
    reveal_scores,
    score_plans,
)
from beautyads.eval.evalset import (
    AXIS_NAMES,
    REQUESTS_PATH,
    WORKSPACES_PATH,
    RequestItem,
    read_jsonl,
    request_set_hash,
)
from beautyads.eval.freeze_guard import FreezeError, check_run
from beautyads.eval.single_agent import run_single_agent, single_agent_system_prompt
from beautyads.graph.connection import connect_graph
from beautyads.llm.chat import chat_complete
from beautyads.llm.errors import ErrorKind, LlmCallError
from beautyads.llm.structured import make_structured
from beautyads.obs.ledger import (
    CostCapExceeded,
    check_cap,
    ledger_total,
    read_entries,
)
from beautyads.pipeline.preflight import docker_running, tcp_reachable
from beautyads.settings import (
    DEFAULT_ENV_FILE,
    SettingError,
    get_setting,
    load_settings,
)
from beautyads.sources.claim_rules import load_claim_rules
from beautyads.sources.workspaces import load_workspaces

ARMS_DEFAULT = ("supervisor", "single", "off")
DEFAULT_BUDGET_USD = {"dev": 0.40, "final": 3.0}
DEV_SCORE_MAX_ITEMS = 6
RESULT_ROOT = Path("data/interim/e2e5")
_SCORING_MODEL = "claude-sonnet-5-5"


class _RecordedArm(ArmRecord):
    """Runner metadata is stripped before passing records to step 5 consumers."""

    prereg_commit: str | None
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    input_tokens_by_purpose: dict[str, int] = Field(default_factory=dict)
    model_calls_by_purpose: dict[str, int] = Field(default_factory=dict)
    brief_axes: dict[str, str | None] | None = None
    dominant_axes: list[dict] | None = None


class _Stopped(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _Arguments(argparse.ArgumentParser):
    def error(self, message):
        raise _Stopped("ARGUMENT_ERROR")


def _extra_frozen():
    return {
        "동결 단일 에이전트 프롬프트 sha256": hashlib.sha256(
            single_agent_system_prompt().encode("utf-8")
        ).hexdigest(),
        "동결 E2 채점 루브릭 sha256": e2_rubric_sha256(),
    }


def tool_context(assembly, tenant_id):
    """Use exactly the request-local context construction in api/ask.py."""
    return ToolContext(
        tenant_id=tenant_id,
        as_of=assembly.as_of,
        last_collected_at=assembly.last_collected_at,
        price_band=assembly.price_bands.get(tenant_id),
    )


def ledger_delta(path, before):
    entries = read_entries(path).entries[before:]
    return {
        "input_tokens": sum(e.input_tokens for e in entries),
        "model_calls": len(entries),
        "spent_usd": math.fsum(
            e.cost_usd
            for e in entries
            if e.purpose != "image" and not e.purpose.startswith("image-")
        ),
    }


def ledger_purpose_totals(path, before):
    """Count the same ledger increment by exact purpose, including images."""
    tokens, calls = {}, {}
    for entry in read_entries(path).entries[before:]:
        purpose = entry.purpose
        tokens[purpose] = tokens.get(purpose, 0) + entry.input_tokens
        calls[purpose] = calls.get(purpose, 0) + 1
    return {"input_tokens_by_purpose": tokens, "model_calls_by_purpose": calls}


def observed_axes(result, tool_logs=()):
    distribution = ((result.get("handoff") or {}).get("pattern_context") or {}).get(
        "distribution"
    ) or []
    axes = {
        row.get("axis")
        for row in distribution
        if isinstance(row, dict) and row.get("axis") in AXIS_NAMES
    }
    for row in tool_logs:
        if not isinstance(row, dict):
            continue
        args = row.get("arguments") or row.get("inputs") or row
        if isinstance(args, dict) and args.get("axis") in AXIS_NAMES:
            axes.add(args.get("axis"))
    return sorted(axes)


class _Watch:
    """Retain stop reasons even when an agent sanitizes a wrapper exception."""

    def __init__(self):
        self.stopped = None
        self.tool_logs = []
        self.error_class = None
        self.cap_scope = None

    def call(self, fn, *args, **kwargs):
        if self.stopped:
            raise _Stopped(self.stopped)
        try:
            result = fn(*args, **kwargs)
            for call in getattr(result, "tool_calls", ()):
                arguments = call.arguments
                if isinstance(arguments, dict) and arguments.get("axis") in AXIS_NAMES:
                    # Retain only the closed axis, never arbitrary tool arguments.
                    self.tool_logs.append({"axis": arguments.get("axis")})
            return result
        except CostCapExceeded as error:
            self.stopped = "COST_CAP_REACHED"
            self.error_class = type(error).__name__
            self.cap_scope = _cap_scope(error)
            raise
        except LlmCallError as error:
            self.error_class = type(error).__name__
            if error.kind in {ErrorKind.DAILY_LIMIT, ErrorKind.CREDITS_DEPLETED}:
                self.stopped = "DAILY_LIMIT"
            raise
        except Exception as error:
            self.error_class = type(error).__name__
            raise

    def structured(self, factory, model):
        return _WatchedStructured(factory(model), self)


def _cap_scope(error):
    provider = error.provider
    if provider in {"gemini", "openai", "anthropic"}:
        return "provider:" + provider
    if provider in {"purpose:image", "purpose:e2-score", "purpose:e2-score-run"}:
        return provider
    return "provider:unknown"


class _WatchedStructured:
    def __init__(self, inner, watch):
        self.inner, self.watch, self.model = inner, watch, inner.model

    @property
    def stats(self):
        return self.inner.stats

    def generate(self, *args, **kwargs):
        return self.watch.call(self.inner.generate, *args, **kwargs)


def _call_options(settings, model, *, environ, env_file):
    return {
        "ledger_path": settings.ledger_path,
        "caps": dict(settings.provider_caps_usd),
        "api_key": get_setting(
            "ANTHROPIC_API_KEY" if model.startswith("claude-") else "OPENAI_API_KEY",
            environ=environ,
            env_file=env_file,
        ),
        "max_tokens": 4096,
    }


class _ConfiguredStructured:
    def __init__(self, inner, options, guard):
        self.inner, self.options, self.guard = inner, options, guard
        self.model = inner.model

    def generate(self, *args, **kwargs):
        self.guard()
        return self.inner.generate(*args, **{**kwargs, **self.options})


def build_single_arm(
    *,
    settings,
    limits,
    environ=None,
    env_file=DEFAULT_ENV_FILE,
    graph_fn=connect_graph,
    chat_fn=chat_complete,
    structured_factory=make_structured,
    watch=None,
):
    """Mirror assembly's SDK wrappers, Settings caps and deterministic lookups."""
    watch = _Watch() if watch is None else watch
    rules = load_claim_rules(Path("config/claim_rules.yaml"))
    graph = graph_fn(environ=environ, env_file=env_file)
    try:
        runner = partial(run_tool, graph=graph)
        evidence, support, certs = (
            GraphEvidenceIndex(graph),
            GraphEfficacySupport(graph),
            GraphCertLookup(graph),
        )

        def run(**kwargs):
            before = ledger_total(settings.ledger_path, exclude_purpose_prefix="image")

            def spent():
                return (
                    ledger_total(settings.ledger_path, exclude_purpose_prefix="image")
                    - before
                )

            def guard():
                if cost_exceeded(spent(), limits):
                    raise _Stopped("REQUEST_TEXT_CAP_REACHED")

            def chat(**options):
                guard()
                return watch.call(
                    chat_fn,
                    **{
                        "purpose": "agent-skeleton",
                        **options,
                        **_call_options(
                            settings,
                            options["model"],
                            environ=environ,
                            env_file=env_file,
                        ),
                    },
                )

            structured = _ConfiguredStructured(
                watch.structured(structured_factory, "gpt-6.1-terra"),
                _call_options(
                    settings, "gpt-6.1-terra", environ=environ, env_file=env_file
                ),
                guard,
            )
            return run_single_agent(
                **kwargs,
                chat=chat,
                tool_runner=runner,
                structured=structured,
                rules=rules,
                evidence_index=evidence,
                support=support,
                certs=certs,
                limits=limits,
                spent_fn=spent,
            )

        return SimpleNamespace(run=run, close=graph.close)
    except BaseException:
        graph.close()
        raise


def run_arm(arm, item, *, assembly, single):
    tenant_id, _ = resolve_session(
        item.tenant_id,
        None,
        tenants=assembly.tenants,
        allowed_tenants=assembly.allowed_tenants,
    )
    profile = assembly.workspaces.get(tenant_id)
    if profile is None:
        raise _Stopped("WORKSPACE_GROUP_INVALID")
    ctx = tool_context(assembly, tenant_id)
    feedback = feedback_for_prompt(assembly.tenants, tenant_id, assembly.as_of)
    if arm == "single":
        return single.run(
            message=item.message, ctx=ctx, profile=profile, feedback=feedback
        )
    return assembly.ask(
        item.message,
        ctx,
        profile,
        feedback,
        False,
        **({"context_mode": "off"} if arm == "off" else {}),
    )


def _preflight(*, settings, command, environ, env_file):
    config = {"environ": environ, "env_file": env_file}
    keys = (
        ("ANTHROPIC_API_KEY",)
        if command == "score"
        else ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "POSTGRES_PASSWORD")
    )
    for key in keys:
        if get_setting(key, **config) is None:
            return ["ENV_MISSING:" + key]
    try:
        settings.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=settings.ledger_path.parent):
            pass
        if settings.ledger_path.exists():
            with settings.ledger_path.open("a", encoding="utf-8"):
                pass
        if read_entries(settings.ledger_path).skipped_lines:
            return ["LEDGER_INVALID"]
        providers = ("anthropic",) if command == "score" else ("openai", "anthropic")
        for provider in providers:
            check_cap(settings.ledger_path, provider, settings.provider_caps_usd)
    except CostCapExceeded as error:
        return ["COST_CAP_REACHED " + _cap_scope(error)]
    except (OSError, UnicodeError):
        return ["LEDGER_NOT_WRITABLE"]
    if command == "score":
        return []
    problem = cq_preflight(
        **config, docker_check=docker_running, tcp_check=tcp_reachable
    )
    if problem:
        return [problem]
    try:
        port = int(get_setting("BEAUTYADS_POSTGRES_PORT", "5433", **config))
        if not 1 <= port <= 65535 or not tcp_reachable("127.0.0.1", port, 1.0):
            return ["POSTGRES_UNREACHABLE"]
    except (ValueError, TypeError, OSError):
        return ["POSTGRES_UNREACHABLE"]
    return []


def _json_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_records(root):
    path = root / "records.jsonl"
    if not path.exists():
        return []
    rows = [_RecordedArm.model_validate(row) for row in read_jsonl(path)]
    if len({(r.item_id, r.arm) for r in rows}) != len(rows):
        raise _Stopped("ARM_RECORD_DUPLICATE")
    return rows


def _plain(rows):
    return [r.model_dump(include=set(ArmRecord.model_fields)) for r in rows]


def _record_axes(arm, result):
    """Retain only closed brief values and numeric pattern observations."""
    if arm == "single":
        return {"brief_axes": None, "dominant_axes": None}
    closed = {
        "category": Category,
        "claim": Claim,
        "hook_type": HookType,
        "angle": Angle,
        "format": Format,
        "skin_concern": SkinConcern,
    }
    brief = result.get("brief")
    brief_axes = (
        {
            axis: value
            if isinstance(value := brief.get(axis), str) and value in values
            else None
            for axis, values in closed.items()
        }
        if isinstance(brief, dict) and brief
        else None
    )
    context = (result.get("handoff") or {}).get("pattern_context") or {}
    dominant = context.get("dominant_axes")
    dominant_axes = None
    if isinstance(dominant, list):
        dominant_axes = []
        for row in dominant:
            if not isinstance(row, dict):
                continue
            axis, values, share = (row.get(k) for k in ("axis", "values", "share"))
            if (
                axis not in ("format", "hook_type", "angle")
                or not isinstance(values, list)
                or not all(isinstance(v, str) and v in closed[axis] for v in values)
                or type(share) not in (int, float)
                or not math.isfinite(share)
            ):
                continue
            dominant_axes.append({"axis": axis, "values": values, "share": share})
    return {"brief_axes": brief_axes, "dominant_axes": dominant_axes}


def _record(
    item, arm, result, *, run_id, identity, set_hash, delta, by_purpose, latency
):
    first = next(iter(result.get("plans") or []), {})
    plan = result.get("plan") if arm == "single" else first.get("plan")
    status = "plan" if plan is not None else result.get("kind", "failed")
    if status not in ArmRecord.model_fields["status"].annotation.__args__:
        status = "failed"
    versions = result.get("prompt_versions") or {}
    if arm == "single" and isinstance(result.get("prompt_version"), str):
        versions = {"single": result["prompt_version"]}
    return _RecordedArm(
        run_id=run_id,
        item_id=item.id,
        arm=arm,
        tenant_id=item.tenant_id,
        status=status,
        plan=plan,
        check_report=result.get("check_report")
        if arm == "single"
        else (first.get("report") or {}).get("check_report"),
        evidence_pool=result.get("evidence_pool")
        or (result.get("handoff") or {}).get("evidence_ids")
        or [],
        **delta,
        **by_purpose,
        **_record_axes(arm, result),
        latency_s=latency,
        tool_calls=result.get(
            "tool_calls", len((result.get("handoff") or {}).get("result_counts") or [])
        ),
        limit_hit=bool(result.get("limit_hit")) or status == "limit",
        code_commit=identity.code_commit or "unavailable",
        evalset_hash=set_hash,
        prereg_commit=identity.prereg_commit,
        axes_used_observed=observed_axes(result, result.get("tool_logs") or []),
        prompt_versions=versions,
    )


async def _close(resource):
    if resource is not None:
        result = resource.close()
        if inspect.isawaitable(result):
            await result


async def _run_batch(
    args,
    items,
    identity,
    set_hash,
    root,
    rows,
    *,
    settings,
    assemble,
    single_builder,
    chat_fn,
    structured_factory,
    environ,
    env_file,
    out,
    prior_score_spend,
):
    assembly, single, watch = None, None, _Watch()
    limits = RequestLimits()
    seen = {(r.item_id, r.arm) for r in rows}
    baseline = ledger_total(settings.ledger_path)
    previous_spend = math.fsum(r.spent_usd for r in rows) + prior_score_spend
    exit_code = 0
    try:
        assembly = await assemble(
            settings=settings,
            group="dev" if args.mode == "dev" else "test",
            limits=limits,
            environ=environ,
            env_file=env_file,
            models={
                "chat": partial(watch.call, chat_fn),
                "structured": partial(watch.structured, structured_factory),
            },
        )
        if "single" in args.arms:
            single = single_builder(
                settings=settings,
                limits=limits,
                environ=environ,
                env_file=env_file,
                chat_fn=chat_fn,
                structured_factory=structured_factory,
                watch=watch,
            )
        for item in items:
            for arm in ARMS_DEFAULT:
                if arm not in args.arms or (item.id, arm) in seen:
                    continue
                if (
                    previous_spend + ledger_total(settings.ledger_path) - baseline
                    >= args.budget_usd
                ):
                    print("STOPPED BUDGET_REACHED", file=out)
                    return 2
                before, started = (
                    len(read_entries(settings.ledger_path).entries),
                    monotonic(),
                )
                watch.tool_logs.clear()
                watch.error_class = None
                result, stopped = {"kind": "failed"}, None
                try:
                    result = run_arm(arm, item, assembly=assembly, single=single)
                except CostCapExceeded as error:
                    stopped = "COST_CAP_REACHED"
                    watch.error_class = type(error).__name__
                    watch.cap_scope = _cap_scope(error)
                except LlmCallError as error:
                    watch.error_class = type(error).__name__
                    if error.kind in {
                        ErrorKind.DAILY_LIMIT,
                        ErrorKind.CREDITS_DEPLETED,
                    }:
                        stopped = "DAILY_LIMIT"
                except Exception as error:  # noqa: BLE001 -- no exception prose
                    result = {"kind": "failed"}
                    watch.error_class = type(error).__name__
                stopped = stopped or watch.stopped
                result = {
                    **result,
                    "tool_logs": [*watch.tool_logs, *(result.get("tool_logs") or [])],
                }
                row = _record(
                    item,
                    arm,
                    result,
                    run_id=args.run_id,
                    identity=identity,
                    set_hash=set_hash,
                    delta=ledger_delta(settings.ledger_path, before),
                    by_purpose=ledger_purpose_totals(settings.ledger_path, before),
                    latency=monotonic() - started,
                )
                with (root / "records.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(row.model_dump_json() + "\n")
                if row.status == "failed":
                    exit_code = 3
                    print(
                        "REQUEST_FAILED " + (watch.error_class or "RESULT_FAILED"),
                        file=out,
                    )
                if stopped:
                    print(
                        "STOPPED "
                        + stopped
                        + (" " + watch.cap_scope if watch.cap_scope else ""),
                        file=out,
                    )
                    return 2
        print("COMPLETED " + args.run_id, file=out)
        return exit_code
    finally:
        try:
            await _close(single)
        finally:
            await _close(assembly)


def _token_summary(on, off):
    on_total, off_total = sum(on), sum(off)
    return {
        "supervisor": {
            "total": on_total,
            "mean_per_request": on_total / len(on) if on else None,
        },
        "off": {
            "total": off_total,
            "mean_per_request": off_total / len(off) if off else None,
        },
        "reduction": 1 - on_total / off_total if off_total else "해당 없음",
    }


def _e5_supplement(rows, items):
    """Descriptive paired metrics only; never passed to the frozen analyzer."""
    index = {(r.item_id, r.arm): r for r in rows}
    paired = [
        (index[item.id, "supervisor"], index[item.id, "off"])
        for item in items
        if (item.id, "supervisor") in index and (item.id, "off") in index
    ]
    pairs = [p for p in paired if all(r.input_tokens_by_purpose for r in p)]
    purposes = sorted(
        {
            purpose
            for pair in pairs
            for r in pair
            for purpose in r.input_tokens_by_purpose
        }
    )
    totals = {
        purpose: _token_summary(
            [a.input_tokens_by_purpose.get(purpose, 0) for a, _ in pairs],
            [b.input_tokens_by_purpose.get(purpose, 0) for _, b in pairs],
        )
        for purpose in purposes
    }
    research = {}
    for i, arm in enumerate(("supervisor", "off")):
        calls = sum(pair[i].model_calls_by_purpose.get("research", 0) for pair in pairs)
        tokens = sum(
            pair[i].input_tokens_by_purpose.get("research", 0) for pair in pairs
        )
        research[arm] = {
            "mean_calls_per_request": calls / len(pairs) if pairs else None,
            "input_tokens_per_call": tokens / calls if calls else "해당 없음",
        }
    return {
        "pairs_used": len(pairs),
        "pairs_unavailable": len(paired) - len(pairs),
        "purposes": totals,
        "plan_per_request": [
            {
                "supervisor": a.input_tokens_by_purpose.get("plan", 0),
                "off": b.input_tokens_by_purpose.get("plan", 0),
                "reduction": _token_summary(
                    [a.input_tokens_by_purpose.get("plan", 0)],
                    [b.input_tokens_by_purpose.get("plan", 0)],
                )["reduction"],
            }
            for a, b in pairs
        ],
        "research": research,
        "non_research": _token_summary(
            [
                a.input_tokens - a.input_tokens_by_purpose.get("research", 0)
                for a, _ in pairs
            ],
            [
                b.input_tokens - b.input_tokens_by_purpose.get("research", 0)
                for _, b in pairs
            ],
        ),
    }


def _axis_adherence(rows, items):
    requests = {item.id: item for item in items}
    report = {}
    for arm in ("supervisor", "off"):
        selected = [r for r in rows if r.arm == arm and r.item_id in requests]
        available = [
            r for r in selected if r.brief_axes is not None and r.plan is not None
        ]
        axes = {}
        for axis in ("format", "hook_type", "angle"):
            specified = [r for r in available if r.brief_axes.get(axis) is not None]
            axes[axis] = {
                "specified": len(specified),
                "adherent": sum(
                    r.plan.get(axis) == r.brief_axes.get(axis) for r in specified
                ),
                "dominant_conflict": sum(
                    any(
                        d.get("axis") == axis
                        and r.brief_axes.get(axis) in (d.get("values") or [])
                        for d in r.dominant_axes or []
                    )
                    for r in specified
                ),
                "interpretation_missing": sum(
                    axis in requests[r.item_id].axes_used
                    and r.brief_axes.get(axis) is None
                    for r in available
                ),
            }
        report[arm] = {
            "unavailable": sum(r.brief_axes is None for r in selected),
            "with_plan": len(available),
            "axes": axes,
        }
    return report


def _report(rows, items, root, metadata, out):
    scores = json.loads((root / "scores.json").read_text(encoding="utf-8"))
    sheet = root / "claim_sheet.csv"
    matches = None
    if sheet.exists():
        matches = load_claim_matches(sheet, root / "private" / "claim_sheet_key.json")
    report = analyze(_plain(rows), requests=items, scores=scores, claim_matches=matches)
    print("조건: " + metadata["mode"] + "; 이미지 끔; 1인 라벨링", file=out)
    print("E2 구성 한계: 한 에이전트 대 한 시스템", file=out)
    print(
        f"요청당 텍스트 상한: {RequestLimits().max_text_cost_usd}; 채점 모델: {_SCORING_MODEL}",
        file=out,
    )
    print("evalset_hash " + metadata["evalset_hash"], file=out)
    print(
        "RunIdentity " + json.dumps(metadata["identity"], ensure_ascii=False), file=out
    )
    print("| 항목 | 값 |\n| --- | --- |", file=out)
    for name, value in report.items():
        print(f"| {name} | {json.dumps(value, ensure_ascii=False)} |", file=out)
    print("| axes_used_observed (참고) | 건수 |\n| --- | --- |", file=out)
    for axis in AXIS_NAMES:
        count = sum(axis in r.axes_used_observed for r in rows)
        if count:
            print(f"| {axis} | {count} |", file=out)
    supplement = _e5_supplement(rows, items)
    adherence = _axis_adherence(rows, items)
    _json_write(root / "e5_supplement.json", supplement)
    _json_write(root / "axis_adherence.json", adherence)
    print("\nE5 보조 지표(참고용, 판정에 쓰지 않음)", file=out)
    print(
        "| 항목 | 켬(supervisor) | 끔(off) | 변화율 1 − 켬/끔 |\n| --- | --- | --- | --- |",
        file=out,
    )
    print(f"| 사용한 쌍 수 | {supplement['pairs_used']} | | |", file=out)
    print(f"| 값이 없어 뺀 쌍 수 | {supplement['pairs_unavailable']} | | |", file=out)
    for label, values in (
        *supplement["purposes"].items(),
        ("리서치 제외 합계", supplement["non_research"]),
        ("리서치 호출 수 평균·호출당 입력 토큰", supplement["research"]),
        *(
            (f"plan 요청 {i}", value)
            for i, value in enumerate(supplement["plan_per_request"], 1)
        ),
    ):
        cells = [
            json.dumps(values.get(k, ""), ensure_ascii=False)
            for k in ("supervisor", "off", "reduction")
        ]
        print(f"| {label} | " + " | ".join(cells) + " |", file=out)
    print(
        "리서치 호출 수 변동이 합계를 수천 토큰 흔들 수 있다. 판정은 요청당 입력 토큰 합계 기준 그대로다.",
        file=out,
    )
    print("\n지정 축 준수(코드 판정, 참고용)", file=out)
    print(
        "| 팔 | 축 | 지정 | 준수 | 지배 값과 충돌 | 해석 누락 | unavailable |\n| --- | --- | --- | --- | --- | --- | --- |",
        file=out,
    )
    for arm, values in adherence.items():
        print(f"| {arm} | 전체 | | | | | {values['unavailable']} |", file=out)
        for axis, counts in values["axes"].items():
            cells = [
                str(counts[k])
                for k in (
                    "specified",
                    "adherent",
                    "dominant_conflict",
                    "interpretation_missing",
                )
            ]
            print(f"| {arm} | {axis} | " + " | ".join(cells) + " | |", file=out)


def main(
    argv=None,
    *,
    out=None,
    settings=None,
    assemble=assemble_full,
    single_builder=build_single_arm,
    structured_factory=make_structured,
    chat_fn=chat_complete,
    guard_fn=check_run,
    check=_preflight,
    workspace_loader=load_workspaces,
    environ=None,
    env_file=DEFAULT_ENV_FILE,
):
    out = sys.stdout if out is None else out
    parser = _Arguments(description=__doc__)
    parser.add_argument("command", choices=("run", "score", "sheet", "report"))
    parser.add_argument("--mode", choices=("dev", "final"), default="dev")
    parser.add_argument("--arms", default=",".join(ARMS_DEFAULT))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--requests", type=Path)
    try:
        args = parser.parse_args(argv)
        args.arms = args.arms.split(",")
        if (
            not args.arms
            or set(args.arms) - set(ARMS_DEFAULT)
            or len(set(args.arms)) != len(args.arms)
            or args.limit is not None
            and (args.limit < 1 or args.mode == "final")
            or args.mode == "final"
            and args.requests is not None
            or args.run_id is not None
            and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", args.run_id)
        ):
            raise _Stopped("ARGUMENT_ERROR")
        if args.budget_usd is None:
            args.budget_usd = DEFAULT_BUDGET_USD[args.mode]
        if not math.isfinite(args.budget_usd) or args.budget_usd <= 0:
            raise _Stopped("ARGUMENT_ERROR")
        if args.mode == "dev" and args.budget_usd > DEFAULT_BUDGET_USD["dev"]:
            raise _Stopped("DEV_BUDGET_INVALID")
        # This must precede request/record access, workspace loading and services
        # for EVERY final subcommand (including dry-run, sheet and report).
        identity = None
        if args.mode == "final":
            identity = guard_fn(mode="final", groups={"test"}, extra=_extra_frozen())
        request_path = args.requests or REQUESTS_PATH
        raw = read_jsonl(request_path)
        split = "dev" if args.mode == "dev" else "test"
        selected = raw if args.requests else [r for r in raw if r.get("split") == split]
        items = [RequestItem.model_validate(r) for r in selected]
        groups = {w.tenant_id: w.group for w in workspace_loader(WORKSPACES_PATH)}
        if args.mode == "dev":
            identity = guard_fn(
                mode="dev",
                groups={r.split for r in items}
                | {groups.get(r.tenant_id) for r in items},
                extra=_extra_frozen(),
            )
        if any(r.split != split or groups.get(r.tenant_id) != split for r in items):
            raise FreezeError("WORKSPACE_GROUP_INVALID")
        if not items or len({r.id for r in items}) != len(items):
            raise _Stopped("REQUEST_SET_INVALID")
        set_hash = identity.request_hash or request_set_hash(items)
        items = items[: args.limit]
        if args.run_id is None:
            if args.command != "run" and not args.dry_run:
                raise _Stopped("RUN_ID_REQUIRED")
            args.run_id = uuid4().hex
        root = RESULT_ROOT / args.run_id
        metadata_path = root / "run.json"
        rows = _load_records(root)
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            expected = metadata["identity"]
            if (
                metadata["mode"] != args.mode
                or metadata["evalset_hash"] != set_hash
                or expected["code_commit"] != identity.code_commit
                or expected["prereg_commit"] != identity.prereg_commit
            ):
                raise _Stopped("RUN_IDENTITY_MISMATCH")
            by_id = {r.id: r for r in items}
            items = [by_id[i] for i in metadata["item_ids"]]
        else:
            if rows or args.command != "run" and not args.dry_run:
                raise _Stopped("RUN_METADATA_MISSING")
            metadata = {
                "mode": args.mode,
                "identity": asdict(identity),
                "evalset_hash": set_hash,
                "item_ids": [r.id for r in items],
                "scoring_spent_usd": 0.0,
            }
        if any(
            r.run_id != args.run_id
            or r.evalset_hash != set_hash
            or r.code_commit != (identity.code_commit or "unavailable")
            or r.prereg_commit != identity.prereg_commit
            or r.item_id not in {i.id for i in items}
            or r.tenant_id != next(i.tenant_id for i in items if i.id == r.item_id)
            for r in rows
        ):
            raise _Stopped("RUN_IDENTITY_MISMATCH")
        if args.dry_run:
            count = len(items) * len(args.arms)
            scoring_count = sum(r.plan is not None for r in rows) if rows else count
            print(
                json.dumps(
                    {
                        "requests": len(items),
                        "arms": args.arms,
                        "request_arm_count": count,
                        "scoring_items": scoring_count,
                        "scoring_calls": scoring_count,
                        "generation_calls_assumed": count * 8,
                        "cost_estimate_usd_assumed": count * 8 * 0.005
                        + scoring_count * 0.01,
                        "note": "호출 수 기준 비용 추정(가정, 미실측): 생성 8회/팔, $0.005/회; 채점 $0.01/회. 구조화 재요청 제외.",
                    },
                    ensure_ascii=False,
                ),
                file=out,
            )
            return 0
        scoring = (
            blind_items(_plain(rows), requests=items)
            if args.command == "score"
            else None
        )
        if scoring is not None:
            if not scoring[0]:
                raise _Stopped("SCORING_EMPTY")
            if args.mode == "dev" and len(scoring[0]) > DEV_SCORE_MAX_ITEMS:
                raise _Stopped("DEV_SCORE_MAX_ITEMS")
        if args.command == "report":
            _report(rows, items, root, metadata, out)
            return 0
        settings = (
            load_settings(environ=environ, env_file=env_file)
            if settings is None
            else settings
        )
        problems = check(
            settings=settings, command=args.command, environ=environ, env_file=env_file
        )
        if problems:
            for problem in problems:
                print("PREFLIGHT_FAILED " + problem, file=out)
            return 2
        if args.command == "run":
            _json_write(metadata_path, metadata)
            return asyncio.run(
                _run_batch(
                    args,
                    items,
                    identity,
                    set_hash,
                    root,
                    rows,
                    settings=settings,
                    assemble=assemble,
                    single_builder=single_builder,
                    chat_fn=chat_fn,
                    structured_factory=structured_factory,
                    environ=environ,
                    env_file=env_file,
                    out=out,
                    prior_score_spend=metadata["scoring_spent_usd"],
                )
            )
        if args.command == "score":
            baseline = ledger_total(settings.ledger_path)
            previous_spend = (
                math.fsum(r.spent_usd for r in rows) + metadata["scoring_spent_usd"]
            )
            if previous_spend >= args.budget_usd:
                raise _Stopped("BUDGET_REACHED")

            def budget_guard():
                if (
                    previous_spend + ledger_total(settings.ledger_path) - baseline
                    >= args.budget_usd
                ):
                    raise CostCapExceeded(
                        "purpose:e2-score-run", args.budget_usd, args.budget_usd
                    )

            structured = _ConfiguredStructured(
                structured_factory(_SCORING_MODEL),
                _call_options(
                    settings, _SCORING_MODEL, environ=environ, env_file=env_file
                ),
                budget_guard,
            )
            if structured.model != _SCORING_MODEL:
                raise _Stopped("SCORING_MODEL_INVALID")
            scores = score_plans(
                scoring[0], structured=structured, ledger_path=settings.ledger_path
            )
            metadata["scoring_spent_usd"] += (
                ledger_total(settings.ledger_path) - baseline
            )
            _json_write(metadata_path, metadata)
            _json_write(root / "scores.json", reveal_scores(scores, scoring[1]))
            return 0 if all(s["status"] == "scored" for s in scores) else 2

        async def sheet():
            assembly = await assemble(
                settings=settings,
                group=split,
                limits=RequestLimits(),
                environ=environ,
                env_file=env_file,
            )
            try:
                ids = {
                    eid
                    for r in rows
                    if r.plan
                    for eid in r.plan.get("evidence_ids") or []
                }
                texts = {
                    card.get("evidence_id"): " · ".join(
                        value
                        for key in ("title", "brand")
                        if isinstance(value := card.get(key), str)
                    )
                    for card in assembly.hydrate(sorted(ids))
                }
                build_claim_sheet(
                    _plain(rows), evidence_texts=texts, seed=SCORING_SEED, out_dir=root
                )
            finally:
                await _close(assembly)

        asyncio.run(sheet())
        return 0
    except (FreezeError, _Stopped) as error:
        print(error.code, file=out)
        return 2
    except SettingError as error:
        print("PREFLIGHT_FAILED " + error.code + ":" + error.name, file=out)
        return 2
    except Exception as error:  # noqa: BLE001 -- no paths, provider bodies or exception prose
        print("E2E5_FAILED " + type(error).__name__, file=out)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
