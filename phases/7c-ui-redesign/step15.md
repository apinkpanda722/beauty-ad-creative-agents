# Step 15: shell-plan-fixes

## 설계 검토 기록

**목적**: 7c 시각 확인에서 사용자가 지적한 쉘·기획·근거 소재 화면 수정 6건(항목 1~5, 10)을 한 step으로 처리한다. 새 패키지·서버 변경·live 호출 없음. 6b-clarify 되묻기 동작 변경 없음. 아래 "교체 단언" 2건만 기존 단언을 바꾸고 그 밖의 기존 단언은 수정하지 않는다. 목록 밖에서 충돌을 발견하면 구현하지 말고 `blocked`로 멈추고 최소 교체안을 `reason`에 적어라(임의로 단언을 고치지 않는다).

**코드를 열어 확인한 사실**
- 탭: `web/components/plan/PlanTabs.tsx`의 닫기 버튼은 `<button className="gs-tab-close" aria-label={`기획 ${tab.id} 닫기`}>×</button>`이고 `close(id, index)`가 포커스를 `index + 1 === tabs.length ? index - 1 : index + 1` 위치 버튼으로 옮긴 뒤 `closeTab(id)`를 부른다. `web/lib/reducer.ts`의 `tab_closed`는 닫힌 탭이 활성이면 `tabs.find(활성) ?? tabs[0]`(= 항상 맨 앞 탭)을 새 활성으로 고른다. 진행 중인 턴이 있는 탭의 닫기는 reducer가 거부(상태 그대로)하고 버튼도 `disabled`다. 기존 테스트: `tests/tabs.test.tsx`(닫기 128·132·180행 부근: 비활성 탭 닫기, 마지막 탭 교체), `tests/reducer.test.ts`(`tab_closed` 130~175행 부근), `tests/plan.test.tsx` 74행(버튼 `textContent` 배열 `["합성 공간 A · 합성 제품 A", "×", "+ 새 기획", "기획하기"]`).
- 기하: `web/app/plan.css`에서 `.gs-plan-tabs { display:flex; align-items:center; gap: var(--gs-space-4) }`, `.gs-plan-tabs > .gs-button { flex-shrink: 0 }`, `.gs-composer-bar { display:flex; gap: var(--gs-space-3) }`, `.gs-composer-bar .gs-button { flex-shrink: 0 }`이고 `@media (width < 600px)`에서 `.gs-composer-bar`의 gap과 버튼 padding을 줄인다. `.gs-tab-list`(`ui.css`)는 `border-bottom`이 가로줄이고 `.gs-plan-tabs .gs-tab-list { flex: 1 }`이다. 즉 두 줄의 오른쪽 버튼 너비(`+ 새 기획`은 작은 ghost 버튼, `기획하기`는 기본 버튼)와 gap이 달라 가로줄 오른쪽 끝이 입력 칸보다 튀어나온다.
- 실행 기록: `web/app/page.tsx`가 `selectedTurnId` 상태와 `OpenHistoryDetailContext.Provider`(결과의 `검증 상세 보기 →`가 `setSelectedTurnId(turn.id); setView("history")`)를 갖고, `HistoryPage`(`web/components/history/HistoryPage.tsx`)가 `selectedTurnId`가 있으면 `HistoryDetail`(`onBack={() => onSelectTurn(null)}`)을 그린다. `HistoryDetail`의 `목록으로` 버튼은 `PageHeader`의 `actions`에 있다. 광고 기획 화면은 `<div hidden={view !== "plan"}>`로 유지된다(탭·결과 상태 보존). 기존 테스트 `tests/history-page.test.tsx`의 `목록으로` 클릭(59행 부근)과 링크 진입(99·121~124행 부근).
- 쉘: `web/components/shell/AppShell.tsx`가 `view` 상태를 갖고 `TopBar`(`Mark`가 장식 SVG)·`Sidebar`(`nav` `aria-label="주요 화면"`, 그룹 `작업`·`관리`, 항목은 `<NavIcon/>` + 라벨 텍스트)를 그린다. `web/app/shell.css`의 `.gs-shell`은 `grid-template-columns: var(--gs-sidebar-width) minmax(0, 1fr)`이고 `tokens.css`에 `--gs-sidebar-width: 216px`가 있다. 소비자 테스트: `tests/smoke.test.tsx`(15행: `nav`의 `button`이 정확히 5개), `tests/shell.test.tsx`(28~35행: 항목 `textContent`가 라벨 배열과 정확히 같음, 그룹 이름 `작업`·`관리`, 항목마다 `svg[aria-hidden=true]`).
- 근거 소재: `web/components/evidence/EvidencePage.tsx`가 `filter` 상태 하나(`{type:"all"} | {type:"own"} | {type:"platform", source}`)와 버튼 한 줄(`role="group" aria-label="근거 소재 필터"`: `전체`, 플랫폼들, `자사만`)을 갖는다. 플랫폼별 그룹 제목(`YouTube · 7건`)은 `groupByPlatform(visible)`에서 나온다. `source`는 `null`일 수 있다(`출처 정보 없음`). 기존 테스트 `tests/results.test.tsx` 81~97행("marks only the workspace brand, filters own/platform cards and restores all cards"), 98~110행("빈 세션·빈 필터"), `plan.test.tsx`·`tabs.test.tsx`의 `EvidencePage` 사용.

