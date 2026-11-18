"""Synthetic structured results drive text and separate screen commands."""

import json
from copy import deepcopy

import pytest

from beautyads.api.ask_view import build_view
from beautyads.domain.claims import CLAIM_CHECK_DISCLAIMER
from beautyads.domain.supervisor import (
    AGGREGATES_LABEL,
    LIMIT_REACHED_TEXT,
    NO_EVIDENCE_TEXT,
    OUT_OF_SCOPE_TEXT,
)


def result():
    return {
        "kind": "plan",
        "handoff": {
            "conclusion": "synthetic conclusion",
            "evidence_ids": ["youtube:a", "youtube:b", "youtube:missing"],
            "result_counts": [
                {"tool": "find_example_creatives", "row_count": 7, "shown_count": 5}
            ],
            "aggregates": {"kept": "5", "removed": "999"},
        },
        "aggregates_removed": ["removed"],
        "plans": [
            {
                "plan": {
                    "title": "synthetic title",
                    "hook_text": "synthetic hook",
                    "scenes": ["scene"],
                    "copy_lines": ["copy"],
                    "evidence_ids": ["youtube:a"],
                },
                "status": "needs_review",
                "report": {"passed": True},
                "unknown_count": 1,
                "unknown_codes": {"EFFICACY_UNKNOWN": 1},
                "efficacy_status": {"soothing": "unknown", "hydration": "supported"},
                "efficacy_summary": {"supported": 1, "unknown": 1},
                "attempts": [
                    {
                        "attempt": 1,
                        "scores": {"differentiation": 2, "fit": 3},
                        "low_items": ["differentiation"],
                        "passed": False,
                    }
                ],
                "evidence_counts": {"in_plan": 1, "in_pool": 3},
                "image": {
                    "request_key": "request",
                    "index": 0,
                    "mime": "image/png",
                    "size": 8,
                    "sha256": "a" * 64,
                    "path": "/synthetic/private.png",
                    "base64": "private-image",
                    "thought_signatures": "private-signature",
                },
            }
        ],
        "tool_outputs": [
            {
                "tool": "compare_axis_by_category",
                "row_count": 60,
                "rows": [{"i": i} for i in range(60)],
            }
        ],
    }


def hydrate(ids):
    return [
        {
            "evidence_id": eid,
            "source": "youtube",
            "url": "https://example.test/" + eid,
            "brand": "synthetic",
            "title": eid,
            "published_at": None,
            "view_count": 7,
            "like_count": 2,
            "thumbnail": "omitted",
        }
        for eid in ids
        if eid != "youtube:missing"
    ]


def command(view, kind):
    return next(item["data"] for item in view.ui_commands if item["kind"] == kind)


def test_plan_keeps_unknowns_efficacy_and_reworks_separate():
    raw = result()
    original = deepcopy(raw)
    view = build_view(raw, plan_ids=["server-id"], hydrate=hydrate)
    card = command(view, "show_plan")
    assert card["passed"] is True
    assert card["unknown_count"] == 1 and card["unknown_codes"] == {
        "EFFICACY_UNKNOWN": 1
    }
    assert card["efficacy_status"] == raw["plans"][0]["efficacy_status"]
    assert card["efficacy_summary"] == {"supported": 1, "unknown": 1}
    assert card["count_label"] == "7건 중 5건 표시"
    assert card["disclaimer"] == CLAIM_CHECK_DISCLAIMER
    assert card["attempts"] == raw["plans"][0]["attempts"]
    assert card["plan_id"] == "server-id" and card["status"] == "needs_review"
    assert card["evidence_counts"] == {"in_plan": 1, "in_pool": 3}
    assert set(card["image"]) == {"request_key", "index", "mime", "size", "sha256"}
    encoded = json.dumps(view.ui_commands)
    assert (
        "private" not in encoded
        and "base64" not in encoded
        and "thought_signatures" not in encoded
    )
    assert raw == original
    for text in ("synthetic title", "synthetic hook", "scene", "copy"):
        assert text in view.answer_text


