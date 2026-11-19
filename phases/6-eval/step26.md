# Step 26: prereg-adherence-sentence

## 설계 검토 기록

**배경(조언 세션 승인, PR #50에 포함)**: dev 재스모크(`dev-smoke-axes-4`, 10건)에서 지정 축 요청 8건 중 해석 채움 6건, 과채움 0건, 최종 기획안 준수 8건이었고 해석 누락 2건은 모두 "정지 이미지" 포맷이었다. 사전 등록에는 이 한계와 지정 축 준수율·과채움을 보조 지표로 보고한다는 문장이 없다(22번째는 변경 기록, 23번째는 표시 이름 한계). 이 step은 **24번째 문장 하나를 추가**한다. 코드 동작은 바꾸지 않는다.

**사용자 확인 사항(기록)**: 임시 값 3개(`SCORING_SEED` 20261126·`MIN_STRATUM_N` 5·`E2_SCORE_PURPOSE_CAP` $1.5)는 사용자가 확정했다. `make live-evalset ARGS="finalize --dry-run"`은 통과했다(요청 30·질문 47·부족 0). `stash` 삭제는 병합 뒤 사용자가 요청할 때만 한다.

**식별자 전수 대조(현재 코드, 모두 열어 확인)**: `eval/prereg.py`(`REQUIRED_SENTENCES` 23개: 21번째 EVAL 대비 변경(step 23), 22번째 해석 변경 기록, 23번째 해석 한계(step 25); 렌더링은 `enumerate(REQUIRED_SENTENCES, 1)`로 번호를 매기고 코드가 `[1]`·`[6]`·`[7]` 인덱스를 직접 참조한다 → **끝에만 추가**한다)·`render_results_template()`(E2 행에 "지정 축 준수(코드 판정, 참고용)"와 "요청에 없는 축 채움(과채움, 코드 판정, 참고용)"이 이미 있다 → **수정하지 않는다**), `eval/e2e5_live.py`(읽기 전용: `_axis_adherence`가 축별 `specified`·`adherent`·`dominant_conflict`·`interpretation_missing`·`unrequested_filled`를 낸다).

**상수 단언 grep(전수, 이 step이 영향을 주는 `tests/test_prereg.py`의 위치)**
- 문장 수 단언 두 곳: `:42`(`len(sentences) == len(set(sentences)) == 23`)와 `:817`(`test_repeat_procedures_and_empty_distribution_template`의 `assert len(sentences) == 23`) → `== 24`.
- **고정 길이 언패킹**: `:860 test_interpretation_change_and_limit_are_appended_and_frozen`의 `changed, limitation = prereg.REQUIRED_SENTENCES[21:]`는 문장이 24개가 되면 `ValueError`(값이 너무 많음)다 → `prereg.REQUIRED_SENTENCES[21:23]`으로 바꾼다(단언은 그대로).
- **문장 해시를 고정하는 테스트 세 곳**: (a) `test_none_measurement_preserves_original_bytes`(`:567`의 렌더링 전체 SHA-256, **24번째 문장 추가로 바뀐다 → 이 기대 해시 한 줄을 새 값으로 갱신**; `uv run python`으로 `render_inputs`와 같은 합성 입력에서 계산), (b) `test_first_seventeen_procedures_remain_byte_identical`(`:131-132`, `REQUIRED_SENTENCES[:17]` → **불변**), (c) `test_failure_as_worst_procedure_is_nineteenth`(`:160-161`, `REQUIRED_SENTENCES[:18]` → **불변**). 앞 17·18개 문장을 바꾸지 않는다.

**새 칸 대응표**: 24번째 문장(dev 재스모크 관찰 → 사전 등록 절차 문장 → 결과 문서의 준수율 보고).

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건(합성 테스트만).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 사전 등록 문장은 기존 항목을 고치지 않고 끝에만 추가한다, 동결된 기준은 결과를 본 뒤 바꾸지 않는다
- `/src/beautyads/eval/prereg.py`(`REQUIRED_SENTENCES`·`render_preregistration`·`render_results_template`), `/src/beautyads/eval/e2e5_live.py`(`_axis_adherence`, 읽기 전용)
- `/tests/test_prereg.py`(`:42`·`:131`·`:160`·`:560-570`·`:810-880`)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/prereg.py`, `tests/test_prereg.py`

열람 금지 경로: `data/interim/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `src/beautyads/eval/prereg.py`, `tests/test_prereg.py`

사전 등록 `REQUIRED_SENTENCES` 끝에 24번째 문장을 추가한다. **모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: (없음)

**1. 24번째 문장(`eval/prereg.py`)**: `REQUIRED_SENTENCES` 끝에 추가한다(앞 23개의 순서·문장 불변). 내용: (a) 해석 단계는 "정지 이미지" 같은 표현에서 불안정할 수 있다. (b) 지정 축 준수율(해석 채움 건수와 최종 기획안 준수 건수)과 요청에 없는 축 채움(과채움)을 코드 판정 보조 지표로 보고하며 판정(`graph_adopted`·`verdict_e2`·`verdict_e5` 등)에 쓰지 않는다. (c) 근거는 dev 재스모크 관찰이다: 지정 축 요청 8건 중 해석 채움 6건, 과채움 0건, 최종 기획안 준수 8건이며 해석 누락 2건은 모두 정지 이미지 포맷이었다. 이 수치는 dev 관찰이며 test 결과가 아니다. `render_preregistration`의 번호 매김·인덱스 참조는 바꾸지 않는다.

**테스트(합성 데이터, 모델·접속 없음)**
- `tests/test_prereg.py`: (1) 위 "상수 단언 grep"의 갱신(`== 24` 두 곳, `[21:23]`). (2) 24번째 문장 존재(`정지 이미지`·`불안정`·`해석 채움`·`최종 기획안 준수`·`과채움`·`보조 지표`·`판정에 쓰지 않`·`dev 재스모크`·`8건`·`6건`·`0건`·`2건` 포함)와 렌더링 출력에 `24. `로 번호가 붙어 들어 있음. (3) 앞 23개 문장이 변경 전과 같다(JSON 해시 (b)·(c) 테스트가 단언 변경 없이 통과, (a)만 새 값). (4) 기존 결과 틀 테스트가 그대로 통과한다(결과 틀은 수정하지 않는다). 합성 문장·분류 값을 기대값으로 굳히지 않는다.

## Acceptance Criteria

```bash
make verify   # lint + test 통과
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - AGENTS.md CRITICAL 규칙을 위반하지 않았는가?
3. 결과를 최종 응답(JSON)으로 보고한다. `phases/` 아래 파일은 수정하지 않고 git commit도 하지 않는다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약(설치한 패키지 버전 포함)"`
   - 해결할 수 없는 실패 → `"status": "error"`, `"reason": "구체적 에러 내용"`
   - 사용자 개입 필요 (API 키, 외부 인증, 수동 설정 등) → `"status": "blocked"`, `"reason": "구체적 사유"` 후 즉시 중단

## 공통 금지사항

<!-- common-block:start -->
- **선점검**: 코드를 쓰기 전에 이 파일의 작업 지시·금지사항·"수정할 파일" 목록을 서로 대조한다. 충돌(하나가 요구한 것을 다른 것이 금지함, 수정할 파일 목록 밖 파일의 수정이 필요함, 계층 경계 위반)이 있으면 코드를 쓰지 않고 즉시 `blocked`로 보고한다. reason에는 충돌하는 두 문장을 그대로 인용한다. 충돌이 없으면 진행한다.
- **실제 서비스**: 실제 서비스(YouTube·Instagram·TikTok·식약처 공공 API·브랜드 공식몰·Gemini·OpenAI·Anthropic·LiteLLM·Langfuse·Neo4j·PostgreSQL·외부 API)에 접속하는 코드는 작성할 수 있다. step 안에서 그 코드를 실행하거나 그 코드에 접속하는 테스트를 만들지 않는다. 테스트는 가짜 환경(가짜 실행기·로컬 루프백·`tests/fixtures/contracts/`의 응답 원본에서 만든 픽스처)으로만 한다.
- **계층 경계**: `AGENTS.md`의 계층 경계 표와 `tests/test_architecture.py`를 따른다. 가드 테스트를 약화하지 않는다.
- **읽기 전용**: `.claude/`, `docs/EVAL.md`의 동결된 판정 기준, `docs/results/`의 사전 등록 파일, `scripts/`, `phases/`, `tests/fixtures/contracts/`의 응답 원본은 읽기만 한다(이 step의 "수정할 파일"에 있는 것만 예외). 기존 테스트의 단언을 약화하지 않는다.
- **비밀 값**: `.env`를 열거나 출력하지 않는다. 토큰·키·Authorization 헤더를 코드·테스트·문서·로그·trace에 남기지 않는다.
<!-- common-block:end -->

## 이 step의 금지사항

- `REQUIRED_SENTENCES`의 기존 23개 문장·순서·번호를 바꾸거나 `render_results_template`·`render_preregistration`의 구조를 바꾸지 마라. 이유: 사전 등록 문장은 끝에만 추가하고 앞 17·18개는 해시로 고정되어 있다.
- 판정 로직·상수·동결 값, `eval/e2e5_live.py`·`eval/e2_scoring.py`를 수정하거나 새 의존성을 추가하지 마라. 이유: 이 step은 문장 추가뿐이다(허용 범위 밖이면 `blocked`로 보고).
- 기존 테스트의 단언을 약화하지 마라(위 "상수 단언 grep"에 적힌 문장 수·언패킹 범위·해시 (a) 한 줄 갱신만 허용). 이유: 이미 통과한 step의 계약이다.
