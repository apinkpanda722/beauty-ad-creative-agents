# Step 4: single-agent

## 설계 검토 기록

**식별자 전수 대조(bb0e64f)**: `agents/research.py:136-203`(`act`: 도구 이름 검증 `names`, `get_tool(name).input_model.model_validate`, 코드 `TOOL_UNKNOWN`·`INPUT_INVALID`·`TOOL_RESULT_UNREADABLE`, `raw_store`, `pool.update(result.evidence_ids)`)·`:15 MAX_ROWS`·`:19`·`:120 tool_result_payload`·`:185`, `agents/tool_messages.py`(`tool_result_payload`·`TOOL_DATA_RULE`·`PARTIAL_RESULT_RULE`·`TOOL_RESULT_UNREADABLE`), `agents/planning.py:58 strict_plan_schema`·`:19 _SYSTEM`(규칙 문장 출처, 읽기 전용), `domain/plan.py:12 Plan`·`validate_plan`, `checks/plan_checks.py:104 run_checks_on_dict(data, *, handoff_evidence_ids, rules, evidence_index, support, certs)`, `domain/research.py:24 ResearchBrief.max_tool_calls`(기본 6, 상한 10), `domain/supervisor.py:49 RequestLimits`·`cost_exceeded`, `llm/structured.py`(`StructuredSpec`·`StructuredGenerator`·`generate`), `agents/tools.py`(`TOOLS`·`ToolKind`·`get_tool`·`tool_definitions`), `domain/tools.py:25 ToolContext`, `api/assembly.py:94-112`(래퍼가 호출 옵션과 상한 검사를 합쳐 주는 방식, 읽기 전용).

**상수 단언 grep**: 이 step의 새 상수(`SINGLE_AGENT_PROMPT_VERSION`, 모델·효능, 도구 호출 한도)를 단언하는 기존 테스트 없음. 도구 호출 한도는 `ResearchBrief.model_fields["max_tool_calls"].default`를 읽어 쓰고 리터럴 6을 코드·테스트에 적지 않는다(`tests/`에서 `max_tool_calls == 6` 정확 단언을 새로 만들지 않는다).

**새 칸 대응표**: `run_tool_loop`의 반환(`observations`·`evidence_pool`·`tool_calls`·`model_calls`)(이 step → step 7 실행기, step 8의 E3 그래프 팔), `SINGLE_AGENT_PROMPT_VERSION`·`_SYSTEM` sha256(이 step → step 10 사전 등록 동결 값 → step 2 가드의 `extra`), 단일 팔 결과 필드(`kind`·`plan`·`check_report`·`evidence_pool`·`failure_code`)(이 step → step 5 채점기·step 7 러너).

