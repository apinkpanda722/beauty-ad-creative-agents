# Step 1c: chat-param-compat

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표, CRITICAL 규칙(모델 호출은 `llm/` 한 곳, 비밀 값, 모델이 만든 값을 기대값으로 굳히지 않기)
- `/docs/CONTRACTS.md` — "LiteLLM SDK 경유 OpenAI·Anthropic·Gemini Files"와 "P5 step 0 시험" 절
- `/src/beautyads/llm/chat.py`, `/src/beautyads/llm/structured.py`, `/src/beautyads/llm/prices.py`, `/tests/test_llm_chat.py`, `/tests/test_llm_structured.py`, `/src/beautyads/agents/skeleton.py`, `/src/beautyads/api/app.py`, `/src/beautyads/api/sse.py`, `/src/beautyads/api/chat_client.py`, `/src/beautyads/eval/live_agent.py`, `/tests/test_api_chat.py`, `/tests/test_api_chat_client.py`, `/tests/test_live_agent.py`, `/tests/test_architecture.py` — step 0·0b·1·1b 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/llm/chat.py`, `src/beautyads/api/app.py`, `src/beautyads/api/chat_client.py`, `src/beautyads/eval/live_agent.py`, `tests/test_llm_chat.py`, `tests/test_llm_param_guard.py`(새 파일), `tests/test_api_chat.py`, `tests/test_api_chat_client.py`, `tests/test_live_agent.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/llm/chat.py`(OpenAI 모델의 `tool_choice` 호환 인자 추가에 한함, 다른 호출 모양과 기존 동작 불변), `src/beautyads/api/app.py`(`error` 이벤트의 `detail`·`error_code` 칸 추가에 한함, 기존 칸·이벤트 이름 불변), `src/beautyads/api/chat_client.py`(`error` 이벤트 칸 파싱 추가에 한함), `src/beautyads/eval/live_agent.py`(error 이벤트 출력 추가에 한함, `preflight()` 반환 코드 불변), `tests/test_llm_chat.py`(케이스 추가에 한함, 단언 약화 금지), `tests/test_llm_param_guard.py`, `tests/test_api_chat.py`(케이스 추가에 한함, 기존 `AGENT_INTERNAL_ERROR` 단언은 유지하고 새 칸 단언을 더한다), `tests/test_api_chat_client.py`(케이스 추가에 한함, 단언 약화 금지), `tests/test_live_agent.py`(케이스 추가에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

첫 `make live-agent`가 호출 전에 거부됐다. 원인은 오프라인으로 재현됐다(2026-11-18, 네트워크·모델 호출 없이 `litellm.get_optional_params`를 로컬에서 실행): `gpt-6-luna`·`gpt-6.1-terra`에 `tool_choice`(`auto`·`none`·`required`)를 보내면 `reasoning_effort` 값과 무관하게 `litellm.UnsupportedParamsError`("openai does not support parameters: ['tool_choice']")가 호출 전에 난다. `tools`만 보내기, `response_format` `json_schema` `strict`, 스트리밍(`stream_options`)은 통과하고 haiku·sonnet은 `tool_choice`를 포함해 모두 통과한다. `allowed_openai_params=["tool_choice"]`를 주면 같은 검사를 통과한다(litellm이 오류 메시지에서 안내한 방법). 이 step은 그 수정, 같은 종류의 문제를 호출 전에 잡는 오프라인 회귀 가드, 실패 원인이 출력에 보이게 하는 에러 가시성을 만든다. **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다(수정 전 코드로 새 가드 테스트가 luna·terra의 `tool_choice` 조합에서 실패함을 확인한 뒤 통과시킨다).**

**1. `llm/chat.py`**: OpenAI 모델(`gpt-6-luna`·`gpt-6.1-terra`)에서 `tool_choice`가 `None`이 아니면 `litellm.completion`(스트리밍 포함)에 `allowed_openai_params=["tool_choice"]`를 추가한다. `tool_choice`가 없으면 아무것도 추가하지 않는다. Anthropic 모델과 다른 호출 모양, 재시도·원장·가격표·`reasoning_effort` 규칙은 바꾸지 않는다. 이 인자가 실제 OpenAI API에서 받아들여지는지는 **미실측**이다(litellm의 정적 허용 목록이 모르는 모델이라 막은 것으로 보이는 것은 가설일 뿐이다). 사용자가 `make live-agent`를 다시 실행해 확인한다.

**2. 호출 전 검증 회귀 가드 `tests/test_llm_param_guard.py`**(네트워크·모델 호출 없음, 실제 `litellm.get_optional_params`는 순수 로컬 함수다): 가짜 `completion_fn`이 받은 인자를 그대로 모아, 그 인자(`api_key`·`timeout`·`messages` 같은 호출 비의존 항목은 빼고)를 `litellm.get_optional_params(model=..., custom_llm_provider=..., ...)`에 넣어 **예외가 없음**을 단언한다. `llm/__init__.py`가 `LITELLM_LOCAL_MODEL_COST_MAP=True`를 설정한 상태에서 돈다(이 설정과 `litellm==1.103.3`을 테스트 주석에 적는다). 모델 4종(`gpt-6-luna`, `gpt-6.1-terra`, `claude-haiku-5-5`, `claude-sonnet-5-5`) × 호출 모양을 모두 돌린다: 일반 호출, `reasoning_effort`가 있는 OpenAI 호출(`none`·`low`·`medium`·`high` 네 값 각각), `tools`만, `tools`+`tool_choice="auto"`, `tools`+`tool_choice="none"`, `response_format` `json_schema` `strict`, 스트리밍(`chat_stream`, `stream_options`), 도구 정의는 `agents.tools.tool_definitions()`의 실제 정의를 쓴다. 가드가 공허하게 통과하지 않도록 **검사한 조합 수가 0이면 실패**하고, 같은 가드가 `allowed_openai_params` 없이 보낸 `tool_choice`(OpenAI 모델)를 실제로 거부함을 대조 케이스로 단언한다(가드가 거부를 잡을 수 있음을 증명한다, 이 대조는 래퍼 밖에서 `litellm.get_optional_params`를 직접 부른다).
- 이후 step의 모델 호출 경로(6a 이미지 래퍼, 6b 구조화·도구 경로)도 같은 방식으로 이 가드에 조합을 추가하는 것을 요구한다(이 step은 현재 존재하는 `chat_complete`·`chat_stream`·`make_structured`가 만드는 호출 모양까지). `structured.py`가 `chat_complete`에 넘기는 인자(`JsonSchemaStructured`의 `response_format`, `ToolCallStructured`의 도구·`tool_choice="auto"`)도 조합에 넣는다.

**3. 에러 가시성**: `api/app.py`의 `event: error`를 `{"code": "AGENT_INTERNAL_ERROR", "detail": "<예외 클래스 이름>"}`로 보낸다(`code`는 그대로 유지). `detail`은 `type(exc).__name__` **한 가지뿐**이고 예외 메시지·인자·값·키·`__cause__` 문자열은 싣지 않는다. 예외에 문자열 `code` 속성이 있고 `^[A-Za-z0-9_:]{1,64}$`에 맞으면 `error_code` 칸으로 함께 싣는다(예: `LlmCallError`·`CostCapExceeded`·`CallCostLimit`). `api/chat_client.py`는 `error` 이벤트의 두 칸을 `ChatOutcome`에 담는다(없으면 `None`). `eval/live_agent.py`는 결과 출력에 error 이벤트가 있으면 `error_code`(있으면)와 `detail`(예외 클래스 이름)을 출력하고 종료 코드는 그대로(3)다. 출력에 키·값·메시지가 없다.

**반드시 있어야 하는 테스트**(가짜 그래프·합성 값):
- 래퍼: OpenAI 모델에서 `tool_choice`를 주면 가짜 `completion_fn`이 받은 인자에 `allowed_openai_params == ["tool_choice"]`가 있고, `tool_choice`가 없으면 그 키가 없다. Anthropic 모델은 어떤 경우에도 그 키가 없다. 스트리밍도 같다. 기존 `test_llm_chat.py`의 단언은 그대로 통과한다.
- 가드(위 2번 전체).
- 에러 가시성: 예외를 던지는 그래프(합성 비밀 문자열을 메시지·인자에 담은 예외, `litellm.UnsupportedParamsError`와 같은 이름의 합성 예외 클래스, 문자열 `code` 속성이 있는 합성 예외)에서 `error` 이벤트가 `code`·`detail`(클래스 이름)·`error_code`(있을 때만)만 갖고 **합성 비밀·메시지가 이벤트 본문 어디에도 없다**. `chat_client`가 두 칸을 파싱한다. `live_agent` 출력에 `detail`이 있고 키·메시지가 없으며 종료 코드가 3이다. 정상 경로에는 새 칸이 없다.
- `tests/test_architecture.py`가 통과한다(`litellm`은 `llm`만, 가드 테스트는 `tests/`라 대상이 아니다).

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

- `tool_choice`를 OpenAI 모델 호출에서 빼거나 `skeleton.py`의 호출 모양을 바꿔 우회하지 마라. 이유: 마지막 호출에서 모델의 도구 재호출을 막으려면 `tool_choice="none"`이 필요하고, 원인은 호출 모양이 아니라 litellm의 호출 전 허용 목록이다. 이 step은 `llm/chat.py`만 고친다.
- 예외 메시지·인자·`__cause__`·키를 `error` 이벤트나 `live_agent` 출력에 넣지 마라. 이유: 모델·드라이버 진단에 키와 값이 들어갈 수 있다(AGENTS.md 비밀 값). 클래스 이름과 안전한 형식의 `code`만 허용한다.
- 가드 테스트에서 `get_optional_params`를 가짜로 바꾸지 마라. 이유: 가짜 응답과 코드가 같은 가정을 공유하면 이번 결함이 다시 통과한다(B-FP-020). 실제 litellm 함수를 쓰고 조합 수 0을 실패로 처리한다(B-FP-069).
- `allowed_openai_params`에 `tool_choice` 외 값을 넣거나 `drop_params`를 켜지 마라. 이유: 모르는 파라미터를 조용히 버리면 같은 종류의 결함이 가려진다. 필요한 값만 명시한다.
- `preflight()` 반환 코드와 기존 `AGENT_INTERNAL_ERROR` 단언을 바꾸거나 약화하지 마라. 이유: step 1·1b 테스트가 코드 문자열을 단언한다. 새 칸은 추가만 한다.
