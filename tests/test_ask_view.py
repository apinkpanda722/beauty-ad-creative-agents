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


@pytest.mark.parametrize("kept,removed", [(True, True), (True, False), (False, True)])
def test_aggregate_command_separates_tool_counts_model_values_and_removed(
    kept, removed
):
    from beautyads.api.ask_view import _counts

    raw = result()
    if not kept:
        raw["handoff"]["aggregates"].pop("kept")
    if not removed:
        raw["aggregates_removed"] = []
    before = deepcopy(raw)
    view = build_view(raw, plan_ids=["id"], hydrate=None)
    data = command(view, "show_aggregates")
    surviving = {
        name: value
        for name, value in raw["handoff"]["aggregates"].items()
        if name not in raw["aggregates_removed"]
    }
    assert data == {
        "label": AGGREGATES_LABEL,
        "verified_counts": _counts(raw["handoff"]["result_counts"]),
        "model_written": [
            {"name": name, "value": value} for name, value in surviving.items()
        ],
        "removed": raw["aggregates_removed"],
    }
    assert not set(data["removed"]) & {item["name"] for item in data["model_written"]}
    assert all(
        model["value"] not in count.values()
        for model in data["model_written"]
        for count in data["verified_counts"]
    )
    json.dumps(data, allow_nan=False)
    data["verified_counts"][0]["row_count"] = 100
    data["model_written"].clear()
    data["removed"].append("changed")
    assert raw == before


@pytest.mark.parametrize("absent", [False, True])
def test_no_aggregate_command_without_values_or_removals(absent):
    raw = result()
    raw["handoff"]["aggregates"] = {}
    raw["aggregates_removed"] = []
    if absent:
        raw["handoff"].pop("aggregates")
        raw.pop("aggregates_removed")
    view = build_view(raw, plan_ids=["id"], hydrate=None)
    assert "show_aggregates" not in [item["kind"] for item in view.ui_commands]


@pytest.mark.parametrize("spent,maximum", [(0, 1), (0.125, 0.3)])
def test_cost_command_uses_only_request_text_cost(spent, maximum):
    raw = result()
    raw["limits"] = {"text_spent_usd": spent, "max_text_cost_usd": maximum}
    raw["image_spent_usd"] = 100
    data = command(build_view(raw, plan_ids=["id"], hydrate=None), "show_cost")
    assert data == {
        "label": "텍스트 모델 비용(이미지 제외)",
        "text_spent_usd": float(spent),
        "max_text_cost_usd": float(maximum),
        "image_cost_usd": None,
    }
    assert type(data["text_spent_usd"]) is type(data["max_text_cost_usd"]) is float
    json.dumps(data, allow_nan=False)
    data["text_spent_usd"] = 99
    assert raw["limits"]["text_spent_usd"] == spent


@pytest.mark.parametrize("costs", [[0.0336], [0.0336, 0.04], [0]])
def test_successful_image_costs_are_summed_without_exposing_reference_cost(costs):
    from beautyads.api.ask_view import image_reference

    raw = result()
    raw["limits"] = {"text_spent_usd": 0.1, "max_text_cost_usd": 0.3}
    template = raw["plans"][0]
    raw["plans"] = [
        {
            **deepcopy(template),
            "image": {**template["image"], "ok": True, "cost_usd": cost},
        }
        for cost in costs
    ]
    before = deepcopy(raw)
    view = build_view(raw, plan_ids=["id"] * len(costs), hydrate=None)
    data = command(view, "show_cost")
    assert type(data["image_cost_usd"]) is float
    assert data["image_cost_usd"] == sum(costs)
    json.dumps(view.ui_commands, allow_nan=False)
    for item in raw["plans"]:
        reference = image_reference(item["image"])
        assert "cost_usd" not in reference
        assert list(reference) == ["request_key", "index", "mime", "size", "sha256"]
    assert raw == before


@pytest.mark.parametrize(
    "image",
    [
        None,
        {},
        {"ok": False, "cost_usd": 0.0336},
        {"ok": True},
        *[
            {"ok": True, "cost_usd": value}
            for value in [
                True,
                False,
                float("nan"),
                float("inf"),
                -float("inf"),
                -0.1,
                "0.03",
                None,
            ]
        ],
    ],
)
def test_invalid_or_missing_image_costs_are_ignored(image):
    raw = result()
    raw["limits"] = {"text_spent_usd": 0.1, "max_text_cost_usd": 0.3}
    raw["plans"][0]["image"] = image
    before = deepcopy(raw)
    view = build_view(raw, plan_ids=["id"], hydrate=None)
    assert command(view, "show_cost")["image_cost_usd"] is None
    json.dumps(view.ui_commands, allow_nan=False)
    assert raw == before


def test_invalid_image_cost_does_not_discard_a_valid_image_cost():
    raw = result()
    raw["limits"] = {"text_spent_usd": 0.1, "max_text_cost_usd": 0.3}
    raw["plans"] = [
        {"image": {"ok": False, "cost_usd": 10}},
        {"image": {"ok": True, "cost_usd": 0.0336}},
    ]
    before = deepcopy(raw)
    data = command(build_view(raw, plan_ids=[], hydrate=None), "show_cost")
    assert data["image_cost_usd"] == 0.0336
    assert type(data["image_cost_usd"]) is float
    json.dumps(data, allow_nan=False)
    assert raw == before


@pytest.mark.parametrize("field", ["text_spent_usd", "max_text_cost_usd"])
@pytest.mark.parametrize(
    "invalid", [float("nan"), float("inf"), -float("inf"), "0.1", True, False, None]
)
def test_invalid_cost_field_omits_whole_cost_command(field, invalid):
    raw = result()
    raw["limits"] = {"text_spent_usd": 0.1, "max_text_cost_usd": 0.3, field: invalid}
    view = build_view(raw, plan_ids=["id"], hydrate=None)
    assert "show_cost" not in [item["kind"] for item in view.ui_commands]
    json.dumps(view.ui_commands, allow_nan=False)


