# Step 3: evalset-candidates

## 설계 검토 기록

**식별자 전수 대조(bb0e64f)**: `graph/queries.py`의 `QUESTIONS`(`Question.cypher`·`parameters`·`hops`·`inputs`)와 `question_parameters(spec, *, as_of, inputs, context)`(닫힌 값만 입력, 위반 시 `ValueError("CQ_INPUT_INVALID")`), `eval/cq_verify.py`의 `cq_preflight`·`error_code`, `eval/p5_compare.py`의 `BRIEFS`(카테고리·효능 5쌍)와 `PROFILES`, `eval/agents_live.py`(`as_of` 결정과 `assemble_full` 호출 방식, 읽기 전용), `sources/workspaces.py`의 `load_workspaces`, `graph/values.py`의 `to_json_safe`, `graph/connection.py`의 연결 팩토리(`.run(cypher, params).records`는 `api/assembly.py`에서 쓰는 방식), `domain/labels.py`의 `Category`·`Claim`·`Format`·`HookType`·`Angle`, `eval/evalset.py`(step 2 산출물).

**상수 단언 grep**: 이 step이 새로 만드는 상수(후보 배수 1.5, 후보 수)는 기존 테스트가 단언하지 않는다. `QUESTIONS`의 키 집합을 단언하는 기존 테스트가 있으면 이 step은 읽기만 한다. `tests/`에서 `QUESTIONS`·`question_parameters`를 정확 일치로 단언하는 곳은 수정하지 않는다.

**새 칸 대응표**: `needs_human_review`·`reviewed`·`axes_used`(후보 생성기 → 사용자 시트 편집 → step 2 검증기), 정답 `value`·`evidence_ids`(그래프 고정 질의 결과를 코드가 계산 → 사용자가 시트에서 확인 → 확정본), 사람 시트 열(`decision`·`edited_text`·`answer_confirmed`)(이 step의 시트 생성기 → 같은 step의 `apply_review`).

**비용(호출 수 기준)**: 모델 호출 0건. 그래프 읽기 전용 질의만 한다(약 수십 건, 비용 0). 사용자 실행은 `make live-evalset`.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 에이전트에게 Cypher를 쓰게 하지 않는다(이 step은 기존 고정 질의만 쓴다), 실제 호출은 사용자가 실행한다
- `/docs/COMPETENCY_QUESTIONS.md`(CQ 표: ID·질문·쓰는 층·쓰이는 곳. CQ-07은 없다), `/docs/EVAL.md`(요청 20·질문 30+단순 검색 10 기준과 dev 분할), `/docs/results/2026-11-19-e1-scoring.md`(충족·미충족 축)
- `/src/beautyads/eval/evalset.py`·`/src/beautyads/eval/freeze_guard.py`(step 2 산출물), `/src/beautyads/graph/queries.py`·`/src/beautyads/graph/values.py`·`/src/beautyads/graph/connection.py`
- `/src/beautyads/eval/cq_verify.py`(`cq_preflight`·`error_code`, 읽기 전용), `/src/beautyads/eval/p5_compare.py`(`BRIEFS`, 읽기 전용), `/src/beautyads/eval/agents_live.py`(`as_of`·`assemble_full` 사용 방식, 읽기 전용), `/src/beautyads/sources/workspaces.py`, `/config/workspaces.yaml`
- `/Makefile`(live 타깃 형식: `live-compare`·`live-evidence`), `/src/beautyads/eval/sheets.py`(사람 시트 CSV·설명 문서 생성 선례, 읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/evalset_candidates.py`(새 파일), `tests/test_evalset_candidates.py`(새 파일), `Makefile`(`live-evalset` 타깃 한 개 추가에 한함)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/evalset_candidates.py`, `tests/test_evalset_candidates.py`, `Makefile`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로, 평가 정답을 읽는 채점 함수)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

평가셋 **후보 생성기**와 사람 검수 시트를 만든다. 요청 30건(dev 10 + test 20)·질문 50건(dev 10 + test 40, test 중 단순 검색 10 포함)의 약 1.5배 후보를 `docs/COMPETENCY_QUESTIONS.md`의 CQ와 고정 질의에서만 만든다. **이 코드는 모델을 부르지 않는다**(문장은 결정적 템플릿). **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: `CANDIDATE_FACTOR`, `CANDIDATE_DIR`, `parse_cq_table`, `build_request_candidates`, `build_question_candidates`, `compute_answer`, `write_review_sheet`, `apply_review`, `REVIEW_COLUMNS`, `WORKSPACE_CATEGORY`

