# Step 12: main-polish

## 설계 검토 기록

**배경(사용자 시각 확인, 2026-11-21)**: step 10·11 뒤 확인에서 메인 화면 수정 항목이 모였다. 이 step은 **메인 화면(광고 기획)**만 다룬다: 입력창, 진행 줄 강조, 시안 시간 비표시, 기획 탭과 새 기획 버튼, 확인 질문 요약 유지. 새 패키지·서버 변경·live 호출 없음. 6b-clarify 되묻기 동작(`needs_clarification`·`claim_choice` 선택지 구성)은 바꾸지 않는다.

**코드를 열어 확인한 사실(현재 main 위 7c 브랜치)**
- `web/components/plan/Composer.tsx`: `textarea`가 `rows=1`에서 시작해 `scrollHeight`로 자동 높이를 맞춘다(step 10). 기본 textarea 스크롤바 노출 제거 규칙은 없다.
- `web/components/plan/ProgressTracker.tsx`: `deriveProgress` 항목을 `<li data-status>` + `.gs-stage-icon`(CSS 펄스) + 라벨 + 소요 시간으로 그린다. `aria-label="경과 시간"` 요소(`N초 경과`, 진행 중에만 갱신, 종료 시 `gs-sr-only`)가 아래쪽 `.gs-progress-details`에 있다. 오른쪽 끝 비용은 `costUsd` prop(3자리).
- `web/lib/reducer.ts`/`web/lib/session.tsx`: 상태는 `{tenantId, threadId, turns, activeTurnId, nextTurnId}`이고 `threadId`는 작업 공간 하나에 하나(첫 응답이 소유). `append`가 새 턴에 `threadId: state.threadId`를 넣고 `thread_received`가 첫 응답의 스레드를 `state.threadId`에 기록한다. `choice_submitted`는 `needs_choice` 턴 뒤에 이어지는 새 턴(같은 메시지, `claimChoice`·`choiceLabel`)을 만들고, 새 요청 시작 시 `needs_choice` 턴을 `done`으로 바꾼다. `selectWorkspace`가 `workspace_selected`로 모든 상태를 초기화하고 진행 중 요청을 중단한다.
- `web/components/plan/PlanPage.tsx`: `state.turns` 전체를 `TurnCard`로 그리고, 이웃 턴(`previous`/`next`)을 보고 확인 질문 선택 요약(`choiceLabel`)을 계산한다. `busy = state.activeTurnId !== null`.
- `reducer.test.ts`는 `state.threadId`(작업 공간 변경 시 `null`, 첫 응답 스레드 유지), `turns[1].threadId`(이어지는 턴이 같은 스레드), 이웃 턴 단언을 가진다. **이 단언은 모두 수정 없이 통과해야 한다**(그래서 `state.threadId`는 **활성 탭의 스레드**를 가리키는 필드로 유지하고, 탭별 스레드는 새 필드에 따로 둔다).
- `ProgressTracker`의 소비자: `TurnCard.tsx`, `tests/plan.test.tsx`, `tests/results.test.tsx`. `Composer`의 소비자: `PlanPage.tsx`뿐. `state.turns`의 소비자: `PlanPage.tsx`, `EvidencePage`(`collectSessionCards(turns)`), `latestGraphIds`(session), `tests/*`. 이 소비자들은 `state.turns`가 **모든 탭의 평면 목록으로 남는다**는 전제로 동작하므로 그대로 둔다(근거 소재 화면과 이후 실행 기록은 모든 탭의 데이터를 모은다).

**설계 결정**

