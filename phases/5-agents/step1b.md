# Step 1b: db-migrate

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`pipeline`은 `store`·`settings` import 가능, `psycopg`는 `store`·`api`만), CRITICAL 규칙(비밀 값, 실제 서비스 접속 금지)
- `/docs/ARCHITECTURE.md` — "상태 관리"
- `/src/beautyads/store/connection.py`, `/src/beautyads/store/schema.py`, `/src/beautyads/pipeline/products.py`(`_live_deps`의 접속·마이그레이션 방식), `/src/beautyads/pipeline/preflight.py`, `/src/beautyads/eval/live_agent.py`(`MIGRATIONS_PENDING` 처리), `/tests/test_live_agent.py`, `/tests/test_store.py`, `/Makefile`, `/tests/test_architecture.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/pipeline/migrate.py`(새 파일), `src/beautyads/eval/live_agent.py`, `Makefile`, `README.md`, `tests/test_migrate.py`(새 파일), `tests/test_live_agent.py`, `tests/test_compose.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/pipeline/migrate.py`, `src/beautyads/eval/live_agent.py`(`MIGRATIONS_PENDING` 안내 문구 추가에 한함, `preflight()`가 돌려주는 코드 목록과 기존 동작 불변), `Makefile`(`db-migrate` 타깃과 `.PHONY` 추가에 한함, `verify` 불변), `README.md`(db-migrate 절 추가에 한함), `tests/test_migrate.py`, `tests/test_live_agent.py`(케이스 추가에 한함, 단언 약화 금지), `tests/test_compose.py`(`Makefile` 타깃 목록을 단언한다면 `db-migrate` 추가를 반영하는 갱신에 한함, 그 외 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

마이그레이션만 적용하는 가벼운 명령 `make db-migrate`를 만든다. 지금은 수집·분석 파이프라인을 돌려야만 마이그레이션이 적용돼서 `make live-agent`가 `MIGRATIONS_PENDING`에서 멈춘다. **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

**`pipeline/migrate.py`**: `main(argv=None, *, environ=None, env_file=DEFAULT_ENV_FILE, out=None, connect_fn=connect, apply_fn=apply_migrations) -> int`(`connect`·`postgres_dsn`·`apply_migrations`는 `store`에서, 설정은 `settings`에서 읽는다. `pipeline`은 `psycopg`를 import하지 않는다).
- `POSTGRES_PASSWORD`가 설정돼 있지 않으면(`settings`의 한 함수로 읽는다, 이름만 출력) `PREFLIGHT_FAILED ENV_MISSING:POSTGRES_PASSWORD`를 출력하고 종료 코드 2로 끝낸다(접속하지 않는다).
- 접속은 `connect_fn(postgres_dsn(...))`이다. 접속 실패는 예외 종류·메시지·DSN·비밀번호를 **출력하지 않고** `PREFLIGHT_FAILED POSTGRES_UNREACHABLE`만 출력해 종료 코드 2로 끝낸다(`psycopg`를 import하지 않으므로 접속 단계의 예외를 `Exception`으로 잡되, 접속 이후 `apply_fn`의 예외는 잡지 않고 그대로 올라가게 한다).
- 성공하면 `apply_fn(connection)`이 돌려준 적용된 버전 목록**만** 한 줄로 출력한다: `MIGRATIONS_APPLIED [4, 5, 6, 7]` 형식(정수 목록, 이미 모두 적용돼 있으면 `MIGRATIONS_APPLIED []`). 종료 코드 0. 다른 값·키·DSN·호스트를 출력하지 않는다. 연결은 항상 닫는다(`finally`). 반복 실행해도 결과가 같다(`apply_migrations`가 멱등이다).
- `python -m beautyads.pipeline.migrate`로 실행된다.

**`eval/live_agent.py`**: 사전 점검 실패 출력이 `MIGRATIONS_PENDING`을 포함하면 같은 줄이나 다음 줄에 "make db-migrate를 실행하라"를 덧붙인다. `preflight()`가 돌려주는 코드 목록(`["MIGRATIONS_PENDING"]` 등)은 바꾸지 않는다(기존 테스트가 코드를 단언한다).

**`Makefile`**: `db-migrate: uv run python -m beautyads.pipeline.migrate`와 `.PHONY`. `verify`에는 넣지 않는다.

**반드시 있어야 하는 테스트**(가짜 `connect_fn`·`apply_fn`, 실제 접속 없음):
- 성공: `apply_fn`이 `[4, 5, 6, 7]`을 돌려주면 출력이 정확히 `MIGRATIONS_APPLIED [4, 5, 6, 7]`이고 종료 코드 0, `[]`이면 `MIGRATIONS_APPLIED []`. 연결이 닫힌다(`apply_fn`이 예외를 던져도 닫힌다).
- 환경 변수 누락(`POSTGRES_PASSWORD`)은 접속 시도 없이 `PREFLIGHT_FAILED ENV_MISSING:POSTGRES_PASSWORD`, 종료 코드 2. 빈 문자열·공백도 누락으로 본다.
- 접속 실패(가짜 `connect_fn`이 임의의 예외를 던짐)는 종료 코드 2와 `PREFLIGHT_FAILED POSTGRES_UNREACHABLE`뿐이고 예외 메시지(합성 비밀번호·DSN 문자열을 담아 던져 본다)가 출력에 없다.
- 출력 전체에 합성 비밀번호·`postgresql://`·호스트가 없다(모든 경로).
- `live_agent`: `MIGRATIONS_PENDING` 출력에 `make db-migrate`가 있고 `preflight()`의 반환 코드는 그대로다. 다른 코드에는 안내가 없다.
- `tests/test_architecture.py`가 통과한다(`pipeline`은 `store`·`settings`만 쓰고 `psycopg`를 import하지 않는다).

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

- 예외 메시지·DSN·비밀번호·호스트를 출력하거나 로그에 남기지 마라. 이유: DSN에 비밀번호가 들어간다(AGENTS.md CRITICAL 비밀 값). 출력은 코드와 적용 버전 목록뿐이다.
- `pipeline/`에서 `psycopg`를 import하지 마라. 이유: 계층 표에서 `psycopg`는 `store`·`api`만 허용한다. 접속은 `store.connection.connect`를 거친다.
- `apply_migrations` 호출 이후의 예외를 삼키지 마라. 이유: 마이그레이션 실패는 숨기면 안 된다(실패를 "적용 없음"으로 오인하는 FP-C05 유형).
- `make db-migrate`를 실행하거나 실제 Postgres에 접속하는 테스트를 만들지 마라. 이유: 실제 접속은 사용자가 한다(AGENTS.md CRITICAL).
- `eval/live_agent.py`의 `preflight()` 반환 코드와 기존 테스트 단언을 바꾸지 마라. 이유: step 1 테스트가 코드 문자열을 단언한다. 안내 문구는 출력 쪽에만 덧붙인다.