**후보 수와 출력(모두 `CANDIDATE_DIR = Path("data/interim/evalset")` 아래, 커밋하지 않음)**
- 요청: dev `ceil(10×1.5)=15`, test `ceil(20×1.5)=30`. 질문: dev 15, test 60(그중 단순 검색 15). `CANDIDATE_FACTOR = 1.5`. 후보가 모자라면 만든 만큼만 쓰고(지어내서 채우지 않는다) 부족 건수를 출력·반환한다.
- 파일: `requests_candidates.jsonl`·`questions_candidates.jsonl`·`answers_candidates.jsonl`(step 2의 항목 모델과 같은 필드, `needs_human_review=true`·`reviewed=false`·정답 `confirmed=false`), 사람 시트 `review_sheet.csv`와 설명 `review_instructions.md`.

**CQ 읽기**: `parse_cq_table(text) -> list[dict]`는 문서 표 행(`| CQ-NN | 질문 | 쓰는 층 | 경로 | 쓰이는 곳 |`)을 읽는다. 번호는 문서에서 읽고 코드에 1~16을 적지 않는다.

**요청 후보(`build_request_candidates`)**: 쓰이는 곳에 `기획` 또는 `리서치`가 있는 CQ와 `eval/p5_compare.BRIEFS`의 (카테고리, 효능) 쌍, 작업 공간(`load_workspaces`)에서 만든다. 요청 문장은 `plan_count`가 1이 되도록 "기획안 1안" 표현을 포함하는 한국어 템플릿(4종: 기본, 포맷 지정, 훅 유형 지정, 각도 지정)이며 닫힌 값은 코드 안 한글 표기 사전으로 옮긴다(사전에 없는 값은 후보에서 제외). 작업 공간별 카테고리는 상수 `WORKSPACE_CATEGORY`(`dev-mixsoon`→`serum_ampoule`, `dev-cosrx`→`sun_care`, `test-isntree`→`serum_ampoule`, `test-bojoseon`→`sun_care`)로 두고, 테스트가 키 집합이 `load_workspaces` 결과의 dev·test 작업 공간과 같고 값이 `Category` 안임을 단언한다(값의 사실 확인은 사람 시트가 한다). dev 요청은 `dev-*`, test 요청은 `test-*`만 쓴다. `axes_used`는 템플릿이 정한다(기본 `["category"]`, 포맷 지정 `["category","format"]`, 훅 지정 `["hook_type"]`, 각도 지정 `["angle"]`). **충족 축만 쓰는 후보를 우선**하되 각 split에 `reliable` 약 2/3, `unreliable` 약 1/3이 되게 하고, 항목은 버리지 않는다(층화 보조 분석용).

**질문 후보(`build_question_candidates`)**: `QUESTIONS` 중 `"context" not in spec.parameters`인 CQ(작업 공간 컨텍스트가 필요 없는 것)만 쓴다. 입력 조합(`spec.inputs`의 닫힌 값 곱)마다 질문 하나를 만든다. `spec.hops <= 1`이면 `kind="simple_search"`, 아니면 `"graph"`다. 질문 문장은 템플릿+한글 표기 사전이고 `cq_inputs`에 입력 값을 그대로 둔다. `axes_used`는 CQ가 읽는 축(예: 훅·앵글·포맷·효능)으로 코드 표에 고정하고 그래프 구조만 쓰는 CQ는 `["graph_structure"]`다(모델·사람이 정하지 않는다). 후보 선택은 CQ별로 고르게(라운드로빈) 하고 시드를 고정한다(`random.Random(20261119)`).

**정답 계산(`compute_answer(graph, question, *, as_of)`)**: `QUESTIONS[question.source_cq]`와 `question_parameters(spec, as_of=as_of, inputs=question.cq_inputs)`로 고정 Cypher를 `graph.run(...)`으로 읽는다(새 Cypher 금지, `question_parameters`가 `CQ_INPUT_INVALID`를 올리면 그 후보를 제외하고 건수를 센다). 행은 `to_json_safe`를 거친다. `answer_type="count"`면 행 수, `"set"`이면 각 행의 첫 문자열 열(질의가 돌려주는 대표 키, 정렬·중복 제거)의 목록이며, 정답을 만든 소재 ID가 행에 있으면 `evidence_ids`에 싣는다. 질의가 실패하면 그 후보를 만들지 않고 `error_code`로 센다.