**설계 결정**

1. **탭 닫기 x(`PlanTabs.tsx`, `plan.css`)**: 문자 `×`를 인라인 SVG(`aria-hidden="true"`, `width`·`height` 12, 두 선 `M3 3l6 6M9 3l-6 6`, `stroke="currentColor"`)로 바꾼다. 버튼은 정사각(너비·높이 같은 토큰)이고 `display: inline-flex; align-items: center; justify-content: center; padding: 0; line-height: 1`. `aria-label` `기획 N 닫기`는 그대로, 버튼 안에 텍스트는 없다. 탭 항목(`.gs-plan-tab-item`)은 라벨 버튼과 닫기 버튼이 같은 세로 중심을 갖도록 `display: flex; align-items: center`를 유지하고, 라벨 버튼의 `border-bottom: 2px`가 만드는 시각 중심 차이가 있으면 닫기 버튼에 같은 크기의 `margin-bottom`·`padding-bottom` 보정을 하지 말고 항목 컨테이너에서 정렬한다(예: 라벨 버튼의 위·아래 padding을 대칭으로 두고 활성 표시를 `box-shadow: inset 0 -2px`가 아닌 현재 방식 그대로 두되 닫기 버튼만 `align-self: center`).
2. **활성 탭 닫기 이동(`reducer.ts`, `PlanTabs.tsx`)**: `reducer.ts`에 순수 함수 `nextActiveTabId(tabs: {id:number}[], closedId: number, activeId: number): number | null`을 만들어 내보낸다. 닫힌 탭이 활성이 아니면 `activeId`를 그대로, 활성이면 닫기 전 목록에서 직전 탭(index-1), 맨 앞 탭이면 다음 탭(새 맨 앞), 남는 탭이 없으면 `null`을 돌려준다. `tab_closed`는 이 함수로 새 활성 탭을 고르고(`null`이면 기존대로 빈 새 탭 하나로 교체), 새 활성 탭의 `threadId`로 `state.threadId`를 맞춘다. 진행 중 탭 닫기 거부와 없는 `tabId` 무시(상태 그대로 반환)는 그대로다. `PlanTabs.close()`는 같은 함수로 새 활성 탭 id를 구해 **닫기 전에** 그 탭의 버튼으로 포커스를 옮긴다(닫는 탭이 마지막 하나라서 `null`이면 포커스를 옮기지 않는다).
3. **탭 줄·입력 줄 같은 기하(`plan.css`, `tokens.css`)**: `tokens.css`에 `--gs-action-col-width`(예: 96px)와 `--gs-action-gap`(예: `var(--gs-space-3)`)을 만들고 `@media (width < 600px)`에서 `--gs-action-gap`을 `var(--gs-space-2)`로 다시 정의한다(폭 토큰은 그대로). `.gs-plan-tabs > .gs-button`과 `.gs-composer-bar .gs-button`은 둘 다 `flex: 0 0 var(--gs-action-col-width); width: var(--gs-action-col-width)`(padding-inline은 `0`으로 두고 글자는 가운데 정렬)이고 `.gs-plan-tabs`와 `.gs-composer-bar`의 `gap`은 둘 다 `var(--gs-action-gap)`이다. 600px 미만 미디어 쿼리가 `.gs-composer-bar`의 gap을 직접 바꾸던 줄은 토큰 재정의로 대체한다(두 줄이 항상 같은 토큰을 쓴다). 결과: 가로줄 오른쪽 끝 = 입력 칸 오른쪽 끝, `+ 새 기획` 왼쪽 끝 = `기획하기` 왼쪽 끝. 문구 `+ 새 기획`이 폭 안에 한 줄로 들어가야 한다(`white-space: nowrap`).
4. **실행 기록 돌아가기(`page.tsx`, `HistoryPage.tsx`, `HistoryDetail.tsx`)**: `page.tsx`에 `historyOrigin: "plan" | null` 상태를 둔다. 결과의 `검증 상세 보기 →` 콜백(`OpenHistoryDetailContext`)은 `setHistoryOrigin("plan")`을 함께 호출한다. 목록 행 클릭으로 들어간 상세는 출처가 없다(목록에서 선택할 때 `null`). `HistoryPage`에 `origin`과 `onReturn` props를 추가하고(선택적, 기본 `null`), `origin === "plan"`이면 `HistoryDetail`의 헤더 `actions`에 `목록으로` 옆 버튼 **`광고 기획으로 돌아가기`**(`variant="secondary"`)를 더한다. 이 버튼은 `setHistoryOrigin(null); setView("plan")`이다(광고 기획 화면은 `hidden`만 풀리므로 탭·결과가 그대로 보인다. `selectedTurnId`는 유지한다). `목록으로`는 지금처럼 `onSelectTurn(null)`이고 출처도 `null`로 지운다(`page.tsx`의 선택 콜백에서). `view`가 `history`가 아니게 되면 출처를 항상 지운다(사이드바로 떠난 경우 포함, `useEffect` 또는 `view` 비교). `HistoryDetail`은 선택적 `onReturn?: () => void`를 받고 없으면 버튼을 그리지 않는다(기존 단위 렌더 `detail()`이 그대로 통과).
5. **사이드바 접기(`AppShell.tsx`, `TopBar.tsx`, `Sidebar.tsx`, `Mark.tsx`, `shell.css`, `tokens.css`)**: `TopBar`의 `Mark`를 실제 `<button type="button" className="gs-sidebar-toggle">`으로 감싼다(`Mark` 자체는 장식 SVG 그대로): `aria-label`은 펼침일 때 `사이드바 접기`, 접힘일 때 `사이드바 펼치기`, `aria-expanded={!collapsed}`, `aria-controls={nav의 id}`, `cursor: pointer`, hover 배경(`--gs-accent-weak`)과 `:focus-visible` 윤곽. 상태 `collapsed`는 `AppShell`의 `useState(false)`(기본 펼침, 세션 내 유지, `localStorage` 등 저장 안 함)이고 `useId()`로 만든 nav id를 `Sidebar`(`id` prop)와 `TopBar`(`navId` prop)에 내려 준다. 토글 버튼은 `nav` 바깥(TopBar)에 있어야 한다(`nav`의 `button`이 정확히 5개라는 기존 단언). 접힘 상태는 `.gs-shell`의 `data-sidebar="collapsed"` 속성이고 CSS는 이 속성으로 분기한다: `grid-template-columns: var(--gs-sidebar-rail-width) minmax(0, 1fr)`(`tokens.css`의 새 토큰 `--gs-sidebar-rail-width: 64px`), 그룹 소제목(`.gs-nav-group-label`) `display: none`(그룹의 `aria-label`은 유지), 항목 버튼의 라벨은 **DOM 텍스트를 유지한 채 시각적으로만 숨긴다**(라벨을 `<span className="gs-nav-label">`로 감싸고 접힘일 때만 기존 `.gs-sr-only`와 같은 시각 숨김 규칙을 적용, `display: none` 금지: 버튼의 접근 가능한 이름과 `textContent`가 접힘·펼침에서 같다), 접힘일 때 각 항목 버튼에 `title={라벨}`(펼침일 때는 `title` 없음), 아이콘 가운데 정렬. 폭 전환은 `transition: grid-template-columns var(--gs-motion-accordion)`이고 `@media (prefers-reduced-motion: reduce)`에서 `transition: none`. 880px 미만(가로 내비)에서는 접기가 적용되지 않는다(기존 모바일 규칙 유지, 토글 버튼은 보이되 데스크톱 레일 규칙만 `@media (width >= 880px)`에 둔다).
10. **근거 소재 필터 두 줄(`EvidencePage.tsx`, `evidence.css`)**: 필터 상태를 `{ platform: "all" | { source: string | null }, ownOnly: boolean }` 두 값으로 분리하고 둘을 함께 적용한다(`visible = cards.filter(카드 → (platform이 all이거나 카드.source === platform.source) && (!ownOnly || isOwnBrand(...)))`). 필터 영역은 두 줄이다: 줄 1 `role="group"` `aria-label="플랫폼"`: 버튼 `전체`(= platform을 `all`로 복원, `aria-pressed`는 `platform === "all"`)와 데이터에 있는 플랫폼 버튼들(`platformLabel`, 순서는 기존 `groupByPlatform(cards)` 순서). 줄 2 `role="group"` `aria-label="브랜드"`: 버튼 `전체 브랜드`(ownOnly를 `false`로, `aria-pressed={!ownOnly}`)와 `자사만`(ownOnly를 `true`로, `aria-pressed={ownOnly}`). 두 줄은 `cards.length > 0`일 때만 보이고, 옛 단일 그룹(`aria-label="근거 소재 필터"`)은 없다. 플랫폼별 그룹 제목(`YouTube · 7건`)·빈 상태 문구와 `광고 기획으로` 버튼은 그대로다. CSS는 두 줄 각각 `display:flex; flex-wrap:wrap; gap`이고 줄 사이는 `--gs-space-2`, 줄 앞에 작은 회색 한글 라벨(`플랫폼`·`브랜드`)을 둘 수 있으나 접근 이름은 `aria-label`로 정한다(라벨 글자와 `aria-label`이 같아야 한다).

