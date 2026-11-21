# Step 8: saved-ui

## 설계 검토 기록

**목적**: 저장한 기획 화면을 만든다(카드 목록, 상세 패널, 빈 상태, 시안 이미지). 새 패키지·서버 변경·live 호출 없음(서버 API는 step 7이 만든다). **교체 단언은 아래 표 S1 한 건뿐**이고 그 밖의 기존 단언은 수정하지 않는다. 표 밖에서 충돌을 발견하면 구현하지 말고 `blocked`로 멈춰 최소 교체안을 `reason`에 적어라.

**코드를 열어 확인한 사실**
- `web/app/page.tsx`는 `view === "saved"`일 때 자리표시 `<section className="gs-placeholder"><h1>저장한 기획</h1><p>준비 중</p></section>`를 그린다(조건부 마운트: 화면에 들어갈 때마다 새로 마운트). 지식 그래프·실행 기록처럼 작업 공간이 없으면 `상단 바에서 작업 공간을 선택하세요.`를 보인다. `web/lib/api.ts`의 `getDesignImage(tenantId, requestKey, index)`는 `requireSuccess(fetch(..., { headers: { "X-Tenant-Id": tenantId } }))` 후 `response.blob()`이고 오류는 `ApiError(status, code)`다. `web/lib/types.ts`는 `tests/test_web_contract.py`가 읽는 파일이므로 **타입 추가만** 한다.
- 승인은 `FeedbackBar`(`승인`·`반려`, 저장 성공 시 `저장했습니다`)가 한다. 저장한 기획 화면은 **마운트될 때마다** 목록을 새로 불러오므로 피드백 저장 신호(`feedbackVersion`)를 만들 필요가 없다(승인은 광고 기획 화면에서만 일어나고 그동안 이 화면은 마운트되어 있지 않다). `FeedbackBar.tsx`·`web/lib/session.tsx`는 수정하지 않는다.
- step 7 결과(`src/beautyads/api/plans.py`): `GET /plans` 응답 본문은 `{"plans": [...]}`이고 항목 키는 `plan_id`, `title`, `hook_text`, `hook_type`, `angle`, `format`, `claimed_efficacy`, `scenes`, `copy_lines`, `evidence_ids`, `has_image`, `decided_at`, `reason`이다. `GET /plans/{plan_id}/image`는 시안 바이트(`Cache-Control: no-store`)이고 오류는 `404 PLAN_NOT_FOUND`·`404 DESIGN_NOT_FOUND`다. **Codex가 `plans.py`를 열어 키를 확인하고 다르면 `blocked`**.
- 소비자 테스트: `tests/shell.test.tsx`의 지식 그래프·근거 소재·저장한 기획·실행 기록 항목 루프에서 저장한 기획(인덱스 2)은 작업 공간이 선택되기 전 상태에서 `getByRole("heading", { name: "저장한 기획" })`와 `expect(screen.getByText("준비 중")).toBeTruthy()`를 단언하고, 인덱스 4(실행 기록)에서 `queryByText("준비 중")`가 `null`임을 단언한다.

**설계 결정**
- `web/lib/api.ts`: `getSavedPlans(tenantId): Promise<SavedPlan[]>`(`GET /api/plans`, 본문의 `plans` 배열을 돌려준다; 키가 없으면 빈 배열)와 `getPlanImage(tenantId, planId): Promise<Blob>`(`GET /api/plans/${encodeURIComponent(planId)}/image`, `getDesignImage`와 같은 오류 처리). `web/lib/types.ts`에 `SavedPlan` 타입(step 7 응답 항목과 일치). Next 프록시는 기존 `/api/*` 리라이트(`web/next.config.ts`)를 그대로 쓴다(Codex가 확인).
- `web/components/saved/SavedPage.tsx`(props `tenantId: string | null`, `onPlan: () => void`): `PageHeader` 제목 `저장한 기획`, 설명 한 문장 `승인한 기획안을 모아 봅니다. 광고 기획 결과에서 승인을 누르면 여기에 모입니다.` 작업 공간이 없으면 `상단 바에서 작업 공간을 선택하세요.`만. 목록은 `Card` 격자(`graph`처럼 사이드바 폭 토큰을 참조하지 않는 `minmax(0, 1fr)` 기반 반응형 열): 시안 썸네일 또는 타일, 제목, 훅 문구 2줄(CSS 줄 제한), 배지(훅 유형·주장 효능 — 표시는 `taxonomyNames(schema)`의 한글 이름, 스키마를 못 불러오면 이름이 없는 값은 `기타`로 표시해 **영문 코드를 노출하지 않는다**), `승인 일시`(`<time>`, `toLocaleString("ko-KR")`), 사유가 있으면 한 줄 `사유: …`. 스키마는 `getSchema(tenantId)`로 한 번 불러온다(실패해도 목록은 보인다).
- 카드를 누르면(`button` 역할, 키보드 가능) `ui/SidePanel`에 장면 구성(번호 목록)·카피(인용)·주장 효능 배지·**근거 소재 N건**(플랫폼별 건수 `YouTube 3건 · Instagram 1건`: `evidence_ids`의 `source:` 접두를 `platformLabel`로 한글화해 센다. **원시 근거 id 문자열은 화면에 표시하지 않는다**)·큰 시안을 보인다. 상세 닫기는 `SidePanel`의 `닫기` 버튼이다(목록으로 돌아간다). 접근성은 `SidePanel`의 기존 동작(포커스 이동·복귀)을 그대로 쓴다.
- **빈 상태**: `EmptyState`(제목 `승인한 기획안이 없습니다`, 설명 `광고 기획 결과에서 승인을 누르면 여기에 모입니다.`, 행동 버튼 `광고 기획으로`). 로딩 `role="status"`, 오류 `role="alert"`(상태·코드)와 `다시 시도`.
- 이미지는 `blob` URL(`URL.createObjectURL`, 언마운트·교체 시 `revokeObjectURL`)이고 실패하면 타일과 `시안 이미지를 불러오지 못했습니다`. `has_image`가 거짓이면 요청하지 않고 타일(`시안 없음`). 작업 공간이 바뀌면 목록을 다시 불러오고 이전 응답은 무시한다(요청마다 취소 플래그).
- `web/app/page.tsx`: `view === "saved"` 본문을 `<SavedPage tenantId={state.tenantId} onPlan={() => setView("plan")} />`로 교체하고 `gs-placeholder` 자리표시를 지운다. 새 스타일은 `web/app/saved.css`(토큰만, `prefers-reduced-motion` 정지).
- 새 시각 기준: 영문 코드 노출 없음, 처음 보는 용어(`승인 일시`)에 뜻은 설명 문장으로, 폭은 컨테이너 기준이라 사이드바가 접혀도 깨지지 않는다.

