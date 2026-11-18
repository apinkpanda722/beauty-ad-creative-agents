"""Local trace contracts use synthetic metadata and temporary files only."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from beautyads.domain.supervisor import RequestLimits
from beautyads.obs.ledger import LedgerEntry
from beautyads.obs.trace import (
    TraceRead,
    TraceRecord,
    append_trace,
    build_trace,
    read_traces,
    summarize_by_tenant,
)

START = datetime(2026, 11, 18, tzinfo=UTC)
SECRET = "SYNTHETIC-SECRET-private-prose"


def make_trace(**options):
    return build_trace(
        **{
            "tenant_id": "tenant_a",
            "started_at": START,
            "duration_ms": 12,
            "message": SECRET,
            "result": None,
            "failure": None,
            "ledger_entries": [],
            "structured": {},
            **options,
        }
    )


def ledger(purpose="planning", cost=0.02):
    return LedgerEntry(
        ts=START,
        provider="openai",
        model="synthetic-model",
        purpose=purpose,
        reasoning_effort="low",
        input_tokens=11,
        output_tokens=12,
        thought_tokens=3,
        cached_tokens=4,
        cost_usd=cost,
        cost_source="price_table",
    )


@pytest.mark.parametrize(
    "kind", ["research", "plan", "out_of_scope", "no_evidence", "failed"]
)
def test_build_projects_only_metadata_and_integer_scores(kind):
    result = {
        "kind": kind,
        "intent": "plan",
        "brief": {"goal": SECRET},
        "handoff": {
            "conclusion": SECRET,
            "aggregates": {SECRET: SECRET},
            "result_counts": [
                {"tool": "synthetic_tool", "row_count": 9, "shown_count": 2}
            ],
        },
        "steps": [{"agent": "research", "phase": "end", "status": "ok"}],
        "plans": [
            {
                "status": "needs_review",
                "plan": {"title": SECRET},
                "rework_count": 1,
                "unknown_count": 2,
                "efficacy_status": {"hydration": "unknown", "invalid": 7},
                "attempts": [
                    {
                        "attempt": 1,
                        "passed": False,
                        "scores": {
                            "differentiation": 2,
                            "fit": 3,
                            "rationale": SECRET,
                            "float": 2.5,
                            "boolean": True,
                            "numeric_string": "4",
                        },
                        "failed_check_codes": ["EVIDENCE_MISSING"],
                        "cost_usd": 0.02,
                        "planning_failure": SECRET,
                    },
                    {"attempt": 2, "passed": True, "scores": None},
                ],
                "report": {"rationale": SECRET},
            }
        ],
        "limit_hit": True,
        "limit_kinds": ["text", "steps"],
        "input_trims": [{"field": "evidence_ids", "kept": 30, "total": 40}],
        "aggregates_removed": [SECRET, SECRET],
        "limits": {"text_spent_usd": 0.02},
        "unknown_key": SECRET,
        "error_message": SECRET,
    }
    structured = {
        "synthetic-model": {
            "calls": 2,
            "failed_after_retry": 1,
            "first_attempt_failures": {"PARSE_FAILED": 1, "TOOL_NOT_CALLED": 1},
            "rationale": SECRET,
        }
    }
    record = make_trace(
        result=result,
        ledger_entries=[ledger(), ledger("image-plan", 0.04)],
        structured=structured,
    )
    assert record.kind == kind and record.intent == "plan"
    assert record.outcome == "ok"
    assert record.message_chars == len(SECRET) and not record.message_trimmed
    assert record.steps[0].model_dump() == result["steps"][0]
    assert record.tools[0].model_dump() == result["handoff"]["result_counts"][0]
    plan = record.plans[0]
    assert (plan.status, plan.rework_count, plan.unknown_count) == (
        "needs_review",
        1,
        2,
    )
    assert plan.efficacy_status == {"hydration": "unknown"}
    assert plan.attempts[0].scores == {"differentiation": 2, "fit": 3}
    assert plan.attempts[0].failed_check_codes == ["EVIDENCE_MISSING"]
    assert plan.attempts[0].cost_usd == 0.02
    assert plan.attempts[1].attempt == 2 and plan.attempts[1].passed is True
    assert plan.attempts[1].scores is None
    assert record.limit_hit and record.limit_kinds == ["text", "steps"]
    assert record.input_trims[0].model_dump() == result["input_trims"][0]
    assert record.aggregates_removed_count == 2 and record.text_spent_usd == 0.02
    assert record.calls[0].model_dump() == ledger().model_dump(
        exclude={"ts", "provider", "requested_model"}
    )
    assert record.cost_total_usd == pytest.approx(0.06)
    assert record.cost_by_purpose == {"planning": 0.02, "image-plan": 0.04}
    assert record.structured["synthetic-model"].model_dump() == {
        key: value
        for key, value in structured["synthetic-model"].items()
        if key != "rationale"
    }
    assert SECRET not in record.model_dump_json()
    assert result["plans"][0]["attempts"][0]["scores"]["rationale"] == SECRET


@pytest.mark.parametrize("size", [0, 2000, 2001])
def test_message_budget_defaults_and_empty_result(size):
    record = make_trace(message="x" * size, result={"unknown": SECRET})
    assert record.message_chars == size
    assert record.message_trimmed is (size > RequestLimits().decide_max_chars)
    assert record.kind is record.intent is record.text_spent_usd is None
    assert record.steps == record.tools == record.plans == record.calls == []
    assert record.cost_total_usd == 0 and record.cost_by_purpose == {}
    assert record.structured == {} and not record.limit_hit
    assert re.fullmatch(r"[0-9a-f]{32}", record.trace_id)
    assert record.trace_id != make_trace().trace_id


def test_custom_message_trim_is_reported():
    record = make_trace(
        result={"input_trims": [{"field": "message", "kept": 2, "total": len(SECRET)}]}
    )
    assert record.message_trimmed


@pytest.mark.parametrize("code", [SECRET, "bad code", "a/b", "", "x" * 65, 9, None])
def test_failure_codes_are_safe_and_messages_never_copied(code):
    record = make_trace(
        failure={"class": "SyntheticError", "code": code, "message": SECRET}
    )
    assert record.outcome == "error" and record.error_class == "SyntheticError"
    assert record.error_code is None
    assert SECRET not in record.model_dump_json()


def test_failure_code_and_class_validation_also_applies_to_schema():
    record = make_trace(failure={"class": SECRET, "code": "COST_CAP:openai"})
    assert record.error_class is None and record.error_code == "COST_CAP:openai"
    data = record.model_dump()
    data.update(error_class="bad/class", error_code=SECRET)
    validated = TraceRecord.model_validate(data)
    assert validated.error_class is validated.error_code is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("unknown", SECRET),
        ("cost_total_usd", float("inf")),
        ("text_spent_usd", float("nan")),
        ("kind", "unexpected"),
    ],
)
def test_record_schema_rejects_extra_nonfinite_and_unknown_kind(field, value):
    with pytest.raises(ValidationError):
        TraceRecord.model_validate({**make_trace().model_dump(), field: value})


def test_timestamp_requires_timezone_and_normalizes_to_utc():
    with pytest.raises(ValidationError):
        make_trace(started_at=START.replace(tzinfo=None))
    assert (
        make_trace(started_at=START.astimezone(timezone(timedelta(hours=9)))).started_at
        == START
    )


def test_file_roundtrip_parent_creation_and_corruption(tmp_path, caplog, capsys):
    path = tmp_path / "nested" / "traces.jsonl"
    assert read_traces(path) == TraceRead([], 0)
    assert not path.parent.exists()
    record = make_trace()
    append_trace(path, record)
    append_trace(path, record)
    assert [json.loads(line) for line in path.read_text().splitlines()] == [
        record.model_dump(mode="json")
    ] * 2
    with path.open("a") as stream:
        stream.write(SECRET + "\nnull\n{}\n")
    read = read_traces(path)
    assert read.records == [record, record] and read.skipped_lines == 3
    assert SECRET not in repr(read) + caplog.text + str(capsys.readouterr())


def test_concurrent_appends_keep_every_line(tmp_path):
    path = tmp_path / "nested" / "traces.jsonl"
    workers, per_worker = 8, 25

    def write_many(_):
        for _ in range(per_worker):
            append_trace(path, make_trace())

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(write_many, range(workers)))
    lines = path.read_text().splitlines()
    assert len(lines) == workers * per_worker
    assert all(isinstance(json.loads(line), dict) for line in lines)
    read = read_traces(path)
    assert read.skipped_lines == 0 and len(read.records) == len(lines)
    assert len({record.trace_id for record in read.records}) == len(lines)


def test_tenant_summary_separates_requests_calls_costs_and_structured_failures():
    def record(tenant, failure=None):
        return make_trace(
            tenant_id=tenant,
            failure=failure,
            ledger_entries=[ledger(), ledger("image-plan", 0.04)],
            structured={
                "model_a": {
                    "calls": 2,
                    "failed_after_retry": 1,
                    "first_attempt_failures": {"PARSE_FAILED": 2},
                },
                "model_b": {
                    "calls": 1,
                    "failed_after_retry": 0,
                    "first_attempt_failures": {
                        "PARSE_FAILED": 1,
                        "SCHEMA_VIOLATION": 1,
                    },
                },
            },
        )

    records = [
        record("tenant_a"),
        record("tenant_b"),
        record("tenant_a", {"class": "SyntheticError"}),
    ]
    summary = summarize_by_tenant(records)
    assert summarize_by_tenant([]) == {}
    assert set(summary) == {"tenant_a", "tenant_b"}
    for tenant, count, errors in (("tenant_a", 2, 1), ("tenant_b", 1, 0)):
        assert summary[tenant] == {
            "requests": count,
            "errors": errors,
            "calls": 2 * count,
            "cost_usd": pytest.approx(0.06 * count),
            "cost_by_purpose": {"planning": 0.02 * count, "image-plan": 0.04 * count},
            "first_attempt_failures": {
                "PARSE_FAILED": 3 * count,
                "SCHEMA_VIOLATION": count,
            },
            "structured_calls": 3 * count,
        }
