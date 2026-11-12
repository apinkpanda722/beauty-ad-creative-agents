# Step 9: analysis-full

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P2 sources-pilot"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/TAXONOMY.md` — "축과 값" 전체(콘텐츠 유형 0번 축부터 카테고리 10번 축까지. **값 목록은 초안 v0이며 P3에서 동결된다**)와 원칙(관찰 가능한 사실만, 닫힌 목록, 해당 없음으로 빠질 길이)
- `/docs/ARCHITECTURE.md` — "데이터 흐름" 오프라인 3~6번(콘텐츠 유형 판정 → 제품 소재만 분석, 첫 3초 구간과 전체 두 번 호출, 목록 밖이면 1회 재요청 뒤 보류)
- `/docs/CONTRACTS.md` — "Gemini API" 표의 구조화 출력·구간 지정·응답 위치, 영상 입력 토큰이 길이에 비례한다는 주의
- `/src/beautyads/analysis/` 전체(`hook.py`, `prompts.py`, `batch.py`), `/src/beautyads/domain/labels.py`, `/src/beautyads/llm/__init__.py` — P1 산출물과 이전 step의 `video_part(mime_type)`
- `/tests/test_analysis.py`, `/tests/test_domain.py` — 기존 테스트

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/labels.py`, `src/beautyads/domain/__init__.py`, `src/beautyads/analysis/models.py`, `src/beautyads/analysis/axes.py`, `src/beautyads/analysis/prompts.py`, `src/beautyads/analysis/hook.py`, `tests/test_analysis_full.py`, `tests/test_analysis.py`, `tests/test_domain.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/labels.py`(분류 값·결과 모델 추가에 한함, 기존 `HookType`·`HookResult` 불변), `src/beautyads/domain/__init__.py`(공개 이름 추가에 한함), `src/beautyads/analysis/models.py`, `src/beautyads/analysis/axes.py`, `src/beautyads/analysis/prompts.py`(추가에 한함), `src/beautyads/analysis/hook.py`(모델 상수 사용과 `video` 인자 추가에 한함, 기존 동작 불변), `tests/test_analysis_full.py`, `tests/test_analysis.py`(추가에 한함, 단언 약화 금지), `tests/test_domain.py`(추가에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 라벨 키 파일을 읽는 채점 함수, 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

P1은 `hook_type` 하나만 분류했다. 이 step은 TAXONOMY v0의 **나머지 축**과 **콘텐츠 유형 선별**을 추가한다. 호출은 세 종류다: ① **콘텐츠 유형 + 카테고리**(전체 구간) ② **훅**(첫 3초, P1의 `analyze_hook`) ③ **전체 축**(구간 상한 안). 훅과 전체 축은 ①에서 `product_creative`이고 카테고리가 `other`가 아닌 소재에만 한다(`other` 카테고리는 수집은 하되 분석 대상에서 뺀다). 이 step은 `domain`과 `analysis` 두 계층을 바꾼다(분류 값은 데이터뿐이라 한 step으로 둔다). `analysis/`는 `domain`과 `llm`만 import할 수 있다. **테스트는 가짜 `interact` 함수로만 하고 실제 호출은 하지 않는다.** 호출 횟수가 제품 소재 1건당 세 번이 되므로 비용이 견적보다 커질 수 있다. 시범 20건 직후 `cost-recalc`가 실측으로 다시 계산한다(이 step은 비용 값을 가정하지 않는다).

소비자 테스트 점검 결과: `tests/test_analysis.py`는 `hook.py`의 `analyze_hook`·`select_for_analysis`·`analyze_pending`을 검사한다. 이 step은 `analyze_hook`에 **선택 인자**와 모델 상수 사용만 추가하며 기존 인자·반환·오류 처리는 바꾸지 않는다. `analyze_pending`(배치)은 바꾸지 않는다(다음 step이 새 배치 실행기를 만든다). 기존 단언은 고치지 않고 새 테스트를 **추가**한다. `domain/__init__.py`에 이름을 **추가**할 뿐이므로 이를 import하는 `tests/test_slice.py`·`tests/test_store.py`·`tests/test_youtube.py`·`tests/test_architecture.py`는 영향이 없다(수정하지 않는다. 깨지면 고치지 말고 `blocked`로 보고한다).

### domain 추가 (`labels.py`, 기존 `HookType`·`HookResult`는 불변)

`StrEnum`과 결과 모델(pydantic, `extra="forbid"`). **값은 `docs/TAXONOMY.md`의 표에서 옮긴다. 값 목록을 다른 곳에 복사하지 않는다.**

- `ContentType`: `product_creative`, `event_place`, `brand_campaign`, `other`
- `Angle`: `problem_solution`, `desire`, `social_proof`, `comparison`, `ingredient_science`, `how_to`, `other`
- `Format`: `ugc_style`, `studio_film`, `demo`, `text_motion`, `static_image`, `other`
- `Talent`: `none`, `ordinary_person`, `creator`, `celebrity`, `expert`, `staff`
- `CtaType`: `none`, `shop_now`, `learn_more`, `store_mention`, `event`, `follow_engage`
- `Claim`: `hydration`, `soothing`, `brightening`, `firming_elasticity`, `pore_sebum`, `acne_trouble`, `barrier`, `anti_aging`, `sun_protection`, `texture_finish`, `other`
- `Category`: `mask_pack`, `serum_ampoule`, `sun_care`, `other`
- `StructureFlags`: `has_hook_segment`, `has_demo_segment`, `has_proof_segment`, `has_cta`(모두 `bool`)
- `PlatformFitFlags`: `is_vertical`, `has_text_overlay`, `has_voice`, `has_music_only`, `has_subtitles`(모두 `bool`)
- `ContentTypeResult`: `content_type: ContentType`, `category: Category`
- `FullResult`: `angle`, `format`, `talent`, `structure: StructureFlags`, `platform_fit: PlatformFitFlags`, `cta_type`, `claims: list[Claim]`, **`ingredients: list[str]`(자막·음성·제품 표기에 나온 성분명을 원문 그대로. 표준명 대조·목록 밖 폐기는 사전이 생기는 P4에서 한다. 이 step은 정규화·번역·폐기를 하지 않는다)**

### analysis 추가

```python
# models.py
ANALYSIS_MODEL_ID = "gemini-3.6-flash"            # 분석 모델 ID가 코드에 나타나는 유일한 곳
PROMPT_VERSIONS = {"content_type": "content-type-v0", "hook": "hook-v0", "full": "full-v0"}
FINAL_RUN_TAG = "v1"                       # 정본으로 읽는 실행 태그. P3 일괄 분석(analyze-target)과 P4 그래프 동기화가 이 태그의 `content_type@`·`hook@`·`full@`만 읽는다. 시범은 `@minimal`·`@default`로 따로 둔다
class VideoInput(NamedTuple): uri: str; mime_type: str | None      # YouTube는 영상 주소와 None, 업로드한 파일은 파일 id와 "video/mp4"
def video_input_for(creative: Creative) -> VideoInput               # YouTube 소재의 url. 없으면 ValueError
def models_match(requested: str, actual: str | None) -> bool        # actual == requested 이거나 actual이 requested + "-"로 시작하면 True. actual이 None이면 False

