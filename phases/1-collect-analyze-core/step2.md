# Step 2: compose

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P1 collect-analyze-core"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드(step 0 산출물). 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/ADR.md` — ADR-007(로컬 실행), ADR-010(PostgreSQL 원본)
- `/docs/CONTRACTS.md` — "Neo4j" 절(이미지 태그, 첫 live 함정: 비밀번호는 첫 볼륨에만 적용, 8자 미만이면 기동 실패)와 LangGraph 절의 `postgres:17.11` 언급
- `/Makefile`, `/.env.example`(키 이름만)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `deploy/docker-compose.yml`, `Makefile`, `tests/test_compose.py`, `pyproject.toml`, `uv.lock`

열람 금지 경로: (없음)
수정 허용 경로: `deploy/docker-compose.yml`, `Makefile`(`db-up`·`db-down`·`graph-reset` 타깃과 `.PHONY` 추가에 한함, `verify` 타깃 불변), `tests/test_compose.py`, `pyproject.toml`, `uv.lock`

이 step은 로컬 개발용 PostgreSQL과 Neo4j를 띄우는 compose 파일과 Makefile 타깃을 만든다. 이 step의 테스트는 compose 파일을 **파싱**만 하고 컨테이너를 띄우지 않는다. `uv add pyyaml`로 의존성을 추가한다(이후 step의 설정 로더도 쓴다). 패키지 설치는 이 명령만 허용되고, 해석된 `pyyaml` 버전을 완료 보고의 `summary`에 적는다.

소비자 테스트 점검 결과: `scripts/test_hooks.py`가 `Makefile`을 언급하지만 임시 디렉터리에 자기 `Makefile`을 만들어 쓰므로 저장소 `Makefile` 변경의 영향을 받지 않는다(확인함). 그 파일은 수정하지 않는다.

### deploy/docker-compose.yml

- 최상위 `name: beautyads`.
- 서비스 `postgres`: 이미지 `postgres:17.11`, 컨테이너 이름 `beautyads-postgres`, 환경 `POSTGRES_USER: beautyads`, `POSTGRES_DB: beautyads`, `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD가 .env에 필요하다}`, 포트 `127.0.0.1:5433:5432`, 이름 있는 볼륨 `beautyads_pgdata`(`/var/lib/postgresql/data`), `pg_isready -U beautyads -d beautyads`를 쓰는 `healthcheck`.
- 서비스 `neo4j`: 이미지 `neo4j:2026.10.1-community`, 컨테이너 이름 `beautyads-neo4j`, 환경 `NEO4J_AUTH: neo4j/${NEO4J_PASSWORD:?NEO4J_PASSWORD가 .env에 필요하다(8자 이상)}`, 포트 `127.0.0.1:7475:7474`와 `127.0.0.1:7688:7687`, 이름 있는 볼륨 `beautyads_neo4j_data`(`/data`). 이 이미지에 healthcheck 도구가 있는지 실측하지 않았으므로 neo4j에는 healthcheck를 두지 않는다.
- 이름 있는 볼륨은 최상위 `volumes:`에서 `name:`으로 `beautyads_pgdata`, `beautyads_neo4j_data`를 명시한다.
- Langfuse(`obs` profile) 서비스는 이 step에서 만들지 않는다(P5).

### Makefile 타깃 (기존 `verify` 타깃과 `.PHONY` 줄은 유지하며 새 타깃 이름만 `.PHONY`에 추가)

```make
COMPOSE := docker compose --env-file .env -f deploy/docker-compose.yml
db-up:        # $(COMPOSE) up -d postgres neo4j
db-down:      # $(COMPOSE) down   (볼륨은 지우지 않는다)
graph-reset:  # CONFIRM=yes 가 아니면 메시지를 출력하고 실패 종료. 맞으면 neo4j 컨테이너를 내리고 볼륨 beautyads_neo4j_data를 삭제
```

