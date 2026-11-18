# Step 6b: planning-evaluation

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`agents`는 `domain`·`graph`·`checks`·`llm`·`store`·`obs`), CRITICAL 규칙(판정은 `checks`가 코드로, LLM 채점은 차별성·요청 적합성에만, `reasoning_effort` 명시·원장 기록, `temperature` 금지)
- `/docs/PRD.md` — 핵심 기능 6(기획 에이전트)·7(평가 에이전트)
- `/docs/ARCHITECTURE.md` — "컨텍스트 관리"(핸드오프, 되돌림 시 전달), "그라운딩 원칙"
- `/docs/COMPETENCY_QUESTIONS.md` — CQ-10·11과 "한계와 조건"(연결 없음은 unknown)
- `/src/beautyads/domain/plan.py`, `/src/beautyads/domain/lookups.py`, `/src/beautyads/domain/research.py`, `/src/beautyads/domain/tenant.py`, `/src/beautyads/checks/plan_checks.py`, `/src/beautyads/llm/structured.py`, `/src/beautyads/llm/chat.py`, `/src/beautyads/agents/research.py`, `/src/beautyads/agents/tool_messages.py`, `/src/beautyads/graph/evidence_queries.py`, `/src/beautyads/graph/queries.py`(동결, 읽기 전용), `/tests/test_graph_evidence_queries.py`, `/tests/test_llm_param_guard.py`, `/tests/test_architecture.py` — step 0b·3·4·5·5a·5c 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/evaluation.py`(새 파일), `src/beautyads/agents/planning.py`(새 파일), `src/beautyads/agents/evaluation.py`(새 파일), `src/beautyads/agents/lookups.py`(새 파일), `src/beautyads/graph/evidence_queries.py`, `tests/test_domain_evaluation.py`(새 파일), `tests/test_planning.py`(새 파일), `tests/test_evaluation.py`(새 파일), `tests/test_lookups.py`(새 파일), `tests/test_graph_evidence_queries.py`, `tests/test_llm_param_guard.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/evaluation.py`, `src/beautyads/agents/planning.py`, `src/beautyads/agents/evaluation.py`, `src/beautyads/agents/lookups.py`, `src/beautyads/graph/evidence_queries.py`(질의 2개와 입력 검증 추가에 한함, 기존 질의·함수 불변), `tests/test_domain_evaluation.py`, `tests/test_planning.py`, `tests/test_evaluation.py`, `tests/test_lookups.py`, `tests/test_graph_evidence_queries.py`(케이스 추가에 한함, 단언 약화 금지), `tests/test_llm_param_guard.py`(기획·평가 호출 모양 조합 추가에 한함, 기존 조합과 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

기획 에이전트(terra)와 평가 에이전트(haiku 개발·sonnet 공식)를 만든다. 평가는 **코드 검사가 먼저**(`checks`)이고 LLM은 **차별성과 요청 적합성만** 채점한다. 이 step은 모델·네트워크를 부르지 않는다(가짜 `structured`·가짜 그래프만). **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

**`domain/evaluation.py`**(표준 라이브러리·pydantic만): `EvaluationScores`(`differentiation: int`(1~5), `fit: int`(1~5), `rationale: str`(최대 200자)), 상수 `PASS_MIN_SCORE = 3`(**잠정 개발값, 최종 평가(test 브랜드) 전 동결**: 값 옆 코드 주석에 "잠정값, 최종 평가 전 동결"을 적는다. test 결과를 보고 바꾸지 않고, 개발 중에 바꾸면 이유와 날짜를 `docs/PHASES.md` 변경 기록에 적는다. 5점 척도에서 두 항목이 모두 이 값 이상이어야 통과), 순수 함수 `low_items(scores) -> list[str]`(`PASS_MIN_SCORE` 미만인 항목 이름 목록 `differentiation`·`fit`), `EvaluationReport`(`check_report: dict`(`PlanCheckReport`를 `model_dump`한 것), `scores: dict | None`, `low_items: list[str]`, `scoring_failed: bool`, `passed: bool`(= 코드 검사 `passed`이고 점수가 있으며 낮은 항목이 없음), `unknown_count: int`, `unknown_codes: dict[str, int]`(코드 검사 결과에서 복사), `efficacy_status: dict[str, str]`(기획안이 주장한 효능 값 → `supported`·`unknown`, `passed`에 섞지 않는 별도 칸), `efficacy_summary: dict[str, int]`(`{"supported": n, "unknown": m}`), `disclaimer: str`(`CLAIM_CHECK_DISCLAIMER` 그대로)). `passed`는 `unknown`이 있어도 영향을 받지 않고 `unknown_count`가 별도 칸으로 남는다. 채점이 구조화 실패하면 `scores=None`, `scoring_failed=True`, `passed=False`다.

**`graph/evidence_queries.py`**(추가에 한함): (1) `existing_creatives_query()`: `$ids` 목록 중 그래프에 있는 소재 ID(`source + ':' + source_id`)를 돌려주는 고정 읽기 전용 Cypher. (2) `product_support_query()`: `$product_url`·`$claim`으로 그 제품의 `CONTAINS` 성분 수, 그 효능으로 `HAS_EFFICACY`가 이어진 성분 수, 제품이 `CERTIFIED_AS`로 이은 인증 종류 목록을 돌려주는 고정 읽기 전용 Cypher. 값은 `$` 파라미터이고 닫힌 값 검증 함수를 둔다. 동결 질의는 건드리지 않는다.

**`agents/lookups.py`**(`agents` 계층): `domain/lookups.py`의 `Protocol` 구현체 3개를 `GraphReader`로 만든다. `GraphEvidenceIndex.existing(ids)`(위 질의, 형식이 틀린 ID는 질의 전에 제외), `GraphEfficacySupport.efficacy_support(product_url, efficacy)`: 제품의 `CONTAINS` 성분이 없거나 제품이 그래프에 없으면 `unknown`, 그 효능으로 이어진 성분이 하나라도 있으면 `supported`, 그 밖에는 `unknown`(**`unsupported`를 돌려주지 않는다**: 성분→효능 표가 범위가 제한적이라 연결이 없다는 것이 근거가 없다는 뜻이 아니다. COMPETENCY_QUESTIONS 한계), `GraphCertLookup.cert_status(product_url, efficacy)`: 효능에 대응하는 인증 종류(`brightening`→`brightening`, `anti_aging`→`anti_aging`, `sun_protection`→`sun_protection`, 그 밖의 효능은 `unknown`)가 제품의 인증 목록에 있으면 `certified`, 그 밖에는 `unknown`(**`not_certified`를 돌려주지 않는다**: 식약처 보고 품목과 연결되지 않은 제품은 인증 없음이 아니다). 그래프 오류는 예외로 올리지 않고 `unknown`으로 내리되 호출한 쪽이 구분할 수 있게 `last_error` 코드 속성을 남긴다(`GRAPH_UNAVAILABLE`).

**`agents/planning.py`**: `PLANNING_REASONING_EFFORT = "low"`(모듈 상수, 6d의 사전 등록 비교 결과로 확정한다. 비교 전 기본값). `make_plan(*, brief: dict, handoff: dict, profile: dict, feedback: dict | None, rework: dict | None, structured, purpose: str = "plan", **call_options) -> PlanResult`(`PlanResult`: `ok`, `plan: dict | None`, `failure`, `cost_usd`). 모델은 `gpt-6.1-terra`, `reasoning_effort=PLANNING_REASONING_EFFORT`, `temperature` 없음, 구조화는 `make_structured("gpt-6.1-terra")`(OpenAI `JsonSchemaStructured`)이다. 한 호출에 **기획안 1안**. 스키마는 `domain.plan.Plan`의 JSON 스키마를 OpenAI strict 규칙(모든 속성 required, `additionalProperties: false`)으로 바꾼 것이다(변환 함수와 테스트를 둔다). **모델 입력은 JSON 데이터**: `{brief, research(handoff의 conclusion·evidence_ids·aggregates·result_counts·basis_notes·unresolved), profile(브랜드·톤·금지 표현·우리 제품), feedback(승인·반려 요약, 사유 원문 보존), rework}`, 시스템 지시는 역할 규칙과 `TOOL_DATA_RULE`·`PARTIAL_RESULT_RULE` 상수(`agents/tool_messages.py`)와 "근거 ID는 research.evidence_ids 안에서만 고른다"이다. 입력에 수집한 경쟁 소재의 이미지·URL 본문을 넣지 않는다(텍스트 핸드오프만). `rework`는 이전 기획안 전문이 아니라 `{check_issues: 실패한 검사 항목과 사유, low_items: 낮은 평가 항목과 점수·근거 짧은 문장}`뿐이다(6c가 채운다).

**`agents/evaluation.py`**: `evaluate_plan(*, plan: dict, brief: dict, handoff: dict, rules, evidence_index, support, certs, structured, model: str = "claude-haiku-5-5", purpose: str = "evaluate", **call_options) -> EvaluationReport`. (1) `checks.run_checks`(또는 dict 진입점)를 **먼저** 돌려 코드 판정을 만들고, 주장한 효능마다 `support.efficacy_support`로 효능별 상태(`efficacy_status`)를 채운다(`product_url`이 없으면 모두 `unknown`, 조회 구현체가 `unsupported`를 돌려주는 다른 구현이면 그 값을 그대로 둔다. 이 버전의 그래프 구현은 `supported`·`unknown`만 만든다)(`handoff_evidence_ids`는 핸드오프의 `evidence_ids`). (2) 점수 채점은 `make_structured(model)`(Anthropic 기본 (a) `tool_choice=auto` 단일 도구)로 `EvaluationScores`만 만든다. `reasoning_effort`는 Anthropic이라 `None`이고 `model`은 개발 기본 `claude-haiku-5-5`, 공식은 `claude-sonnet-5-5`를 호출부가 명시한다. **LLM은 코드가 판정한 것(근거 ID 존재, 분류 값, 금지 표현, 효능 근거)을 채점하지 않는다**: 프롬프트의 평가 항목은 차별성(경쟁 소재 요약과 비교한 새로움)과 요청 적합성(브리프 조건과의 일치) 둘뿐이다. 입력은 JSON 데이터(기획안 텍스트, 브리프, 핸드오프 요약, 평가 기준)이고 외부 텍스트는 데이터 필드로만 넣는다. 코드 검사가 실패해도 채점은 한다(6c의 되돌림에 낮은 항목을 함께 전달하기 위해서다). 채점이 구조화 실패하면 `scoring_failed`로 보고하고 예외를 던지지 않는다.

**FP-C13 가드(필수)**: `tests/test_llm_param_guard.py`에 기획 호출 모양(terra, `reasoning_effort` `low` 포함 네 값, `response_format` strict `json_schema`로 변환한 `Plan` 스키마)과 평가 호출 모양(haiku·sonnet, (a) 단일 도구 + `tool_choice="auto"`)을 실제 `litellm.get_optional_params`에 넣어 예외가 없음을 단언한다.

**반드시 있어야 하는 테스트**(가짜 `structured`·가짜 `GraphReader`·합성 값. 모델이 만든 문장·값을 기대값으로 굳히지 않는다):
- `domain/evaluation`: `PASS_MIN_SCORE` 경계(2와 3)와 값 옆 "잠정값, 최종 평가 전 동결" 주석 존재(소스 텍스트 확인), `efficacy_status`·`efficacy_summary`가 `passed`와 독립이고 `unknown`이 `passed`를 깨지 않음,, 점수 범위 밖 거부, `low_items`, `passed`가 코드 검사 실패·점수 없음·낮은 항목에서 거짓이고 `unknown`만 있을 때는 영향 없음, `unknown_count`·`unknown_codes` 복사, `disclaimer`가 `CLAIM_CHECK_DISCLAIMER`와 같다.
- lookups: 가짜 그래프 행으로 `existing`이 부분집합을 돌려주고 형식이 틀린 ID는 질의 인자에 없다. `efficacy_support`가 `supported`·`unknown`만 돌려주고 `unsupported`를 돌려주지 않는다. `cert_status`가 `certified`·`unknown`만 돌려주고 `not_certified`를 돌려주지 않는다. 그래프 오류에서 예외 없이 `unknown`과 `last_error`.
- 질의: 읽기 전용, 파라미터만 쓰고 입력이 문장에 끼지 않는다. 기존 질의·`QUESTIONS` 본문 불변.
- 기획: **가짜 `structured`가 받은 `messages` 호출 인자를 직접 검사**한다: 모델이 `gpt-6.1-terra`, `reasoning_effort`가 상수 값, `temperature` 없음, 사용자 메시지(JSON)에 `research.evidence_ids`·`result_counts`·`profile`·`feedback`이 들어 있고, `rework`가 있으면 `check_issues`·`low_items`만 있고 이전 기획안 전문(합성 식별 문자열)이 없다. 시스템 메시지에 두 지시 상수가 있다. 입력에 URL·이미지 필드가 없다. 구조화 실패는 `ok=False`로 돌려주고 예외가 없다. `Plan` 스키마 변환 결과가 strict 규칙(모든 속성 required, `additionalProperties` false)을 만족한다.
- 평가: 코드 검사가 `structured`보다 먼저 돌고(호출 순서 기록), 코드 검사가 실패해도 채점 호출이 일어난다. 채점 입력(`messages`)에 코드 판정 항목(금지 표현 목록·근거 ID 존재 여부)이 평가 항목으로 들어 있지 않고 차별성·요청 적합성 두 항목만 있다. 모델이 `haiku`·`sonnet`으로 명시되고 `reasoning_effort`가 `None`이다. `efficacy_status`가 가짜 조회의 `supported`·`unknown`을 효능별로 담고(`product_url` 없음은 전부 `unknown`) `efficacy_summary` 합이 주장한 효능 수와 같다. 채점 실패는 `scoring_failed=True`·`passed=False`이고 예외가 없다.
- `tests/test_architecture.py`가 통과한다.

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

- 코드가 판정할 수 있는 것(근거 ID 존재, 분류 값, 금지 표현, 효능 근거)을 LLM 채점에 맡기지 마라. 이유: 판정할 수 있는 것은 `checks/`가 코드로 판정한다(AGENTS.md CRITICAL).
- `unsupported`·`not_certified`를 그래프 조회 구현체가 돌려주게 하지 마라. 이유: 성분→효능 표와 인증 연결은 범위가 제한적이라 연결이 없다는 것이 근거 없음·인증 없음이 아니다(COMPETENCY_QUESTIONS 한계, 설계 원칙 14). `unknown`으로 내린다.
- 기획 입력에 수집한 경쟁 소재의 이미지·URL을 넣거나 이전 기획안 전문을 되돌림 입력에 넣지 마라. 이유: 입력은 텍스트 핸드오프이고 되돌림에는 검사 실패 항목과 낮은 평가 항목만 전달한다(ARCHITECTURE 컨텍스트 관리).
- 기획 모델의 `reasoning_effort`를 생략하거나 haiku·sonnet에 `reasoning_effort`·`thinking`·`temperature`를 보내지 마라. 이유: luna·terra는 비용이 달라지므로 명시하고 원장에 기록하며, Anthropic 경로는 효과가 확인되지 않아 보내지 않는다(P5 결정, step 0 규칙).
- 가짜 `structured`의 반환값만 단언하지 말고 받은 `messages` 인자를 직접 검사하라. 이유: 모델이 읽어야 할 정보가 입력에 실제로 들어가는지 확인한다(FP-C14).
- `PASS_MIN_SCORE`나 점수 범위를 호출부 인자로 바꾸지 마라. 이유: 통과 기준은 한 곳에서 정하고 6d의 비교와 보고가 같은 값을 쓴다(B-FP-044).