class AxisOutcome(BaseModel):
    key: CreativeKey; axis: str                                     # "content_type" | "full"
    status: JobStatus; labels: dict[str, Any] | None                # 결과 모델의 model_dump(mode="json")
    raw_output: str | None; model: str | None                       # 응답이 알려 준 실제 모델 이름
    model_matches_request: bool | None
    error_code: str | None; attempts: int; prompt_version: str

# axes.py
def content_type_schema() -> dict; def full_schema() -> dict        # 위 enum·모델에서 만든 JSON schema(값을 따로 적지 않는다)
def is_product_target(result: ContentTypeResult) -> bool            # content_type == product_creative 이고 category != other
def full_window(duration_s: float | None, *, window_max_s: float) -> tuple[float, float]   # (0.0, min(window_max_s, duration_s가 있으면 duration_s))
def analyze_content_type(creative, video: VideoInput, *, thinking_level, purpose, ledger_path, caps, window_max_s,
                         interact=gemini_interact, max_validation_retries: int = 1) -> AxisOutcome
def analyze_full(creative, video: VideoInput, *, ...같은 인자...) -> AxisOutcome
```

- **구간 인자는 호출마다 별도다**: `analyze_content_type`과 `analyze_full`은 각자 `window_max_s`를 받는다. 호출자(배치 실행기와 시범 대상)는 콘텐츠 유형 호출의 구간을 전체 축 호출과 **따로** 정할 수 있어야 한다(예: `--content-type-window-s` 기본 60). 콘텐츠 유형 호출은 분석 가능 소재 전부에 전체 구간 입력이 한 번 더 붙으므로 비용을 코드 변경 없이 줄일 수 있게 하려는 것이다.
- 두 함수는 P1 `analyze_hook`과 **같은 규칙**을 따른다: `interact(model=ANALYSIS_MODEL_ID, ...)`를 `thinking_level`·`response_format`과 함께 부르고, 입력은 `[text_part(프롬프트), video_part(video.uri, start_s=0, end_s=창 끝, fps=1, mime_type=video.mime_type)]`이다. 결과 텍스트를 `parse_json_output`→결과 모델로 검증하고 **형식 오류(JSON이 아님·목록 밖 값·누락)이면 같은 입력으로 최대 `max_validation_retries`번 다시 요청, 그래도 실패하면 `HELD`(`INVALID_OUTPUT`)**다. `DailyLimitReached`·`RATE_LIMIT`인 `LlmCallError`·`CostCapExceeded`는 잡지 않고 올리며, 다른 `LlmCallError`·`LlmResponseError`는 `FAILED`로 돌려준다(`error_code`는 P1 `analyze_hook`과 같은 규칙으로 만든다). `raw_output`은 번역·정규화 없이 그대로 둔다. 응답이 알려 준 모델 이름을 `model`에 기록하고 `models_match(ANALYSIS_MODEL_ID, model)`을 `model_matches_request`에 기록한다(불일치는 실패로 보지 않고 기록만 한다).
- 프롬프트(`prompts.py`에 추가: `build_content_type_prompt`, `build_full_prompt`): 영상과 제목·캡션을 보고 TAXONOMY의 판정 기준으로 고르게 한다. **콘텐츠 유형 프롬프트는 특정 제품을 보여주거나 설명하는 것이 중심이 아니면 `product_creative`가 아니라고 답할 길(`event_place`·`brand_campaign`·`other`)을 분명히 준다**(시험 호출에서 팝업 홍보 영상이 제품 소재로 억지 분류된 사례가 있었다). 전체 축 프롬프트는 자막·음성에 **명시된** 효능·성분만 적게 하고 분위기에서 추정하지 않게 한다. 각 프롬프트는 TAXONOMY의 문구를 따르고 값 목록은 enum에서 만든다.
- `hook.py` 변경(추가에 한함): 분석 모델 문자열 `"gemini-3.6-flash"`를 `ANALYSIS_MODEL_ID` 사용으로 바꾼다. `analyze_hook`에 선택 키워드 인자 `video: VideoInput | None = None`을 추가한다(없으면 기존대로 `creative.url`을 YouTube 주소로 쓰고, 있으면 `video.uri`·`video.mime_type`을 쓴다. `source != youtube`인 소재도 `video`가 주어지면 분석한다).

### 반드시 있어야 하는 테스트 (`tests/test_analysis_full.py` + 기존 파일 추가분)

- `domain`: 각 enum의 모든 멤버를 순회해 결과 모델이 받아들이고 목록 밖 값·알 수 없는 필드·누락을 거부한다. `FullResult.ingredients`가 입력 문자열을 **바꾸지 않고** 보존한다(공백·대소문자·한글 포함 그대로). `HookType`·`HookResult` 테스트는 그대로 통과한다.
- 스키마: `content_type_schema()`·`full_schema()`의 속성 이름 집합이 결과 모델 필드 집합과 같고, 각 enum 속성의 값 집합이 enum 멤버 집합과 같다(멤버를 순회해 비교한다).
- `analyze_content_type`·`analyze_full`(가짜 `interact`): 각 enum 멤버를 순회하며 그 값을 JSON으로 돌려주는 가짜가 `DONE`이 되고 `labels`가 가짜가 돌려준 값과 같다(**특정 값을 기대값으로 고정하지 않는다**), 목록 밖 값·JSON이 아닌 텍스트는 정확히 2번 호출되고 `HELD`·`INVALID_OUTPUT`이며 원문 보존, `DailyLimitReached`·`CostCapExceeded`는 그대로 올라감, `FATAL`은 `FAILED`, 요청 입력의 `video_part`가 `video.uri`·`mime_type`·창(0, min(상한, 길이))을 담고 `thinking_level`이 전달되며 `model`이 `ANALYSIS_MODEL_ID`다, 응답 모델명이 요청과 다르면 `model_matches_request`가 `False`이고 결과는 그대로 `DONE`이다.
- `is_product_target`: `product_creative`+`mask_pack`은 참, `product_creative`+`other`는 거짓, `event_place`+`mask_pack`은 거짓(조합을 열거해 단언한다).
- `video_input_for`: YouTube 소재는 `(url, None)`, `url`이 없으면 `ValueError`. `models_match`의 경계(`None`, 접미사, 다른 모델).
- `FINAL_RUN_TAG`가 `"v1"`이고 시범 실행 태그(`minimal`, `default`)와 다르며 `PROMPT_VERSIONS`의 키가 `content_type`·`hook`·`full` 세 축이다.
- **모델 ID 단일 출처**: `src/beautyads/analysis/` 아래 모든 `.py`를 읽어 문자열 `gemini-3.6-flash`가 `models.py`에만 나타남을 단언한다(소스 검사. 다른 파일에 하드코딩이 남으면 실패).
- `tests/test_analysis.py`에 추가: `analyze_hook`이 `video`를 받으면 그 `uri`·`mime_type`으로 요청하고 `source != youtube`여도 분석하며, `video`가 없으면 기존 동작(`UNSUPPORTED_SOURCE`·`NO_URL`)이 그대로다.

프롬프트 버전 연속성: `PROMPT_VERSIONS`는 `-v0`이다. P3의 분류 동결(`taxonomy-partial`·`taxonomy-v1`)이 값 목록·프롬프트를 v1로 올릴 때 이 상수를 갱신하고, E1 사전 등록 파일에 **프롬프트 버전 3개와 `ANALYSIS_MODEL_ID`를 함께 기록**한다(이 step은 상수만 둔다).

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

- 분류 값 목록을 프롬프트·스키마·테스트에 따로 적지 마라. `domain`의 enum에서 만들고 테스트는 멤버를 순회한다. 이유: 분류 v1 동결(P3)에서 한 곳만 바뀌어야 한다(`docs/TAXONOMY.md`, FP-C03).
- 모델이 고른 분류 값을 테스트 기대값으로 고정하지 마라. 가짜가 돌려준 값이 그대로 저장되는지와 형식 오류의 재요청·보류만 단언한다. 이유: 모델의 정확도는 테스트가 아니라 평가(E1)에서 잰다(FP-C03).
- 성분 문자열을 정규화·번역·사전 대조·폐기하지 마라(원문 그대로 보존). 이유: 성분 표준명 사전은 P4에서 만들어지고 지금 버리면 되돌릴 수 없다. 사전에 없는 값은 P4 적재 때 `미해결`로 보존한다(TROUBLESHOOTING 2026-11-12).
- `models.py` 밖에 모델 ID 문자열을 쓰지 마라. 이유: E1 사전 등록이 모델 ID를 동결해 기록하므로 한 곳에서만 바뀌어야 하고, 요청 모델과 응답 모델의 불일치를 기록으로 잡는다.
- `analyze_hook`의 기존 인자·반환·오류 처리와 `analyze_pending`을 바꾸지 마라. 선택 인자와 모델 상수 사용만 추가한다. 이유: P1에서 승인된 동작이 조용히 바뀌면 안 된다. 기존 테스트 단언을 약화하지 마라(B-FP-056).