1. **입력창(`Composer.tsx`, `plan.css`)**: 기본 높이를 **3줄 안팎**(`rows=3` 또는 `min-height`)으로 키우고 입력이 길어지면 최대 높이(예: 10줄)까지 자동으로 늘어난다. 최대 높이에 닿기 전에는 스크롤바가 **보이지 않는다**: `overflow-y: hidden`을 기본으로 하고 `scrollHeight > clientHeight`이고 최대 높이에 닿았을 때만 `overflow-y: auto`로 바꾼다(`scrollbar-width: none`만으로 숨기지 않는다). Enter 전송·Shift+Enter·IME 조합 중 Enter 무시·2000자 상한·전송 후 비우기·진행 중/미선택 비활성·`요청` 접근 이름·`기획하기` 버튼은 **기존 단언 그대로**.
2. **진행 줄 강조(`ProgressTracker.tsx`, `plan.css`, `tokens.css`)**: 진행 중 단계는 ① 원 둘레를 도는 틸색 회전 호(스피너 링: SVG 호 또는 CSS `conic`/`border` 방식, `@keyframes`), ② 라벨 shimmer(빛이 지나가는 효과, `background-clip: text` 그라디언트 이동 `@keyframes`), ③ 단계 칩에 연한 틸 배경(`--gs-accent-weak`), ④ 단계 사이 연결선은 **완료된 구간만 틸색으로 차오르는** 채움(`transform: scaleX` 전환), ⑤ **진행 중 단계 옆에 경과 초가 실시간으로 올라간다**. 기존 `aria-label="경과 시간"` 요소(`N초 경과` 텍스트, 타이머·종료 시 정리·주입 시계 규칙 포함)를 **진행 중인 `li` 안**으로 옮기고(작고 흐리게), 진행 중인 항목이 없으면 목록 뒤에 `gs-sr-only`로 남긴다(텍스트·갱신 규칙 불변, 아래쪽 `.gs-progress-details`의 경과 문구는 제거). 대기 단계는 흐리게(`opacity`). `prefers-reduced-motion: reduce`에서는 회전·shimmer·채움 애니메이션을 **정지**(`animation: none`, `transition: none`)하고 **부분 호(예: 3/4 호)와 `진행 중` 글자**로 구분한다(색에만 의존하지 않음). 접근 이름·`data-status`·완료 체크·실패 ✕·재작업 배지·비용 표시 단언은 유지한다. 이 `진행 중` 글자는 시각적으로 reduced-motion에서만 보이고 평소에는 `gs-sr-only`로 접근 이름에 남긴다(라벨+상태 문구 중복 금지 단언 유지).
3. **시안 단계 시간 비표시(`ProgressTracker.tsx`)**: `시안` 항목은 소요 시간을 **그리지 않는다**(체크만). `deriveProgress`의 `durationMs` 계산(`stages.ts`)은 바꾸지 않는다(`progress.test.ts` 불변). 다른 단계의 시간 표시는 유지. 사유: 클라이언트 수신 시각 기준이라 시안 구간이 0.0초로 나오고 `기획·평가` 구간에 흡수되는 것이 사용자 화면에서 확인됐다. 정확한 시간은 서버가 시각 필드를 보내야 하므로 이번 범위 밖이다.
4. **기획 탭과 새 기획 버튼(`PlanTabs.tsx` 신규, `PlanPage.tsx`, `reducer.ts`, `session.tsx`, `plan.css`)**:
   - 입력 바 **위**에 탭 줄 `기획 1 · 기획 2 · …`(`ui/Tabs` 재사용 가능, 밑줄형 `role="tablist"`·방향키·`aria-selected`, **탭 줄의 접근 이름은 `기획 탭`**)과 줄 오른쪽 끝의 `+ 새 기획` 버튼. 탭 하나는 **요청 1건과 그 확인 질문·재요청까지의 스레드**(진행 줄·결과·확인 질문)를 담는다. 선택한 탭의 턴만 그린다. 
   - 상태: `Turn`에 선택 필드 `tabId?: number`, `State`에 `tabs?: { id: number; threadId: string | null }[]`와 `activeTabId?: number`(`initialState`에서 첫 탭 하나를 둔다. 모든 기존 reducer 단언이 통과해야 하므로 `workspace_selected`는 기존처럼 초기 상태로 되돌리되 탭도 초기 탭 하나로 되돌린다). 액션 `tab_created`·`tab_selected`·`tab_closed`를 추가한다. 새 탭의 `threadId`는 `null`이고 첫 응답에서 `thread_received`가 그 탭의 `threadId`에 기록한다(**새 탭은 새 서버 스레드**). `state.threadId`는 활성 탭의 스레드와 같게 유지한다. `append`는 활성 탭의 `tabId`를 새 턴에 붙이고, `choice_submitted`·`retry_requested`는 원본 턴의 탭에 이어 붙인다(탭 전환과 무관하게).
   - 동시 실행 금지: 요청이 진행 중(`activeTurnId !== null`)이면 **새 요청 전송과 `+ 새 기획`을 비활성**하고, 진행 중인 탭에는 스피너를 표시한다. 다른 탭으로 옮겨 이전 결과를 보는 것은 가능하다(탭 전환은 진행 중 요청에 영향을 주지 않는다). 진행 중인 탭은 닫을 수 없다.
   - 완료되면 탭 이름을 **효능·제품 요약**(예: `자외선 차단 · 선케어`)으로 바꾼다: 그 탭의 마지막 `show_plan`의 `plan.claimed_efficacy[0]`을 `taxonomyNames().claimName`으로, 제품은 `plan.category` 또는 `product_display.product_name`으로 만들고 ` · `로 잇는다. 정보가 없으면 요청 문장의 앞 14자(`…`)로, 아직 결과가 없으면 `기획 N`. 각 탭에 닫기(`x`, 접근 이름 `기획 N 닫기`)가 있고 마지막 탭을 닫으면 빈 탭 하나가 새로 생긴다. 탭을 닫으면 그 탭의 턴은 `state.turns`에서 제거된다(근거 소재·이후 실행 기록은 남은 탭의 데이터만 모은다).
   - 작업 공간을 바꾸면 모든 탭이 초기화된다(기존 동작).
