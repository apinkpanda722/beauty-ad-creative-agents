# Step 1: serve-entry

## 설계 검토 기록

**배경(P7 설계 승인 a)**: 지금 저장소에는 FastAPI 앱을 띄우는 진입점이 없다. `create_app`은 `eval/agents_live.py`·`eval/clarify_demo.py`가 프로세스 안에서만 부르고, `uvicorn`은 `pyproject.toml` 의존성에만 있다(코드 어디에도 import가 없다, 2026-11-20 확인). 화면(Next.js)이 붙으려면 사용자가 한 줄로 서버를 띄울 수 있어야 한다. 이 step은 **서버 기동 진입점과 `make serve`**만 만든다. 라우트·SSE 계약·`assemble_full`은 바꾸지 않는다.

**식별자 대조(현재 코드, 모두 열어 확인)**:
- `api/app.py`: `create_app(assemble: Callable[[], Assembly]) -> FastAPI`(조립 함수는 lifespan 안에서 호출, 값이 awaitable이면 await). `Assembly`는 이 step에서 바꾸지 않는다.
- `api/assembly.py`: `async def assemble_full(*, settings, workspaces_path=Path("config/workspaces.yaml"), group="dev", models=None, connect_fn=..., graph_fn=..., saver_fn=..., environ=None, env_file=DEFAULT_ENV_FILE, limits=_DEFAULT_LIMITS, with_image_enabled=False, evaluation_model="claude-haiku-5-5", trace_path=None) -> Assembly`. `group`은 `"dev" | "test" | "isolation"`만, `evaluation_model`은 `"claude-haiku-5-5" | "claude-sonnet-5-5"`만 받고 아니면 `ValueError`. 시작 실패는 `RuntimeError("ASSEMBLY_FAILED")`로 올라온다.
- `settings.py`: `get_setting(name, default=None, *, environ=None, env_file=DEFAULT_ENV_FILE)`(미설정·빈 문자열·공백은 기본값), `load_settings(*, environ=None, env_file=DEFAULT_ENV_FILE) -> Settings`, `InvalidSetting(name)`, `DEFAULT_ENV_FILE`.
- `eval/agents_live.py:446-455`: 같은 호출 모양(`create_app(partial(assemble, settings=..., group="dev", evaluation_model=..., with_image_enabled=..., limits=...))`)이 이미 쓰인다(읽기 전용 참고).
- 서버 포트: 기본 8000(Next 개발 서버는 3000). compose는 Postgres 5433·Neo4j 7688/7475를 쓴다(`deploy/docker-compose.yml`)라 충돌이 없다.

**설계 결정**:
- 새 환경 변수 네 개를 **`settings.get_setting`으로만** 읽는다(`os.environ` 직접 읽기 금지, B-FP-030): `BEAUTYADS_GROUP`(기본 `dev`, 허용 `dev`·`test`. `isolation`은 격리 검사 전용이라 서버로 띄우지 않는다), `BEAUTYADS_EVAL_MODEL`(기본 `claude-haiku-5-5`, 허용 `claude-haiku-5-5`·`claude-sonnet-5-5`), `BEAUTYADS_WITH_IMAGE`(`1`/`0`, 기본 `0`), `BEAUTYADS_API_PORT`(기본 `8000`, 1024~65535 정수). 허용 밖의 값은 `InvalidSetting(변수 이름)`이고 **값을 메시지에 넣지 않는다**.
- 호스트는 `127.0.0.1` 고정이다(ADR-007: 로컬 실행, 외부 노출 없음).
- 서버를 띄우는 것은 모델 호출이 아니다. 화면에서 요청을 보내는 것이 비용 승인이고 기존 원장 상한 검사는 그대로다(P7 승인 Q8).
- 개발은 `dev`, 시연은 `test`로 **서버를 다시 시작**한다(한 프로세스가 한 그룹만 로드, P7 승인 Q9).