@pytest.mark.parametrize(
    "limits", [None, {}, {"text_spent_usd": 0.1}, {"max_text_cost_usd": 0.3}]
)
def test_missing_cost_limits_omit_cost_command(limits):
    raw = result()
    if limits is not None:
        raw["limits"] = limits
    view = build_view(raw, plan_ids=["id"], hydrate=None)
    assert "show_cost" not in [item["kind"] for item in view.ui_commands]


@pytest.mark.parametrize("kind", ["plan", "research"])
def test_display_text_omits_structured_content_and_preserves_legacy_bytes(kind):
    from beautyads.api.ask_view import _counts

    raw = result()
    raw["kind"] = kind
    raw["limits"] = {"text_spent_usd": 0.1, "max_text_cost_usd": 0.3}
    message = (
        ["기획안입니다."]
        if kind == "plan"
        else ["리서치 결과입니다.", raw["handoff"]["conclusion"]]
    )
    counts = _counts(raw["handoff"]["result_counts"])
    count_lines = [f"{item['tool']}: {item['count_label']}" for item in counts]
    plan = raw["plans"][0]["plan"]
    plan_lines = [
        plan["title"],
        plan["hook_text"],
        *plan["scenes"],
        *plan["copy_lines"],
    ]
    if kind == "research":
        raw["plans"] = []
    model_lines = [
        f"{name}: {value}"
        for name, value in raw["handoff"]["aggregates"].items()
        if name not in raw["aggregates_removed"]
    ]
    aggregate_lines = [
        AGGREGATES_LABEL,
        *model_lines,
        "aggregates_removed: " + ", ".join(raw["aggregates_removed"]),
    ]
    view = build_view(raw, plan_ids=["id"], hydrate=None)
    expected = "\n".join(
        [
            *message,
            *count_lines,
            *(plan_lines if kind == "plan" else []),
            *aggregate_lines,
        ]
    )
    assert view.answer_text.encode("utf-8") == expected.encode("utf-8")
    assert view.display_text == "\n".join(message)
    assert all(
        line not in view.display_text
        for line in [*plan_lines, *count_lines, *aggregate_lines]
    )


@pytest.mark.parametrize(
    "kind,fixed",
    [
        ("out_of_scope", OUT_OF_SCOPE_TEXT),
        ("no_evidence", NO_EVIDENCE_TEXT),
        ("limit_hit", LIMIT_REACHED_TEXT),
    ],
)
def test_display_text_keeps_fixed_messages_and_limit_details(kind, fixed):
    raw = result()
    raw.update(kind=kind, plans=[], limit_hit=True, limit_kinds=["text", "image"])
    view = build_view(raw, plan_ids=[], hydrate=None)
    assert fixed in view.answer_text and fixed in view.display_text
    assert LIMIT_REACHED_TEXT in view.display_text
    assert "도달한 상한: " + ", ".join(raw["limit_kinds"]) in view.display_text
    assert AGGREGATES_LABEL not in view.display_text


@pytest.mark.parametrize(
    "kind", ["needs_clarification", "efficacy_unavailable", "claim_choice_invalid"]
)
def test_early_views_keep_display_text_none_and_commands_empty(kind):
    raw = result()
    raw.update(
        kind=kind,
        limits={"text_spent_usd": 0.1, "max_text_cost_usd": 0.3},
        clarification={
            "reason": "no_efficacy_confirmed",
            "available_efficacy": [],
            "options": ["none", "cancel"],
        },
        efficacy_unavailable={"reason": "failed"},
    )
    view = build_view(
        raw, plan_ids=[], hydrate=lambda ids: pytest.fail("must not hydrate")
    )
    assert view.display_text is None and view.ui_commands == []


@pytest.mark.parametrize("labels", ["present", "absent", "unlabelled"])
def test_evidence_cards_export_all_analysis_fields_in_contract_order(labels):
    from beautyads.api.ask_view import _CARD_FIELDS
    from beautyads.domain.labels import Angle, Claim, CtaType, Format, HookType, Talent

    fields = ("hook_type", "angle", "format", "talent", "cta_type", "claims")
    assert _CARD_FIELDS == (
        "evidence_id",
        "source",
        "url",
        "brand",
        "title",
        "published_at",
        "view_count",
        "like_count",
        *fields,
    )
    analysis = dict(
        zip(
            fields,
            [
                next(iter(HookType)).value,
                next(iter(Angle)).value,
                next(iter(Format)).value,
                next(iter(Talent)).value,
                next(iter(CtaType)).value,
                [next(iter(Claim)).value],
            ],
            strict=True,
        )
    )
    if labels == "unlabelled":
        analysis = {**dict.fromkeys(fields), "claims": []}
    rows = hydrate(result()["handoff"]["evidence_ids"])
    if labels != "absent":
        for row in rows:
            row.update(deepcopy(analysis))
    view = build_view(result(), plan_ids=["id"], hydrate=lambda ids: rows)
    cards = command(view, "show_evidence_cards")["cards"]
    assert len(cards) == len(rows)
    for card, row in zip(cards, rows, strict=True):
        assert set(card) == set(_CARD_FIELDS)
        assert tuple(card) == _CARD_FIELDS
        assert {key: card[key] for key in fields} == {
            key: row.get(key) for key in fields
        }
        assert card["view_count"] == 7 and "thumbnail" not in card
    cards[0]["claims"] = []
    assert rows[0].get("claims") == (None if labels == "absent" else analysis["claims"])
