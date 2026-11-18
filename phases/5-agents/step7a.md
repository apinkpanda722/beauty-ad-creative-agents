# Step 7a: supervisor

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`agents`는 `domain`·`graph`·`checks`·`llm`·`store`·`obs`), CRITICAL 규칙(LangGraph 상태 dict·기본 타입·하위 그래프 전용 상태, 되돌림은 상태 카운터, `reasoning_effort` 명시·원장 기록, `temperature` 금지, 판정은 코드, 모델이 만든 값을 기대값으로 굳히지 않기)
- `/docs/PRD.md` — 핵심 기능 4(Supervisor), 10(컨텍스트 관리), 15(요청 공통 장치)와 시나리오 S1~S6
- `/docs/ARCHITECTURE.md` — "컨텍스트 관리", "요청 처리 공통 장치", "그라운딩 원칙"
- `/docs/results/p5_dev_compare_preregistration.md` — §8 실측 비용(sonnet 평가 시도당 $0.0063~0.0102, terra low 기획 호출당 $0.0048)
- `/src/beautyads/agents/research.py`, `/src/beautyads/agents/plan_eval.py`, `/src/beautyads/agents/planning.py`, `/src/beautyads/agents/evaluation.py`, `/src/beautyads/agents/state.py`, `/src/beautyads/domain/research.py`, `/src/beautyads/domain/supervisor.py`(없으면 이 step이 만든다), `/src/beautyads/domain/tenant.py`, `/src/beautyads/domain/tools.py`, `/src/beautyads/llm/structured.py`, `/tests/test_schema_guard.py`, `/tests/test_llm_param_guard.py`, `/tests/test_research_agent.py`, `/tests/test_plan_eval.py`, `/tests/test_architecture.py` — step 4·5·5c·6a~6f 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/supervisor.py`(새 파일), `src/beautyads/agents/supervisor.py`(새 파일), `src/beautyads/agents/research.py`, `tests/test_domain_supervisor.py`(새 파일), `tests/test_supervisor.py`(새 파일), `tests/test_schema_guard.py`, `tests/test_llm_param_guard.py`, `tests/test_research_agent.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/supervisor.py`, `src/beautyads/agents/supervisor.py`, `src/beautyads/agents/research.py`(`_SYSTEM`에 지시 한 줄 추가에 한함, 그 밖의 코드·상태 키·상태 판정 불변), `tests/test_domain_supervisor.py`, `tests/test_supervisor.py`, `tests/test_schema_guard.py`(`GUARDED_MODULES`에 `agents/supervisor.py`를 추가하는 갱신과 Supervisor 스펙을 캡처해 검증하는 케이스 추가에 한함. 기존 단언 약화·삭제 금지, 갱신한 줄은 집합에 항목 하나만 더한다), `tests/test_llm_param_guard.py`(Supervisor 호출 모양 조합 추가에 한함, 기존 조합 불변), `tests/test_research_agent.py`(새 시스템 지시 한 줄을 확인하는 케이스 추가에 한함, 기존 단언 변경 0줄)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

요청 하나를 해석해 리서치·기획·평가 하위 에이전트를 부르고 한도를 코드로 강제하는 **Supervisor**를 만든다. 하위 에이전트에는 대화 전체가 아니라 **과제 지시서**(`ResearchBrief`)만 넘긴다. 이 step은 api·저장소·그래프·모델을 직접 부르지 않는다(모든 서비스는 주입 함수, 테스트는 가짜). **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

**`domain/supervisor.py`**(표준 라이브러리·pydantic만):
- `Intent`(StrEnum `pattern`(S1 패턴 질의)·`relation`(S2 관계 질의)·`plan`(S3 기획 요청)·`boundary`(S5 범위 밖·근거 없음 조건). 피드백(S4)은 자연어가 아니라 별도 엔드포인트(7b)라서 의도에 없다).
- `SupervisorDecision`(`extra="forbid"`, **자유 형식 딕셔너리 금지**): `intent: Intent`, `category: Category | None`(`other` 제외 3종), `claim: Claim | None`, `hook_type: HookType | None`, `angle: Angle | None`, `format: Format | None`, `skin_concern: SkinConcern | None`, `plan_count: Literal[1, 2, 3]`, `goal: str`. 모델이 채운다(스키마는 OpenAI strict 규칙을 만족해야 한다).
- `RequestLimits`(frozen): `max_text_cost_usd: float = 0.30`(**이미지를 제외한 텍스트 모델 비용의 요청 1건 상한**. 이름·주석·문서에 "텍스트 모델 비용, 이미지 제외"를 명시한다. 기획 1안 평가 3시도 약 $0.07를 3안까지 담는 값, 실측 근거: 6d 결과 §8. 이미지는 기존 이미지 목적 상한($3.5)과 호출 전 검사로 따로 막고 요청당 합산에는 포함하지 않는다), `max_plans: int = 3`, `max_reworks: int = 2`, `decide_max_chars: int = 2000`, `handoff_max_evidence_ids: int = 30`, `handoff_max_aggregates: int = 20`.
- 순수 함수: `cost_exceeded(text_spent_usd, limits) -> bool`(`>=` 경계, 텍스트 모델 비용만), `trim_message(message, limits) -> tuple[str, bool]`(자른 사실), `trim_handoff(handoff, limits) -> tuple[dict, list[dict]]`(근거 ID·`aggregates` 항목이 상한을 넘으면 앞부분만 남기고 `{"field", "kept", "total"}` 기록을 돌려준다. 조용히 자르지 않는다), `numbers_in_results(values) -> set[float]`와 `verify_aggregates(aggregates: dict[str, str], allowed: set[float]) -> tuple[dict[str, str], list[str]]`(아래), `AGGREGATE_UNVERIFIED_PREFIX = "aggregate:"`, 고정 문장 상수(`OUT_OF_SCOPE_TEXT`, `NO_EVIDENCE_TEXT`, `LIMIT_REACHED_TEXT`)와 `AGGREGATES_LABEL = "모델 작성값, 검증되지 않음"`.
- **`verify_aggregates`(승인된 요구: 숫자 집합 대조)**: 각 항목 값에서 숫자 토큰(`-?\d+(?:[.,]\d+)?`, 천 단위 쉼표 제거)을 뽑아 **하나라도 `allowed`에 없으면 그 항목을 결과에서 빼고** 항목 이름을 `["aggregate:<이름>: 도구 출력에 없는 수치"]` 형태로 돌려준다(숫자 토큰이 없는 항목은 그대로 둔다). 비교는 수치 동일성(정수·실수 표기 차이 무시, 절대 오차 1e-9)이다. `numbers_in_results(values)`는 도구 결과 dict(`ToolResult.model_dump`)의 `row_count`·`shown_count`·`len(evidence_ids)`·`top_rows`의 **숫자형 값과 숫자만으로 된 문자열 값**을 모은다(ID 문자열 안의 숫자·날짜 문자열·`summary` 안의 숫자는 넣지 않는다. 직접 계산한 비율·합계는 집합에 없으므로 빠진다).

**`agents/research.py`**: `_SYSTEM`에 한 줄을 더한다: "수치는 도구 출력의 값을 그대로 인용하고 직접 계산하지 않는다." 그 밖은 바꾸지 않는다.

**`agents/supervisor.py`**(`agents` 계층):
- `decide(message, *, as_of, structured, limits, **call_options) -> DecideResult(ok, decision: dict | None, trimmed: bool, failure)`: `gpt-6-luna`, **`reasoning_effort="none"` 상수 `SUPERVISOR_REASONING_EFFORT`로 명시**(`temperature` 없음), `make_structured("gpt-6-luna")`(OpenAI strict). 스키마는 `SupervisorDecision`의 JSON 스키마를 strict 규칙(모든 객체 `additionalProperties: false`·`required`가 모든 속성, 선택 값은 `anyOf [X, null]`, 자유 형식 객체 없음)으로 변환한 것이다(이 모듈 안의 작은 변환 함수, `agents/planning.py`는 import하지 않는다). 모델 입력은 JSON 데이터 `{message(자른 뒤), as_of, supported_categories, intents}`와 시스템 지시(역할, "지원 카테고리 밖이거나 판단할 수 없으면 `boundary`", 닫힌 값만, `TOOL_DATA_RULE` 상수)이고 **기준일은 서버가 `as_of`로 준다**(모델이 오늘 날짜를 추측하지 않는다).
- `run_request(*, message, ctx, profile, feedback, decide_fn, research_fn, plan_eval_fn, spent_fn, limits=RequestLimits(), on_event=None) -> dict`: LangGraph 상위 그래프. **전용 상태는 접두사 `sv_`**(`sv_message`, `sv_decision`, `sv_brief`, `sv_handoff`, `sv_results`, `sv_index`, `sv_status`, `sv_steps`, `sv_trims`, `sv_tool_outputs`, `sv_spent`, 모두 dict·기본 타입, 부모 `AgentState`·`ResearchState`·`PlanEvalState`와 키 교차 0, 테스트가 실제 키 집합으로 단언). `decide_fn(message) -> dict`, `research_fn(brief: dict, raw_store: dict) -> dict`(핸드오프), `plan_eval_fn(brief, handoff, profile, feedback) -> dict`(6c 결과), `spent_fn() -> float`(요청 시작 뒤 누적 **텍스트 모델 비용(이미지 제외)**, 호출 직전에 부른다).
- 흐름: `decide` → (`boundary`이거나 `category`가 없으면 코드가 `kind="out_of_scope"`로 끝내고 모델을 더 부르지 않는다) → `brief` 구성(닫힌 값만) → `research`(`research_fn`, 도구 원출력은 `raw_store`에 두고 상태에는 넣지 않는다) → 핸드오프 `status`가 `no_evidence`이면 코드가 `kind="no_evidence"`로 끝낸다(**지어내지 않는다**) → `aggregates` 검증(`numbers_in_results`로 만든 집합에 없는 수치는 `aggregates`에서 빼고 `unresolved`에 `aggregate:<이름>: ...`로 옮긴다) → 의도가 `pattern`·`relation`이면 `kind="research"`로 끝 → `plan`이면 안마다(`plan_count`) `cost_exceeded(spent_fn())`를 **호출 직전에 검사**하고(넘으면 `kind="plan"`·`limit_hit=True`·`limit_kinds`에 `"text"`로 그 시점 결과를 미완료 표시와 함께 돌려준다) `trim_handoff` 뒤 `plan_eval_fn`을 호출한다.
- **한도(코드가 강제)**: 요청당 텍스트 모델 비용(`max_text_cost_usd`, 이미지 제외), 기획 안 수(`max_plans`), 되돌림 횟수(6c가 상태 카운터로 강제, 이 step은 `max_reworks=2`를 넘기지 않게 넘긴다), 단계 수(노드 실행 상한, 넘으면 미완료 표시), 에이전트별 입력 예산(`decide_max_chars`, `handoff_max_*`: 자른 사실은 `input_trims`에 기록). `recursion_limit`은 안전망으로만 쓴다.
- 결과 dict(JSON): `{"kind": "research"|"plan"|"out_of_scope"|"no_evidence"|"failed", "intent", "brief", "handoff"(검증을 거친 것), "aggregates_label": AGGREGATES_LABEL, "aggregates_removed": [이름…], "plans": [6c 결과…], "limit_hit": bool, "limit_kinds": ["text"|"image"…](어느 상한에 닿았는지, 정렬된 목록, 비면 `limit_hit`는 거짓: `text`는 `cost_exceeded`, `image`는 어떤 기획안의 `image`가 `{"ok": False, "code": "IMAGE_CAP_REACHED"}`일 때), "limits": {"text_spent_usd", "max_text_cost_usd"}, "input_trims": [...], "steps": [{"agent", "phase", "status"}…], "tool_outputs": [{"tool", "row_count", "rows"(최대 50행, 값은 JSON 안전)}…](집계·비교 도구만, 화면 명령용), "disclaimer": CLAIM_CHECK_DISCLAIMER}`. **`on_event`(스레드 안전 큐로 SSE에 연결되는 콜백, 7c)**: 있으면 단계 경계마다 **그 시점에** 호출한다(실패해도 흐름을 막지 않는다: 예외는 삼키고 코드만 센다). 이벤트는 dict `{"event": "step", "agent", "phase", "status"}` 또는 `{"event": "tool_start", "name", "kind"}`다. 호출 지점과 순서: 요청 해석 끝(`supervisor` `end`) → 리서치 끝(`research` `end`) → 리서치가 쓴 도구마다 `tool_start`(핸드오프 `result_counts`의 도구 이름과 `agents/tools.get_tool`의 종류, **리서치 종료 뒤 순서대로 한꺼번에 내보내는 한계는 승인됨, 코드 주석에 명시**) → 기획 안마다: `planning` `start`(그 안의 `plan_eval_fn` 호출 직전) → 호출이 끝나면 `evaluation` `end`, 되돌림 횟수만큼 `rework` 이벤트(결과의 `rework_count`), 이미지가 있으면 `image` `end` → 완료(`supervisor` `done`). 단계 함수가 끝나기 **전에** 다음 단계가 시작되지 않으므로 이벤트는 단계 순서대로 먼저 도착해야 하고 마지막에 한꺼번에 나가면 안 된다(research.py·plan_eval.py는 바꾸지 않는다).
- 비밀·본문·모델 응답 전문을 결과·로그에 넣지 않는다.

**FP 가드(필수)**: `tests/test_llm_param_guard.py`에 Supervisor 호출 모양(`gpt-6-luna`, `reasoning_effort="none"`, strict `json_schema`)을 실제 `litellm.get_optional_params`에 통과시키는 조합을 추가한다(FP-C13). `tests/test_schema_guard.py`의 `GUARDED_MODULES`에 `agents/supervisor.py`를 더하고(`StructuredSpec(`을 호출하는 새 모듈), Supervisor 흐름에서 가짜 `structured`가 받은 스펙을 모아 strict 검증기로 검증하는 케이스를 추가한다(FP-C15, 검사 0건이면 실패).

**반드시 있어야 하는 테스트**(가짜 함수·합성 값. 모델 문장·값을 기대값으로 굳히지 않는다):
- `domain/supervisor`: `SupervisorDecision` 닫힌 값 밖 거부·`plan_count` 범위 밖 거부·`extra` 거부·자유 형식 필드 없음(스키마에 `additionalProperties: true` 객체가 없음). `cost_exceeded` 경계, `trim_message`·`trim_handoff`의 상한 경계와 `{"field", "kept", "total"}` 기록(조용한 잘림 없음). **`verify_aggregates`**: 도구 결과 숫자와 일치하는 값은 유지, 집합에 없는 수치(직접 계산한 비율·합계)가 든 항목은 빠지고 이름이 `aggregate:` 형식으로 나온다, 숫자 토큰이 없는 항목은 유지, 정수·실수 표기 차이(`7`·`7.0`)와 쉼표(`1,234`)가 같게 취급된다, `numbers_in_results`가 ID 문자열·날짜 문자열·`summary` 안의 숫자를 넣지 않는다.
- `decide`: **가짜 `structured`가 받은 `messages` 호출 인자를 직접 검사**한다(FP-C14): 모델 `gpt-6-luna`, `reasoning_effort`가 상수 `"none"`, `temperature` 없음, 사용자 메시지 JSON에 자른 `message`·`as_of`·`supported_categories`가 있고 시스템 메시지에 `TOOL_DATA_RULE`이 있다. 2,000자를 넘는 메시지는 잘리고 `trimmed=True`. 구조화 실패는 예외 없이 `ok=False`. 스키마가 strict 검증기를 통과한다.
- `run_request` 흐름(가짜 함수): `boundary`·카테고리 없음은 `out_of_scope`이고 `research_fn`이 불리지 않는다. 핸드오프 `no_evidence`는 `kind="no_evidence"`이고 `plan_eval_fn`이 불리지 않는다. `pattern`은 `research`로 끝나 `plan_eval_fn` 미호출. `plan` `plan_count=3`이면 `plan_eval_fn`이 3번 불리고 안마다 호출 직전에 `spent_fn`이 불린다. `spent_fn`이 상한을 넘기면 그 안부터 호출하지 않고 `limit_hit=True`와 지금까지의 결과가 나온다. 비용 상한 전에는 `limit_hit=False`. `aggregates`의 검증 안 된 수치가 빠지고 `unresolved`·`aggregates_removed`에 반영된다. 하위 에이전트 호출 인자에 **대화 전체가 아니라 `brief`만** 있다(`research_fn`이 받은 인자 검사). `plan_eval_fn`이 받은 핸드오프가 `trim_handoff`를 거친다. 결과가 `json.dumps`로 직렬화된다. `on_event`가 예외를 던져도 흐름이 끝난다.
- 상태: 상위 상태의 모든 값이 dict·기본 타입이고 상태 스키마 키 집합과 `AgentState`·`ResearchState`·`PlanEvalState` 키 집합의 교차가 비어 있다. 한도는 상태 카운터로 강제한다(매우 낮은 안전망에서도 카운터로 먼저 끝나는 케이스). **이벤트 실시간성**: 가짜 단계 함수가 호출 순서를 기록하고 `on_event`도 같은 기록에 남겨, 요청 해석 끝 이벤트가 `research_fn` 호출보다 먼저, 리서치 끝 이벤트가 첫 `plan_eval_fn` 호출보다 먼저, 각 안의 시작 이벤트가 그 안의 `plan_eval_fn`보다 먼저 기록됨을 단언한다(마지막에 한꺼번에 오지 않음). `on_event`가 예외를 던져도 요청이 끝까지 계속된다. 이미지 상한(`IMAGE_CAP_REACHED`)이면 `limit_kinds`에 `image`가 있고 텍스트 상한과 구분된다(둘 다면 둘 다 담긴다). 텍스트 비용 상한은 `spent_fn` 값만 본다(이미지 비용을 합산하지 않음).
- 새 시스템 지시: `research`의 시스템 메시지에 "수치는 도구 출력의 값을 그대로 인용하고 직접 계산하지 않는다"가 있다(호출 인자 검사).
- FP 가드(위) 통과. `tests/test_architecture.py` 통과(`agents`는 허용 계층만, 새 모듈은 `fastapi`·`neo4j`·`psycopg`를 import하지 않는다).

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

- 하위 에이전트에 대화 전체나 이전 기획안 전문을 넘기지 마라. 이유: 과제 지시서와 구조화 핸드오프만 넘긴다(ARCHITECTURE 컨텍스트 관리). 입력 예산을 넘으면 자른 사실을 `input_trims`에 남긴다(조용한 잘림 금지).
- 근거가 없거나 범위 밖인 요청을 모델이 채우게 하지 마라. 이유: S5는 코드가 판정해 "근거 없음"·"범위 밖"으로 끝낸다(AGENTS.md CRITICAL: 판정할 수 있는 것은 코드).
- `aggregates`를 검증 없이 통과시키거나 직접 계산한 수치를 남기지 마라. 이유: `aggregates`는 모델 작성값이다. 도구 출력에 없는 수치는 빼서 `unresolved`로 옮긴다(승인된 요구).
- 상위 상태에 하위 그래프 상태 키(`brief`·`handoff`·`pe_*` 등)를 쓰거나 pydantic 객체·도구 원출력 전체를 넣지 마라. 이유: 전용 상태 스키마(접두사 `sv_`)와 dict·기본 타입 규칙(AGENTS.md CRITICAL). 원출력은 `raw_store`에만 둔다.
- Supervisor의 `reasoning_effort`를 생략하거나 `temperature`를 지정하지 마라. 이유: luna는 추론 기본값 때문에 비용이 약 100배 달라진다(AGENTS.md). 상수로 명시하고 원장에 기록된다.
- 한도 검사를 호출 뒤에 하거나 `recursion_limit`에 맡기지 마라. 이유: 비용·횟수는 호출 직전에 코드가 막아야 한다(AGENTS.md: 호출 직전 상한 검사, 되돌림은 상태 카운터).
- 가짜 `structured`·`research_fn`의 반환값만 단언하지 말고 받은 인자를 직접 검사하라. 이유: 모델이 읽어야 할 정보가 실제 입력에 들어가는지 확인한다(FP-C14).
