# Step 14: history-verify

## 설계 검토 기록

**목적**: 실행 기록·검증 페이지를 만들고(원래 step 9에 있던 실행 기록 화면 구현이 이 step으로 이관됐다), 사이드바를 `작업`·`관리` 두 그룹으로 묶고, step 13이 전체 보기에 임시로 둔 `검증 상세(관리자용)` 접힘을 이 상세 페이지로 **옮긴다**(삭제가 아니라 이동: 같은 내용이 상세 페이지 탭에서 보인다는 단언으로 옮긴다). 새 패키지·서버 변경·live 호출 없음.

**코드를 열어 확인한 사실**
- 내비: `web/components/shell/Sidebar.tsx`의 `items` 5개(`광고 기획`·`근거 소재`·`지식 그래프`·`실행 기록`·`저장한 기획`, `View` 타입 `plan|evidence|graph|history|saved`), `aria-current="page"`, 선형 인라인 아이콘. 화면 연결은 `web/app/page.tsx`의 `AppShell` children 렌더 함수가 한다(실행 기록·저장한 기획은 현재 `section.gs-placeholder`의 `준비 중`). 소비자: `shell.test.tsx`(내비 5개·순서·`aria-current`·내용 전환).
- 데이터: `useSession().state.turns`는 **모든 기획 탭의 평면 목록**(step 12). 각 `Turn`: `message`, `status`, `stepEvents`, `startedAt?`, `stepAt?`, `commands`(`show_plan`(`attempts`, `pattern_alignment`, `unknown_*`), `show_aggregates`(`verified_counts`: `{tool, count_label, row_count, shown_count}`, `model_written`, `removed`), `show_distribution`(`tool`, `rows`), `show_cost`), `choiceLabel`, `error`. 작업 공간 정보는 `/workspaces`(`Workspace`)와 `workspaceLabel`.
- 시간: `deriveProgress(stepEvents, status, {startedAt, stepAt})`가 단계별 `durationMs`와 `reworks`를 계산한다(step 10). **시안 구간은 클라이언트 수신 시각이라 신뢰할 수 없어 표시하지 않는다**(step 12와 같은 이유).
- 평가 시도: `show_plan.attempts[]`의 `attempt`, `scores`(`differentiation`·`fit`·`rationale` 한국어 자유 문장), `low_items`, `checks_passed`, `final_passed`, `cost_usd`. 한글화는 step 13의 `web/lib/localize.ts`(`localizeText`)를 재사용한다.
- step 13이 둔 `검증 상세(관리자용)`(`PlanResult.tsx`의 접힘)는 평가 시도·검사 상세·집계·분포 도구 이름 칩을 담는다. 이 step이 그 내용을 상세 페이지 탭으로 옮기고 접힘을 제거한다. 소비자: `tests/results.test.tsx`의 step 13 단언(23)(접힘 안의 기존 항목).

**설계 결정**

