# Step 7: saved-api

## 설계 검토 기록

**목적**: 저장한 기획 화면용 서버 API 두 개를 만든다: `GET /plans`(저장한 기획 목록)와 `GET /plans/{plan_id}/image`(plan_id 기반 시안 이미지). **작업 공간(테넌트) 일치와 경로 검증을 반드시 넣고 테스트로 고정한다.**

**코드를 열어 확인한 사실**
- `src/beautyads/api/ask.py`의 `GET /design/{request_key}/{index}`는 메모리 딕셔너리 `designs`로 plan_id를 찾는다(서버 재시작 시 비어 있음). 이미지 경로는 `services.design_dir.resolve()` 아래 `sha256(request_key)[:16]/{index:02d}_composed.png`(합성본이 있을 때) 또는 `{index:02d}.{IMAGE_MIMES[mime]}`이고 `path.resolve()` 후 `is_relative_to(root)`를 검사, 읽기 실패는 `404 DESIGN_NOT_FOUND`. `image_reference`(`api/ask_view.py`)가 payload의 `image`에서 `request_key, index, mime, size, sha256`(+선택 `composed`)만 남긴다.
- `TenantRepository`(`domain/tenant.py`)는 `get_plan(tenant_id, plan_id)`·`list_feedback(tenant_id, decision, since, limit)`를 갖고 **plan 목록 조회는 없다**. `tenant_feedback`의 `decision`은 `approved|rejected`. plan_id는 `uuid4().hex`(32자 소문자 16진수).
- `resolve_tenant(X-Tenant-Id, allowed_tenants)`가 세션 경계다.

