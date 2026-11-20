"""Synthetic structured results drive text and separate screen commands."""

import json
from copy import deepcopy

import pytest

from beautyads.api.ask_view import build_view
from beautyads.domain.claims import CLAIM_CHECK_DISCLAIMER
from beautyads.domain.supervisor import (
    AGGREGATES_LABEL,
    CLARIFY_REQUESTED_NO_CONFIRMED_TEXT,
    CLARIFY_REQUESTED_TEXT,
    CLARIFY_UNSPECIFIED_TEXT,
    EFFICACY_UNAVAILABLE_TEXT,
    LIMIT_REACHED_TEXT,
    NO_EVIDENCE_TEXT,
    OPTION_KEEP_REQUESTED,
    OPTION_NONE,
    OPTION_SELECT_CONFIRMED,
    OPTION_SELECT_MANY,
    OPTION_SELECT_ONE,
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
                        "checks_passed": False,
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


def test_plan_displays_alignment_separately_from_scores_and_final_pass():
    raw = result()
    alignment = {
        "axes": {"hook_type": {"same": True}},
        "compared": 1,
        "same_count": 1,
        "skipped": 0,
    }
    raw["plans"][0]["pattern_alignment"] = alignment
    raw["plans"][0]["attempts"][0]["final_passed"] = False
    view = build_view(raw, plan_ids=["id"], hydrate=None)
    data = command(view, "show_plan")
    assert data["pattern_alignment"] == alignment
    assert data["pattern_alignment_label"] == "코드 계산, 판정 아님"
    assert data["passed"] is True
    assert "pattern_alignment" not in data["attempts"][0]["scores"]
    assert "passed" not in data["attempts"][0]
    data["pattern_alignment"]["axes"].clear()
    assert raw["plans"][0]["pattern_alignment"] == alignment


@pytest.mark.parametrize("with_image", [False, True])
@pytest.mark.parametrize(
    "display", [None, {"brand": "synthetic brand", "display_name": "synthetic product"}]
)
def test_plan_has_fixed_image_disclaimer_and_separate_product_display(
    with_image, display
):
    from beautyads.domain.supervisor import DESIGN_IMAGE_DISCLAIMER

    raw = result()
    if not with_image:
        raw["plans"][0]["image"] = None
    if display is not None:
        raw["product_display"] = display
    raw["plans"][0]["design_disclaimer"] = "model-authored-disclaimer"
    raw["plans"][0]["product_display"] = {"brand": "model-authored-brand"}
    data = command(build_view(raw, plan_ids=["id"], hydrate=None), "show_plan")
    assert data["design_disclaimer"] == (
        DESIGN_IMAGE_DISCLAIMER if with_image else None
    )
    assert data["product_display"] == (
        display or {"brand": None, "display_name": None, "product_name": None}
    )
    json.dumps(data, allow_nan=False)


def test_composed_reference_passes_only_safe_metadata_without_mutation():
    from beautyads.api.ask_view import image_reference

    raw = result()
    image = raw["plans"][0]["image"]
    image["composed"] = {
        "mime": "image/png",
        "size": 123,
        "sha256": "b" * 64,
        "path": "/synthetic/private.png",
        "base64": "private-image",
    }
    expected = {"mime": "image/png", "size": 123, "sha256": "b" * 64}
    original = deepcopy(raw)
    assert image_reference(image)["composed"] == expected
    card = command(build_view(raw, plan_ids=["id"], hydrate=None), "show_plan")
    assert card["image"]["composed"] == expected
    assert "private" not in json.dumps(card) and "base64" not in json.dumps(card)
    assert raw == original
    card["image"]["composed"]["size"] = 999
    assert image["composed"]["size"] == 123


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        [],
        {},
        {"mime": "image/jpeg", "size": 1, "sha256": "b" * 64},
        {"mime": "image/png", "size": True, "sha256": "b" * 64},
        {"mime": "image/png", "size": -1, "sha256": "b" * 64},
        {"mime": "image/png", "size": 1, "sha256": "private/base64"},
        {"mime": "image/png", "size": 1, "sha256": None},
    ],
)
def test_invalid_composed_metadata_is_dropped_but_original_stays_valid(invalid):
    from beautyads.api.ask_view import image_reference

    image = result()["plans"][0]["image"]
    expected = image_reference(image)
    image["composed"] = invalid
    assert image_reference(image) == expected