**교체 단언(이 2건 외에 기존 단언을 수정하지 마라, 조언 세션 승인분)**

| # | 파일·행 | 이전 | 이후 | 이유 |
|---|---|---|---|---|
| R1 | `web/tests/plan.test.tsx` 74행 | `["합성 공간 A · 합성 제품 A", "×", "+ 새 기획", "기획하기"]` | `["합성 공간 A · 합성 제품 A", "", "+ 새 기획", "기획하기"]` | 닫기 버튼이 문자 `×` 대신 SVG가 되어 `textContent`가 빈 문자열이다(정확 일치·개수·순서 유지). 숨김 텍스트 `×`로 통과시키지 마라. 보강 단언: 닫기 버튼은 `aria-label` `기획 1 닫기`, 안에 `svg[aria-hidden="true"]` 정확히 하나, 텍스트 없음 |
| R2 | `web/tests/results.test.tsx` 90행 | `fireEvent.click(screen.getByRole("button", { name: "전체" }));`(`자사만` 클릭 뒤 복원) | `fireEvent.click(screen.getByRole("button", { name: "전체 브랜드" }));` | `전체`는 이제 플랫폼 줄의 복원이고 자사만의 복원은 `전체 브랜드`다. 그 다음 `Instagram` 클릭 이후의 단언과 94행의 마지막 `전체` 복원 단언(`article` 2개)은 수정하지 않는다 |

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `nextActiveTabId` | `web/lib/reducer.ts` | `reducer.ts`(`tab_closed`), `PlanTabs.tsx`(포커스), `reducer.test.ts`, `tabs.test.tsx` |
| `--gs-action-col-width`·`--gs-action-gap`·`--gs-sidebar-rail-width` | `web/app/tokens.css` | `plan.css`, `shell.css`, 새 CSS 구조 테스트 |
| `historyOrigin`·`origin`/`onReturn`/`onReturn?` | `web/app/page.tsx` | `HistoryPage.tsx`, `HistoryDetail.tsx`, `history-page.test.tsx` |
| `collapsed`·`navId` | `web/components/shell/AppShell.tsx` | `TopBar.tsx`, `Sidebar.tsx`, `shell.css`, `shell.test.tsx` |
| 필터 상태 `{platform, ownOnly}` | `web/components/evidence/EvidencePage.tsx` | `results.test.tsx` |

