"""Report Gemini ledger costs and assumed analysis scenarios, without services."""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from math import fsum, isfinite
from pathlib import Path
from typing import TextIO

from beautyads.obs.ledger import LedgerEntry, provider_total, read_entries
from beautyads.settings import SettingError, load_settings

TAGS = ("minimal", "default")
KINDS = ("content_type", "hook", "full")
METRICS = (
    "input_tokens",
    "output_tokens",
    "thought_tokens",
    "cached_tokens",
    "cost_usd",
)
MEASURED = "측정값"
ASSUMED = "가정(미실측)"
LIMITATION = (
    "시범 표본이 작다({items}건, 소재 길이·제품 비율에 따라 크게 달라질 수 있음). "
    "정확한 종류별 비용은 `analyze-target`의 첫 실행에서 측정한다."
)


def distribution(values: Sequence[int | float]) -> dict | None:
    """Linear-interpolated percentiles at (n-1)*q; an empty group is unknown."""
    if not values:
        return None
    ordered = sorted(values)

    def percentile(q):
        position = (len(ordered) - 1) * q
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    return {
        "mean": fsum(values) / len(values),
        "p50": percentile(0.5),
        "p90": percentile(0.9),
        "max": ordered[-1],
    }


def _summary(entries: Sequence[LedgerEntry]) -> dict:
    estimated = sum(entry.cost_source != "response_cost" for entry in entries)
    return {
        "basis": MEASURED,
        "calls": len(entries),
        "cost_usd": fsum(entry.cost_usd for entry in entries),
        "estimated_cost_entries": estimated,
        "cost_note": "비용 추정치 포함" if estimated else "response_cost 측정값",
        "stats": {
            name: distribution([getattr(entry, name) for entry in entries])
            for name in METRICS
        },
    }


def _cost(summary: dict, statistic: str) -> float | None:
    stats = summary["stats"]["cost_usd"]
    return stats[statistic] if stats is not None else None


def _scenarios(
    content: dict,
    hook: dict,
    full: dict,
    *,
    items: int,
    shares: Sequence[float],
    cumulative: float,
    cap: float,
    candidate: float,
) -> list[dict]:
    result = []
    for share in shares:
        row = {"basis": ASSUMED, "product_share": share}
        for column, statistic in (("mean", "mean"), ("p90", "p90")):
            content_cost = _cost(content, statistic)
            full_cost = _cost(full, statistic)
            hook_cost = _cost(hook, "mean")
            estimate = None
            if content_cost is not None and (
                share == 0 or (full_cost is not None and hook_cost is not None)
            ):
                estimate = items * content_cost
                if share:
                    estimate += items * share * (full_cost + hook_cost)
            total = cumulative + estimate if estimate is not None else None
            row.update(
                {
                    f"{column}_usd": estimate,
                    f"{column}_total_usd": total,
                    # Match obs.ledger.check_cap: equality already stops calls.
                    f"{column}_within_current_cap": total < cap
                    if total is not None
                    else None,
                    f"{column}_within_candidate_cap": total < candidate
                    if total is not None
                    else None,
                }
            )
        result.append(row)
    return result


