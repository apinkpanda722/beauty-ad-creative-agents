# Step 6: context-mode

## 설계 검토 기록

**식별자 전수 대조(bb0e64f)**: `agents/supervisor.py` — `:35` `trim_handoff` import·`:436` 호출(`plan` 노드, 반환 `(bounded, trims)`), `:95`·`:161` `trim_message`(유지), `:144`·`:182`·`:365` `sv_tool_outputs`, `:239 _tool_outputs(raw_store)`, `:263 build_supervisor_graph`·`:273 on_event`, `:346-353` `research_fn(deepcopy(state["sv_brief"]), raw_store)` 호출, `:443-449` `plan_eval_fn(brief, bounded, profile, feedback, max_reworks=…)`, `:496 run_request`·`:507 on_event`, 결과 dict `:542-600`(`input_trims`·`tool_outputs`). `agents/research.py` — `:19`·`:120 tool_result_payload`(관측 만들기, `messages` 안)·`:185`·`:206 MAX_ROWS`(로그 표시 건수, 유지)·`:310 run_research`·`:93 build_research_graph`. `agents/planning.py` — `:77 _text_data`·`:93 research_payload`(고정 키 7개)·`:110 make_plan`·`:132-149` payload(`brief`·`research`·`available_efficacy`·`profile`·`feedback`·`rework`)·`:135-140`(`handoff.get("available_efficacy")` 선례)·`:19 _SYSTEM`·`:17 PLANNING_PROMPT_VERSION`. `agents/plan_eval.py:253 run_plan_eval`(핸드오프를 `plan_fn(handoff=…)`에 그대로 전달)·`:138 build_plan_eval_graph`. `agents/evaluation.py:117 research_payload(handoff)`(평가자 입력, **불변**). `api/assembly.py` — `:276 ask(message, ctx, profile, feedback, with_image, on_event=None)`·`:320 research_fn(brief, raw_store)`·`:454 plan_eval_fn`·`:466` 부근 `run_request(...)` 호출. `domain/supervisor.py` — `:49 RequestLimits`(frozen·extra forbid, **칸 추가 금지**)·`:79 trim_handoff`·`:75 trim_message`. `agents/skeleton.py:147`은 `/ask` Supervisor 경로가 아닌 별도 `build_graph`(assembly에서 import만 한다)이므로 **이 step의 대상이 아니다**.

**"끔"이 우회·유지·불변하는 것(사전 등록 문서에 같은 목록을 싣는다)**
| 식별자 | 위치 | 끔 |
|---|---|---|
| `trim_handoff` | `supervisor.py:436` | 우회(원본 `sv_handoff` 그대로, `input_trims`는 빈 목록) |
| `tool_result_payload` | `research.py:120`(`messages`의 관측) | 우회(원출력 그대로 관측에 전달) |
| `sv_tool_outputs` | `supervisor.py:365` | 기획 입력에 별도 필드 `raw_tool_outputs`로 추가 전달 |
| `trim_message` | `supervisor.py:95`·`:161` | 유지(입력 안전 상한, 컨텍스트 관리가 아님) |
| `_text_data`·`research_payload` | `planning.py:77`·`:93` | 유지(텍스트 전용 정책; 새 필드에도 `_text_data` 적용) |
| `MAX_ROWS` 로그 표시 | `research.py:206` | 유지(표시 값 계산식) |
| `MAX_ROWS`·`MAX_VALUE_CHARS`·`MAX_EVIDENCE_IDS`·`tool_result_payload`·`tool_message_content` 정의 | `tool_messages.py` | 불변 |
| `decide_max_chars`·`handoff_max_evidence_ids`·`handoff_max_aggregates`·`trim_message`·`trim_handoff` 정의 | `domain/supervisor.py` | 불변 |

