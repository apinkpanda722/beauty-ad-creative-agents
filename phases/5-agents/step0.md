# Step 0: llm-chat-models

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`llm`은 `domain`·`settings`·`obs`), CRITICAL 규칙(temperature, reasoning_effort, 재시도, 공급사별 상한, 비밀 값)
- `/docs/ADR.md` — ADR-005, ADR-015
- `/docs/COST_ESTIMATE.md` — 단가와 상한
- `/docs/CONTRACTS.md` — "LiteLLM SDK 경유 OpenAI·Anthropic·Gemini Files"와 "P5 step 0 시험(2026-11-17)" 절(실측 원본 경로가 있다)
- `/tests/fixtures/contracts/README.md`, `/tests/fixtures/contracts/litellm_openai_anthropic_probe.json`, `/tests/fixtures/contracts/litellm_reasoning_effort_and_stream_cost.json`, `/tests/fixtures/contracts/litellm_temperature_with_reasoning_none.json`, `/tests/fixtures/contracts/litellm_p5_chat_models.json`, `/tests/fixtures/contracts/litellm_p5_sonnet_structured.json` — 응답 원본(읽기 전용)
- `/tests/test_architecture.py`, `/src/beautyads/llm/gemini.py`, `/src/beautyads/llm/errors.py`, `/src/beautyads/llm/__init__.py`, `/src/beautyads/obs/ledger.py`, `/src/beautyads/settings.py`, `/tests/test_llm.py`, `/tests/test_ledger.py`, `/tests/test_settings.py` — Gemini 래퍼의 재시도·원장·상한 방식을 그대로 따른다

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/llm/prices.py`(새 파일), `src/beautyads/llm/chat.py`(새 파일), `src/beautyads/llm/__init__.py`, `src/beautyads/obs/ledger.py`, `src/beautyads/obs/__init__.py`, `src/beautyads/settings.py`, `.env.example`, `tests/test_llm_prices.py`(새 파일), `tests/test_llm_chat.py`(새 파일), `tests/test_ledger.py`, `tests/test_settings.py`, `tests/test_llm.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/llm/prices.py`, `src/beautyads/llm/chat.py`, `src/beautyads/llm/__init__.py`(export 추가에 한함, 기존 export 불변), `src/beautyads/obs/ledger.py`(`cost_source`에 `price_table` 값 추가, `LedgerEntry`에 선택 필드 `reasoning_effort: str | None = None` 추가, 목적 접두어 합계·상한 함수 추가에 한함. 기존 동작·단언 불변, 기본값 `None`이라 이미 쓴 장부 행이 그대로 읽혀야 한다), `src/beautyads/obs/__init__.py`(export 추가에 한함), `src/beautyads/settings.py`(`purpose_caps_usd`와 `BEAUTYADS_CAP_IMAGE_USD` 읽기 추가에 한함, 기존 동작 불변), `.env.example`(변수 이름 한 줄 추가에 한함), `tests/test_llm_prices.py`, `tests/test_llm_chat.py`, `tests/test_ledger.py`(케이스 추가에 한함, 단언 약화 금지), `tests/test_settings.py`(케이스 추가에 한함, 단언 약화 금지), `tests/test_llm.py`(`llm.__all__`을 단언하는 줄이 있으면 새 export를 반영하는 갱신에 한함, 그 외 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

`llm/`에 OpenAI·Anthropic 채팅 호출 경로, 가격표 비용 계산, 목적별 상한을 추가한다. **기존 Gemini·luna 경로의 동작은 바꾸지 않는다.** 이 step은 모델·네트워크를 부르지 않는다. 모델이 달라도 응답의 모양은 `tests/fixtures/contracts/`의 실측 원본(위 읽을 파일)에서만 가정한다. **이 step 안에서는 실제 접속·실행을 하지 않는다.**

**1. 가격표 `llm/prices.py`**(공식 가격 페이지, 2026-11-17 확인, 100만 토큰당 USD): `ModelPrice`(frozen: `model`, `provider`, `input`, `cache_read`, `cache_write_short`, `cache_write_long`, `output`, `source_url`, `tier_threshold_tokens: int | None`, `tier_over`(임계 초과 구간의 같은 다섯 값)). 상수 `PRICE_TABLE_CHECKED_ON = "2026-11-17"`.
- `gpt-6.1-terra` 입력 1.00 / 캐시 읽기 0.05 / 캐시 쓰기 30분 1.25·12시간 2.50 / 출력 5.00. `gpt-6-luna` 0.10 / 0.01 / 0.125·0.25 / 0.50. `claude-sonnet-5-5` 2.00 / 0.10 / 5분 2.50·1시간 4.00 / 10.00. `claude-haiku-5-5`는 **입력 100,000토큰 이하** 0.10 / 0.01 / 0.125·0.20 / 0.50, **초과** 0.50 / 0.05 / 0.625·1.00 / 2.50(임계는 그 호출의 입력 토큰 수로 판단한다). 출처 주소는 `https://developers.openai.com/api/docs/pricing`과 `https://platform.claude.com/docs/en/about-claude/pricing`.
- `price_for(model: str) -> ModelPrice | None`(공급사 접두어 `openai/`·`anthropic/`는 떼고 찾는다), `compute_cost(model, *, input_tokens, output_tokens, cache_read_tokens=0, cache_write_tokens=0, cache_write_long=False) -> float`(캐시 토큰은 입력과 **겹치지 않게** 분리해 센다. OpenAI의 `cached_tokens`는 `prompt_tokens`의 부분집합이므로 호출부가 `input_tokens = prompt_tokens - cached_tokens`로 넘긴다. Anthropic은 `cache_read_input_tokens`·`cache_creation_input_tokens`가 별도 필드이므로 그대로 넘긴다. 이 해석은 원본 `litellm_openai_anthropic_probe.json`의 `cache_*` 항목으로 검증한다), `resolve_cost(model, *, response_cost, usage) -> tuple[float, Literal["response_cost", "price_table"]]`: `response_cost`가 `None`이거나 0이하이면 가격표로 계산해 `price_table`로, 양수이면 `response_cost`를 그대로 쓰고, 가격표에도 없으면 `PriceUnknown`(코드 `PRICE_UNKNOWN`)을 올린다. **입력·출력 토큰이 둘 다 0인 호출은 0.0이 정상이므로 `PriceUnknown`이 아니라 `response_cost`로 0을 기록한다.**

