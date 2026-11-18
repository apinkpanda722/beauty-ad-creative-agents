"""Code checks run before subjective scoring; all inputs are synthetic."""

import json
from copy import deepcopy

import pytest
from test_plan_checks import TERM, FakeCerts, FakeEvidence, plan_data, synthetic_rule

from beautyads.agents import evaluation
from beautyads.agents.evaluation import evaluate_plan
from beautyads.domain.evaluation import EvaluationScores
from beautyads.domain.labels import Claim
from beautyads.llm.structured import StructuredFailure, StructuredResult


class Support:
    def __init__(self, statuses=None):
        self.statuses, self.calls = statuses or {}, []

    def efficacy_support(self, url, claim):
        self.calls.append((url, claim))
        return self.statuses.get(str(claim), "unknown")


class Scorer:
    def __init__(self, model, fail=False):
        self.model, self.fail, self.calls = model, fail, []

    def generate(self, spec, **kwargs):
        self.calls.append((spec, deepcopy(kwargs)))
        value = (
            None
            if self.fail
            else spec.validate(
                {"differentiation": 3, "fit": 3, "rationale": "synthetic"}
            )
        )
        return StructuredResult(
            not self.fail,
            value,
            StructuredFailure.TOOL_NOT_CALLED if self.fail else None,
            2 if self.fail else 1,
            0.1,
            [],
        )


def run(fake, plan=None, support=None, **kwargs):
    return evaluate_plan(
        plan=plan or plan_data(),
        brief={"goal": "synthetic goal"},
        handoff={
            "conclusion": "synthetic comparison",
            "evidence_ids": plan_data()["evidence_ids"],
            "result_counts": [{"row_count": 5, "shown_count": 1}],
        },
        rules=[synthetic_rule()],
        evidence_index=FakeEvidence(),
        support=support or Support(),
        certs=FakeCerts(),
        structured=fake,
        model=fake.model,
        **kwargs,
    )


@pytest.mark.parametrize("model", ["claude-haiku-5-5", "claude-sonnet-5-5"])
@pytest.mark.parametrize("fails_check", [False, True])
def test_checks_before_scoring_and_scoring_has_only_two_criteria(
    monkeypatch, model, fails_check
):
    events = []
    original = evaluation.run_checks_on_dict

    def checks(*args, **kwargs):
        events.append("checks")
        return original(*args, **kwargs)

    monkeypatch.setattr(evaluation, "run_checks_on_dict", checks)
    fake = Scorer(model)
    generate = fake.generate

    def score(*args, **kwargs):
        events.append("score")
        return generate(*args, **kwargs)

    fake.generate = score
    report = run(fake, plan_data(title=TERM) if fails_check else None)
    assert events == ["checks", "score"]
    assert report.check_report["passed"] == (not fails_check)
    assert report.passed == (not fails_check)
    spec, options = fake.calls[0]
    assert spec.schema == EvaluationScores.model_json_schema()
    assert options["reasoning_effort"] is None
    assert options["purpose"] == "evaluate"
    assert not {"temperature", "thinking"} & options.keys()
    system, user = options["messages"]
    assert TERM not in system["content"]
    payload = json.loads(user["content"])
    assert set(payload["criteria"]) == {"differentiation", "fit"}
    assert set(payload["plan"]) == {
        "title",
        "hook_text",
        "scenes",
        "copy_lines",
        "image_brief",
        "hook_type",
        "angle",
        "format",
        "cta_type",
        "claimed_efficacy",
        "category",
    }
    assert payload["brief"]["goal"] == "synthetic goal"
    assert payload["research"]["conclusion"] == "synthetic comparison"
    for prohibited in (
        "forbidden_terms",
        "evidence_exists",
        "check_report",
        "efficacy_status",
        "rules",
    ):
        assert prohibited not in payload
        assert prohibited not in payload["criteria"]