**상수 단언 grep(정확 일치 소비자, 모두 수정 금지·통과 유지)**: `tests/test_tool_messages.py:47`(`(5,200,10)`)·`:60·145·165·187·210·235·243·286·306`, `tests/test_agent_tools.py:735·755`, `tests/test_domain_supervisor.py:93·106`(`trim_message`·`trim_handoff`)·`:260-281`·`:293-295`·`:318-336`, `tests/test_supervisor.py:595`(`handoff_max_aggregates=0`)·`:578·582·631-633`(핸드오프 키 집합), `tests/test_evaluation.py:236-247`·`:223`, `tests/test_api_assembly.py:149-150`, `tests/test_trace.py:161`(`decide_max_chars`), `tests/test_supervisor.py:35·63·78·279`(`RequestLimits()` 직접 생성). **"on"에서 기본 동작이 바뀌지 않으므로 기존 테스트의 단언을 갱신할 필요가 없다. 한 줄도 바꾸지 않는다.**

**새 칸 대응표**: `context_mode`("on" 기본, 인자 → 끔 경로 → 결과 dict에 **끔일 때만** `"context_mode": "off"`; trace 파일 스키마 `obs/trace.py`는 불변이라 trace에는 싣지 않고 step 7 러너 기록에 남긴다), `handoff["raw_tool_outputs"]`(끔 전용: `supervisor.py` → `planning.make_plan`이 키가 있을 때만 payload에 추가).

**조언 세션 승인(B)**: 기획 프롬프트 `_SYSTEM`·`PLANNING_PROMPT_VERSION`은 불변이다. "on"에서 기획 호출 payload는 이 step 전과 **바이트 동일**하다(테스트로 고정).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: LangGraph 상태에는 dict·기본 타입만, 하위 그래프는 전용 상태, 동결 프롬프트 불변
- `/docs/ARCHITECTURE.md`(컨텍스트 관리 절: 지시서·구조화 핸드오프·원자료 참조·도구 반환 이원화), `/docs/ADR.md` ADR-008, `/docs/EVAL.md` E5(켬 대 끔 정의), `/docs/PROMPT_CHANGELOG.md`(읽기 전용: 동결 대상 프롬프트)
- `/src/beautyads/agents/supervisor.py`(전체), `/src/beautyads/agents/research.py`(전체), `/src/beautyads/agents/planning.py`(전체), `/src/beautyads/agents/plan_eval.py`(핸드오프 전달, 읽기 전용), `/src/beautyads/agents/evaluation.py`(`research_payload(handoff)` 사용, 읽기 전용), `/src/beautyads/agents/tool_messages.py`(읽기 전용), `/src/beautyads/domain/supervisor.py`(읽기 전용), `/src/beautyads/api/assembly.py`(`ask`·`research_fn`·`run_request` 호출)
- `/tests/test_supervisor.py`, `/tests/test_research_agent.py`, `/tests/test_planning.py`, `/tests/test_plan_eval.py`, `/tests/test_api_assembly.py`, `/tests/test_evaluation.py`, `/tests/test_tool_messages.py`(모두 읽기 전용: 기존 단언 위치와 가짜 `research_fn`·`chat`·`structured` 구성 방식 — 가짜 `research_fn`은 인자가 둘이다)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/agents/supervisor.py`(`context_mode` 인자·분기 추가에 한함), `src/beautyads/agents/research.py`(`context_mode` 인자와 관측 분기 추가에 한함), `src/beautyads/agents/planning.py`(`make_plan`의 조건부 payload 필드 한 곳에 한함, `_SYSTEM`·버전 불변), `src/beautyads/api/assembly.py`(`ask` 인자와 두 곳 전달에 한함), `tests/test_supervisor_context_mode.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/agents/supervisor.py`, `src/beautyads/agents/research.py`, `src/beautyads/agents/planning.py`, `src/beautyads/api/assembly.py`, `tests/test_supervisor_context_mode.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로, 평가 정답을 읽는 채점 함수)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

