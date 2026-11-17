# Step 0b: structured-output

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표, CRITICAL 규칙(모델이 만든 값을 기대값으로 굳히지 않기, 형식은 스키마 검증)
- `/docs/CONTRACTS.md` — "P5 step 0 시험(2026-11-17)" 절
- `/docs/ARCHITECTURE.md` — "요청 처리 공통 장치"(프롬프트 캐시), "컨텍스트 관리"
- `/tests/fixtures/contracts/litellm_p5_sonnet_structured.json`, `/tests/fixtures/contracts/litellm_p5_sonnet_native.json`, `/tests/fixtures/contracts/litellm_openai_anthropic_probe.json` — 응답 원본(읽기 전용)
- `/src/beautyads/llm/chat.py`, `/src/beautyads/llm/prices.py`, `/src/beautyads/llm/errors.py`, `/tests/test_llm_chat.py` — step 0 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/llm/structured.py`(새 파일), `src/beautyads/llm/__init__.py`, `tests/test_llm_structured.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/llm/structured.py`, `src/beautyads/llm/__init__.py`(export 추가에 한함), `tests/test_llm_structured.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

스키마 검증된 구조화 출력을 **어댑터 인터페이스 뒤에** 둔다. 호출부는 방식이 바뀌어도 변하지 않는다. 이 step은 모델·네트워크를 부르지 않는다. **이 step 안에서는 실제 접속·실행을 하지 않는다.**

**인터페이스 `llm/structured.py`**: `StructuredSpec`(`name: str`, `description: str`, `schema: dict`(JSON 스키마), `validate: Callable[[dict], Any]`(pydantic `model_validate`처럼 검증하고 실패하면 예외, 반환값을 결과로 쓴다)), `StructuredFailure`(StrEnum: `PARSE_FAILED`, `SCHEMA_VIOLATION`, `TOOL_NOT_CALLED`), `StructuredResult`(`ok: bool`, `value: Any | None`, `failure: StructuredFailure | None`, `attempts: int`(1 또는 2), `cost_usd`, `calls: list[ChatResult 요약]`), `StructuredGenerator`(Protocol: `generate(spec, *, messages, purpose, ledger_path, caps, reasoning_effort, ...) -> StructuredResult`. `reasoning_effort`는 step 0 규칙 그대로다: OpenAI 모델은 필수 값, Anthropic 모델은 `None`만), `StructuredStats`(`calls`, `failed_after_retry`, 실패 종류별 첫 시도 실패 수, 속성 `failure_rate`(재요청 뒤에도 실패한 비율, 호출 0이면 `None`), 두 `StructuredStats`를 합치는 `merge`). `StructuredStats`의 독스트링에 "호출 수가 적으면(20호출 미만) 실패율이 우연일 수 있어 판단 근거로 쓰지 않는다"를 한 줄로 적는다. **재요청은 최대 1회**다: 첫 시도가 `PARSE_FAILED`·`SCHEMA_VIOLATION`·`TOOL_NOT_CALLED`이면 실패 사유를 덧붙여 한 번 더 요청하고, 그래도 실패면 `ok=False`와 마지막 실패 종류를 돌려준다(예외를 던지지 않는다). 호출 실패(`LlmCallError`·`CostCapExceeded` 등 `llm` 예외)는 구조화 실패가 아니므로 그대로 올라간다.

**구현 셋**(같은 인터페이스):
1. **`ToolCallStructured`(기본, 방식 a)**: Anthropic용. 스키마를 단일 도구 `spec.name`으로 보내고 `tool_choice="auto"`에 지시문("반드시 그 도구를 호출해 제출한다")을 붙인다. **`tool_choice`에 `tool`·`any`를 쓰지 않는다**(sonnet이 400으로 거부했다). 도구 호출이 없으면 `TOOL_NOT_CALLED`, `arguments_error`는 `PARSE_FAILED`, 검증 실패는 `SCHEMA_VIOLATION`.
2. **`InstructionJsonStructured`(대체, 방식 d)**: 지시문에 스키마를 적고 본문 JSON을 읽는다(코드 울타리가 있어도 없어도 처리, FP-C02). 파싱 실패는 `PARSE_FAILED`, 검증 실패는 `SCHEMA_VIOLATION`. 도구를 쓰지 않으므로 `TOOL_NOT_CALLED`가 없다.
3. **`NativeAnthropicStructured`(방식 b)**: `litellm.anthropic.messages.acreate(..., output_config={"format": {"type": "json_schema", "schema": ...}})`를 쓴다. **비동기 경로뿐이다**(`create`는 동기 호출을 지원하지 않고 `completion`의 `extra_body`는 Anthropic이 400으로 거부했다. 원본 `litellm_p5_sonnet_native.json`). 동기 호출부와 맞추는 방법: 내부에서 `run_coroutine_sync(coro)` 헬퍼를 쓴다. 실행 중인 이벤트 루프가 없으면 `asyncio.run`을, 있으면 별도 스레드에서 새 루프로 돌려 결과를 기다린다(루프 안에서 `asyncio.run`을 부르지 않는다). 응답은 `content` 블록 중 `type == "text"`를 이름으로 찾아 JSON으로 읽는다(위치로 찾지 않는다). **호출 직전에 step 0의 `precheck_call`(가격표 확인과 공급사 누적액 상한 검사)을 통과해야 하고**, 재시도는 `classify_error`가 `RETRYABLE`로 분류한 503·연결 실패·시간 초과에만 한다(`chat_complete`와 같은 규칙, 시도마다 `precheck_call`). 비용은 `usage.input_tokens`·`output_tokens`로 step 0의 `record_usage`가 `resolve_cost`를 거쳐 원장에 기록한다(`reasoning_effort`는 `None`). **`output_config.format`을 바꾸면 그 대화의 프롬프트 캐시가 무효화된다**(공식 문서). 이를 `StructuredResult`에 `cache_note`로 남기지 않고 문서 주석 한 줄로만 적는다.
- **OpenAI(luna·terra)**: `response_format={"type": "json_schema", "json_schema": {"strict": true, ...}}`(실측 동작)를 `chat_complete`로 보내는 `JsonSchemaStructured`를 같은 인터페이스로 둔다. 파싱·검증 실패 처리와 재요청은 위와 같다.
- 어떤 구현을 쓸지는 호출부가 고르지 않고 `make_structured(model, *, style=...)` 팩토리 하나가 고른다. 기본은 모델의 기본 방식(Anthropic은 (a), OpenAI는 `JsonSchemaStructured`)이고 `style`로 (d)·(b)를 명시할 수 있다. **기본 방식을 (b)로 바꾸는 판단은 step 6 개발 단계의 사전 등록 비교로 한다**(이 step에서는 바꾸지 않는다).
- **전환 조건(설계 제안, 승인 필요)**: 개발 중 한 모델·방식의 `StructuredStats.failure_rate`가 20호출 이상에서 10% 이상이면 (d)로 전환을 검토한다. 이 숫자는 이 step에서는 상수로 코드에 박지 않고 `StructuredStats`가 값을 낼 뿐이다.