5. **확인 질문 요약 유지(`PlanPage.tsx`)**: 선택 뒤 `효능 선택 · …` 요약 한 줄로 접히는 동작은 **같은 탭 안에서** 같은 이웃 턴 규칙으로 계산한다(이웃은 같은 탭의 턴). 기존 단언이 새 탭 구조에서 같은 엄격도로 통과해야 한다.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| 탭 상태(`tabs`, `activeTabId`, `Turn.tabId`) | `web/lib/reducer.ts` | `session.tsx`, `PlanPage.tsx`, `PlanTabs.tsx`, `reducer.test.ts` |
| 탭 액션 호출 | `web/lib/session.tsx`(`newTab`, `selectTab`, `closeTab`) | `PlanTabs.tsx`, `PlanPage.tsx` |
| 탭 제목 요약 | `web/components/plan/PlanTabs.tsx` | `taxonomyNames`, `tabs.test.tsx` |
| 진행 중 경과 초 위치 | `web/components/plan/ProgressTracker.tsx` | `plan.test.tsx`(`경과 시간` 단언) |

**공통 시각 기준(7c 시각 확인 반영, 이후 모든 새 화면이 따른다)**: 간격은 `tokens.css`의 `--gs-space-*`(4px 배수, 기본 리듬은 8px 단위)만 쓰고 색·반경·그림자·글자 크기도 `tokens.css` 변수만 쓴다. 화면에 보이는 문자열은 **한글**이다(영문 내부 코드·브랜드 슬러그·도구 이름·`value`·`n_top` 같은 필드명을 그대로 노출하지 않는다. `taxonomyNames`의 한글 이름, `web/lib/workspace.ts`의 `workspaceLabel`, 그리고 step 13의 한글 표시 매핑을 재사용하고 없는 이름은 새로 지어내지 말고 원문 대신 `기타`·`정보 없음` 같은 한글 대체를 쓴다). 펼침·접힘은 `grid-template-rows: 0fr → 1fr` 방식의 부드러운 아코디언(화살표 회전)이고, 모든 애니메이션·전환은 `@media (prefers-reduced-motion: reduce)`에서 즉시 동작·정지한다. 색에만 의존하지 않고 아이콘·글자를 함께 쓴다. 접힌 영역의 내용은 DOM에 유지한다(`hidden`이 아니라 `inert`/`aria-hidden`과 높이 0).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/components/plan/{Composer,ProgressTracker,PlanPage,TurnCard,ClarifyCard,ClarifySummary}.tsx`, `/web/lib/{reducer,session,stages,taxonomy}.ts*`, `/web/components/ui/Tabs.tsx`, `/web/app/{plan,tokens,ui}.css`
- `/web/tests/{plan,reducer,progress,shell,results}.test.ts*`(결합 지점 확인)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/lib/reducer.ts`, `web/lib/session.tsx`, `web/components/plan/PlanPage.tsx`, `web/components/plan/PlanTabs.tsx`, `web/components/plan/Composer.tsx`, `web/components/plan/ProgressTracker.tsx`, `web/components/plan/TurnCard.tsx`(필요 시 prop만), `web/app/plan.css`, `web/app/tokens.css`, `web/app/ui.css`(필요 시), `web/components/ui/Tabs.tsx`(필요 시), `web/tests/reducer.test.ts`(추가만), `web/tests/plan.test.tsx`, `web/tests/tabs.test.tsx`, `web/tests/shell.test.tsx`(렌더 헬퍼와 위 `tablist` 단언 교체만), `web/tests/smoke.test.tsx`(위 `tablist` 단언 교체만), `web/tests/results.test.tsx`(렌더 헬퍼만)

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/lib/reducer.ts`, `web/lib/session.tsx`, `web/components/plan/PlanPage.tsx`, `web/components/plan/PlanTabs.tsx`, `web/components/plan/Composer.tsx`, `web/components/plan/ProgressTracker.tsx`, `web/components/plan/TurnCard.tsx`(필요 시 prop만), `web/app/plan.css`, `web/app/tokens.css`, `web/app/ui.css`(필요 시), `web/components/ui/Tabs.tsx`(필요 시), `web/tests/reducer.test.ts`(추가만), `web/tests/plan.test.tsx`, `web/tests/tabs.test.tsx`, `web/tests/shell.test.tsx`(렌더 헬퍼와 위 `tablist` 단언 교체만), `web/tests/smoke.test.tsx`(위 `tablist` 단언 교체만), `web/tests/results.test.tsx`(렌더 헬퍼만)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `reducer.ts`·`session.tsx`에 탭 상태·액션·세션 함수(기존 필드·액션 의미 불변). **2.** `PlanTabs.tsx`, `PlanPage.tsx`(탭 줄, 활성 탭의 턴만 렌더, 이웃 턴 계산을 탭 단위로). **3.** `Composer.tsx`(3줄·스크롤바), `ProgressTracker.tsx`(강조·경과 초 이동·시안 시간 비표시), `plan.css`·`tokens.css`(애니메이션·reduced-motion). **4.** 테스트.

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `web/tests/reducer.test.ts`: 기존 단언은 **수정 없이** 통과하고 추가: (1) 초기 상태에 탭이 하나이고 `activeTabId`가 그 탭, (2) `tab_created`는 `threadId: null`인 새 탭을 만들고 활성으로 바꾸며 `state.threadId`가 `null`이 된다, (3) 새 탭의 첫 `thread_received`는 그 탭의 `threadId`에만 기록되고 다른 탭의 `threadId`는 그대로다, (4) 새 턴은 활성 탭의 `tabId`를 가진다, (5) `choice_submitted`·`retry_requested`의 새 턴은 원본 턴의 탭에 붙는다(활성 탭이 달라도), (6) 진행 중(`activeTurnId !== null`)에는 `tab_created`가 무시되고(동시 실행 방지) `tab_selected`는 허용되며 진행 중인 탭의 `tab_closed`는 무시, (7) 마지막 탭을 닫으면 빈 탭이 생기고 닫은 탭의 턴이 제거된다, (8) `workspace_selected`는 탭을 초기 탭 하나로 되돌린다.
- `web/tests/plan.test.tsx`(교체 + 추가, 기존 행동 단언 유지): (9) 입력창 기본 높이가 3줄 안팎(`rows` 3 또는 최소 높이 규칙)이고 입력이 길어지면 높이가 늘며 최대 높이 전에는 `overflow-y`가 `hidden`이다(CSS 파일 읽기 + `scrollHeight` 가짜), (10) 진행 중 단계에 회전 호·shimmer 클래스가 있고(`@keyframes` 이름 단언) 완료 단계 사이 연결선만 채워진다(`data-filled`), 대기 단계는 `data-status="pending"`, (11) `prefers-reduced-motion` 블록에 회전·shimmer·채움의 `animation: none`·`transition: none`이 있고 부분 호 규칙이 있다, (12) `경과 시간` 요소가 진행 중인 `li` 안에 있고 기존 단언(`0초 경과`, 주입 시계로 `3초 경과`, 종료 시 정리·타이머 0개)이 그대로 통과한다, 진행 항목이 없으면 `gs-sr-only`로 남는다, (13) `시안` 항목에는 시간 문구가 없고(체크만) 다른 단계의 시간 `1.6s` 형식은 유지된다, (14) 상태 글자와 라벨 중복 금지 단언(`완료 완료` 없음) 유지.
- `web/tests/tabs.test.tsx`(새, `SessionProvider` + 가짜 `postChatAsk`): (15) 탭 줄과 `+ 새 기획` 버튼이 입력 바 위에 있다, (16) `+ 새 기획`을 누르면 빈 입력창의 새 탭이 열리고 이전 탭의 결과는 그 탭에서만 보인다, (17) 요청 진행 중에는 `+ 새 기획`과 전송이 비활성이고 진행 중 탭에 스피너(`aria-busy`)가 있으며 다른 탭으로 옮겨 이전 결과를 볼 수 있다, (18) 완료 후 탭 이름이 `효능 · 제품` 요약으로 바뀌고(합성 `claimed_efficacy`·`category`) 정보가 없으면 요청 문장 앞 14자, (19) 탭 닫기(`기획 N 닫기`)가 동작하고 진행 중 탭은 닫을 수 없다, (20) 새 탭의 첫 요청은 `threadId` 없이 서버로 가고(`postChatAsk` 인자 단언) 같은 탭의 이어지는 요청은 같은 `threadId`를 보낸다, (21) 확인 질문 선택 뒤 `효능 선택 · …` 요약 한 줄 단언이 탭 안에서 통과하고 선택지 버튼이 없다, (22) 작업 공간 변경 시 모든 탭이 초기화된다, (23) 모든 탭의 턴이 `state.turns`에 남아 근거 소재 화면(`EvidencePage`)이 모든 탭의 카드를 모은다.
- `web/tests/results.test.tsx`: `ProgressTracker`·`PlanPage` 결합 단언은 새 구조에 맞는 렌더 헬퍼 변경만 허용(행동 단언 유지).
- **`tablist` 없음 단언 교체(앞선 실행이 blocked로 찾아낸 결합)**: `web/tests/shell.test.tsx`(39행 부근)와 `web/tests/smoke.test.tsx`(17행 부근)는 광고 기획 화면에서 `expect(screen.queryByRole("tablist")).toBeNull()`로 **옛 `대화`·`전체 스키마` 탭 막대가 없음**을 단언한다. 기획 탭이 `role="tablist"`를 쓰므로 이 단언은 같은 의도를 유지하며 교체한다: (24) 옛 탭 막대는 이름으로 구분해 없음을 단언(`queryByRole("tablist", { name: "화면 선택" })`가 `null`이고 `대화`·`전체 스키마` 이름의 `tab`이 없다), (25) 기획 탭 줄은 접근 이름 `기획 탭`인 `tablist`가 **정확히 하나**(광고 기획 화면)이고 다른 화면(근거 소재·지식 그래프)에는 `기획 탭` `tablist`가 없다. 나머지 단언은 수정하지 않는다.
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
- `web/lib/reducer.ts`의 기존 필드·액션 의미, `state.threadId`의 의미(활성 탭의 스레드), `web/lib/api.ts`·`web/lib/sse.ts`·`web/lib/types.ts`의 서버 계약, 6b-clarify의 `needs_clarification`·`claim_choice` 처리·선택지 구성(`ClarifyCard`·`claim.ts`)을 바꾸지 마라. 이유: 기존 `reducer.test.ts`·`claim.test.ts` 단언이 그대로 통과해야 하고 서버 계약은 불변이다.
- 서버 코드(`src/`)를 수정하지 마라. 서버에 시각 필드를 요청하지 마라. 이유: 시안 시간 비표시는 이번 범위의 결정이다.
- `stages.ts`의 `deriveStages`·`deriveProgress`의 계산을 바꾸지 마라(`stages.test.ts`·`progress.test.ts` 불변). 이유: 표시만 바꾼다.
- JS `setInterval`로 회전·shimmer·채움을 구동하지 마라(경과 초 숫자 갱신 타이머만 허용). 이유: 애니메이션은 CSS이고 `prefers-reduced-motion`에서 꺼져야 한다.
- `web/app`·`web/components`·`web/lib` 소스에 `examples`·`.examples`·`예시 요청` 문자열을 쓰지 마라. 이유: `tests/test_demo_docs.py`의 예시 칩 금지 가드.
