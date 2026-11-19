# Step 12: candidate-validity

## 설계 검토 기록

**배경(조언 세션 승인)**: 후보 생성기(step 3)는 정답을 계산해 놓고도 비어 있는 정답을 거르지 않고 앞에서부터 15/45건을 채택해, 생성된 시트의 관계 질문 정답이 dev 15건 중 8건·test 45건 중 27건 비어 있다(count 0·빈 집합). 이대로는 `finalize`가 부족으로 멈춘다. 또 요청 문장 템플릿에 "기타 포맷 포맷을", "문제 해결 각도을" 같은 중복·조사 오류가 있다(요청 45건 중 13건). 이 step은 (1) 빈 정답과 크기 50 초과 정답 질문을 후보에서 제외하고, (2) 유효 후보를 CQ별 비례로 dev:test = 10:30에 고정 시드로 배정하고, (3) 요청 문장 오류를 고치고, (4) 사전 등록에 들어갈 한계 문장을 추가한다. **EVAL.md의 수치(요청 20·질문 30+단순 검색 10)와 `_FINAL_TARGETS`는 바꾸지 않는다.** 관계 질문이 부족하면 dev만 단순 검색으로 채우고 부족 건수를 보고만 한다(구성 조정은 사용자 결정).

**식별자 전수 대조(현재 코드)**: `eval/evalset_candidates.py`(`CANDIDATE_FACTOR`·`CANDIDATE_DIR`·`WORKSPACE_CATEGORY`·`REVIEW_COLUMNS`·`_LABELS`·`_INPUTS`·`_REQUEST_AXES`·`_CQ_AXES`·`_QUESTION_TEXT`·`_FINAL_TARGETS`·`Candidates`(dataclass: `requests`·`questions`·`answers`·`shortages`·`errors`·`query_count`)·`ReviewedSet`·`_shortages(requests, questions, targets)`·`_eligible`·`_workspaces`·`_round_robin(groups, rng)`·`build_request_candidates(cq_rows, workspaces, *, briefs=None)`(요청 값 `enums = {"format": Format, "hook_type": HookType, "angle": Angle}`, 조건 문구 f-string)·`_CountingGraph`·`_failure_code`·`build_question_candidates(cq_rows, workspaces, *, graph=None, as_of)`(조합 `product(...)`, `groups = {"graph": {}, "simple_search": {}}`, 시드 `random.Random(20261119)`, `compute_answer(graph, question, *, as_of)`)·`write_review_sheet`·`main`(생성 출력 JSON `{"requests","questions","shortages","errors"}`과 `질의 N건` 줄)), `eval/evalset.py`(`QuestionItem`·`AnswerItem`·`RequestItem`·`validate_set`), `eval/prereg.py`(`REQUIRED_SENTENCES` 튜플 14개, 번호는 `enumerate(..., 1)`로 매겨지며 코드가 `[1]`·`[6]`·`[7]` 인덱스를 직접 참조한다 → **끝에 추가만 하고 기존 항목 순서·문장을 바꾸지 않는다**), `eval/e3_live.py:score_answer`(읽기 전용: `set`은 정규화한 집합의 **완전 일치**, 부분 점수 없음, `count`는 `tolerance_abs` 허용).