@pytest.mark.parametrize(
    "adjusted,contrast,expected",
    [
        (True, 2.346, {"contrast_adjusted": True, "min_contrast": 2.346}),
        (False, 0, {"contrast_adjusted": False, "min_contrast": 0.0}),
        ("private-secret", 3.5, {"min_contrast": 3.5}),
        (1, -1, {}),
        (0, float("nan"), {}),
        (None, float("inf"), {}),
        (True, True, {"contrast_adjusted": True}),
        (True, "private-secret", {"contrast_adjusted": True}),
    ],
)
def test_composed_contrast_fields_are_independently_validated(
    adjusted, contrast, expected
):
    from beautyads.api.ask_view import image_reference

    raw = result()
    image = raw["plans"][0]["image"]
    base = {"mime": "image/png", "size": 123, "sha256": "b" * 64}
    image["composed"] = {
        **base,
        "contrast_adjusted": adjusted,
        "min_contrast": contrast,
        "path": "/private-secret",
        "base64": "private-secret",
    }
    original = deepcopy(image)
    safe = image_reference(image)
    assert safe["composed"] == {**base, **expected}
    assert set(safe) == {"request_key", "index", "mime", "size", "sha256", "composed"}
    assert "private-secret" not in json.dumps(safe, allow_nan=False)
    data = command(build_view(raw, plan_ids=["id"], hydrate=None), "show_plan")
    assert data["image"]["composed"] == safe["composed"]
    assert image.keys() == original.keys()
    assert image["composed"].keys() == original["composed"].keys()
    assert image["composed"]["contrast_adjusted"] is adjusted
    assert image["composed"]["min_contrast"] is contrast


def test_product_identity_is_separate_from_model_plan_and_cta_type_is_preserved():
    raw = result()
    raw["product_display"] = {
        "brand": "English_Brand",
        "display_name": "합성 작업 공간",
        "product_name": "공식 합성 세럼",
    }
    raw["plans"][0]["plan"].update(
        cta_type="learn_more", product_display={"brand": "MODEL_SENTINEL"}
    )
    data = command(build_view(raw, plan_ids=["id"], hydrate=None), "show_plan")
    assert data["plan"]["cta_type"] == raw["plans"][0]["plan"]["cta_type"]
    assert data["product_display"] == raw["product_display"]
    assert "product_display" not in data["plan"]


@pytest.mark.parametrize(
    "requested,available,template,options",
    [
        (
            "anti_aging",
            ["hydration", "soothing"],
            CLARIFY_REQUESTED_TEXT,
            [
                ("keep_requested", OPTION_KEEP_REQUESTED),
                ("select_confirmed", OPTION_SELECT_CONFIRMED),
                ("none", OPTION_NONE),
            ],
        ),
        (
            "anti_aging",
            [],
            CLARIFY_REQUESTED_NO_CONFIRMED_TEXT,
            [("keep_requested", OPTION_KEEP_REQUESTED), ("none", OPTION_NONE)],
        ),
        (
            None,
            ["hydration", "soothing"],
            CLARIFY_UNSPECIFIED_TEXT,
            [
                ("select_one", OPTION_SELECT_ONE),
                ("select_many", OPTION_SELECT_MANY),
                ("none", OPTION_NONE),
            ],
        ),
    ],
)
def test_clarification_text_options_and_no_screen_commands(
    requested, available, template, options
):
    from beautyads.analysis.prompts import CLAIM_DISPLAY_NAMES
    from beautyads.domain.labels import Claim

    reason = "requested_not_confirmed" if requested else "no_claim_requested"
    clarification = {
        "reason": reason,
        "requested_claim": requested,
        "available_efficacy": available,
        "available_status": "ok",
        "options": [option for option, _ in options],
    }
    # Even unrelated result data must not create cards, plans or distributions.
    raw = {**result(), "kind": "needs_clarification", "clarification": clarification}
    before = deepcopy(raw)
    view = build_view(
        raw,
        plan_ids=[],
        hydrate=lambda ids: pytest.fail("clarification must not hydrate evidence"),
    )
    requested_label = CLAIM_DISPLAY_NAMES[Claim(requested)] if requested else None
    expected_text = template.format(
        requested=requested_label,
        available=", ".join(CLAIM_DISPLAY_NAMES[Claim(value)] for value in available),
    )
    assert view.answer_text == expected_text
    assert view.ui_commands == [] and view.error_code is None
    assert view.clarification == {
        "reason": reason,
        "requested_claim": requested,
        "requested_label": requested_label,
        "available": [
            {"claim": value, "label": CLAIM_DISPLAY_NAMES[Claim(value)]}
            for value in available
        ],
        "options": [
            {"id": option, "label": label.format(requested=requested_label)}
            for option, label in options
        ],
        "text": expected_text,
    }
    assert raw == before
    view.clarification["options"].clear()
    assert raw == before


