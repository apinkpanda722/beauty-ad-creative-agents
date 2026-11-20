# Step 2: clarify-api

## 설계 검토 기록

**배경(조언 세션 승인, 이슈 #55)**: step 1이 `run_request` 결과에 `kind: "needs_clarification"`·`"claim_choice_invalid"`, `clarification`, `efficacy_notice`, `claim_choice`를 싣고 `assembly.ask(..., claim_choice=None)`가 그것을 `run_request`에 전달한다. 이 step은 그 결과를 **API 계약**으로 노출한다: 요청에 `claim_choice`를 받고, 되묻기를 SSE 이벤트와 텍스트로 돌려주고, 선택 검증 실패를 `error` 이벤트로 낸다. **선택 카드 UI는 P7이며 이 step의 범위가 아니다.** 모델 호출 없음.

**승인된 결정**: (1) 구조 오류(`Claim` enum 아님·mode와 `claims` 불일치·`keep_requested`인데 `requested_claim` 없음 등)는 FastAPI/pydantic이 HTTP 422로 거절한다. (2) `selected ⊆ 확인 효능` 위반은 서버가 코드로 다시 계산해(step 1의 `interpret`) 판정하며, 스트림이 이미 200으로 열린 뒤이므로 SSE `error` 이벤트 `{"code": "CLAIM_CHOICE_INVALID"}`로 낸다. (3) 핸들러에서 `claims_fn`을 한 번 더 부르지 않는다. (4) 효능 표시 이름은 `analysis/prompts.py`에 공개 별칭 `CLAIM_DISPLAY_NAMES = _CLAIM_CRITERIA`를 추가해 재사용한다(문구·분석 프롬프트 해시 불변). 선택지와 안내 문구에서 `Claim.other`는 제외한다.

**식별자 전수 대조(현재 코드, 모두 열어 확인)**:
- `api/ask.py`: `AskRequest(BaseModel, extra="forbid")`(`message`·`thread_id`·`with_image`), `register_ask`, `/ask` 핸들러(세션 확인 `resolve_session` → 워크스페이스·`ToolContext` → `services.ask(body.message, ctx, profile, feedback, body.with_image, on_event=on_event)`; 실패 시 `AGENT_INTERNAL_ERROR` `error` 이벤트; 성공 시 `ui_command`들 뒤 `token`), `work()`가 `result.get("plans", [])`로 `PlanRecord`를 저장하고 `build_view(result, plan_ids=..., hydrate=services.hydrate)`를 돌려준다.
- `api/sse.py`: `EventName = Literal["step", "tool_start", "token", "ui_command", "error"]`, `encode_event(name, body)`.
- `api/ask_view.py`: `View(answer_text, ui_commands)`(frozen dataclass), `build_view(result, *, plan_ids, hydrate)`(`kind` 별 고정 문구 `fixed = {"out_of_scope", "no_evidence", "failed"}`, `research`·`plan` 문구, 마지막에 `View("\n".join(...), json_copy(commands))`).
- `obs/trace.py`: `TraceRecord.kind`가 `Literal["research", "plan", "out_of_scope", "no_evidence", "failed"] | None`이다. **새 `kind`가 여기 없으면 `build_trace`가 검증 오류를 내고 `assembly.ask`의 `finally` 블록이 예외를 삼켜(`except Exception: pass`) trace가 조용히 사라진다**(이 step에서 `needs_clarification`·`claim_choice_invalid`를 `Literal`에 더한다). `tests/test_trace.py:59`가 `kind` 목록을 매개변수로 가진다.
- `analysis/prompts.py`: `_CLAIM_CRITERIA: dict[Claim, str]`(`hydration: "보습"`, `soothing: "진정"`, `anti_aging: "주름 개선·안티에이징"`, `sun_protection: "자외선 차단"`, `barrier: "피부 장벽"`, … `other`).
- `domain/supervisor.py`(step 1 산출물): `ClaimChoice`, `ClarifyOption`, `ClarifyReason`, `clarification_texts(clarification, display)`, `EFFICACY_NOTICE_TEXT`. `api`는 `domain`·`analysis`·`agents`를 import할 수 있다(계층 표).
- 기존 테스트의 가짜 `ask`는 `ask(message, ctx, profile, feedback, with_image, on_event)`처럼 **고정 시그니처**(`tests/test_api_ask.py:87, 221`) 또는 `ask(*args, **kwargs)`다 → `claim_choice`는 **요청에 값이 있을 때만** 키워드로 넘긴다(없으면 인자 자체를 넘기지 않는다).

**새 칸 대응표**:
- 요청 `claim_choice`(JSON 객체: `mode`·`claims`·`requested_claim`) → `AskRequest.claim_choice: ClaimChoice | None` → `services.ask(..., claim_choice=<model_dump dict>)`(값이 있을 때만).
- 결과 `clarification`(step 1 형태) → `build_view`가 `clarification_texts`로 문장·선택지를 만들어 `View.clarification` → SSE `needs_clarification` 본문.
- 결과 `efficacy_notice`(`None | "lookup_unconfirmed" | "none_confirmed"`) → `build_view`가 `EFFICACY_NOTICE_TEXT`의 문구를 답변 텍스트의 **첫 줄**로 추가.
- 결과 `kind == "claim_choice_invalid"` → `View.error_code = "CLAIM_CHOICE_INVALID"` → SSE `error` `{"code": "CLAIM_CHOICE_INVALID"}`.
- SSE `needs_clarification` 본문 키(정확히): `reason`, `requested_claim`, `requested_label`, `available`(`[{"claim", "label"}]`), `options`(`[{"id", "label"}]`), `text`. `requested_label`은 `requested_claim`이 `None`이면 `None`.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: `tenant_id`는 세션에서만 나온다(도구·요청 입력에 테넌트 칸 금지), 검사 실패 시 요청을 거부한다
- `/docs/ADR.md`(ADR-009), `/docs/ARCHITECTURE.md`(api 계층)
- `/src/beautyads/api/ask.py`, `/src/beautyads/api/sse.py`, `/src/beautyads/api/ask_view.py`, `/src/beautyads/api/assembly.py`(`ask`, step 1이 더한 `claim_choice` 전달부), `/src/beautyads/api/session.py`(읽기 전용), `/src/beautyads/obs/trace.py`(`TraceRecord.kind`), `/src/beautyads/analysis/prompts.py`(`_CLAIM_CRITERIA`), `/src/beautyads/domain/supervisor.py`(step 1 산출물)
- `/tests/test_api_ask.py`(전체), `/tests/test_ask_view.py`, `/tests/test_trace.py`, `/tests/test_api_assembly.py`(읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/api/ask.py`, `src/beautyads/api/sse.py`, `src/beautyads/api/ask_view.py`, `src/beautyads/analysis/prompts.py`, `src/beautyads/obs/trace.py`, `tests/test_api_ask.py`, `tests/test_ask_view.py`, `tests/test_trace.py`

열람 금지 경로: `data/interim/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `src/beautyads/api/ask.py`, `src/beautyads/api/sse.py`, `src/beautyads/api/ask_view.py`, `src/beautyads/analysis/prompts.py`, `src/beautyads/obs/trace.py`, `tests/test_api_ask.py`, `tests/test_ask_view.py`, `tests/test_trace.py`

`/ask`가 `claim_choice`를 받고, 되묻기·안내·선택 검증 실패를 SSE로 노출한다. **모델 호출 없음. 테스트를 먼저 쓴다(TDD).**

새 식별자: `CLAIM_DISPLAY_NAMES`, `View.clarification`, `View.error_code`, SSE 이벤트 `needs_clarification`

**1. `analysis/prompts.py`**: `CLAIM_DISPLAY_NAMES = _CLAIM_CRITERIA` 한 줄(공개 별칭). `_CLAIM_CRITERIA` 값과 순서·분석 프롬프트 문자열은 바꾸지 않는다.

**2. `obs/trace.py`**: `TraceRecord.kind`의 `Literal`에 `"needs_clarification"`·`"claim_choice_invalid"`를 더한다(기존 값·다른 칸 불변).

**3. `api/sse.py`**: `EventName`에 `"needs_clarification"`을 더한다.

**4. `api/ask_view.py`**
- `View`에 `clarification: dict | None = None`, `error_code: str | None = None`을 더한다(기본값 있음, 기존 두 인자 호출 그대로 동작).
- 표시 이름 매핑은 `CLAIM_DISPLAY_NAMES`에서 `Claim.other`를 뺀 `{claim.value: 이름}`이다.
- `build_view`: `kind == "needs_clarification"`이면 `clarification_texts(result["clarification"], display)`로 `text`·`options`를 만들고 `View(answer_text=text, ui_commands=[], clarification={...위 본문 키...})`를 돌려준다(근거 카드·계획·분포 명령 없음). `kind == "claim_choice_invalid"`이면 `View("", [], error_code="CLAIM_CHOICE_INVALID")`. 그 밖의 `kind`에서 `result.get("efficacy_notice")`가 `EFFICACY_NOTICE_TEXT`의 키이면 그 문구를 답변 텍스트의 첫 줄로 더한다(기존 문구·명령 순서는 그대로). 알 수 없는 `efficacy_notice` 값은 무시한다.

**5. `api/ask.py`**
- `AskRequest`에 `claim_choice: ClaimChoice | None = None`(`beautyads.domain.supervisor.ClaimChoice`)을 더한다. `extra="forbid"`·`message`·`thread_id`·`with_image` 불변. 구조 오류는 pydantic이 422를 낸다(핸들러에 따로 검사를 두지 않는다).
- `work()`의 `services.ask(...)` 호출에 `claim_choice`가 있을 때만 `claim_choice=body.claim_choice.model_dump(mode="json")`를 키워드로 더한다(없으면 호출 인자 목록이 지금과 같다). 세션 확인(`resolve_session`)·워크스페이스·`ToolContext` 생성은 `claim_choice`와 무관하게 먼저 지금처럼 일어나며 **`claim_choice`가 `tenant_id`를 바꾸거나 검사를 우회할 수 없다**.
- `events()`: 작업이 끝난 뒤 `outcome.error_code`가 있으면 `encode_event("error", {"code": outcome.error_code})`만 내고 끝낸다(`token`·`ui_command` 없음). `outcome.clarification`이 있으면 `encode_event("needs_clarification", outcome.clarification)`를 낸 뒤 `token`(`answer_text`)을 낸다(`ui_command` 없음). 그 밖에는 지금 순서(`ui_command`들 → `token`) 그대로다. `work()`는 `result["plans"]`가 없거나 비어 있으면 `PlanRecord`를 저장하지 않는다(지금 코드 그대로).

**테스트(합성 데이터, 모델·접속 없음, `tmp_path`)**
- `tests/test_api_ask.py`: (1) `claim_choice` 없는 기존 요청에서 가짜 `ask`가 받은 인자 목록이 지금과 같다(키워드 `claim_choice`가 없다). (2) 정상 `claim_choice`가 있으면 가짜 `ask`가 `claim_choice` 키워드로 `{"mode", "claims", "requested_claim"}` dict를 받는다. (3) 구조 오류 요청(Claim 값이 아닌 문자열, `other`, `selected`인데 `claims` 비어 있음, `keep_requested`인데 `requested_claim` 없음, `none`인데 `claims` 있음, 알 수 없는 추가 키, `claim_choice` 안에 `tenant_id` 키)은 HTTP 422이고 가짜 `ask`가 호출되지 않는다. (4) 가짜 `ask`가 `kind: "needs_clarification"` 결과(step 1 형태의 `clarification`, `plans` 없음)를 돌려주면 SSE 이벤트가 `needs_clarification`(본문 키 집합이 정확히 위 여섯 개, `requested_label`·`available` 라벨이 표시 이름, `options`의 `id`·`label`이 `clarification_texts` 결과와 같음) 다음 `token`이고 `ui_command`가 없으며 `PlanRecord`가 저장되지 않는다(`services.tenants`의 저장 호출 0회). (5) `kind: "claim_choice_invalid"` 결과는 이벤트가 정확히 `("error", {"code": "CLAIM_CHOICE_INVALID"})` 하나뿐이다(`token` 없음). (6) 세션 검사가 `claim_choice`보다 먼저 일어난다: 허용되지 않은 테넌트 또는 다른 테넌트의 `thread_id`로 `claim_choice`를 보내도 지금과 같은 거절이고 가짜 `ask`가 호출되지 않는다. (7) **실제 서버 진입점 경유**: `create_app(assemble)`에 가짜 `Assembly`(가짜 `ask`)를 넣은 앱으로 위 (2)(4)가 동작한다(B-FP-070; 이 앱에서 모든 `/ask` 경로가 가짜 `Assembly.ask`를 부름을 단언한다). (8) `needs_clarification`·`claim_choice_invalid` 경로에서 `X-Thread-Id` 헤더가 지금처럼 나간다.
- `tests/test_ask_view.py`: (9) `build_view`가 `needs_clarification`을 ②(확인 효능 있음·0개)·③ 각각에서 기대 `text`·선택지 id 목록과 같게 만든다(문구는 step 1 상수와 표시 이름을 써서 손으로 만든 기대 문자열과 정확 일치). (10) 표시 이름 매핑에 `Claim.other`가 없고 `CLAIM_DISPLAY_NAMES`가 `_CLAIM_CRITERIA`와 같은 객체다. (11) `efficacy_notice`가 `lookup_unconfirmed`·`none_confirmed`이면 답변 텍스트의 첫 줄이 해당 문구이고 그 아래 기존 텍스트·`ui_commands`가 그대로이며, `None`이면 기존 출력과 바이트 단위로 같다. (12) `claim_choice_invalid`는 `error_code`만 갖고 `answer_text == ""`다. (13) 기존 `View(text, commands)` 두 인자 호출이 그대로 동작한다.
- `tests/test_trace.py`: (14) `kind` 매개변수 목록에 두 새 값을 더한다(기존 값·단언 유지). 새 `kind`로 `build_trace`가 검증 오류 없이 `TraceRecord`를 만들고 `kind`가 보존된다.
- 합성 문장·분류 값을 기대값으로 굳히지 않는다(문구 상수·닫힌 값·구조만 검사).

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

- 핸들러(`ask.py`)에서 `claims_fn`·그래프·Neo4j를 직접 부르지 마라. `selected ⊆ 확인 효능` 검증을 핸들러에서 다시 하지 마라. 이유: 승인된 설계는 `interpret`의 코드 판정 한 곳이다. 핸들러가 한 번 더 부르면 요청당 그래프 질의가 10번 늘고 두 판정이 어긋날 수 있다.
- `claim_choice`를 서버가 쓰는 세션·테넌트 판정에 쓰거나 `tenant_id`·사용자·날짜 칸을 요청 모델에 더하지 마라. 이유: `tenant_id`는 세션에서만 나온다(ADR-009). 테스트가 `claim_choice` 안의 `tenant_id` 키가 422임을 단언한다.
- `claim_choice`가 없을 때 가짜 `ask`에 `claim_choice=None` 키워드를 넘기지 마라(키워드 자체를 생략). 이유: 기존 테스트의 가짜 `ask`는 고정 시그니처라 새 키워드를 받으면 `TypeError`가 된다(FP-C11, B-FP-071).
- `obs/trace.py`에서 `kind` 목록 말고 다른 칸·검증을 바꾸지 마라. 이유: `TraceRecord`는 닫힌 모델이며 새 `kind`가 없으면 trace가 조용히 버려지므로 그 한 줄만 허용한다. 기존 `tests/test_trace.py` 단언은 약화하지 않고 매개변수만 더한다.
- `CLAIM_DISPLAY_NAMES` 외에 `analysis/prompts.py`의 프롬프트 문구·분류 기준·`_CLAIM_CRITERIA` 값을 바꾸지 마라. 이유: 분석 프롬프트 해시·E1 라벨 계약에 영향을 준다(문구 불변).
