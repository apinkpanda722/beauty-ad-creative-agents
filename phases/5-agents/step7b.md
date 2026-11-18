# Step 7b: workspace-feedback

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`sources`는 `domain`·`settings`만, `api`는 `store`·`graph` 등 import 가능, `fastapi`는 `api`만), CRITICAL 규칙(테넌트는 세션에서만, 검사 실패 시 요청 거부, 비밀 값)
- `/docs/ARCHITECTURE.md` — "멀티테넌트", "피드백 메모리"(PRD 핵심 기능 8·11)
- `/docs/COMPETENCY_QUESTIONS.md` — CQ-12(`Feedback` 노드 형태)와 CQ-13·14·16("우리 제품"은 작업 공간 프로필)
- `/docs/results/p5_dev_compare_preregistration.md` — §1(dev workspace 제품 주소)
- `/src/beautyads/domain/tenant.py`, `/src/beautyads/store/tenant_repository.py`, `/src/beautyads/api/app.py`, `/src/beautyads/api/session.py`, `/src/beautyads/graph/evidence_queries.py`, `/src/beautyads/sources/claim_rules.py`(YAML 로더의 선례), `/tests/test_api_chat.py`, `/tests/test_api_session.py`, `/tests/test_graph_evidence_queries.py`, `/tests/test_tenant_domain.py`, `/tests/test_architecture.py` — step 1·4·4b 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `config/workspaces.yaml`(새 파일), `src/beautyads/sources/workspaces.py`(새 파일), `src/beautyads/graph/evidence_queries.py`, `src/beautyads/api/session.py`, `src/beautyads/api/feedback.py`(새 파일), `src/beautyads/api/app.py`, `tests/test_workspaces_source.py`(새 파일), `tests/test_api_feedback.py`(새 파일), `tests/test_api_session.py`, `tests/test_graph_evidence_queries.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `config/workspaces.yaml`, `src/beautyads/sources/workspaces.py`, `src/beautyads/graph/evidence_queries.py`(질의 1개와 입력 검증 추가에 한함, 기존 질의·함수 불변), `src/beautyads/api/session.py`(`resolve_tenant` 함수 추가에 한함, 기존 `resolve_session` 동작 불변), `src/beautyads/api/feedback.py`, `src/beautyads/api/app.py`(`Assembly`에 기본값이 있는 필드 추가와 `/feedback` 라우트 등록에 한함. 기존 필드·`/chat`·`/healthz` 동작 불변, 새 필드는 모두 기본값을 가져 기존 `Assembly(...)` 생성부가 그대로 동작한다), `tests/test_workspaces_source.py`, `tests/test_api_feedback.py`, `tests/test_api_session.py`(케이스 추가에 한함, 기존 단언 변경 0줄), `tests/test_graph_evidence_queries.py`(케이스 추가에 한함, 기존 단언 변경 0줄)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

작업 공간(테넌트) 프로필 로딩, 우리 제품 단위당 정가에서 가격대 계산, 승인·반려 피드백 엔드포인트와 기획 입력용 피드백 요약을 만든다. 테넌트는 **세션(헤더)에서만** 나오고 요청 본문·도구 입력에는 테넌트 칸이 없다. 이 step은 모델·실제 서비스를 부르지 않는다. **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

**`config/workspaces.yaml`**(작업 공간 4개, dev 2개와 test 2개. dev는 개발 반복에, test는 최종 평가·시연에만 쓴다):
- `dev-mixsoon`: brand `mixsoon`, `own_product_url` `https://mixsoon.co.kr/product/detail.html?product_no=921`.
- `dev-cosrx`: brand `cosrx`, `own_product_url` `https://www.cosrx.co.kr/product/%EC%9A%B8%ED%8A%B8%EB%9D%BC-%EB%9D%BC%EC%9D%B4%ED%8A%B8-%EC%9D%B8%EB%B9%84%EC%A0%80%EB%B8%94-%EC%84%A0%EC%84%B8%EB%9F%BC-50ml/740/category/57/display/1/`.
- `test-isntree`: brand `isntree`, `own_product_url` `https://www.isntree.com/product/%EC%B4%88%EC%A0%80%EB%B6%84%EC%9E%90-%ED%9E%88%EC%95%84%EB%A3%A8%EB%A1%A0%EC%82%B0-%EC%84%B8%EB%9F%BC-50ml/55/category/42/display/1/`.
- `test-bojoseon`: brand `beauty_of_joseon`, `own_product_url` `https://beautyofjoseon.co.kr/product/%EC%9D%B8%EC%82%BC%EC%84%A0%EC%84%B8%EB%9F%BC-spf-50-pa/27/category/117/display/1/`.
- 각 항목: `tenant_id`(테넌트 ID 형식, 위 이름), `display_name`, `brand`, `own_product_url`, `tone`(짧은 한국어 문장, 예: "친근하고 간결한 말투"), `forbidden_terms`(빈 목록 기본), `price_band_pct: 30`, `group: dev|test`. 파일 머리 주석에 "test 그룹은 최종 평가·시연 전에는 개발 반복에 쓰지 않는다"를 적는다.

