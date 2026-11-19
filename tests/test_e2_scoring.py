"""Synthetic E2/E5 scoring, blinding, paired statistics and human review."""

import csv
import hashlib
import json
import random
from copy import deepcopy
from difflib import SequenceMatcher
from functools import partial
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_plan_checks import plan_data

from beautyads.agents import evaluation
from beautyads.eval import e2_scoring as scoring
from beautyads.eval.evalset import RequestItem
from beautyads.llm.errors import DailyLimitReached, ErrorKind
from beautyads.llm.structured import StructuredResult, make_structured
from beautyads.obs.ledger import CostCapExceeded, LedgerEntry, append_entry


def request(index=0, axes=None):
    return RequestItem(
        id=f"request-{index}",
        split="test",
        tenant_id="test-synthetic",
        source_cq="synthetic",
        axes_used=axes or ["format"],
        needs_human_review=False,
        reviewed=True,
        message=f"합성 요청 {index}",
    )


def record(index=0, arm="supervisor", invalid=0, count=4, **changes):
    data = {
        "run_id": "synthetic-run",
        "item_id": request(index).id,
        "arm": arm,
        "tenant_id": "test-synthetic",
        "status": "plan",
        "plan": plan_data(evidence_ids=[f"yt:synthetic-{i}" for i in range(count)]),
        "check_report": {
            "issues": [
                {"code": "EVIDENCE_NOT_FOUND", "field": f"evidence_ids[{i}]"}
                for i in range(invalid)
            ]
        },
        "evidence_pool": [],
        "spent_usd": 0.01,
        "input_tokens": 100,
        "model_calls": 2,
        "latency_s": 1.0,
        "tool_calls": 3,
        "limit_hit": False,
        "code_commit": "synthetic-commit",
        "evalset_hash": "synthetic-hash",
        "axes_used_observed": ["claims"],
    }
    data.update(changes)
    return scoring.ArmRecord(**data)


class FakeStructured:
    model = "claude-sonnet-5-5"

    def __init__(self, effects=()):
        self.effects, self.calls = list(effects), []

    def generate(self, spec, **options):
        self.calls.append((spec, deepcopy(options)))
        effect = self.effects.pop(0) if self.effects else True
        if isinstance(effect, Exception):
            raise effect
        value = spec.validate(
            {"request_fit": 3, "distinctiveness": 3, "rationale": "합성"}
        )
        return StructuredResult(effect, value if effect else None, None, 1, 0, [])


def blind(n=3):
    reqs = [request(i) for i in range(n)]
    records = [record(i, arm) for i in range(n) for arm in scoring.ARMS]
    return scoring.blind_items(records, requests=reqs)


def population(n=10, fit=0, distinct=0, invalid_supervisor=0, invalid_single=0):
    reqs = [request(i) for i in range(n)]
    records, scores = [], {}
    for i, req in enumerate(reqs):
        scores[req.id] = {}
        for arm in scoring.ARMS:
            invalid = invalid_supervisor if arm == "supervisor" else invalid_single
            records.append(record(i, arm, invalid=invalid))
            scores[req.id][arm] = {
                "status": "scored",
                "request_fit": 3 + (fit if arm == "supervisor" else 0),
                "distinctiveness": 3 + (distinct if arm == "supervisor" else 0),
                "rationale": "合成",
            }
    return records, scores, reqs


def test_arm_record_contract_is_closed_and_json_serializable():
    row = record()
    assert tuple(scoring.ARMS) == ("supervisor", "single", "off")
    assert scoring.ArmRecord.model_validate_json(row.model_dump_json()) == row
    for update in (
        {"arm": "unknown"},
        {"status": "unknown"},
        {"extra": 1},
        {"spent_usd": float("nan")},
        {"input_tokens": -1},
    ):
        with pytest.raises(ValidationError):
            scoring.ArmRecord(**{**row.model_dump(), **update})