**2. 원장·설정(`obs`, `settings`)**: `LedgerEntry.cost_source`에 `"price_table"`을 추가한다(기존 세 값 불변). `LedgerEntry`에 선택 필드 `reasoning_effort: str | None = None`을 추가한다(AGENTS.md CRITICAL: 에이전트마다 `reasoning_effort`를 명시하고 **비용 원장에 기록한다**). 문자열이 아닌 값(정수·목록 등)은 거부한다. 채팅 래퍼는 OpenAI 호출에서 사용한 값(`none`·`low`·`medium`·`high`)을 기록하고 Anthropic·Gemini 호출은 `None`이다. `purpose_total(path, prefix) -> float`과 `check_purpose_cap(path, prefix, cap, *, additional_usd=0.0)`(합계 + 추가분이 상한 이상이면 `CostCapExceeded`, 코드 `COST_CAP:purpose:<prefix>`)를 추가한다. `purpose`가 `prefix` 자체이거나 `prefix + "-"`로 시작할 때만 합산한다(`image`는 `image-probe`·`image-plan`과 맞고 `imagery`와는 맞지 않는다). `Settings.purpose_caps_usd: dict[str, float]` 기본 `{"image": 3.5}`, 환경 변수 `BEAUTYADS_CAP_IMAGE_USD`로 덮을 수 있고 음수·비수는 `InvalidSetting`(공급사 상한과 같은 읽기 방식). 이미지 호출 래퍼는 step 6에서 만든다(이 step은 함수와 설정까지).

