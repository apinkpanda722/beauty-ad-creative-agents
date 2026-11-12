# Step 5: llm-wrapper

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P1 collect-analyze-core"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드(step 0 산출물). 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/ADR.md` — ADR-005, ADR-015
- `/docs/CONTRACTS.md` — "Gemini API" 표와 주의(응답 본문 위치, 울타리, 오류 두 형태, 일일 한도 429)와 "LiteLLM SDK 경유" 절
- `/tests/fixtures/contracts/gemini_interactions_36flash_response_format_schema.json`, `gemini_interactions_36flash_youtube_offset.json`, `gemini_error_free_tier_daily_limit.json`, `gemini_error_overloaded.json`, `gemini_error_bad_key.json`, `litellm_gemini_files_flow.json` — 응답·오류 원본(수정 금지)
- `/src/beautyads/obs/ledger.py`, `/src/beautyads/settings.py` — step 1·4 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `pyproject.toml`, `uv.lock`, `src/beautyads/llm/__init__.py`, `src/beautyads/llm/gemini.py`, `src/beautyads/llm/errors.py`, `tests/test_llm.py`

열람 금지 경로: (없음)
수정 허용 경로: `pyproject.toml`, `uv.lock`, `src/beautyads/llm/**`, `tests/test_llm.py`

이 step은 LiteLLM SDK로 **Gemini Interactions API만** 부르는 래퍼를 만든다(OpenAI·Anthropic은 P5). `uv add litellm==1.103.3`으로 의존성을 추가한다(버전 고정). 패키지 설치는 이 명령만 허용되고, 해석된 `litellm`·`pydantic` 등 주요 버전을 완료 보고의 `summary`에 적는다. `llm/`은 `domain`, `settings`, `obs`만 import할 수 있고 `litellm`은 이 계층에서만 import한다. **테스트는 가짜 호출 함수와 원본 픽스처로만 하고 실제 호출은 하지 않는다.**

### 가격표는 로컬만 (`llm/__init__.py`)

**`llm/__init__.py`의 맨 처음에서, 어떤 `litellm` import보다 앞에** `os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")`를 실행한다(이후의 `from .gemini import ...` 같은 import는 모두 그 뒤에 온다). 이유: `import litellm`은 기본으로 GitHub에서 가격표를 내려받아 오며, 그러면 검증이 네트워크를 쓰고 가격이 실행마다 달라져 원장의 재현성이 깨진다. 번들된 가격표에 우리 모델(`gemini-3.6-flash` 등)의 단가가 있음을 확인했다.

### 공개 이름 (`llm/__init__.py`)

`analysis`는 `settings`와 `obs`를 import할 수 없으므로(AGENTS.md 계층 표), `llm/__init__.py`가 이 step의 공개 이름과 함께 아래를 **다시 내보낸다**: `ThinkingLevel`(`settings`에서), `CostCapExceeded`(`obs`에서). 이후 step은 이 이름들을 `beautyads.llm`에서 가져온다.

### 요청 구성과 응답 처리 — 시그니처

```python
class GeminiInteractionsFn(Protocol):
    def __call__(self, **kwargs: Any) -> Any: ...      # 기본 구현은 litellm.interactions.create

def text_part(text: str) -> dict
def video_part(uri: str, *, start_s: float | None = None, end_s: float | None = None, fps: float | None = None) -> dict
    # {"type": "video", "uri": uri} + (구간 지정이 있으면) "processing": {"type": "static", "start_offset": "0s", "end_offset": "3s", "fps": 1}
def json_schema_format(schema: Mapping[str, Any]) -> dict
    # {"type": "text", "mime_type": "application/json", "schema": schema}

class LlmResponseError(Exception):   # 속성: code ("NO_MODEL_OUTPUT" | "INVALID_JSON" | ...)
def extract_output_text(response: Any) -> str
def parse_json_output(text: str) -> Any

class UsageInfo(NamedTuple):
    model: str; input_tokens: int; output_tokens: int; thought_tokens: int; cached_tokens: int; cost_usd: float | None
def usage_from_response(response: Any) -> UsageInfo

class InteractionResult(NamedTuple):
    text: str; usage: UsageInfo; raw: dict
```

- 응답은 `dict`이거나 `model_dump()`를 가진 객체일 수 있다. 둘 다 받는다.
- **답은 `steps[]` 중 `type == "model_output"`인 항목의 `content[].text`에서 찾는다. 위치(`steps[0]`, `steps[-1]`)로 찾지 않는다.** 그런 항목이 없으면 `LlmResponseError("NO_MODEL_OUTPUT")`. LiteLLM이 추가하는 최상위 `agent`·`outputs` 키는 무시한다.
- `parse_json_output`은 ```` ```json ```` 울타리가 있는 경우와 없는 경우를 모두 처리하고, 파싱 실패는 `LlmResponseError("INVALID_JSON")`.
- `usage_from_response`: `usage.total_input_tokens`·`total_output_tokens`·`total_thought_tokens`·`total_cached_tokens`를 이름으로 읽고 **없으면 0**. `model`은 응답 최상위 `model`. 비용은 `_hidden_params["response_cost"]`(객체 속성 또는 딕셔너리 키)이고 없으면 `None`.

### 오류 분류와 호출

```python
class ErrorKind(StrEnum): RETRYABLE; DAILY_LIMIT; RATE_LIMIT; FATAL
class LlmCallError(Exception):        # 속성: kind, code, retry_after_s
class DailyLimitReached(LlmCallError) # 일일 한도: 재시도하지 않는다