def test_blinding_whitelists_and_reproducible_shuffle(tmp_path):
    reqs = [request(i) for i in range(4)]
    records = [record(i, arm) for i in range(4) for arm in scoring.ARMS]
    for row in records:
        row.plan.update(
            model="SENTINEL_MODEL",
            scores="SENTINEL_SCORE",
            check_report="SENTINEL_CHECK",
            evidence_ids=["SENTINEL_EVIDENCE"],
            cost="SENTINEL_COST",
            arm="SENTINEL_ARM_supervisor",
            latency="SENTINEL_LATENCY",
        )
    items, key = scoring.blind_items(records, requests=reqs)
    assert (items, key) == scoring.blind_items(records, requests=reqs)
    other, other_key = scoring.blind_items(
        records, requests=reqs, seed=scoring.SCORING_SEED + 1
    )
    assert list(key) != list(other_key)
    assert [key[r["arm_hidden_id"]]["item_id"] for r in items] != [
        other_key[r["arm_hidden_id"]]["item_id"] for r in other
    ]
    fake = FakeStructured()
    scores = scoring.score_plans(
        items, structured=fake, ledger_path=tmp_path / "ledger"
    )
    assert len(fake.calls) == len(records)
    for spec, options in fake.calls:
        content = json.dumps(options["messages"], ensure_ascii=False)
        assert "SENTINEL_" not in content
        assert not any(
            name in content
            for name in (*scoring.ARMS, "claude-sonnet-5-5", "gpt-6.1-terra")
        )
        assert (
            not {"key", "arm", "scores", "check_report", "evidence_ids"}
            & options.keys()
        )
        assert options.get("reasoning_effort") is None
        assert "temperature" not in options
        assert spec.name == "e2_scores"
        payload = json.loads(options["messages"][-1]["content"])
        assert set(payload) == {"request", "plan", "rubric"}
        assert set(payload["plan"]) == {
            "title",
            "hook_text",
            "scenes",
            "copy_lines",
            "image_brief",
            "hook_type",
            "angle",
            "format",
            "claimed_efficacy",
        }
    revealed = scoring.reveal_scores(scores, key)
    assert set(revealed) == {req.id for req in reqs}
    assert all(set(arms) == set(scoring.ARMS) for arms in revealed.values())
    for item in items:
        source = key[item["arm_hidden_id"]]
        expected = hashlib.sha256(
            f"{scoring.SCORING_SEED}:{source['item_id']}:{source['arm']}".encode()
        ).hexdigest()[:12]
        assert item["arm_hidden_id"] == expected
        assert item["order_seed"] == scoring.SCORING_SEED


def test_blinding_skips_no_plan_and_rejects_duplicate_records():
    items, key = scoring.blind_items(
        [record(plan=None, status="failed")], requests=[request()]
    )
    assert items == [] and key == {}
    with pytest.raises(ValueError, match="ARM_RECORD_DUPLICATE"):
        scoring.blind_items([record(), record()], requests=[request()])


