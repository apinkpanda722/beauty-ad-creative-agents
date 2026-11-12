# Step 8: store-queries

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P2 sources-pilot"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/ARCHITECTURE.md` — "상태 관리"(분석 작업 상태: 대기·완료·보류·실패, 과부하로 실패한 건은 다음 실행에서 다시 집는다)
- `/docs/PHASES.md` — P2 `batch-runner`·`pilot-sheet` 행(재시도 대상 오류를 `pending`으로 되돌림, 실행 태그)
- `/src/beautyads/domain/` 전체(`protocols.py`, `creative.py`, `__init__.py`), `/src/beautyads/store/repository.py`, `/src/beautyads/store/schema.py` — P1·P2 step 2 산출물
- `/tests/test_store.py`, `/tests/test_domain.py` — 기존 테스트

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/jobs.py`, `src/beautyads/domain/protocols.py`, `src/beautyads/domain/__init__.py`, `src/beautyads/store/repository.py`, `tests/test_domain.py`, `tests/test_store.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/jobs.py`, `src/beautyads/domain/protocols.py`(메서드 추가와 `labels` 형 확장에 한함), `src/beautyads/domain/__init__.py`(공개 이름 추가에 한함), `src/beautyads/store/repository.py`(메서드 추가에 한함, 기존 SQL 불변), `tests/test_domain.py`(추가에 한함, 단언 약화 금지), `tests/test_store.py`(추가에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 라벨 키 파일을 읽는 채점 함수, 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

다음 step들(전체 분석, 배치 실행기, 시범 시트)이 저장소에서 읽고 되돌려야 하는 것을 `domain`·`store`에 추가한다. **스키마(마이그레이션)는 바꾸지 않는다.** 분석 실행 태그는 별도 열이 아니라 `kind` 문자열에 붙인다: 축 이름 + `@` + 실행 태그(예: `hook@minimal`, `hook@default`). 같은 소재를 두 `thinking_level`로 분석해도 `(source, source_id, kind)` 키가 달라 서로 덮어쓰지 않는다. 이 step은 `domain`과 `store` 두 계층을 함께 바꾼다(P2 step 2와 같은 이유로 한 step으로 둔다).

소비자 테스트 점검 결과: `tests/test_analysis.py`·`tests/test_slice.py`의 가짜 저장소는 Protocol을 상속하지 않는 일반 클래스이고 Protocol에 `runtime_checkable`이 없어 메서드 추가의 영향이 없다. `record_analysis`의 `labels` 형 확장은 타입 힌트만 바꾸고 기존 호출(문자열 값)을 허용한 채로 둔다. `domain/__init__.py`는 공개 이름을 **추가**만 하므로 이를 import하는 `tests/test_architecture.py`·`tests/test_youtube.py`도 영향이 없다. 그 파일들은 수정하지 않는다. 깨지면 고치지 말고 `blocked`로 보고한다.

### domain 변경

- 새 파일 `domain/jobs.py`: `JobResult`(`key: CreativeKey`, `kind: str`, `status: JobStatus`, `labels: dict[str, Any] | None`, `error_code: str | None`, `model: str | None`, `thinking_level: str | None`, `prompt_version: str | None`, `raw_output: str | None`, `attempts: int`, `updated_at: datetime | None`). pydantic, `extra="forbid"`.
- `AnalysisRepository`에 메서드 추가:

```python
def requeue_jobs(self, kind: str, error_codes: Collection[str]) -> int
    # status가 'failed'이고 error_code가 목록에 있는 작업만 'pending'으로 되돌리고 updated_at 갱신. 되돌린 수. 'held'와 'done'은 건드리지 않는다
def job_counts(self, kind: str) -> dict[str, int]
    # JobStatus의 네 값을 모두 키로 갖는다(없는 값은 0)
def get_job_results(self, kind: str, keys: Sequence[CreativeKey]) -> list[JobResult]
    # 키마다 해당 kind의 작업과 그 소재의 가장 최근 model_outputs 행(raw_output·model·thinking_level·prompt_version)을 합쳐 돌려준다. 작업이 없는 키는 건너뛴다
```

- `CreativeRepository`에 메서드 추가:

```python
def list_creatives(self, *, brands: Collection[str] | None = None, sources: Collection[Source] | None = None,
                   analyzable_only: bool = False, limit: int | None = None) -> list[Creative]
    # 정렬은 published_at 내림차순(NULL 마지막), source, source_id(결정적). brands가 None이면 브랜드 제한 없음(빈 컬렉션은 결과 없음)
