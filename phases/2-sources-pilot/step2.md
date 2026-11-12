# Step 2: creative-brand

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P2 sources-pilot"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/ARCHITECTURE.md` — 온톨로지 2층 `Creative`(소재가 어느 브랜드·계정의 것인지)와 "데이터 흐름" 7번(증분 동기화)
- `/src/beautyads/domain/` 전체(`creative.py`, `protocols.py`, `__init__.py`) — P1 산출물
- `/src/beautyads/store/schema.py`, `/src/beautyads/store/repository.py` — P1 산출물(`CHANGE_COLUMNS`, 마이그레이션, 업서트)
- `/tests/test_domain.py`, `/tests/test_store.py` — P1 테스트(이 step이 기대 목록을 고친다)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/creative.py`, `src/beautyads/domain/protocols.py`, `src/beautyads/domain/__init__.py`, `src/beautyads/store/schema.py`, `src/beautyads/store/repository.py`, `tests/test_domain.py`, `tests/test_store.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/creative.py`, `src/beautyads/domain/protocols.py`, `src/beautyads/domain/__init__.py`, `src/beautyads/store/schema.py`, `src/beautyads/store/repository.py`, `tests/test_domain.py`(추가·갱신에 한함, 단언 약화 금지), `tests/test_store.py`(추가·갱신에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 라벨 키 파일을 읽는 채점 함수, 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

P1의 `Creative`에는 소재가 **어느 브랜드·계정의 것인지**가 없다. E1 표본의 "출처×브랜드" 층화, dev/test 분할 적용, 시범 20건 선정이 모두 이 정보를 쓰므로 이 step이 `brand`와 `account`를 추가한다. 이 step은 `domain`과 `store` 두 계층을 함께 바꾼다(하나의 작은 수직 변경이라 한 step으로 둔다). 수집 쪽(어댑터)은 다음 step들이 채운다.

소비자 테스트 점검 결과: `tests/test_analysis.py`·`tests/test_slice.py`의 가짜 저장소(`MemoryRepo`, `MemoryStore`)는 Protocol을 상속하지 않는 일반 클래스이고 Protocol에 `runtime_checkable`이 없으므로 Protocol에 메서드가 늘어도 영향이 없다(확인함). `Creative`의 새 필드는 기본값 `None`이라 기존 테스트의 생성 호출이 깨지지 않는다. `tests/test_architecture.py`·`tests/test_youtube.py`는 `domain`을 import만 한다. 이 파일들은 수정하지 않는다. `tests/test_store.py`의 `creative_row` 헬퍼는 `model_dump`로 열 값을 만들어 새 열을 자동으로 포함한다. 이 점검과 다르게 위 파일의 테스트가 깨지면 고치지 말고 `blocked`로 보고한다.

### domain 변경

- `Creative`에 `brand: str | None = None`, `account: str | None = None`을 추가한다(`extra="forbid"` 유지). `account`는 출처별 계정 식별자(YouTube는 `@handle`, Instagram은 username, TikTok은 이후 step이 정한다).
- 새 모델 `CollectionStat`(`NamedTuple` 또는 pydantic): `source: Source`, `brand: str | None`, `account: str | None`, `total: int`, `analyzable_true: int`, `analyzable_false: int`, `analyzable_null: int`, `last_collected_at: datetime | None`.
- `CreativeRepository` Protocol에 `def collection_stats(self) -> list[CollectionStat]: ...`를 추가한다.
- `domain/__init__.py`의 공개 이름에 `CollectionStat`을 추가한다.

### store 변경

- **마이그레이션 버전 2**(`creative_brand_account`): `ALTER TABLE creatives ADD COLUMN IF NOT EXISTS brand text`, `ADD COLUMN IF NOT EXISTS account text`. 버전 1은 고치지 않는다. 두 번 적용해도 같다.
- `CHANGE_COLUMNS`에 `brand`와 `account`를 **추가**한다(내용 열이다. 수집 시각 열은 여전히 포함하지 않는다). 업서트 SQL·`CREATIVE_COLUMNS`·행 복원이 새 열을 다룬다. 기존 행의 `brand`·`account`는 NULL이고 재수집 때 채워진다(별도 백필은 하지 않는다).
- `collection_stats()`(읽기 메서드이므로 step 0이 만든 `_read` 헬퍼로 읽어 **트랜잭션을 닫는다**): `creatives`를 `(source, brand, account)`로 묶어 `count(*)`, `analyzable`이 TRUE/FALSE/NULL인 개수(`FILTER`), `max(collected_at)`을 한 쿼리로 돌려준다(정렬은 `source, brand, account`). 값은 매개변수로 전달한다.

### 반드시 있어야 하는 테스트

- `tests/test_domain.py`: `brand`·`account`가 생략되면 `None`, 문자열로 주면 보존, 알 수 없는 필드는 여전히 거부. `CollectionStat` 필드.
- `tests/test_store.py`: **기존 `CHANGE_COLUMNS` 정확 일치 단언을 새 목록으로 갱신**한다(내용 열 7개 + `brand`·`account` + 최신 지표 값 3개. 수집 시각 열 4개가 없음을 계속 단언한다). 마이그레이션 테스트가 버전을 `[1]` 같은 리터럴로 단언하면 `MIGRATIONS`에서 파생한 값과 비교하도록 바꾼다(버전이 늘어도 깨지지 않게, 단언을 약화하지 않는다). 버전 2 SQL에 `IF NOT EXISTS`가 있고 `DROP`·`TRUNCATE`가 없다. 업서트 `params`에 `brand`·`account`가 들어가고 `None`이면 NULL로 전달된다. `get_creative`·`next_pending`이 새 열을 `Creative`로 복원한다. `collection_stats`: 가짜 연결이 돌려준 행(NULL 브랜드 포함)이 `CollectionStat`으로 복원되고 SQL에 `GROUP BY`와 `FILTER`가 있으며 매개변수 이외의 값이 SQL에 들어가지 않는다. 읽은 뒤 `rollback()`이 정확히 한 번이고 `commit()`은 없다.

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

- 기존 행의 `brand`·`account`를 채우려고 백필 쿼리를 만들지 마라. 이유: 재수집이 같은 키로 업서트하며 채우고, 추측으로 채우면 잘못된 브랜드가 붙는다.
- `CHANGE_COLUMNS`에 `collected_at`·`first_seen_at`·`metrics_collected_at`·`updated_at`을 넣지 마라. 이유: 수집 시각이 포함되면 재수집마다 모든 행의 `updated_at`이 올라 증분 동기화가 무력해진다(P1 step 3 규칙).
- 마이그레이션 버전 1을 고치거나 `DROP`·`TRUNCATE`를 쓰지 마라. 새 변경은 버전 2로만 한다. 이유: 이미 적용된 마이그레이션을 고치면 환경마다 스키마가 달라진다.
- `brand`·`account`를 필수 필드로 만들지 마라(기본값 `None`). 이유: P1의 호출부와 테스트가 이 필드 없이 `Creative`를 만든다.
- 기존 테스트의 단언을 느슨하게 하지 마라. `CHANGE_COLUMNS` 정확 일치는 새 목록으로 **바꾸되** 여전히 정확 일치로 단언한다(B-FP-056). 이유: 열 목록은 증분 동기화의 핵심 계약이다.