**사람 시트와 `apply_review`**: `REVIEW_COLUMNS = ("item_id","kind","split","text","source_cq","axes_used","answer_summary","decision","edited_text","answer_confirmed","note")`. 설명 문서(`review_instructions.md`)는 **칸의 뜻, 칸별 기준, 예시 1개, 기록 방법**을 담는다: `decision`은 `O`(그대로 채택)·`X`(제외)·`수정`(`edited_text`에 고친 문장), `answer_confirmed`는 `Y`·`N`(정답을 그래프 질의 요약 `answer_summary`와 대조해 맞으면 Y), 모호하면 `N`과 `note`에 사유, 빈 칸 금지. `apply_review(candidates, sheet_rows) -> (requests, questions, answers)`는 `O`·`수정`만 채택하고 `수정`은 `edited_text`로 `text`·`message`를 바꾼다(`axes_used`·정답·`source_cq`는 바뀌지 않는다). 채택 항목은 `reviewed=true`, 정답은 `answer_confirmed=="Y"`일 때만 `confirmed=true`(아니면 그 질문을 채택하지 않는다). 결과가 모자라면 부족 건수를 돌려주고 `final=True` 검증은 호출하지 않는다(확정은 사용자가 시트를 채운 뒤 별도 실행에서 `--finalize`로 `data/evalset/`에 쓰고 그때 `validate_set(final=True)`를 거친다).

**CLI**: `python -m beautyads.eval.evalset_candidates [generate|finalize] [--dry-run]`. `generate`는 점검(`cq_preflight`) 뒤 그래프를 읽어 후보·시트를 쓴다. `--dry-run`은 접속 없이 후보 수와 부족 건수와 "모델 호출 0건, 그래프 읽기 전용 질의 N건(가정, 미실측)"만 출력한다. `Makefile`에 `live-evalset` 타깃(`uv run python -m beautyads.eval.evalset_candidates $(ARGS)`)을 추가한다.

**테스트(합성 환경)**: 합성 CQ 표 문장·합성 `QUESTIONS` 대체 객체·가짜 `graph.run`(`records` 반환)으로: 후보 수가 `ceil(필요×1.5)`이고 부족 시 부족 건수를 센다, dev 요청은 dev 작업 공간만·test는 test만, `reliable`/`unreliable` 비율, `axes_used`가 모두 `AXIS_NAMES` 안, `context` 매개변수가 있는 CQ가 제외됨, `spec.hops` 기준 `kind` 분류, 같은 시드에서 같은 출력, `CQ_INPUT_INVALID`·질의 실패 후보 제외와 집계, `compute_answer`가 `count`·`set`을 만들고 모델을 호출하지 않음(모델 SDK import 없음을 AST로 단언), 정답 계산이 `QUESTIONS`의 `cypher`와 `question_parameters`만 쓰며 새 Cypher 문자열이 모듈에 없음, `apply_review`가 `X`·`N`을 제외하고 `수정`에서 `axes_used`를 바꾸지 않음, 시트 열이 `REVIEW_COLUMNS`와 같고 설명 문서에 네 항목(칸의 뜻·기준·예시·기록 방법)이 있음, `finalize`가 해시·검증 오류를 고정 코드로만 냄. 합성 문장을 기대값으로 굳히지 않고 형식(필드·닫힌 값·건수)만 단언한다.

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

- 이 코드에서 모델을 호출하거나 `llm`을 import하지 마라. 이유: 후보 문장은 결정적 템플릿이고 정답은 그래프 고정 질의 결과다. 모델이 만든 문장을 정답이나 기대값에 굳히면 안 된다(FP-C03, AGENTS.md CRITICAL).
- `QUESTIONS`·`question_parameters`·`graph/queries.py`를 고치거나 새 Cypher 문자열을 만들지 마라. 이유: CQ v1은 동결이고 새 질의는 승인된 예외만 허용된다(P5 9h 선례, AGENTS.md).
- `axes_used`·정답·`source_cq`를 사람 시트의 `수정`으로 바뀌게 하지 마라. 이유: 층화 보조 분석 기준은 코드가 정하고 세트 해시로 동결된다. 문항을 빼거나 축을 옮기면 결과를 본 뒤 세트를 바꾸는 것이다(docs/EVAL.md 원칙).
- tenant 전용 CQ(`context` 매개변수가 있는 질의)나 `docs/COMPETENCY_QUESTIONS.md`에 없는 질문으로 후보를 채우지 마라. 이유: 후보는 CQ에서만 만든다(조언 세션 결정). 모자라면 부족 건수를 보고한다.
- `data/evalset/`에 이 step의 테스트가 파일을 쓰게 하지 마라. 이유: 확정본은 사용자가 시트를 채운 뒤 `finalize`로만 만든다. 테스트는 `tmp_path`만 쓴다.