1. **사이드바 그룹(`Sidebar.tsx`, `icons.tsx`, `shell.css`)**: 항목 5개 그대로, 두 그룹으로 묶는다: `작업`(광고 기획·근거 소재·저장한 기획), `관리`(`지식 그래프`·`실행 기록·검증`). 기존 `실행 기록` 항목 이름은 화면 제목 `실행 기록·검증`과 맞춰 **`실행 기록·검증`**으로 표시한다(`View` 값 `history`는 유지). 그룹 소제목은 작은 한글 라벨(`role="group"` + `aria-label`). 항목 5개·`aria-current` 규칙은 불변, **순서만 그룹 순서**(`광고 기획`·`근거 소재`·`저장한 기획`·`지식 그래프`·`실행 기록·검증`)로 바뀐다 — `shell.test.tsx`의 정확 순서 단언은 새 순서·그룹 소제목 단언으로 교체한다.
2. **목록(`web/components/history/HistoryPage.tsx`)**: `DataTable`로 시각(`startedAt`이 없으면 `정보 없음`), 요청 문장, 결과 종류(기획안/확인 질문/근거 없음/오류/중단), 소요 시간(전체: 마지막 `stepAt` − `startedAt`, 없으면 `정보 없음`), 텍스트 비용(`show_cost`가 있으면 4자리). **모든 기획 탭의 턴**(`state.turns`)을 최신순으로. 상단에 `이번 접속 중 N건 · 새로고침하면 지워집니다`, 빈 상태는 `EmptyState`(`아직 실행한 요청이 없습니다` + `광고 기획으로` 버튼). 새로 만드는 순수 함수 `web/lib/history.ts`의 `summarizeTurn(turn)`이 결과 종류·단계 요약·시간·비용을 계산한다.
3. **상세 페이지(`HistoryDetail.tsx`)**: 행 클릭 시 같은 화면에서 열리고 `목록으로` 버튼이 있다(`view`는 `history` 그대로, 선택한 턴 id는 화면 상태). 헤더: 요청 문장, 작업 공간(`workspaceLabel`), 시각, 총 시간, 총 비용. 결과 화면의 `검증 상세 보기 →` 링크가 `view`를 `history`로 바꾸고 그 턴의 상세를 연다(`page.tsx`가 가진 상태를 콜백·컨텍스트로 전달). 탭 4개(`ui/Tabs`):
   - **단계**: 단계별 시간 타임라인(`deriveProgress`의 `durationMs`, **시안은 시간 없이 체크만**)과 재작업 횟수.
   - **검증**: `검증된 집계(도구가 센 값)`는 **녹색 배지**, `모델 작성값·미검증`은 **앰버**, `제외된 값`은 **회색**으로 구분하고 도구 이름은 작은 회색 출처 칩으로 보인다. 숫자는 한글 라벨과 함께(`count_label`, `row_count`·`shown_count`). **시장 인사이트 차트(step 13)의 원천 데이터(`show_distribution`의 `tool`·`rows`)와 같은 값**을 표로 보인다(한글 열 이름은 step 13의 `insight.ts` 재사용, 도구 이름은 출처 칩). 색에만 의존하지 않는다(배지 글자 병행).
   - **평가**: 시도별 점수(`차별성`·`요청 적합성`)·코드 검사·최종 판정·재검토 항목·한글 사유(`rationale`을 `localizeText`로 표시 시점에만 치환), **되돌림이 있으면 강조**(시도가 2개 이상이면 `되돌림 N회` 배지와 시도 구분 강조).
   - **비용**: 텍스트 비용(4자리, 서버 라벨), 상한, 시도별 비용(`attempt.cost_usd`, 없으면 `정보 없음`). `CostDetail`을 재사용해도 된다.
4. **이동(결과 화면 정리, `PlanResult.tsx`, `ResultsView.tsx`)**: step 13의 접힘 `검증 상세(관리자용)`을 **제거**하고(코드·CSS), 그 안의 모든 항목이 위 상세 페이지 탭에서 보이는지 단언으로 옮긴다(결과 화면에서 삭제만 하고 옮기지 않는 일이 없게). 마케터 결과 화면에는 한 줄 요약과 시장 인사이트와 `검증 상세 보기 →` 링크 한 개만 남는다. 면책·비용 각주 블록(step 13)은 유지한다.
5. 화면 연결은 `web/app/page.tsx`의 `history` 본문에서 `HistoryPage`로 교체한다(`준비 중` 자리표시 제거). 컷 시에도 **실행 기록·검증은 필수**다(컷 순서: 저장한 기획 → 데이터 그래프 → 근거 소재 별도 화면).

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `summarizeTurn`(결과 종류·시간·비용) | `web/lib/history.ts` | `HistoryPage.tsx`, `history.test.ts` |
| 상세 4탭 | `web/components/history/HistoryDetail.tsx` | `HistoryPage.tsx`, `history-page.test.tsx` |
| 상세 열기 콜백(`openHistoryDetail`) | `web/app/page.tsx` | `PlanResult.tsx`(`검증 상세 보기 →`), `HistoryPage.tsx` |
| 사이드바 그룹 | `web/components/shell/Sidebar.tsx` | `shell.test.tsx` |