def test_claim_display_alias_and_mapping_exclude_other():
    from beautyads.analysis.prompts import _CLAIM_CRITERIA, CLAIM_DISPLAY_NAMES
    from beautyads.api.ask_view import _CLAIM_DISPLAY
    from beautyads.domain.labels import Claim

    assert CLAIM_DISPLAY_NAMES is _CLAIM_CRITERIA
    assert _CLAIM_DISPLAY == {
        claim.value: CLAIM_DISPLAY_NAMES[claim]
        for claim in Claim
        if claim != Claim.other
    }
    assert Claim.other.value not in _CLAIM_DISPLAY


@pytest.mark.parametrize("notice", ["legacy_notice", None, "unknown_notice"])
@pytest.mark.parametrize(
    "kind", ["research", "plan", "out_of_scope", "no_evidence", "failed", "limit_hit"]
)
def test_legacy_efficacy_notice_is_ignored(notice, kind):
    raw = {**result(), "kind": kind}
    baseline = build_view(raw, plan_ids=["id"], hydrate=hydrate)
    raw["efficacy_notice"] = notice
    assert build_view(raw, plan_ids=["id"], hydrate=hydrate) == baseline


@pytest.mark.parametrize(
    "reason,expected",
    [("failed", "failed"), ("no_product", "no_product"), ("unknown", "failed")],
)
def test_efficacy_unavailable_has_only_fixed_text_and_no_commands(reason, expected):
    raw = {
        **result(),
        "kind": "efficacy_unavailable",
        "efficacy_unavailable": {"reason": reason},
    }
    before = deepcopy(raw)
    view = build_view(
        raw,
        plan_ids=[],
        hydrate=lambda ids: pytest.fail("unavailable must not hydrate"),
    )
    assert view.answer_text == EFFICACY_UNAVAILABLE_TEXT[expected]
    assert view.ui_commands == []
    assert view.clarification is view.error_code is None
    assert view.efficacy_unavailable == {
        "reason": expected,
        "text": EFFICACY_UNAVAILABLE_TEXT[expected],
    }
    assert raw == before


def test_no_confirmed_efficacy_view_asks_to_proceed_or_cancel():
    from beautyads.domain.supervisor import CLARIFY_NO_CONFIRMED_TEXT

    raw = {
        **result(),
        "kind": "needs_clarification",
        "clarification": {
            "reason": "no_efficacy_confirmed",
            "requested_claim": None,
            "available_efficacy": [],
            "available_status": "ok",
            "options": ["none", "cancel"],
        },
    }
    view = build_view(
        raw, plan_ids=[], hydrate=lambda ids: pytest.fail("must not hydrate")
    )
    assert view.answer_text == CLARIFY_NO_CONFIRMED_TEXT
    assert view.clarification == {
        "reason": "no_efficacy_confirmed",
        "requested_claim": None,
        "requested_label": None,
        "available": [],
        "text": CLARIFY_NO_CONFIRMED_TEXT,
        "options": [
            {"id": "none", "label": "효능 강조 없이 진행"},
            {"id": "cancel", "label": "중단"},
        ],
    }
    assert view.ui_commands == [] and view.efficacy_unavailable is None


def test_invalid_claim_choice_has_only_error_code():
    view = build_view(
        {**result(), "kind": "claim_choice_invalid"},
        plan_ids=[],
        hydrate=lambda ids: pytest.fail("invalid choice must not hydrate evidence"),
    )
    assert view.error_code == "CLAIM_CHOICE_INVALID"
    assert view.answer_text == "" and view.ui_commands == []
    assert view.clarification is None


def test_view_two_argument_constructor_is_compatible():
    from beautyads.api.ask_view import View

    commands = [{"kind": "show_graph_fragment", "data": {"evidence_ids": []}}]
    view = View("synthetic", commands)
    assert view.answer_text == "synthetic" and view.ui_commands == commands
    assert view.clarification is view.error_code is None


@pytest.mark.parametrize("available", [["hydration"], []])
def test_other_requested_label_is_none_and_generic_copy_is_used(available):
    from beautyads.domain.supervisor import clarification_texts

    clarification = {
        "reason": "requested_not_confirmed",
        "requested_claim": "other",
        "available_efficacy": available,
        "available_status": "ok",
        "options": ["keep_requested"]
        + (["select_confirmed"] if available else [])
        + ["none"],
    }
    raw = {"kind": "needs_clarification", "clarification": clarification}
    before = deepcopy(raw)
    view = build_view(raw, plan_ids=[], hydrate=None)
    rendered = clarification_texts(clarification, {"hydration": "보습"})
    assert view.clarification == {
        "reason": "requested_not_confirmed",
        "requested_claim": "other",
        "requested_label": None,
        "available": [{"claim": claim, "label": "보습"} for claim in available],
        **rendered,
    }
    assert "other" not in view.answer_text
    assert view.ui_commands == [] and view.error_code is None
    assert raw == before