**`sources/workspaces.py`**(`sources` 계층, `domain`·표준 라이브러리·`pyyaml`만): `load_workspaces(path) -> list[Workspace]`(`Workspace` = `WorkspaceProfile` + `group`). 검증: `tenant_id` 중복 금지, `domain.tenant.validate_tenant_id` 형식, `group`은 `dev`·`test`만, 알 수 없는 키 거부(`extra="forbid"`), 형식 오류는 `WORKSPACES_INVALID`(위치만, 값 미노출).

**`graph/evidence_queries.py`**(추가에 한함): `product_unit_price_query()` 고정 읽기 전용 Cypher: `$brand`·`$url`로 그 제품의 `unit_list_price`·`price_basis`·`volume_unit`을 돌려준다(값은 `$` 파라미터, 모델 입력 없음). 입력 검증 함수를 둔다.

**`api/session.py`**(추가에 한함): `resolve_tenant(header, *, allowed_tenants) -> str`(헤더를 `validate_tenant_id`로 검사, 형식 오류 400 `TENANT_CONTEXT_MISSING`, 허용 목록 밖 403 `TENANT_NOT_ALLOWED`, **thread를 만들지 않는다**).

**`api/feedback.py`**: `register_feedback(app)`가 `POST /feedback`을 등록한다. 본문 `{plan_id: str, decision: "approved"|"rejected", reason: str}`(`extra="forbid"`: 본문에 `tenant_id`·`hook_type`·`claims`가 있으면 422). 동작: `resolve_tenant` → `services.tenants.get_plan(tenant_id, plan_id)`가 `None`이면 **404 `PLAN_NOT_FOUND`**(다른 테넌트의 plan_id도 같은 응답, 존재 여부를 알리지 않는다) → **훅 유형과 효능은 클라이언트가 아니라 저장된 기획안 `payload`에서 서버가 꺼낸다**(`payload`의 `plan.hook_type`·`plan.claimed_efficacy`, 없으면 `None`·빈 목록) → `Feedback(tenant_id=세션 값, ..., created_at=서버 시각)`을 `tenants.add_feedback` → 응답 `{"status": "ok"}`. `reason` 원문은 PostgreSQL에만 저장한다(그래프·로그·trace에 넣지 않는다). 모든 거부에서 저장소 쓰기가 없다. 함수 `feedback_for_prompt(tenants, tenant_id, as_of, *, limit=50) -> dict`: `list_feedback(tenant_id, limit=limit)`를 `domain.tenant.summarize_feedback`로 요약해 `model_dump(mode="json")`(사유 원문 보존)을 돌려준다(7c가 기획 입력으로 쓴다).

**`api/app.py`**: `Assembly`에 **기본값이 있는 필드**를 추가한다: `workspaces: Mapping[str, dict] = field(default_factory=dict)`(테넌트 ID → 프로필 dict), `price_bands: Mapping[str, dict] = field(default_factory=dict)`(테넌트 ID → `{"price_min", "price_max"}` 또는 값이 없으면 빈 dict). `create_app`이 `/feedback`을 등록한다. 서비스는 요청 시점에 `request.app.state.assembly`에서 꺼낸다(생성 시점 값을 붙잡지 않는다, B-FP-070).

