"""Pure screen projection of Supervisor results, without replaying model UI data."""

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime

from beautyads.agents.tools import get_tool
from beautyads.domain.claims import CLAIM_CHECK_DISCLAIMER
from beautyads.domain.plan import Plan
from beautyads.domain.research import count_label
from beautyads.domain.supervisor import (
    AGGREGATES_LABEL,
    DESIGN_IMAGE_DISCLAIMER,
    LIMIT_REACHED_TEXT,
    NO_EVIDENCE_TEXT,
    OUT_OF_SCOPE_TEXT,
)
from beautyads.domain.tools import ToolKind

IMAGE_MIMES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_IMAGE_FIELDS = ("request_key", "index", "mime", "size", "sha256")
_CARD_FIELDS = (
    "evidence_id",
    "source",
    "url",
    "brand",
    "title",
    "published_at",
    "view_count",
    "like_count",
)


@dataclass(frozen=True)
class View:
    answer_text: str
    ui_commands: list[dict]


def json_copy(value):
    """Own JSON values; timestamps become ISO strings, other objects fail closed."""

    def default(item):
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        raise TypeError("VIEW_NON_JSON_VALUE")

    return json.loads(json.dumps(value, default=default, allow_nan=False))


def image_reference(image) -> dict | None:
    """Drop image bodies, signatures, diagnostics and local filesystem paths."""
    if not isinstance(image, dict) or not all(key in image for key in _IMAGE_FIELDS):
        return None
    if (
        not isinstance(image.get("request_key"), str)
        or not image["request_key"]
        or type(image.get("index")) is not int
        or image["index"] < 0
        or image.get("mime") not in IMAGE_MIMES
        or type(image.get("size")) is not int
        or image["size"] < 0
        or not isinstance(image.get("sha256"), str)
    ):
        return None
    reference = {key: image[key] for key in _IMAGE_FIELDS}
    composed = image.get("composed")
    if (
        isinstance(composed, dict)
        and composed.get("mime") == "image/png"
        and type(composed.get("size")) is int
        and composed["size"] >= 0
        and isinstance(composed.get("sha256"), str)
        and re.fullmatch(r"[a-fA-F0-9]{64}", composed["sha256"])
    ):
        reference["composed"] = {
            key: composed[key] for key in ("mime", "size", "sha256")
        }
        if type(composed.get("contrast_adjusted")) is bool:
            reference["composed"]["contrast_adjusted"] = composed["contrast_adjusted"]
        contrast = composed.get("min_contrast")
        if type(contrast) in (int, float) and math.isfinite(contrast) and contrast >= 0:
            reference["composed"]["min_contrast"] = float(contrast)
    return reference


def _counts(counts):
    return [
        {**item, "count_label": count_label(item["row_count"], item["shown_count"])}
        for item in counts
    ]


def build_view(result, *, plan_ids, hydrate) -> View:
    """Hydrate only IDs; aggregate values here already passed Supervisor checks.

    The Supervisor removes unverified numeric aggregates before this boundary.
    Keep its removal list separate, even if an injected result repeats a name.
    Distribution rows come exclusively from tool_outputs, never handoff prose.
    """
    handoff = result.get("handoff") or {}
    kind = result.get("kind")
    commands, text = [], []
    fixed = {
        "out_of_scope": OUT_OF_SCOPE_TEXT,
        "no_evidence": NO_EVIDENCE_TEXT,
        "failed": "요청 처리에 실패했다.",
    }
    if kind in fixed:
        text.append(fixed[kind])
    elif kind == "research":
        text.extend(["리서치 결과입니다.", handoff.get("conclusion", "")])
    elif kind == "plan":
        text.append("기획안입니다.")

    counts = _counts(handoff.get("result_counts", []))
    text.extend(f"{item['tool']}: {item['count_label']}" for item in counts)
    ids = list(dict.fromkeys(handoff.get("evidence_ids", [])))
    if ids:
        selected = ids[:20]
        rows = hydrate(selected) if hydrate is not None else []
        by_id = {
            row.get("evidence_id"): row
            for row in rows
            if row.get("evidence_id") in selected
        }
        cards = [
            {key: by_id[eid].get(key) for key in _CARD_FIELDS}
            for eid in selected
            if eid in by_id
        ]
        commands.append(
            {
                "kind": "show_evidence_cards",
                "data": {
                    "cards": cards,
                    "missing": len(selected) - len(cards),
                },
            }
        )

    for index, item in enumerate(result.get("plans", [])):
        plan = item.get("plan")
        if not isinstance(plan, dict):
            continue
        report = item.get("report") or {}
        fields = {key: value for key, value in plan.items() if key in Plan.model_fields}
        text.extend(
            [
                fields.get("title", ""),
                fields.get("hook_text", ""),
                *fields.get("scenes", []),
                *fields.get("copy_lines", []),
            ]
        )
        plan_counts = _counts(
            item.get("result_counts", handoff.get("result_counts", []))
        )
        data = {
            "plan": fields,
            "plan_id": plan_ids[index],
            "passed": report.get("passed", False),
            "unknown_count": item.get("unknown_count", report.get("unknown_count", 0)),
            "unknown_codes": item.get("unknown_codes", report.get("unknown_codes", {})),
            "efficacy_status": item.get(
                "efficacy_status", report.get("efficacy_status", {})
            ),
            "efficacy_summary": item.get(
                "efficacy_summary",
                report.get("efficacy_summary", {"supported": 0, "unknown": 0}),
            ),
            "count_label": "; ".join(count["count_label"] for count in plan_counts),
            "result_counts": plan_counts,
            "evidence_counts": item.get("evidence_counts", {}),
            "status": item.get("status", "failed"),
            "attempts": item.get("attempts", []),
            "pattern_alignment": item.get("pattern_alignment", {}),
            "pattern_alignment_label": "코드 계산, 판정 아님",
            "disclaimer": CLAIM_CHECK_DISCLAIMER,
            "image": image_reference(item.get("image")),
            "design_disclaimer": DESIGN_IMAGE_DISCLAIMER
            if image_reference(item.get("image")) is not None
            else None,
            "product_display": result.get("product_display")
            or {"brand": None, "display_name": None, "product_name": None},
        }
        commands.append({"kind": "show_plan", "data": data})

    removed = result.get("aggregates_removed", [])
    aggregates = {
        key: value
        for key, value in handoff.get("aggregates", {}).items()
        if key not in removed
    }
    if aggregates or removed:
        text.append(AGGREGATES_LABEL)
        text.extend(f"{key}: {value}" for key, value in aggregates.items())
    if removed:
        text.append("aggregates_removed: " + ", ".join(removed))

    for output in result.get("tool_outputs", []):
        tool = get_tool(output.get("tool"))
        if tool is not None and tool.kind in {ToolKind.aggregate, ToolKind.compare}:
            commands.append(
                {
                    "kind": "show_distribution",
                    "data": {
                        "tool": tool.name,
                        "rows": output.get("rows", [])[:50],
                    },
                }
            )
    if ids:
        commands.append({"kind": "show_graph_fragment", "data": {"evidence_ids": ids}})
    if kind == "limit_hit" or result.get("limit_hit"):
        text.append(LIMIT_REACHED_TEXT)
        text.append("도달한 상한: " + ", ".join(result.get("limit_kinds", [])))
    return View("\n".join(part for part in text if part), json_copy(commands))
