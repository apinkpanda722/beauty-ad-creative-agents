# Step 16: tenant-isolation-asserts

## 설계 검토 기록

**배경(조언 세션 승인)**: 격리 `setup`은 테넌트 A 요청 1건을 실제로 보내고(`eval/isolation_live.py:161` `_seed`), 테넌트 범위 테이블(`tenant_profiles`·`tenant_threads`·`tenant_plans`·`tenant_feedback`)과 LangGraph 체크포인트 테이블에만 쓴다(`store/tenant_repository.py`: `save_profile:83`·`save_plan:111`·`add_feedback:135`·`register_thread:168`, 모두 `INSERT … ON CONFLICT`). E3 코퍼스는 소재·제품·규칙 읽기 소스(`PostgresGraphSyncSource`·`PostgresLayer1Source`·`load_claim_rules`)만 읽어 구조상 격리 테넌트 데이터가 들어오지 않지만, 이를 고정하는 단언이 없다. 이 step은 **테스트만** 추가해 그 구조를 고정한다. **코드는 바꾸지 않는다.**

**식별자 전수 대조(현재 코드)**: `eval/isolation_live.py`(`ISOLATION_TENANTS`·`MARKERS`·`_seed(assembly, client, guard)`·`positive_control(assembly, setup)`·`main(argv, *, out, settings, assemble, check, root, setup_path, requests_path, ...)`), `store/tenant_repository.py`(`PostgresTenantRepository`와 위 메서드의 SQL 문자열), `eval/e3_live.py`(`load_corpus()`: `connect(postgres_dsn())`·`PostgresGraphSyncSource(conn)`·`PostgresLayer1Source(conn)`·`load_claim_rules`·`build_corpus(..., rules=...)`; import 중 `beautyads.store.*`는 `connection`·`layer1_source`·`repository`·`sync_source`뿐), `eval/vector_baseline.py`(import는 표준 라이브러리 `hashlib`·`json`·`math`·`re`·`array`·`dataclasses`뿐), `tests/test_isolation_live.py`(`Memory(Tenants)`·`rig` 픽스처: `Assembly(graph=None, chat=None, tool_runner=None, ...)`, `test_setup_and_positive_control_and_limits:197`), `tests/test_vector_baseline.py`(`:100-122 test_no_new_queries_or_forbidden_imports`의 AST 방식, `synthetic_rule`·`build_corpus` 사례 `:204`·`:256`), `tests/test_e3_live.py`(`:1521 test_load_corpus_reuses_claim_rule_reader_and_sanitizes_failure`의 가짜 `connect`·소스·`load_claim_rules` 방식).

**상수 단언 grep**: 이 step은 새 테스트 함수만 추가하고 기존 테스트·상수를 바꾸지 않는다. 기존 `rig` 픽스처의 `Assembly(...)` 인자(`graph=None`·`chat=None`·`tool_runner=None`)는 그대로 쓴다.

**새 칸 대응표**: 테넌트 쓰기 범위(`store/tenant_repository.py`의 SQL 대상 테이블 → `tests/test_isolation_live.py`의 소스 문자열 단언), 코퍼스 구성 입력(`load_corpus`가 부르는 소스 → `tests/test_e3_live.py`의 가짜 연결·소스 단언), 금지 import(`vector_baseline.py`·`e3_live.py` → AST 단언).

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건(합성·소스 문자열 검사만).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 테스트는 가짜 환경만 쓴다, 계층 경계, `tenant_id`는 세션에서만 나온다(ADR-009)
- `/src/beautyads/eval/isolation_live.py`(`_seed`·`positive_control`·`main`), `/src/beautyads/store/tenant_repository.py`(읽기 전용), `/src/beautyads/eval/e3_live.py`(`load_corpus`·import 목록, 읽기 전용), `/src/beautyads/eval/vector_baseline.py`(import 목록, 읽기 전용)
- `/tests/test_isolation_live.py`(전체), `/tests/test_e3_live.py`(`:1521` 부근), `/tests/test_vector_baseline.py`(`:100-122`·`:204`·`:256`)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `tests/test_vector_baseline.py`, `tests/test_e3_live.py`, `tests/test_isolation_live.py`

