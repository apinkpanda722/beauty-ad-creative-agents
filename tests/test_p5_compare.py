"""Offline preregistered comparison contracts; never read real interim data."""

import hashlib
import json
import re
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from beautyads.eval import p5_compare as compare
from beautyads.llm.chat import ChatResult
from beautyads.llm.structured import StructuredResult, StructuredStats
from beautyads.obs.ledger import LedgerEntry, append_entry, purpose_total
from beautyads.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
SECRET = "synthetic-private-credential"
PROSE = "synthetic-plan-prose"


def forbidden(*args, **kwargs):
    pytest.fail("external boundary must not run")


def plan():
    return {
        "title": PROSE,
        "hook_type": "question",
        "hook_text": PROSE,
        "scenes": [PROSE],
        "copy_lines": [PROSE],
        "image_brief": None,
        "cta_type": "none",
        "angle": "problem_solution",
        "format": "demo",
        "category": "serum_ampoule",
        "product_url": None,
        "claimed_efficacy": [],
        "evidence_ids": ["youtube:one"],
    }


def handoff():
    return {
        "conclusion": "synthetic-handoff",
        "evidence_ids": ["youtube:one"],
        "aggregates": {},
        "confidence": "low",
        "unresolved": [],
        "status": "ok",
        "no_evidence_tools": [],
        "basis_notes": [],
        "structured_failure_rate": 0,
    }


class FakeStructured:
    def __init__(self, model, style, guard, seen):
        self.model, self.style, self.guard, self.seen = model, style, guard, seen
        self.stats = StructuredStats()

    def generate(self, spec, **kw):
        self.guard()
        self.seen.append((self.model, self.style, kw))
        assert "temperature" not in kw and "thinking" not in kw
        value = (
            plan()
            if spec.name == "plan"
            else {"differentiation": 3, "fit": 4, "rationale": SECRET}
        )
        call = ChatResult(
            SECRET,
            [],
            "stop",
            {
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "completion_tokens_details": {"reasoning_tokens": 2},
                "prompt_tokens_details": {"cached_tokens": 5},
                "cache_read_input_tokens": 5,
            },
            0.001,
            "price_table",
            {"api_key": SECRET, "thought_signatures": SECRET},
        )
        return StructuredResult(True, value, None, 1, 0.001, [call])


class FakeGraph:
    def run(self, query, params=None):
        if "unit_list_price" in query:
            rows = [{"unit_list_price": 100}]
        elif "creative_id" in query:
            rows = [{"creative_id": "youtube:one"}]
        else:
            rows = []
        return SimpleNamespace(records=rows)

    def close(self):
        pass


def prepared(tmp_path):
    base = tmp_path / "comparison"
    (base / "inputs").mkdir(parents=True, exist_ok=True)
    lines = ["## 7. 입력 해시 기록"]
    for index in range(1, 6):
        path = base / "inputs" / f"{index:02}.json"
        path.write_text(json.dumps(handoff()), encoding="utf-8")
        lines.append(f"{path.name} {hashlib.sha256(path.read_bytes()).hexdigest()}")
    prereg = tmp_path / "prereg.md"
    prereg.write_text("\n".join(lines), encoding="utf-8")
    return base, prereg


def invocation(tmp_path, command, **overrides):
    base, prereg = prepared(tmp_path)
    seen, out = [], StringIO()
    options = {
        "environ": {},
        "out": out,
        "root": base,
        "prereg_path": prereg,
        "prereg_check": lambda path: True,
        "check": lambda **kw: None,
        "settings": Settings(ledger_path=tmp_path / "ledger"),
        "graph_factory": FakeGraph,
        "rules_loader": list,
        "structured_factory": lambda model, style, guard: FakeStructured(
            model, style, guard, seen
        ),
    }
    options.update(overrides)
    return compare.main([command], **options), base, seen, out.getvalue()