**공통 시각 기준(7c 시각 확인 반영, 이후 모든 새 화면이 따른다)**: 간격은 `tokens.css`의 `--gs-space-*`(4px 배수, 기본 리듬은 8px 단위)만 쓰고 색·반경·그림자·글자 크기도 `tokens.css` 변수만 쓴다. 화면에 보이는 문자열은 **한글**이다(영문 내부 코드·브랜드 슬러그·도구 이름·`value`·`n_top` 같은 필드명을 그대로 노출하지 않는다. `taxonomyNames`의 한글 이름, `web/lib/workspace.ts`의 `workspaceLabel`, 그리고 step 13의 한글 표시 매핑을 재사용하고 없는 이름은 새로 지어내지 말고 원문 대신 `기타`·`정보 없음` 같은 한글 대체를 쓴다). 펼침·접힘은 `grid-template-rows: 0fr → 1fr` 방식의 부드러운 아코디언(화살표 회전)이고, 모든 애니메이션·전환은 `@media (prefers-reduced-motion: reduce)`에서 즉시 동작·정지한다. 색에만 의존하지 않고 아이콘·글자를 함께 쓴다. 접힌 영역의 내용은 DOM에 유지한다(`hidden`이 아니라 `inert`/`aria-hidden`과 높이 0).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/app/page.tsx`, `/web/components/shell/{Sidebar,AppShell,icons}.tsx`, `/web/components/results/{PlanResult,ResultsView,AggregatesPanel,DistributionChart,CostDetail,CostLine}.tsx`, `/web/components/ui/*`, `/web/lib/{stages,reducer,session,localize,insight,unknown,workspace,history}.ts*`, `/web/app/{shell,results,ui}.css`
- `/web/tests/{shell,results,plan,tabs,progress}.test.ts*`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/lib/history.ts`, `web/components/history/*`, `web/app/history.css`, `web/app/shell.css`, `web/app/results.css`, `web/app/page.tsx`, `web/components/shell/{Sidebar,AppShell,icons}.tsx`, `web/components/results/{PlanResult,ResultsView,AggregatesPanel,DistributionChart}.tsx`, `web/tests/history.test.ts`, `web/tests/history-page.test.tsx`, `web/tests/results.test.tsx`, `web/tests/shell.test.tsx`, `web/tests/plan.test.tsx`(결합 단언만)

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/lib/history.ts`, `web/components/history/*`, `web/app/history.css`, `web/app/shell.css`, `web/app/results.css`, `web/app/page.tsx`, `web/components/shell/{Sidebar,AppShell,icons}.tsx`, `web/components/results/{PlanResult,ResultsView,AggregatesPanel,DistributionChart}.tsx`, `web/tests/history.test.ts`, `web/tests/history-page.test.tsx`, `web/tests/results.test.tsx`, `web/tests/shell.test.tsx`, `web/tests/plan.test.tsx`(결합 단언만)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `web/lib/history.ts`, `web/components/history/{HistoryPage,HistoryDetail}.tsx`, `web/app/history.css`. **2.** `Sidebar.tsx`·`shell.css` 그룹. **3.** `page.tsx` 연결(`history` 본문, `openHistoryDetail` 상태), `PlanResult.tsx`에서 `검증 상세(관리자용)` 접힘 제거와 `검증 상세 보기 →` 링크 추가. **4.** 테스트.

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `web/tests/history.test.ts`(새): (1) `summarizeTurn`이 결과 종류 5가지(기획안·확인 질문·근거 없음·오류·중단)를 구분, (2) 전체 시간은 마지막 `stepAt`−`startedAt`이고 없으면 `null`, (3) 비용은 `show_cost`가 없으면 `null`, (4) 단계 요약이 기획·평가 횟수·재작업 횟수와 일치, (5) 합성 입력만 사용(시계 주입).
- `web/tests/history-page.test.tsx`(새, `SessionProvider` + 가짜 `postChatAsk`): (6) 목록 행 수가 **모든 기획 탭의 턴 수**와 같고 최신순, (7) `이번 접속 중 N건 · 새로고침하면 지워집니다` 문구, (8) 빈 상태와 `광고 기획으로` 버튼, (9) 행 클릭 시 상세가 열리고 헤더에 요청 문장·작업 공간·시각·총 시간·총 비용이 있다, `목록으로`로 돌아온다, (10) **단계 탭**: 단계별 시간과 재작업 횟수가 보이고 `시안`에는 시간 문구가 없다(체크만), (11) **검증 탭**: 집계 3종이 녹색·앰버·회색 배지 **글자**(`검증됨`·`미검증`·`제외됨`)와 함께 구분되고 도구 이름이 출처 칩으로 보이며 한글 라벨과 숫자가 있고, 시장 인사이트 차트의 원천 `rows`와 **같은 값**이 표로 보인다(같은 합성 `show_distribution` 입력으로 차트와 검증 탭을 모두 렌더해 값 일치 단언), (12) **평가 탭**: 시도별 점수·코드 검사·재검토 항목·한글 사유(`how_to` 같은 코드는 치환되고 `profit` 같은 비대상은 그대로), 시도가 2개 이상이면 되돌림 강조, (13) **비용 탭**: 서버 라벨·4자리 비용·상한·시도별 비용(없으면 `정보 없음`), (14) `검증 상세 보기 →` 링크를 누르면 `실행 기록·검증` 화면의 그 턴 상세가 열린다.
- `web/tests/results.test.tsx`(교체, **이동 단언**): (15) 결과 화면에 `검증 상세(관리자용)` 접힘이 **더 이상 없다**, (16) step 13의 단언(23)이 확인하던 모든 기존 항목(시도별 점수·코드 검사·재검토 항목·비용·집계 3블록·분포 도구 이름)은 **상세 페이지의 해당 탭에서 보인다**는 단언으로 같은 엄격도로 옮긴다, (17) 한 줄 요약·시장 인사이트·`검증 상세 보기 →` 링크 한 개만 마케터 화면에 있다, (18) 4c의 비용·상한 단언은 수정 없이 통과.
- `web/tests/shell.test.tsx`(교체): (19) 그룹 소제목 `작업`·`관리`와 항목 5개(순서: `광고 기획`·`근거 소재`·`저장한 기획`·`지식 그래프`·`실행 기록·검증`), `aria-current` 규칙, 항목 클릭으로 본문 전환, (20) `준비 중` 자리표시는 아직 구현되지 않은 `저장한 기획`에만 남는다(step 7·8에서 구현).
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
- `src/`(서버)와 `web/lib/{api,sse,types}.ts`를 수정하지 마라. 서버에 단계 시각·검증 필드를 요청하지 마라. 이유: 서버 계약은 불변이고 시안 시간은 표시하지 않는다.
- 결과 화면에서 항목을 지우기만 하고 옮기지 마라(`검증 상세(관리자용)`의 모든 내용은 상세 페이지 탭에 있어야 하고 단언이 있어야 한다). 이유: 항목 삭제 금지 원칙.
- 서버 영속 기록·실행 이력 API·`localStorage` 저장을 만들지 마라(세션 기반, 새로고침하면 지워진다고 화면에 표시). 이유: 서버 영속 확대는 이번 범위 밖이다(승인되지 않음).
- `stages.ts`의 `deriveStages`·`deriveProgress` 계산, `localize.ts`·`insight.ts`의 규칙을 바꾸지 마라(재사용만). 이유: 단일 매핑 한 곳을 유지한다.
- `web/app`·`web/components`·`web/lib` 소스에 `examples`·`.examples`·`예시 요청` 문자열을 쓰지 마라. 이유: `tests/test_demo_docs.py`의 예시 칩 금지 가드.