E5의 컨텍스트 관리 **"끔" 경로**를 `run_request(..., context_mode="on")` 키워드 인자로 만든다. 모델·네트워크에 접속하지 않는다. **테스트를 먼저 쓴다.**

새 식별자: `context_mode`, `CONTEXT_MODES`, `raw_tool_outputs`

**설계 규칙(바꾸지 않는다)**
- `context_mode`는 `"on"`(기본)·`"off"`만 받는다. 그 밖의 값은 **호출 전에** `ValueError("CONTEXT_MODE_INVALID")`. `RequestLimits`에 칸을 추가하지 않는다.
- **"on"의 동작은 이 step 전과 같다**: 같은 입력에서 `run_request` 결과 dict·모델이 받는 인자가 같다.

**`agents/supervisor.py`**
- `run_request(..., context_mode="on")`·`build_supervisor_graph(..., context_mode="on")`로 전달한다(키워드 전용 끝에 추가, 기존 인자 이름·순서 불변).
- `research` 노드: `context_mode == "off"`일 때만 `research_fn(deepcopy(state["sv_brief"]), raw_store, context_mode="off")`로 호출하고, "on"이면 지금처럼 인자 둘로 호출한다(기존 가짜 `research_fn`이 인자 둘이므로 "on"에서 키워드를 넘기지 않는다).
- `plan` 노드: "off"이면 `trim_handoff`를 건너뛰고 `bounded = deepcopy(state["sv_handoff"])`, `trims = []`, 그리고 `bounded["raw_tool_outputs"] = deepcopy(state["sv_tool_outputs"])`로 도구 원출력을 핸드오프 dict에 실어 `plan_eval_fn`에 넘긴다. "on"이면 지금 코드 그대로다. `research_payload`의 키 집합은 **늘리지 않는다**.
- 결과 dict에는 **"off"일 때만** `"context_mode": "off"` 키를 더한다("on"은 키가 없다). trace(`obs/trace.py`)는 이 step에서 고치지 않는다.

**`agents/research.py`**
- `run_research(..., context_mode="on")`·`build_research_graph(..., context_mode="on")`. `messages(state)`의 관측 만들기만 분기한다: "on"은 `tool_result_payload(entry["name"], raw)`(지금), "off"는 `deepcopy(raw)`(도구 원출력 그대로). `MAX_ROWS`·`shown_count` 표시 계산·`tool_result_payload` 정의는 그대로다. 잘못된 값은 `ValueError("CONTEXT_MODE_INVALID")`.

**`agents/planning.py`**
- `make_plan`의 `payload`를 만든 뒤, `handoff.get("raw_tool_outputs")`가 `None`이 아닐 때만 `payload["raw_tool_outputs"] = _text_data(raw)`를 더한다(`available_efficacy` 처리와 같은 방식, `handoff`는 이미 인자). **그 밖의 줄(`_SYSTEM`, `PLANNING_PROMPT_VERSION`, `research_payload`, 기존 payload 키)은 바꾸지 않는다.** 평가자(`evaluation.py`)는 `research_payload(handoff)`만 읽으므로 새 키를 무시하고 입력이 두 모드에서 같다.

**`api/assembly.py`**
- `ask(message, ctx, profile, feedback, with_image, on_event=None, *, context_mode="on")`. `research_fn(brief, raw_store, context_mode="on")`이 `run_research(..., context_mode=context_mode)`로 전달하고, `run_request(..., context_mode=context_mode)`로 전달한다. `/ask` 라우트(`api/ask.py`)는 고치지 않는다(HTTP 경로는 "on"만 쓴다).

