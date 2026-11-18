# Step 4b: feedback-graph

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`graph`는 `domain`·`settings`만), CRITICAL 규칙(PostgreSQL이 원본, MERGE 멱등, 변경 판정은 PostgreSQL 변경 시각)
- `/docs/ARCHITECTURE.md` — "2층: 광고 관찰"(피드백), "멀티테넌트"(전용 노드에 `tenant_id`), "상태 관리"
- `/docs/ADR.md` — ADR-009, ADR-012
- `/docs/COMPETENCY_QUESTIONS.md` — CQ-12(`Feedback`→`ABOUT`→패턴, `f.tenant_id`·`f.decision`·`f.created_at`)
- `/tests/test_architecture.py`
- `/src/beautyads/domain/sync.py`, `/src/beautyads/domain/links.py`, `/src/beautyads/graph/layer2.py`, `/src/beautyads/graph/schema.py`, `/src/beautyads/graph/queries.py`, `/src/beautyads/store/links_source.py`, `/src/beautyads/store/sync_source.py`, `/src/beautyads/pipeline/sync.py`, `/tests/test_graph_layer2.py`, `/tests/test_links_source.py`, `/tests/test_sync_pipeline.py`, `/src/beautyads/domain/tenant.py`(step 4), `/src/beautyads/store/tenant_repository.py`(step 4) — step 9(layer2-links)와 같은 동기화 틀의 선례

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/feedback_sync.py`(새 파일), `src/beautyads/store/feedback_source.py`(새 파일), `src/beautyads/graph/feedback.py`(새 파일), `src/beautyads/graph/schema.py`, `src/beautyads/pipeline/sync.py`, `README.md`, `tests/test_feedback_sync_domain.py`(새 파일), `tests/test_feedback_source.py`(새 파일), `tests/test_graph_feedback.py`(새 파일), `tests/test_graph_schema.py`, `tests/test_sync_pipeline.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/feedback_sync.py`, `src/beautyads/store/feedback_source.py`, `src/beautyads/graph/feedback.py`, `src/beautyads/graph/schema.py`(제약 추가에 한함, 기존 제약·테스트 단언 불변), `src/beautyads/pipeline/sync.py`(`--layers`에 3 추가에 한함, 기존 동작 불변), `README.md`(sync 절 추가에 한함), `tests/test_feedback_sync_domain.py`, `tests/test_feedback_source.py`, `tests/test_graph_feedback.py`, `tests/test_graph_schema.py`(케이스 추가에 한함, 단언 약화 금지), `tests/test_sync_pipeline.py`(케이스 추가에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

step 4의 PostgreSQL `tenant_feedback`을 Neo4j `Feedback` 노드로 증분 MERGE로 적재한다(`--layers 3`). CQ-12가 읽는 모양(`f.tenant_id`, `f.decision`, `f.created_at`, `(f)-[:ABOUT]->(pattern)`)을 만든다. step 9(layer2-links)와 같은 동기화 틀(변경 판정은 PostgreSQL 변경 시각, 겹쳐 읽기, 적재 뒤 워터마크 갱신, 레이어별 워터마크 이름)을 그대로 쓴다. **이 step 안에서는 실제 접속·실행을 하지 않는다. 모델을 호출하지 않는다.**

- **`domain/feedback_sync.py`**(표준 라이브러리·pydantic만): `SyncFeedback`(frozen: `tenant_id`, `feedback_id: str`(`tenant_feedback.id`의 문자열), `plan_id`, `decision: str`, `hook_type: str | None`, `claims: tuple[str, ...]`, `created_at: datetime`, `updated_at: datetime`), `FeedbackSyncSource`(`Protocol`: `read_changed(*, since, limit) -> list[SyncFeedback]`, `get_watermark`, `set_watermark`). **반려 사유(`reason`) 원문은 그래프에 올리지 않는다**(전용 텍스트는 PostgreSQL에만 둔다. CQ-12는 사유를 읽지 않는다).
- **`store/feedback_source.py`**: `tenant_feedback`에서 `updated_at > since`(겹쳐 읽기 포함)인 행을 읽어 `SyncFeedback`으로 돌려준다. 워터마크 이름은 새 레이어 이름 하나(기존 이름과 겹치지 않게)이고 읽기·갱신은 `store/sync_source.py`의 방식을 따른다. SQL은 파라미터만 쓴다.
- **`graph/feedback.py`**: `load_feedback(graph, items) -> 요약`. 모든 문장은 `MERGE`와 파라미터이고 `CREATE`가 없다. `Feedback` 노드는 `(tenant_id, feedback_id)`로 MERGE하고 속성은 `tenant_id`, `feedback_id`, `plan_id`, `decision`, `created_at`(UTC ISO 문자열, CQ-12가 `datetime(f.created_at)`로 읽는다)이다. `ABOUT`은 `hook_type`이 있으면 `Hook {value}`로, `claims`의 각 값은 `Efficacy {value}`로 잇는다(`Hook`·`Efficacy` 노드는 이미 있으면 MERGE하고, **닫힌 값 밖이면 그 Feedback 전체를 거부**한다: 코드 `FEEDBACK_VALUE_INVALID`, 요약 `rejected` 건수). **한 Feedback의 `ABOUT`은 집합 교체**다: 같은 트랜잭션에서 그 Feedback의 기존 `ABOUT`을 지우고 다시 만든다(이 삭제는 해당 `Feedback` 노드의 `ABOUT`에 한정, 다른 노드·관계는 건드리지 않는다). `decision`은 `approved`·`rejected`만(그 밖이면 거부). `tenant_id`가 비었거나 패턴(`domain.tenant.validate_tenant_id`와 같은 규칙, `graph`는 `store`를 import하지 않으므로 같은 정규식을 `domain/feedback_sync.py`에 두고 양쪽이 그것을 쓴다 — `domain/tenant.py`를 고치지 않고 `domain/feedback_sync.py`가 같은 패턴 상수를 정의하되 두 상수가 같은 값임을 단언하는 테스트를 둔다)에 맞지 않으면 거부한다.
- **`graph/schema.py`**: `Feedback`용 제약 하나(`IF NOT EXISTS`, `(tenant_id, feedback_id)` 유일)를 별도 튜플로 추가하고 기존 제약은 바꾸지 않는다.
- **`pipeline/sync.py`**: `--layers`에 `3`을 추가한다(기존 `1`·`2`와 기본 동작은 그대로). 요약에 읽은 수, 적재한 수, `rejected` 수를 출력한다.

**반드시 있어야 하는 테스트**(가짜 그래프·가짜 소스와 합성 값만):
- 적재 문장: `CREATE` 없음·`MERGE`·파라미터만, 같은 입력을 두 번 넣으면 문장·파라미터가 같다(멱등), 제약이 `IF NOT EXISTS`이고 기존 제약이 불변이다.
- 모든 `Feedback` 노드에 `tenant_id` 파라미터가 있고, 노드 키에 `tenant_id`가 포함된다. `reason`이 어떤 문장·파라미터에도 없다.
- `ABOUT` 집합 교체: 이전에 `ABOUT`이 둘이던 Feedback을 하나로 줄여 다시 적재하면 사라진 관계를 지우는 문장이 나가고 그 삭제가 해당 Feedback에 한정된다(문장이 `feedback_id`·`tenant_id`로 범위가 걸린다).
- 닫힌 값 밖의 `hook_type`·`claims`·`decision`, 잘못된 `tenant_id`는 `FEEDBACK_VALUE_INVALID`로 거부되고 그 Feedback의 그래프 쓰기가 없다. 거부는 요약에 센다.
- **CQ-12 호환**: `QUESTIONS["CQ-12"]`의 Cypher 텍스트가 읽는 속성 이름(`tenant_id`, `decision`, `created_at`)이 `graph/feedback.py`가 쓰는 속성 이름 집합에 모두 있다(텍스트에서 `f.<속성>`을 뽑아 비교한다. 질의를 고치지 않는다).
- 증분: 워터마크보다 오래된 행은 읽지 않는다, 적재 실패 시 워터마크가 오르지 않는다, 그래프 카운터를 판정에 쓰지 않는다. `--layers 3`이 인자 파서에서 받아들여지고 기존 `1`·`2`·기본 경로의 테스트가 그대로 통과한다.
- 두 정규식(`domain/feedback_sync.py`와 `domain/tenant.py`의 테넌트 ID 패턴)이 같은 값이다.
- `tests/test_architecture.py`가 통과한다(`graph`는 `store`를 import하지 않는다, `neo4j`는 `graph`만).

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

- `make sync`를 실행하지 마라. 이유: 실제 Neo4j 접속은 사용자가 한다.
- `graph/queries.py`나 CQ-12 질의를 고치지 마라. 이유: CQ v1이 동결돼 있다. 적재 쪽이 질의가 읽는 속성에 맞춘다.
- `reason`(반려 사유 원문)이나 기획안 본문을 그래프에 올리지 마라. 이유: 전용 텍스트의 노출 면을 PostgreSQL 한 곳으로 제한한다(ADR-009).
- `tenant_id` 없는 `Feedback` 노드를 만들거나 노드 키에서 `tenant_id`를 빼지 마라. 이유: 테넌트 전용 노드는 전부 `tenant_id`가 붙는다(ARCHITECTURE 멀티테넌트).
- `ABOUT` 삭제 범위를 `Feedback` 한 노드 밖으로 넓히지 마라. 이유: 공용 노드·다른 테넌트 관계를 지울 수 있다. 기존 `layer1`·`layer2` 적재 동작과 `graph/load.py`도 바꾸지 마라(step 0·8·9 테스트가 계약).
- 그래프 카운터를 "바뀐 행" 판정에 쓰지 마라. 이유: PostgreSQL이 원본이고 변경 시각으로 판정한다(AGENTS.md).
