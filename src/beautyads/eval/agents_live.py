"""User-run P5 dev-workspace batch; dry-run and injected tests make no calls."""

import argparse
import json
import math
import re
import sys
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from uuid import uuid4

from beautyads.api.app import create_app
from beautyads.api.assembly import assemble_full
from beautyads.api.chat_client import run_ask_once
from beautyads.domain.supervisor import RequestLimits
from beautyads.eval.live_agent import preflight
from beautyads.obs.ledger import provider_total, purpose_total
from beautyads.obs.trace import read_traces
from beautyads.settings import SettingError, get_setting, load_settings
from beautyads.sources.workspaces import load_workspaces

OUTPUT_ROOT = Path("data/interim/agents_live")
RUN_CAPS = {"openai": 0.7, "anthropic": 0.6, "image": 0.2}
SCENARIOS = (
    {
        "id": "serum-pattern",
        "tenant_id": "dev-mixsoon",
        "kind": "pattern",
        "message": "세럼 광고에서 자주 쓰는 훅 패턴과 근거를 알려줘.",
    },
    {
        "id": "ingredient-relation",
        "tenant_id": "dev-mixsoon",
        "kind": "relation",
        "message": "병풀 성분을 내세운 광고는 어떤 소구점과 포맷으로 연결돼?",
    },
    {
        "id": "serum-plan",
        "tenant_id": "dev-mixsoon",
        "kind": "plan",
        "message": "믹순 세럼의 보습을 알리는 광고 기획안 1개를 근거와 함께 만들어줘.",
    },
    {
        "id": "sun-care-plan",
        "tenant_id": "dev-cosrx",
        "kind": "plan",
        "message": "코스알엑스 선케어 광고 기획안 1개를 근거와 함께 만들어줘.",
    },
    {
        "id": "unsupported-category",
        "tenant_id": "dev-mixsoon",
        "kind": "boundary",
        "message": "헤어 샴푸 광고의 주요 패턴을 알려줘.",
    },
)
_CONFIGS = {
    "dev": ("claude-haiku-5-5", False),
    "official": ("claude-sonnet-5-5", False),
    "image": ("claude-sonnet-5-5", True),
}
_STOP_CODES = {"DAILY_LIMIT", "RATE_LIMIT", "HTTP_429", "CREDITS_DEPLETED"}


class _ArgumentError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse diagnostics normally repeat raw arguments, which may be secrets.
        raise _ArgumentError


def select_scenarios(config):
    selected = [s for s in SCENARIOS if config == "dev" or s["kind"] == "plan"]
    return selected[:1] if config == "image" else selected


def _preflight(*, with_image):
    problems = preflight()
    if problems:
        return problems
    names = ["ANTHROPIC_API_KEY"] + (["GEMINI_API_KEY"] if with_image else [])
    return [f"ENV_MISSING:{name}" for name in names if get_setting(name) is None]


def _totals(settings):
    return {
        "openai": provider_total(settings.ledger_path, "openai"),
        "anthropic": provider_total(settings.ledger_path, "anthropic"),
        "image": purpose_total(settings.ledger_path, "image"),
    }


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _baseline(current, started_at, *, reset):
    path = OUTPUT_ROOT / "baseline.json"
    if reset or not path.exists():
        value = {
            "created_at": started_at.isoformat(),
            "provider_totals": {p: current[p] for p in ("openai", "anthropic")},
            "image_total": current["image"],
        }
        _write_json(path, value)
        return current.copy()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        created = datetime.fromisoformat(value["created_at"])
        totals = {p: value["provider_totals"][p] for p in ("openai", "anthropic")}
        totals["image"] = value["image_total"]
        if created.utcoffset() is None or any(
            type(amount) not in (int, float) or not math.isfinite(amount) or amount < 0
            for amount in totals.values()
        ):
            raise ValueError
        if any(totals[p] > current[p] for p in RUN_CAPS):
            raise ValueError
        return totals
    except (ValueError, KeyError, TypeError, OverflowError):
        # Never silently replace a corrupt baseline with a fresh allowance.
        raise SettingError("baseline", "BUDGET_BASELINE_INVALID") from None