**테스트(`tests/test_supervisor_context_mode.py`, 가짜 `research_fn`·`plan_eval_fn`·`chat`·`structured`)**
1. **"on" 동일성(회귀)**: (a) `context_mode`를 생략한 `run_request`와 `"on"`을 준 `run_request`의 결과 dict가 같다. (b) 인자 둘짜리 가짜 `research_fn`이 "on"에서 그대로 호출된다. (c) `make_plan`의 payload 키 집합이 정확히 `{"brief","research","available_efficacy","profile","feedback","rework"}`이고 모델이 받은 `messages`의 user JSON이 `research_payload(handoff)` 등 기존 구성식으로 만든 기대값과 같다(`raw_tool_outputs` 없음). (d) `plan_eval_fn`이 받은 핸드오프에 `raw_tool_outputs` 키가 없고 `input_trims`가 기존대로다.
2. **"off" 경로**: (a) `research_fn`이 `context_mode="off"`를 받는다. (b) 상한 `handoff_max_evidence_ids`를 작게 준 `RequestLimits`에서도 `plan_eval_fn`이 받은 핸드오프의 `evidence_ids`가 자르지 않은 원본이고 `input_trims == []`. (c) 받은 핸드오프의 `raw_tool_outputs`가 `sv_tool_outputs`와 같다. (d) 결과 dict에 `"context_mode": "off"`가 있다. (e) `make_plan`이 만든 `messages`의 user JSON에 `raw_tool_outputs`가 들어 있고(FP-C14: 가짜 `structured`가 받은 인자를 직접 검사) 그 안에 URL·이미지 필드(`_text_data` 대상)가 없다.
3. **research 관측**: 가짜 `tool_runner`가 8행을 돌려줄 때 "on"의 모델 입력 관측은 `MAX_ROWS` 상한(5행)이 적용되고 "off"는 8행 전부를 담는다. 둘 다 `evidence_pool`·로그 표시 건수(`shown_count`)는 같다.
4. **검증**: 잘못된 `context_mode`는 가짜가 한 번도 불리기 전에 `CONTEXT_MODE_INVALID`. `RequestLimits`가 `context_mode` 칸을 갖지 않는다(`model_fields`).
5. **조립 경유**: `tests/test_api_assembly.py`의 가짜 조립 방식으로 `ask(..., context_mode="off")`가 `run_request`와 `research_fn`에 값을 전달하고, 기본 호출은 `context_mode`를 **전달하지 않는다**(인자 둘 가짜가 통과).
6. 기존 테스트 전체가 수정 없이 통과한다.

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

- `planning._SYSTEM`·`evaluation._SYSTEM`·`PLANNING_PROMPT_VERSION`·`EVALUATION_PROMPT_VERSION`·`research_payload`의 키 집합·`RequestLimits`·`tool_messages.py`의 상수와 함수를 바꾸지 마라. 이유: 동결 값이고 키 집합·상수를 정확 일치로 단언하는 기존 테스트가 있다(FP-C11). 새 입력은 별도 필드로만 전달한다(조언 세션 승인 B).
- "on"에서 호출 인자·결과 키·payload를 하나라도 바꾸지 마라. 이유: E5의 켬은 P5 동작과 같아야 한다. "on"에서 `research_fn`에 키워드를 넘기면 인자 둘짜리 기존 가짜가 깨진다.
- `trim_message`(입력 안전 상한)·`_text_data`(텍스트 전용 정책)·`MAX_ROWS` 표시 계산을 "끔"에서 우회하지 마라. 이유: 컨텍스트 관리가 아니라 별개 정책이다. 끔이 바꾸는 것은 `trim_handoff`·`tool_result_payload` 이원화·원출력 비전달 세 가지뿐이다(조언 세션 결정).
- `obs/trace.py`·`api/ask.py`·`agents/skeleton.py`·기존 테스트 파일을 고치지 마라. 이유: 허용 목록 밖이다. trace에는 싣지 않고 결과 dict의 끔 전용 키로만 남긴다. 보고 시 이 선택을 알린다.
- `state`(LangGraph 상태)에 pydantic 객체를 넣거나 원출력을 상태 키로 늘리지 마라. 이유: 상태에는 dict·기본 타입만 넣는다(AGENTS.md). 원출력은 `raw_store` 클로저와 JSON 복사본만 쓴다.