**설계 결정**
- 새 `src/beautyads/api/plans.py`의 `register_plans(app)`와 `app.py`에서 등록(기존 등록 방식과 같은 위치·형식).
- **`GET /plans`**: `resolve_tenant` → `list_feedback(tenant_id, limit=200)`(최신순) → plan_id별 **첫 행(최신 피드백)**만 남기고 `approved`인 것만 → 각각 `get_plan(tenant_id, plan_id)`(없으면 건너뜀). 응답 본문은 `{"plans": [항목…]}`(최신 승인 순, 다른 키 없음)이고 응답 항목: `plan_id`, `title`, `hook_text`, `hook_type`, `angle`, `format`, `claimed_efficacy`, `scenes`, `copy_lines`, `evidence_ids`, `has_image`(payload `image`가 유효한 `image_reference`인지), `decided_at`(피드백 `created_at`), `reason`. 값은 payload의 `plan`에서 **허용 키만** 골라 복사한다(`report`·이미지 해시·파일 경로는 응답에 넣지 않음). 반려로 바뀐 plan(최신이 rejected)은 빠진다. 한계(최근 피드백 200건)는 코드 상수와 DEMO.md 기록용 주석으로 남긴다.
- **`GET /plans/{plan_id}/image`**: (1) `plan_id`가 `^[0-9a-f]{32}$`가 아니면 `404 PLAN_NOT_FOUND`(경로 이탈 문자열 포함, 파일 시스템에 닿기 전에 거부), (2) `resolve_tenant`, (3) `get_plan(tenant_id, plan_id)`가 `None`이거나 `record.tenant_id != tenant_id`면 `404 PLAN_NOT_FOUND`(다른 작업 공간의 plan은 존재 여부도 알리지 않음), (4) `image_reference(payload["image"])`가 `None`이면 `404 DESIGN_NOT_FOUND`, (5) 파일 경로는 기존 `design`과 **같은 규칙**으로 만든 뒤 `is_relative_to(root)` 검사 + **심볼릭 링크 거부**(`path.is_symlink()` 또는 root 아래 경로 중 링크 하나라도 있으면 404), (6) 읽기 실패 404, (7) 응답 헤더 `Cache-Control: no-store`, `Content-Type`은 기존과 같이 `composed.mime` 또는 `image.mime`. 경로 계산은 `ask.py`의 로직을 **공통 헬퍼로 추출**해 두 라우트가 쓰게 하되 기존 `/design/...` 라우트의 동작·상태 코드는 바뀌지 않아야 한다(심볼릭 링크 거부는 새 라우트에만 적용).

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `GET /plans` | `src/beautyads/api/plans.py` | `web/lib/api.ts`(step 8), `tests/test_api_plans.py` |
| `GET /plans/{plan_id}/image` | `src/beautyads/api/plans.py` | `web/components/saved/*`(step 8) |
| 설계 파일 경로 헬퍼 | `src/beautyads/api/design_files.py` | `api/ask.py`, `api/plans.py` |

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/src/beautyads/api/{ask,ask_view,app,session,feedback,assembly}.py`, `/src/beautyads/domain/tenant.py`, `/src/beautyads/store/tenant_repository.py`, `/tests/`의 기존 `/design/` 라우트 테스트(`rg -n "design/" tests`)와 피드백·플랜 저장소 테스트, `/tests/test_architecture.py`, `/tests/test_caps_guard.py`, `/docs/ADR.md`(ADR-009)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/api/plans.py`, `src/beautyads/api/design_files.py`, `src/beautyads/api/ask.py`(헬퍼 사용으로 최소 수정), `src/beautyads/api/app.py`(라우터 등록), `tests/test_api_plans.py`

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `src/beautyads/api/plans.py`, `src/beautyads/api/design_files.py`, `src/beautyads/api/ask.py`(헬퍼 사용으로 최소 수정), `src/beautyads/api/app.py`(라우터 등록), `tests/test_api_plans.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `api/design_files.py`(경로 계산 헬퍼 추출). **2.** `api/ask.py`가 헬퍼를 쓰도록 최소 수정(동작 불변). **3.** `api/plans.py`와 `app.py` 등록. **4.** 테스트 작성.

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `tests/test_api_plans.py`(가짜 저장소·임시 `design_dir`, 실제 `data/design` 읽기 금지): 
  (1) 목록(본문 키는 정확히 `["plans"]`): 최신 피드백이 approved인 plan만, rejected로 바뀐 plan·피드백 없는 plan은 제외, 다른 테넌트의 plan은 포함되지 않음, 응답 키는 허용 목록(`report`·`sha256`·경로 없음),
  (2) **다른 작업 공간의 plan_id로 이미지 요청 → 404 `PLAN_NOT_FOUND`**(존재하는 plan_id로도), 
  (3) **허용되지 않은 `X-Tenant-Id` → 기존 `resolve_tenant`와 같은 거부**, 
  (4) **경로 이탈 입력 거부**: `plan_id`에 `../`, `..%2f`, 절대 경로(`/etc/passwd`), 32자 아닌 값, 대문자 16진수 → 모두 404이고 `get_plan`이 호출되지 않는다(가짜 저장소 호출 횟수 단언),
  (5) **payload의 `image.request_key`가 경로를 조작해도**(예: `../x`) 해시 디렉터리 때문에 root 밖으로 나가지 않으며 root 밖을 가리키는 경우 404,
  (6) 심볼릭 링크로 root 밖 파일을 가리키는 시안 파일 → 404(`tmp_path`에 링크 생성, 링크 생성이 불가능한 플랫폼이면 skip이 아니라 헬퍼 단위 테스트로 대체),
  (7) 정상: 같은 테넌트·유효 image → 200, 바이트·`Content-Type`·`Cache-Control: no-store` 일치(합성 PNG 바이트), 합성본이 있으면 `_composed.png` 우선,
  (8) 이미지 없는 plan → 404 `DESIGN_NOT_FOUND`,
  (9) 기존 `/design/{request_key}/{index}` 라우트 테스트는 **수정 없이 통과**.
- `tests/test_architecture.py`가 통과(새 파일이 허용 계층만 import).
- 해시 시드·집합·딕셔너리 순회 순서에 기대는 새 단언을 만들지 마라(리스트와 명시적 순서로 단언).

## Acceptance Criteria

```bash
make verify   # lint + pytest + pnpm lint·typecheck·test 통과
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - AGENTS.md CRITICAL 규칙을 위반하지 않았는가?
3. 결과를 최종 응답(JSON)으로 보고한다. `phases/` 아래 파일은 수정하지 않고 git commit도 하지 않는다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약(설치한 패키지 버전 포함, 승인 목록에서 조정한 것은 이유까지)"`
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

