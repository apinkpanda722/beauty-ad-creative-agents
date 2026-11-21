"""Request IO projections use synthetic bodies and never contact services."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from beautyads.obs.langfuse_io import (
    CLIP_CHARS,
    OMITTED,
    REDACTED,
    Capture,
    RequestIO,
    clip,
    match_captures,
    redact,
    stage_io,
    to_text,
    trace_input,
    trace_output,
)
from beautyads.obs.trace import TraceCall

START = datetime(2026, 11, 21, tzinfo=UTC)


@pytest.mark.parametrize(
    "text",
    [
        "sk-" + "synthetic_" * 3,
        "sk-ant-" + "synthetic_" * 3,
        "AIza" + "synthetic_" * 3,
        "Bearer synthetic-token",
        "Authorization: synthetic authentication header",
        "eyJsynthetic.eyJsynthetic.synthetic",
    ],
)
def test_redact_credentials(text):
    assert redact(text) == REDACTED


@pytest.mark.parametrize("name", ["API_KEY", "access_TOKEN", "SECRET", "PASSWORD"])
@pytest.mark.parametrize(
    "value", ["synthetic", '"synthetic value"', "'synthetic value'"]
)
def test_redact_assignments(name, value):
    assert redact(f"{name}={value}") == f"{name}={REDACTED}"


def test_redact_images_and_preserve_normal_prose():
    assert redact("data:image/png;base64,c3ludGhldGlj") == "(이미지 데이터 생략)"
    assert redact("Zg==" * 60) == "(이미지 데이터 생략)"
    text = "일반 한국어 문장, ordinary prose.\n다음 줄"
    assert redact(text) == text
    assert redact("Authorization: synthetic\n다음 줄") == REDACTED + "\n다음 줄"


def test_redact_serialized_credentials_with_escaped_quotes():
    for value in (
        'API_KEY="SYNTHETIC PRIVATE VALUE"',
        "TOKEN='SYNTHETIC PRIVATE VALUE'",
    ):
        assert "SYNTHETIC PRIVATE VALUE" not in redact(to_text({"content": value}))


@pytest.mark.parametrize("size", [0, 3999, 4000, 4001])
def test_clip_boundary(size):
    text = "가" * size
    assert clip(text) == (
        text if size <= CLIP_CHARS else text[:CLIP_CHARS] + "\n" + OMITTED
    )
    assert clip(text, 2) == (text if size <= 2 else text[:2] + "\n" + OMITTED)


def test_to_text_unicode_and_fixed_failure():
    assert to_text("한국어") == "한국어"
    assert to_text({"문장": "한국어"}) == '{"문장": "한국어"}'
    assert "\\u" not in to_text({"문장": "한국어"})
    circular = []
    circular.append(circular)
    assert to_text(circular) == "(직렬화 불가)"

    class Broken:
        def __str__(self):
            raise ValueError("SYNTHETIC_PRIVATE_DIAGNOSTIC")

    assert to_text(Broken()) == "(직렬화 불가)"


def synthetic_io():
    private = "SYNTHETIC_NOT_ALLOWED"
    plan = {
        "title": "합성 제목",
        "hook_text": "합성 훅",
        "copy_lines": ["합성 카피"],
        "claimed_efficacy": ["hydration"],
        "evidence_ids": ["youtube:synthetic"],
        "image_brief": "합성 장면",
        "unknown": private,
    }
    attempt = {
        "scores": {
            "fit": 2,
            "differentiation": 3,
            "rationale": private,
            "unknown": private,
        },
        "checks_passed": True,
        "final_passed": False,
        "low_items": ["fit"],
        "failed_check_codes": ["SYNTHETIC_CHECK"],
        "rationale": private,
        "unknown": private,
    }
    return RequestIO(
        message="합성 요청",
        claim_choice={
            "mode": "select",
            "claims": ["hydration"],
            "requested_claim": "hydration",
            "unknown": private,
        },
        result={
            "kind": "plan",
            "intent": "plan",
            "brief": {
                "claim": "hydration",
                "hook_type": "question",
                "angle": "how_to",
                "format": "demo",
                "goal": "합성 목표",
                "category": "serum_ampoule",
                "skin_concern": "dryness",
                "output": "both",
                "unknown": private,
            },
            "handoff": {
                "conclusion": "합성 결론",
                "evidence_ids": ["youtube:synthetic", "youtube:other"],
                "result_counts": [
                    {
                        "tool": "find_example_creatives",
                        "row_count": 3,
                        "shown_count": 2,
                        "unknown": private,
                    }
                ],
                "unknown": private,
            },
            "plans": [
                {
                    "plan": plan,
                    "attempts": [attempt, attempt],
                    "unknown_count": 0,
                    "efficacy_status": {"hydration": "supported"},
                },
                {
                    "plan": plan,
                    "attempts": [attempt],
                    "unknown_count": 1,
                    "efficacy_status": {"hydration": "unsupported"},
                },
            ],
            "claim_choice": {
                "mode": "select",
                "claims": ["hydration"],
                "requested_claim": "hydration",
                "unknown": private,
            },
            "available_efficacy": ["hydration"],
            "profile": {"forbidden_terms": [private]},
            "feedback": private,
            "raw_tool_outputs": private,
            "unknown": private,
        },
        captures=(),
    )


def test_allowlisted_projections_and_final_attempt_only():
    io = synthetic_io()
    incoming, outgoing, stages = trace_input(io), trace_output(io), stage_io(io)
    assert incoming == {
        "요청": "합성 요청",
        "효능 선택": {
            "mode": "select",
            "claims": ["hydration"],
            "requested_claim": "hydration",
        },
    }
    summary = {
        "제목": "합성 제목",
        "훅": "합성 훅",
        "카피": ["합성 카피"],
        "주장 효능": ["hydration"],
        "근거 ID": ["youtube:synthetic"],
    }
    assert outgoing == {"결과": "plan", "기획안": [summary, summary]}
    assert stages["supervisor"] == {
        "output": {
            "의도": "plan",
            "효능": "hydration",
            "훅 유형": "question",
            "소구": "how_to",
            "형식": "demo",
        }
    }
    assert stages["research"] == {
        "input": {
            "목표": "합성 목표",
            "카테고리": "serum_ampoule",
            "효능": "hydration",
            "훅 유형": "question",
            "소구": "how_to",
            "형식": "demo",
            "피부 고민": "dryness",
            "산출 형식": "both",
        },
        "output": {
            "도구": ["find_example_creatives"],
            "결과 건수": [
                {"tool": "find_example_creatives", "row_count": 3, "shown_count": 2}
            ],
            "결론": "합성 결론",
        },
    }
    assert "planning #1" not in stages or "output" not in stages["planning #1"]
    planning_input = {
        "소구": "how_to",
        "요청 효능": "hydration",
        "효능 선택": {
            "mode": "select",
            "claims": ["hydration"],
            "requested_claim": "hydration",
        },
        "확인된 효능": ["hydration"],
        "근거 소재 수": 2,
    }
    assert stages["planning #1"] == {"input": planning_input}
    assert stages["planning #2"] == {
        "input": {
            **planning_input,
            "재작업": {
                "코드 검사 실패": ["SYNTHETIC_CHECK"],
                "재검토 항목": ["fit"],
            },
        },
        "output": summary,
    }
    assert stages["planning #3"] == {"input": planning_input, "output": summary}
    for k in (1, 2, 3):
        assert stages[f"evaluation #{k}"] == {
            "input": {
                "코드 검사": {
                    "통과": True,
                    "실패 코드": ["SYNTHETIC_CHECK"],
                },
                **(
                    {
                        "기획안": summary,
                        "근거 연결 없음": 0 if k == 2 else 1,
                        "효능 상태": {
                            "hydration": "supported" if k == 2 else "unsupported"
                        },
                    }
                    if k in (2, 3)
                    else {}
                ),
            },
            "output": {
                "점수": {"fit": 2, "differentiation": 3},
                "통과": False,
                "코드 검사": True,
                "재검토 항목": ["fit"],
            },
        }
    assert stages["image"] == {"input": {"장면 묘사": "합성 장면"}}
    wire = json.dumps([incoming, outgoing, stages], ensure_ascii=False)
    assert all(
        value not in wire
        for value in (
            "SYNTHETIC_NOT_ALLOWED",
            "rationale",
            "unknown",
            "profile",
            "feedback",
            "forbidden_terms",
            "raw_tool_outputs",
        )
    )


@pytest.mark.parametrize(
    "result", [None, {}, {"brief": None, "handoff": None, "plans": [{"plan": None}]}]
)
def test_missing_result_fields_are_skipped(result):
    io = RequestIO("합성 요청", None, result, ())
    assert trace_input(io) == {"요청": "합성 요청"}
    assert "결과" not in trace_output(io)
    assert stage_io(io) == {}


@pytest.mark.parametrize("brief", [None, {}, {"claim": None, "angle": ""}])
def test_research_missing_brief_values_do_not_create_input(brief):
    io = RequestIO(
        "합성 요청", None, {"brief": brief, "handoff": {"conclusion": "합성"}}, ()
    )
    assert stage_io(io)["research"] == {"output": {"결론": "합성"}}


def test_research_partial_brief_without_handoff():
    io = RequestIO(
        "합성 요청",
        None,
        {
            "brief": {
                "goal": "합성 목표",
                "claim": None,
                "angle": "",
                "max_tool_calls": 6,
            }
        },
        (),
    )
    assert stage_io(io)["research"] == {"input": {"목표": "합성 목표"}}


def test_rework_uses_immediately_previous_attempt_and_resets_for_each_plan():
    io = RequestIO(
        "합성 요청",
        None,
        {
            "plans": [
                {
                    "attempts": [
                        {"failed_check_codes": ["FIRST"], "low_items": ["fit"]},
                        {
                            "failed_check_codes": ["SECOND"],
                            "low_items": ["differentiation"],
                        },
                        {"failed_check_codes": [], "low_items": []},
                    ]
                },
                {"attempts": [{"failed_check_codes": [], "low_items": []}]},
            ]
        },
        (),
    )
    stages = stage_io(io)
    assert "planning #1" not in stages
    assert stages["planning #2"]["input"] == {
        "재작업": {
            "코드 검사 실패": ["FIRST"],
            "재검토 항목": ["fit"],
        }
    }
    assert stages["planning #3"]["input"] == {
        "재작업": {
            "코드 검사 실패": ["SECOND"],
            "재검토 항목": ["differentiation"],
        }
    }
    assert "planning #4" not in stages


def test_stage_inputs_do_not_fill_missing_result_fields_from_request():
    io = RequestIO(
        "합성 요청",
        {"mode": "select"},
        {
            "plans": [
                {
                    "attempts": [
                        {"checks_passed": False, "failed_check_codes": ["CHECK"]}
                    ]
                },
            ]
        },
        (),
    )
    assert stage_io(io) == {
        "evaluation #1": {
            "input": {
                "코드 검사": {"통과": False, "실패 코드": ["CHECK"]},
            },
            "output": {"코드 검사": False},
        }
    }


@pytest.mark.parametrize("image_count", [0, 1, 2])
def test_image_inputs_use_only_image_captures_in_capture_order(image_count):
    captures = tuple(
        Capture(purpose, START, prompt, "합성 출력")
        for purpose, prompt in (
            ("supervisor", "일반 호출"),
            ("image-plan", "첫 최종 프롬프트"),
            ("research", "일반 호출"),
            ("plan", "일반 호출"),
            ("image-other", "둘째 최종 프롬프트"),
            ("evaluate", "일반 호출"),
        )
        if not purpose.startswith("image")
        or prompt in ("첫 최종 프롬프트", "둘째 최종 프롬프트")[:image_count]
    )
    io = replace(synthetic_io(), captures=captures)
    io.result["plans"][1]["plan"] = {"image_brief": "둘째 합성 장면"}
    stages = stage_io(io)
    first = {"장면 묘사": "합성 장면"}
    second = {"장면 묘사": "둘째 합성 장면"}
    if image_count >= 1:
        first["이미지 프롬프트"] = "첫 최종 프롬프트"
    if image_count == 2:
        second["이미지 프롬프트"] = "둘째 최종 프롬프트"
    assert stages["image"] == stages["image #1"] == {"input": first}
    assert stages["image #2"] == {"input": second}


def test_match_by_purpose_nearest_unused_and_five_second_boundary():
    def call(purpose, seconds):
        return TraceCall(
            purpose=purpose,
            model="synthetic",
            ended_at=START + timedelta(seconds=seconds),
            cost_usd=0,
            cost_source="missing",
        )

    captures = tuple(
        Capture(purpose, START + timedelta(seconds=t), "합성 입력", "합성 출력")
        for purpose, t in [("plan", 2), ("plan", 1), ("evaluate", 1)]
    )
    calls = [
        call("plan", 1),
        call("plan", 2.1),
        call("plan", 2.2),
        call("evaluate", 6),
        call("other", 1),
    ]
    assert match_captures(calls, captures) == {
        0: captures[1],
        1: captures[0],
        3: captures[2],
    }
    assert match_captures([call("plan", 7.01)], captures[:1]) == {}
    assert (
        match_captures([calls[0].model_copy(update={"ended_at": None})], captures) == {}
    )