**교체 단언(조언 세션 승인 범위: 자리표시 `준비 중`을 실제 화면으로 바꾸는 결과. 이 표 밖의 기존 단언을 수정하지 마라)**

| # | 파일·행 | 이전 | 이후 | 이유 |
|---|---|---|---|---|
| S1 | `web/tests/shell.test.tsx` 95행(루프 안 `else if (index === 2)` 분기) | `else if (index === 2) expect(screen.getByText("준비 중")).toBeTruthy();` | `else if (index === 2) expect(screen.getByText("상단 바에서 작업 공간을 선택하세요.")).toBeTruthy();`(작업 공간이 아직 선택되지 않은 루프 상태에서 저장한 기획 화면이 보이는 안내. 같은 분기의 `heading` `저장한 기획` 단언과 인덱스 4의 `queryByText("준비 중")` `null` 단언은 수정하지 않는다) | 자리표시 `준비 중`이 실제 화면으로 바뀌었다 |

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `getSavedPlans`·`getPlanImage`·`SavedPlan` | `web/lib/api.ts`, `web/lib/types.ts` | `SavedPage.tsx`, `api.test.ts` |
| 저장한 기획 화면 | `web/components/saved/SavedPage.tsx` | `page.tsx`, `saved.test.tsx` |

**공통 시각 기준(7c 시각 확인 반영, 이후 모든 새 화면이 따른다)**: 간격은 `tokens.css`의 `--gs-space-*`(4px 배수, 기본 리듬은 8px 단위)만 쓰고 색·반경·그림자·글자 크기도 `tokens.css` 변수만 쓴다. 화면에 보이는 문자열은 **한글**이다(영문 내부 코드·브랜드 슬러그·도구 이름·`value`·`n_top` 같은 필드명을 그대로 노출하지 않는다. `taxonomyNames`의 한글 이름, `web/lib/workspace.ts`의 `workspaceLabel`, 그리고 step 13의 한글 표시 매핑을 재사용하고 없는 이름은 새로 지어내지 말고 원문 대신 `기타`·`정보 없음` 같은 한글 대체를 쓴다). 펼침·접힘은 `grid-template-rows: 0fr → 1fr` 방식의 부드러운 아코디언(화살표 회전)이고, 모든 애니메이션·전환은 `@media (prefers-reduced-motion: reduce)`에서 즉시 동작·정지한다. 색에만 의존하지 않고 아이콘·글자를 함께 쓴다. 접힌 영역의 내용은 DOM에 유지하고 접힌 최종 상태는 기존처럼 `hidden` 속성이다(펼칠 때 `hidden`을 동기적으로 제거한 뒤 다음 프레임에 열림 클래스를 붙이고, 접을 때는 전환 뒤 `hidden`을 설정하되 reduced-motion·전환 시간 0이면 즉시 설정한다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/lib/{api,types,taxonomy,evidence}.ts*`, `/web/components/ui/{SidePanel,EmptyState,Card,PageHeader,Badge}.tsx`, `/web/components/{results,shell}/*`, `/web/app/{page.tsx,tokens.css}`, `/web/next.config.ts`, `/src/beautyads/api/plans.py`(step 7 결과, 응답 키 확인, 읽기 전용), `/web/tests/{api,shell}.test.ts*`, `/tests/test_web_contract.py`(`web/lib/types.ts`를 읽는 기존 단언은 수정 없이 통과해야 한다)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/lib/api.ts`, `web/lib/types.ts`(타입 추가만), `web/components/saved/*`, `web/app/saved.css`, `web/app/page.tsx`(저장한 기획 본문 연결만), `web/tests/{api.test.ts,saved.test.tsx,shell.test.tsx}`

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/lib/api.ts`, `web/lib/types.ts`(타입 추가만), `web/components/saved/*`, `web/app/saved.css`, `web/app/page.tsx`(저장한 기획 본문 연결만), `web/tests/{api.test.ts,saved.test.tsx,shell.test.tsx}`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `web/lib/api.ts` 함수 2개와 `types.ts`의 `SavedPlan` 타입(서버 응답 키와 일치). **2.** `web/components/saved/SavedPage.tsx`, `web/app/saved.css`. **3.** `web/app/page.tsx`의 저장한 기획 본문 연결. **4.** 테스트(아래). 위 설계 결정과 교체 단언 표 S1을 그대로 구현한다.

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `web/tests/api.test.ts`(기존 단언 수정 없음, 새 단언 추가만): (1) `getSavedPlans`는 `X-Tenant-Id`를 보내고 `plans` 배열을 돌려주며(키가 없으면 `[]`) 오류 시 `ApiError(code)`, (2) `getPlanImage`는 `Blob`을 반환하고 `PLAN_NOT_FOUND`·`DESIGN_NOT_FOUND`를 `ApiError`로 전달하며 `planId`를 경로 인코딩한다.
- `web/tests/saved.test.tsx`(새, 합성 데이터): (3) 목록 카드에 제목·훅 문구·`승인 일시`가 표시, (4) 빈 응답이면 빈 상태 제목과 `광고 기획으로` 버튼, (5) 카드 클릭 시 `SidePanel`에 장면·카피·`근거 소재 N건`(플랫폼별 건수)이 보이고 원시 근거 id 문자열(`youtube:`)은 없다, (6) 이미지 성공은 `img`, 실패는 `시안 이미지를 불러오지 못했습니다`, `has_image` 거짓이면 이미지 요청이 없다, (7) 작업 공간이 바뀌면 `getSavedPlans`를 새 테넌트로 다시 호출하고 이전 응답은 무시, (8) 언마운트 시 `revokeObjectURL` 호출, (9) 오류 시 `다시 시도`, (10) 훅 유형·효능 배지가 한글 이름이고 이름이 없으면 `기타`(영문 코드 없음), (11) 작업 공간이 없으면 안내 문구만, (12) `saved.css`가 사이드바 폭 토큰을 참조하지 않는다. (13) **승인 직후 화면 전환**: `Page` 전체를 렌더하고(합성 `fetch` 스텁: 작업 공간·`/api/ask`가 `plan_id`가 있는 기획안을 내려줌·`POST /api/feedback` 성공·`GET /api/plans`는 **피드백 저장이 끝난 뒤에만** 그 기획안을 돌려줌) 광고 기획 결과에서 `승인`을 눌러 `저장했습니다`가 보인 뒤 사이드바 `저장한 기획`으로 가면 `GET /api/plans`가 피드백 저장 호출 **이후**에 호출되고(`fetch` 호출 순서로 단언) 그 기획안 카드(제목)가 목록에 나타난다, 광고 기획으로 돌아가 다른 기획안을 승인하고 다시 들어오면 새 카드도 나타난다(화면이 마운트될 때마다 새로 불러오는 방식이 사용자 요구를 충족함을 고정). 이 테스트는 `web/tests/saved.test.tsx`에 둔다.
- `web/tests/shell.test.tsx`: 교체 S1만. 해시 시드·집합 순회 순서에 기대는 새 단언을 만들지 마라.
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
- 교체 단언 표(S1) 밖의 기존 단언을 수정·삭제·약화하지 마라. 충돌이 나면 구현하지 말고 `blocked`로 멈춰 최소 교체안을 `reason`에 적어라. 이유: 승인된 교체만 허용된다.
- 서버 코드(`src/`)를 수정하지 마라. 응답 키가 step 7 결과와 다르면 구현하지 말고 `blocked`로 멈춰라. `web/components/results/FeedbackBar.tsx`·`web/lib/session.tsx`·`web/components/shell/*`를 수정하지 마라. 이유: 서버 계약은 step 7에서 고정됐고 저장 신호는 필요 없다.
- 원시 근거 id·영문 분류 코드를 화면에 표시하지 마라(한글 이름 또는 `기타`·건수만). 이미지 파일 경로를 만들거나 이미지를 저장하지 마라(`blob` URL만). 이유: 새 시각 기준과 이미지 비저장 원칙.
- `web/app`·`web/components`·`web/lib` 소스에 `examples`·`.examples`·`예시 요청` 문자열을 쓰지 마라. 이유: `tests/test_demo_docs.py`의 예시 칩 금지 가드.