- `docs/EVAL.md`의 동결 기준·`docs/results/`·사전 등록과 동결 가드 테스트(`tests/test_prereg.py`·`tests/test_freeze_guard.py`)·`src/beautyads/agents/`·`llm/`·`analysis/`·`checks/`의 프롬프트와 상수를 수정하지 마라. 이유: 동결 값은 결과를 본 뒤 바꾸지 않는다(AGENTS.md CRITICAL).
- 기존 단언을 약화·삭제하지 마라. 컴포넌트 구조가 바뀌어 교체해야 하는 웹 테스트는 **같은 행동을 같은 엄격도로** 새 구조에서 단언하고, 완료 보고(summary)에 "교체한 단언 → 새 단언" 대응을 적어라. 이유: 가드를 약화하면 회귀를 못 잡는다.
- `pnpm add`·`uv add`·그 밖의 패키지 설치와 `package.json`·`pnpm-lock.yaml` 수정을 하지 마라. 이유: 이번 phase의 새 패키지는 승인된 `pretendard@1.3.9` 하나뿐이다.
- 모델·유료 API를 호출하거나 `make live-slice`, `make live-collect`, `make live-pilot`, `make live-analyze`, `make live-tiktok`, `make live-tiktok-analyze`, `make live-graph`, `make live-products`, `make live-ingredient-catalog`, `make live-cert-recheck`, `make live-cq`, `make live-product-identify`, `make live-agent`, `make live-agents`, `make live-evidence`, `make live-compare`, `make live-evalset`, `make live-e2e5`, `make live-e3`, `make live-isolation`, `make serve`, `make demo-up`, `make db-up`, `make obs-up`을 실행하지 마라. `.env`를 열거나 출력하지 마라. 테스트는 합성 데이터와 가짜 환경만 쓴다. 이유: 실제 호출과 사람이 보는 확인은 사용자가 한다(AGENTS.md CRITICAL).
- 제품 이름 문자열(`Gyeol Studio`, `결 스튜디오`)을 `web/lib/brand.ts` 밖에 리터럴로 쓰지 마라(테스트 파일 제외 불가: 가드 테스트가 `web/` 소스 전체를 검사한다). 이유: 이름은 한 곳에서만 바꾼다(확정 설계 조건 1).
- `domain/`·`store/`(저장소 메서드·스키마)를 수정하지 마라. 이유: 목록은 기존 `list_feedback`+`get_plan`으로 만든다. plan 목록 조회 메서드가 필요해 보이면 완료 보고에 적고 중단하라(범위 확대는 승인 필요).
- `/design/{request_key}/{index}` 라우트의 응답·상태 코드·헤더를 바꾸거나 그 기존 테스트를 수정하지 마라. 이유: 헬퍼 추출은 동작 불변이어야 한다.
- 도구 입력이나 쿼리 문자열에서 `tenant_id`를 받지 마라. 이유: `tenant_id`는 세션에서만 나온다(ADR-009).
- 응답이나 로그에 이미지 해시·파일 시스템 경로·예외 문자열을 싣지 마라. 이유: 로컬 경로·내부 값은 HTTP 경계를 넘지 않는다.
- 엔드포인트를 `GET /plans`·`GET /plans/{plan_id}/image` 외에 추가하지 마라. `app.py`는 `register_plans` import 한 줄과 등록 호출 한 줄(기존 `register_graph`와 같은 위치·형식)만 추가하고 이 밖의 `src/` 변경이 필요하면 구현하지 말고 `blocked`로 멈춰 `reason`에 적어라. 이유: 승인된 서버 변경 범위(테넌트 격리·plan_id 정규식 `^[0-9a-f]{32}$`·경로 이탈·심볼릭 링크 거부는 테스트로 고정한다).