- `graph-reset`은 첫 줄에서 `CONFIRM` 값을 검사해 `yes`가 아니면 `GRAPH_RESET_NOT_CONFIRMED: make graph-reset CONFIRM=yes`를 출력하고 종료 코드 1로 끝낸다. 볼륨 삭제 명령은 그 검사 **뒤에** 온다. **PostgreSQL 볼륨(`beautyads_pgdata`)을 지우는 타깃은 만들지 않는다.** (Neo4j 비밀번호는 데이터 볼륨을 처음 만들 때만 적용되므로, `.env`의 비밀번호를 바꾼 뒤 인증이 실패하면 이 타깃으로 볼륨을 지운다. 그래프는 PostgreSQL에서 다시 만들 수 있는 파생물이다.)

### 반드시 있어야 하는 테스트 (`tests/test_compose.py`)

compose 파일은 `yaml.safe_load`로, Makefile은 텍스트로 읽는다.

- 서비스 집합이 `{"postgres", "neo4j"}`를 **포함**한다(이후 phase가 서비스를 추가하므로 정확 일치로 단언하지 않는다).
- 모든 서비스 이미지에 명시적 태그가 있고 태그가 `latest`가 아니다.
- 호스트 포트가 B 프로젝트 스택의 기본 포트 `5432`, `3000`, `7474`, `7687`과 겹치지 않고, 모든 포트 매핑이 `127.0.0.1:`로 시작한다.
- 비밀번호 환경 변수가 `${...}` 참조이고 평문 값이 아니다(`POSTGRES_PASSWORD`, `NEO4J_AUTH`).
- 컨테이너 이름이 `beautyads-`로, 볼륨 이름이 `beautyads_`로 시작한다.
- Makefile에 `db-up`, `db-down`, `graph-reset` 타깃이 있고, `graph-reset` 레시피에서 `CONFIRM` 검사가 볼륨 삭제 명령보다 앞에 있으며, `verify` 레시피 줄에 `db-`·`graph-`·`live-`가 들어 있지 않다. Makefile 어디에도 `beautyads_pgdata` 문자열이 없다(PostgreSQL 볼륨을 지우는 타깃이 없음).

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

- 이미지를 `latest`나 태그 없이 쓰지 마라. 이유: 버전이 바뀌면 재현이 깨진다. 이 프로젝트는 `postgres:17.11`과 `neo4j:2026.10.1-community`를 실측했다(`docs/CONTRACTS.md`).
- B 프로젝트 스택 기본 포트(5432·3000·7474·7687)와 겹치는 호스트 포트를 쓰지 마라. 모든 포트는 `127.0.0.1`에만 바인딩한다. 이유: B 스택과 동시에 켜도 충돌하지 않게 하고 로컬 데이터가 외부에 노출되지 않게 한다.
- 비밀번호를 compose 파일에 평문으로 쓰지 마라. `.env` 변수 참조(`${...:?...}`)만 쓴다. 이유: 비밀 값이 저장소에 들어가는 것을 막는다.
- `docker compose up`과 `docker volume rm`을 실행하지 마라. 테스트는 파일을 파싱할 뿐이다. 이유: 실제 서비스를 띄우는 것은 사용자의 live 실행이다.
- `graph-reset`이 확인 없이 볼륨을 지우게 하지 마라(`CONFIRM=yes` 검사가 삭제 명령보다 먼저 와야 한다). PostgreSQL 볼륨을 지우는 타깃은 아예 만들지 마라. 이유: 그래프는 파생물이지만 PostgreSQL은 모든 데이터의 원본이라 실수 비용이 크다.
- 지시한 `uv add` 외의 패키지를 설치하거나 `pyproject.toml`에 다른 의존성을 추가하지 마라. 이유: 의존성 변경은 `uv.lock`과 함께 검토 대상이고 계층 가드의 SDK 표가 모르는 패키지는 검증되지 않는다.