@pytest.mark.parametrize("command", ["inputs", "terra", "sonnet"])
@pytest.mark.parametrize("committed,dirty", [(False, False), (True, True)])
def test_preregistration_guard_before_every_boundary(
    tmp_path, command, committed, dirty
):
    calls = []

    def git(args, **kw):
        calls.append(args)
        return SimpleNamespace(
            returncode=0,
            stdout=("commit" if committed else "")
            if args[1] == "log"
            else (" M prereg" if dirty else ""),
        )

    path = tmp_path / "prereg.md"
    assert not compare.preregistration_committed(path, run=git)
    assert all(args[-2:] == ["--", str(path)] for args in calls)
    out = StringIO()
    assert (
        compare.main(
            [command],
            environ={},
            out=out,
            prereg_check=lambda p: False,
            check=forbidden,
            research_fn=forbidden,
            structured_factory=forbidden,
            graph_factory=forbidden,
        )
        == 2
    )
    assert out.getvalue().strip() == "PREREGISTRATION_NOT_COMMITTED"


def test_committed_clean_and_git_errors(tmp_path):
    path = tmp_path / "file"

    def git(args, **kw):
        return SimpleNamespace(returncode=0, stdout="hash" if args[1] == "log" else "")

    assert compare.preregistration_committed(path, run=git)
    assert not compare.preregistration_committed(
        path, run=lambda *a, **k: (_ for _ in ()).throw(OSError())
    )


def test_caps_and_fixed_briefs_match_readonly_preregistration():
    text = (ROOT / compare.PREREG_PATH).read_text(encoding="utf-8")
    for purpose, cap in compare.PURPOSE_CAPS.items():
        match = re.search(rf"^상한 `{purpose}` = \$([0-9.]+)$", text, re.MULTILINE)
        assert match is not None
        assert float(match.group(1)) == cap
    for pattern, constant in (
        (r"모든 값의 쓸 수 있는 기획안 수가 (\d+)\(5건 중\)", compare.MIN_USABLE),
        (r"파일 sha256 오름차순 앞 (\d+)건", compare.SONNET_SAMPLE),
        (
            r"점수 차이 절댓값 평균이 ([0-9.]+)\(5점 척도\)",
            compare.SCORE_REVIEW_THRESHOLD,
        ),
    ):
        match = re.search(pattern, text)
        assert match is not None
        assert float(match.group(1)) == constant
    rows = [line for line in text.splitlines() if re.match(r"\| [1-5] \|", line)]
    assert len(rows) == len(compare.BRIEFS) == 5
    for row, brief in zip(rows, compare.BRIEFS, strict=True):
        cells = [cell.strip().strip("`") for cell in row.strip("|").split("|")]
        assert (brief["category"], brief["claim"], brief["goal"]) == tuple(cells[2:5])
        assert brief["output"] == "both"
    assert set(compare.PROFILES) == {"mixsoon", "cosrx"}
    assert all(
        profile["own_product_url"] in text for profile in compare.PROFILES.values()
    )
    assert "data/interim/" in (ROOT / ".gitignore").read_text().splitlines()


def ledger(path, purpose, cost):
    append_entry(
        path,
        LedgerEntry(
            ts=datetime.now(UTC),
            provider="openai",
            model="gpt-6.1-terra",
            purpose=purpose,
            cost_usd=cost,
            cost_source="price_table",
        ),
    )


def test_purpose_cap_exact_prefix_and_no_call(tmp_path):
    path = tmp_path / "ledger"
    ledger(path, "compare-terra-other", 0.06)
    ledger(path, "compare-terra", 0.06)
    for name in ("compare-terrain", "xcompare-terra", "compare-terraX"):
        ledger(path, name, 20)
    assert purpose_total(path, "compare-terra") == 0.12
    code, _, seen, output = invocation(
        tmp_path, "terra", structured_factory=forbidden, graph_factory=forbidden
    )
    assert code == 2 and not seen and "PURPOSE_CAP_REACHED" in output


@pytest.mark.parametrize(
    "counts,failures,chosen",
    [
        ([3, 5, 4], [0, 1, 0], "low"),
        ([4, 4, 4], [1, 0, 1], "low"),
        ([3, 3, 3], [0, 0, 0], "none"),
        ([2, 2, 1], [0, 0, 0], None),
    ],
)
def test_terra_decision(counts, failures, chosen):
    values = {
        effort: {"usable": count, "structured_failures": failed}
        for effort, count, failed in zip(compare.EFFORTS, counts, failures, strict=True)
    }
    result = compare.decide_terra(values)
    assert result["selected"] == chosen
    assert (result["decision"] == "보류") == (chosen is None)


