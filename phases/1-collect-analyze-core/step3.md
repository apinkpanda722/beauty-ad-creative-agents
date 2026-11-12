# Step 3: store

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P1 collect-analyze-core"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드(step 0 산출물). 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/ARCHITECTURE.md`의 "데이터 흐름" 오프라인 2·6·7번과 "상태 관리"
- `/docs/ADR.md` — ADR-010(PostgreSQL이 원본, 증분 동기화는 변경 시각으로 판정)
- `/docs/CONTRACTS.md` — "Neo4j" 절의 MERGE 반복 결과(`properties_set`이 올라가므로 "바뀐 행"을 그래프 카운터로 판정하지 않는다)
- `/src/beautyads/domain/` 전체와 `/src/beautyads/settings.py` — step 1 산출물(모델과 Protocol)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `pyproject.toml`, `uv.lock`, `src/beautyads/store/__init__.py`, `src/beautyads/store/schema.py`, `src/beautyads/store/connection.py`, `src/beautyads/store/repository.py`, `tests/test_store.py`

열람 금지 경로: (없음)
수정 허용 경로: `pyproject.toml`, `uv.lock`, `src/beautyads/store/**`, `tests/test_store.py`

이 step은 PostgreSQL 원본 저장소(`store/`)를 만든다. 테스트는 **가짜 연결**로만 하고 실제 DB에 접속하지 않는다. `uv add "psycopg[binary]"`로 의존성을 추가한다. 패키지 설치는 이 명령만 허용되고, 해석된 `psycopg` 버전을 완료 보고의 `summary`에 적는다. `store/`는 `domain`과 `settings`만 import할 수 있다.

### 연결 추상화와 구성 (`connection.py`)

```python
class SqlCursor(Protocol):
    rowcount: int
    def fetchall(self) -> list[Sequence[Any]]
    def fetchone(self) -> Sequence[Any] | None

class SqlConnection(Protocol):
    def execute(self, query: str, params: Sequence[Any] | None = None) -> SqlCursor
    def commit(self) -> None
    def rollback(self) -> None

def postgres_dsn(*, environ=None, env_file=DEFAULT_ENV_FILE) -> str   # POSTGRES_PASSWORD 필수. 호스트 127.0.0.1, 포트 기본 5433(BEAUTYADS_POSTGRES_PORT로 변경), 사용자·DB는 beautyads
class StoreConnectError(Exception):   # 속성: code ("POSTGRES_AUTH_FAILED" | "POSTGRES_CONNECT_FAILED"). 메시지에 DSN·비밀번호를 넣지 않는다
def connect(dsn: str, *, connect_fn: Callable[[str], Any] | None = None) -> SqlConnection
    # connect_fn 기본값은 psycopg.connect. psycopg의 OperationalError를 StoreConnectError로 바꾼다:
    # 메시지에 "password authentication failed"가 있거나 sqlstate가 "28P01"이면 POSTGRES_AUTH_FAILED, 그 밖은 POSTGRES_CONNECT_FAILED
```

`psycopg.Connection`이 `SqlConnection`을 만족한다(duck typing). `psycopg`는 이 파일에서만 import한다.

### 스키마와 마이그레이션 (`schema.py`)

- `MIGRATIONS`: `(version: int, name: str, sql: str)` 목록. 버전 1이 아래 테이블을 만든다. 모든 DDL은 `IF NOT EXISTS`를 쓴다.
- `apply_migrations(conn: SqlConnection) -> list[int]`: `schema_migrations(version int primary key, name text, applied_at timestamptz default now())`를 먼저 보장하고, 적용되지 않은 버전만 순서대로 적용한다. 버전마다 커밋하고 예외가 나면 롤백한 뒤 다시 올린다. **두 번째 호출은 아무것도 적용하지 않고 빈 목록을 돌려준다.**
- 테이블:
  - `creatives`: `source text`, `source_id text`, `url`, `title`, `caption`, `published_at timestamptz`, `duration_s double precision`, `language`, `analyzable boolean`(NULL 허용), 최신 지표 `latest_view_count`·`latest_like_count`·`latest_comment_count bigint`(NULL 허용)와 `metrics_collected_at timestamptz`, `first_seen_at timestamptz default now()`, `collected_at timestamptz`, **`updated_at timestamptz not null default now()`**, `PRIMARY KEY (source, source_id)`
  - `metrics_history`: `source`, `source_id`, `collected_at`, `view_count`·`like_count`·`comment_count`(NULL 허용), `PRIMARY KEY (source, source_id, collected_at)`
  - `model_outputs`: `id bigserial primary key`, `source`, `source_id`, `kind text`, `model text`, `thinking_level text`, **`prompt_version text`**, `raw_output text`, `created_at timestamptz default now()` — **모델 출력 원문을 그대로 보존**한다
  - `analysis_jobs`: `source`, `source_id`, `kind text`, `status text check (status in ('pending','done','held','failed'))`, `attempts int default 0`, `error_code text`, `labels jsonb`, `updated_at timestamptz default now()`, `PRIMARY KEY (source, source_id, kind)`
  - `sync_state`: `name text primary key`, `last_synced_at timestamptz`