def recalculate(
    entries: Sequence[LedgerEntry],
    *,
    items: int,
    pilot_items: int,
    hook_input_max: int,
    shares: Sequence[float],
    cumulative: float,
    cap: float,
    candidate: float,
) -> dict:
    """Pure aggregation; the caller supplies the ledger's provider_total."""
    gemini = [entry for entry in entries if entry.provider == "gemini"]
    purposes = {f"pilot-{tag}{suffix}" for tag in TAGS for suffix in ("", "-retry")}
    report = {
        "basis": MEASURED,
        "errors": [],
        "warnings": [],
        "skipped_lines": {"basis": MEASURED, "value": 0},
        "assumptions": {
            "basis": ASSUMED,
            "items": items,
            "pilot_items": pilot_items,
            "hook_input_max": hook_input_max,
            "product_shares": list(shares),
            "note": "items는 content_type 호출 수의 상한. 제품 비율은 시범에서 외삽하지 않음.",
        },
        "budget": {
            "cumulative_usd": {"basis": MEASURED, "value": cumulative},
            "current_cap_usd": {"basis": "가정(현재 설정 상한)", "value": cap},
            "candidate_cap_usd": {"basis": ASSUMED, "value": candidate},
            "note": "상한 미만인지 보고(같으면 래퍼가 중단). 상한·thinking_level 결정/변경 없음.",
        },
        "pilots": {},
        "other": {
            "basis": MEASURED,
            "calls": sum(entry.purpose not in purposes for entry in gemini),
            "cost_usd": fsum(
                entry.cost_usd for entry in gemini if entry.purpose not in purposes
            ),
            "note": "종류별 측정값도 기타 합계에 포함되므로 중복 가산하지 않음.",
        },
        "kinds": {},
        "measured_kind_scenarios": [],
        "missing_tags": [],
        "estimated_cost_entries": sum(
            entry.cost_source != "response_cost" for entry in gemini
        ),
    }
    scenario_args = {
        "items": items,
        "shares": shares,
        "cumulative": cumulative,
        "cap": cap,
        "candidate": candidate,
    }
    for tag in TAGS:
        tagged = [
            entry
            for entry in gemini
            if entry.purpose in {f"pilot-{tag}", f"pilot-{tag}-retry"}
        ]
        if not tagged:
            report["missing_tags"].append(tag)
            continue
        summary = _summary(tagged)
        short = _summary(
            [entry for entry in tagged if entry.input_tokens <= hook_input_max]
        )
        segment = _summary(
            [entry for entry in tagged if entry.input_tokens > hook_input_max]
        )
        products = (len(tagged) - pilot_items) / 2
        reliable = (
            short["calls"] == products
            and products.is_integer()
            and 0 <= products <= pilot_items
        )
        summary["split"] = {
            "basis": "가정(입력 토큰 크기로 분리)",
            "short": short,
            "segment": segment,
            "reliable": reliable,
            "note": "짧은 호출은 hook, 구간 호출은 content_type·full로 보인다는 가정. "
            "content_type과 full의 비용이 같다고 가정.",
        }
        summary["pilot_reference"] = {
            "basis": "가정(호출 수 역산; retry 포함으로 왜곡 가능, 참고 전용)",
            "product_items": products,
            "product_share": products / pilot_items,
        }
        if not reliable:
            report["warnings"].append(f"COST_KIND_SPLIT_MISMATCH:{tag}")
            summary["split"]["note"] += " 분리가 믿을 수 없음; 견적은 계속 계산."
        summary["scenarios"] = _scenarios(segment, short, segment, **scenario_args)
        report["pilots"][tag] = summary
    if report["missing_tags"]:
        report["errors"].append("COST_NO_PILOT_ENTRIES")
    for kind in KINDS:
        rows = [entry for entry in gemini if entry.purpose == f"analyze-target-{kind}"]
        if rows:
            report["kinds"][kind] = _summary(rows)
    if all(kind in report["kinds"] for kind in KINDS):
        report["measured_kind_scenarios"] = _scenarios(
            *(report["kinds"][kind] for kind in KINDS), **scenario_args
        )
    if not report["missing_tags"]:
        minimal, default = (report["pilots"][tag] for tag in TAGS)
        report["ratios"] = {
            "basis": "측정값(호출당); 가정(소재당은 지정한 시범 항목 수로 나눔)",
            "per_call_default_over_minimal": _cost(default, "mean")
            / _cost(minimal, "mean")
            if _cost(minimal, "mean")
            else None,
            "per_item_default_over_minimal": (default["cost_usd"] / pilot_items)
            / (minimal["cost_usd"] / pilot_items)
            if minimal["cost_usd"]
            else None,
            "note": "default/minimal. 분모가 0이면 계산 불가. 소재당 비율은 전체 견적에 쓰지 않음.",
        }
    report["limitations"] = LIMITATION.format(items=pilot_items)
    return report


def _number(value, basis=MEASURED) -> str:
    return "계산 불가" if value is None else f"{value:.8g} ({basis})"


def _print_summary(name: str, summary: dict, out: TextIO) -> None:
    print(f"{name}\t호출 수\t비용 합계 USD\tresponse_cost 외 항목 수", file=out)
    print(
        f"합계\t{_number(summary['calls'])}\t{_number(summary['cost_usd'])}\t{_number(summary['estimated_cost_entries'])} {summary['cost_note']}",
        file=out,
    )
    print("호출당 지표\t평균\tp50\tp90\t최댓값", file=out)
    for metric, stats in summary["stats"].items():
        print(
            metric
            + "\t"
            + "\t".join(
                _number(stats[key] if stats else None)
                for key in ("mean", "p50", "p90", "max")
            ),
            file=out,
        )


def _print_scenarios(name: str, scenarios: list[dict], out: TextIO) -> None:
    print(f"{name} 시나리오: 제품 비율 s는 {ASSUMED}; 비용 USD", file=out)
    print(
        "s\t평균 견적\tp90 견적\t누적+평균\t누적+p90\t현재 상한(평균/p90)\t후보 상한(평균/p90)",
        file=out,
    )

    def verdict(value):
        return "계산 불가" if value is None else ("안" if value else "밖")

    for row in scenarios:
        numbers = "\t".join(
            _number(row[key], ASSUMED)
            for key in (
                "product_share",
                "mean_usd",
                "p90_usd",
                "mean_total_usd",
                "p90_total_usd",
            )
        )
        caps = "\t".join(
            "/".join(
                verdict(row[f"{column}_within_{cap}_cap"]) for column in ("mean", "p90")
            )
            for cap in ("current", "candidate")
        )
        print(f"{numbers}\t{caps} ({ASSUMED})", file=out)


