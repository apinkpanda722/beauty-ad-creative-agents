# Step 1: agent-api-skeleton

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표, CRITICAL 규칙(LangGraph 상태·체크포인터·테넌트·재시도)
- `/docs/ARCHITECTURE.md` — "요청 한 번의 흐름", "스트리밍 이벤트와 화면 명령", "상태 관리", "멀티테넌트", "요청 처리 공통 장치"
- `/docs/ADR.md` — ADR-009, ADR-016
- `/docs/CONTRACTS.md` — "LangGraph" 절(체크포인터 풀 설정, `recursion_limit`)
- `/tests/fixtures/contracts/langgraph_checkpointer_probe.json` — 실측 원본(읽기 전용)
- `/tests/test_architecture.py`, `/tests/test_agent_tools.py`
- `/src/beautyads/agents/tools.py`, `/src/beautyads/domain/tools.py`, `/src/beautyads/domain/tenant.py`, `/src/beautyads/store/tenant_repository.py`, `/src/beautyads/store/connection.py`, `/src/beautyads/llm/chat.py`, `/src/beautyads/llm/prices.py`, `/src/beautyads/llm/structured.py`, `/src/beautyads/graph/connection.py`, `/src/beautyads/pipeline/preflight.py`, `/Makefile` — step 0·2·4가 만든 것과 기존 live 진입점의 점검 방식

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `pyproject.toml`, `uv.lock`, `src/beautyads/agents/state.py`(새 파일), `src/beautyads/agents/skeleton.py`(새 파일), `src/beautyads/api/__init__.py`(새 파일), `src/beautyads/api/app.py`(새 파일), `src/beautyads/api/session.py`(새 파일), `src/beautyads/api/checkpointer.py`(새 파일), `src/beautyads/api/sse.py`(새 파일), `src/beautyads/api/chat_client.py`(새 파일), `src/beautyads/eval/live_agent.py`(새 파일), `Makefile`, `README.md`, `tests/test_agent_skeleton.py`(새 파일), `tests/test_api_chat.py`(새 파일), `tests/test_api_session.py`(새 파일), `tests/test_api_chat_client.py`(새 파일), `tests/test_live_agent.py`(새 파일), `tests/test_architecture.py`, `tests/test_compose.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `pyproject.toml`(아래 `uv add`가 만드는 의존성 추가에 한함), `uv.lock`, `src/beautyads/agents/state.py`, `src/beautyads/agents/skeleton.py`, `src/beautyads/api/__init__.py`, `src/beautyads/api/app.py`, `src/beautyads/api/session.py`, `src/beautyads/api/checkpointer.py`, `src/beautyads/api/sse.py`, `src/beautyads/api/chat_client.py`, `src/beautyads/eval/live_agent.py`, `Makefile`(`live-agent` 타깃과 `.PHONY` 추가에 한함, `verify` 불변), `README.md`(live-agent 절 추가에 한함), `tests/test_agent_skeleton.py`, `tests/test_api_chat.py`, `tests/test_api_session.py`, `tests/test_api_chat_client.py`, `tests/test_live_agent.py`, `tests/test_architecture.py`(새 `api` 모듈을 반영하는 케이스 추가에 한함, 계층·SDK 표 단언 약화 금지), `tests/test_compose.py`(`Makefile` 타깃 목록을 단언한다면 `live-agent` 추가를 반영하는 갱신에 한함, 그 외 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

도구 1개와 노드 1개로 **요청 하나가 끝까지 도는 뼈대**를 만든다: FastAPI `/chat`(SSE) → 테넌트 세션 검사 → LangGraph(체크포인터, luna `reasoning_effort="none"`) → 도구 1개(`lookup_certified_products`) → 답. 에이전트 4종과 Supervisor는 이후 step이다. **이 step 안에서는 실제 접속·실행을 하지 않는다.**

**의존성(step이 지시한 `uv add`만 허용, 설치한 버전은 summary에 적는다)**: `uv add langgraph==1.2.20 langgraph-checkpoint-postgres==3.2.0 psycopg-pool==3.3.3 fastapi uvicorn`(앞의 세 개는 `docs/CONTRACTS.md` LangGraph 절의 실측 버전, 뒤 둘은 최신 안정판). 그 밖의 패키지는 추가하지 않는다. 환경 변수 `LANGGRAPH_STRICT_MSGPACK=true`를 앱 시작 시 설정한다(`os.environ.setdefault`).

**`agents/state.py`·`agents/skeleton.py`**(`agents` 계층, `fastapi` 없음): 상태는 `TypedDict`이고 **dict·기본 타입만** 담는다(pydantic 객체·`ToolResult` 객체를 상태에 넣지 않는다. 직렬화한 dict만). 키: `messages`(dict 목록), `tenant_id`, `thread_id`, `final_text`, `tool_trace`(dict 목록), `step_count`. `build_graph(*, chat, tool_runner, checkpointer)`는 노드 하나(`assistant`)로 이루어진 그래프를 컴파일해 돌려준다. `assistant`는 `llm.chat_complete(model="gpt-6-luna", reasoning_effort="none", tools=<tool_definitions 중 lookup_certified_products 한 개>)`(주입된 `chat` 함수)를 한 번 부르고, 도구 호출이 있으면 `tool_runner`(주입된 `agents.tools.run_tool` 래퍼, `ToolContext`는 서버가 세션에서 만든 것)로 실행한 뒤 도구 결과 요약을 넣어 `chat`을 한 번 더 불러 `final_text`를 만든다. 도구 실패(`ToolFailure`)는 모델에 "도구가 실패했다(코드)"로 전달하고 예외로 끊지 않는다. **`tenant_id`·`as_of`는 상태의 서버 값에서만 읽고 모델이 채우지 않는다.** 단계 수는 상태 카운터(`step_count`)로 세고 상한을 넘으면 그 시점 결과를 미완료 표시와 함께 반환한다. `recursion_limit`은 안전망으로만 설정한다.

**`api/checkpointer.py`**(`psycopg`·`langgraph` 사용 허용 계층): 체크포인터용 `AsyncConnectionPool`을 `kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0}`으로 만든다(CONTRACTS 실측: 이 세 값이 없으면 `setup()`이 실패한다). `build_checkpointer(conninfo)`는 풀을 열고 `AsyncPostgresSaver(pool)`을 돌려주며 `setup()` 호출을 함수로 분리한다(테스트는 가짜 풀로 `kwargs`만 검사한다).

**`api/session.py`**: 데모용 세션. 요청 헤더 `X-Tenant-Id`를 `domain.tenant.validate_tenant_id`로 검사하고, 서버 설정의 허용 목록(`Assembly.allowed_tenants`)에 없으면 `403 TENANT_NOT_ALLOWED`, 헤더가 없거나 형식이 틀리면 `400 TENANT_CONTEXT_MISSING`이다(**fail-closed, 요청을 거부한다**). `thread_id`가 요청에 있으면 `TenantRepository.assert_thread_access(tenant_id, thread_id)`를 **그래프 호출 전에** 부르고 `TenantMismatch`면 `403 TENANT_MISMATCH`, 없으면 `make_thread_id`로 만들어 `register_thread`한다. 본문의 어떤 필드도 테넌트를 바꾸지 못한다(본문에 `tenant_id` 필드가 있으면 `422`).

**`api/app.py`·`api/sse.py`**: `create_app(assemble: Callable[[], Assembly]) -> FastAPI`. `Assembly`(`graph`, `tenants`(`TenantRepository`), `allowed_tenants`, `as_of`, `last_collected_at`, `chat`, `tool_runner`, 종료 함수). **서비스는 앱 시작 시(`lifespan`) `assemble()`로 만들고 라우트는 `app.state.assembly`에서 요청 시점에 꺼내 쓴다**(생성 시점 값을 라우트에 붙잡지 않는다, B-FP-070). `POST /chat`(본문: `message: str`, 선택 `thread_id`)은 SSE(`text/event-stream`)로 `event: step`(에이전트 단계 시작·종료), `event: tool_start`(도구 이름·종류), `event: token`(최종 답 글자, 이 step은 완성된 답 하나를 한 번에 보낸다)을 보낸다. `ui_command`는 이 step에서 만들지 않는다(타입만 `sse.py`에 이름으로 정의). 이벤트 본문은 JSON 한 줄이고 비밀·키·응답 전문을 싣지 않는다. 예기치 못한 예외는 `event: error`(코드만)로 보내고 스트림을 닫는다. `GET /healthz`는 `{"status": "ok"}`만 돌려준다(의존 서비스를 부르지 않는다).

**`api/chat_client.py`와 `eval/live_agent.py`, `make live-agent`**(계층 규칙: `httpx`는 `sources`만, `pipeline`은 `api`를 import하지 않으므로 실행 진입점은 `api`를 import할 수 있는 `eval`에 둔다. `fastapi`는 `api`만 import하므로 앱을 한 건 호출하는 일은 `api` 안의 얇은 헬퍼가 한다):
- `api/chat_client.py`: `run_chat_once(app, *, tenant_id, message, thread_id=None) -> ChatOutcome`(`with TestClient(app) as client:` 형태로만 쓴다: `lifespan`이 실행돼 비동기 연결 풀·체크포인터가 같은 이벤트 루프에서 만들어지고 종료 때 닫힌다. 프로세스 안에서 `/chat`을 한 번 호출하고 SSE를 파싱해 `events`(이름·JSON 본문 목록), `final_text`, `status_code`를 돌려준다. `httpx`를 직접 import하지 않는다).
- `eval/live_agent.py`: 사전 점검과 실행·보고. 실제 조립(`Assembly`의 실물 버전, `api`의 `create_app`)을 만들고, 시작 전에 사전 점검을 한다(키·서비스를 값 없이 확인): `OPENAI_API_KEY`·`NEO4J_PASSWORD`·`POSTGRES_PASSWORD` 설정 여부(이름만 출력), Postgres·Neo4j 컨테이너 기동 여부(`pipeline/preflight.py`의 방식을 따른다: `eval`은 `pipeline`을 import할 수 있다), 마이그레이션 적용 여부. 하나라도 어긋나면 이유 코드를 출력하고 **호출 없이** 종료한다. 통과하면 `run_chat_once`로 데모 테넌트(`--tenant`, 기본값 없음, 필수)에 `/chat` 한 건(`--message`)을 보내고 SSE 이벤트 종류와 최종 답, 비용(장부 증가분)을 출력한다. 모델 한 호출의 비용 상한을 `--max-usd`(기본 0.02)로 두고 넘으면 호출 전에 멈춘다. `Makefile`에 `live-agent: uv run python -m beautyads.eval.live_agent $(ARGS)`를 추가하고 `.PHONY`에 넣는다(`verify`에는 넣지 않는다).

**반드시 있어야 하는 테스트**(가짜 `chat`·`tool_runner`·가짜 저장소·가짜 풀. 실제 서비스에 접속하지 않는다. 모델이 만든 문장을 기대값으로 굳히지 않는다):
- 상태: 그래프 상태 값이 dict·기본 타입뿐이다(그래프를 가짜 체인으로 돌린 뒤 모든 값의 타입을 검사). 도구 실패가 예외가 아니라 모델에 전달된다. `step_count` 상한에서 미완료 표시와 함께 끝난다. 노드가 `llm.chat_complete`를 `reasoning_effort="none"`·`model="gpt-6-luna"`로 부른다(주입된 가짜가 받은 인자를 검사). 모델에 보내는 도구 정의에 `tenant`·`user`·`date` 칸이 없다.
- 체크포인터: 풀 생성 인자의 `kwargs`가 `autocommit=True`·`row_factory=dict_row`·`prepare_threshold=0`이다. `LANGGRAPH_STRICT_MSGPACK`이 앱 시작 뒤 `"true"`다.
- 세션: 헤더 없음·형식 오류는 400, 허용 목록 밖은 403, 다른 테넌트의 `thread_id`는 403, 본문의 `tenant_id` 필드는 422이고 **모든 거부에서 그래프(호출하면 실패하는 가짜)가 불리지 않는다**. 정상 요청은 그래프를 부르고 `ToolContext.tenant_id`가 헤더 값이다.
- **서버 진입점 경유 테스트(필수)**: `create_app(assemble=<가짜 조립>)`로 만든 앱을 `lifespan`을 거쳐 시작하고, 모든 서비스 라우트(`/chat`)가 **시작 시점에 `assemble()`이 돌려준 가짜**를 부름을 단언한다. 앱 생성 뒤 `app.state.assembly`의 `graph`를 다른 가짜로 바꿔 두 번째 요청이 바뀐 가짜를 부르는 것도 단언한다(생성 시점 값을 붙잡지 않음).
- SSE: 응답 `Content-Type`이 `text/event-stream`이고 이벤트 이름 집합이 `{step, tool_start, token}`의 부분집합이며 `step`이 시작과 종료를 가진다. 본문에 키·헤더·응답 전문이 없다. 예외를 던지는 그래프에서 `event: error`가 코드만 싣고 스트림이 닫힌다. `/healthz`는 의존 서비스를 부르지 않는다.
- `run_chat_once`: **`with` 안에서 `lifespan`이 실행되고 `with`를 나갈 때 종료 처리가 돌아 풀이 닫힌다**(가짜 풀의 `open`·`close` 호출 기록으로 단언). 가짜 앱(조립 가짜)으로 SSE 이벤트 이름·본문·`final_text`를 파싱한다(실제 서비스 접속 없음). 이 모듈은 `httpx`를 직접 import하지 않는다(`tests/test_architecture.py` 통과).
- `live_agent`: 사전 점검이 키 누락·서비스 미기동·마이그레이션 미적용에서 호출 없이 이유 코드로 종료한다(가짜 점검 함수). `--tenant` 누락은 인자 오류다. `--max-usd` 초과 예상은 호출 전에 멈춘다. 출력에 키·값이 없다.
- `tests/test_architecture.py`가 통과한다(`api`는 `fastapi`·`psycopg`·`langgraph`를 쓸 수 있고, `eval`은 `api`·`pipeline`을 import하지만 `fastapi`·`httpx`는 import하지 않는다, `agents`는 `fastapi`를 import하지 않는다, `litellm`은 `llm`만).

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

- `pipeline/`에 `api`를 import하는 실행 진입점을 만들거나 `httpx`를 직접 import하지 마라. 이유: 계층 표에서 `pipeline`은 `api`를 import하지 않고 `httpx`는 `sources`만 허용한다(AGENTS.md, `tests/test_architecture.py`). 실행 진입점은 `eval/live_agent.py`, 앱 호출은 `api/chat_client.py`.
- `app = FastAPI()`를 모듈 최상위에서 만들거나 라우트가 서비스를 생성 시점에 붙잡게 하지 마라. 이유: 진입점이 시작 때 교체하는 의존성을 라우트가 붙잡아 가짜가 안 먹은 실패가 있었다(B-FP-070). `create_app(assemble)`과 `app.state`만 쓴다.
- LangGraph 상태에 pydantic 객체(`ToolResult`·`Plan` 등)를 넣지 마라. 이유: dict·기본 타입만 넣는다(AGENTS.md CRITICAL). 직렬화한 dict만 쓴다.
- 체크포인터 풀을 기본 설정으로 만들지 마라. 이유: `autocommit=True`·`row_factory=dict_row`·`prepare_threshold=0` 없이는 `setup()`이 실패한다(CONTRACTS 실측, FP-C01).
- 도구 입력이나 요청 본문에 테넌트·사용자·오늘 날짜를 받지 마라. 이유: 테넌트는 세션(헤더)이 정하고 날짜는 서버가 푼다(ADR-009). 검사가 실패하면 요청을 거부한다(fail-closed).
- 테스트가 실제 Neo4j·PostgreSQL·모델에 접속하게 하거나 `make live-agent`를 실행하지 마라. 이유: 첫 live는 사용자가 한 건으로 돌린다(AGENTS.md CRITICAL). 사전 점검은 값 없이 이름만 본다.
- `temperature`를 지정하거나 `reasoning_effort`를 생략하지 마라. 이유: luna는 추론이 기본으로 켜져 비용이 약 100배 차이난다(AGENTS.md). 노드는 `none`을 명시한다.
- `uv add`로 지시한 다섯 패키지 밖의 의존성을 추가하지 마라. 이유: 설치는 step이 지시한 것만 허용된다(AGENTS.md CRITICAL). 설치한 버전은 summary에 적는다.