def _budget(current, baseline):
    used = {p: max(0.0, round(current[p] - baseline[p], 12)) for p in RUN_CAPS}
    return {
        "used": used,
        "caps": RUN_CAPS.copy(),
        "remaining": {
            p: max(0.0, round(cap - used[p], 12)) for p, cap in RUN_CAPS.items()
        },
    }


def _code(value):
    return (
        value
        if isinstance(value, str)
        and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}(?::[a-z_]{1,32})?", value)
        else None
    )


def _provider(call):
    # TraceCall intentionally stores model metadata without ledger provider fields.
    model = call.model.rsplit("/", 1)[-1]
    if model.startswith("gpt-"):
        return "openai"
    if model.startswith("claude-"):
        return "anthropic"
    if model.startswith("gemini-"):
        return "gemini"
    return "unknown"


def _trace_fields(record):
    costs = {}
    for call in record.calls:
        provider = _provider(call)
        costs[provider] = math.fsum((costs.get(provider, 0), call.cost_usd))
    return {
        "trace_id": record.trace_id,
        "plans": [
            plan.model_dump(exclude={"attempts"})
            | {
                "attempts": [
                    attempt.model_dump(exclude={"cost_usd"})
                    for attempt in plan.attempts
                ]
            }
            for plan in record.plans
        ],
        "limit_hit": record.limit_hit,
        "limit_kinds": record.limit_kinds,
        "cost_by_provider": costs,
        "duration_ms": record.duration_ms,
    }


def _structured(records):
    by_model = {}
    for record in records:
        for model, stats in record.structured.items():
            target = by_model.setdefault(
                model,
                {"calls": 0, "failed_after_retry": 0, "first_attempt_failures": {}},
            )
            target["calls"] += stats.calls
            target["failed_after_retry"] += stats.failed_after_retry
            for kind, count in stats.first_attempt_failures.items():
                failures = target["first_attempt_failures"]
                failures[kind] = failures.get(kind, 0) + count
    calls = sum(stats["calls"] for stats in by_model.values())
    failures = {}
    for stats in by_model.values():
        for kind, count in stats["first_attempt_failures"].items():
            failures[kind] = failures.get(kind, 0) + count
    return {
        "by_model": by_model,
        "calls": calls,
        "failed_after_retry": sum(s["failed_after_retry"] for s in by_model.values()),
        "first_attempt_failures": failures,
        "sample_too_small": calls < 20,
    }


def _request(scenario, *, run, app, with_image):
    row = {key: scenario[key] for key in ("id", "tenant_id", "kind")}
    row.update(
        status_code=None,
        event_names=[],
        error_code=None,
        trace_id=None,
        plans=[],
        limit_hit=False,
        limit_kinds=[],
        cost_by_provider={},
        duration_ms=0,
    )
    try:
        outcome = run(
            app,
            tenant_id=scenario["tenant_id"],
            message=scenario["message"],
            with_image=with_image,
        )
        row["status_code"] = outcome.status_code
        row["event_names"] = [
            name
            for name, _ in outcome.events
            if name in {"step", "tool_start", "ui_command", "token", "error"}
        ]
        if outcome.status_code != 200:
            row["error_code"] = f"HTTP_{outcome.status_code}"
        else:
            error = next(
                (body for name, body in outcome.events if name == "error"), None
            )
            if error is not None:
                row["error_code"] = (
                    _code(error.get("error_code"))
                    or _code(error.get("code"))
                    or "REQUEST_FAILED"
                )
    except SettingError:
        raise
    except Exception as exc:  # noqa: BLE001 -- no exception messages cross the summary boundary
        row["error_code"] = (
            "HTTP_429"
            if getattr(exc, "status_code", None) == 429
            else _code(getattr(exc, "code", None)) or "REQUEST_FAILED"
        )
    return row