**3. 채팅 래퍼 `llm/chat.py`**: `chat_complete(*, model: str, messages, purpose: str, ledger_path, caps, reasoning_effort, tools=None, tool_choice=None, response_format=None, max_tokens=None, api_key=None, timeout_s=120.0, max_attempts=3, backoff_s=(2.0, 5.0, 15.0), completion_fn=None, sleep=time.sleep, now=None) -> ChatResult`. `model`은 공급사 접두어 없이 `gpt-6-luna`·`gpt-6.1-terra`·`claude-haiku-5-5`·`claude-sonnet-5-5` 중 하나이고(그 밖이면 `ValueError`) 공급사는 이름에서 정한다.
- **`temperature` 인자가 없다**(지정할 방법이 없다). **`reasoning_effort`는 필수 키워드**다: OpenAI 모델(luna·terra)은 `none`·`low`·`medium`·`high` 중 하나여야 하고(`minimal`·미지정은 `ValueError`) 그대로 전달한다. **Anthropic 모델(haiku·sonnet)은 `None`만 허용**하고 요청에 `reasoning_effort`·`thinking`을 보내지 않는다(sonnet의 thinking은 효과가 확인되지 않았다. 다른 값을 주면 `ValueError`).
- 호출 직전에 (1) `price_for(model)`이 없으면 호출 없이 `PRICE_UNKNOWN`(`LlmCallError`), (2) `check_cap(ledger_path, provider, caps)`를 통과해야 한다(Gemini 래퍼와 같은 방식, 시도마다). `api_key`는 `require_setting`으로 읽는다(`OPENAI_API_KEY`·`ANTHROPIC_API_KEY`).
- 재시도는 `classify_error`가 `RETRYABLE`로 분류한 503·연결 실패·시간 초과에만 한다(Gemini 래퍼와 같은 규칙, 일일 한도 429·크레딧 소진은 재시도하지 않고 `DailyLimitReached`). 재시도마다 상한을 다시 검사한다. 전송 후 실패를 재시도해 이중 과금하지 않는다.
- 비용: 응답 `usage`의 필드를 **이름으로** 읽고 없으면 0으로 본다. `resolve_cost`로 계산해 원장에 `cost_source`와 함께 기록한다(`response_cost`가 0.0이면 가격표). 원장에는 입력·출력·캐시 읽기 토큰을 적는다. 응답 전문·이미지·키는 원장에 쓰지 않는다.
- `ChatResult`: `text: str | None`, `tool_calls: list[ToolCall]`, `finish_reason`, `usage`, `cost_usd`, `cost_source`, `raw: dict`. `ToolCall`(`id`, `name`, `arguments: dict | None`, `arguments_error: str | None`): **도구 호출 `arguments`는 JSON 문자열이라 파싱 실패를 `arguments_error`로 돌려주고 예외를 던지지 않는다**(`arguments`는 `None`). 답은 항목의 이름·타입으로 찾고 위치(`[0]`)로 찾지 않는 헬퍼를 쓴다(`choices`가 비면 구조화 실패).
- `chat_stream(...)`: 같은 인자로 청크를 모아 돌려준다. 스트리밍 응답은 `response_cost`가 `None`이므로 `stream_chunk_builder`로 합친 응답의 usage에서 `resolve_cost`로 계산한다. `stream_options={"include_usage": True}`를 보낸다.
- Anthropic 캐시: `cache_system_block(text) -> dict`(시스템 블록에 `cache_control: {"type": "ephemeral"}`를 붙이는 헬퍼, 실측된 형태).
- **공용 헬퍼**(0b의 비동기 네이티브 경로가 같은 규칙을 쓰도록 `llm/chat.py`에서 공개한다): `precheck_call(model, *, ledger_path, caps)`(가격표 확인 → 없으면 `PRICE_UNKNOWN`, 공급사 누적액 상한 검사 → `CostCapExceeded`)와 `record_usage(*, model, purpose, ledger_path, usage, response_cost, reasoning_effort, now)`(`resolve_cost`로 비용을 정해 원장에 한 줄 기록하고 `(cost, source)`를 돌려준다)를 `chat_complete`도 내부에서 쓴다. 이 둘의 동작은 `chat_complete` 테스트가 함께 검증한다.
- `llm/__init__.py`에 새 이름을 export한다. `litellm`을 import하는 곳은 `llm/`뿐이다.

