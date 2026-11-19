# Step 23: test-questions-37

## 설계 검토 기록

**배경(사용자 확정·조언 세션 승인)**: test 질문 목표를 40건에서 **37건(관계 27 + 단순 검색 10)**으로 바꾼다. 사유: 후보 중 CQ-04 count 질문 10건은 정답이 항상 1(결과 행 수)이라 정보가 없어 제외했고, 닫힌 입력 조합을 모두 계산해도 유효한 관계 질문이 27건이다. 단순 검색 10건·요청 20건·dev 구성(요청 10·질문 10)은 불변이다. `docs/EVAL.md`는 수정하지 않는다(사전 등록 문장에 변경을 적는다).

**식별자·리터럴 전수 대조(grep 결과, 모두 열어 확인)**
- `eval/evalset.py:266-268`: `validate_set(..., final=True)`가 `Counter(row.split for row in questions) != {"dev": 10, "test": 40}`와 `sum(row.split == "test" and row.kind == "simple_search" ...) != 10`이면 `EVALSET_COUNT_INVALID`다. 이 두 곳이 40·10의 원천 리터럴이다.
- `eval/e3_live.py:130`(`_questions(questions, mode)`): `mode == "final"`에서 `len(questions) != 40 or sum(q.kind == "simple_search" ...) != 10`이면 `E3Error("EVALSET_COUNT_INVALID")`이다(`run`·`report`·`measure` 경로가 공유한다).
- `eval/evalset_candidates.py:162-168 _FINAL_TARGETS`(`requests_dev` 10·`requests_test` 20·`questions_dev` 10·`questions_test_graph` 30·`questions_test_simple_search` 10), 그리고 파생: `DEV_TARGETS`(`:169`, dev 키만 → **영향 없음**), `ReviewedSet.shortages`(`:196`)·`_shortages`(`:202`)·후보 목표 `ceil(value * CANDIDATE_FACTOR)`(`:292·:438`; test 관계 후보 목표가 `ceil(30*1.5)=45` → `ceil(27*1.5)=41`로 바뀐다)·관계 질문 배정 상한 `targets["questions_dev"] + targets["questions_test_graph"]`(`:502`)·dev 몫 비율 `_FINAL_TARGETS["questions_dev"] / (questions_dev + questions_test_graph)`(`:510-511`; 10:30 → 10:27로 바뀐다. **이미 만든 후보·시트는 이 변경의 영향을 받지 않는다**: 후보 파일 생성기를 다시 돌릴 때만 배정이 달라지며 시트는 해시로 후보 파일에 묶여 있어 다시 만들면 어차피 무효다)·`final_shortages`(`:563`)·시트 지침 문자열 `:676`("질문 dev 10/test 관계 30·단순 검색 10"), `:1018`쪽 호출들.
- `eval/prereg.py:256`: E3 문장 "…질문 40건과 단순 검색형 10건 부분집합을 따로 보고한다."(6번째 문장, `REQUIRED_SENTENCES[5]`). `render_results_template()`의 E3 행에는 질문 수 숫자가 없다(확인).
- `eval/freeze_guard.py`·`eval/isolation_live.py`·`eval/e2e5_live.py`·`eval/p5_compare.py`: 질문 수 리터럴 없음(`validate_set`을 통해서만 간접 의존; `freeze_guard.py:107`의 `{40,64}`는 git 해시 길이 정규식으로 무관).
- **E3 판정 코드의 질문 수 가정(확인)**: `e3_live._summary`가 `"decision": "undecidable" if len(ids) < 20 else ("graph_adopted" if ci[0] > 0 else "not_adopted")`(`:579-584`)이다. 37건(전체)·27건(관계형 부분집합)은 20 이상이라 판정 불가 하한에 걸리지 않고, 단순 검색 10건 부분집합은 10 < 20이라 이전처럼 `undecidable`(참고용)이다. 부트스트랩(`bootstrap_ci(diffs)`)과 층·크기 층·도달 가능 부분집합의 최소 n(`MIN_STRATUM_N = 5`)은 질문 수 40을 가정하지 않는다. **판정 코드는 바꾸지 않는다.**

