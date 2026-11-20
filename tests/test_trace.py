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
    "kind",
    [
        "research",
        "plan",
        "out_of_scope",
        "no_evidence",
        "failed",
        "needs_clarification",
        "claim_choice_invalid",
    ],
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
                        "checks_passed": False,
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
                    {"attempt": 2, "checks_passed": True, "scores": None},
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
    assert plan.attempts[1].attempt == 2 and plan.attempts[1].checks_passed is True
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


def test_limit_detail_projects_only_safe_fields_and_roundtrips(tmp_path):
    detail = [
        {"kind": "image", "cap": "purpose:image"},
        {"kind": "text", "cap": "request:text"},
    ]
    record = make_trace(
        result={"limit_detail": [{**item, "diagnostic": SECRET} for item in detail]}
    )
    assert [item.model_dump() for item in record.limit_detail] == detail
    path = tmp_path / "trace.jsonl"
    append_trace(path, record)
    assert read_traces(path).records == [record]
    assert SECRET not in path.read_text()
    assert make_trace().limit_detail == []


@pytest.mark.parametrize(
    "cap", [SECRET, "provider:gemini\n", "provider:Gemini", "a/b", 9, None]
)
def test_limit_detail_sanitizes_invalid_cap_without_losing_trace(cap):
    record = make_trace(result={"limit_detail": [{"kind": "image", "cap": cap}]})
    assert [item.model_dump() for item in record.limit_detail] == [
        {"kind": "image", "cap": "unknown"}
    ]
    assert SECRET not in record.model_dump_json()


def test_limit_detail_kind_must_pass_trace_token_pattern():
    with pytest.raises(ValidationError):
        make_trace(
            result={"limit_detail": [{"kind": "invalid kind/", "cap": "unknown"}]}
        )


def test_trace_records_only_alignment_counts_prompt_versions_and_distinct_passes(
    tmp_path,
):
    versions = {"planning": "2026-11-18-1", "evaluation": "2026-11-18-1"}
    result = {
        "prompt_versions": versions,
        "plans": [
            {
                "pattern_alignment": {
                    "compared": 2,
                    "same_count": 1,
                    "skipped": 3,
                    "axes": {"hook_type": {"plan": SECRET, "dominant": [SECRET]}},
                    "detail": SECRET,
                },
                "attempts": [
                    {
                        "attempt": 1,
                        "checks_passed": True,
                        "final_passed": False,
                        "scores": {"fit": 2, "rationale": SECRET},
                    }
                ],
            }
        ],
    }
    record = make_trace(
        result=result, failure={"class": "SyntheticError", "message": SECRET}
    )
    assert record.prompt_versions == versions
    assert record.plans[0].alignment.model_dump() == {
        "compared": 2,
        "same_count": 1,
        "skipped": 3,
    }
    attempt = record.plans[0].attempts[0].model_dump()
    assert attempt["checks_passed"] is True and attempt["final_passed"] is False
    assert "passed" not in attempt
    path = tmp_path / "trace.jsonl"
    append_trace(path, record)
    assert read_traces(path).records == [record]
    assert SECRET not in path.read_text()


def test_trace_new_metadata_cannot_carry_prose_or_key_shaped_values():
    record = make_trace(
        result={
            "prompt_versions": {
                "planning": SECRET,
                "evaluation": "2026-11-18-1",
                "extra": SECRET,
            },
            "plans": [
                {
                    "pattern_alignment": {
                        "compared": SECRET,
                        "same_count": True,
                        "skipped": 0,
                        "axes": {SECRET: SECRET},
                    }
                }
            ],
        }
    )
    assert SECRET not in record.model_dump_json()
    assert record.prompt_versions == {"evaluation": "2026-11-18-1"}
    assert record.plans[0].alignment.model_dump() == {
        "compared": 0,
        "same_count": 0,
        "skipped": 0,
    }


def test_failure_details_roundtrip_and_sum_by_tenant_without_values(tmp_path):
    key = "evaluation_scores|rationale|string_too_long"
    other = "plan|scenes.*|string_type"
    records = [
        make_trace(
            tenant_id=tenant,
            structured={
                "model_a": {"calls": 2, "first_attempt_failure_details": {key: 1}},
                "model_b": {
                    "calls": 1,
                    "first_attempt_failure_details": {key: 2, other: 1},
                },
            },
        )
        for tenant in ("tenant_a", "tenant_b", "tenant_a")
    ]
    path = tmp_path / "traces.jsonl"
    for record in records:
        append_trace(path, record)
    assert read_traces(path).records == records
    assert records[0].structured["model_a"].model_dump()[
        "first_attempt_failure_details"
    ] == {key: 1}
    summary = summarize_by_tenant(read_traces(path).records)
    assert summary["tenant_a"]["first_attempt_failure_details"] == {key: 6, other: 2}
    assert summary["tenant_b"]["first_attempt_failure_details"] == {key: 3, other: 1}
    assert SECRET not in path.read_text() + json.dumps(summary)