def _print_report(report: dict, out: TextIO) -> None:
    for code in (*report["errors"], *report.get("warnings", [])):
        print(code, file=out)
    print(f"파싱 못 한 줄 수: {_number(report['skipped_lines']['value'])}", file=out)
    if "assumptions" in report:
        assumptions = report["assumptions"]
        print(
            "견적 입력: "
            + ", ".join(
                f"{key}={_number(assumptions[key], ASSUMED)}"
                for key in ("items", "pilot_items", "hook_input_max")
            ),
            file=out,
        )
        print(assumptions["note"], file=out)
        for name, value in report["budget"].items():
            print(
                f"{name}: {_number(value['value'], value['basis'])}"
                if isinstance(value, dict)
                else value,
                file=out,
            )
        print(
            f"Gemini response_cost 외 항목 수: {_number(report['estimated_cost_entries'])} (있으면 비용 추정치 포함)",
            file=out,
        )
        for tag, summary in report["pilots"].items():
            _print_summary(tag, summary, out)
            print(summary["split"]["note"], file=out)
            for group, label in (("short", "짧은 호출"), ("segment", "구간 호출")):
                _print_summary(
                    f"{label} (가정: 입력 토큰 분리)", summary["split"][group], out
                )
            reference = summary["pilot_reference"]
            print(
                f"{tag} 시범 제품 소재 수 p={_number(reference['product_items'], reference['basis'])}, 비율={_number(reference['product_share'], reference['basis'])}",
                file=out,
            )
            _print_scenarios(tag, summary["scenarios"], out)
        other = report["other"]
        print(
            f"기타 purpose 합계: 호출 수 {_number(other['calls'])}, 비용 USD {_number(other['cost_usd'])}. {other['note']}",
            file=out,
        )
        if not report["kinds"]:
            print("종류별 측정 없음", file=out)
        for kind, summary in report["kinds"].items():
            _print_summary(f"종류별 측정값 {kind}", summary, out)
        if report["measured_kind_scenarios"]:
            print(
                "종류별 측정 단가 사용(실행 설정이 섞였을 수 있음). p90은 content_type·full에 적용, hook은 평균.",
                file=out,
            )
            _print_scenarios(
                "종류별 측정 단가 기반", report["measured_kind_scenarios"], out
            )
        elif report["kinds"]:
            print("종류별 견적 계산 불가: 세 종류의 측정값이 모두 필요함.", file=out)
        if "ratios" in report:
            ratios = report["ratios"]
            print(
                "default/minimal 비용 비율: "
                + ", ".join(
                    f"{key}={_number(ratios[key], ratios['basis'])}"
                    for key in (
                        "per_call_default_over_minimal",
                        "per_item_default_over_minimal",
                    )
                ),
                file=out,
            )
            print(ratios["note"], file=out)
        print(
            "견적 가정: N × c_구간 + N × s × (c_구간 + c_짧음). p90은 구간 단가만 p90으로 대체하며 총비용의 통계적 p90은 아님.",
            file=out,
        )
    print(json.dumps(report, ensure_ascii=False, allow_nan=False), file=out)
    print(report["limitations"], file=out)


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--items", type=int, required=True)
    parser.add_argument("--pilot-items", type=int, default=20)
    parser.add_argument("--hook-input-max", type=int, default=1000)
    parser.add_argument("--product-shares", default="0.25,0.5,0.75")
    parser.add_argument("--candidate-cap", type=float, default=14)
    error_report = {
        "errors": ["COST_INPUT_INVALID"],
        "skipped_lines": {"basis": MEASURED, "value": 0},
        "limitations": LIMITATION.format(items=20),
    }
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code:
            _print_report(error_report, out)
        return int(exc.code)
    try:
        shares = [float(value) for value in args.product_shares.split(",")]
        if (
            args.items <= 0
            or args.pilot_items <= 0
            or args.hook_input_max < 0
            or not isfinite(args.candidate_cap)
            or args.candidate_cap < 0
            or not all(isfinite(share) and 0 <= share <= 1 for share in shares)
        ):
            raise ValueError
        # Deliberately disable .env reads, even when no explicit environment is supplied.
        settings = load_settings(environ=environ, env_file=None)
    except (ValueError, SettingError):
        _print_report(error_report, out)
        return 2
    error_report["limitations"] = LIMITATION.format(items=args.pilot_items)
    path = args.ledger if args.ledger is not None else settings.ledger_path
    try:
        if not path.is_file():
            raise OSError
        entries, skipped = read_entries(path)
        error_report["skipped_lines"]["value"] = skipped
        if skipped:
            raise ValueError
        cumulative = provider_total(path, "gemini")
    except (OSError, UnicodeError, ValueError):
        error_report["errors"] = ["LEDGER_UNREADABLE"]
        _print_report(error_report, out)
        return 2
    report = recalculate(
        entries,
        items=args.items,
        pilot_items=args.pilot_items,
        hook_input_max=args.hook_input_max,
        shares=shares,
        cumulative=cumulative,
        cap=settings.provider_caps_usd["gemini"],
        candidate=args.candidate_cap,
    )
    _print_report(report, out)
    return 3 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