**기존 단언과의 충돌 점검**: 새 모듈·새 Makefile 타깃·`.env.example` 주석만 더한다. `verify` 레시피는 바꾸지 않는다(소비자: `tests/test_pilot.py`·`tests/test_compose.py`·`tests/test_clarify_demo.py` 등이 `verify` 본문을 정확 일치·부분 문자열로 검사한다). 새 타깃은 `demo-clarify`처럼 별도 `.PHONY: serve` 블록으로 더하고 맨 윗줄 `.PHONY:` 목록은 건드리지 않는다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`(계층 경계, CRITICAL: 비밀 값·실제 호출)
- `/docs/ARCHITECTURE.md`(실행 환경), `/docs/ADR.md`(ADR-007, ADR-009)
- `/src/beautyads/api/app.py`, `/src/beautyads/api/assembly.py`(`assemble_full` 시그니처와 앞부분만)
- `/src/beautyads/settings.py`, `/src/beautyads/eval/agents_live.py`(445~455행 `create_app(partial(...))` 호출 모양만, 읽기 전용)
- `/tests/test_api_chat.py`(`assembly()` 헬퍼), `/tests/test_api_ask.py`(`services(ask)` 헬퍼), `/tests/test_architecture.py`, `/tests/test_clarify_demo.py`(`test_make_target_leaves_verify_offline`)
- `/Makefile`, `/.env.example`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/api/main.py`, `Makefile`, `.env.example`, `tests/test_api_main.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `src/beautyads/api/main.py`, `Makefile`, `.env.example`, `tests/test_api_main.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1. `src/beautyads/api/main.py`(새 파일)**
- `def build_app(*, environ=None, env_file=DEFAULT_ENV_FILE, assemble=assemble_full) -> FastAPI`: 위 네 변수 중 그룹·평가 모델·이미지를 읽고 검증한 뒤 `create_app(partial(assemble, settings=load_settings(environ=environ, env_file=env_file), group=..., evaluation_model=..., with_image_enabled=..., environ=environ, env_file=env_file))`를 돌려준다. **`build_app`은 조립을 호출하지 않는다**(조립은 `create_app`의 lifespan이 서버 시작 때 호출한다). `assemble` 인자는 테스트가 가짜 조립을 주입하는 자리다.
- `def server_port(*, environ=None, env_file=DEFAULT_ENV_FILE) -> int`: `BEAUTYADS_API_PORT` 검증.
- `def main() -> None`: 시작 줄 한 줄을 출력한다(`SERVE group=<그룹> eval_model=<모델> image=<on|off> url=http://127.0.0.1:<포트>`; 키·경로·환경 값 원문 없음) 다음 `uvicorn.run(build_app(), host="127.0.0.1", port=server_port())`. `if __name__ == "__main__": main()`.
- 설정 오류(`InvalidSetting`)는 `SERVE_FAILED INVALID_SETTING:<변수 이름>` 한 줄을 출력하고 종료 코드 2로 끝난다. 그 밖의 시작 실패는 uvicorn이 lifespan 예외로 처리하게 둔다(예외 메시지를 가리거나 다시 쓰지 않는다. `assemble_full`이 이미 자격 증명 없는 `RuntimeError("ASSEMBLY_FAILED")`만 올린다).

**2. `Makefile`**: 파일 끝에 `.PHONY: serve` / `serve:` / `\tuv run python -m beautyads.api.main`을 더한다(`demo-clarify` 블록 모양). 사용 예를 한 줄 주석으로 둔다(`make serve`, `make serve BEAUTYADS_GROUP=test BEAUTYADS_EVAL_MODEL=claude-sonnet-5-5 BEAUTYADS_WITH_IMAGE=1`; make 명령행 변수는 환경 변수로 전달된다). 기존 줄·`verify` 레시피는 바꾸지 않는다.