**반드시 있어야 하는 테스트**(가짜 `completion_fn`, 원본 픽스처를 읽어 만든 응답, 합성 입력만. 모델이 만든 문장·값을 기대값으로 굳히지 않는다):
- 가격표: 모든 모델에 `source_url`이 있고 `PRICE_TABLE_CHECKED_ON`이 있다. `compute_cost`가 손계산과 같다(합성 토큰 수, 정확 일치). **원본 `litellm_openai_anthropic_probe.json`에서 LiteLLM이 양수 `response_cost`를 돌려준 luna·haiku 항목**은 같은 usage로 `compute_cost`가 `response_cost`와 상대 오차 1e-6 안에서 같다(캐시 읽기·쓰기 포함, 이 비교가 가격표와 캐시 토큰 해석을 함께 검증한다). haiku는 입력 100k를 넘는 합성 호출에서 상위 구간 단가를 쓴다. 가격표에 없는 모델은 `PRICE_UNKNOWN`이다.
- `resolve_cost`: 양수 `response_cost`는 그대로, 0.0·None은 가격표, 가격표에도 없으면 `PRICE_UNKNOWN`, 토큰 0인 호출은 0.0이다. 원본 `litellm_p5_chat_models.json`의 terra·haiku·sonnet 호출(`response_cost` 0.0)이 `price_table`로 양수 비용이 된다.
- 원장·설정: `price_table` 항목이 기록·읽기되고 기존 세 값도 그대로다. `reasoning_effort` 필드가 없는 기존 행(JSON 한 줄)이 그대로 읽힌다, 새 행에 쓴 값이 그대로 읽힌다, 문자열이 아닌 값은 거부된다. 채팅 래퍼가 OpenAI 호출의 원장 행에 `reasoning_effort`를 기록하고 Anthropic 호출의 행은 `None`이다. 목적 접두어 합계가 `image`·`image-*`만 합친다(`imagery`는 제외), 상한 직전·이상 경계, 0건이면 합계 0. `BEAUTYADS_CAP_IMAGE_USD`가 기본값을 덮고 빈 문자열·공백은 기본값을 덮지 않으며 음수·비수는 `InvalidSetting`.
- 채팅 래퍼: `temperature` 인자가 시그니처에 없다. luna·terra의 `reasoning_effort` 누락·`minimal`·알 수 없는 값은 호출 없이 `ValueError`. haiku·sonnet에 `reasoning_effort`·`thinking` 값을 주면 `ValueError`이고 `None`이면 요청 인자에 두 키가 없다. 가격표에 없는 모델은 호출 전에 거부된다. 공급사 누적액이 상한 이상이면 호출 없이 `CostCapExceeded`.
- 재시도: 503·연결 실패·시간 초과는 재시도해 성공하고 시도마다 상한을 검사한다. 일일 한도 429·크레딧 소진은 재시도 없이 `DailyLimitReached`, 인증 오류(401)·잘못된 모델(404)은 재시도 없이 `FATAL`. 재시도 소진은 `RETRIES_EXHAUSTED`. 실패한 호출은 원장에 기록되지 않는다.
- 도구 호출: 원본 `tool_*` 항목에서 `ToolCall`이 나오고, `arguments`가 깨진 JSON이면 `arguments_error`가 채워지고 예외가 없다. `choices`가 비거나 `tool_calls`가 없는 응답도 예외 없이 `ChatResult`가 나온다.
- 스트리밍: 청크 목록에서 합쳐진 usage로 비용이 계산되고 `response_cost`가 `None`이어도 `price_table`로 기록된다(원본 `litellm_reasoning_effort_and_stream_cost.json`의 스트림 항목).
- `cache_system_block`의 모양이 원본 `cache_*` 요청과 같다. `tests/test_architecture.py`가 통과한다(`litellm`은 `llm`만, `llm`은 `domain`·`settings`·`obs`만).

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

- `temperature`를 지정하거나 인자로 받지 마라. 이유: 추론이 켜진 luna와 haiku는 `UnsupportedParamsError`로 호출 전 거부된다(AGENTS.md, CONTRACTS temperature 항목).
- haiku·sonnet에 `reasoning_effort`·`thinking`을 보내지 마라. 이유: sonnet은 수락하지만 효과가 확인되지 않았고(thinking 블록·추론 토큰 0), 추론 비용을 가정하지 않는다(P5 결정).
- `response_cost`가 0.0인 값을 그대로 원장에 적지 마라. 이유: terra·haiku·sonnet은 litellm 단가가 없어 0.0이 오고 공급사 상한이 걸리지 않는다(2026-11-17 시험, TROUBLESHOOTING_LOG). 토큰이 0인 호출만 0.0이 정상이다.
- 가격표 숫자를 이 파일 밖 문서·추정에서 가져오지 마라. 이유: 위 값은 공식 페이지 2026-11-17 확인값이다. 값이 바뀌면 확인 날짜와 출처를 함께 고친다(FP-C06).
- 응답 전문·base64·`thought_signatures`·키를 원장·로그·예외 메시지에 넣지 마라. 이유: 서명 값 하나가 약 82만 자였고 키 노출 금지다(AGENTS.md).
- 재시도를 429·인증 오류·잘못된 모델에 하거나 모든 예외를 재시도하지 마라. 이유: 전송 후 실패를 재시도하면 이중 과금한다(A-FP-035, FP-C07).
- `llm/gemini.py`·`llm/files.py`·`llm/errors.py`의 동작과 기존 테스트 단언을 바꾸지 마라. 이유: Gemini 분석 경로가 이미 live에서 쓰였다.