**반드시 있어야 하는 테스트**(가짜 저장소·합성 값):
- 로더: 4개 작업 공간을 읽고 각각 `WorkspaceProfile`이 유효하다(실제 `config/workspaces.yaml` 읽기. **개수·값을 단언하지 않고** 형식·`group` 값 집합·중복 없음·`dev`와 `test` 그룹이 모두 있음만 단언한다), 중복 ID·잘못된 `group`·알 수 없는 키는 `WORKSPACES_INVALID`이고 메시지에 값이 없다.
- 질의: `product_unit_price_query()`가 읽기 전용이고 `$` 파라미터만 쓰며 입력이 문장에 끼지 않는다. 기존 질의 본문 불변.
- `resolve_tenant`: 헤더 없음·형식 오류 400, 허용 목록 밖 403, thread를 만들지 않는다(가짜 저장소에 `register_thread` 호출 0). 기존 `tests/test_api_session.py` 단언은 그대로 통과한다.
- `/feedback`: 정상 요청은 `add_feedback`이 불리고 `Feedback.tenant_id`가 헤더 값, `hook_type`·`claims`가 **저장된 기획안 payload에서 온 값**(클라이언트 값 아님)이며 `created_at`이 서버 시각이다. 다른 테넌트의 `plan_id`·없는 `plan_id`는 404 `PLAN_NOT_FOUND`이고 **쓰기 0건**. 본문에 `tenant_id`·`hook_type`·`claims`가 있으면 422·쓰기 0건. 헤더 없음 400, 허용 밖 403, 형식 오류 `decision` 422. 응답·예외·로그에 `reason` 원문이 없다(응답은 `{"status": "ok"}`뿐).
- `feedback_for_prompt`: 사유 원문이 그대로 보존되고 최신순이며 `limit`이 `list_feedback`에 전달된다(가짜 저장소가 받은 인자), 피드백이 없으면 빈 요약이다.
- **서버 진입점 경유 테스트**: `create_app(assemble=<가짜 조립>)`을 `lifespan`으로 시작해 `/feedback`이 시작 시점의 가짜를 부르고, 앱 생성 뒤 `app.state.assembly.tenants`를 바꾸면 바뀐 가짜를 부른다(생성 시점 값을 붙잡지 않음). 기존 `Assembly(...)` 생성부(`tests/test_api_chat.py`의 `assembly()`)가 새 필드 없이 그대로 동작한다(기본값).
- `tests/test_architecture.py` 통과(`sources`는 `domain`·`settings`만, `fastapi`는 `api`만).

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

- 테넌트·`hook_type`·`claims`를 요청 본문에서 받지 마라. 이유: 테넌트는 세션에서만 나오고 분류 값은 서버가 저장된 기획안에서 꺼낸다(AGENTS.md CRITICAL, ADR-009). 본문에 있으면 422다.
- 다른 테넌트의 `plan_id`에 403 등 존재를 알리는 응답을 하지 마라. 이유: 존재 여부가 새면 격리가 깨진다. 없는 것과 같은 404 `PLAN_NOT_FOUND`다.
- `reason`(반려 사유 원문)을 그래프·로그·응답·trace에 넣지 마라. 이유: 전용 텍스트의 노출 면을 PostgreSQL 한 곳으로 제한한다(ADR-009, 4b 결정).
- `Assembly`에 기본값 없는 필드를 추가하거나 기존 필드를 바꾸지 마라. 이유: 기존 테스트의 `Assembly(...)` 생성부가 깨진다(B-FP-071). 새 필드는 기본값을 갖는다.
- `config/workspaces.yaml`의 test 그룹을 개발 반복 기본값으로 쓰지 마라. 이유: test 브랜드(isntree·beauty_of_joseon)는 최종 평가·시연에만 쓴다(P5 결정). 이 step은 로딩만 만들고 선택은 호출부가 한다.
- 테스트가 실제 `config/workspaces.yaml`의 개수·브랜드 값을 `== N`으로 단언하지 마라. 이유: 작업 공간은 데이터이고 바뀔 수 있다(B-FP-061). 형식과 불변식만 단언한다.