**상수 단언 grep(테스트, 전수)**: 아래 외의 기존 테스트는 영향이 없다(`tests/test_freeze_guard.py`·`tests/test_isolation_live.py`·`tests/test_e2*.py`에는 질문 수 40 리터럴이 없고 `test_evalset.synthetic_set()`을 가져다 쓴다).
- `tests/test_evalset.py:35`: `synthetic_set()`의 `("test", 20, 40)` → test 질문 37건(앞 10건 `simple_search`, 나머지 `graph` 27건: `kind`는 `index < 10`이면 단순 검색인 기존 방식 유지). 이 합성 세트를 쓰는 테스트(`tests/test_prereg.py`·`tests/test_freeze_guard.py`·`tests/test_isolation_live.py`의 최종 가드 사용)는 자동으로 37을 따른다.
- `tests/test_evalset.py:332-350 test_final_counts`(질문·요청 하나를 빼거나 단순 검색을 그래프로 바꾸면 `EVALSET_COUNT_INVALID`): 유지한다(37 기준에서도 같은 동작). **경계 테스트를 추가한다(아래)**.
- `tests/test_e3_live.py`: `:259·:262·:278`(`range(40)` 질문 40건·`result["overall"]["n"] == 40`), `:391`, `:691·:694`, `:1559`(`range(1 if mode == "dev" else 40)`)의 final 모드 합성 질문 수 40 → 37(단순 검색 10 포함). `:278`의 `n`은 37로 갱신한다.
- `tests/test_evalset_candidates.py`: 최종 목표 30을 값으로 쓰는 단언 — `:303-304`(후보 목표 기준 부족 `questions_test_graph` 44 → `ceil(27*1.5)=41`에서 하나를 뺀 40), `:423-424`, `:600`(`("graph", "test"): 30`), `:1026-1027`(`questions_test_graph: 30`), `:1076-1082`·`:1125-1126`(부족 건수 `5`·`20`·`29` 등 `30`에서 계산한 값), `:1169-1171`(`final_shortages["questions_test_graph"] == 30`), `:1361-1362`. 각각 새 목표(27)와 후보 목표(41)에서 **다시 계산한 값**으로 갱신하되 가능하면 `candidates._FINAL_TARGETS`·`math.ceil(… * candidates.CANDIDATE_FACTOR)`처럼 상수에서 읽는다(리터럴을 새 값으로 바꿀 때는 의도를 단언 이름·값 비교로 남긴다). `DEV_TARGETS`·`finalize --split dev` 관련 테스트(`:664-` 이후 dev-split 테스트)는 **불변이어야 한다**.
- `tests/test_prereg.py`: 문장 수 단언 `:42`와 `:800`의 `== 20` → `== 21`. **문장 해시를 고정하는 테스트가 세 곳**이다: (a) `test_none_measurement_preserves_original_bytes`(`:550`, `dev_measurement=None` 렌더링 전체 SHA-256), (b) `test_first_seventeen_procedures_remain_byte_identical`(`:113-117`, `REQUIRED_SENTENCES[:17]` — **6번째 문장이 바뀌어 달라진다**), (c) `test_failure_as_worst_procedure_is_nineteenth`(`:120-145`, `REQUIRED_SENTENCES[:18]` — 같은 이유). 세 기대 해시를 각각 한 줄씩 새 값으로 갱신한다(`uv run python`으로 계산; 사전 등록 문서 생성 전이라 문장 수정이 허용되며 이 해시들은 이후 변경을 막는 장치로 남는다). 각 테스트의 나머지 단언은 유지한다.

**새 칸 대응표**: 원천 상수 `TEST_QUESTIONS_COUNT = 37`·`TEST_SIMPLE_SEARCH_COUNT = 10`·`TEST_GRAPH_QUESTIONS_COUNT = TEST_QUESTIONS_COUNT - TEST_SIMPLE_SEARCH_COUNT`(27)(`evalset.py` 한 곳 → `validate_set`·`e3_live._questions`·`evalset_candidates._FINAL_TARGETS`·사전 등록 문장), 사전 등록 21번째 문장(EVAL.md 대비 변경 기록).

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건(합성 테스트만).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: `docs/EVAL.md`의 동결 기준은 결과를 본 뒤 바꾸지 않는다(질문 수 변경은 사전 등록 전에 사용자가 확정하고 사전 등록 문장에 기록한다), 모델이 만든 값을 테스트 기대값으로 굳히지 않는다
- `/src/beautyads/eval/evalset.py`(`validate_set`), `/src/beautyads/eval/evalset_candidates.py`(`_FINAL_TARGETS`와 파생, `_finalize`·`_finalize_dev`), `/src/beautyads/eval/e3_live.py`(`_questions`·`_summary`), `/src/beautyads/eval/prereg.py`(`REQUIRED_SENTENCES`), `/docs/EVAL.md`(E3 절, 읽기 전용)
- `/tests/test_evalset.py`(`synthetic_set`·`test_final_counts`), `/tests/test_evalset_candidates.py`(위 목록의 줄), `/tests/test_e3_live.py`(위 목록의 줄), `/tests/test_prereg.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/evalset.py`, `src/beautyads/eval/evalset_candidates.py`, `src/beautyads/eval/e3_live.py`, `src/beautyads/eval/prereg.py`, `tests/test_evalset.py`, `tests/test_evalset_candidates.py`, `tests/test_e3_live.py`, `tests/test_prereg.py`

