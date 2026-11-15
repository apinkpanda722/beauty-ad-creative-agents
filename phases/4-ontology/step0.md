# Step 0: graph-sync

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조, 온톨로지 절, 데이터 흐름
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P4 절과 변경 기록 #36
- `/docs/COMPETENCY_QUESTIONS.md` — v1(2026-11-15 동결), 홉 정의와 한계
- `/docs/CONTRACTS.md` — Neo4j 절(이미지·드라이버, 복합 유일 제약, MERGE 반복의 카운터, 오류 종류, 첫 live 함정)
- `/docs/ADR.md` — ADR-010(PostgreSQL이 원본, 증분 동기화)
- `/src/beautyads/store/schema.py`, `/src/beautyads/store/repository.py` — `CHANGE_COLUMNS`, `updated_at` 갱신 조건, `sync_state` 표, 작업 상태 표
- `/src/beautyads/domain/protocols.py`, `/src/beautyads/domain/labels.py`, `/src/beautyads/analysis/models.py` — 기존 Protocol(**고치지 않는다**), 닫힌 값 목록, `FINAL_RUN_TAG`
- `/src/beautyads/pipeline/preflight.py`, `/src/beautyads/settings.py`, `/deploy/docker-compose.yml`, `/Makefile`, `/README.md`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `pyproject.toml`, `uv.lock`, `src/beautyads/graph/__init__.py`, `src/beautyads/graph/schema.py`, `src/beautyads/graph/connection.py`, `src/beautyads/graph/load.py`, `src/beautyads/domain/sync.py`(새 파일), `src/beautyads/store/sync_source.py`(새 파일), `src/beautyads/pipeline/sync.py`(새 파일), `src/beautyads/settings.py`, `Makefile`, `README.md`, `tests/test_graph_schema.py`, `tests/test_graph_load.py`, `tests/test_sync_source.py`, `tests/test_sync_pipeline.py`, `tests/test_settings.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `pyproject.toml`, `uv.lock`(`uv add neo4j==6.4.1`만), `src/beautyads/graph/**`, `src/beautyads/domain/sync.py`, `src/beautyads/store/sync_source.py`, `src/beautyads/pipeline/sync.py`, `src/beautyads/settings.py`(Neo4j 주소 설정 함수 추가에 한함, 기존 함수 불변), `tests/test_settings.py`(해당 케이스 추가에 한함, 단언 약화 금지), `Makefile`(`sync`·`live-graph` 타깃과 `.PHONY` 추가에 한함, 기존 타깃·`verify` 불변), `README.md`(live-graph 절 추가에 한함), `tests/test_graph_schema.py`, `tests/test_graph_load.py`, `tests/test_sync_source.py`, `tests/test_sync_pipeline.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

소비자 테스트 점검 결과: `tests/test_compose.py`·`tests/test_slice.py`·`tests/test_collect.py`·`tests/test_pilot.py`는 저장소 `Makefile`을 읽고 `.PHONY`는 부분집합으로, 기존 타깃의 레시피 원문은 정확히, `verify` 레시피는 `live-`가 없음을 단언한다. 따라서 **새 타깃은 추가하되 기존 타깃의 레시피 원문·`verify` 레시피·형식은 바꾸지 않는다.** 이 테스트 파일들은 수정하지 않는다. 깨지면 고치지 말고 `blocked`로 보고한다.

`uv add neo4j==6.4.1`을 실행하고 해석된 버전을 `summary`에 적는다(다른 패키지 추가 금지). **`neo4j`는 `graph/`에서만 import한다.**

PostgreSQL이 원본이고 Neo4j는 거기서 만든 파생물이다(ADR-010). 이 step은 **공용 2층 뼈대**(Creative와 분류 축 노드)를 증분 MERGE로 적재하는 동기화 계층과 실행 진입점을 만든다. 1층·`PROMOTES`·`CLAIMS`·`MENTIONS`는 뒤 step이다.

- **계층**: `graph/`는 `domain`·`settings`만 import한다(`store`를 import하지 않는다). PostgreSQL에서 바뀐 행을 읽는 일은 `domain/sync.py`의 새 Protocol(`GraphSyncSource`: 변경된 소재 읽기, 소재별 `*@v1` 완료 라벨 읽기, 워터마크 읽기·쓰기)과 그 구현 `store/sync_source.py`로 나누고 `pipeline/sync.py`가 둘을 이어 붙인다. **기존 `CreativeRepository`·`AnalysisRepository` Protocol에 메서드를 추가하지 않는다**(가짜 구현이 깨진다).
- **스키마(`graph/schema.py`)**: 제약은 모두 `IF NOT EXISTS`이고 두 번 실행해도 같다. `Creative (source, source_id)` 복합 유일 제약, `Hook`·`Angle`·`Format`·`Talent`·`CtaType`의 `value` 유일 제약, `Brand`의 `name` 유일 제약. 라벨·관계 이름·속성 이름은 코드 상수이고 **데이터 값은 항상 파라미터**로 넘긴다(Cypher 문자열에 값을 끼워 넣지 않는다).
- **적재(`graph/load.py`)**: `UNWIND $rows`로 배치하고 노드와 관계는 모두 `MERGE`다(`CREATE` 금지). `Creative` 속성은 출처, 원본 ID, 링크, 게시 시각, 길이, 언어, 브랜드, 콘텐츠 유형, 카테고리, 최신 지표 3개와 지표 수집 시각이다(수집 기록·원본 응답은 올리지 않는다). 분류 축 관계는 `USES_HOOK`·`HAS_ANGLE`·`HAS_FORMAT`·`FEATURES`·`HAS_CTA`이고, 값은 **`FINAL_RUN_TAG`(`v1`)의 `content_type@v1`·`hook@v1`·`full@v1`이 `done`인 작업**에서만 읽는다(시범 `@minimal`·`@default`와 v0는 읽지 않는다). 값이 `domain`의 닫힌 목록에 없으면 노드를 만들지 않고 건수를 `skipped_invalid`로 센다. `USES_HOOK`에는 훅 묘사 원문을 관계 속성으로 둔다. 제품 소재가 아닌 소재(`content_type != product_creative`)는 콘텐츠 유형과 지표만 올린다. 숫자는 정수로 변환해 넘긴다(YouTube 통계는 문자열이었다).
- **변경 판정**: PostgreSQL의 `updated_at`(소재 표)과 작업 표의 `updated_at`이 워터마크보다 큰 행만 읽는다. **그래프 카운터(`properties_set` 등)로 판정하지 않는다.** `now()`는 트랜잭션 시작 시각이라 오래 걸린 트랜잭션이 워터마크보다 이른 `updated_at`으로 나중에 커밋될 수 있으므로, 읽기 시작점은 `워터마크 − SYNC_OVERLAP`(상수, 기본 10분)이고 워터마크는 **적재가 끝난 뒤에만** 이번에 읽은 행의 최대 `updated_at`으로 올린다. 겹쳐 읽는 구간은 MERGE가 멱등이라 비용만 든다.
- **연결(`graph/connection.py`)**: 드라이버는 `neo4j.GraphDatabase.driver(uri, auth=("neo4j", 비밀번호))`로 만들고 주소 기본값은 compose 호스트 포트 `bolt://127.0.0.1:7688`이다(`settings`에 설정 함수를 추가하고 비밀번호는 기존 `neo4j_password`를 쓴다). 오류는 `AuthError`→`NEO4J_AUTH_VOLUME_STALE`(메시지에 "비밀번호는 데이터 볼륨을 처음 만들 때만 적용된다, `make graph-reset`" 안내), `ServiceUnavailable`→`NEO4J_UNREACHABLE`, `ConstraintError`→`NEO4J_CONSTRAINT_VIOLATION`으로 바꾼다(비밀번호·주소의 인증 정보는 출력하지 않는다). 없는 라벨·속성 알림(`01N50`·`01N52`)은 `notifications_min_severity`로 거른다.
- **실행(`pipeline/sync.py`, `make sync`)**: 점검(`ENV_MISSING:NEO4J_PASSWORD`, `ENV_MISSING:POSTGRES_PASSWORD`, `DOCKER_DOWN`, `POSTGRES_UNREACHABLE`, `NEO4J_UNREACHABLE`, 실패하면 `PREFLIGHT_FAILED <코드>` 종료 코드 2, 그 전에는 접속하지 않는다) → 스키마 적용 → 변경 행 읽기 → 배치 적재 → 워터마크 갱신. `--limit N`(읽을 소재 수 상한), `--full`(워터마크 무시, 처음부터 다시 만들기)을 받는다. 요약(읽은 소재 수, 적재한 노드·관계 수, `skipped_invalid`, 새 워터마크, 소요)을 출력하고 키·URI 인증 정보는 출력하지 않는다.
- **`make live-graph`**: `python -m beautyads.pipeline.sync --limit 50 --verify`. 같은 50건을 **두 번** 적재해 두 번째가 `nodes_created 0`·`relationships_created 0`이고 `Creative` 노드 수가 같으며 분류 값 노드가 닫힌 목록 안임을 `count`로 확인해 출력한다. 이 step 안에서는 실행하지 않는다(사용자가 돌린다). README에 선행 조건(OrbStack, `make db-up`, 처음 볼륨 비밀번호 함정)과 이유 코드 표를 쓴다.

### 반드시 있어야 하는 테스트

(가짜 드라이버·가짜 소스·`tests/fixtures/contracts/`에는 Neo4j 원본이 없으므로 `docs/CONTRACTS.md` Neo4j 표의 오류 종류를 실제 `neo4j.exceptions` 클래스를 만들어 재현한다.)
- 스키마: 모든 제약 문장이 `IF NOT EXISTS`이고 두 번 적용해도 같은 문장 목록이다, `Creative` 제약이 `(source, source_id)` 복합이다.
- 적재 문장: 노드·관계 문장에 `CREATE`가 없고 `MERGE`만 쓴다, 값이 문자열에 끼워지지 않고 파라미터로 간다(감시 문자열을 데이터에 넣어 문장 텍스트에 없음을 확인), 같은 입력을 두 번 넣으면 가짜 드라이버가 받은 문장·파라미터가 같다.
- 라벨 읽기: `*@v1`이 아닌 작업(`@minimal`·`@default`·v0)의 라벨은 올라가지 않는다, 목록에 없는 값은 노드를 만들지 않고 `skipped_invalid`로 센다, `product_creative`가 아닌 소재에는 분류 축 관계가 없다, 값의 위치가 아니라 키 이름으로 읽는다.
- 변경 판정: 워터마크보다 오래된 행은 읽지 않고 `워터마크 − SYNC_OVERLAP` 안의 행은 다시 읽는다, 적재가 실패하면 워터마크가 올라가지 않는다, `--full`은 워터마크를 무시한다, 그래프 카운터를 판정에 쓰지 않는다(카운터가 항상 `properties_set 1`을 돌려주는 가짜로도 같은 결과).
- 오류: `AuthError`→`NEO4J_AUTH_VOLUME_STALE`(`make graph-reset` 안내 포함), `ServiceUnavailable`→`NEO4J_UNREACHABLE`, `ConstraintError`→`NEO4J_CONSTRAINT_VIOLATION`, 출력에 비밀번호가 없다(감시 값 주입).
- 점검: 각 이유 코드가 해당 조건에서 나오고 점검 실패 시 드라이버 생성·`store` 접속이 **한 번도** 불리지 않는다.
- `Makefile`에 `sync`·`live-graph`가 있고 `verify` 레시피에 `live-`가 없다. `tests/test_architecture.py`가 그대로 통과한다(`neo4j`는 `graph`에서만).
- 빈 입력(변경된 소재 0건)은 오류가 아니라 0건 요약이고 워터마크는 그대로다.

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

- `make sync`·`make live-graph`를 실행하지 마라. 테스트는 가짜 드라이버·가짜 소스만 쓴다. 이유: 실제 Neo4j 접속은 사용자의 live 실행이고 SQL·Cypher는 가짜로만 통과할 수 있어 첫 live에서 결함이 드러난다.
- 에이전트가 Cypher를 쓰게 하는 코드를 만들지 마라(이 step은 적재만 한다). 이유: 아키텍처 규칙(고수준 도구만).
- 노드·관계를 `CREATE`로 만들거나 값을 Cypher 문자열에 끼워 넣지 마라. 이유: MERGE 멱등성과 주입 방지.
- 그래프 카운터로 "바뀐 행"을 판정하지 마라. 이유: 같은 값을 MERGE해도 `properties_set`이 올라간다(`docs/CONTRACTS.md` Neo4j).
- 워터마크를 적재 전에 올리지 마라. 이유: 중간 실패 시 행이 영구히 빠진다.
- 기존 `Protocol`에 메서드를 추가하거나 가짜 저장소 구현을 고치지 마라. 이유: 가짜 3곳이 깨진다(P2 `requeue_jobs`에서 겪음).
- Neo4j 볼륨을 지우는 타깃·코드를 새로 만들지 마라(`graph-reset`은 이미 있다). 이유: 파괴적 작업은 사용자가 명시적으로 한다.
- 시범 태그(`@minimal`·`@default`)와 v0 라벨을 읽지 마라. 이유: 규칙이 달라 섞이면 안 된다(ADR-018).