**상수 단언 grep**: `tests/test_evalset_candidates.py`의 다음 기존 단언은 새 규칙에서 값이 달라지는 것만 갱신하고(이유를 테스트 이름·주석 아닌 단언 값으로 반영) 나머지는 약화하지 않는다.
- `test_questions_counts_round_robin_and_disjoint_combinations`: `{"dev": 15, "test": 60}`·test 단순 검색 15는 합성 풀(CQ-01 33 + CQ-04 33 = 66 ≥ 60)에서 그대로 성립해야 한다. CQ별 개수 차이 `<= 1` 단언은 "CQ별 비례 배정(합성 풀에서 dev 15·test 45가 CQ-01·CQ-04에 각각 최대 1 차이)"으로 유지한다. `len(graph.calls) == result.query_count == len(result.questions)`는 새 규칙에서 **계산한 항목 수가 후보 수 이상**이므로 `result.query_count == len(graph.calls)`와 `len(graph.calls) >= len(result.questions)`로 바꾼다.
- `test_missing_pool_reports_shortages_without_duplicates`: 합성 풀 1건(`CQ-01`, 입력 없음)은 비례 규칙(`dev 몫 = 반올림(유효 수 × 10/40)`)으로 test 관계 질문에 배정되어 `len(questions) == 1`이고 부족 건수는 `questions_dev` 15·`questions_test_graph` 44·`questions_test_simple_search` 15가 된다(값 갱신, 중복 없음 단언은 유지).
- `test_failed_candidates_are_excluded_and_counted`: 모든 질의 실패 시 후보 없음·오류 코드 집계·`questions_dev == 15`는 그대로다.
- `test_request_counts_strata_split_and_determinism`(요청 dev 15·test 30, 층 reliable/unreliable 10:5·20:10): `other` 값 제외 뒤에도 풀이 충분해야 하며 단언은 그대로다.
- `tests/test_prereg.py:39`의 `== 14`: 문장이 15개가 되므로 `== 15`로 갱신하고 새 문장 존재 단언을 추가한다(다른 기존 단언은 그대로).
- `test_sheet_columns_instructions_and_hash_guard`(지침에 "칸의 뜻"·"기준"·"예시"·"기록 방법"과 두 해시): 기존 문구는 그대로 두고 지침에 **절만 추가**한다.