def main(
    argv=None,
    *,
    out=None,
    check=None,
    run=None,
    settings=None,
    assemble=None,
    clock=None,
) -> int:
    out = sys.stdout if out is None else out
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--config", choices=tuple(_CONFIGS), required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset-baseline", action="store_true")
    parser.add_argument("--only", action="append", default=[])
    try:
        args = parser.parse_args(argv)
        selected = select_scenarios(args.config)
        if set(args.only) - {s["id"] for s in selected}:
            raise _ArgumentError
        if args.only:
            selected = [s for s in selected if s["id"] in args.only]
    except _ArgumentError:
        print("ARGUMENT_ERROR", file=out)
        return 2
    model, with_image = _CONFIGS[args.config]
    plan = {
        "config": args.config,
        "evaluation_model": model,
        "with_image": with_image,
        "scenarios": [{k: s[k] for k in ("id", "tenant_id", "kind")} for s in selected],
        "budget": {"caps": RUN_CAPS.copy()},
    }
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False), file=out)
        return 0
    now = (lambda: datetime.now(UTC)) if clock is None else clock
    run = run_ask_once if run is None else run
    assemble = assemble_full if assemble is None else assemble
    try:
        problems = _preflight(with_image=with_image) if check is None else check()
        if problems:
            for code in problems:
                print(f"PREFLIGHT_FAILED {code}", file=out)
            return 2
        settings = load_settings() if settings is None else settings
        dev_tenants = {
            w.tenant_id
            for w in load_workspaces(Path("config/workspaces.yaml"))
            if w.group == "dev"
        }
        if any(s["tenant_id"] not in dev_tenants for s in selected):
            print("PREFLIGHT_FAILED WORKSPACE_GROUP_INVALID", file=out)
            return 2
        started_at = now()
        run_id = started_at.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex
        baseline = _baseline(_totals(settings), started_at, reset=args.reset_baseline)
        trace_path = settings.ledger_path.with_name("traces.jsonl")
        seen = {record.trace_id for record in read_traces(trace_path).records}
        rows, records, pending = [], [], []
        exit_code = 0
        for index, scenario in enumerate(selected):
            budget = _budget(_totals(settings), baseline)
            if any(budget["used"][p] >= cap for p, cap in RUN_CAPS.items()):
                pending = [s["id"] for s in selected[index:]]
                print("STOPPED BUDGET_REACHED", file=out)
                exit_code = 2
                break
            limits = RequestLimits(
                max_text_cost_usd=min(
                    0.30,
                    budget["remaining"]["openai"] + budget["remaining"]["anthropic"],
                )
            )
            request_started = now()
            app = create_app(
                partial(
                    assemble,
                    settings=settings,
                    group="dev",
                    evaluation_model=model,
                    with_image_enabled=with_image,
                    limits=limits,
                )
            )
            row = _request(scenario, run=run, app=app, with_image=with_image)
            ended_at = now()
            row["duration_ms"] = max(
                0, int((ended_at - request_started).total_seconds() * 1000)
            )
            candidates = sorted(
                (
                    record
                    for record in read_traces(trace_path).records
                    if record.trace_id not in seen
                    and record.tenant_id == scenario["tenant_id"]
                    and started_at <= request_started <= record.started_at <= ended_at
                ),
                key=lambda record: record.started_at,
            )
            if candidates:
                record = candidates[0]
                seen.add(record.trace_id)
                records.append(record)
                row.update(_trace_fields(record))
                if record.outcome == "error":
                    row["error_code"] = (
                        _code(record.error_code)
                        or row["error_code"]
                        or "REQUEST_FAILED"
                    )
            rows.append(row)
            if row["error_code"] is not None:
                exit_code = 3
            if row["error_code"] in _STOP_CODES:
                pending = [s["id"] for s in selected[index + 1 :]]
                print(f"STOPPED {row['error_code']}", file=out)
                break
        summary = {
            "run_id": run_id,
            "config": args.config,
            "scenarios": rows,
            "structured": _structured(records),
            "budget": _budget(_totals(settings), baseline),
            "pending": pending,
        }
        _write_json(OUTPUT_ROOT / f"{run_id}.json", summary)
        print(json.dumps(summary, ensure_ascii=False, allow_nan=False), file=out)
        return exit_code
    except SettingError as error:
        print(f"PREFLIGHT_FAILED {error.code}:{error.name}", file=out)
        return 2
    except Exception:  # noqa: BLE001 -- public CLI must not expose paths, DSNs or diagnostics
        print("STOPPED LIVE_AGENTS_FAILED", file=out)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
