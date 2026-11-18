"""User-run P5 development comparisons; defaults never change as a side effect."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from beautyads.agents.evaluation import evaluate_plan
from beautyads.agents.lookups import (
    GraphCertLookup,
    GraphEfficacySupport,
    GraphEvidenceIndex,
)
from beautyads.agents.planning import make_plan
from beautyads.agents.research import run_research
from beautyads.agents.tools import run_tool
from beautyads.checks.plan_checks import run_checks
from beautyads.domain.evaluation import EvaluationScores
from beautyads.domain.plan import Plan
from beautyads.domain.research import ResearchBrief, ResearchHandoff
from beautyads.domain.tenant import price_band
from beautyads.domain.tools import ToolContext
from beautyads.eval.cq_verify import cq_preflight
from beautyads.graph.connection import connect_graph
from beautyads.llm.chat import cache_system_block, chat_complete
from beautyads.llm.prices import _usage_tokens
from beautyads.llm.structured import (
    JsonSchemaStructured,
    NativeAnthropicStructured,
    ToolCallStructured,
)
from beautyads.obs.ledger import CostCapExceeded, check_purpose_cap, purpose_total
from beautyads.pipeline.preflight import docker_running, tcp_reachable
from beautyads.settings import (
    DEFAULT_ENV_FILE,
    SettingError,
    get_setting,
    load_settings,
)
from beautyads.sources.claim_rules import load_claim_rules

PREREG_PATH = Path("docs/results/p5_dev_compare_preregistration.md")
OUTPUT_ROOT = Path("data/interim/p5_compare")
PURPOSE_CAPS = {"compare-inputs": 0.02, "compare-terra": 0.12, "compare-sonnet": 0.10}
HARD_CAPS = {"gemini": 12.0, "openai": 10.0, "anthropic": 8.0}
EFFORTS = ("none", "low", "medium")
MIN_USABLE = 3
SONNET_SAMPLE = 6
SCORE_REVIEW_THRESHOLD = 1.0
PROFILES = {
    "mixsoon": {
        "brand": "mixsoon",
        "own_product_url": "https://mixsoon.co.kr/product/detail.html?product_no=921",
        "tone": "",
        "forbidden_terms": [],
    },
    "cosrx": {
        "brand": "cosrx",
        "own_product_url": "https://www.cosrx.co.kr/product/%EC%9A%B8%ED%8A%B8%EB%9D%BC-%EB%9D%BC%EC%9D%B4%ED%8A%B8-%EC%9D%B8%EB%B9%84%EC%A0%80%EB%B8%94-%EC%84%A0%EC%84%B8%EB%9F%BC-50ml/740/category/57/display/1/",
        "tone": "",
        "forbidden_terms": [],
    },
}
BRIEFS = tuple(
    ResearchBrief(goal=goal, category=category, claim=claim, output="both").model_dump(
        mode="json"
    )
    for category, claim, goal in (
        ("serum_ampoule", "soothing", "진정 소구 세럼의 경쟁 광고 근거를 수집한다"),
        ("serum_ampoule", "hydration", "보습 소구 세럼의 경쟁 광고 근거를 수집한다"),
        ("serum_ampoule", "brightening", "미백 소구 세럼의 경쟁 광고 근거를 수집한다"),
        (
            "sun_care",
            "sun_protection",
            "자외선 차단 소구 선케어의 경쟁 광고 근거를 수집한다",
        ),
        ("sun_care", "soothing", "진정 소구 선케어의 경쟁 광고 근거를 수집한다"),
    )
)


class CompareStopped(Exception):
    """Only internally defined codes may cross the CLI boundary."""


def preregistration_committed(path=PREREG_PATH, *, run=subprocess.run):
    try:
        options = {"capture_output": True, "text": True, "timeout": 5, "check": False}
        history = run(["git", "log", "-1", "--", str(path)], **options)
        status = run(["git", "status", "--porcelain", "--", str(path)], **options)
        return (
            history.returncode == status.returncode == 0
            and bool(history.stdout.strip())
            and not status.stdout.strip()
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


def _commit_hash():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        value = result.stdout.strip()
        return (
            value
            if result.returncode == 0 and re.fullmatch(r"[a-f0-9]{40,64}", value)
            else None
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def preflight(
    command, *, environ, env_file, docker_check=docker_running, tcp_check=tcp_reachable
):
    key_name = "ANTHROPIC_API_KEY" if command == "sonnet" else "OPENAI_API_KEY"
    if get_setting(key_name, environ=environ, env_file=env_file) is None:
        return f"ENV_MISSING:{key_name}"
    return cq_preflight(
        environ=environ,
        env_file=env_file,
        docker_check=docker_check,
        tcp_check=tcp_check,
    )


def usable_plan(plan, report, pool):
    ids = plan.get("evidence_ids") or []
    return bool(report.get("passed") and ids and set(ids) <= set(pool))


def decide_terra(metrics):
    if all(metrics[effort]["usable"] < MIN_USABLE for effort in EFFORTS):
        return {"decision": "보류", "selected": None}
    chosen = min(
        EFFORTS,
        key=lambda effort: (
            -metrics[effort]["usable"],
            metrics[effort]["structured_failures"],
            EFFORTS.index(effort),
        ),
    )
    return {"decision": "권고", "selected": chosen}


def failure_rates(rows):
    count = len(rows)
    return {
        "first_failure_rate": sum(row["attempts"] > 1 or not row["ok"] for row in rows)
        / count
        if count
        else None,
        "final_failure_rate": sum(not row["ok"] for row in rows) / count
        if count
        else None,
    }


def decide_sonnet(a, b, score_difference_mean):
    return {
        "recommended": "b" if b < a else "a",
        "review": score_difference_mean is not None
        and score_difference_mean > SCORE_REVIEW_THRESHOLD,
    }


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_bytes(value):
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()


def _value_hash(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def select_plans(paths):
    return sorted(paths, key=lambda path: (file_hash(path), path.name))[:SONNET_SAMPLE]


def _write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(_json_bytes(value))


def save_plan(path, value):
    # No request/response envelope or provider extension may enter a plan artifact.
    clean = Plan.model_validate({key: value.get(key) for key in Plan.model_fields})
    _write_new(path, clean.model_dump(mode="json"))


def _load_inputs(root, prereg_path):
    # Only the explicitly appendable hash section is read. Experimental parameters
    # above are constants, never extracted from the preregistration document.
    try:
        sections = prereg_path.read_text(encoding="utf-8").split("## 7.", 1)
    except OSError:
        raise CompareStopped("INPUT_HASH_MISMATCH") from None
    if len(sections) != 2:
        raise CompareStopped("INPUT_HASH_MISMATCH")
    section = sections[1].split("\n## ", 1)[0]
    hashes = {}
    for line in section.splitlines():
        match = re.fullmatch(
            r"\s*[-|]?\s*`?((?:0[1-5])\.json)`?\s*[| :]\s*`?([a-f0-9]{64})`?\s*\|?\s*",
            line,
        )
        if match:
            name, digest = match.groups()
            if name in hashes:
                raise CompareStopped("INPUT_HASH_MISMATCH")
            hashes[name] = digest
    paths = [root / "inputs" / f"{index:02}.json" for index in range(1, 6)]
    if any(
        not path.is_file() or hashes.get(path.name) != file_hash(path) for path in paths
    ):
        raise CompareStopped("INPUT_HASH_MISMATCH")
    return [
        ResearchHandoff.model_validate_json(path.read_bytes()).model_dump(mode="json")
        for path in paths
    ], paths


def default_structured_factory(model, style, guard):
    base = (
        (NativeAnthropicStructured if style == "native" else ToolCallStructured)
        if model.startswith("claude-")
        else JsonSchemaStructured
    )

    class Guarded(base):
        def _complete(self, spec, messages, options):
            # Also runs before the single structured correction. Transport retries
            # have no intervening paid response; supplier checks remain in llm/.
            guard()
            return super()._complete(spec, messages, options)

    return Guarded(model)


class _ConfiguredStructured:
    """Inject comparison options without touching production agent constants."""

    def __init__(self, model, style, effort, runtime):
        self.model, self.effort, self.runtime = model, effort, runtime
        self.inner = runtime.structured_factory(model, style, runtime.guard)
        self.last = None
        self.request_sha256 = None

    @property
    def stats(self):
        return self.inner.stats

    def generate(self, spec, **options):
        self.runtime.guard()
        options.update(self.runtime.options(self.model, self.effort))
        if self.model.startswith("claude-"):
            # Same fixed system prefix for both arms; preserve native cache blocks.
            options["messages"] = [
                {**message, "content": cache_system_block(message["content"])}
                if message.get("role") == "system"
                and isinstance(message.get("content"), str)
                else message
                for message in options["messages"]
            ]
            options["messages"] = [
                {**message, "content": [message["content"]]}
                if isinstance(message.get("content"), dict)
                else message
                for message in options["messages"]
            ]
        self.request_sha256 = _value_hash(
            {"messages": options["messages"], "schema": spec.schema}
        )
        result = self.inner.generate(spec, **options)
        self.last = result
        self.runtime.record_calls(self.model, result.calls)
        # Never retain calls' text, raw responses, reasons, or tool arguments.
        return result


def _metrics(generator):
    result = generator.last
    if result is None:
        return {
            "ok": False,
            "attempts": 0,
            "cost_usd": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "thought_tokens": 0,
            "cached_tokens": 0,
            "calls": [],
        }
    calls = [_call_metrics(generator.model, call) for call in result.calls]
    return {
        "ok": result.ok,
        "attempts": result.attempts,
        "cost_usd": result.cost_usd,
        **{
            key: sum(call[key] for call in calls)
            for key in (
                "input_tokens",
                "output_tokens",
                "thought_tokens",
                "cached_tokens",
            )
        },
        "calls": calls,
    }


def _call_metrics(model, call):
    tokens = _usage_tokens(model, call.usage)
    return {
        "input_tokens": tokens.total_input,
        "output_tokens": tokens.output,
        "cached_tokens": tokens.read,
        "thought_tokens": (call.usage.get("completion_tokens_details") or {}).get(
            "reasoning_tokens"
        )
        or 0,
        "cost_usd": call.cost_usd,
    }


class _Runtime:
    def __init__(self, *, command, settings, environ, env_file, structured_factory):
        self.purpose = f"compare-{command}"
        self.settings, self.environ, self.env_file = settings, environ, env_file
        self.structured_factory = structured_factory
        self.calls = []
        self.caps = {
            key: min(value, settings.provider_caps_usd[key])
            for key, value in HARD_CAPS.items()
        }

    def guard(self):
        try:
            check_purpose_cap(
                self.settings.ledger_path, self.purpose, PURPOSE_CAPS[self.purpose]
            )
        except CostCapExceeded:
            raise CompareStopped("PURPOSE_CAP_REACHED") from None

    def options(self, model, effort):
        key_name = (
            "ANTHROPIC_API_KEY" if model.startswith("claude-") else "OPENAI_API_KEY"
        )
        return {
            "purpose": self.purpose,
            "ledger_path": self.settings.ledger_path,
            "caps": self.caps,
            "reasoning_effort": effort,
            "max_tokens": 4096,
            "api_key": get_setting(
                key_name, environ=self.environ, env_file=self.env_file
            ),
        }

    def structured(self, model, *, style="default", effort=None):
        return _ConfiguredStructured(model, style, effort, self)

    def record_calls(self, model, calls):
        self.calls.extend(_call_metrics(model, call) for call in calls)

    def chat(self, **options):
        self.guard()
        options.update(self.options("gpt-6-luna", "none"))
        result = chat_complete(**options)
        self.record_calls("gpt-6-luna", [result])
        return result


def _profile(index):
    return PROFILES["mixsoon" if index < 3 else "cosrx"]


def _check_options(graph, rules):
    return {
        "rules": rules,
        "evidence_index": GraphEvidenceIndex(graph),
        "support": GraphEfficacySupport(graph),
        "certs": GraphCertLookup(graph),
    }


def _inputs(root, graph, runtime, rows, research_fn, now):
    for index, brief in enumerate(BRIEFS):
        start = len(runtime.calls)
        profile = _profile(index)
        # A fixed, bound read of existing derived facts; never fetch product media.
        records = graph.run(
            "MATCH (p:Product {brand: $brand, source_url: $url}) RETURN p.unit_list_price AS unit_list_price",
            {"brand": profile["brand"], "url": profile["own_product_url"]},
        ).records
        price = next(
            (
                row.get("unit_list_price")
                for row in records
                if row.get("unit_list_price") is not None
            ),
            None,
        )
        if price is None:
            raise CompareStopped("PRODUCT_PRICE_MISSING")
        ctx = ToolContext(
            tenant_id=f"compare-{profile['brand']}",
            as_of=now.date(),
            price_band=price_band(float(price), 30),
        )
        runtime.guard()
        generator = runtime.structured("gpt-6-luna", effort="none")
        value = research_fn(
            brief,
            ctx=ctx,
            chat=runtime.chat,
            tool_runner=partial(run_tool, graph=graph),
            structured=generator,
        )
        handoff = ResearchHandoff.model_validate(value).model_dump(mode="json")
        path = root / "inputs" / f"{index + 1:02}.json"
        _write_new(path, handoff)
        rows.append(
            {
                "input": index + 1,
                "output_sha256": file_hash(path),
                "input_sha256": _value_hash(brief),
                "calls": runtime.calls[start:],
                **{
                    key: sum(call[key] for call in runtime.calls[start:])
                    for key in (
                        "cost_usd",
                        "input_tokens",
                        "output_tokens",
                        "thought_tokens",
                        "cached_tokens",
                    )
                },
            }
        )


def _terra(root, handoffs, paths, graph, runtime, rules, rows):
    metrics = {}
    for effort in EFFORTS:
        group = []
        for index, (brief, handoff) in enumerate(zip(BRIEFS, handoffs, strict=True)):
            runtime.guard()
            generator = runtime.structured("gpt-6.1-terra", effort=effort)
            result = make_plan(
                brief=brief,
                handoff=handoff,
                profile=_profile(index),
                feedback=None,
                rework=None,
                structured=generator,
            )
            row = {
                "input": index + 1,
                "effort": effort,
                **_metrics(generator),
                "input_sha256": file_hash(paths[index]),
                "request_sha256": generator.request_sha256,
                "output_sha256": None,
                "usable": False,
                "unknown_count": None,
            }
            if result.ok:
                plan = Plan.model_validate(result.plan)
                report = run_checks(
                    plan,
                    handoff_evidence_ids=handoff["evidence_ids"],
                    **_check_options(graph, rules),
                )
                path = root / "plans" / f"{index + 1:02}-{effort}.json"
                save_plan(path, plan.model_dump(mode="json"))
                row.update(
                    output_sha256=file_hash(path),
                    usable=usable_plan(
                        result.plan, report.model_dump(), handoff["evidence_ids"]
                    ),
                    unknown_count=report.unknown_count,
                    rule_count=report.rule_count,
                )
            rows.append(row)
            group.append(row)
        unknowns = [
            row["unknown_count"] for row in group if row["unknown_count"] is not None
        ]
        metrics[effort] = {
            "usable": sum(row["usable"] for row in group),
            "structured_failures": sum(not row["ok"] for row in group),
            "cost_per_call": sum(row["cost_usd"] for row in group) / len(group),
            "thought_tokens_per_call": sum(row["thought_tokens"] for row in group)
            / len(group),
            "unknown_count_mean": sum(unknowns) / len(unknowns) if unknowns else None,
        }
    return {"metrics": metrics, "decision": decide_terra(metrics)}


def _sonnet(selected, handoffs, paths, graph, runtime, rules, rows):
    scores, groups = {}, {}
    # Consecutive calls within each arm keep the fixed system/schema prefix.
    # Crossing from (a) to (b) changes the output format; record observed cache
    # reads only, without inferring cache invalidation from an absent hit.
    for arm, style in (("a", "default"), ("b", "native")):
        group = []
        for path in selected:
            index = int(path.name[:2]) - 1
            plan = Plan.model_validate_json(path.read_bytes()).model_dump(mode="json")
            runtime.guard()
            generator = runtime.structured("claude-sonnet-5-5", style=style)
            report = evaluate_plan(
                plan=plan,
                brief=BRIEFS[index],
                handoff=handoffs[index],
                structured=generator,
                model="claude-sonnet-5-5",
                **_check_options(graph, rules),
            )
            numeric_scores = None
            if report.scores is not None:
                validated = EvaluationScores.model_validate(report.scores)
                numeric_scores = [validated.differentiation, validated.fit]
            scores[arm, path.name] = numeric_scores
            row = {
                "arm": arm,
                "plan_sha256": file_hash(path),
                "input_sha256": file_hash(paths[index]),
                "request_sha256": generator.request_sha256,
                "output_sha256": _value_hash(generator.last.value)
                if generator.last.ok
                else None,
                "scores": numeric_scores,
                **_metrics(generator),
            }
            rows.append(row)
            group.append(row)
        groups[arm] = {
            "count": len(group),
            **failure_rates(group),
            "input_tokens_per_call": sum(row["input_tokens"] for row in group)
            / len(group),
            "cost_per_call": sum(row["cost_usd"] for row in group) / len(group),
        }
    pairs = [
        (scores["a", path.name], scores["b", path.name])
        for path in selected
        if scores["a", path.name] is not None and scores["b", path.name] is not None
    ]
    difference = (
        sum(
            abs(a - b)
            for left, right in pairs
            for a, b in zip(left, right, strict=True)
        )
        / (2 * len(pairs))
        if pairs
        else None
    )
    exact = sum(left == right for left, right in pairs) / len(pairs) if pairs else None
    return {
        "metrics": groups,
        "paired_count": len(pairs),
        "score_difference_mean": difference,
        "score_exact_match_rate": exact,
        "decision": decide_sonnet(
            groups["a"]["final_failure_rate"],
            groups["b"]["final_failure_rate"],
            difference,
        ),
    }


def _publish(root, command, report, out, now):
    _write_new(root / f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{command}.json", report)
    # One table, built exclusively from fixed labels, numbers, and digests.
    print(
        "| input/plan | arm | output sha256 | cost USD | input tokens | reasoning | cache read |",
        file=out,
    )
    print("|---|---|---|---:|---:|---:|---:|", file=out)
    for row in report["rows"]:
        print(
            f"| {row.get('plan_sha256', row.get('input'))} | {row.get('effort', row.get('arm', '-'))} | {row.get('output_sha256') or '-'} | {row.get('cost_usd', 0):.8f} | {row.get('input_tokens', 0)} | {row.get('thought_tokens', 0)} | {row.get('cached_tokens', 0)} |",
            file=out,
        )
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "rows"},
            ensure_ascii=False,
        ),
        file=out,
    )
    if report.get("decision", {}).get("review"):
        print("검토 표시", file=out)


def main(
    argv=None,
    *,
    environ=None,
    out=None,
    root=OUTPUT_ROOT,
    prereg_path=PREREG_PATH,
    prereg_check=preregistration_committed,
    check=preflight,
    settings=None,
    graph_factory=None,
    structured_factory=default_structured_factory,
    research_fn=run_research,
    rules_loader=None,
    now=None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inputs", "terra", "sonnet"))
    args = parser.parse_args(argv)
    out = sys.stdout if out is None else out
    root, prereg_path = Path(root), Path(prereg_path)
    if not prereg_check(prereg_path):
        print("PREREGISTRATION_NOT_COMMITTED", file=out)
        return 2
    env_file = DEFAULT_ENV_FILE if environ is None else None
    graph, report = None, None
    timestamp = datetime.now(UTC) if now is None else now()
    status = 0
    try:
        problem = check(command=args.command, environ=environ, env_file=env_file)
        if problem:
            safe_codes = {
                "ENV_MISSING:OPENAI_API_KEY",
                "ENV_MISSING:ANTHROPIC_API_KEY",
                "ENV_MISSING:NEO4J_PASSWORD",
                "INVALID_SETTING:NEO4J_PASSWORD",
                "DOCKER_DOWN",
                "NEO4J_UNREACHABLE",
            }
            print(
                f"PREFLIGHT_FAILED {problem if problem in safe_codes else 'CONFIG_INVALID'}",
                file=out,
            )
            return 2
        settings = (
            load_settings(environ=environ, env_file=env_file)
            if settings is None
            else settings
        )
        runtime = _Runtime(
            command=args.command,
            settings=settings,
            environ=environ,
            env_file=env_file,
            structured_factory=structured_factory,
        )
        runtime.guard()
        if args.command == "inputs":
            if (root / "inputs").exists() and any((root / "inputs").iterdir()):
                raise CompareStopped("INPUTS_EXIST")
        else:
            handoffs, paths = _load_inputs(root, prereg_path)
            if (
                args.command == "terra"
                and (root / "plans").exists()
                and any((root / "plans").iterdir())
            ):
                raise CompareStopped("PLANS_EXIST")
            if args.command == "sonnet":
                plans = list((root / "plans").glob("*.json"))
                if any(
                    not re.fullmatch(r"0[1-5]-(none|low|medium)\.json", path.name)
                    for path in plans
                ):
                    raise CompareStopped("PLAN_INPUT_INVALID")
                if len(plans) < SONNET_SAMPLE:
                    raise CompareStopped("PLANS_INSUFFICIENT")
                selected = select_plans(plans)
                for path in selected:
                    Plan.model_validate_json(path.read_bytes())
        graph = (
            graph_factory()
            if graph_factory
            else connect_graph(environ=environ, env_file=env_file)
        )
        rules = (
            (
                rules_loader()
                if rules_loader
                else load_claim_rules(Path("config/claim_rules.yaml"))
            )
            if args.command != "inputs"
            else []
        )
        report = {
            "command": args.command,
            "date": timestamp.isoformat(),
            "commit_hash": _commit_hash(),
            "models": [
                "gpt-6-luna"
                if args.command == "inputs"
                else "gpt-6.1-terra"
                if args.command == "terra"
                else "claude-sonnet-5-5"
            ],
            "with_image": False,
            "rows": [],
            "complete": False,
            "limitations": [
                "경쟁 소재 검색은 전 브랜드 대상이며 test 브랜드 소재가 포함될 수 있다.",
                "개발 기본값 참고용이며 E1~E5 실험이나 통계적 근거가 아니다.",
            ],
        }
        if args.command == "inputs":
            _inputs(root, graph, runtime, report["rows"], research_fn, timestamp)
        elif args.command == "terra":
            report.update(
                _terra(root, handoffs, paths, graph, runtime, rules, report["rows"])
            )
        else:
            report.update(
                _sonnet(
                    selected, handoffs, paths, graph, runtime, rules, report["rows"]
                )
            )
        report["complete"] = True
    except CompareStopped as error:
        print(str(error), file=out)
        status = 2
    except (SettingError, CostCapExceeded):
        print("PREFLIGHT_FAILED COST_OR_SETTING", file=out)
        status = 2
    except Exception as error:  # noqa: BLE001 -- model/graph/validation exceptions can contain secrets and full plans
        code = getattr(error, "code", None)
        code = (
            code
            if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_:]{1,64}", code)
            else None
        )
        detail = type(error).__name__
        print(
            "COMPARE_FAILED"
            + (f" error_code={code}" if code is not None else "")
            + f" detail={detail}",
            file=out,
        )
        if report is not None:
            report["error"] = {"code": code, "detail": detail}
        status = 3
    finally:
        if graph is not None:
            try:
                graph.close()
            except Exception:  # noqa: BLE001, S110 -- close errors may contain credentials
                pass
        if report is not None:
            try:
                report["ledger_cost_usd"] = purpose_total(
                    settings.ledger_path, f"compare-{args.command}"
                )
                _publish(root, args.command, report, out, timestamp)
            except Exception:  # noqa: BLE001 -- file errors must not echo payloads
                print("RESULT_WRITE_FAILED", file=out)
                status = 3
    return status


if __name__ == "__main__":
    raise SystemExit(main())