def test_rubric_has_distinct_wording_and_all_scale_anchors():
    original = evaluation._SYSTEM + "\n" + "\n".join(evaluation._CRITERIA.values())
    separate = scoring._SYSTEM + "\n" + "\n".join(scoring.E2_RUBRIC.values())
    assert (
        SequenceMatcher(None, original, separate, autojunk=False)
        .find_longest_match()
        .size
        < 20
    )
    assert set(scoring.E2_RUBRIC) == {"request_fit", "distinctiveness"}
    for description in scoring.E2_RUBRIC.values():
        assert all(f"{i}점" in description for i in range(1, 6))
    assert scoring.E2_SCORING_PROMPT_VERSION
    assert (
        scoring.e2_rubric_sha256()
        == hashlib.sha256(
            (
                json.dumps(
                    scoring.E2_RUBRIC,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
                + scoring._SYSTEM
            ).encode()
        ).hexdigest()
    )


def test_cap_checked_immediately_before_each_call_and_stops(monkeypatch, tmp_path):
    items, _ = blind()
    events = []
    fake = FakeStructured()
    generate = fake.generate

    def check(path, purpose, cap):
        assert path == tmp_path / "ledger" and purpose == "e2-score"
        assert cap == scoring.E2_SCORE_PURPOSE_CAP
        events.append("check")
        if events.count("check") == 3:
            raise CostCapExceeded("purpose:e2-score", cap, cap)

    def call(*args, **options):
        events.append("call")
        return generate(*args, **options)

    monkeypatch.setattr(scoring, "check_purpose_cap", check)
    fake.generate = call
    result = scoring.score_plans(
        items, structured=fake, ledger_path=tmp_path / "ledger"
    )
    assert events == ["check", "call", "check", "call", "check"]
    assert [r["status"] for r in result] == ["scored"] * 2 + ["SCORING_CAP_REACHED"] * (
        len(items) - 2
    )


def test_real_ledger_cap_boundary_and_purpose_family(tmp_path):
    items, _ = blind(1)
    path = tmp_path / "ledger"
    append_entry(
        path,
        LedgerEntry(
            ts="2026-11-19T00:00:00Z",
            provider="anthropic",
            model="synthetic",
            purpose="e2-score-part",
            cost_usd=scoring.E2_SCORE_PURPOSE_CAP,
            cost_source="computed",
        ),
    )
    fake = FakeStructured()
    result = scoring.score_plans(
        items, structured=fake, ledger_path=path, purpose="e2-score-batch"
    )
    assert not fake.calls
    assert all(row["status"] == "SCORING_CAP_REACHED" for row in result)
    with pytest.raises(ValueError, match="SCORING_PURPOSE_INVALID"):
        scoring.score_plans(items, structured=fake, ledger_path=path, purpose="other")


def test_scoring_failure_continues_and_daily_limit_stops(tmp_path):
    items, _ = blind(1)
    fake = FakeStructured([False, ValueError("private synthetic body"), True])
    result = scoring.score_plans(
        items, structured=fake, ledger_path=tmp_path / "ledger"
    )
    assert [row["status"] for row in result] == [
        "SCORE_FAILED",
        "SCORE_FAILED",
        "scored",
    ]
    assert "private" not in json.dumps(result)
    fake = FakeStructured(
        [DailyLimitReached(kind=ErrorKind.DAILY_LIMIT, code="DAILY_LIMIT")]
    )
    result = scoring.score_plans(
        items, structured=fake, ledger_path=tmp_path / "ledger"
    )
    assert len(fake.calls) == 1
    assert all(row["status"] == "SCORING_DAILY_LIMIT" for row in result)


def test_injected_sonnet_wrapper_emits_no_effort_or_temperature(tmp_path):
    items, _ = blind(1)
    calls = []
    generator = make_structured("claude-sonnet-5-5")

    def complete(**options):
        calls.append(options)
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "synthetic",
                                "type": "function",
                                "function": {
                                    "name": "e2_scores",
                                    "arguments": json.dumps(
                                        {
                                            "request_fit": 2,
                                            "distinctiveness": 4,
                                            "rationale": "合成",
                                        }
                                    ),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    wrapped = SimpleNamespace(
        model=generator.model,
        generate=partial(
            generator.generate,
            completion_fn=complete,
            api_key=uuid4().hex,
            caps={"anthropic": 8.0},
        ),
    )
    result = scoring.score_plans(
        items, structured=wrapped, ledger_path=tmp_path / "ledger"
    )
    assert all(row["status"] == "scored" for row in result)
    assert calls and all(
        not {"reasoning_effort", "temperature", "thinking"} & call.keys()
        for call in calls
    )
    fake = FakeStructured()
    fake.model = "claude-haiku-5-5"
    with pytest.raises(ValueError, match="SCORING_MODEL_INVALID"):
        scoring.score_plans(items, structured=fake, ledger_path=tmp_path / "ledger")


def test_scoring_schema_rejects_invalid_values(tmp_path):
    items, _ = blind(1)
    fake = FakeStructured()
    scoring.score_plans(items, structured=fake, ledger_path=tmp_path / "ledger")
    spec = fake.calls[0][0]
    for changes in (
        {"request_fit": 0},
        {"request_fit": 6},
        {"request_fit": True},
        {"distinctiveness": 1.5},
        {"rationale": "x" * 201},
        {"extra": 1},
    ):
        with pytest.raises(ValidationError):
            spec.validate(
                {"request_fit": 3, "distinctiveness": 3, "rationale": "합성", **changes}
            )


def test_bootstrap_determinism_percentile_and_constant_input():
    values = [-2, -1, 0, 1, 2]
    first = scoring.bootstrap_ci(values)
    assert first == scoring.bootstrap_ci(values)
    assert first[0] <= sum(values) / len(values) <= first[1]
    assert scoring.bootstrap_ci([2] * 10) == (2, 2)
    seed, resamples = scoring.SCORING_SEED, 31
    rng = random.Random(seed)
    means = sorted(
        sum(rng.choices(values, k=len(values))) / len(values) for _ in range(resamples)
    )
    assert scoring.bootstrap_ci(
        values, seed=seed, resamples=resamples, confidence=0.8
    ) == pytest.approx((means[3], means[27]))
    with pytest.raises(ValueError, match="BOOTSTRAP_EMPTY"):
        scoring.bootstrap_ci([])


def test_evidence_validity_uses_positions_and_only_two_codes():
    row = record(count=4)
    row.check_report["issues"] = [
        {"code": code, "field": field}
        for code, field in [
            ("EVIDENCE_NOT_FOUND", "evidence_ids[0]"),
            ("EVIDENCE_NOT_IN_HANDOFF", "evidence_ids[0]"),
            ("EVIDENCE_NOT_IN_HANDOFF", "evidence_ids[2]"),
            ("PROHIBITED_EXPRESSION", "evidence_ids[1]"),
            ("EVIDENCE_NOT_FOUND", "evidence_ids[99]"),
        ]
    ]
    assert scoring.evidence_validity(row) == 2 / 4
    assert scoring.evidence_validity(record(count=0)) == 0
    with pytest.raises(ValueError, match="EVIDENCE_UNDEFINED"):
        scoring.evidence_validity(record(plan=None))


@pytest.mark.parametrize(
    "fit,distinct,invalid_sup,invalid_single,expected",
    [
        (1, 0, 0, 0, "supervisor_better"),
        (-1, 0, 0, 0, "single_better"),
        (1, -1, 0, 0, "mixed"),
        (0, 0, 0, 0, "no_difference_found"),
        (0, 0, 0, 1, "supervisor_better"),
        (0, 0, 1, 0, "single_better"),
    ],
)
def test_e2_verdict_branches(fit, distinct, invalid_sup, invalid_single, expected):
    records, scores, reqs = population(
        fit=fit,
        distinct=distinct,
        invalid_supervisor=invalid_sup,
        invalid_single=invalid_single,
    )
    result = scoring.analyze(records, scores=scores, requests=reqs)
    assert result["verdict_e2"] == expected
    for metric in result["e2"]["metrics"].values():
        assert metric["n"] == len(reqs) and metric["excluded"] == 0


def test_exclusions_are_per_metric_and_small_sample_undecidable(monkeypatch):
    records, scores, reqs = population(n=12, fit=1)
    records[0].plan = None
    records[0].status = "no_evidence"
    scores[reqs[1].id]["single"] = {"status": "SCORE_FAILED"}
    records = [
        r for r in records if not (r.item_id == reqs[2].id and r.arm == "single")
    ]
    monkeypatch.setattr(scoring, "bootstrap_ci", lambda values: (0, 0))
    result = scoring.analyze(records, scores=scores, requests=reqs)
    metrics = result["e2_complete_case"]["metrics"]
    assert metrics["evidence_validity"]["n"] == 10
    assert metrics["evidence_validity"]["excluded"] == 2
    assert metrics["request_fit"]["n"] == 9
    assert metrics["request_fit"]["excluded"] == 3
    assert result["verdict_e2_complete_case"] == "undecidable"
    assert result["e2_complete_case"]["excluded_no_plan"] == 1
    assert result["e2_complete_case"]["n"] == 9
    assert result["e2_complete_case"]["excluded"] == 3
    assert result["e2_complete_case"]["verdict"] == "undecidable"
    primary = result["e2"]
    assert primary["metrics"]["evidence_validity"]["n"] == 11
    assert primary["metrics"]["evidence_validity"]["excluded"] == 1
    for name in ("request_fit", "distinctiveness"):
        assert primary["metrics"][name]["n"] == 10
        assert primary["metrics"][name]["excluded"] == 2
    assert primary["n"] == 10 and primary["excluded"] == 2
    assert primary["not_run"] == 1
    assert primary["imputed_no_plan"] == {"supervisor": 1, "single": 0}
    assert "excluded_no_plan" not in primary
    assert result["verdict_e2"] == "no_difference_found"
    records, scores, reqs = population(n=9, fit=1)
    assert (
        scoring.analyze(records, scores=scores, requests=reqs)["verdict_e2"]
        == "undecidable"
    )


@pytest.mark.parametrize(
    "tokens_ok,evidence_ok,expected",
    [
        (True, True, "cost_reduced_evidence_kept"),
        (False, True, "not_met:tokens"),
        (True, False, "not_met:evidence"),
        (False, False, "not_met:both"),
    ],
)
def test_e5_thresholds(tokens_ok, evidence_ok, expected):
    records, scores, reqs = population()
    off_tokens = 10000
    reduction = scoring.E5_MIN_TOKEN_REDUCTION + (0.01 if tokens_ok else -0.01)
    # A single invalid ID out of sufficiently many gives a deterministic
    # validity difference just above or below the imported noninferiority bound.
    count = 100
    invalid = round(-scoring.E5_MIN_VALIDITY_LOWER * count) + (-1 if evidence_ok else 1)
    records = [
        record(
            i,
            arm,
            count=count,
            invalid=invalid if arm == "supervisor" else 0,
            input_tokens=round(off_tokens * (1 - reduction))
            if arm == "supervisor"
            else off_tokens,
        )
        for i in range(len(reqs))
        for arm in scoring.ARMS
    ]
    result = scoring.analyze(records, scores=scores, requests=reqs)
    assert result["verdict_e5"] == expected
    assert result["e5"]["token_reduction"] == pytest.approx(reduction)


def test_e5_exact_boundaries_and_missing_denominator(monkeypatch):
    records, scores, reqs = population()
    denominator = 10000
    for row in records:
        row.input_tokens = (
            round(denominator * (1 - scoring.E5_MIN_TOKEN_REDUCTION))
            if row.arm == "supervisor"
            else denominator
        )
    monkeypatch.setattr(
        scoring,
        "bootstrap_ci",
        lambda *args, **kwargs: (scoring.E5_MIN_VALIDITY_LOWER, 0),
    )
    result = scoring.analyze(records, scores=scores, requests=reqs)
    assert result["verdict_e5"] == "not_met:evidence"
    monkeypatch.setattr(
        scoring,
        "bootstrap_ci",
        lambda *args, **kwargs: (scoring.E5_MIN_VALIDITY_LOWER + 0.001, 0),
    )
    assert (
        scoring.analyze(records, scores=scores, requests=reqs)["verdict_e5"]
        == "cost_reduced_evidence_kept"
    )
    for row in records:
        row.input_tokens = 0
    assert (
        scoring.analyze(records, scores=scores, requests=reqs)["verdict_e5"]
        == "not_met:tokens"
    )


@pytest.mark.parametrize("field", ["code_commit", "evalset_hash", "run_id"])
def test_run_identity_mismatch(field):
    records, scores, reqs = population()
    setattr(records[-1], field, "different")
    with pytest.raises(scoring.RunIdentityMismatch):
        scoring.analyze(records, scores=scores, requests=reqs)


def test_mixed_scoring_batches_are_rejected():
    records, scores, reqs = population()
    for arms in scores.values():
        for score in arms.values():
            score["scoring_run_id"] = "first"
    scores[reqs[0].id]["single"]["scoring_run_id"] = "second"
    with pytest.raises(scoring.RunIdentityMismatch):
        scoring.analyze(records, scores=scores, requests=reqs)


def test_efficiency_summary_and_nearest_rank_include_failed_runs():
    records, scores, reqs = population(n=20)
    for index, row in enumerate(r for r in records if r.arm == "supervisor"):
        row.latency_s = index + 1
        row.spent_usd = 2
        row.model_calls = 5
        row.tool_calls = 8
    records[0].plan = None
    result = scoring.analyze(records, scores=scores, requests=reqs)
    desc = result["e2"]["descriptive"]
    assert desc["arms"]["supervisor"]["latency_s"] == {
        "mean": 10.5,
        "p50": 10,
        "p95": 19,
        "n": 20,
    }
    assert desc["differences"]["model_calls"]["mean_diff"] == 5 - 2
    assert desc["differences"]["tool_calls"]["mean_diff"] == 8 - 3
    assert "verdict" not in json.dumps(desc)
    assert "대가로 그대로 적는다" in desc["note"]


def test_strata_use_preassigned_axes_and_claims_bias_is_separate():
    n = scoring.MIN_STRATUM_N
    records, scores, reqs = population(n=2 * n - 1)
    for req in reqs[n:]:
        req.axes_used[:] = ["claims"]
    result = scoring.analyze(
        records,
        scores=scores,
        requests=reqs,
        claim_matches=[{"arm": "supervisor", "claim_match": "no_match"}],
    )
    reliable, unreliable = (result["strata"][s] for s in ("reliable", "unreliable"))
    assert reliable["request_n"] == n and reliable["status"] == "descriptive_only"
    assert unreliable["request_n"] == n - 1 and unreliable["status"] == "undecidable"
    assert "라벨 신뢰도 낮음" in unreliable["note"]
    assert reliable["arms"]["supervisor"]["n"] == n
    bias = result["claim_bias_check"]
    assert "1인 라벨링" in bias["note"] and "편향 점검" in bias["note"]
    assert bias["arms"]["supervisor"]["no_match"] == 1
    without = scoring.analyze(records, scores=scores, requests=reqs)
    assert result["verdict_e2"] == without["verdict_e2"]
    assert result["verdict_e5"] == without["verdict_e5"]


@pytest.fixture
def point_ci(monkeypatch):
    """Fix synthetic CIs at their means to isolate missingness and verdict rules."""
    monkeypatch.setattr(
        scoring, "bootstrap_ci", lambda values: (sum(values) / len(values),) * 2
    )


def test_worst_constants_match_score_schema_lower_bounds():
    assert scoring.WORST_REQUEST_FIT == scoring.WORST_DISTINCTIVENESS == 1
    assert scoring.WORST_EVIDENCE_VALIDITY == 0.0
    data = {"request_fit": 1, "distinctiveness": 1, "rationale": ""}
    assert scoring._Scores.model_validate(data).model_dump() == data
    for name in ("request_fit", "distinctiveness"):
        with pytest.raises(ValidationError):
            scoring._Scores.model_validate({**data, name: 0})


@pytest.mark.parametrize("failed_arm", scoring.ARMS)
def test_one_failed_arm_enters_primary_at_worst_scores(point_ci, failed_arm):
    records, scores, reqs = population(n=1)
    for row in records:
        row.check_report = record(invalid=1).check_report
        if row.arm == failed_arm:
            row.plan, row.status = None, "no_evidence"
            # Failed plans have no blinded score; even a stale score is ignored.
            scores[reqs[0].id][row.arm] = {"status": "scored", "request_fit": 0}
    result = scoring.analyze(records, scores=scores, requests=reqs)
    for block, right in (("e2", "single"), ("e5", "off")):
        sign = 1 if failed_arm == "supervisor" else -1 if failed_arm == right else 0
        validity = (
            result[block]["metrics"]["evidence_validity"]
            if block == "e2"
            else result[block]["evidence_validity"]
        )
        expected = sign * (scoring.WORST_EVIDENCE_VALIDITY - 0.75)
        assert validity == {
            "mean_diff": expected,
            "ci": (expected, expected),
            "n": 1,
            "excluded": 0,
        }
        assert result[block]["imputed_no_plan"] == {
            arm: int(arm == failed_arm) for arm in ("supervisor", right)
        }
        assert result[block]["not_run"] == 0
        assert result[f"{block}_complete_case"]["excluded_no_plan"] == abs(sign)
        assert "excluded_no_plan" not in result[block]
    sign = 1 if failed_arm == "supervisor" else -1 if failed_arm == "single" else 0
    for name, worst in (
        ("request_fit", scoring.WORST_REQUEST_FIT),
        ("distinctiveness", scoring.WORST_DISTINCTIVENESS),
    ):
        metric = result["e2"]["metrics"][name]
        expected = sign * (worst - 3)
        assert metric == {
            "mean_diff": expected,
            "ci": (expected, expected),
            "n": 1,
            "excluded": 0,
        }


def test_both_failed_arms_enter_as_zero_differences(point_ci):
    records = [record(arm=arm, plan=None, status="failed") for arm in scoring.ARMS]
    result = scoring.analyze(records, scores={}, requests=[request()])
    zero = {"mean_diff": 0, "ci": (0, 0), "n": 1, "excluded": 0}
    assert all(metric == zero for metric in result["e2"]["metrics"].values())
    assert result["e5"]["evidence_validity"] == zero
    for block, right in (("e2", "single"), ("e5", "off")):
        assert result[block]["imputed_no_plan"] == {"supervisor": 1, right: 1}
        assert result[f"{block}_complete_case"]["excluded_no_plan"] == 1


@pytest.mark.parametrize("missing_arm", scoring.ARMS)
def test_missing_records_are_not_run_and_never_imputed(point_ci, missing_arm):
    records, scores, reqs = population(n=3)
    records = [
        r for r in records if not (r.item_id == reqs[1].id and r.arm == missing_arm)
    ]
    # A wholly unattempted request also counts once per comparison.
    reqs.append(request(3))
    result = scoring.analyze(records, scores=scores, requests=reqs)
    for block, right in (("e2", "single"), ("e5", "off")):
        missing = 1 + int(missing_arm in ("supervisor", right))
        assert result[block]["not_run"] == missing
        assert result[block]["n"] == 4 - missing
        assert result[block]["excluded"] == missing
        assert result[block]["imputed_no_plan"] == {"supervisor": 0, right: 0}
    for metric in result["e2"]["metrics"].values():
        assert metric["n"] == result["e2"]["n"]


@pytest.mark.parametrize(
    "score_status", [None, "SCORE_FAILED", "SCORING_CAP_REACHED", "SCORING_DAILY_LIMIT"]
)
@pytest.mark.parametrize("failed_plan", [False, True])
def test_unscored_plans_exclude_quality_only(point_ci, score_status, failed_plan):
    records, scores, reqs = population(n=1)
    if failed_plan:
        records[1].plan, records[1].status = None, "failed"
        scores[reqs[0].id].pop("single")
    if score_status is None:
        scores[reqs[0].id].pop("supervisor")
    else:
        scores[reqs[0].id]["supervisor"] = {"status": score_status}
    result = scoring.analyze(records, scores=scores, requests=reqs)
    for name in ("request_fit", "distinctiveness"):
        assert result["e2"]["metrics"][name] == {
            "mean_diff": None,
            "ci": None,
            "n": 0,
            "excluded": 1,
        }
    assert result["e2"]["metrics"]["evidence_validity"]["n"] == 1
    assert result["e2"]["not_run"] == 0
    assert result["e2"]["imputed_no_plan"] == {
        "supervisor": 0,
        "single": int(failed_plan),
    }
    assert result["failure_rates"]["supervisor"]["no_plan"] == 0


@pytest.mark.parametrize("name", ["request_fit", "distinctiveness"])
@pytest.mark.parametrize("other_failed", [False, True])
def test_external_scored_values_still_require_schema(point_ci, name, other_failed):
    records, scores, reqs = population(n=1)
    if other_failed:
        records[1].plan, records[1].status = None, "failed"
        scores[reqs[0].id].pop("single")
    scores[reqs[0].id]["supervisor"][name] = 0
    with pytest.raises(ValidationError):
        scoring.analyze(records, scores=scores, requests=reqs)


@pytest.mark.parametrize("arm", scoring.ARMS)
def test_failure_rates_count_every_no_plan_status_and_unpaired_attempt(point_ci, arm):
    records, scores, reqs = population(n=5)
    statuses = ("no_evidence", "failed", "limit", "out_of_scope")
    for i, status in enumerate(statuses):
        row = next(r for r in records if r.item_id == reqs[i].id and r.arm == arm)
        row.plan, row.status = None, status
        scores[reqs[i].id].pop(arm)
    result = scoring.analyze(records, scores=scores, requests=reqs)
    assert result["failure_rates"][arm] == {
        "records": 5,
        "no_plan": 4,
        "rate": 4 / 5,
        "by_status": dict.fromkeys(statuses, 1),
    }
    for other in set(scoring.ARMS) - {arm}:
        assert result["failure_rates"][other] == {
            "records": 5,
            "no_plan": 0,
            "rate": 0,
            "by_status": {},
        }
    for block, right in (("e2", "single"), ("e5", "off")):
        assert result[block]["imputed_no_plan"] == {
            name: 4 if name == arm else 0 for name in ("supervisor", right)
        }
        sign = 1 if arm == "supervisor" else -1 if arm == right else 0
        validity = (
            result[block]["metrics"]["evidence_validity"]
            if block == "e2"
            else result[block]["evidence_validity"]
        )
        assert validity["mean_diff"] == sign * (-4 / 5)
        assert validity["n"] == 5 and validity["excluded"] == 0
    sign = 1 if arm == "supervisor" else -1 if arm == "single" else 0
    for name in ("request_fit", "distinctiveness"):
        metric = result["e2"]["metrics"][name]
        assert metric["mean_diff"] == sign * (-8 / 5)
        assert metric["n"] == 5 and metric["excluded"] == 0
    only_arm = [record(arm=arm, plan=None, status="limit")]
    rates = scoring.analyze(only_arm, scores={}, requests=[request()])["failure_rates"]
    assert rates[arm] == {
        "records": 1,
        "no_plan": 1,
        "rate": 1,
        "by_status": {"limit": 1},
    }
    for other in set(scoring.ARMS) - {arm}:
        assert rates[other] == {
            "records": 0,
            "no_plan": 0,
            "rate": None,
            "by_status": {},
        }


def test_survivor_bias_is_visible_in_complete_case_sensitivity(point_ci):
    records, scores, reqs = population(n=20, fit=1, distinct=1)
    for row in records:
        row.input_tokens = 50 if row.arm == "supervisor" else 100
        if row.arm == "supervisor" and row.item_id in {r.id for r in reqs[:10]}:
            row.plan, row.status = None, "no_evidence"
            scores[row.item_id].pop(row.arm)
    result = scoring.analyze(records, scores=scores, requests=reqs)
    assert result["e2"]["n"] == 20 and result["e2_complete_case"]["n"] == 10
    assert result["e2"]["metrics"]["request_fit"]["mean_diff"] == -0.5
    assert result["e2_complete_case"]["metrics"]["request_fit"]["mean_diff"] == 1
    assert result["verdict_e2_complete_case"] == "supervisor_better"
    assert result["e2_complete_case"]["verdict"] == "supervisor_better"
    assert result["verdict_e2"] == "single_better"
    assert result["verdicts_agree"]["e2"] is False
    assert result["verdict_e5"] == "not_met:evidence"
    assert result["verdict_e5_complete_case"] == "cost_reduced_evidence_kept"
    assert result["e5_complete_case"]["verdict"] == result["verdict_e5_complete_case"]
    assert result["verdicts_agree"]["e5"] is False


@pytest.mark.parametrize("failed_arm", ["supervisor", "off"])
def test_e5_token_totals_do_not_depend_on_plan_success(point_ci, failed_arm):
    records, scores, reqs = population(n=2)
    for row in records:
        row.input_tokens = 50 if row.arm == "supervisor" else 100
    before = scoring.analyze(records, scores=scores, requests=reqs)
    for row in records:
        if row.arm == failed_arm:
            row.plan, row.status = None, "failed"
            scores[row.item_id].pop(row.arm)
    after = scoring.analyze(records, scores=scores, requests=reqs)
    for key, expected in (
        ("token_reduction", 0.5),
        ("on_input_tokens", 100),
        ("off_input_tokens", 200),
    ):
        assert before["e5"][key] == after["e5"][key] == expected
    for key in ("n", "excluded", "descriptive"):
        assert before["e5"][key] == after["e5"][key]


def test_no_failures_give_identical_primary_and_complete_case(point_ci):
    records, scores, reqs = population(fit=1)
    result = scoring.analyze(records, scores=scores, requests=reqs)
    for name in ("metrics", "n", "excluded"):
        assert result["e2"][name] == result["e2_complete_case"][name]
    assert (
        result["e5"]["evidence_validity"]
        == result["e5_complete_case"]["evidence_validity"]
    )
    assert (
        result["e2_complete_case"]["excluded_no_plan"]
        == result["e5_complete_case"]["excluded_no_plan"]
        == 0
    )
    for block in ("e2", "e5"):
        assert result[f"verdict_{block}"] == result[f"verdict_{block}_complete_case"]
        assert result[f"{block}_complete_case"]["verdict"] == result[f"verdict_{block}"]
    assert result["verdicts_agree"] == {"e2": True, "e5": True}


def write_labels(path, labels):
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    for row, value in zip(rows, labels, strict=True):
        row["claim_match"] = value
        row["claim_match_note"] = "합성 사유"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return fields, rows


def test_claim_sheet_blind_columns_instructions_and_round_trip(tmp_path):
    records = [record(i, arm) for i in range(3) for arm in scoring.ARMS]
    texts = {
        eid: "합성 소재 제목·브랜드"
        for row in records
        for eid in row.plan["evidence_ids"]
    }
    paths = scoring.build_claim_sheet(
        records,
        evidence_texts=texts,
        seed=scoring.SCORING_SEED,
        size=5,
        out_dir=tmp_path / "first",
    )
    assert paths["sheet"].name == "claim_sheet.csv"
    assert paths["key"].name == "claim_sheet_key.json"
    assert paths["sheet"].parent != paths["key"].parent
    text = paths["sheet"].read_text()
    assert not any(arm in text for arm in scoring.ARMS)
    assert not any(row.plan["title"] in text for row in records)
    fields, rows = write_labels(
        paths["sheet"], ["match", "partial", "no_match", "match", "partial"]
    )
    assert fields == [
        "item_id",
        "claim",
        "evidence_text",
        "claim_match",
        "claim_match_note",
    ]
    assert len(rows) == 5
    instructions = paths["instructions"].read_text()
    assert all(
        word in instructions for word in ("칸의 뜻", "칸별 기준", "예시", "기록 방법")
    )
    assert all(
        word in instructions
        for word in ("1인 라벨링", "partial", "빈 칸", "두 칸만", "따로 보관")
    )
    loaded = scoring.load_claim_matches(paths["sheet"], paths["key"])
    assert len(loaded) == len(rows)
    assert all(row["arm"] in scoring.ARMS for row in loaded)
    other = scoring.build_claim_sheet(
        records,
        evidence_texts=texts,
        seed=scoring.SCORING_SEED,
        size=5,
        out_dir=tmp_path / "other",
    )
    assert paths["key"].read_bytes() == other["key"].read_bytes()
    with other["sheet"].open() as stream:
        assert [r["item_id"] for r in csv.DictReader(stream)] == [
            r["item_id"] for r in rows
        ]


@pytest.mark.parametrize("label", ["", "unknown", "MATCH", " match "])
def test_load_claim_matches_rejects_invalid_values(tmp_path, label):
    row = record(count=1)
    paths = scoring.build_claim_sheet(
        [row],
        evidence_texts={"yt:synthetic-0": "합성"},
        seed=scoring.SCORING_SEED,
        out_dir=tmp_path,
    )
    write_labels(paths["sheet"], [label])
    with pytest.raises(ValueError, match="CLAIM_MATCH_INVALID"):
        scoring.load_claim_matches(paths["sheet"], paths["key"])


def test_load_claim_matches_rejects_unknown_or_duplicate_ids(tmp_path):
    paths = scoring.build_claim_sheet(
        [record(count=1)],
        evidence_texts={"yt:synthetic-0": "합성"},
        seed=scoring.SCORING_SEED,
        out_dir=tmp_path,
    )
    fields, rows = write_labels(paths["sheet"], ["match"])
    for changed in ([{**rows[0], "item_id": "unknown"}], rows * 2, []):
        with paths["sheet"].open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(changed)
        with pytest.raises(ValueError, match="CLAIM_SHEET_INVALID"):
            scoring.load_claim_matches(paths["sheet"], paths["key"])