@pytest.mark.parametrize("product_url", [None, "", " ", "https://example.invalid/p"])
def test_efficacy_status_summary_and_no_product_lookup(product_url):
    support = Support({"hydration": "supported", "soothing": "unknown"})
    report = run(
        Scorer("claude-haiku-5-5"),
        plan_data(
            product_url=product_url, claimed_efficacy=[Claim.hydration, Claim.soothing]
        ),
        support,
    )
    assert report.efficacy_status == {
        "hydration": "supported" if product_url and product_url.strip() else "unknown",
        "soothing": "unknown",
    }
    assert sum(report.efficacy_summary.values()) == 2
    assert report.passed
    assert report.unknown_count == report.check_report["unknown_count"]
    assert report.unknown_codes == report.check_report["unknown_codes"]
    if not product_url or not product_url.strip():
        assert not support.calls


def test_other_implementation_unsupported_is_preserved():
    report = run(
        Scorer("claude-haiku-5-5"),
        plan_data(claimed_efficacy=[Claim.hydration]),
        Support({"hydration": "unsupported"}),
    )
    assert report.efficacy_status == {"hydration": "unsupported"}
    assert not report.passed


def test_scoring_failure_is_reported():
    report = run(Scorer("claude-haiku-5-5", fail=True))
    assert report.scoring_failed and not report.passed
    assert report.scores is None and report.low_items == []


def test_invalid_plan_still_scored():
    report = run(
        Scorer("claude-haiku-5-5"), {"evidence_ids": [], "claimed_efficacy": []}
    )
    assert not report.passed and not report.scoring_failed


def test_default_factory_uses_haiku(monkeypatch):
    seen = []

    def factory(model):
        seen.append(model)
        return Scorer(model)

    monkeypatch.setattr(evaluation, "make_structured", factory)
    report = evaluate_plan(
        plan=plan_data(),
        brief={},
        handoff={"evidence_ids": plan_data()["evidence_ids"]},
        rules=[],
        evidence_index=FakeEvidence(),
        support=Support(),
        certs=FakeCerts(),
        structured=None,
    )
    assert seen == ["claude-haiku-5-5"] and report.passed


def test_fp_c14_evaluation_receives_closed_plan_values_and_anchored_scale():
    fake = Scorer("claude-haiku-5-5")
    source = plan_data()
    run(fake, source)
    _, options = fake.calls[0]
    system, user = options["messages"]
    payload = json.loads(user["content"])
    fields = {
        "hook_type",
        "angle",
        "format",
        "cta_type",
        "claimed_efficacy",
        "category",
    }
    for field in fields:
        assert payload["plan"][field] == source[field]
    assert set(payload["criteria"]) == {"differentiation", "fit"}
    for scale in payload["criteria"].values():
        assert all(f"{stage}점" in scale for stage in range(1, 6))
    assert "지배 패턴" in system["content"]
    assert all(
        f"plan.{field}" in system["content"]
        for field in ("hook_type", "angle", "format")
    )
    assert "내용 추측" in system["content"]
    assert (
        not {"evidence_exists", "forbidden_terms", "efficacy_status"}
        & payload["plan"].keys()
    )
    assert evaluation.EVALUATION_PROMPT_VERSION == "2026-11-18-2"


def test_fp_c14_evaluation_context_and_korean_copy_are_in_actual_messages():
    from beautyads.domain.supervisor import pattern_context

    context = pattern_context([], ["yt:a"])
    fake = Scorer("claude-haiku-5-5")
    evaluate_plan(
        plan=plan_data(),
        brief={},
        handoff={
            "evidence_ids": plan_data()["evidence_ids"],
            "pattern_context": context,
        },
        rules=[],
        evidence_index=FakeEvidence(),
        support=Support(),
        certs=FakeCerts(),
        structured=fake,
    )
    _, options = fake.calls[0]
    system, user = options["messages"]
    payload = json.loads(user["content"])
    assert payload["research"]["pattern_context"] == context
    for phrase in ("thin_pool", "dominant_axes", "200자", "극단 점수"):
        assert phrase in system["content"]
    for phrase in ("한국어 광고 카피", "번역투", "설명조", "실제 상황", "구어체"):
        assert phrase in payload["criteria"]["fit"]