**조언 세션 결정(A)**: 단일 에이전트 팔은 **순수 기준선**이다. `available_efficacy`·`pattern_context`·`verify_aggregates`·재작업 루프·루프 내 평가(sonnet)를 갖지 않는다. 같은 `chat`·`structured` 래퍼 기본 인자, 도구 호출 한도(기본 6), 요청당 텍스트 비용 상한(`RequestLimits.max_text_cost_usd` 0.30), 같은 생성 모델(`gpt-6.1-terra`, `reasoning_effort` low)을 쓴다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 외부 호출은 래퍼 하나, `temperature` 미지정, 에이전트마다 `reasoning_effort` 명시와 원장 기록, 유료 호출 직전 공급사별 누적액 검사, 도구 호출 `arguments`는 JSON 문자열이라 파싱 실패 처리
- `/docs/EVAL.md`(E2: 같은 모델·같은 도구·같은 그래프·같은 요청당 비용 상한, 구성만 다르다), `/docs/ARCHITECTURE.md`(그라운딩 원칙·컨텍스트 관리 절), `/.claude/skills/failure-patterns/SKILL.md`(FP-C13·C14·C15·C16)
- `/src/beautyads/agents/research.py`(전체, 읽기 전용: 도구 루프 `act`·`messages`), `/src/beautyads/agents/tool_messages.py`, `/src/beautyads/agents/planning.py`(`_SYSTEM`·`strict_plan_schema`·`make_plan`, 읽기 전용), `/src/beautyads/agents/tools.py`, `/src/beautyads/domain/tools.py`, `/src/beautyads/domain/plan.py`, `/src/beautyads/checks/plan_checks.py`, `/src/beautyads/domain/supervisor.py`(`RequestLimits`·`cost_exceeded`)
- `/src/beautyads/llm/structured.py`·`/src/beautyads/llm/chat.py`(읽기 전용: 래퍼 시그니처와 반환), `/src/beautyads/api/assembly.py`(`call_options`·`chat`·`structured` 조립, 읽기 전용), `/src/beautyads/agents/evaluation.py`(`evaluate_plan`이 `run_checks_on_dict`를 부르는 방식, 읽기 전용)
- `/tests/test_schema_guard.py`(`GUARDED_MODULES`·`test_no_new_structured_spec_module_without_a_guard`·`test_actual_research_chat_messages`·`guard_specs`), `/tests/test_llm_param_guard.py`(읽기 전용: 이미 terra low 구조화·도구 모양을 덮는다), `/tests/test_caps_guard.py`(읽기 전용: 상한 리터럴 금지 스캔), `/tests/test_research_agent.py`(가짜 `chat`·`tool_runner` 방식 선례)
- `/src/beautyads/eval/evalset.py`(step 2), `/src/beautyads/eval/p5_compare.py`(읽기 전용: 가짜 구성 선례)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/single_agent.py`(새 파일), `tests/test_single_agent.py`(새 파일), `tests/test_schema_guard.py`(`GUARDED_MODULES`에 `eval/single_agent.py` 한 개 추가와 새 테스트 함수 추가에 한함, 기존 단언 약화 금지)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/single_agent.py`, `tests/test_single_agent.py`, `tests/test_schema_guard.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로, 평가 정답을 읽는 채점 함수)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

E2의 **단일 에이전트 팔**과, E3 그래프 팔이 함께 쓸 **도구 루프**를 `eval/single_agent.py`에 만든다. 모델·그래프·네트워크에 접속하지 않는다. **테스트를 먼저 쓴다.**

새 식별자: `SINGLE_AGENT_PROMPT_VERSION`, `SINGLE_AGENT_MODEL`, `SINGLE_AGENT_EFFORT`, `single_agent_system_prompt`, `ToolLoopResult`, `run_tool_loop`, `SingleAgentResult`, `run_single_agent`

**`run_tool_loop(*, seed, system, ctx, chat, tool_runner, model, reasoning_effort, max_tool_calls, purpose) -> ToolLoopResult`**
- `agents/research.py`의 `act` 루프와 **같은 동작**을 만든다: 표시 도구가 아닌 도구 정의만 노출(`names = {tool.name for tool in TOOLS if tool.kind != ToolKind.display}`), `tool_choice="auto"`, 호출마다 메시지를 `system` + user JSON(`{**seed, "observations": [...]}`)으로 다시 만들고 관측은 `tool_result_payload(name, raw)`(컨텍스트 관리 켬: 단일 팔도 도구 반환은 같은 이원화를 받는다), 도구 호출 수가 `max_tool_calls`에 닿거나 응답에 도구 호출이 없으면 끝, 알 수 없는 도구는 코드 `TOOL_UNKNOWN`, 인자 파싱·검증 실패는 `INPUT_INVALID`, `ToolFailure`는 그 코드, `tool_result_payload(...).get("failure") == TOOL_RESULT_UNREADABLE`이면 그 코드, 성공 결과의 `evidence_ids`는 풀에 합친다. 원출력(`raw`)은 반환 객체 안에만 두고 그래프 상태에 넣지 않는다.
- `ToolLoopResult`: `observations: list[dict]`, `raw: list[dict]`, `evidence_pool: list[str]`(정렬·중복 제거), `tool_calls: int`, `model_calls: int`(이 루프가 부른 `chat` 횟수), `failures: list[str]`.
- `chat`은 호출 옵션(원장 경로·상한·키)을 합쳐 주는 주입 래퍼다. **이 모듈은 상한·원장 경로·키 리터럴을 만들지 않는다**(FP-C16, `tests/test_caps_guard.py`가 통과해야 한다). 이 루프가 넘기는 옵션은 `model`·`messages`·`tools`·`tool_choice`·`reasoning_effort`·`purpose`뿐이다(`temperature` 지정 금지).

**`run_single_agent(*, message, ctx, profile, feedback, chat, tool_runner, structured, rules, evidence_index, support, certs, limits=RequestLimits(), spent_fn=None) -> dict`**
- 입력은 요청 문장 원문이다(요청 해석 단계 없음). seed는 `{"request": message, "profile": {brand, tone, forbidden_terms, own_product_url}, "feedback": feedback}`.
- 모델은 `SINGLE_AGENT_MODEL = "gpt-6.1-terra"`, `SINGLE_AGENT_EFFORT = "low"`. 도구 호출 한도는 `ResearchBrief.model_fields["max_tool_calls"].default`. 도구 루프 `purpose="single-agent"`.
- 도구 루프 뒤 **기획안 1개**를 `structured.generate(StructuredSpec("single_agent_plan", …, strict_plan_schema(), Plan 검증), messages=…, purpose="single-plan", reasoning_effort=SINGLE_AGENT_EFFORT)`로 만든다. 모델이 읽는 입력 JSON은 seed + 관측 + `"evidence_pool"`이다. **`pattern_context`·`available_efficacy`·`aggregates`·`rework` 칸은 입력에 없다.**
- 비용 상한: 모델 호출(도구 루프 각 호출과 기획 호출) **직전마다** `spent_fn()`(요청 시작 이후 텍스트 비용)이 있으면 `cost_exceeded(spent, limits)`를 검사하고 참이면 호출하지 않고 `kind="limit"`으로 끝낸다. `spent_fn`이 예외를 던지면 `kind="failed"`, `failure_code="SINGLE_SPENT_FAILED"`로 닫는다(조용히 통과 금지).
- 끝난 뒤 코드 검사: `run_checks_on_dict(plan, handoff_evidence_ids=evidence_pool, rules=rules, evidence_index=evidence_index, support=support, certs=certs)`를 **한 번** 적용한다(Supervisor 팔의 `evaluate_plan`이 쓰는 것과 같은 함수, LLM 평가·재작업 없음).
- 반환 dict 키: `kind`(`plan`|`no_evidence`|`limit`|`failed`), `plan`(dict|None), `check_report`(dict|None), `evidence_pool`, `tool_calls`, `model_calls`(도구 루프 + 기획 호출 수), `failure_code`(고정 코드|None), `prompt_version`. 풀이 비면 기획 호출 없이 `no_evidence`. 구조화 실패는 `failed`와 `STRUCTURED_FAILED` 계열 고정 코드, 모델 응답 본문·키·예외 문장은 담지 않는다.
- **시스템 프롬프트(`single_agent_system_prompt()`, `SINGLE_AGENT_PROMPT_VERSION = "2026-11-19-1"`)**: `agents/planning.py`의 `_SYSTEM`에서 근거·분류 값·카피 지침·`TOOL_DATA_RULE`·`PARTIAL_RESULT_RULE` 문장을 따르되 `pattern_context`·`dominant_axes`·`thin_pool`·`available_efficacy`·`rework` 문장은 뺀다. 도구로 경쟁 소재를 조회한 뒤 기획안 1안을 쓰고 `evidence_ids`는 조회된 근거 ID 안에서만 고르며, 도구 결과로 확인된 효능이 아니면 `claimed_efficacy`를 빈 목록으로 둔다고 쓴다. `planning._SYSTEM`은 읽기만 하고 고치지 않는다. 이 프롬프트의 sha256은 step 10 사전 등록의 동결 값이 된다.

**`tests/test_schema_guard.py`**: `GUARDED_MODULES`에 `"eval/single_agent.py"`를 더하고(기존 항목·단언 불변), 기존 `test_actual_agent_specs_are_guarded`·`test_actual_research_chat_messages`와 같은 방식의 새 테스트 함수 두 개(이 모듈이 만든 `StructuredSpec` 스키마가 strict 검증기를 통과, 가짜 `chat`이 받은 `messages`가 메시지 시퀀스 검증기를 통과, 검사한 스펙·메시지 수 0은 실패)를 추가한다.

**테스트(`tests/test_single_agent.py`, 합성 환경)**
- (FP-C14) 가짜 `chat`이 받은 `messages`·`tools` 인자를 직접 검사: 도구 관측이 user JSON의 `observations`에 `tool_result_payload` 결과 그대로 들어가 있고(5행·200자·10 ID 상한 적용), 시스템 지시가 `TOOL_DATA_RULE`을 포함한다. 입력 JSON 어디에도 `pattern_context`·`available_efficacy`·`rework` 키가 없다(순수 기준선 단언).
- 호출 모양: 모든 `chat` 호출이 `model="gpt-6.1-terra"`·`reasoning_effort="low"`·`purpose="single-agent"`이고 `temperature`·`caps`·`ledger_path` 키가 없다. 구조화 호출 `purpose="single-plan"`, `reasoning_effort="low"`.
- 도구 호출 한도: 가짜 `chat`이 계속 도구를 호출해도 `ResearchBrief` 기본 한도(코드에서 읽은 값)에서 멈춘다. 알 수 없는 도구·깨진 인자·`ToolFailure`·읽을 수 없는 결과의 코드와 풀 갱신이 `run_research`와 같다.
- **`run_research`와의 동등성**: 같은 가짜 `chat` 응답열·같은 가짜 `tool_runner`로 `run_research`(가짜 `structured`)와 `run_tool_loop`를 각각 돌려 도구 호출 수·증거 풀·관측 payload가 같음을 단언한다.
- 비용 상한: `spent_fn`이 상한 이상이면 모델 호출 전에 `kind="limit"`이고 가짜 `chat` 호출 0건. `spent_fn` 예외 → `SINGLE_SPENT_FAILED`.
- 코드 검사: 기획안의 근거 ID가 풀 밖이면 `check_report`에 `EVIDENCE_NOT_IN_HANDOFF`가 있고, 풀이 비면 기획 호출 0건·`no_evidence`.
- 구조: AST로 이 모듈이 `agents.evaluation`·`agents.plan_eval`·`agents.supervisor`를 import하지 않음(재작업·루프 내 평가·시스템 구성 없음), 상한 딕셔너리·`"caps"` 키 리터럴 없음. 합성 문장을 기대값으로 굳히지 말고 형식(키·닫힌 값·호출 횟수)만 단언한다.

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

- 단일 팔에 `pattern_context`·`available_efficacy`·`aggregates` 검증·재작업 루프·`evaluate_plan`을 붙이지 마라. 이유: 순수 기준선이다(조언 세션 결정 A). 시스템 구성 전체의 효과를 재는 실험이므로 사전 등록 문장과 구현이 어긋나면 안 된다.
- `agents/research.py`·`agents/planning.py`를 고치거나 `planning._SYSTEM`을 재사용 문자열로 바꾸지 마라. 이유: 동결 프롬프트(기획 `2026-11-18-3`)는 읽기만 하고, 단일 팔 프롬프트는 이 모듈에 따로 둔다(sha256로 동결).
- 상한·원장 경로·API 키 리터럴을 이 모듈에 두거나 `min(caps)`로 깎지 마라. 이유: 상한 출처는 `Settings` 한 곳이다(FP-C16, `tests/test_caps_guard.py`).
- 도구 호출 한도를 6으로 하드코딩하거나 `temperature`를 지정하지 마라. 이유: 한도는 `ResearchBrief` 기본값이 출처이고(같은 한도 보장), 추론이 켜진 모델은 `temperature`를 거부한다(AGENTS.md).
- 가짜 `chat`의 반환값만 단언하고 모델이 받은 입력을 검사하지 않는 테스트로 끝내지 마라. 이유: 관측이 실제로 모델에 전달되는지가 결함이었다(FP-C14).