@pytest.mark.parametrize(
    "passed,ids,expected",
    [
        (True, ["a"], True),
        (True, [], False),
        (True, ["a", "outside"], False),
        (False, ["a"], False),
    ],
)
def test_usable_definition(passed, ids, expected):
    assert (
        compare.usable_plan({"evidence_ids": ids}, {"passed": passed}, ["a"])
        is expected
    )


def test_input_hash_mismatch_before_calls(tmp_path):
    base, prereg = prepared(tmp_path)
    (base / "inputs" / "01.json").write_text(
        json.dumps({**handoff(), "conclusion": "changed"})
    )
    out = StringIO()
    assert (
        compare.main(
            ["terra"],
            environ={},
            root=base,
            prereg_path=prereg,
            out=out,
            prereg_check=lambda p: True,
            check=lambda **kw: None,
            settings=Settings(ledger_path=tmp_path / "ledger"),
            structured_factory=forbidden,
            graph_factory=forbidden,
        )
        == 2
    )
    assert "INPUT_HASH_MISMATCH" in out.getvalue()


@pytest.mark.parametrize(
    "a,b,expected", [(0.2, 0.1, "b"), (0.1, 0.1, "a"), (0, 0.2, "a")]
)
def test_sonnet_strict_decision(a, b, expected):
    assert compare.decide_sonnet(a, b, 1)["recommended"] == expected
    assert not compare.decide_sonnet(a, b, 1)["review"]
    assert compare.decide_sonnet(a, b, 1.001)["review"]


def test_first_and_final_failure_rates_separate():
    rows = [
        {"attempts": 1, "ok": True},
        {"attempts": 2, "ok": True},
        {"attempts": 2, "ok": False},
    ]
    metrics = compare.failure_rates(rows)
    assert metrics == {"first_failure_rate": 2 / 3, "final_failure_rate": 1 / 3}


def test_plan_selection_hash_sorted_independent_of_input(tmp_path):
    paths = []
    for index in range(15):
        path = tmp_path / f"{index}.json"
        path.write_text(json.dumps({**plan(), "title": str(index)}))
        paths.append(path)
    expected = sorted(
        paths, key=lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    )[:6]
    assert compare.select_plans(paths) == expected
    assert compare.select_plans(list(reversed(paths))) == expected


def test_terra_report_and_plan_files_are_allowlisted(tmp_path):
    code, base, seen, output = invocation(tmp_path, "terra")
    assert code == 0 and len(seen) == 15
    assert [kw["reasoning_effort"] for _, _, kw in seen] == [
        e for e in compare.EFFORTS for _ in range(5)
    ]
    assert all(
        model == "gpt-6.1-terra" and style == "default" for model, style, _ in seen
    )
    reports = list(base.glob("*-terra.json"))
    assert len(reports) == 1
    report_text = reports[0].read_text()
    assert SECRET not in output + report_text and PROSE not in output + report_text
    report = json.loads(report_text)
    assert len(report["rows"]) == 15
    assert report["metrics"]["none"]["usable"] == 5
    assert report["rows"][0]["thought_tokens"] == 2
    assert report["rows"][0]["input_tokens"] == 20
    files = list((base / "plans").glob("*.json"))
    assert len(files) == 15
    from beautyads.domain.plan import Plan

    for path in files:
        value = json.loads(path.read_text())
        assert set(value) == set(Plan.model_fields)
        assert SECRET not in path.read_text()
    for i in range(5):
        requests = [seen[offset + i][2]["messages"] for offset in (0, 5, 10)]
        assert requests[0] == requests[1] == requests[2]


