# Step 7c: ask-sse

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`api`는 `domain`~`agents` 전부 import 가능, `fastapi`·`psycopg`는 `api`만, `httpx`는 `sources`만), CRITICAL 규칙(테넌트 세션, 검사 실패 시 거부, 상태 dict·기본 타입)
- `/docs/PRD.md` — 핵심 기능 14(화면 명령), 시나리오 S1~S6
- `/docs/ARCHITECTURE.md` — "스트리밍 이벤트와 화면 명령"(token·step·tool_start·ui_command)과 "컨텍스트 관리"의 도구 반환 이원화, "상태 관리"의 파일 시스템 행(생성 시안은 로컬만)
- `/src/beautyads/api/app.py`, `/src/beautyads/api/session.py`, `/src/beautyads/api/feedback.py`, `/src/beautyads/api/sse.py`, `/src/beautyads/api/chat_client.py`, `/src/beautyads/agents/supervisor.py`, `/src/beautyads/agents/plan_eval.py`, `/src/beautyads/agents/design_images.py`, `/src/beautyads/domain/supervisor.py`, `/src/beautyads/domain/research.py`, `/src/beautyads/domain/tenant.py`, `/src/beautyads/store/repository.py`, `/tests/test_api_chat.py`, `/tests/test_api_chat_client.py`, `/tests/test_api_feedback.py`, `/tests/test_architecture.py` — step 1·6a·6c·7a·7b 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/api/ask.py`(새 파일), `src/beautyads/api/ask_view.py`(새 파일), `src/beautyads/api/app.py`, `src/beautyads/api/chat_client.py`, `tests/test_api_ask.py`(새 파일), `tests/test_ask_view.py`(새 파일), `tests/test_api_chat_client.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/api/ask.py`, `src/beautyads/api/ask_view.py`, `src/beautyads/api/app.py`(`Assembly`에 기본값이 있는 필드 추가와 `/ask`·`/design` 라우트 등록에 한함, 기존 필드·`/chat`·`/healthz`·`/feedback` 동작 불변), `src/beautyads/api/chat_client.py`(`run_ask_once` 함수와 결과 형식 추가에 한함, 기존 `run_chat_once`·`ChatOutcome` 동작 불변), `tests/test_api_ask.py`, `tests/test_ask_view.py`, `tests/test_api_chat_client.py`(케이스 추가에 한함, 기존 단언 변경 0줄)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

사용자 요청 한 건을 Supervisor(7a)로 처리해 **SSE 이벤트와 화면 명령**으로 내보내는 `POST /ask`와 생성 시안 이미지 조회 `GET /design/...`을 만든다. 기존 `/chat`(skeleton)은 바꾸지 않는다. 이 step은 모델·실제 서비스를 부르지 않는다(모든 서비스는 `Assembly`의 주입 함수, 테스트는 가짜). **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

**`api/app.py`**(추가에 한함): `Assembly`에 기본값이 있는 필드를 더한다: `ask: Callable | None = None`(요청 처리 함수 `ask(message, ctx, profile, feedback, with_image, on_event) -> dict`, Supervisor 결과 dict를 돌려준다. 조립 단계(7d)가 만든다), `hydrate: Callable | None = None`(`hydrate(evidence_ids) -> list[dict]`), `design_dir: Path = Path("data/design")`, `image_enabled: bool = False`. `create_app`이 `/ask`·`/design`을 등록한다.

**`api/ask.py`**: `register_ask(app)`.
- `POST /ask` 본문 `{message: str(1~2000자), thread_id?: str, with_image?: bool = False}`(`extra="forbid"`: 본문에 `tenant_id`·`as_of` 등이 있으면 422). 순서: `resolve_session`(헤더 테넌트·허용 목록·thread 소유, 그래프 호출 전 거부, 7b 이전과 동일) → `services.workspaces[tenant_id]`가 없으면 **403 `WORKSPACE_MISSING`**(요청 거부, fail-closed) → `ToolContext`는 서버가 만든다(`tenant_id`는 세션, `as_of`·`last_collected_at`은 `Assembly`, `price_band`는 `services.price_bands.get(tenant_id)`에서) → 피드백 요약은 7b의 `feedback_for_prompt` → `with_image`가 참이고 `image_enabled`가 거짓이면 **400 `IMAGE_DISABLED`**(기본은 이미지 끄기) → `asyncio.to_thread(services.ask, ..., on_event=...)`로 처리하되 **작업 스레드가 내보내는 이벤트를 실시간으로 SSE로 연결한다**: `on_event`는 `loop.call_soon_threadsafe(queue.put_nowait, event)`로 `asyncio.Queue`에 넣고(스레드 안전), SSE 제너레이터가 큐에서 꺼내는 대로 즉시 내보낸다(작업이 끝날 때까지 기다렸다가 한꺼번에 내보내지 않는다). 작업이 끝나면 종료 표지를 큐에 넣어 제너레이터가 남은 이벤트를 비운 뒤 `ui_command`·`token`을 내보낸다. 큐는 요청마다 새로 만든다(요청 간 공유 금지).
- 응답은 SSE(`text/event-stream`, `X-Thread-Id` 헤더). **이벤트 종류**: `step`(`{agent, phase, status}`: supervisor·research·planning·evaluation·rework·image 단계 경계, **7a의 `on_event` 콜백으로 단계가 진행되는 그 시점에 실시간으로** 도착한다), `tool_start`(`{name, kind}`: 7a가 리서치 종료 직후 순서대로 한꺼번에 내보낸다. 이 한계(승인됨)를 문서 주석에 명시한다), `ui_command`(아래), `token`(답변 글자, 코드가 `ask_view`로 만든 문장), `error`(`{code, detail}`: `code`는 `AGENT_INTERNAL_ERROR`, `detail`은 예외 클래스 이름, 안전한 `code` 속성이 있으면 `error_code`, 메시지·값·키 없음). 예외 뒤에는 스트림을 닫는다.
- 기획안(`plans[].plan`)마다 `PlanRecord`를 만들어 `tenants.save_plan`으로 저장한다(`plan_id`는 서버가 만든 `uuid4().hex`, `payload`는 `{"plan": ..., "report": ..., "image": {경로 없는 참조}}`). 저장된 `plan_id`가 `show_plan`·결과에 실린다(7b의 `/feedback`이 쓴다). 이미지 파일 참조는 `{"request_key", "index", "mime", "size", "sha256"}`뿐이다(**파일 경로를 응답에 싣지 않는다**).

**`api/ask_view.py`**(`api` 계층 순수 함수): `build_view(result, *, plan_ids, hydrate) -> View(answer_text, ui_commands)`.
- **답변 글자는 코드가 만든다**: `kind`별 고정 문장 + 구조화 칸(`out_of_scope`→`OUT_OF_SCOPE_TEXT`, `no_evidence`→`NO_EVIDENCE_TEXT`, `limit_hit`→`LIMIT_REACHED_TEXT`를 덧붙이고 어느 상한인지(`limit_kinds`의 `text`·`image`)를 구분해 적음, `research`→핸드오프 `conclusion`(모델 작성 문장) + 건수 문구, `plan`→각 기획안의 제목·훅·장면·카피). **건수 문구는 `domain.research.count_label`로 만든다**("N건 중 M건 표시", 문자열 매칭에 의존하지 않고 `result_counts`의 구조화 칸에서). `aggregates`는 `AGGREGATES_LABEL`("모델 작성값, 검증되지 않음") 표시와 함께 **검증 통과분만** 본문에 쓰고 빠진 항목은 `aggregates_removed`로 따로 적는다.
- **화면 명령**(모델을 거치지 않는다. 데이터는 도구·코드가 만든 값): `show_evidence_cards`(근거 ID 최대 20개를 `hydrate`로 채운 카드 `{evidence_id, source, url, brand, title, published_at, view_count, like_count}`, 찾지 못한 ID는 빠지고 `missing` 개수로 센다. 썸네일은 저장하지 않으므로 링크만), `show_plan`(기획안마다: 기획안 필드, **`unknown_count`·`unknown_codes`를 눈에 띄는 별도 칸**, **`efficacy_status`·`efficacy_summary`(supported·unknown) 별도 칸**, `count_label` 문구, `evidence_counts`, `status`(`done`·`needs_review`·`failed`), 되돌림 경로(`attempts`: 시도별 차별성·적합성 점수·낮은 항목·통과 여부), `disclaimer`(`CLAIM_CHECK_DISCLAIMER` 그대로), `plan_id`, 이미지 참조. **`passed`에 `unknown`을 섞지 않는다**), `show_distribution`(최소 형태: 결과의 `tool_outputs` 중 집계·비교 도구의 행을 **그대로** 전달, 최대 50행, 가공·계산 없음), `show_graph_fragment`(최소 형태: 근거 ID 목록만 전달. 노드·관계 질의와 화면은 P7 web에서 별도로 만든다). 증거 카드와 기획안 카드가 우선이고 나머지 둘은 최소 형태로 둔다.
- 모든 값은 JSON 안전해야 한다(`json.dumps` 통과).

**`GET /design/{request_key}/{index}`**: `resolve_tenant`(헤더 필수) → 그 테넌트의 저장된 기획안 중 `payload["image"]["request_key"]`가 요청과 같은 것이 없으면 **404**(다른 테넌트의 이미지도 같은 404) → `design_dir/<해시16자>/<번호>.<확장자>`를 읽어 바이트와 `mime`으로 응답(`Cache-Control: no-store`). 경로는 요청 키 문자열이 아니라 서버가 아는 해시에서 만든다(경로 조작 불가). 이미지는 공개하지 않고 로컬 전용이다.

**`api/chat_client.py`**(추가에 한함): `run_ask_once(app, *, tenant_id, message, with_image=False, thread_id=None) -> AskOutcome`(`with TestClient(app) as client:` 형태로 `/ask`를 한 번 호출해 이벤트 목록, `ui_command` 목록, `token` 글자, 상태 코드를 돌려준다. `httpx`를 직접 import하지 않는다).

**반드시 있어야 하는 테스트**(가짜 `ask`·`hydrate`·저장소, 합성 값):
- 이벤트: 이벤트 이름 집합이 `{step, tool_start, ui_command, token, error}`의 부분집합이고 `step`이 시작·끝을 가진다. **실시간성(게이트 방식)**: 가짜 `ask`가 `on_event`로 첫 `step` 이벤트를 내보낸 뒤 **테스트가 그 이벤트를 SSE로 받았음을 확인할 때까지 `threading.Event`로 기다렸다가** 다음 이벤트를 내보낸다(이벤트가 작업 종료 뒤 한꺼번에 나가면 게이트가 열리지 않아 시간 제한으로 실패한다). 이벤트 순서는 가짜 `ask`가 내보낸 순서와 같고 큐는 요청마다 새로 만들어진다(두 요청의 이벤트가 섞이지 않음). `on_event` 콜백이 예외를 던져도(가짜 `ask` 안에서) 요청이 계속된다. `tool_start`가 `result_counts`의 도구 이름과 등록 목록의 종류로 나온다. 예외를 던지는 `ask`에서 `error`가 `code`·`detail`(클래스 이름)·(`error_code`)만 싣고 합성 비밀이 없으며 스트림이 닫힌다.
- 세션·격리(모든 거부에서 `ask`가 불리지 않음): 헤더 없음 400, 허용 밖 403, 다른 테넌트의 `thread_id` 403, 작업 공간 없음 403 `WORKSPACE_MISSING`, 본문의 `tenant_id`·`as_of` 422, `with_image`가 참인데 `image_enabled` 거짓이면 400 `IMAGE_DISABLED`. 정상 요청에서 `ask`가 받은 `ToolContext`의 `tenant_id`가 헤더 값이고 `price_band`가 그 테넌트의 값이다.
- 화면 명령: `show_plan`에 `unknown_count`·`unknown_codes`가 `passed`와 별도 칸으로, `efficacy_status`·`efficacy_summary`가 별도 칸으로, `count_label` 문구(합성 `result_counts` 7·5에서 정확히 `"7건 중 5건 표시"`와 `(3, 3)`에서 `"3건"`: 이 함수의 계약), `disclaimer`가 `CLAIM_CHECK_DISCLAIMER`와 같고 되돌림 경로 `attempts`가 있다. 증거 카드가 `hydrate` 결과로 채워지고 찾지 못한 ID가 `missing`으로 센다. `show_distribution`이 도구 행을 변경 없이 전달하고 50행을 넘으면 자른다. `show_graph_fragment`에 근거 ID뿐이다. 모든 화면 명령 데이터가 `json.dumps`를 통과하고 이미지 참조에 **파일 경로가 없다**.
- `aggregates`: 검증 통과분만 본문에 있고 `aggregates_removed`가 따로 있으며 `AGGREGATES_LABEL`이 표시된다. 답변 글자는 모델 문장 외에 코드가 만든 건수 문구를 구조화 칸에서 만든다(`result_counts`를 바꾸면 문구가 바뀐다).
- 저장: 기획안마다 `save_plan`이 불리고 `plan_id`가 `show_plan`에 실린다. `payload`에 파일 경로가 없다. 다른 테넌트의 `plan_id`로 `/design`을 요청하면 404.
- `/design`: 정상 요청이 바이트와 `mime`을 돌려주고 `Cache-Control: no-store`, 헤더 없음 400, 다른 테넌트·없는 키 404, 요청 키에 `../`가 있어도 `design_dir` 밖을 읽지 않는다(합성 파일은 `tmp_path`).
- **서버 진입점 경유 테스트**: `create_app(assemble=<가짜>)`을 `lifespan`으로 시작해 `/ask`가 시작 시점의 가짜 `ask`를 부르고 앱 생성 뒤 `app.state.assembly.ask`를 바꾸면 바뀐 가짜를 부른다. 기존 `/chat`·`/healthz`·`/feedback` 테스트가 그대로 통과한다(`Assembly` 새 필드는 기본값).
- `run_ask_once`: 가짜 앱의 SSE를 파싱한다(`httpx` 직접 import 없음). `tests/test_architecture.py` 통과.

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

- 본문·쿼리에서 테넌트·기준일·가격대를 받지 마라. 이유: 모두 서버가 세션과 `Assembly`에서 만든다(AGENTS.md CRITICAL, 도구 입력에 테넌트·날짜 칸 금지). 본문에 있으면 422다.
- 화면 명령 데이터를 모델 출력에서 만들거나 모델을 거치게 하지 마라. 이유: 화면 명령의 데이터는 도구·코드가 만든 값이다(ARCHITECTURE 스트리밍 이벤트와 화면 명령). `aggregates`는 검증 통과분만 쓴다.
- `unknown_count`나 효능별 상태를 `passed`에 합치거나 화면 데이터에서 빼지 마라. 이유: "근거 연결 없음"은 눈에 띄게 별도로 노출한다(P5 결정, FP-C14 계열).
- 응답·이벤트·저장 `payload`에 이미지 파일 경로·base64·`thought_signatures`를 넣지 마라. 이유: 생성 시안은 로컬 전용이고 참조(`request_key`·`index`·`mime`·`size`·`sha256`)만 쓴다(ARCHITECTURE, 6a 규칙). 파일은 테넌트 검사를 거친 `/design`으로만 읽는다.
- `/chat`·`/healthz`·`/feedback`의 동작이나 기존 테스트 단언을 바꾸지 마라. 이유: 이미 live로 확인한 경로이고 새 라우트는 추가만 한다(B-FP-071). `Assembly` 새 필드는 기본값을 갖는다.
- `ask`·`hydrate`를 라우트 생성 시점 값으로 붙잡지 마라. 이유: 진입점이 시작 때 교체하는 의존성을 라우트가 붙잡는 결함이 있었다(B-FP-070). 요청 시점에 `app.state.assembly`에서 꺼낸다.
- `httpx`를 직접 import하거나 `ask_view`에서 모델·그래프·저장소를 직접 부르지 마라. 이유: `httpx`는 `sources`만 허용되고 뷰 함수는 순수 함수여야 테스트로 닫힌다(AGENTS.md 계층 경계).