### 저장소 (`repository.py`)

`PostgresCreativeStore(conn)`이 domain의 `CreativeRepository`와 `AnalysisRepository`를 모두 구현한다.

- `upsert_creatives`: 입력 안의 같은 키(출처, 원본 ID)는 마지막 것만 남긴다. `INSERT ... ON CONFLICT (source, source_id) DO UPDATE SET ... WHERE (기존 값 튜플) IS DISTINCT FROM (새 값 튜플)`로 쓰고, **`updated_at`은 값이 실제로 바뀐 행에서만 `now()`로 올라간다.** "바뀐 행"을 가르는 비교 열은 `schema.py`의 상수 `CHANGE_COLUMNS: tuple[str, ...]` 하나로 정하고 `build_upsert_sql()`이 그 상수로 `IS DISTINCT FROM` 튜플을 만든다. **`CHANGE_COLUMNS`는 정확히 내용 열 `url`, `title`, `caption`, `published_at`, `duration_s`, `language`, `analyzable`과 최신 지표 **값** 열 `latest_view_count`, `latest_like_count`, `latest_comment_count`다. `collected_at`, `first_seen_at`, `metrics_collected_at`, `updated_at`은 포함하지 않는다**(수집 시각은 재수집할 때마다 달라지므로 넣으면 모든 행의 `updated_at`이 올라 증분 동기화가 무력해진다). 같은 입력을 다시 넣으면 `updated_at`이 바뀌지 않는다(증분 동기화가 이 시각으로 "바뀐 행"을 판정한다). 지표는 `metrics_history`에 `ON CONFLICT DO NOTHING`으로 이력을 쌓고, 최신 지표 컬럼은 새 `collected_at`이 기존 `metrics_collected_at` 이상일 때만 갱신한다. 돌려주는 값은 처리한 고유 소재 수.
- `get_creative`: 없으면 `None`. 행을 `Creative`로 되돌릴 때 **NULL은 `None`으로** 복원한다(0이나 빈 문자열로 바꾸지 않는다). 컬럼 순서는 상수 튜플로 고정한다.
- `enqueue_analysis(kind, creatives)`: **`is_analyzable`인 소재만** `analysis_jobs`에 `status='pending'`으로 `ON CONFLICT (source, source_id, kind) DO NOTHING` 삽입한다. 이미 있는 작업은 상태를 건드리지 않는다. 넣은 수를 돌려준다.
- `next_pending(kind, limit)`: `pending` 작업의 소재를 게시 시각 최신순(NULL 마지막)으로 최대 `limit`개 돌려준다.
- `record_analysis(...)`: `raw_output`이 있으면 `model_outputs`에 한 줄 추가(`prompt_version` 포함)하고, `analysis_jobs`의 `status`·`error_code`·`labels`를 갱신하며 `attempts`를 1 올리고 `updated_at`을 갱신한다.
- **모든 값은 `%s` 매개변수로 전달한다.** SQL 문자열에 값을 이어 붙이지 않는다. 쓰기 메서드는 성공 시 `commit()`, 예외 시 `rollback()` 후 다시 올린다.

### 반드시 있어야 하는 테스트 (`tests/test_store.py`, 가짜 연결만)

가짜 연결은 `(query, params)`를 기록하고 `fetchall/fetchone` 결과를 미리 정한 대로 돌려준다.