def test_sonnet_both_adapters_same_prompts_and_metrics(tmp_path):
    assert invocation(tmp_path, "terra")[0] == 0
    # invocation recreates identical inputs, never consumes real data/interim.
    code, base, seen, output = invocation(tmp_path, "sonnet")
    assert code == 0 and len(seen) == 12
    assert [style for _, style, _ in seen] == ["default"] * 6 + ["native"] * 6
    assert all(
        model == "claude-sonnet-5-5" and kw["reasoning_effort"] is None
        for model, _, kw in seen
    )
    for i in range(6):
        assert seen[i][2]["messages"] == seen[i + 6][2]["messages"]
    text = next(base.glob("*-sonnet.json")).read_text()
    assert SECRET not in text + output and PROSE not in text + output
    report = json.loads(text)
    assert report["decision"]["recommended"] == "a"
    assert (
        report["score_difference_mean"] == 0 and report["score_exact_match_rate"] == 1
    )
    assert [row["cached_tokens"] for row in report["rows"]] == [5] * 12


def test_inputs_existing_never_overwritten_or_called(tmp_path):
    base, prereg = prepared(tmp_path)
    before = (base / "inputs" / "01.json").read_bytes()
    out = StringIO()
    assert (
        compare.main(
            ["inputs"],
            environ={},
            root=base,
            prereg_path=prereg,
            out=out,
            prereg_check=lambda p: True,
            check=lambda **kw: None,
            research_fn=forbidden,
            graph_factory=forbidden,
            settings=Settings(ledger_path=tmp_path / "ledger"),
        )
        == 2
    )
    assert "INPUTS_EXIST" in out.getvalue()
    assert (base / "inputs" / "01.json").read_bytes() == before


def test_inputs_five_handoffs_and_safe_hashes(tmp_path):
    seen = []

    def research(brief, **kw):
        seen.append((brief, kw))
        return handoff()

    out, base = StringIO(), tmp_path / "new"
    assert (
        compare.main(
            ["inputs"],
            environ={},
            root=base,
            out=out,
            prereg_check=lambda p: True,
            check=lambda **kw: None,
            research_fn=research,
            graph_factory=FakeGraph,
            rules_loader=list,
            settings=Settings(ledger_path=tmp_path / "ledger"),
        )
        == 0
    )
    assert len(seen) == len(list((base / "inputs").glob("*.json"))) == 5
    assert [kw["ctx"].tenant_id for _, kw in seen] == ["compare-mixsoon"] * 3 + [
        "compare-cosrx"
    ] * 2
    assert all(kw["ctx"].price_band.price_min == 70 for _, kw in seen)
    assert "synthetic-handoff" not in out.getvalue()


def test_preflight_safe_names_only():
    assert (
        compare.preflight(
            "sonnet",
            environ={},
            env_file=None,
            docker_check=forbidden,
            tcp_check=forbidden,
        )
        == "ENV_MISSING:ANTHROPIC_API_KEY"
    )
    env = {"ANTHROPIC_API_KEY": SECRET}
    assert (
        compare.preflight(
            "sonnet",
            environ=env,
            env_file=None,
            docker_check=forbidden,
            tcp_check=forbidden,
        )
        == "ENV_MISSING:NEO4J_PASSWORD"
    )


def test_generator_guards_corrections_and_strips_plan_extras(tmp_path):
    path = tmp_path / "plan.json"
    compare.save_plan(
        path,
        {
            **plan(),
            "api_key": SECRET,
            "thought_signatures": SECRET,
            "messages": [SECRET],
        },
    )
    assert SECRET not in path.read_text()
    assert json.loads(path.read_text()) == plan()
    calls = []

    def guard():
        calls.append("guard")

    gen = compare.default_structured_factory("gpt-6.1-terra", "default", guard)
    from beautyads.llm.structured import StructuredSpec

    response = lambda **kw: {
        "choices": [{"message": {"role": "assistant", "content": "invalid"}}]
    }
    result = gen.generate(
        StructuredSpec("x", "x", {}, lambda v: v),
        messages=[],
        purpose="compare-terra",
        ledger_path=tmp_path / "ledger",
        caps={"openai": 10},
        reasoning_effort="none",
        api_key=SECRET,
        completion_fn=response,
    )
    assert not result.ok and result.attempts == 2 and len(calls) == 2


@pytest.mark.parametrize(
    "content",
    ["", "01.json " + "a" * 64, "## 7. hashes\n## 8. later\n01.json " + "a" * 64],
)
def test_hashes_must_be_registered_in_section_seven(tmp_path, content):
    base, prereg = prepared(tmp_path)
    prereg.write_text(content)
    with pytest.raises(compare.CompareStopped, match="INPUT_HASH_MISMATCH"):
        compare._load_inputs(base, prereg)


