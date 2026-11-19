"""Render offline preregistration and blank results; never commit or overwrite.

The CLI reads E3 dev measurement evidence and the finalized
data/evalset/isolation_requests.jsonl. It does not run measurements or services.
After set confirmation, use --print or --write with a new document path.
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from beautyads.domain.research import ResearchBrief
from beautyads.domain.supervisor import RequestLimits
from beautyads.eval import e2_scoring, e2e5_live, e3_live, evalset_candidates
from beautyads.eval.evalset import (
    ANSWERS_PATH,
    EVALSET_DIR,
    QUESTIONS_PATH,
    REQUESTS_PATH,
    WORKSPACES_PATH,
    EvalsetError,
    question_set_hash,
    read_jsonl,
    request_set_hash,
    validate_set,
)
from beautyads.eval.freeze_guard import (
    PREREG_LINE_FORMAT,
    PREREG_PATH,
    QUESTION_HASH_LABEL,
    REQUEST_HASH_LABEL,
    frozen_values,
)
from beautyads.eval.single_agent import SINGLE_AGENT_PROMPT_VERSION
from beautyads.llm.prices import EMBEDDING_PRICES

EMBEDDING_MEASUREMENT_PATH = e3_live.OUTPUT_DIR / "measurement.json"
ISOLATION_REQUESTS_PATH = EVALSET_DIR / "isolation_requests.jsonl"

DEV_MEASUREMENT_KEYS = {
    "root": (
        "selected_model",
        "dev_question_hash",
        "selection_rule",
        "truncated_document_ratio",
        "truncated_dev_evidence_ratio",
        "n_set_questions_values_not_in_corpus",
        "models",
        "combinations",
    ),
    "models": (
        "embedding_model",
        "price_per_million",
        "hit_at_k",
        "recall_at_k",
        "n_with_target",
        "n_no_target",
        "hit_at_k_all_questions",
    ),
    "combinations": (
        "embedding_model",
        "top_k",
        "max_doc_chars",
        "hit_at_k",
        "recall_at_k",
        "n_with_target",
        "n_no_target",
    ),
}


def validate_dev_measurement(measurement) -> None:
    """Validate offline measurement evidence without replacing any file values."""
    invalid = "PREREG_INPUT_INVALID"
    if not isinstance(measurement, dict):
        raise ValueError(invalid)  # noqa: TRY004 -- fixed public validation error
    groups = {"root": [measurement]}
    for name in ("models", "combinations"):
        rows = measurement.get(name)
        if not isinstance(rows, list) or not rows:
            raise ValueError(invalid)
        groups[name] = rows
    for name, rows in groups.items():
        for row in rows:
            if not isinstance(row, dict) or not all(
                key in row for key in DEV_MEASUREMENT_KEYS[name]
            ):
                raise ValueError(invalid)
            for key in DEV_MEASUREMENT_KEYS[name]:
                value = row.get(key)
                if key in ("models", "combinations"):
                    continue
                if key in (
                    "selected_model",
                    "embedding_model",
                    "dev_question_hash",
                    "selection_rule",
                ):
                    if not isinstance(value, str) or ":" in value:
                        raise ValueError(invalid)
                elif key in ("top_k", "max_doc_chars"):
                    if type(value) is not int or value <= 0:
                        raise ValueError(invalid)
                elif key in (
                    "n_with_target",
                    "n_no_target",
                    "n_set_questions_values_not_in_corpus",
                ):
                    if type(value) is not int or value < 0:
                        raise ValueError(invalid)
                elif value is not None and type(value) not in (int, float):
                    raise ValueError(invalid)
            if name == "models" and row.get("embedding_model") not in EMBEDDING_PRICES:
                raise ValueError(invalid)
    selected = measurement.get("selected_model")
    if (
        selected not in EMBEDDING_PRICES
        or selected not in {row.get("embedding_model") for row in groups["models"]}
        or re.fullmatch(r"[0-9a-f]{64}", measurement.get("dev_question_hash")) is None
    ):
        raise ValueError(invalid)


def _dev_measurement_lines(measurement):
    def table(header, rows):
        return [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
            *(
                "| "
                + " | ".join(
                    "해당 없음" if value is None else str(value) for value in row
                )
                + " |"
                for row in rows
            ),
            "",
        ]

    lines = [
        "## E3 dev 측정 근거",
        "",
        (
            "측정 파일의 값을 그대로 옮겼으며 모델 선택은 6번 문장의 규칙(hit@k 최고, 동률이면 저가)을 따른다. "
            "TOP_K와 MAX_DOC_CHARS는 사용자가 사전 등록 전에 확정한다."
        ),
        "",
    ]
    for name, header in (
        (
            "models",
            (
                "모델",
                "단가(100만 토큰당 USD)",
                "hit@k",
                "recall@k",
                "대상 질문 수",
                "대상 없는 질문 수",
                "옛 정의 hit@k(전체 질문 기준)",
            ),
        ),
        (
            "combinations",
            (
                "모델",
                "TOP_K",
                "MAX_DOC_CHARS",
                "hit@k",
                "recall@k",
                "대상 질문 수",
                "대상 없는 질문 수",
            ),
        ),
    ):
        lines.extend(
            table(
                header,
                (
                    [row.get(key) for key in DEV_MEASUREMENT_KEYS[name]]
                    for row in measurement.get(name)
                ),
            )
        )
    lines.extend(
        table(
            ("항목", "값"),
            (
                (label, measurement.get(key))
                for label, key in (
                    ("선택 모델", "selected_model"),
                    ("선택 규칙", "selection_rule"),
                    ("dev 질문 세트 해시", "dev_question_hash"),
                    ("잘린 문서 비율", "truncated_document_ratio"),
                    (
                        "정답 근거 소재 문서 중 잘린 비율",
                        "truncated_dev_evidence_ratio",
                    ),
                    (
                        "정답 값이 코퍼스에 없는 집합 질문 수",
                        "n_set_questions_values_not_in_corpus",
                    ),
                )
            ),
        )
    )
    return lines


REQUIRED_SENTENCES = (
    (
        "기준 숫자는 `docs/EVAL.md` 그대로이고 이 문서는 절차 세부만 추가한다. "
        "결과가 기준에 못 미쳐도 그대로 보고한다."
    ),
    (
        'E2는 "한 에이전트 대 한 시스템" 비교다. 두 팔은 생성 모델(gpt-6.1-terra, reasoning_effort low), '
        "도구 집합, 그래프, API 호출 재시도·구조화 교정 한도, 도구 호출 한도, 요청당 텍스트 비용 상한이 같다. "
        "Supervisor 팔은 요청 해석, 리서치 분리, 코드가 만드는 보조 값(pattern_context, available_efficacy, "
        "aggregates 검증), 루프 내 평가와 최대 2회 재작업 루프를 시스템으로서 함께 가진다. "
        "단일 팔은 보조 값(pattern_context, available_efficacy)을 받지 않는다. "
        "차이는 시스템 구성 전체의 효과이며 결과 문서에도 그렇게 적는다."
    ),
    (
        "반복 횟수는 요청당 팔마다 1회(요청 20건), 쌍 비교 부트스트랩 10,000회(퍼센타일 95%), "
        "시드는 코드 상수 값, 기준 판정은 CI가 0을 넘는지(하한 > 0)로 한다."
    ),
    (
        "E2 채점은 Anthropic sonnet이고 팔 이름을 숨기고 순서를 섞고 시드를 고정하며 "
        '루프 내 평가와 다른 루브릭·프롬프트를 쓴다. 사람 "claim 일치" 판정 약 200건은 '
        "편향 점검용이며 주 판정이 아니다(1인 라벨링)."
    ),
    (
        'E5 "끔"의 정의와 식별자 목록(우회: `trim_handoff`·`tool_result_payload` 이원화·원출력 비전달, '
        "추가 전달: `sv_tool_outputs`를 `raw_tool_outputs` 필드로; "
        "유지: `trim_message`·`_text_data`·`research_payload`·`MAX_ROWS` 표시; 불변: 상수·함수 정의), "
        "입력 토큰은 요청 중 원장 증가분의 `input_tokens` 합이다. E5 (a)는 E2 Supervisor 실행을 재사용하며 "
        "같은 코드 커밋·같은 세트 해시·같은 채점 실행일 때만 유효하고 "
        "코드 커밋 해시와 사전 등록 커밋 해시를 결과 문서에 적는다. 이력 압축은 이 실험에 넣지 않는다."
    ),
    (
        "E3: 코퍼스 필드(`CORPUS_FIELDS`), top-k(`TOP_K`), 문서 길이 자르기(`MAX_DOC_CHARS`), "
        "답 프롬프트 버전(`ANSWER_PROMPT_VERSION`), 청크 방식(청크 분할 없음), "
        "임베딩 모델과 선택 기준(dev 질문 hit@k 최고, 동률이면 저가)이 고정이다. "
        "정답은 그래프 질의로 계산해 사람이 확인했다(그래프에 유리한 질문일 수 있다). "
        "코퍼스에 test 브랜드 소재가 섞인다. 질문 40건과 단순 검색형 10건 부분집합을 따로 보고한다."
    ),
    (
        "격리: 4경로·경로당 50건·합계 200건, 표식 문자열 검색을 코드가 판정, 노출 0건 기준, "
        '정상 요청 응답률을 짝 지표로 보고한다. 경로 3은 "다른 테넌트의 thread_id 요청 거부 + 정상 요청 응답 확인"이며 '
        "대화 압축 요약 경로는 미구현이라 대상이 아니다. 어디서도 대화 압축 격리를 검증했다고 쓰지 않는다. "
        "재작업 경로(max_reworks=0)는 실행되지 않는다. 요청당 `max_plans=1`, `max_reworks=0`. "
        "0건은 관측값이지 증명이 아니며 시도한 요청 유형의 범위를 결과와 함께 적는다."
    ),
    (
        "층화 보조 분석: 요청·질문의 `axes_used`(세트 확정 때 고정)로 충족 축만 쓰는 항목과 "
        "미충족 축(hook_type·angle·talent·has_proof_segment·is_vertical·has_text_overlay·cta_type·claims)을 "
        "쓰는 항목을 나눠 따로 보고한다. 결론 근거가 아니며 층의 건수가 작으면 판정 불가로 적는다. "
        '문항은 빼지 않는다. 미충족 축과 claims는 "라벨 신뢰도 낮음(κ x.xx)"로 표시하고 '
        "κ 값은 E1 결과 문서에서 그대로 읽는다. 재검사 κ는 재현성 증거로 쓰지 않는다."
    ),
    (
        "동결: 프롬프트 버전·상수·`_SYSTEM` sha256과 세트 해시가 위 줄과 같을 때만 "
        "test 실행(와 격리 최종 실행)이 코드로 허용된다. 동결 뒤 프롬프트·상수·세트를 바꾸지 않는다."
    ),
    (
        "E4는 선택이며 11-24까지 구현을 시작하지 못했으면 하지 않는다"
        '(11-28까지 나머지 실험이 끝나지 않아도 하지 않는다). 하지 않은 경우 결과 문서에 "미수행"과 이유를 적는다.'
    ),
    (
        '이미지 생성은 실험에서 끈다. 모든 사람 판정 수치에 "1인 라벨링"을 병기한다. '
        "건수가 작으면 작다고 적는다. 기준을 못 넘긴 항목·판정 불가 항목도 같은 표에 넣는다. "
        "정정은 기존 문장을 고치지 않고 정정 기록으로만 쌓는다."
    ),
    (
        "비용 상한과 실행 순서: E3, E2, E5, 격리, E4(Anthropic 잔여 $1.5 이상일 때만). "
        "호출 전 공급사별 누적액 검사는 유지한다."
    ),
    (
        "변경 규칙: 사전 등록 이후 `src/`·`config/`·`data/evalset/`를 수정하면 "
        "재등록(새 사전 등록 문서와 새 커밋)이 필요하다. "
        "재등록 전에는 test와 격리 최종 실행이 코드로 막힌다."
    ),
    (
        "커밋 절차: 사전 등록 커밋은 확정 세트(`data/evalset/`의 요청·질문·정답 파일)와 이 문서를 "
        "함께 커밋한다(`data/evalset/`는 gitignore 대상이 아니며 최종 가드가 이 폴더의 작업 트리 변경을 차단한다)."
    ),
    (
        "E3 관계 질문 후보는 정답이 비었거나 정답 집합 크기가 "
        f"{evalset_candidates.MAX_ANSWER_SET}을 넘는 질문을 제외했다. "
        "CQ-08·CQ-13·CQ-14는 데이터 부재로 항상 빈 정답이라 제외된다. "
        "관계 질문은 소수 CQ 유형의 닫힌 입력 조합에서 만든 것이므로 "
        "질문 간 독립이 아니며 결과는 이 템플릿 범위에 한정한다."
    ),
    (
        "E3 채택 판정은 기존 완전 일치 기준 그대로이며 set 질문의 부분 점수(F1)는 참고용으로 판정에 쓰지 않는다. "
        f"정답 집합 크기 {e3_live.SIZE_STRATUM_THRESHOLD} 이하 대 초과와 실행에 쓴 TOP_K 이하 대 초과로 "
        "층화 보고한다(참고용, 채택 판정 없음). 벡터 팔은 TOP_K 문서만 보는 구조적 한계가 있어 이 층 구분이 필요하다. "
        "TOP_K와 MAX_DOC_CHARS는 dev 질문의 재현율과 비용을 보고 사용자가 사전 등록 전에 확정하며 "
        "test 결과를 본 뒤에는 바꾸지 않는다. 임베딩 측정의 hit@k는 정답에서 대응되는 코퍼스 문서"
        "(evidence_ids와 문서 id로 대응되는 정답 값)가 있는 질문만 평균하고 대상이 없는 질문 수를 함께 보고한다. "
        "현재 코퍼스 필드에 없는 값(효능·카테고리 값 등)을 정답으로 하는 질문은 "
        "벡터 팔이 정의상 도달할 수 없고 이 한계를 결과에 적는다."
    ),
    (
        "E3 코퍼스에는 표현 규칙 문서가 포함되며 문서 id는 규칙 ID다. "
        "규칙이 직접 걸리는 대상(APPLIES_TO, 그래프가 적재하는 advisor_approved·confirmed 범위 상태만)만 "
        "적고 상속 관계를 미리 펼치지 않는다(상속·범위 추론은 벡터 팔이 직접 해야 한다). "
        "코퍼스에서 도달 가능한 질문만의 부분집합 결과(reachable_subset)는 참고용이며 "
        "채택 판정(graph_adopted 등)은 기존 전체 질문 기준이다. "
        "코퍼스에 없는 값(효능·카테고리 값 등)을 정답으로 하는 질문은 도달 불가라는 한계로 적고 "
        "도달 가능 질문 수를 함께 보고한다."
    ),
)


def render_preregistration(
    *,
    request_hash,
    question_hash,
    extra,
    embedding,
    isolation_hash,
    today,
    dev_measurement=None,
) -> str:
    """Render caller-supplied hashes and runner labels alongside current code."""
    if dev_measurement is not None:
        validate_dev_measurement(dev_measurement)
    values = {
        REQUEST_HASH_LABEL: request_hash,
        QUESTION_HASH_LABEL: question_hash,
        **frozen_values(),
    }
    # Extra labels belong to the runners. Do not rename or reconstruct them.
    for label, value in sorted(extra.items()):
        if label in values and values[label] != value:
            raise ValueError("PREREG_INPUT_INVALID")
        values[label] = value
    values["격리 요청 세트 해시"] = isolation_hash
    lines = [
        f"# P6 사전 등록 ({today.isoformat()})",
        "",
        "상태: 생성됨. 확정 세트와 이 문서를 함께 커밋한 뒤에만 최종 실험을 실행한다.",
        "기존 사전 등록 문장은 수정하지 않고 정정 기록을 추가한다.",
        "",
        "## 동결 값",
        "",
        *(PREREG_LINE_FORMAT.format(label=k, value=v) for k, v in values.items()),
        "",
        "## 코드에서 읽은 절차 값",
        "",
        "| 항목 | 값 |",
        "| --- | --- |",
        f"| 단일 에이전트 프롬프트 버전 | {SINGLE_AGENT_PROMPT_VERSION} |",
        f"| E2 채점 프롬프트 버전 | {e2_scoring.E2_SCORING_PROMPT_VERSION} |",
        f"| SCORING_SEED | {e2_scoring.SCORING_SEED} |",
        f"| BOOTSTRAP_RESAMPLES | {e2_scoring.BOOTSTRAP_RESAMPLES} |",
        f"| CI_CONFIDENCE | {e2_scoring.CI_CONFIDENCE} |",
        f"| E2_SCORE_PURPOSE_CAP | {e2_scoring.E2_SCORE_PURPOSE_CAP} |",
        f"| MIN_STRATUM_N | {e2_scoring.MIN_STRATUM_N} |",
        f"| E5_MIN_TOKEN_REDUCTION | {e2_scoring.E5_MIN_TOKEN_REDUCTION} |",
        f"| E5_MIN_VALIDITY_LOWER | {e2_scoring.E5_MIN_VALIDITY_LOWER} |",
        f"| EMBED_PURPOSE_CAP | {e3_live.EMBED_PURPOSE_CAP} |",
        f"| 임베딩 모델 | {embedding} |",
        f"| 도구 호출 한도 | {ResearchBrief.model_fields['max_tool_calls'].default} |",
        *(
            f"| RequestLimits.{name} | {value} |"
            for name, value in RequestLimits().model_dump().items()
        ),
        "",
        *(
            _dev_measurement_lines(dev_measurement)
            if dev_measurement is not None
            else []
        ),
        "## 절차와 한계",
        "",
        *(f"{i}. {sentence}\n" for i, sentence in enumerate(REQUIRED_SENTENCES, 1)),
        "## 정정 기록",
        "",
        "기존 문장 대신 날짜·이유·변경 범위·새 사전 등록 커밋을 추가 기록한다.",
        "",
    ]
    return "\n".join(lines)


def _blank_table(header, rows):
    width = len(header)
    return [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
        *("| " + " | ".join([row, *([""] * (width - 1))]) + " |" for row in rows),
        "",
    ]


def render_results_template() -> str:
    """Return blank reporting tables; no observation or decision is invented."""
    lines = [
        "# P6 실험 결과",
        "",
        "모든 수치에 건수·기준일·조건을 함께 적고 사람 판정은 1인 라벨링으로 표시한다.",
        "기준 미달과 판정 불가 항목도 같은 표에 넣는다. 결과가 기준에 못 미쳐도 그대로 보고한다.",
        "사전 등록 커밋은 확정 세트와 문서를 함께 커밋한 것이다.",
        "",
    ]
    metrics = {
        "E2": (
            "근거 유효율(사람 claim 일치, 1인 라벨링)",
            "요청 적합성·차별성",
            "쌍 비교 차이·95% CI",
            "비용·지연(p50·p95)·모델 호출 수",
        ),
        "E3": (
            "정답률·쌍 비교 차이·95% CI",
            "근거 소재 적중률",
            "관계형 질문",
            "단순 검색형 부분집합",
            "임베딩 모델 선택(dev hit@k·가격)",
        ),
        "E4": ("AUC", "미수행", "이유"),
        "E5": (
            "입력 토큰 합계·감소율",
            "근거 유효율 차이·95% CI 하한",
            "품질 점수",
            "비용·지연",
            "E2 Supervisor 재사용 조건·채점 실행 식별자",
        ),
        "격리": ("표식 노출 건수", "정상 요청 응답률", "시도한 요청 유형의 범위"),
    }
    for experiment, rows in metrics.items():
        lines.extend([f"## {experiment}", ""])
        lines.extend(
            _blank_table(
                ("항목", "값"),
                (
                    "건수",
                    "기준일",
                    "조건",
                    "코드 커밋 해시",
                    "사전 등록 커밋 해시",
                    "모델 ID",
                    "판정 코드",
                    "기준 미달 항목",
                    "판정 불가 항목",
                ),
            )
        )
        lines.extend(
            _blank_table(("지표", "건수", "측정값", "동결 기준", "판정 코드"), rows)
        )
        if experiment == "E2":
            lines.extend([REQUIRED_SENTENCES[1], ""])
        elif experiment == "격리":
            lines.extend([REQUIRED_SENTENCES[6], ""])
            lines.extend(
                _blank_table(
                    ("경로", "시도 건수", "표식 노출", "정상 요청 응답률"),
                    (
                        "그래프 도구",
                        "피드백 메모리",
                        "thread_id 요청 거부·정상 요청",
                        "최종 응답",
                    ),
                )
            )
    lines.extend(["## 층화 보조 분석", "", REQUIRED_SENTENCES[7], ""])
    lines.extend(
        _blank_table(
            ("층", "실험", "건수", "측정값·CI", "판정 코드"),
            ("충족 축만 사용", "미충족 축·claims 사용"),
        )
    )
    lines.extend(
        _blank_table(
            ("축", "E1 사람·모델 κ 원문 값", "라벨 신뢰도 표시"),
            (
                "hook_type",
                "angle",
                "talent",
                "has_proof_segment",
                "is_vertical",
                "has_text_overlay",
                "cta_type",
                "claims",
            ),
        )
    )
    lines.extend(
        [
            "## 한계",
            "",
            "- 작은 표본과 판정 불가 항목의 범위를 적는다.",
            "- 사람 판정은 1인 라벨링이며 재검사 κ는 재현성 증거로 쓰지 않는다.",
            (
                "- E3 정답은 그래프 질의로 계산해 사람이 확인했다. 그래프에 유리한 질문일 수 있고 "
                "코퍼스에 test 브랜드 소재가 섞인다."
            ),
            "- E5는 이력 압축을 포함하지 않는다. 격리의 대화 압축 요약 경로는 미구현이다.",
            "- 격리 노출이 없더라도 관측값이며 증명으로 쓰지 않는다.",
            "",
            "## 정정 기록",
            "",
            "기존 문장을 고치지 않고 날짜·이유·변경 범위를 추가한다.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv=None, *, out=sys.stdout) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--print", action="store_true", help="사전 등록 문서 출력(기본)"
    )
    actions.add_argument(
        "--write", type=Path, metavar="PATH", help=f"새 파일로 저장(예: {PREREG_PATH})"
    )
    actions.add_argument("--results-template", action="store_true")
    parser.add_argument("--dev-measurement", type=Path, metavar="PATH")
    args = parser.parse_args(argv)
    if args.results_template:
        out.write(render_results_template())
        return 0
    # lexists semantics also protect a dangling symlink; open('x') below closes
    # the race between this read-only precheck and creating the new document.
    if args.write is not None and (args.write.exists() or args.write.is_symlink()):
        print("PREREG_FILE_EXISTS", file=out)
        return 1
    try:
        requests, questions, answers = (
            read_jsonl(path) for path in (REQUESTS_PATH, QUESTIONS_PATH, ANSWERS_PATH)
        )
        validate_set(
            requests, questions, answers, final=True, workspaces_path=WORKSPACES_PATH
        )
        measurement_path = (
            args.dev_measurement
            if args.dev_measurement is not None
            else EMBEDDING_MEASUREMENT_PATH
        )
        selection = json.loads(measurement_path.read_text(encoding="utf-8"))
        validate_dev_measurement(selection)
        embedding = selection.get("selected_model")
        isolation = read_jsonl(ISOLATION_REQUESTS_PATH)
        if not isolation:
            raise ValueError("PREREG_INPUT_INVALID")
        text = render_preregistration(
            request_hash=request_set_hash(requests),
            question_hash=question_set_hash(questions, answers),
            extra={**e2e5_live._extra_frozen(), **e3_live.extra_frozen(embedding)},
            embedding=embedding,
            isolation_hash=request_set_hash(isolation),
            today=date.today(),
            dev_measurement=selection,
        )
    except EvalsetError as exc:
        print(exc.code, file=out)
        return 1
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        print("PREREG_INPUT_INVALID", file=out)
        return 1
    if args.write is None:
        out.write(text)
        return 0
    try:
        with args.write.open("x", encoding="utf-8") as document:
            document.write(text)
    except FileExistsError:
        print("PREREG_FILE_EXISTS", file=out)
        return 1
    except OSError:
        print("PREREG_WRITE_FAILED", file=out)
        return 1
    print("사전 등록 커밋은 `data/evalset/`와 이 문서를 함께 커밋한다", file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