def test_pattern_distribution_projects_only_closed_axis_and_numeric_metadata(tmp_path):
    from test_domain_supervisor import comparison_rows

    from beautyads.domain.supervisor import pattern_context

    context = pattern_context(
        [comparison_rows(("question", 5), ("problem", 3), total=10)], []
    )
    expected = [
        {key: value for key, value in row.items() if key != "top_value"}
        for row in context["distribution"]
    ]
    source = [{**row, "top_value": SECRET} for row in expected]
    record = make_trace(
        result={
            "pattern_distribution": source,
            "handoff": {"pattern_distribution": [{"axis": SECRET}]},
        }
    )
    assert record.model_dump()["pattern_distribution"] == expected
    path = tmp_path / "trace.jsonl"
    append_trace(path, record)
    records = read_traces(path).records
    assert records[0].model_dump()["pattern_distribution"] == expected
    summary = summarize_by_tenant(
        [*records, make_trace(tenant_id="tenant_b"), *records]
    )
    assert summary["tenant_a"]["pattern_distribution"] == expected * 2
    assert SECRET not in path.read_text() + json.dumps(summary)
    assert make_trace().pattern_distribution == []


def test_pattern_distribution_rejects_open_axis_names():
    with pytest.raises(ValidationError):
        make_trace(
            result={
                "pattern_distribution": [
                    {"axis": SECRET, "total": 1, "top_share": 1.0, "second_share": None}
                ]
            }
        )


@pytest.mark.parametrize("key", ["", "bad/key", "bad key", "x" * 121, "bad\n"])
def test_failure_detail_trace_key_contract(key):
    from beautyads.obs.trace import TraceStructured

    with pytest.raises(ValidationError):
        TraceStructured(first_attempt_failure_details={key: 1})


@pytest.mark.parametrize("count", [-1, True, "1", 1.5])
def test_failure_detail_trace_count_contract(count):
    from beautyads.obs.trace import TraceStructured

    with pytest.raises(ValidationError):
        TraceStructured(first_attempt_failure_details={"spec|-|parse_failed": count})


def test_legacy_trace_failure_details_default_is_independent():
    from beautyads.obs.trace import TraceStructured

    first, second = TraceStructured(), TraceStructured()
    first.first_attempt_failure_details["spec|-|parse_failed"] = 1
    assert second.first_attempt_failure_details == {}


@pytest.mark.parametrize(
    "composed,expected",
    [
        (
            {"contrast_adjusted": True, "min_contrast": 2.346},
            {"contrast_adjusted": True, "min_contrast": 2.346},
        ),
        (
            {"contrast_adjusted": False},
            {"contrast_adjusted": False, "min_contrast": None},
        ),
        (
            {"contrast_adjusted": True, "min_contrast": None},
            {"contrast_adjusted": True, "min_contrast": None},
        ),
        (None, None),
        ({}, None),
        ([], None),
        ({"contrast_adjusted": SECRET, "min_contrast": 3.0}, None),
        ({"contrast_adjusted": 1, "min_contrast": 3.0}, None),
        ({"contrast_adjusted": True, "min_contrast": SECRET}, None),
        ({"contrast_adjusted": True, "min_contrast": float("nan")}, None),
        ({"contrast_adjusted": True, "min_contrast": float("inf")}, None),
        ({"contrast_adjusted": True, "min_contrast": -1}, None),
        ({"contrast_adjusted": True, "min_contrast": True}, None),
    ],
)
def test_trace_composed_contrast_is_validated_without_prose(composed, expected):
    record = make_trace(
        result={
            "plans": [
                {
                    "image": {"composed": composed},
                    "composed_contrast": {"contrast_adjusted": SECRET},
                }
            ]
        }
    )
    value = record.plans[0].composed_contrast
    assert (value.model_dump() if value is not None else None) == expected
    assert SECRET not in record.model_dump_json()


def test_trace_contrast_projects_only_image_metadata_and_roundtrips(tmp_path):
    record = make_trace(
        result={
            "plans": [
                {
                    "image": {
                        "composed": {
                            "contrast_adjusted": True,
                            "min_contrast": 2.346,
                            "path": SECRET,
                            "base64": SECRET,
                        }
                    }
                },
                {},
                {"image": SECRET},
            ]
        }
    )
    assert record.plans[0].composed_contrast.min_contrast == 2.346
    assert (
        record.plans[1].composed_contrast is record.plans[2].composed_contrast is None
    )
    path = tmp_path / "trace.jsonl"
    append_trace(path, record)
    assert read_traces(path).records[0] == record
    assert SECRET not in path.read_text()
