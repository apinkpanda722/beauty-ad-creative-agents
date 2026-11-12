# Step 7: analysis-hook

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P1 collect-analyze-core"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드(step 0 산출물). 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/TAXONOMY.md` — "1. 훅 유형" 절(판정 기준 표와 우선순위, 값 목록은 초안 v0)
- `/docs/CONTRACTS.md` — "Gemini API" 표의 구조화 출력·구간 지정·응답 위치
- `/docs/ARCHITECTURE.md` — "데이터 흐름" 오프라인 4~6번
- `/src/beautyads/domain/`, `/src/beautyads/llm/`, `/src/beautyads/settings.py` — step 1·5 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/analysis/__init__.py`, `src/beautyads/analysis/hook.py`, `src/beautyads/analysis/prompts.py`, `src/beautyads/analysis/batch.py`, `tests/test_analysis.py`

열람 금지 경로: (없음)
수정 허용 경로: `src/beautyads/analysis/**`, `tests/test_analysis.py`

이 step은 소재의 **첫 3초 훅 유형**을 Gemini로 분류하는 분석 함수와 단순 배치 실행기를 만든다(분류 축은 `hook_type` 하나뿐이다). `analysis/`는 `domain`과 `llm`만 import할 수 있다. 모델 호출은 step 5의 `gemini_interact`를 통해서만 한다. `ThinkingLevel`·`CostCapExceeded`·`DailyLimitReached`·`LlmCallError`·`InteractionResult` 등은 `beautyads.llm`에서 가져온다(`analysis`는 `settings`·`obs`를 import하지 못한다). **테스트는 가짜 `interact` 함수와 메모리 저장소로만 하고 실제 호출은 하지 않는다.**

### 선별과 구간 (`hook.py`)

```python
HOOK_WINDOW_S = 3.0

def hook_response_schema() -> dict
    # HookResult / HookType 에서 만든 JSON schema: {"type": "object", "properties": {"hook_type": {"type": "string", "enum": [HookType 멤버 값들]}}, "required": ["hook_type"]}

class Skip(NamedTuple): key: CreativeKey; reason: str          # "NOT_ANALYZABLE" | "TOO_LONG"
class Selection(NamedTuple): eligible: list[Creative]; skipped: list[Skip]
def select_for_analysis(creatives: Sequence[Creative], *, video_length_cut_s: float) -> Selection
def hook_window(duration_s: float | None, *, window_max_s: float, hook_window_s: float = HOOK_WINDOW_S) -> tuple[float, float]
```

- `select_for_analysis`: 모델을 부르기 전의 **방어용** 선별이다. 길이 컷은 수집 시점의 `analyzable` 판정(step 6)이 정하는 유일한 지점이고, 여기서는 같은 설정값으로 다시 확인할 뿐이다. `is_analyzable`이 아니면 `NOT_ANALYZABLE`, `duration_s`를 알고 `video_length_cut_s`를 넘으면 `TOO_LONG`로 제외한다. `duration_s`가 `None`이면 제외하지 않는다. 입력 순서를 유지한다.
- `hook_window`: `(0.0, min(hook_window_s, window_max_s, duration_s가 있으면 duration_s))`. 14분 영상 전체를 분석하면 79,435 입력 토큰이지만 60초 구간은 5,461 토큰이므로 **구간 지정은 항상 한다**(영상 전체를 요청하지 않는다).
- 값 목록(`enum`)은 `HookType`에서 만든다. 프롬프트와 스키마 어디에도 값을 따로 적지 않는다.

### 프롬프트 (`prompts.py`)

- `HOOK_PROMPT_VERSION = "hook-v0"`와 프롬프트를 만드는 함수 `build_hook_prompt(creative) -> str`. 내용: 영상의 **첫 구간만** 보고 `HookType` 값 중 하나를 고르게 한다. TAXONOMY의 훅 유형 판정 기준(첫 3초 안에 관찰되는 것)과 겹칠 때의 우선순위를 담고, 소재의 제목·캡션을 참고 정보로 붙인다. 판정 기준 문구는 `docs/TAXONOMY.md`의 표현을 따른다. 출력은 JSON 하나뿐이어야 한다고 요구하되 형식 보장은 스키마(`response_format`)가 한다.

### 분석과 배치

```python
class AnalysisOutcome(BaseModel):
    key: CreativeKey; status: JobStatus; hook: HookResult | None; raw_output: str | None
    model: str | None; error_code: str | None; attempts: int; prompt_version: str

def analyze_hook(creative: Creative, *, thinking_level: ThinkingLevel, purpose: str, ledger_path: Path,
                 caps: Mapping[str, float], window_max_s: float,
                 interact: Callable[..., InteractionResult] = gemini_interact,
                 max_validation_retries: int = 1) -> AnalysisOutcome

class BatchSummary(BaseModel):
    counts: dict[str, int]      # JobStatus 값별 건수
    stopped: str | None         # "DAILY_LIMIT" | "RATE_LIMITED" | "COST_CAP:<공급사>" | None

def analyze_pending(repo: AnalysisRepository, *, limit: int, **call_kwargs: Any) -> BatchSummary
```

- `analyze_hook`: P1은 YouTube만 지원한다(`source != youtube`이면 `FAILED`, `error_code="UNSUPPORTED_SOURCE"`, `creative.url`이 없으면 `FAILED`, `error_code="NO_URL"`). 입력은 `[text_part(프롬프트), video_part(creative.url, start_s=0, end_s=창 끝, fps=1)]`, `response_format=json_schema_format(hook_response_schema())`로 `interact`를 부른다. 결과 텍스트를 `parse_json_output`→`HookResult`로 검증한다. **형식 오류(JSON이 아님·목록 밖 값)이면 같은 입력으로 최대 `max_validation_retries`(기본 1)번 다시 요청하고, 그래도 실패하면 `HELD`(`error_code="INVALID_OUTPUT"`, 마지막 원문 보존)다.** 성공이면 `DONE`이고 `hook`에 결과를 담는다. `raw_output`에는 모델 텍스트를 **번역·정규화 없이 그대로** 담는다. 다른 `LlmCallError`(재시도 소진·치명 오류)는 `FAILED`(`error_code=f"LLM_{kind}"`)로 돌려주고 예외를 올리지 않는다. `LlmResponseError`(`NO_MODEL_OUTPUT`)는 `FAILED`. **`DailyLimitReached`·`kind == RATE_LIMIT`인 `LlmCallError`·`CostCapExceeded`는 잡지 않고 그대로 올린다.**
- `analyze_pending`: `repo.next_pending("hook", limit)`로 가져와 순서대로 `analyze_hook`을 부르고 결과를 `repo.record_analysis("hook", key, status=..., model=..., thinking_level=..., prompt_version=HOOK_PROMPT_VERSION, raw_output=..., labels={"hook_type": 값} 또는 None, error_code=...)`로 저장한다. **한 소재의 실패(`FAILED`·`HELD`)는 기록하고 다음 소재로 넘어간다.** 위 세 종류의 예외가 나면 그 소재는 기록하지 않고(`pending`으로 남긴다) 배치를 멈춰 `stopped`에 사유를 담아 돌려준다.

### 반드시 있어야 하는 테스트 (`tests/test_analysis.py`)

- `select_for_analysis`: `analyzable`이 `None`·`False`인 소재는 `NOT_ANALYZABLE`로, 길이 컷을 넘으면 `TOO_LONG`로 제외되고 `duration_s is None`은 통과한다. `hook_window`가 3초·창 상한·영상 길이 중 가장 작은 값으로 끝나고 시작은 0이다.
- `hook_response_schema`의 `enum` 값 집합이 `HookType` 멤버 값 집합과 같다(멤버를 순회해서 비교한다).
- `analyze_hook`(가짜 `interact`): **`HookType`의 모든 멤버를 순회**하며 각 값을 JSON으로 돌려주는 가짜가 `DONE`이 되고 `hook.hook_type`이 가짜가 돌려준 그 값과 같다(특정 값을 기대값으로 고정하지 않는다). 목록 밖 값·JSON이 아닌 텍스트를 돌려주면 정확히 2번 호출되고 `HELD`·`INVALID_OUTPUT`이며 원문이 그대로 남는다. 요청 인자에 `thinking_level`이 그대로 전달되고 `video_part`의 구간이 `hook_window` 결과와 같다.
- 예외 처리: `FATAL`인 `LlmCallError`는 `FAILED`, `DailyLimitReached`는 그대로 올라간다.
- `analyze_pending`(메모리 저장소 가짜): 한 소재가 `FAILED`여도 나머지가 처리됨, `DailyLimitReached`가 나면 그 소재와 나머지가 `pending`으로 남고 `stopped == "DAILY_LIMIT"`, `COST_CAP`도 마찬가지, 정상 처리된 소재의 저장 호출 인자에 `status`·`labels`·`prompt_version`(= `HOOK_PROMPT_VERSION`)이 들어간다. `thinking_level="default"`로 불러도 그 문자열이 그대로 저장 인자로 전달된다.

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

- 모델이 고른 `hook_type` 값을 테스트 기대값으로 고정하지 마라. 가짜가 돌려준 값이 그대로 저장되는지, 형식이 틀리면 재요청·보류가 되는지만 단언한다. 이유: 모델의 정확도는 테스트가 아니라 평가(E1)에서 잰다(FP-C03).
- 한 소재의 실패(`FAILED`·`HELD`)로 배치를 멈추지 마라. 멈추는 것은 일일·분당 한도와 비용 상한뿐이다. 이유: 소재 하나의 결함이 전체 분석을 막으면 안 된다(A-FP-030).
- 훅 값 목록을 프롬프트·스키마·테스트에 따로 적지 마라. `HookType`에서 만든다. 이유: 분류 v1 동결 때 한 곳만 바꿔야 한다(`docs/TAXONOMY.md`).
- 영상 전체를 요청하지 마라. 항상 구간을 지정한다. 이유: 입력 토큰이 길이에 비례해(약 91토큰/초) 14분 영상 하나가 79,435토큰이다.
- 모델 출력을 번역하거나 정규화해 저장하지 마라. 원문을 `raw_output`에 그대로 둔다. 이유: 원문은 재검증과 분류 수정 때의 근거다(PRD).