열람 금지 경로: `data/interim/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `tests/test_vector_baseline.py`, `tests/test_e3_live.py`, `tests/test_isolation_live.py`

격리 테넌트 데이터가 E3 코퍼스에 들어오지 않고, 격리 `setup`이 테넌트 범위 저장소 밖에 쓰지 않음을 고정하는 **테스트만** 추가한다. **소스 코드는 한 줄도 바꾸지 않는다. 모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다.**

새 식별자: (없음, 새 테스트 함수만)

**테스트(합성 데이터·`tmp_path`, 모델·접속 없음)**
- `tests/test_vector_baseline.py`: (1) `vector_baseline.py` 모듈의 AST import 이름(최상위 패키지)이 표준 라이브러리 집합(`hashlib`·`json`·`math`·`re`·`array`·`dataclasses`와 `sys.stdlib_module_names`에 있는 것)뿐이고 `beautyads.*`를 하나도 import하지 않는다(테넌트 저장소·피드백 소스·`api`를 간접으로도 못 쓴다). `:100-122`의 기존 AST 테스트는 그대로 둔다.
- `tests/test_e3_live.py`: (2) `e3_live.py` 모듈의 AST import에 `beautyads.store.tenant_repository`·`beautyads.store.feedback_source`·`beautyads.store.links_source`·`beautyads.store.product_repository`·`beautyads.api` 하위·`beautyads.eval.isolation_live`가 하나도 없다(허용된 `beautyads.store.*`는 `connection`·`layer1_source`·`repository`·`sync_source`뿐임을 집합으로 단언). (3) `load_corpus()`를 가짜 `connect`·`PostgresGraphSyncSource`·`PostgresLayer1Source`·`load_claim_rules`로 부르는 테스트(`:1521`의 방식)에 **테넌트 저장소 경로를 막는 가짜**를 더한다: `beautyads.store.tenant_repository.PostgresTenantRepository`를 접근하면 실패하는 가짜로 바꿔 두고(`monkeypatch`), 소스가 돌려주는 합성 소재·제품·규칙으로 만든 코퍼스 문서 전체에 테넌트 쪽 표식 문자열(`SENTINEL_TENANT_PLAN`·`SENTINEL_TENANT_FEEDBACK`)이 없고 문서 id가 `{출처}:{id}`·`product:…`·규칙 ID 형식뿐임을 단언한다. 격리 작업 공간 `tenant_id`(`iso-alpha`·`iso-beta`, `eval/isolation_live.ISOLATION_TENANTS`의 값)가 문서에 없음도 단언한다.
- `tests/test_isolation_live.py`: (4) **쓰기 범위**: `store/tenant_repository.py`의 소스 텍스트에서 `INSERT INTO`·`UPDATE`·`DELETE FROM` 뒤의 테이블 이름을 모두 뽑아(정규식, 실제 파일 읽기는 소스 코드 파일이라 허용) 전부 `tenant_`로 시작함을 단언하고, 하나도 못 찾으면 실패한다(검사한 문장 수 0은 실패). (5) **`setup`의 접근 범위**: 기존 `rig`로 `["setup"]`을 실행하면서 `Assembly` 인스턴스의 속성 읽기를 기록해(`__getattribute__` 감시 또는 읽기 전용 속성 래퍼 등) `setup`이 `graph`·`hydrate`·`chat`·`tool_runner`에 접근하지 않았고, `rig.tenants`(`Memory`)의 호출 메서드 집합이 `register_thread`·`save_plan`·`add_feedback`·`assert_thread_access`·`get_plan`·`list_feedback`·`save_profile` 부분집합임을 단언한다(`Memory`가 모르는 메서드를 부르면 실패한다). (6) `setup` 뒤 `rig.tenants`에 저장된 데이터의 `tenant_id`가 모두 `ISOLATION_TENANTS` 안이다.
- 합성 문장·분류 값을 기대값으로 굳히지 않는다(경계·집합·형식만 검사).

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

- 소스 코드(`src/` 아래 모든 파일)와 기존 테스트의 단언·상수를 수정하지 마라. 이유: 이 step은 이미 통과한 구조를 테스트로 고정하는 일이다. 소스 변경이 필요하면 `blocked`로 보고한다.
- 실제 DB·모델·네트워크에 접속하거나 `data/interim/`의 실제 파일 내용을 읽는 테스트를 만들지 마라. 이유: 테스트는 가짜 환경과 소스 코드 텍스트만 쓴다(AGENTS.md).
- 단언을 느슨하게(`in`으로 부분 비교하거나 "하나라도")하지 마라. 이유: 허용 import·메서드·테이블 집합은 정확히 닫혀 있어야 새로운 경로가 생기면 실패한다.