열람 금지 경로: `data/interim/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 후보 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `src/beautyads/eval/evalset.py`, `src/beautyads/eval/evalset_candidates.py`, `src/beautyads/eval/e3_live.py`, `src/beautyads/eval/prereg.py`, `tests/test_evalset.py`, `tests/test_evalset_candidates.py`, `tests/test_e3_live.py`, `tests/test_prereg.py`

test 질문 목표를 37건(관계 27·단순 검색 10)으로 바꾸고 사전 등록 문장에 변경을 기록한다. **모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: `TEST_QUESTIONS_COUNT`, `TEST_SIMPLE_SEARCH_COUNT`, `TEST_GRAPH_QUESTIONS_COUNT`

**1. 원천 상수와 검증(`eval/evalset.py`)**
- 모듈 상수 `TEST_QUESTIONS_COUNT = 37`, `TEST_SIMPLE_SEARCH_COUNT = 10`, `TEST_GRAPH_QUESTIONS_COUNT = TEST_QUESTIONS_COUNT - TEST_SIMPLE_SEARCH_COUNT`(27). `validate_set(final=True)`의 질문 수 조건을 `Counter(row.split for row in questions) != {"dev": 10, "test": TEST_QUESTIONS_COUNT}`와 `sum(test 단순 검색) != TEST_SIMPLE_SEARCH_COUNT`로 바꾼다(dev 10·요청 dev 10·test 20·오류 코드 `EVALSET_COUNT_INVALID`·그 밖의 검증 불변).

**2. 소비처(`eval/e3_live.py`·`eval/evalset_candidates.py`)**
- `e3_live._questions`의 final 조건 `len(questions) != 40 or sum(simple_search) != 10`을 위 상수로 바꾼다(`evalset`에서 가져온다). **`_summary`의 `len(ids) < 20`(판정 불가 하한)·부트스트랩·층 최소 n은 바꾸지 않는다.**
- `evalset_candidates._FINAL_TARGETS`: `"questions_test_graph": TEST_GRAPH_QUESTIONS_COUNT`, `"questions_test_simple_search": TEST_SIMPLE_SEARCH_COUNT`(나머지 키 값 불변). 후보 목표·dev 몫 비율·`final_shortages`는 이 파생을 따른다. 시트 지침의 "질문 dev 10/test 관계 30·단순 검색 10"을 상수에서 만든 값("관계 27")으로 바꾼다(기존 문장 구조·해시 줄 불변). `DEV_TARGETS`·`_finalize_dev`·`finalize --split dev`·dev 확정 파일의 동작은 **불변이어야 한다**.

**3. 사전 등록(`eval/prereg.py`)**
- 6번째 문장의 "질문 40건"을 `evalset`의 `TEST_QUESTIONS_COUNT`(f-string)로 만든 "질문 37건"으로 바꾼다(나머지 문구 불변).
- `REQUIRED_SENTENCES` **끝에 21번째** 문장을 추가한다(기존 20개의 순서 불변): "EVAL.md 대비 변경: test 질문 40→37(관계 30→27, 단순 검색 10 유지). 사유: CQ-04 count 질문 10건은 정답이 항상 1(결과 행 수)이라 정보가 없어 제외했고, 닫힌 입력 조합을 모두 계산해도 유효한 관계 질문이 27건이다. 단순 검색 10건 비율은 유지하며 요청 20건·dev 구성은 불변이다. 질문 37건이 20건 이상이므로 판정 불가 하한은 해당하지 않는다." 숫자는 상수(`evalset.TEST_QUESTIONS_COUNT` 등)에서 만든다. `render_preregistration`의 번호 매김·인덱스 참조는 바꾸지 않는다.

**테스트(합성 데이터·`tmp_path`, 모델·접속 없음)**
- `tests/test_evalset.py`: (1) `synthetic_set()`이 test 질문 37건(단순 검색 10)이다. (2) **경계 테스트**: test 질문 36건은 `EVALSET_COUNT_INVALID`, 38건도 `EVALSET_COUNT_INVALID`, 37건은 통과한다(정답 집합 일치 유지, 단순 검색 10 고정; 38건은 그래프 질문 하나를 더해 만든다). (3) 상수 값(`TEST_QUESTIONS_COUNT == 37`·`TEST_SIMPLE_SEARCH_COUNT == 10`·`TEST_GRAPH_QUESTIONS_COUNT == 27`)이 고정이다. (4) 단순 검색 9건·11건(총 37)은 `EVALSET_COUNT_INVALID`다.
- `tests/test_evalset_candidates.py`: (5) 위 "상수 단언 grep"의 갱신(새 목표 27·후보 목표 41에서 다시 계산한 값, 가능하면 상수에서 읽음). (6) `_FINAL_TARGETS["questions_test_graph"] == TEST_GRAPH_QUESTIONS_COUNT`이고 `DEV_TARGETS == {"requests_dev": 10, "questions_dev": 10}`이다. (7) 전체 `finalize`가 test 관계 27·단순 검색 10·dev 10·요청 dev 10/test 20을 채운 시트에서 성공하고 한 건 모자라면 부족 건수를 출력한다(기존 finalize 테스트의 값 갱신). (8) 시트 지침에 "관계 27"이 있고 기존 문구·해시가 유지된다. (9) dev-split 테스트(`finalize --split dev` 계열)가 변경 없이 통과한다.
- `tests/test_e3_live.py`: (10) final 모드 `_questions`: 질문 36건·38건·단순 검색 9건은 `EVALSET_COUNT_INVALID`, 37건(단순 검색 10)은 통과한다. (11) 기존 final 합성 질문 수를 37로 갱신한 테스트(`overall.n == 37`)와 판정 불가 하한 테스트(20건 미만 `undecidable`)가 그대로 통과한다. (12) 관계형 부분집합 27건이 하한에 걸리지 않고(`decision`이 `undecidable`이 아님) 단순 검색 10건 부분집합은 `undecidable`이다.
- `tests/test_prereg.py`: (13) 문장 수 `== 21`과 21번째 문장 존재(`40→37`·`관계 30→27`·`CQ-04`·`정답이 항상 1`·`판정 불가 하한`·`단순 검색 10` 포함), 6번째 문장의 "질문 37건", 위 세 해시 기대값 한 줄씩 갱신.
- 합성 문장·분류 값을 기대값으로 굳히지 않는다(형식·건수·코드·경계만 검사).

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

- `docs/EVAL.md`를 수정하거나 판정 로직(`_summary`의 판정 불가 하한 20·`graph_adopted` 규칙)·`bootstrap_ci`·`MIN_STRATUM_N`·dev 확정 규칙(`DEV_TARGETS`·`finalize --split dev`)·요청 건수(dev 10·test 20)를 바꾸지 마라. 이유: 이 step은 test 질문 목표 수만 바꾸고 EVAL.md 대비 변경은 사전 등록 문장으로 기록한다.
- 질문 수 리터럴(37·27·10)을 소스의 여러 곳에 새로 흩뿌리지 마라(`evalset.py`의 세 상수가 유일한 원천이다). 이유: 한 곳을 바꾸면 검증·보고·후보 목표·사전 등록이 함께 바뀌어야 한다.
- `eval/freeze_guard.py`·`eval/isolation_live.py`·`eval/e2*.py`·`Makefile`을 수정하거나 새 의존성을 추가하지 마라. 이유: 허용 범위 밖이다(필요하면 `blocked`로 보고).
- 기존 테스트의 단언을 약화하지 마라(위 "상수 단언 grep"에 적힌 값 갱신과 해시 기대값 세 곳 한 줄씩 갱신만 허용, 경계 테스트는 추가). `REQUIRED_SENTENCES`의 6번째 문장 외 기존 문장을 고치지 마라. 이유: 이미 통과한 step의 계약이며 사전 등록 문장은 6번째의 숫자 외에는 바꾸지 않는다.