def test_cap_rechecked_before_structured_correction(tmp_path):
    path = tmp_path / "ledger"
    guard_calls, paid_calls = [], []

    def guard():
        guard_calls.append(True)
        compare.check_purpose_cap(path, "compare-terra", 0.12)

    def complete(**kw):
        paid_calls.append(kw)
        ledger(path, "compare-terra", 0.12)
        return {"choices": [{"message": {"role": "assistant", "content": "invalid"}}]}

    from beautyads.llm.structured import StructuredSpec

    generator = compare.default_structured_factory("gpt-6.1-terra", "default", guard)
    with pytest.raises(compare.CostCapExceeded):
        generator.generate(
            StructuredSpec("x", "x", {}, lambda v: v),
            messages=[],
            purpose="compare-terra",
            ledger_path=path,
            caps={"openai": 10},
            reasoning_effort="none",
            api_key=SECRET,
            completion_fn=complete,
        )
    assert len(paid_calls) == 1 and len(guard_calls) == 2


@pytest.mark.parametrize("style", ["default", "native"])
def test_sonnet_real_adapters_with_injected_transports(tmp_path, style):
    from beautyads.domain.evaluation import EvaluationScores
    from beautyads.llm.structured import StructuredSpec

    seen = []
    value = {"differentiation": 2, "fit": 5, "rationale": SECRET}

    def complete(**kw):
        seen.append(kw)
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "scores",
                                    "arguments": json.dumps(value),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 5,
                "cache_read_input_tokens": 4,
            },
        }

    async def acreate(**kw):
        seen.append(kw)
        return {
            "content": [{"type": "text", "text": json.dumps(value)}],
            "usage": {
                "input_tokens": 16,
                "output_tokens": 5,
                "cache_read_input_tokens": 4,
            },
        }

    guard_calls = []
    generator = compare.default_structured_factory(
        "claude-sonnet-5-5", style, lambda: guard_calls.append(True)
    )
    result = generator.generate(
        StructuredSpec(
            "scores",
            "fixed",
            EvaluationScores.model_json_schema(),
            lambda v: EvaluationScores.model_validate(v).model_dump(),
        ),
        messages=[{"role": "system", "content": [compare.cache_system_block("fixed")]}],
        purpose="compare-sonnet",
        ledger_path=tmp_path / "ledger",
        caps={"anthropic": 8},
        reasoning_effort=None,
        api_key=SECRET,
        completion_fn=complete,
        acreate_fn=acreate,
    )
    assert result.ok and len(seen) == len(guard_calls) == 1
    request = seen[0]
    assert "temperature" not in request and "thinking" not in request
    if style == "default":
        assert request["tool_choice"] == "auto" and len(request["tools"]) == 1
    else:
        assert request["output_config"]["format"]["type"] == "json_schema"
        assert any(block.get("cache_control") for block in request["system"])
    assert (
        compare._call_metrics("claude-sonnet-5-5", result.calls[0])["cached_tokens"]
        == 4
    )


def test_sonnet_partial_structure_failures_and_score_review(tmp_path):
    assert invocation(tmp_path, "terra")[0] == 0
    seen = []

    class Varied(FakeStructured):
        def generate(self, spec, **kw):
            self.guard()
            seen.append(self.style)
            ordinal = seen.count(self.style)
            ok = self.style == "native" or ordinal > 1
            attempts = 2 if ordinal < 3 and self.style == "default" else 1
            value = {
                "differentiation": 5 if self.style == "native" else 1,
                "fit": 5 if self.style == "native" else 1,
                "rationale": SECRET,
            }
            return StructuredResult(ok, value if ok else None, None, attempts, 0, [])

    code, base, _, output = invocation(
        tmp_path,
        "sonnet",
        structured_factory=lambda model, style, guard: Varied(model, style, guard, []),
    )
    assert code == 0
    report = json.loads(next(base.glob("*-sonnet.json")).read_text())
    assert report["metrics"]["a"]["first_failure_rate"] == 2 / 6
    assert report["metrics"]["a"]["final_failure_rate"] == 1 / 6
    assert report["metrics"]["b"]["first_failure_rate"] == 0
    assert report["decision"] == {"recommended": "b", "review": True}
    assert report["paired_count"] == 5 and report["score_difference_mean"] == 4
    assert "검토 표시" in output
    assert SECRET not in output


