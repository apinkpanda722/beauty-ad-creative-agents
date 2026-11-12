# Step 0: live-fixes-config

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P2 sources-pilot"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/ARCHITECTURE.md` — "상태 관리"(PostgreSQL이 원본, 긴 배치에서도 연결이 건강해야 한다)
- `/src/beautyads/store/repository.py`, `/src/beautyads/store/connection.py` — P1 산출물(읽기 메서드 `get_creative`·`next_pending`, 쓰기 메서드의 `commit`/`rollback` 방식)
- `/tests/test_store.py` — P1 테스트(가짜 연결 `FakeConnection`의 `commits`·`rollbacks` 계수)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/store/repository.py`, `tests/test_store.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/store/repository.py`(읽기 헬퍼 추가와 읽기 메서드의 트랜잭션 종료에 한함, 쓰기 메서드와 기존 SQL 불변), `tests/test_store.py`(추가에 한함. 아래에 명시한 **한 줄**만 새 계약으로 바꾸고 다른 단언은 약화하지 않는다)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 라벨 키 파일을 읽는 채점 함수, 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

P1 live(`make live-slice`, 2026-11-12, 사용자 실행)는 첫 시도에 통과했고 결함이 없었다. 이 step은 P1 코드 검토에서 나온 **읽기 트랜잭션 문제 하나**만 고친다. `get_creative`와 `next_pending`은 트랜잭션을 열기만 하고(psycopg는 첫 SQL에서 트랜잭션을 시작한다) 닫지 않아, 긴 배치에서 연결이 **"idle in transaction"**으로 오래 남는다(스냅샷이 열린 채로 남아 다른 세션의 정리 작업을 막을 수 있다). 소재 수천 건을 처리하는 수집·분석 배치(P2 이후)에서 문제가 된다. 이 step은 `store` 한 계층만 바꾼다.

소비자 테스트 점검 결과: `tests/test_store.py`의 `test_get_creative_restores_nulls_and_explicit_false`가 **`assert conn.commits == conn.rollbacks == 0`**을 단언한다. 이것은 P1에서 "읽기는 트랜잭션을 건드리지 않는다"를 그대로 굳힌 단언이라 이 step의 목적과 **정면으로 충돌한다.** 이 한 줄은 약화가 아니라 **의도된 계약 변경**이다: 새 단언은 `conn.rollbacks == 1 and conn.commits == 0`(읽은 뒤 트랜잭션을 `rollback`으로 정확히 한 번 닫고, 읽기가 `commit`하지 않는다)이다. 다른 단언은 그대로 둔다. 다른 테스트 파일(`tests/test_analysis.py`, `tests/test_slice.py` 등)의 가짜 저장소는 `PostgresCreativeStore`를 쓰지 않으므로 영향이 없다. 이 단언 외에 `tests/test_store.py`의 다른 테스트가 깨지면 고치지 말고 `blocked`로 보고한다.

### 변경 (`repository.py`)

- 비공개 헬퍼를 추가한다: `def _read(self, query: str, params: Sequence[Any], *, one: bool = False)`. `self.conn.execute(query, params)`로 실행하고 **결과를 모두 가져온 뒤**(`fetchone()` 또는 `fetchall()`) `self.conn.rollback()`으로 읽기 트랜잭션을 닫고 가져온 행을 돌려준다. 실행·가져오기에서 예외가 나도 `rollback()`을 부른 뒤 예외를 그대로 다시 올린다. **`rollback()`은 가져오기가 끝난 뒤에만 부른다**(닫은 뒤에는 결과를 읽을 수 없다).
- `get_creative`와 `next_pending`이 `self.conn.execute(...).fetch...()` 대신 `_read`를 쓴다. **SQL 문자열·매개변수·반환 값은 바꾸지 않는다.**
- 이후 step이 추가하는 읽기 메서드(`collection_stats`, `list_creatives`, `get_job_results`, `job_counts`)도 이 헬퍼를 쓴다(이 step에서는 아직 없다. 헬퍼의 docstring에 "읽기 메서드는 이 헬퍼로 트랜잭션을 닫는다. **연결을 여러 스레드가 공유하면 호출자가 모든 저장소 호출(읽기 포함)을 직렬화해야 한다**(읽기의 `rollback()`은 연결 단위라 다른 스레드가 쓰기 도중에 열어 둔 트랜잭션을 끝낸다)"고 적는다).
- 쓰기 메서드(`upsert_creatives`, `enqueue_analysis`, `record_analysis`)와 마이그레이션 함수는 바꾸지 않는다(이미 `commit`/`rollback`을 한다).

### 반드시 있어야 하는 테스트 (`tests/test_store.py`)

- 위에 명시한 **한 줄**을 `conn.rollbacks == 1 and conn.commits == 0`으로 바꾼다.
- 새 테스트: `get_creative`가 없는 소재(`None`)를 돌려줄 때도 `rollback()`이 정확히 한 번이고 `commit()`은 없다. `next_pending`도 같다(행이 있을 때와 없을 때 모두).
- 새 테스트: **`rollback()` 이후에 결과를 읽지 않는다**. 가짜 연결이 `rollback()`을 부른 뒤에 `fetchone`/`fetchall`이 불리면 실패하도록 만들어(예: 가짜 커서가 연결의 `rollbacks` 계수를 보고 거부) `get_creative`·`next_pending`이 정상 동작함을 확인한다.
- 새 테스트: 읽기 쿼리 실행이 예외를 올리면(`fail_on`) `rollback()`이 한 번 불리고 예외가 그대로 올라간다(`commit()` 없음). 가져오기(`fetchone`) 중 예외도 같다.
- 기존 쓰기 테스트(`commits == 1`, `rollbacks == 1` 계수 단언 등)는 그대로 통과한다.

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

- 읽기 메서드가 `commit()`을 부르게 하지 마라. 읽기는 `rollback()`으로만 닫는다. 이유: 읽기는 아무것도 쓰지 않으며 `commit`은 쓰기 계수(테스트의 `commits`)와 섞여 쓰기 경로가 깨졌는지 구분할 수 없게 만든다.
- `rollback()`을 결과를 가져오기 전에 부르지 마라. 먼저 모두 가져온 뒤 닫는다. 이유: 닫은 뒤에는 커서 결과를 읽을 수 없다.
- 쓰기 메서드·마이그레이션·기존 SQL을 바꾸지 마라. 이 step은 읽기 헬퍼와 읽기 메서드 두 개만 고친다. 이유: P1에서 승인된 멱등성·변경 시각 기준이 조용히 바뀌면 안 된다.
- `test_get_creative_restores_nulls_and_explicit_false`의 `commits == rollbacks == 0` 한 줄 외에 기존 단언을 고치거나 약화하지 마라. 이유: 그 한 줄만 이 step의 목적과 충돌하는 의도된 계약 변경이고 나머지는 P1에서 검증된 동작이다(B-FP-056).