def test_cards_distribution_and_graph_use_tool_data():
    calls = []

    def fill(ids):
        calls.append(ids)
        return hydrate(ids) + [{"evidence_id": "not-requested"}]

    raw = result()
    view = build_view(raw, plan_ids=["id"], hydrate=fill)
    cards = command(view, "show_evidence_cards")
    assert calls == [raw["handoff"]["evidence_ids"]]
    assert cards["missing"] == 1 and len(cards["cards"]) == 2
    assert cards["cards"][0]["view_count"] == 7
    assert "thumbnail" not in cards["cards"][0]
    assert (
        command(view, "show_distribution")["rows"]
        == raw["tool_outputs"][0]["rows"][:50]
    )
    assert command(view, "show_graph_fragment") == {
        "evidence_ids": raw["handoff"]["evidence_ids"]
    }
    json.dumps(view.ui_commands, allow_nan=False)


def test_evidence_cap_and_missing_hydrator():
    raw = result()
    raw["handoff"]["evidence_ids"] = [f"youtube:{i}" for i in range(30)]
    view = build_view(raw, plan_ids=["id"], hydrate=hydrate)
    assert len(command(view, "show_evidence_cards")["cards"]) == 20
    view = build_view(raw, plan_ids=["id"], hydrate=None)
    assert command(view, "show_evidence_cards")["missing"] == 20


@pytest.mark.parametrize(
    "total,shown,label", [(7, 5, "7건 중 5건 표시"), (3, 3, "3건")]
)
def test_counts_and_aggregates_do_not_depend_on_generated_prose(total, shown, label):
    raw = result()
    raw["kind"] = "research"
    raw["plans"] = []
    raw["handoff"]["result_counts"][0].update(row_count=total, shown_count=shown)
    view = build_view(raw, plan_ids=[], hydrate=hydrate)
    assert label in view.answer_text and "synthetic conclusion" in view.answer_text
    assert AGGREGATES_LABEL in view.answer_text and "kept: 5" in view.answer_text
    assert "999" not in view.answer_text
    assert "aggregates_removed: removed" in view.answer_text


@pytest.mark.parametrize(
    "kind,text",
    [
        ("out_of_scope", OUT_OF_SCOPE_TEXT),
        ("no_evidence", NO_EVIDENCE_TEXT),
        ("limit_hit", LIMIT_REACHED_TEXT),
    ],
)
def test_fixed_text_and_separate_limits(kind, text):
    view = build_view(
        {"kind": kind, "limit_hit": True, "limit_kinds": ["text", "image"]},
        plan_ids=[],
        hydrate=None,
    )
    assert text in view.answer_text
    assert "text" in view.answer_text and "image" in view.answer_text


def test_model_ui_and_lookup_rows_cannot_become_distributions():
    raw = result()
    raw["ui_commands"] = [{"kind": "show_distribution", "data": {"rows": ["invented"]}}]
    raw["tool_outputs"] = [
        {"tool": name, "rows": ["invented"]}
        for name in ("find_example_creatives", "unknown_tool")
    ]
    view = build_view(raw, plan_ids=["id"], hydrate=None)
    assert not any(item["kind"] == "show_distribution" for item in view.ui_commands)
    assert "invented" not in json.dumps(view.ui_commands)


def test_json_timestamps_and_report_fallback():
    from datetime import UTC, datetime

    raw = result()
    item = raw["plans"][0]
    for field in (
        "unknown_count",
        "unknown_codes",
        "efficacy_status",
        "efficacy_summary",
    ):
        item["report"][field] = item.pop(field)

    def fill(ids):
        rows = hydrate(ids)
        rows[0]["published_at"] = datetime(2026, 1, 1, tzinfo=UTC)
        return rows

    view = build_view(raw, plan_ids=["id"], hydrate=fill)
    assert command(view, "show_plan")["unknown_count"] == 1
    assert (
        command(view, "show_evidence_cards")["cards"][0]["published_at"]
        == "2026-01-01T00:00:00+00:00"
    )
    json.dumps(view.ui_commands, allow_nan=False)