**3. `.env.example`**: 이름만 주석으로 더한다(`# BEAUTYADS_GROUP=`, `# BEAUTYADS_EVAL_MODEL=`, `# BEAUTYADS_WITH_IMAGE=`, `# BEAUTYADS_API_PORT=`). 값은 적지 않는다.

**테스트(`tests/test_api_main.py`, 합성 데이터, 서비스·키·네트워크·`.env` 없음)**
1. 기본값: `environ={}`(그리고 빈 문자열·공백뿐인 값)일 때 주입한 가짜 조립이 `group="dev"`, `evaluation_model="claude-haiku-5-5"`, `with_image_enabled is False`로 호출된다(B-FP-030). `env_file=None`으로 실제 `.env`를 읽지 않게 한다.
2. 값 전달: `{"BEAUTYADS_GROUP": "test", "BEAUTYADS_EVAL_MODEL": "claude-sonnet-5-5", "BEAUTYADS_WITH_IMAGE": "1"}`가 그대로 전달된다. 가짜 조립은 키워드 인자 `settings`, `group`, `evaluation_model`, `with_image_enabled`, `environ`, `env_file`을 받는다.
3. 검증: `isolation`·알 수 없는 그룹·허용 밖의 평가 모델·`2`·`yes` 같은 이미지 값·`80`·`abc`·`70000` 같은 포트는 `InvalidSetting`이고 **예외 문자열에 입력 값이 없다**.
4. 실제 진입점 경유(B-FP-070): `TestClient(build_app(environ=..., env_file=None, assemble=fake))`에서 `build_app`을 부른 시점에는 가짜 조립이 호출되지 않고 `with TestClient(app)`로 시작한 뒤 한 번 호출된다. `/healthz`가 200이고, `tests/test_api_ask.py`의 `services(ask)` 형식의 가짜 `Assembly`로 `POST /ask`가 그 가짜의 `ask`에 도달한다.
5. `main()`: `uvicorn.run`을 가짜로 바꿔(`monkeypatch`) 호스트가 `127.0.0.1`이고 포트가 설정을 따르며, 출력에 키 문자열(테스트가 넣은 합성 비밀 값)이 없다. 잘못된 설정이면 `SERVE_FAILED INVALID_SETTING:BEAUTYADS_GROUP`을 출력하고 종료 코드 2.
6. Makefile: `.PHONY: serve\nserve:\n\tuv run python -m beautyads.api.main` 블록이 있고 `verify` 본문에 `serve`가 없다.
- 합성 문장·분류 값을 기대값으로 굳히지 않는다.

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
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약(설치한 패키지 버전 포함, 승인 목록에서 조정한 것은 이유까지)"`
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

- `make serve`와 `uv run python -m beautyads.api.main`을 실행하지 마라. 이유: 서버는 시작할 때 PostgreSQL·Neo4j에 접속하므로 실제 서비스 접속이다. 서버 기동은 사용자가 한다(AGENTS.md CRITICAL, A-FP-040). 시작 경로는 가짜 조립 주입 테스트로만 검증한다.
- 호스트를 `0.0.0.0`이나 환경 변수로 바꿀 수 있게 만들지 마라. 이유: 로컬 전용 실행이다(ADR-007).
- `os.environ`·`os.getenv`로 새 변수를 직접 읽지 마라. 이유: `.env`를 읽는 유일한 함수가 `settings`이고, 직접 읽으면 빈 문자열이 기본값을 덮는다(B-FP-030).
- `eval/` 모듈(예: `live_agent.preflight`)을 import하지 마라. 이유: `eval`은 `api`를 import하는 계층이고 `api`는 `eval`을 import하지 않는다(AGENTS.md 계층 경계, `tests/test_architecture.py`).
- `create_app`·`assemble_full`·`Assembly`·기존 라우트를 수정하지 마라. 이유: 이 step의 범위는 기동 진입점뿐이다. 서버 계약 추가는 step 2·3이 한다.