**새 칸 대응표**: `MAX_ANSWER_SET = 50`(생성기 → 사전 등록 문장 15번이 이 상수 값을 f-string으로 싣는다, 리터럴 50을 프롬프트·문서에 따로 적지 않는다), `Candidates.excluded`(`{"empty": n, "oversize": n}`)·`valid_pool`(CQ별 유효 수)·`answer_sizes`(CQ별 `{"le10": n, "gt10": n, "count": n}`)·`composition`(split별 CQ별 후보 수)·`final_shortages`(`_FINAL_TARGETS` 기준 부족)(생성기 → `main`의 출력 JSON → 사용자 확인·조언 세션 보고), 질문 id(`q-{split}-{번호}`)와 정답의 `question_id`(할당 **뒤에** 부여하므로 둘이 같은 id여야 한다 → `validate_set`의 정답 집합 일치).

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건. 이 step은 합성 테스트만 한다. 사용자가 DB를 켠 뒤 `make live-evalset`으로 재생성하면 읽기 전용 그래프 질의가 관계 질문 약 110건(전체 조합)과 단순 검색 필요한 만큼 나간다(비용 0).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 실제 호출은 사용자가 실행한다, 동결된 기준은 결과를 본 뒤 바꾸지 않는다, 모델이 만든 값을 테스트 기대값으로 굳히지 않는다
- `/src/beautyads/eval/evalset_candidates.py`(전체), `/src/beautyads/eval/evalset.py`, `/src/beautyads/eval/prereg.py`(`REQUIRED_SENTENCES`·`render_preregistration`), `/src/beautyads/eval/e3_live.py`(읽기 전용: `score_answer`·`report`, 수정하지 않는다)
- `/tests/test_evalset_candidates.py`(전체: `synthetic` 픽스처·`FakeGraph`·`combined`), `/tests/test_prereg.py`
- `/docs/COMPETENCY_QUESTIONS.md`(읽기 전용: CQ별 현재 상태표 — CQ-08·13·14는 데이터 부재로 항상 빈 정답이고 CQ-02 등 나머지는 입력 조합에 따라 일부만 빈 정답이다), `/docs/EVAL.md`(읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/evalset_candidates.py`, `tests/test_evalset_candidates.py`, `src/beautyads/eval/prereg.py`, `tests/test_prereg.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/evalset_candidates.py`, `tests/test_evalset_candidates.py`, `src/beautyads/eval/prereg.py`, `tests/test_prereg.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

후보 생성기가 빈 정답·과대 정답 질문을 후보에서 제외하고 유효 후보를 CQ별 비례로 배정하게 하며, 요청 문장 오류를 고치고 사전 등록 한계 문장을 추가한다. **모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: `MAX_ANSWER_SET`, `_apportion`, `_object_particle`

**1. 질문 후보: 제외·배정(`build_question_candidates`)**
- `MAX_ANSWER_SET = 50`. 정답 크기는 `set`이면 `len(value)`, `count`이면 값 자체가 아니라 "결과 행 수"이므로 크기 상한은 `set`에만 적용하고 `count`는 값이 0일 때만 빈 정답이다.
- **전체 계산 후 필터**: 관계 질문(`kind == "graph"`)은 닫힌 입력 조합 **전체**를 계산한다(시드 셔플은 CQ id 오름차순으로 한 번씩, 기존 시드 20261119를 그대로 쓴다. 새 시드 상수를 만들지 않는다). 각 조합은 임시 `QuestionItem`(임시 id)으로 `compute_answer`를 부르고 결과를 분류한다: 질의 실패 → 기존 `errors`(고정 코드) 집계, **빈 정답** → `excluded["empty"]`, **크기 초과** → `excluded["oversize"]`, 그 밖 → 유효. 같은 CQ에서 정답이 같은 유효 후보는 **제외하지 않고** 개수만 `excluded["duplicate_answers"]`로 센다(보고용).
- **관계 질문 배정**: 유효 수가 총 60(= dev 15 + test 45, `CANDIDATE_FACTOR`로 계산한 기존 목표)을 넘으면 `_apportion`으로 CQ별 비례로 60건으로 줄인다. 그 다음 dev 몫 `= min(15, 반올림(유효 수 × dev/(dev+test)))`이며 비율은 `_FINAL_TARGETS`의 `questions_dev`:`questions_test_graph`(10:30)에서 **같은 출처로** 만든다(숫자 10·30을 다시 적지 않는다). dev 몫을 CQ별로 `_apportion`하고 나머지는 test다. dev와 test의 CQ 구성이 비슷해야 하므로 `test 먼저` 같은 순서 배정은 하지 않는다.
- `_apportion(weights: dict[str, int], total: int) -> dict[str, int]`: 가중치에 비례하는 최대 잔여법(largest remainder), 각 키 몫은 그 가중치를 넘지 않고, 소수부가 같으면 키 오름차순, 합은 `min(total, sum(weights))`다(결정적, 시드 불필요).
- **단순 검색(`kind == "simple_search"`)**: 기존 `_round_robin` 순서로 **필요한 만큼만** 게으르게 계산한다. 유효 후보를 먼저 test 단순 검색 15건(`targets["questions_test_simple_search"]`)에 배정하고, 그 다음 유효 후보를 dev 부족분(dev 목표 15 − dev 관계 질문 수)에 배정한다. 풀이 소진되면 있는 만큼만 배정하고 부족을 보고한다. **관계 질문 수를 줄이는 구성 조정이나 test를 단순 검색으로 채우는 일은 하지 않는다.**
- **id와 정답**: 할당이 끝난 뒤에 `q-{split}-{번호:04d}`를 split별 연속 번호로 매기고, 정답(`AnswerItem`)의 `question_id`도 같은 id로 다시 만든다(`validate_set`의 정답 집합 일치). 같은 조합이 dev와 test에 함께 들어가지 않는다. `tenant_id`는 기존처럼 split의 작업 공간을 순환한다.
- `graph=None`(오프라인 추정·`--dry-run`)은 모든 조합을 유효로 취급하는 같은 배정 코드를 탄다(정답이 없으므로 제외하지 않는다, 질의 수는 후보 수).
- `Candidates`에 칸 추가: `excluded: dict[str, int]`, `valid_pool: dict[str, int]`(CQ별 유효 수), `answer_sizes: dict[str, dict[str, int]]`(CQ별 `{"le10","gt10","count"}`: `set`의 크기 10 이하·초과, `count` 건수), `composition: dict[str, dict[str, int]]`(split별 CQ별 후보 수), `final_shortages: dict[str, int]`(`_FINAL_TARGETS` 기준: `questions_dev`는 dev 후보 수(종류 무관), `questions_test_graph`·`questions_test_simple_search`는 해당 종류의 후보 수). 기존 `shortages`(후보 목표 1.5배 기준)는 그대로 둔다. 새 칸은 모두 기본값이 있어 기존 `Candidates(...)` 생성이 깨지지 않는다.
- `main`의 생성 출력 JSON에 위 새 칸을 싣는다(건수만, 문장·정답 값 없음). `질의 N건` 줄은 그대로다.
- 시트 지침(`review_instructions.md`)에 한 절을 추가한다: 정답이 비었거나 크기 50(`MAX_ANSWER_SET`) 초과인 질문은 후보에서 이미 제외했다는 것, CQ-08·13·14는 데이터 부재로 항상 빈 정답이라 후보가 없다는 것, 후보가 부족하면 `final_shortages`를 확인하라는 것. 기존 문장·해시 줄은 그대로 둔다.

**2. 요청 문장 오류(`build_request_candidates`)**
- 요청 값에서 `other`를 제외한다(`enums` 값 순회에서 `value == "other"`를 건너뛴다). `other`를 지정하는 요청은 의미가 없고 표시 이름에 접미사("기타 포맷")가 이미 들어 "기타 포맷 포맷을"이 된다.
- 조건 문구의 목적격 조사를 마지막 글자의 받침으로 고른다: 헬퍼 `_object_particle(word) -> "을" | "를"`(한글 음절의 종성 유무, 한글이 아니면 `을`). 문구는 `"{라벨} {명사}{조사} 지정해"`이며 명사는 포맷 `포맷`, 훅 `훅 유형`, 각도 `각도`다(결과: "…포맷을", "…훅 유형을", "…각도를"). 라벨이 이미 그 명사로 끝나면 명사를 반복하지 않는 방어 조건도 둔다.
- 기존 템플릿의 나머지("역량 질문 {CQ}의 근거를 바탕으로 … 기획안 1안으로 작성해 주세요.")는 그대로다. `signature` 중복 제거와 `axes_used`는 불변이다.

**3. 사전 등록 한계 문장(`eval/prereg.py`)**
- `REQUIRED_SENTENCES` **끝에 15번째** 문장을 추가한다(기존 14개의 순서·문장 불변). 내용: (a) E3 관계 질문 후보는 정답이 비었거나 크기가 `MAX_ANSWER_SET`(f-string으로 `evalset_candidates.MAX_ANSWER_SET`의 값을 싣는다)을 넘는 질문을 제외했다, (b) CQ-08·13·14는 데이터 부재로 항상 빈 정답이라 제외된다, (c) 관계 질문은 소수 CQ 유형의 닫힌 입력 조합에서 만든 것이라 **질문 간 독립이 아니며 결과는 이 템플릿 범위에 한정**한다. **정답 집합 크기 10 이하 대 초과 층화 보고는 이 step에서 문장으로 약속하지 않는다**(보고 코드가 `eval/e3_live.py`에 있고 이 step의 허용 범위 밖이다 → 구현 뒤 별도 step에서 문장을 추가한다).
- `render_preregistration`의 번호 매김·인덱스 참조(`[1]`·`[6]`·`[7]`)는 바꾸지 않는다.

**테스트(합성 데이터·`tmp_path`, 모델·접속 없음)**
- `tests/test_evalset_candidates.py`: (1) 빈 정답(`FakeGraph(rows=[])` 계열)과 크기 초과 정답(`MAX_ANSWER_SET + 1`개 행)이 후보·정답에서 제외되고 `excluded`가 건수를 센다. (2) 유효·무효가 섞인 합성 그래프(입력 값에 따라 행 수가 달라지는 가짜)로 dev·test가 CQ별로 비례 배정된다(CQ 구성 비율이 dev:test = 1:3에서 CQ별 1 이내 오차, 시드 고정으로 같은 입력에서 같은 결과, dev와 test의 조합이 겹치지 않음). (3) `_apportion`: 합 보존·가중치 상한·동률은 키 오름차순·결정적. (4) 관계 질문이 부족하면 dev만 단순 검색으로 채워지고 `final_shortages`가 실제 부족을 보이며 test 관계 질문은 단순 검색으로 채워지지 않는다. (5) `answer_sizes`의 `le10`·`gt10`·`count`와 `valid_pool`·`composition`이 합성 값에서 손으로 센 값과 같다. (6) 질문 id가 split별 연속이고 정답 `question_id`와 일치하며 `validate_set(final=False)`를 통과한다. (7) `graph=None`이 같은 배정 코드를 타고 질의하지 않는다. (8) 요청: `other` 값이 없고, 메시지에 "포맷 포맷"·"훅 훅"·"각도 각도"·"각도을"이 없으며 "포맷을"·"훅 유형을"·"각도를" 조사가 맞다(`_object_particle`의 받침 있음·없음·한글 아님 사례). (9) 지침에 새 절과 기존 문구·해시가 모두 있다. (10) 기존 테스트 중 위 "상수 단언 grep"의 갱신 대상만 갱신한다.
- `tests/test_prereg.py`: `== 15`와 새 문장 존재(상수 이름 `MAX_ANSWER_SET`의 값·"CQ-08"·"독립"이 들어 있음), 출력에 15개 문장이 모두 있음, 값은 `MAX_ANSWER_SET`에서 읽는다(리터럴 50 금지).
- 합성 문장·분류 값·모델 출력을 기대값으로 굳히지 않는다(형식·건수·코드·구성 비율만 검사).

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

- `docs/EVAL.md`의 수치(요청 20·질문 30+단순 검색 10)나 `_FINAL_TARGETS`·`REVIEW_COLUMNS`의 값을 바꾸거나, 관계 질문이 부족할 때 test를 단순 검색으로 채우거나 test 관계 질문 수를 줄이지 마라. 이유: 구성 조정은 동결 기준 변경이라 사용자 결정 사항이다. 부족은 `final_shortages`로 보고만 한다.
- `eval/e3_live.py`·`eval/evalset.py`·`graph/queries.py`·`Makefile`·`tests/test_e3_live.py`를 수정하거나 질의를 새로 만들지 마라. 이유: 고정 질의는 동결되었고 E3 보고 코드는 이 step의 허용 범위 밖이다(필요하면 `blocked`로 보고).
- 정답이 비었는지·크기가 큰지 판정하려고 모델을 부르거나 정답 값을 출력·로그·예외 메시지에 싣지 마라. 이유: 판정은 코드가 하고 출력은 건수만이다(AGENTS.md).
- 기존 테스트의 단언을 약화하지 마라(위 "상수 단언 grep"에 적힌 값 갱신만 허용). 이유: 이미 통과한 step의 계약이다.
- 정답 집합 크기 10 이하 대 초과 층화 보고를 사전 등록 문장으로 약속하지 마라. 이유: 이를 지키는 보고 코드가 이 step에 없다.
- 합성 문장·모델이 만든 분류 값을 테스트 기대값으로 굳히지 마라. 이유: 테스트는 형식과 코드가 하는 일을 검사한다(AGENTS.md CRITICAL).
