# Step 4: tenant-memory

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`store`는 `domain`·`settings`만), CRITICAL 규칙(테넌트·체크포인터)
- `/docs/ARCHITECTURE.md` — "상태 관리", "멀티테넌트", "컨텍스트 관리"(피드백·근거 ID 고정 칸)
- `/docs/ADR.md` — ADR-009(테넌트), ADR-012
- `/docs/COMPETENCY_QUESTIONS.md` — CQ-12(Feedback 노드 형태), CQ-13~16("우리 제품"은 작업 공간 프로필)
- `/tests/test_architecture.py`
- `/src/beautyads/store/schema.py`, `/src/beautyads/store/repository.py`, `/src/beautyads/store/product_repository.py`, `/src/beautyads/store/connection.py`, `/tests/test_store.py`, `/tests/test_product_store.py`, `/src/beautyads/domain/tools.py`(step 2의 `PriceBand`), `/src/beautyads/domain/labels.py` — 저장소 스타일과 마이그레이션 규칙

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/tenant.py`(새 파일), `src/beautyads/store/tenant_repository.py`(새 파일), `src/beautyads/store/schema.py`, `src/beautyads/store/__init__.py`, `tests/test_tenant_domain.py`(새 파일), `tests/test_tenant_repository.py`(새 파일), `tests/test_store.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/tenant.py`, `src/beautyads/store/tenant_repository.py`, `src/beautyads/store/schema.py`(마이그레이션 추가에 한함, 기존 마이그레이션·테스트 단언 불변), `src/beautyads/store/__init__.py`(export 추가에 한함), `tests/test_tenant_domain.py`, `tests/test_tenant_repository.py`, `tests/test_store.py`(새 마이그레이션 버전을 반영하는 데 필요한 기대값의 갱신과 케이스 추가에 한함. 이 갱신 외에 단언을 약화하거나 삭제하지 않는다. 갱신은 `apply_migrations(conn) == [4, 5, 6]`, `conn.commits == 3`, 버전 1~6 적용 완료 픽스처의 세 곳으로 한정하고, 갱신한 줄은 새 버전 목록을 기존 목록 + 7로 정확히 표현한다(`>=` 같은 느슨한 비교나 길이만 보는 단언으로 바꾸지 않는다))
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

테넌트 전용 데이터(작업 공간 프로필·기획안·피드백·thread 소유)를 PostgreSQL에 두고, 모든 읽기·쓰기가 `tenant_id`로 범위를 건다. **이 step은 PostgreSQL 저장소와 도메인 타입까지만 만든다.** Neo4j `Feedback` 적재는 이 step에서 만들지 않는다. **이 step 안에서는 실제 접속·실행을 하지 않는다.**

**`domain/tenant.py`**(표준 라이브러리·pydantic만):
- `validate_tenant_id(value) -> str`: 패턴 `^[a-z0-9][a-z0-9_-]{1,31}$`, 아니면 `TenantContextMissing`(예외, 코드 `TENANT_CONTEXT_MISSING`). `TenantMismatch`(코드 `TENANT_MISMATCH`)도 정의한다.
- `make_thread_id(tenant_id) -> str`: `"{tenant_id}:{uuid4 hex}"`. `thread_tenant(thread_id) -> str | None`: `:` 앞 값(패턴이 맞을 때만, 아니면 `None`).
- `WorkspaceProfile`(`tenant_id`, `display_name`, `brand`, `own_product_url`, `tone`, `forbidden_terms: list[str]`, `price_band_pct: float` 기본 30.0, `0 < pct <= 100`). 순수 함수 `price_band(unit_list_price: float, pct: float) -> PriceBand`(`PriceBand`는 step 2의 `domain/tools.py`, 단위당 정가 × (1 ± pct/100), 정가가 0 이하이면 `ValueError`).
- `FeedbackDecision`(StrEnum `approved`·`rejected`), `Feedback`(`tenant_id`, `plan_id`, `decision`, `reason: str`, `hook_type: HookType | None`, `claims: list[Claim]`, `created_at: datetime`), `PlanRecord`(`tenant_id`, `plan_id`, `thread_id`, `payload: dict`, `created_at`).
- `summarize_feedback(feedbacks: Sequence[Feedback], *, as_of: date, window_days: int = 90, max_reasons: int = 10) -> FeedbackSummary`: 순수 함수. `rejected`·`approved` 각각의 훅 유형·효능별 건수와, 반려 사유 원문을 최신순 `max_reasons`개까지 **줄이거나 바꾸지 않고** 담는다(컨텍스트 관리: 피드백은 요약에서 빠지지 않는 별도 칸). `as_of`는 서버가 주며 윈도 밖 피드백은 제외한다.
- `TenantRepository`(`Protocol`): 모든 메서드의 **첫 인자가 `tenant_id`**다. `save_profile`·`get_profile`, `save_plan`·`get_plan(tenant_id, plan_id)`, `add_feedback`·`list_feedback(tenant_id, *, decision=None, since=None, limit)`, `register_thread(tenant_id, thread_id)`, `assert_thread_access(tenant_id, thread_id)`.

**`store/schema.py`**: `MIGRATIONS`에 **새 버전(현재 마지막 번호 + 1)** `tenant_memory`를 추가한다. 기존 항목은 고치지 않는다. 모두 `CREATE TABLE IF NOT EXISTS`(파괴적 문장 없음): `tenant_profiles`(PK `tenant_id`), `tenant_plans`(PK `(tenant_id, plan_id)`, `thread_id`, `payload jsonb`, `created_at`), `tenant_feedback`(`id bigserial`, `tenant_id NOT NULL`, `plan_id`, `decision`, `reason`, `hook_type`, `claims jsonb`, `created_at`, `updated_at`, 색인 `(tenant_id, created_at)`), `tenant_threads`(PK `thread_id`, `tenant_id NOT NULL`, `created_at`). 모든 전용 테이블의 `tenant_id`는 `NOT NULL`이다.

**`store/tenant_repository.py`**: `PostgresTenantRepository(conn: SqlConnection)`가 위 `Protocol`을 만족한다(`store/product_repository.py`의 스타일을 따른다).
- **모든 메서드는 DB를 만지기 전에 `validate_tenant_id`를 거친다**(실패하면 요청을 거부, fail-closed). 모든 `SELECT`·`UPDATE`·`DELETE`는 `WHERE tenant_id = %s` 조건과 그 파라미터를 가지고, 모든 `INSERT`는 `tenant_id` 열에 값을 넣는다. SQL은 파라미터만 쓴다(문자열 연결 금지).
- 다른 테넌트의 `plan_id`를 `get_plan`으로 읽으면 `None`이다(존재 여부를 알려 주지 않는다).
- `register_thread`는 같은 테넌트가 다시 등록해도 같은 결과(멱등)이고, 다른 테넌트가 같은 `thread_id`를 등록하면 `TenantMismatch`다. `thread_id`의 접두 테넌트(`thread_tenant`)가 인자 `tenant_id`와 다르면 등록 전에 `TenantMismatch`다. `assert_thread_access`는 소유자가 다르거나 없는 thread에 `TenantMismatch`다(없는 thread도 거부, fail-closed).
- `list_feedback`는 `tenant_id` 조건을 항상 걸고 `limit`이 필수이며 최신순이다.

**반드시 있어야 하는 테스트**(합성 데이터만. 저장소 테스트는 기존 테스트의 가짜 `SqlConnection` 방식으로 실행된 SQL과 파라미터를 기록해 검사하고, 실제 PostgreSQL에 접속하지 않는다):
- `validate_tenant_id`: 올바른 값은 통과, 빈 문자열·공백·대문자·길이 초과·특수문자는 `TENANT_CONTEXT_MISSING`. `make_thread_id`·`thread_tenant` 왕복이 같고 접두가 없는 id는 `None`이다.
- `price_band`: ±pct가 맞고(경계 포함 계산식), 정가 0 이하와 pct 범위 밖은 거부된다. `WorkspaceProfile` 기본값이 30이다.
- `summarize_feedback`: 윈도 밖 항목 제외, 사유 원문이 그대로 보존되고 순서가 최신순이며 `max_reasons`를 넘으면 오래된 것이 빠지고 건수 집계에는 남는다, 입력이 비어도 예외 없이 빈 요약이다.
- **격리(핵심)**: 저장소의 모든 공개 메서드를 돌려 기록된 모든 `SELECT`·`UPDATE`·`DELETE` 문장에 `tenant_id = %s`가 있고 첫 파라미터(또는 해당 위치 파라미터)가 호출 인자의 `tenant_id`임을 단언한다. 모든 `INSERT`의 열 목록에 `tenant_id`가 있다(문장을 메서드별로 분해해 검사하고, **검사 대상 문장이 0건이면 실패**한다).
- 잘못된 `tenant_id`로 부르면 SQL이 하나도 실행되지 않고 `TENANT_CONTEXT_MISSING`이다(모든 메서드). thread: 같은 테넌트 재등록은 멱등, 다른 테넌트는 `TenantMismatch`, 접두 불일치는 등록 전에 거부, 없는 thread의 접근 검사는 거부.
- 마이그레이션: 새 버전이 마지막 번호 + 1이고 기존 항목 불변이며 `DROP`·`TRUNCATE`·`DELETE FROM`이 없고 모든 전용 테이블 `tenant_id`가 `NOT NULL`이다. `tests/test_store.py`의 기존 단언 중 버전 목록·커밋 횟수·적용 완료 픽스처는 새 버전 7을 정확히 반영하도록 갱신하고(위 세 곳, 정확 일치 유지), 그 밖의 단언은 그대로 통과한다.
- `tests/test_architecture.py`가 통과한다(`store`는 `domain`·`settings`만 import한다).

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

- `tenant_id` 조건이 없는 `SELECT`·`UPDATE`·`DELETE`를 만들지 마라. 이유: 같은 회사 안이라도 섞임은 모델의 판단이 아니라 코드로 막는다(ADR-009, ARCHITECTURE 멀티테넌트).
- 모델이 채울 수 있는 값을 `tenant_id`로 받지 마라. 저장소 함수는 서버가 세션에서 꺼낸 `tenant_id`를 첫 인자로만 받는다. 이유: 도구 입력에 테넌트 칸이 없다(AGENTS.md).
- 기존 마이그레이션을 고치거나 `DROP`·`TRUNCATE`를 쓰지 마라. 새 버전을 추가만 한다. 이유: 이미 적용된 DB와 `tests/test_store.py`의 단언이 계약이다(B-FP-060).
- 반려 사유 원문을 요약하거나 바꾸지 마라. 이유: 피드백은 압축에서 빠지면 안 되는 고정 칸이다(ARCHITECTURE 컨텍스트 관리).
- Neo4j `Feedback` 적재나 `graph/` 변경을 이 step에 넣지 마라. 이유: 한 step은 한 레이어만 다룬다(하네스 원칙 1). 적재는 별도 step 결정을 따른다.
- 격리 테스트가 검사 대상 0건으로 통과하게 두지 마라. 이유: 빈 집합에 대한 `all()`은 통과가 아니다(B-FP-069).