```

- `record_analysis`의 `labels` 형을 `Mapping[str, str] | None`에서 `Mapping[str, Any] | None`으로 넓힌다(전체 분석 결과에는 목록과 불리언이 있다. JSON으로 직렬화 가능한 값).

### store 변경 (`repository.py`, 기존 SQL은 바꾸지 않는다)

**새 읽기 메서드(`job_counts`, `get_job_results`, `list_creatives`)는 모두 step 0이 만든 `_read` 헬퍼로 읽어 트랜잭션을 닫는다**(읽은 뒤 `rollback()` 정확히 한 번, `commit()` 없음). `requeue_jobs`는 쓰기라 기존 쓰기 메서드처럼 `commit()`/`rollback()`한다.

- `requeue_jobs`: `UPDATE analysis_jobs SET status='pending', updated_at=now() WHERE kind=%s AND status='failed' AND error_code = ANY(%s)`. 목록이 비어 있으면 SQL을 보내지 않고 0. 값은 모두 매개변수.
- `job_counts`: `GROUP BY status`로 센 결과를 네 값 모두 채워 돌려준다.
- `get_job_results`: `analysis_jobs`와 `model_outputs`(소재·kind별 `max(id)` 행)를 조인하는 한 쿼리를 키 목록 단위로 부른다(키가 많으면 일정 크기로 나눠 부른다). `labels`(jsonb)는 `dict`로 복원한다.
- `list_creatives`: 고정된 SQL 조각만 조합한다(`WHERE` 조건은 `brand = ANY(%s)`, `source = ANY(%s)`, `analyzable IS TRUE` 중 필요한 것만). **값을 문자열로 이어 붙이지 않는다.** `limit`이 있으면 `LIMIT %s`. 행을 `Creative`로 복원할 때 `brand`·`account`를 포함한다(NULL은 `None`).

### 반드시 있어야 하는 테스트

- `tests/test_domain.py`: `JobResult`의 필드·`extra` 거부, `labels`에 목록·불리언·중첩 값이 허용됨.
- `tests/test_store.py`(가짜 연결, 기존 방식): 새 읽기 메서드 세 개는 읽은 뒤 `rollback()`이 정확히 한 번이고 `commit()`이 없다. `requeue_jobs`가 `failed`와 지정한 오류 코드만 대상으로 하는 SQL을 보내고(`held`·`done` 조건이 SQL에 없다), 빈 목록이면 SQL을 보내지 않고 0을 돌려주며 값이 매개변수로만 전달된다. `job_counts`가 가짜가 돌려준 일부 상태만 있어도 네 값을 모두 채운다. `get_job_results`가 가짜 행을 `JobResult`로 복원하고(`labels` JSON 복원 포함) 작업이 없는 키를 건너뛴다. `list_creatives`: 필터 조합별 SQL 조각(브랜드·출처·`analyzable IS TRUE`·`LIMIT`)이 맞고 값이 SQL 문자열에 없으며(따옴표가 든 브랜드 이름으로 확인) 빈 `brands` 컬렉션은 결과 없음(DB 호출 없이 빈 목록), 정렬 조건이 SQL에 있다. 복원된 `Creative`에 `brand`·`account`가 들어 있다. **`record_analysis`에 목록·불리언이 든 `labels`를 넘기면 JSON으로 직렬화되어 전달된다.**
- 기존 `kind`가 `@`를 포함해도(`hook@minimal`) 기존 `enqueue_analysis`·`next_pending`·`record_analysis`가 그대로 동작함을 확인하는 테스트를 추가한다.

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

- 마이그레이션을 추가하거나 `analysis_jobs`의 키·열을 바꾸지 마라. 실행 태그는 `kind` 문자열의 `@` 뒤에 붙인다. 이유: 기본 키를 바꾸려면 `DROP`이 필요하고 P1에서 마이그레이션의 `DROP`·`TRUNCATE`를 금지했다. 원본 데이터 저장소의 스키마 변경은 작게 한다.
- `requeue_jobs`가 `held`나 `done` 작업을 되돌리게 하지 마라. `failed`이면서 지정한 오류 코드인 것만 되돌린다. 이유: `held`는 분류 형식 오류로 사람이 보는 항목이고 `done`을 되돌리면 비용이 이중으로 든다(A-FP-035).
- `list_creatives`의 필터 값을 SQL 문자열에 이어 붙이지 마라. 이유: 따옴표가 든 브랜드 이름·캡션이 쿼리를 깨뜨리거나 주입된다(P1 store 규칙).
- 기존 SQL(`build_upsert_sql`, `enqueue_analysis`, `next_pending`, `record_analysis`의 쿼리)을 바꾸지 마라. 새 메서드만 추가한다. 이유: P1·P2 step 2에서 검증된 증분 동기화 기준과 멱등성이 조용히 바뀌면 안 된다.
- 기존 테스트의 단언을 약화하지 마라. 추가만 한다(B-FP-056).