**공통 시각 기준(7c 시각 확인 반영, 이후 모든 새 화면이 따른다)**: 간격은 `tokens.css`의 `--gs-space-*`(4px 배수, 기본 리듬은 8px 단위)만 쓰고 색·반경·그림자·글자 크기도 `tokens.css` 변수만 쓴다. 화면에 보이는 문자열은 **한글**이다(영문 내부 코드·브랜드 슬러그·도구 이름·`value`·`n_top` 같은 필드명을 그대로 노출하지 않는다. `taxonomyNames`의 한글 이름, `web/lib/workspace.ts`의 `workspaceLabel`, 그리고 step 13의 한글 표시 매핑을 재사용하고 없는 이름은 새로 지어내지 말고 원문 대신 `기타`·`정보 없음` 같은 한글 대체를 쓴다). 펼침·접힘은 `grid-template-rows: 0fr → 1fr` 방식의 부드러운 아코디언(화살표 회전)이고, 모든 애니메이션·전환은 `@media (prefers-reduced-motion: reduce)`에서 즉시 동작·정지한다. 색에만 의존하지 않고 아이콘·글자를 함께 쓴다. 접힌 영역의 내용은 DOM에 유지하고 접힌 최종 상태는 기존처럼 `hidden` 속성이다(펼칠 때 `hidden`을 동기적으로 제거한 뒤 다음 프레임에 열림 클래스를 붙이고, 접을 때는 전환 뒤 `hidden`을 설정하되 reduced-motion·전환 시간 0이면 즉시 설정한다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/components/plan/{PlanTabs,PlanPage,Composer}.tsx`, `/web/lib/{reducer,session}.ts*`, `/web/app/{plan,shell,tokens,ui,evidence,history}.css`
- `/web/components/shell/{AppShell,TopBar,Sidebar,Mark,icons}.tsx`, `/web/app/page.tsx`, `/web/components/history/{HistoryPage,HistoryDetail}.tsx`, `/web/components/evidence/EvidencePage.tsx`, `/web/lib/evidence.ts`, `/web/components/ui/*`
- `/web/tests/{tabs,reducer,plan,shell,smoke,history-page,results}.test.ts*`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/lib/reducer.ts`, `web/components/plan/PlanTabs.tsx`, `web/app/plan.css`, `web/app/tokens.css`, `web/app/shell.css`, `web/app/evidence.css`, `web/app/history.css`, `web/app/page.tsx`, `web/components/shell/{AppShell,TopBar,Sidebar,Mark}.tsx`, `web/components/history/{HistoryPage,HistoryDetail}.tsx`, `web/components/evidence/EvidencePage.tsx`, `web/tests/{reducer.test.ts,tabs.test.tsx,plan.test.tsx,shell.test.tsx,smoke.test.tsx,history-page.test.tsx,results.test.tsx,plan-layout.test.ts}`

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/lib/reducer.ts`, `web/components/plan/PlanTabs.tsx`, `web/app/plan.css`, `web/app/tokens.css`, `web/app/shell.css`, `web/app/evidence.css`, `web/app/history.css`, `web/app/page.tsx`, `web/components/shell/{AppShell,TopBar,Sidebar,Mark}.tsx`, `web/components/history/{HistoryPage,HistoryDetail}.tsx`, `web/components/evidence/EvidencePage.tsx`, `web/tests/{reducer.test.ts,tabs.test.tsx,plan.test.tsx,shell.test.tsx,smoke.test.tsx,history-page.test.tsx,results.test.tsx,plan-layout.test.ts}`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `reducer.ts`(`nextActiveTabId`, `tab_closed`)와 `PlanTabs.tsx`(SVG 닫기 버튼, 포커스). **2.** `tokens.css`·`plan.css`(공통 기하 토큰, 닫기 버튼 CSS). **3.** `page.tsx`·`HistoryPage.tsx`·`HistoryDetail.tsx`(돌아가기). **4.** `AppShell.tsx`·`TopBar.tsx`·`Sidebar.tsx`·`shell.css`(사이드바 접기). **5.** `EvidencePage.tsx`·`evidence.css`(필터 두 줄). **6.** 테스트(아래). 위 설계 결정 1~5·10과 "교체 단언" 표를 그대로 구현한다.

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `web/tests/reducer.test.ts`(새 단언 추가만): (1) `nextActiveTabId`: 탭 [1,2,3]에서 활성 3을 닫으면 2, 활성 2를 닫으면 1, 활성 1(맨 앞)을 닫으면 2(다음), 비활성 탭을 닫으면 활성 그대로, 마지막 하나를 닫으면 `null`, (2) `tab_closed` 리듀서: 위 규칙대로 `activeTabId`와 `threadId`가 새 활성 탭 것으로 바뀐다(탭마다 다른 `threadId`로 합성), 진행 중 탭 닫기 거부·없는 `tabId` 무시는 기존 단언 그대로 통과.
- `web/tests/tabs.test.tsx`(새 단언 추가만): (3) UI: 탭 3개에서 활성 3 닫기→2가 선택, 가운데 활성 닫기→직전 탭, 첫 탭 활성 닫기→다음 탭, 비활성 탭 닫기→활성 유지, (4) 닫은 뒤 `document.activeElement`가 새 활성 탭 버튼(활성 탭 닫기와 비활성 탭 닫기 모두), (5) 닫기 버튼은 `svg[aria-hidden="true"]` 정확히 하나·텍스트 없음·`aria-label` `기획 N 닫기`, (6) CSS 구조(`plan.css`·`tokens.css`를 `readFileSync(join(process.cwd(), ...))`로 읽는 기존 방식): `.gs-tab-close` 규칙에 `inline-flex`(또는 `grid`)·`align-items: center`·`justify-content: center`(또는 `place-items: center`)·`line-height: 1`·`padding: 0`과 같은 토큰의 정사각 너비·높이가 있다.
- `web/tests/plan.test.tsx`: 교체 R1(위 표)만. 새 보강 단언은 R1 설명대로.
- `web/tests/tabs.test.tsx` 또는 새 `web/tests/plan-layout.test.ts`(CSS 구조): (7) `tokens.css`가 `--gs-action-col-width`와 `--gs-action-gap`을 정의하고 `@media (width < 600px)` 안에서 `--gs-action-gap`을 다시 정의한다, (8) `plan.css`의 `.gs-plan-tabs > .gs-button` 규칙과 `.gs-composer-bar .gs-button` 규칙이 둘 다 `var(--gs-action-col-width)`를 쓰고, `.gs-plan-tabs`와 `.gs-composer-bar` 규칙의 `gap`이 둘 다 `var(--gs-action-gap)`이다(600px 미만 블록이 두 규칙의 gap을 별도 값으로 덮어쓰지 않는다).
- `web/tests/history-page.test.tsx`(새 단언 추가만, 기존 `목록으로` 단언 수정 없음): (9) `Page`에서 결과의 `검증 상세 보기 →` 링크로 진입하면 `광고 기획으로 돌아가기` 버튼이 있고 누르면 광고 기획 화면이 보이며(사이드바 `광고 기획`의 `aria-current="page"`, `기획 탭` `tablist`와 결과 텍스트가 그대로) `광고 기획으로 돌아가기` 버튼은 다시 사라진다, (10) 같은 진입에서 `목록으로`를 누르면 목록이 보이고 다시 행을 눌러 연 상세에는 돌아가기 버튼이 없다, (11) 목록에서 행을 눌러 진입한 상세에는 돌아가기 버튼이 없고 `목록으로`는 있다, (12) 링크로 진입한 뒤 사이드바로 다른 화면에 갔다가 `실행 기록·검증`으로 돌아오면 돌아가기 버튼이 없다(출처는 화면을 떠날 때 지워진다), (13) `HistoryDetail`을 `onReturn` 없이 단독 렌더하면 돌아가기 버튼이 없다.
- `web/tests/shell.test.tsx`(새 단언 추가만): (14) 토글 `button` 이름이 `사이드바 접기`이고 `aria-expanded="true"`, `aria-controls`가 `nav`의 `id`와 같고 `nav` 안에 있지 않다(`nav`의 `button`은 계속 5개), (15) 누르면 이름이 `사이드바 펼치기`·`aria-expanded="false"`·`.gs-shell`의 `data-sidebar="collapsed"`, 항목 5개의 `textContent`와 접근 이름이 접기 전과 같고(라벨 DOM 유지) 각 항목에 `title`이 라벨과 같게 생기며 그룹 `aria-label`은 유지되고 펼치면 `title`이 사라진다, (16) 기본은 펼침이고 저장하지 않는다(`localStorage`에 키가 생기지 않는다), (17) CSS 구조: `tokens.css`의 `--gs-sidebar-rail-width`, `shell.css`의 `data-sidebar="collapsed"` 규칙이 그 토큰을 쓰고 `transition`이 있으며 `@media (prefers-reduced-motion: reduce)`에서 `transition: none`이다, 토글 버튼에 `cursor: pointer`와 hover·`:focus-visible` 규칙이 있다.
- `web/tests/results.test.tsx`: 교체 R2만(위 표). 새 단언 추가(`EvidencePage` 직접 렌더): (18) `role="group"` 이름 `플랫폼`과 `브랜드` 두 그룹이 있고 옛 `근거 소재 필터` 그룹은 없다, (19) `플랫폼` 그룹에 `전체`와 데이터의 플랫폼들, `브랜드` 그룹에 `전체 브랜드`·`자사만`이 있다, (20) `Instagram` + `자사만` 조합이 서로 독립으로 적용된다(`isntree` 자사 카드는 YouTube, 다른 브랜드 카드는 Instagram인 합성 데이터에서 둘을 함께 켜면 `조건에 맞는 근거 소재가 없습니다` 빈 상태와 `광고 기획으로` 버튼이 보이고, `전체 브랜드`를 누르면 Instagram 카드만, `전체`를 누르면 모두 복원), (21) `aria-pressed` 상태가 두 줄에서 독립이다. 기존 "빈 세션·빈 필터" 테스트의 `자사만` 단언은 수정 없이 통과해야 한다.
- 합성 데이터만 쓴다.
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
- 아래 "교체 단언" 2건(R1·R2) 외의 기존 단언을 수정·삭제·약화하지 마라. 충돌이 나면 구현하지 말고 `blocked`로 멈춰 최소 교체안을 `reason`에 적어라. 이유: 승인된 교체만 허용된다.
- 탭 닫기 버튼에 숨김 텍스트 `×`를 남겨 `plan.test.tsx` 74행을 통과시키지 마라. 이유: 접근 이름이 중복되고 꼼수다.
- `web/lib/{api,sse,types}.ts`·`src/`(서버)·`web/components/results/*`·`web/lib/{localize,insight,taxonomy,stages,history}.ts`를 수정하지 마라(step 16의 몫이거나 범위 밖). 이유: 이 step은 쉘·기획·근거 소재 화면만 고친다.
- 사이드바 접힘 상태를 `localStorage`·쿠키·서버에 저장하지 마라. 접힘일 때 라벨을 `display: none`이나 DOM 제거로 숨기지 마라(시각적으로만 숨긴다). 이유: 세션 내 상태이고 기존 역할·이름 쿼리가 그대로 통과해야 한다.
- 6b-clarify 확인 질문 동작(`ClarifyCard`·`ClarifySummary`·`choice_submitted`)과 `activeTurnId` 동시 요청 차단을 바꾸지 마라. 이유: 승인된 동작이다.
- `web/app`·`web/components`·`web/lib` 소스에 `examples`·`.examples`·`예시 요청` 문자열을 쓰지 마라. 이유: `tests/test_demo_docs.py`의 예시 칩 금지 가드.