def test_inputs_chat_and_structured_calls_use_comparison_ledger(monkeypatch, tmp_path):
    calls = []

    def chat(**kw):
        calls.append(kw)
        return ChatResult(
            SECRET,
            [],
            "stop",
            {"prompt_tokens": 7},
            0.001,
            "price_table",
            {"api_key": SECRET},
        )

    monkeypatch.setattr(compare, "chat_complete", chat)

    def research(brief, *, chat, structured, **kw):
        chat(
            model="gpt-6-luna", messages=[], purpose="research", reasoning_effort="low"
        )
        assert structured.effort == "none" and structured.model == "gpt-6-luna"
        return handoff()

    out, base = StringIO(), tmp_path / "new"
    code = compare.main(
        ["inputs"],
        root=base,
        environ={"OPENAI_API_KEY": SECRET},
        out=out,
        prereg_check=lambda p: True,
        check=lambda **kw: None,
        graph_factory=FakeGraph,
        research_fn=research,
        settings=Settings(ledger_path=tmp_path / "ledger"),
    )
    assert code == 0 and len(calls) == 5
    assert all(
        kw["purpose"] == "compare-inputs" and kw["reasoning_effort"] == "none"
        for kw in calls
    )
    assert all(
        kw["caps"] == Settings().provider_caps_usd
        and kw["ledger_path"] == tmp_path / "ledger"
        for kw in calls
    )
    report = json.loads(next(base.glob("*-inputs.json")).read_text())
    assert all(
        row["input_tokens"] == 7 and row["cost_usd"] == 0.001 for row in report["rows"]
    )
    assert SECRET not in out.getvalue() + json.dumps(report)


def test_failures_close_resources_without_exception_leaks(tmp_path):
    closed = []

    class Graph(FakeGraph):
        def close(self):
            closed.append(True)
            raise RuntimeError(SECRET)

    def factory(*args):
        raise RuntimeError(SECRET, PROSE)

    code, base, _, output = invocation(
        tmp_path, "terra", graph_factory=Graph, structured_factory=factory
    )
    assert code == 3 and closed == [True]
    report = next(base.glob("*-terra.json")).read_text()
    assert json.loads(report)["complete"] is False
    assert "decision" not in json.loads(report)
    assert SECRET not in output + report and PROSE not in output + report


@pytest.mark.parametrize(
    "code",
    [
        None,
        "SCHEMA_INVALID:400",
        "A" * 64,
        "A" * 65,
        "",
        "unsafe-code",
        "bad\ncode",
        400,
        {"private": SECRET},
    ],
)
def test_unexpected_failure_reports_only_safe_code_and_class(tmp_path, code):
    class SyntheticFailure(Exception):
        pass

    def factory(*args):
        error = SyntheticFailure(SECRET, {"private": PROSE})
        if code is not None:
            error.code = code
        raise error from RuntimeError(SECRET, PROSE)

    status, base, _, output = invocation(tmp_path, "terra", structured_factory=factory)
    text = next(base.glob("*-terra.json")).read_text()
    report = json.loads(text)
    safe_code = (
        code
        if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_:]{1,64}", code)
        else None
    )
    assert status == 3 and report["complete"] is False
    assert report["error"] == {"code": safe_code, "detail": "SyntheticFailure"}
    first_line = output.splitlines()[0]
    assert (
        first_line
        == "COMPARE_FAILED"
        + (f" error_code={safe_code}" if safe_code is not None else "")
        + " detail=SyntheticFailure"
    )
    assert SECRET not in output + text and PROSE not in output + text
    assert "private" not in output + text