def classify_error(exc: BaseException) -> ErrorKind
def retry_after_seconds(exc: BaseException) -> float | None

def gemini_interact(*, model: str, input_parts: Sequence[Mapping[str, Any]], thinking_level: ThinkingLevel,
                    purpose: str, ledger_path: Path, caps: Mapping[str, float],
                    response_format: Mapping[str, Any] | None = None, api_key: str | None = None,
                    timeout_s: float = 180.0, max_attempts: int = 3, backoff_s: Sequence[float] = (2.0, 5.0, 15.0),
                    interactions_fn: GeminiInteractionsFn | None = None,
                    sleep: Callable[[float], None] = time.sleep,
                    now: Callable[[], datetime] | None = None) -> InteractionResult
```

- **`thinking_level`은 기본값이 없는 필수 키워드 인자**다(빠뜨리면 `TypeError`). 기본값 `minimal`은 `settings`가 가진다. 요청에는 `generation_config={"thinking_level": thinking_level}`로 전달한다. `thinking_budget`은 서버가 400으로 거부하므로 절대 보내지 않는다. **`thinking_level == "default"`이면 `generation_config`에 `thinking_level` 키를 넣지 않는다**(서버 기본 thinking을 쓰는 비교군이다. `generation_config` 인자 자체를 빼도 된다).
- 요청 인자: `model=f"gemini/{model}"`, `input=list(input_parts)`, `generation_config=...`, `response_format`(있을 때), `api_key`(없으면 호출 시점에 `require_setting("GEMINI_API_KEY")`), `timeout=timeout_s`. (`litellm.interactions.create`의 시그니처에 `timeout`이 있음은 확인했다. 실제 동작은 첫 live에서 확인한다.)
- 분류 규칙(`classify_error`):
  - 503(`litellm.ServiceUnavailableError`·`status_code == 503`), 연결 실패(`litellm.APIConnectionError`), 시간 초과(`litellm.Timeout`) → `RETRYABLE`
  - 429(`litellm.RateLimitError`·`status_code == 429`): `retry_after_seconds`가 3600초 이상이거나 메시지에 `per day`·`daily`(대소문자 무시)가 있으면 `DAILY_LIMIT`, 아니면 `RATE_LIMIT`
  - 그 밖(400·401·403·404, `litellm.UnsupportedParamsError`, 알 수 없는 예외) → `FATAL`
- `retry_after_seconds`: 예외의 응답 헤더 `retry-after`(있을 때, 방어적으로 읽는다) 또는 메시지의 `Please retry in 4h19m15s` 형태(`(\d+)h`, `(\d+)m`, `(\d+)s` 조합)를 초로 바꾼다. 둘 다 없으면 `None`.
- 호출 흐름: ① 시도마다 **호출 직전에 `check_cap`**(`provider="gemini"`)을 부르고 `CostCapExceeded`는 그대로 올린다 ② 호출 ③ 성공하면 **즉시** `append_entry`로 원장에 한 줄 기록(공급사 `gemini`, `model`은 응답이 알려 준 실제 이름, `requested_model`, `purpose`, 토큰, 비용. `cost_usd`가 `None`이면 0.0과 `cost_source="missing"`) ④ 그 다음에 텍스트를 추출한다(추출 실패는 원장 기록 뒤에 `LlmResponseError`).
- 재시도는 `RETRYABLE`에만 한다(`max_attempts`까지, 시도 사이에 `backoff_s`의 값만큼 `sleep`). `DAILY_LIMIT`은 재시도하지 않고 `DailyLimitReached`(`retry_after_s` 포함)로, `RATE_LIMIT`·`FATAL`은 재시도하지 않고 `LlmCallError`로 올린다. 재시도가 끝까지 실패하면 `LlmCallError(kind=RETRYABLE, code="RETRIES_EXHAUSTED")`.
- 오류 메시지에서 `api_key` 문자열을 치환해 제거한 뒤 `LlmCallError`에 담는다(키가 로그·예외에 남지 않게).

### 반드시 있어야 하는 테스트 (`tests/test_llm.py`)

- **응답 처리**: 원본 `gemini_interactions_36flash_response_format_schema.json`의 `response`를 기반으로 하되, 텍스트를 테스트가 만든 값으로 **교체**해 쓴다(원본의 분류 값을 기대값으로 쓰지 않는다). 응답에서 `model_output`과 `thought`의 순서를 뒤집어도 같은 텍스트를 얻는다. 울타리 있는 텍스트·없는 텍스트 둘 다 파싱된다. `model_output`이 없으면 `NO_MODEL_OUTPUT`. LiteLLM 형태(`litellm_gemini_files_flow.json`의 `interactions`: `agent`·`outputs`가 `null`로 추가됨)도 같은 방식으로 읽힌다. `usage` 필드가 없으면 0.
- **오류 분류**: `litellm`의 예외 클래스를 테스트에서 직접 만들어(네트워크 없음) 분류를 확인한다. 일일 한도 메시지는 `gemini_error_free_tier_daily_limit.json`의 `response.error.message`를 `GeminiException - `와 JSON 본문 형태로 감싸 쓴다 → `DAILY_LIMIT`이고 `retry_after_seconds`가 15555에 가깝다. 같은 429에 한도 문구가 없으면 `RATE_LIMIT`. 503(과부하 원본 형태)은 `RETRYABLE`, 400·401·403·404와 `UnsupportedParamsError`는 `FATAL`.
- **호출 동작**(가짜 `interactions_fn`, 가짜 `sleep`): 503이 두 번 난 뒤 성공하면 3번 호출되고 `sleep`이 `backoff_s`의 앞 두 값으로 불린다. 일일 한도는 호출 1번에 `DailyLimitReached`, `sleep` 없음. `RATE_LIMIT`·`FATAL`도 재시도 없음. 가짜 호출이 받은 인자에서 `model == "gemini/<모델>"`, `generation_config == {"thinking_level": 입력값}`, `"thinking_budget"`가 어디에도 없음, `response_format`이 전달됨, `input`이 `input_parts`와 같음을 확인한다. `thinking_level`을 빼면 `TypeError`.
- **원장·상한**: 성공하면 `tmp_path` 원장에 한 줄이 추가되고 `model`이 응답의 모델 이름이며 `cost_source`가 맞다. 비용이 없는 응답은 `missing`. 상한을 넘은 상태에서는 가짜 호출이 **한 번도 불리지 않고** `CostCapExceeded`. 실패한 호출은 원장에 아무것도 쓰지 않는다.
- **키 비노출**: 가짜 호출이 `api_key`를 메시지에 담은 예외를 올려도 `LlmCallError`의 메시지에 그 문자열이 없다.
- **`default` 비교군**: `thinking_level="default"`로 부르면 가짜 호출이 받은 인자의 `generation_config`에 `thinking_level` 키가 없다(인자 자체가 없어도 된다). `minimal` 등 다른 값은 `{"thinking_level": 값}`으로 전달된다.
- **가격표 로컬 고정**: `import beautyads.llm` 뒤에 `os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"`(환경에 미리 다른 값이 없을 때)이고, 이 설정이 `llm/__init__.py`에서 **어떤 import 문보다 앞**에 있음을 `ast`로 단언한다(첫 import 문의 줄 번호가 설정 문장보다 크다). 번들 가격표(`litellm.model_cost`)에 키가 `gemini-3.6-flash`로 끝나는 항목이 있음을 확인한다.

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
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
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

