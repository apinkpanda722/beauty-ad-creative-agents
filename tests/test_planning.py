"""Inspect actual planning messages and schema through an injected generator."""

import json
from copy import deepcopy

import pytest
from test_plan_checks import plan_data

from beautyads.agents import planning
from beautyads.agents.planning import (
    PLANNING_REASONING_EFFORT,
    make_plan,
    strict_plan_schema,
)
from beautyads.agents.tool_messages import PARTIAL_RESULT_RULE, TOOL_DATA_RULE
from beautyads.domain.plan import Plan
from beautyads.llm.structured import StructuredFailure, StructuredResult


class Structured:
    def __init__(self, model="gpt-6.1-terra", fail=False):
        self.model, self.fail, self.calls = model, fail, []

    def generate(self, spec, **kwargs):
        self.calls.append((spec, deepcopy(kwargs)))
        value = None if self.fail else spec.validate(plan_data())
        return StructuredResult(
            not self.fail,
            value,
            StructuredFailure.SCHEMA_VIOLATION if self.fail else None,
            1,
            0.125,
            [],
        )


def assert_strict(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            assert schema.get("additionalProperties") is False
            assert set(schema.get("required", [])) == set(schema.get("properties", {}))
        for value in schema.values():
            assert_strict(value)
    elif isinstance(schema, list):
        for value in schema:
            assert_strict(value)


def test_schema_is_strict_and_preserves_original():
    before = Plan.model_json_schema()
    schema = strict_plan_schema()
    assert_strict(schema)
    assert schema["properties"] == before["properties"]
    assert Plan.model_json_schema() == before
    assert "#/$defs/" in json.dumps(schema)


@pytest.mark.parametrize(
    "rework",
    [
        None,
        {
            "check_issues": [
                {"code": "EVIDENCE_MISSING", "detail": "synthetic reason"}
            ],
            "low_items": [{"item": "fit", "score": 2, "rationale": "synthetic"}],
            "previous_plan": "PREVIOUS_FULL_PLAN",
        },
    ],
)
def test_planning_messages_and_options(rework):
    fake = Structured()
    profile = {
        "brand": "synthetic brand",
        "tone": "synthetic tone",
        "forbidden_terms": ["synthetic term"],
        "own_product_url": "https://example.invalid/own",
        "tenant_id": "private",
    }
    feedback = {
        "approved": {"count": 1},
        "rejected": {"count": 2},
        "rejected_reasons": ["사유 원문\n보존"],
    }
    handoff = {
        "conclusion": "synthetic",
        "evidence_ids": ["youtube:a"],
        "aggregates": {
            "count": 7,
            "rows": [
                {
                    "url": "COMPETITOR_URL",
                    "image": "COMPETITOR_IMAGE",
                    "hook": "question",
                }
            ],
        },
        "result_counts": [{"row_count": 7, "shown_count": 1}],
        "basis_notes": ["partial"],
        "unresolved": ["unknown"],
        "url": "COMPETITOR_URL",
        "image": "COMPETITOR_IMAGE",
        "raw_output": "RAW_CONTENT",
    }
    original = deepcopy((handoff, profile, rework))
    result = make_plan(
        brief={"goal": "synthetic"},
        handoff=handoff,
        profile=profile,
        feedback=feedback,
        rework=rework,
        structured=fake,
    )
    assert result.ok and isinstance(result.plan, dict)
    assert result.failure is None and result.cost_usd == 0.125
    spec, args = fake.calls[0]
    assert spec.name == "plan"
    assert_strict(spec.schema)
    assert fake.model == "gpt-6.1-terra"
    assert args["reasoning_effort"] == PLANNING_REASONING_EFFORT == "low"
    assert "temperature" not in args and "thinking" not in args
    assert args["purpose"] == "plan"
    assert args["caps"] == {"gemini": 12.0, "openai": 10.0, "anthropic": 8.0}
    system, user = args["messages"]
    assert (
        TOOL_DATA_RULE in system["content"] and PARTIAL_RESULT_RULE in system["content"]
    )
    assert "research.evidence_ids" in system["content"]
    payload = json.loads(user["content"])
    assert payload["research"]["evidence_ids"] == handoff["evidence_ids"]
    assert payload["research"]["result_counts"] == handoff["result_counts"]
    assert set(payload["research"]) == {
        "conclusion",
        "evidence_ids",
        "aggregates",
        "result_counts",
        "basis_notes",
        "unresolved",
    }
    assert payload["profile"] == {k: v for k, v in profile.items() if k != "tenant_id"}
    assert payload["feedback"] == feedback
    assert (
        payload["rework"] is None
        if rework is None
        else set(payload["rework"]) == {"check_issues", "low_items"}
    )
    for forbidden in (
        "COMPETITOR_URL",
        "COMPETITOR_IMAGE",
        "RAW_CONTENT",
        "PREVIOUS_FULL_PLAN",
    ):
        assert forbidden not in user["content"]
    assert (handoff, profile, rework) == original


def test_factory_and_structured_failure(monkeypatch):
    fake = Structured(fail=True)
    seen = []

    def factory(model):
        seen.append(model)
        return fake

    monkeypatch.setattr(planning, "make_structured", factory)
    result = make_plan(
        brief={}, handoff={}, profile={}, feedback=None, rework=None, structured=None
    )
    assert seen == ["gpt-6.1-terra"]
    assert not result.ok and result.plan is None
    assert result.failure == "SCHEMA_VIOLATION" and result.cost_usd == 0.125


def test_planning_prompt_distinguishes_internal_rework_from_external_data():
    fake = Structured()
    rework = {
        "low_items": [{"item": "differentiation", "rationale": "synthetic repair"}],
        "check_issues": [{"code": "EVIDENCE_MISSING"}],
    }
    make_plan(
        brief={}, handoff={}, profile={}, feedback=None, rework=rework, structured=fake
    )
    spec, options = fake.calls[0]
    system, user = options["messages"]
    for phrase in (
        "지배 패턴",
        "뚜렷이 다른 조합",
        "own_product_url",
        "확인된 효능",
        "빈 목록",
        "low_items",
        "check_issues",
        "대상이 아니다",
        "덮어쓰지 않는다",
        "근거 ID 제한",
        "분류 값 목록",
    ):
        assert phrase in system["content"]
    assert TOOL_DATA_RULE in system["content"]
    assert PARTIAL_RESULT_RULE in system["content"]
    assert json.loads(user["content"])["rework"] == rework
    assert fake.model == "gpt-6.1-terra"
    assert options["reasoning_effort"] == "low"
    assert spec.schema == strict_plan_schema()
    assert planning.PLANNING_PROMPT_VERSION == "2026-11-18-1"