@pytest.mark.parametrize("unreadable", [False, True])
def test_inputs_actual_neo4j_rows_and_unreadable_codes_save_offline(
    tmp_path, unreadable
):
    from neo4j.time import Date, DateTime, Duration, Time

    from beautyads.agents.research import run_research
    from beautyads.llm.chat import ToolCall

    temporal = DateTime(2025, 1, 1, 1, 2, 3)
    stores = []

    class TemporalGraph(FakeGraph):
        def run(self, query, params=None):
            if "unit_list_price" in query:
                return super().run(query, params)
            return SimpleNamespace(
                records=[
                    {
                        "creative_id": "youtube:one",
                        "published_at": temporal,
                        "date": Date(2025, 1, 1),
                        "time": Time(1, 2, 3),
                        "duration": Duration(seconds=5),
                    }
                ]
            )

    class HandoffStructured:
        stats = StructuredStats()

        def generate(self, spec, **kw):
            value = {
                k: v for k, v in handoff().items() if k in spec.schema["properties"]
            }
            value["aggregates"] = []
            return StructuredResult(True, spec.validate(value), None, 1, 0, [])

    def research(brief, *, ctx, tool_runner, **kw):
        responses = iter(
            [
                ChatResult(
                    None,
                    [
                        ToolCall(
                            "one",
                            "find_example_creatives",
                            {"category": brief["category"]},
                            None,
                        )
                    ],
                    "stop",
                    {},
                    0,
                    "price_table",
                    {},
                ),
                ChatResult(None, [], "stop", {}, 0, "price_table", {}),
            ]
        )
        store = {}
        stores.append(store)
        return run_research(
            brief,
            ctx=ctx,
            chat=lambda **kw: next(responses),
            tool_runner=(lambda *args: {"private": SECRET})
            if unreadable
            else tool_runner,
            structured=HandoffStructured(),
            raw_store=store,
        )

    out, base = StringIO(), tmp_path / "new"
    status = compare.main(
        ["inputs"],
        root=base,
        environ={},
        out=out,
        prereg_check=lambda p: True,
        check=lambda **kw: None,
        graph_factory=TemporalGraph,
        research_fn=research,
        structured_factory=lambda *args: HandoffStructured(),
        settings=Settings(ledger_path=tmp_path / "ledger"),
    )
    assert status == 0
    report = json.loads(next(base.glob("*-inputs.json")).read_text())
    assert report["complete"] is True and len(report["rows"]) == 5
    expected = ["find_example_creatives: TOOL_RESULT_UNREADABLE"] if unreadable else []
    for index, row in enumerate(report["rows"], 1):
        assert row["unresolved"] == expected
        path = base / "inputs" / f"{index:02}.json"
        saved = json.loads(path.read_text())
        assert saved["unresolved"] == expected
        assert row["output_sha256"] == compare.file_hash(path)
        assert saved["status"] == ("no_evidence" if unreadable else "ok")
    assert SECRET not in out.getvalue() + json.dumps(report)
    if not unreadable:
        assert all(
            next(iter(store.values()))["top_rows"][0]["published_at"]
            == temporal.iso_format()
            for store in stores
        )


def test_inputs_unresolved_report_retains_only_tool_and_code(tmp_path):
    def research(*args, **kw):
        return {
            **handoff(),
            "unresolved": [
                "find_example_creatives: TOOL_RESULT_UNREADABLE",
                "ingredient_ad_trend: GRAPH_UNAVAILABLE",
                SECRET,
                f"find_example_creatives: TOOL_RESULT_UNREADABLE {SECRET}",
                f"private prose: {PROSE}",
            ],
        }

    out, base = StringIO(), tmp_path / "new"
    assert (
        compare.main(
            ["inputs"],
            root=base,
            environ={},
            out=out,
            prereg_check=lambda p: True,
            check=lambda **kw: None,
            graph_factory=FakeGraph,
            research_fn=research,
            settings=Settings(ledger_path=tmp_path / "ledger"),
        )
        == 0
    )
    report = json.loads(next(base.glob("*-inputs.json")).read_text())
    assert all(
        row["unresolved"]
        == [
            "find_example_creatives: TOOL_RESULT_UNREADABLE",
            "ingredient_ad_trend: GRAPH_UNAVAILABLE",
        ]
        for row in report["rows"]
    )
    assert SECRET not in json.dumps(report) and PROSE not in json.dumps(report)