- 일일 한도 429를 재시도하지 마라. `RATE_LIMIT`·`FATAL`도 재시도하지 않는다. 이유: 실측 중 고정 간격 재시도가 당일 한도를 소진시켰다(`docs/TROUBLESHOOTING_LOG.md` 2026-11-12). 재시도는 503·연결 실패·시간 초과에만 한다(A-FP-035).
- 응답에서 답을 `steps[0]`·`steps[-1]` 같은 위치로 찾지 마라. `type == "model_output"`로 찾는다. 이유: 첫 항목은 `thought`이고 위치는 응답마다 달라질 수 있다(FP-C02).
- `thinking_level`에 기본값을 두거나 `thinking_budget`을 보내지 마라. 이유: thought 토큰은 출력 단가로 청구되어 기본 thinking이면 1,500건 비용이 $12.8까지 오르고, `thinking_budget`은 400으로 거부된다(`docs/CONTRACTS.md`).
- OpenAI·Anthropic 호출, `reasoning_effort`·`temperature` 인자, 스트리밍 비용 계산을 만들지 마라. 이유: P5 `llm-chat-models` step의 범위이고 이 step은 Gemini 호출 경로만 검증한다.
- 원본 픽스처의 분류 값(`hook_type` 값)을 테스트 기대값으로 쓰지 마라. 응답의 구조만 원본에서 가져오고 텍스트는 테스트가 만든다. 이유: 모델이 고른 값을 굳히면 모델이 바뀔 때 깨진다(FP-C03).
- 지시한 `uv add` 외의 패키지를 설치하거나 `pyproject.toml`에 다른 의존성을 추가하지 마라. 이유: 의존성 변경은 `uv.lock`과 함께 검토 대상이고 계층 가드의 SDK 표가 모르는 패키지는 검증되지 않는다.