- `apply_migrations`: 첫 호출은 버전을 적용하고, 이미 적용된 버전을 가짜가 돌려주면 두 번째 호출은 빈 목록. 마이그레이션 SQL에 `DROP`·`TRUNCATE`가 없고 모든 `CREATE`가 `IF NOT EXISTS`를 쓴다. 중간 실패 시 `rollback`이 호출된다.
- `upsert_creatives`: 제목에 따옴표·세미콜론(예: `O'Brien"; DROP TABLE creatives; --`)이 든 소재를 넣어도 **SQL 문자열에는 그 값이 없고 `params`에만 있다**. 입력 안 중복 키는 한 건으로 합쳐진다. SQL에 `IS DISTINCT FROM`이 있고 `updated_at`을 무조건 올리는 형태가 아니다. 통계가 없는 소재(`None`)의 `params`에 0이 들어가지 않는다.
- `enqueue_analysis`: `analyzable`이 `True`인 소재만 삽입 대상이 되고 `None`·`False`는 제외된다. 반환값이 실제 삽입 시도 수와 같다.
- `get_creative`·`next_pending`: 가짜가 돌려준 행(NULL 포함)이 `Creative`로 복원되고 NULL이 `None`이다.
- `record_analysis`: `raw_output`이 `None`이면 `model_outputs` 삽입이 없다. `status`가 `JobStatus`의 문자열 값으로 전달된다.
- `postgres_dsn`: `POSTGRES_PASSWORD`가 없거나 공백이면 `MissingSetting`, 포트 기본값 5433, `BEAUTYADS_POSTGRES_PORT`로 변경(임시 환경 딕셔너리).
- **`CHANGE_COLUMNS`**: 위 열 목록과 정확히 같은 집합이고(테스트가 기대 목록을 직접 적는다), `collected_at`·`first_seen_at`·`metrics_collected_at`·`updated_at`이 들어 있지 않다. `build_upsert_sql()`의 `WHERE` 이후 부분에 그 제외 열 이름이 나타나지 않고, 포함 열 이름은 모두 나타난다. 수집 시각만 다른 같은 소재를 두 번 넣었을 때 `IS DISTINCT FROM` 비교에 시각 열이 관여하지 않음이 위 단언으로 보장된다.
- **`prompt_version`**: `record_analysis`에 넘긴 값이 `model_outputs` 삽입 매개변수에 들어가고, `None`이면 NULL로 전달된다.
- **`connect` 오류 변환**: `connect_fn`이 `psycopg.OperationalError("... password authentication failed for user ...")`를 올리면 `POSTGRES_AUTH_FAILED`, 다른 `OperationalError`(예: `connection refused`)는 `POSTGRES_CONNECT_FAILED`. 어느 경우에도 `StoreConnectError`의 메시지와 `repr`에 DSN과 비밀번호 문자열이 없다.

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

- SQL 문자열에 값을 이어 붙이지 마라(f-string·`%`·`+`로 값을 넣지 않는다). 모든 값은 매개변수로 전달한다. 이유: 따옴표가 들어간 캡션이 쿼리를 깨뜨리거나 주입된다.
- 소재의 중복 제거 키를 (출처, 원본 ID) 하나로 쓰고 같은 키를 결과(작업·출력)의 키로도 써라. 이유: 중복 제거 키와 출력 키가 다르면 같은 소재가 두 번 분석된다(A-FP-033).
- `updated_at`을 값이 바뀌지 않았는데 올리지 마라(수집 시각 열은 비교에 넣지 않는다). 이유: 증분 동기화가 이 시각으로 바뀐 행을 판정하며, 그래프 카운터로는 판정할 수 없다(`docs/CONTRACTS.md` Neo4j: 같은 값을 MERGE해도 `properties_set`이 올라간다).
- 마이그레이션에 `DROP`·`TRUNCATE`를 쓰지 마라. 이유: 이 저장소가 모든 데이터의 원본이다(ADR-010).
- NULL 통계를 0으로, NULL `analyzable`을 `false`로 바꿔 저장하지 마라. 이유: 값 없음과 0·거짓은 의미가 다르고 표본 추출이 `analyzable == true`만 쓴다.
- 지시한 `uv add` 외의 패키지를 설치하거나 `pyproject.toml`에 다른 의존성을 추가하지 마라. 이유: 의존성 변경은 `uv.lock`과 함께 검토 대상이고 계층 가드의 SDK 표가 모르는 패키지는 검증되지 않는다.