**반드시 있어야 하는 테스트**(가짜 `chat_complete`·가짜 `acreate`, 원본 픽스처에서 만든 응답, 합성 스키마. 모델이 만든 값을 기대값으로 굳히지 않는다. 형식과 코드가 하는 일만 검사한다):
- 첫 시도 성공이면 `attempts == 1`, 실패 뒤 성공이면 `attempts == 2`(요청에 실패 사유가 덧붙는다), 두 번 실패면 `ok=False`·`failure`가 마지막 종류, 예외 없음. 세 가지 실패 종류가 각각 맞는 상황(깨진 JSON, 스키마 위반, 도구 미호출)에서 나온다. `LlmCallError`는 그대로 올라온다.
- (a): 요청에 `tool_choice == "auto"`이고 `tool`·`any`가 어디에도 없다. 원본 `a_tools_auto` 응답에서 `ToolCall.arguments`가 검증을 통과한다. 도구 호출이 없는 응답은 `TOOL_NOT_CALLED`.
- (d): 코드 울타리가 있는 본문·없는 본문 모두 읽힌다. 원본 `d_instruction_only` 응답이 읽힌다.
- (b): 가짜 `acreate`가 받은 인자에 `output_config.format.type == "json_schema"`가 있다. 원본 `b2_native_acreate` 응답의 `content` 블록(`type == "text"`)에서 값이 읽히고 블록 순서가 바뀌어도 같은 결과다. 이벤트 루프가 **없는** 동기 호출과 **실행 중인 루프 안에서의** 호출(예: `asyncio.run` 안의 `asyncio.to_thread` 아님, 실제 `async def` 테스트에서 동기 `generate` 호출) 모두 같은 결과를 내고 데드락 없이 끝난다(timeout을 둔다).
- `StructuredStats`: 합치기(`merge`)가 합을 낸다, 호출 0이면 `failure_rate`는 `None`(0.0이 아니다), 첫 시도 실패 뒤 재요청 성공은 `failed_after_retry`에 세지 않고 첫 시도 실패 종류에는 센다.
- `make_structured`: 기본 방식이 Anthropic은 `ToolCallStructured`, OpenAI는 `JsonSchemaStructured`이고, `style="instruction"`·`"native"`가 각각 (d)·(b)를 돌려준다. 알 수 없는 조합은 `ValueError`. 모델별 `reasoning_effort` 규칙(step 0)은 그대로 적용된다.
- (b)의 사전 점검: 가격표에 없는 모델은 호출 없이 `PRICE_UNKNOWN`, 공급사 누적액이 상한 이상이면 호출 없이 `CostCapExceeded`(가짜 `acreate`가 불리지 않는다). 재시도는 503·연결 실패·시간 초과에만 하고 시도마다 상한을 다시 검사한다. 원장에 `price_table`로 기록된다.
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

- `tool_choice`에 `tool`·`any`를 쓰지 마라. 이유: sonnet이 400으로 거부했다(원본 `litellm_p5_sonnet_structured.json`, FP-C01).
- 응답의 답을 `[0]`·`[-1]`로 찾지 마라. `content` 블록은 `type`으로, 도구 호출은 이름으로 찾는다. 이유: FP-C02.
- `asyncio.run`을 실행 중인 루프 안에서 부르지 마라. 이유: `RuntimeError`가 나고 FastAPI 안에서 호출되기 때문이다. 루프가 있으면 별도 스레드로 돌린다.
- 테스트 기대값에 모델이 만든 문장·값을 굳히지 마라. 이유: 정확도는 평가에서 잰다(FP-C03). 스키마 위반·파싱 실패는 합성으로 만든다.
- 재요청을 두 번 이상 하거나 `LlmCallError`를 구조화 실패로 바꾸지 마라. 이유: 재시도 규칙은 `llm` 래퍼가 정하고 중복 과금을 부른다(A-FP-035).
