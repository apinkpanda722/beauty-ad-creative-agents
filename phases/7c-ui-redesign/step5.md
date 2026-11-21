# Step 5: graph-core

## 설계 검토 기록

**목적**: 지식 그래프 화면을 **탭 구조**로 만든다. 이 step은 **스키마**와 **근거 경로** 탭을 구현하고, **데이터** 탭은 step 6이 `tabs.tsx`에 한 줄을 더해 켠다(step 6이 없으면 탭이 목록에 나타나지 않는다). 새 패키지·서버 변경·live 호출 없음. 이 step의 **교체 단언은 아래 표 G1·G2 두 건뿐**이고 그 밖의 기존 단언은 수정하지 않는다. 표 밖에서 충돌을 발견하면 구현하지 말고 `blocked`로 멈춰 최소 교체안을 `reason`에 적어라.

**코드를 열어 확인한 사실**
- `web/components/GraphCanvas.tsx`: `GraphLegend`(`aria-label="그래프 범례"`, 섹션 `층`·`노드 종류`)와 `GraphCanvas`(cytoscape 동적 import, 컨테이너 `aria-label="그래프 캔버스"` 인라인 높이 `28rem`, 노드 `label: data(displayName)`, 엣지 `label: data(type)`(영문 관계 이름이 그대로 보인다), 첫 `cy.on` 등록이 `("tap", "node", …)`, 실패 시 `role="alert"`와 `다시 시도`). `GraphPanel.tsx`(근거 경로: `getGraphFragment`+`getSchema`, 섹션 `aria-label="근거 그래프"`, 로딩 `role="status"`·오류 `role="alert"`+`다시 시도`·`그래프에 아직 없는 소재 N건`·`표시할 노드가 없습니다`), `SchemaView.tsx`(섹션 `aria-label="전체 스키마"`, `getSchema`, `breadthfirst`), `NodeDetail.tsx`(`aside` `aria-label="노드 상세"`: 레이블·이름과 `props` 키/값 목록, 키는 서버 원문(`url`, `latest_view_count` 등), `url`·`source_url`만 안전한 링크, 비문자열 값은 `JSON.stringify`).
- `web/lib/graph.ts`: `LAYER_COLORS`, `LABEL_COLORS`, `GRAPH_LEGEND`(정확히 `층` 3개·`노드 종류` 2개 항목), `fragmentToElements`, `schemaToElements`, `GraphElement`(엣지 데이터 `{id, source, target, type}`). 서버가 내려주는 노드 `props` 키는 `src/beautyads/graph/fragment_queries.py`의 `_PROPERTIES`: Creative `source·url·brand·published_at·latest_view_count·latest_like_count`, Hook·Angle·Format·Talent·CtaType·Efficacy `value`, Product `brand·source_url·name_ko`, Brand `name`. 노드 라벨 18종과 관계 유형은 `src/beautyads/graph/ontology_view.py`의 `ONTOLOGY_LABELS`(`name_ko` 포함)·`ONTOLOGY_RELATIONSHIPS`에 닫힌 목록으로 있다(관계: CONTAINS·CLAIMS·ALIAS_OF·USES_HOOK·HAS_ANGLE·HAS_FORMAT·FEATURES·HAS_CTA·MENTIONS·PROMOTES·OWNS·IN_CATEGORY·HAS_EFFICACY·CERTIFIED_AS·HAS_FORM·APPLIES_TO·ADDRESSES·SUITS·ABOUT).
- `web/components/plan/TurnCard.tsx`: `ResultsView`에 `onOpenGraph={tenantId ? setGraphIds : undefined}`를 넘기고 그 아래에 `<GraphPanel>`을 **턴 안에 인라인**으로 그린다. `ResultsView`의 `근거 그래프 보기` 버튼(`onOpenGraph(ids)`를 정확히 한 번 호출)은 그대로 둔다. `web/app/page.tsx`는 `view === "graph"`일 때 `PageHeader title="지식 그래프"`와 `state.tenantId ? <SchemaView/> : <p>상단 바에서 작업 공간을 선택하세요.</p>`를 그린다. 광고 기획 화면은 `<div hidden={view !== "plan"}>`로 유지된다. 실행 기록 진입 출처 방식(`historyOrigin`, `OpenHistoryDetailContext`, 사이드바로 화면을 떠나면 출처를 지움)은 step 15가 만들었다.
- 소비자 테스트: `tests/graph-view.test.tsx`(`GraphPanel`·`SchemaView`·`GraphCanvas`·`GraphLegend`·`NodeDetail`을 `components/` 경로에서 import, `GraphLegend` 항목 정확 일치, 노드 스타일 글자 크기, cose 옵션 값, `cy.on.mock.calls[0]`이 `["tap","node",…]`, 110~131행 페이지 흐름), `tests/graph.test.ts`(`GRAPH_LEGEND` 구조, `fragmentToElements` 표시 이름), `tests/shell.test.tsx`(지식 그래프 항목: 작업 공간이 없으면 `상단 바에서 작업 공간을 선택하세요.`, 선택 뒤 `표시할 노드가 없습니다`와 `getSchema`가 정확히 한 번 호출).

**설계 결정**
1. **기존 컴포넌트는 삭제하지 않는다**: `web/components/{GraphCanvas,GraphPanel,SchemaView,NodeDetail}.tsx`는 제자리에서 수정해 재사용한다(테스트의 import 경로가 그대로 유지된다). 새 파일: `web/components/graph/GraphPage.tsx`, `tabs.tsx`, `context.ts`, `GraphFilters.tsx`, `web/app/graph.css`.
2. **`GraphPage`(탭)**: `PageHeader`(제목 `지식 그래프`, 설명 한 문장 `광고 지식이 어떻게 연결되어 있는지 노드(점)와 관계(선)로 살펴봅니다.`)와 `Tabs`(`label="지식 그래프 보기"`). 탭 정의는 `tabs.tsx`의 배열 한 곳이다: `GRAPH_TABS: { id: string; label: string; render: (context: GraphTabContext) => ReactNode }[]`, 이 step은 `schema`(`스키마`)·`path`(`근거 경로`) 두 개를 이 순서로 넣는다(`GraphTabContext = { tenantId: string; pathIds: string[] | null }`). `GraphPage`는 이 배열을 순회해 탭과 패널을 그리고 **활성 탭만 내용을 마운트**한다(비활성 탭의 `panel`은 빈 조각이라 캔버스가 만들어지지 않는다). 초기 활성 탭은 `schema`다. 활성 탭은 `GraphPage`의 `tab`·`onTabChange` props로 제어된다. 작업 공간이 없으면(`tenantId === null`) 지금처럼 `상단 바에서 작업 공간을 선택하세요.`만 보인다(정확한 문구 유지). 각 탭 위에 이 화면이 무엇을 보여 주는지 한 문장이 있다: 스키마 `그래프에 어떤 종류의 노드와 관계가 있는지 보여 줍니다. 층은 1층 제품 지식, 2층 광고에서 관찰한 값, 3층 승인·반려 피드백입니다.`, 근거 경로 `기획안이 근거로 쓴 광고 소재가 어떤 값들과 연결되는지 보여 줍니다.`(`<p class="gs-graph-note">`).
3. **근거 경로 진입(`context.ts`, `TurnCard.tsx`, `page.tsx`)**: `context.ts`에 `OpenGraphPathContext = createContext<((ids: string[]) => void) | null>(null)`. `page.tsx`가 `graphTab`(`"schema"` 기본)·`graphPathIds: string[] | null`·`graphOrigin: "plan" | null` 상태를 갖고 컨텍스트 값은 `ids => { setGraphPathIds(ids); setGraphTab("path"); setGraphOrigin("plan"); setView("graph"); }`다. `TurnCard`는 `onOpenGraph`에 이 컨텍스트 함수를 넘기고(`tenantId`가 있을 때만) **턴 안 인라인 `<GraphPanel>`은 그리지 않는다**(`useState`·`GraphPanel` import 제거). 근거 경로 탭의 ids는 `graphPathIds`가 있으면 그것, 없으면 `latestGraphIds(turns)`(`web/lib/graph.ts`에 새로 만드는 순수 함수: 모든 턴의 `show_graph_fragment` 명령 중 **가장 마지막 것**의 `evidence_ids`, 없으면 `null`)다. ids가 `null`이면 `EmptyState`(`광고 기획에서 요청을 실행하면 근거 경로가 표시됩니다`, 행동 `광고 기획으로`)다. 근거 경로 탭의 `GraphPanel`은 기존 로딩·오류·재시도·`missing` 문구 동작을 그대로 쓴다. `graphOrigin === "plan"`이면 `GraphPage` 헤더 `actions`에 `광고 기획으로 돌아가기`(`variant="secondary"`) 버튼이 있고 누르면 `setGraphOrigin(null); setView("plan")`이다. `view`가 `graph`가 아니게 되면 `graphOrigin`을 항상 지운다(step 15가 `historyOrigin`을 지우는 방식과 같은 `useEffect`). 사이드바로 들어간 지식 그래프에는 돌아가기 버튼이 없고 활성 탭은 마지막으로 보던 탭이다.
4. **확대·축소 한계(`graph.ts`, `GraphCanvas.tsx`)**: `ZOOM_LIMITS = { min: 0.3, max: 2.5 }`를 `graph.ts`에서 내보내고, `GraphCanvas`가 cytoscape 생성 옵션 `minZoom`·`maxZoom`에 이 값을 넣고 `wheelSensitivity`는 상수(0.2)로 낮춘다. 캔버스 오른쪽 위에 `＋`·`－`·`맞춤` 버튼 세 개(접근 이름 `확대`·`축소`·`화면에 맞춤`, 문자 대신 인라인 SVG 아이콘, `aria-hidden`)를 둔다. 확대는 `cy.zoom(...)`으로 `ZOOM_LIMITS` 안에서만 움직이고 한계에서 해당 버튼이 `disabled`다. 버튼 상태는 `cy.on("zoom", …)`(두 번째 이후 등록: 첫 `cy.on`은 반드시 `("tap","node",…)`로 유지)으로 갱신한다. 캔버스 높이는 인라인 `28rem`을 없애고 `graph.css`의 `--gs-graph-height`(예: `min(70dvh, 40rem)`) 토큰을 쓴다.
5. **레이아웃·필터(`GraphFilters.tsx`, `graph.css`, `GraphPanel.tsx`, `SchemaView.tsx`)**: 캔버스 영역은 `grid-template-columns: minmax(0, 1fr) var(--gs-graph-detail-width)`이고 **사이드바 폭 토큰(`--gs-sidebar-width`·`--gs-sidebar-rail-width`)을 참조하지 않는다**(사이드바가 접혀도 캔버스·패널이 깨지지 않는다). `GraphLegend`의 출력(항목·색)은 바꾸지 않는다. `GraphFilters`는 범례 아래에 **기준마다 줄을 나눈 토글 그룹 두 개**: `role="group"` `aria-label="층 필터"`(`1층 · 제품 지식`·`2층 · 광고 관찰`·`3층 · 피드백` 토글, `aria-pressed`)와 `aria-label="노드 종류 필터"`(현재 그래프에 있는 노드 라벨별 토글, 한글 이름은 아래 6번)이고 두 그룹은 독립 적용된다(꺼진 층·종류의 노드와 그에 연결된 엣지를 캔버스 `elements`에서 뺀다; 기본은 모두 켬). `GraphPanel`·`SchemaView`가 범례 아래에 `GraphFilters`를 그리고 필터된 `elements`를 캔버스에 넘긴다(필터가 기본 상태일 때 `cy.create`의 `elements` 개수·내용은 지금과 같다). 피드백(3층)은 작업 공간 범위 데이터임을 범례 아래 문장 `3층 피드백은 이 작업 공간의 데이터입니다.`로 표시한다.
6. **한글 표시 이름(`graph.ts`, `NodeDetail.tsx`, `GraphCanvas.tsx`; 원본 데이터는 변형하지 않는다)**: `graph.ts`에 `NODE_LABEL_NAMES`(`ONTOLOGY_LABELS`의 18개 `label` → `name_ko`와 같은 값)와 `RELATIONSHIP_NAMES`(`ONTOLOGY_RELATIONSHIPS`의 관계 유형 19종 전부에 한글 이름: CONTAINS `포함`, CLAIMS `주장`, ALIAS_OF `별칭`, USES_HOOK `훅 사용`, HAS_ANGLE `소구`, HAS_FORMAT `형식`, FEATURES `출연`, HAS_CTA `행동 유도`, MENTIONS `언급`, PROMOTES `홍보`, OWNS `소유`, IN_CATEGORY `카테고리`, HAS_EFFICACY `효능`, CERTIFIED_AS `인증`, HAS_FORM `제형`, APPLIES_TO `적용 대상`, ADDRESSES `해결`, SUITS `적합`, ABOUT `피드백 대상`)와 `PROPERTY_NAMES`(Creative `source` `출처`, `url` `원본 링크`, `brand` `브랜드`, `published_at` `게시일`, `latest_view_count` `조회수`, `latest_like_count` `좋아요`, `value` `값`, `source_url` `판매처 링크`, `name_ko` `제품명`, `name` `이름`)를 둔다. 엣지의 캔버스 라벨은 `data(typeName)`(새 데이터 필드, 관계 이름이 없으면 원문 유형)이고 엣지 `type` 필드는 그대로 둔다. `NodeDetail`은 라벨을 `NODE_LABEL_NAMES`로(없으면 원문), 속성 키를 `PROPERTY_NAMES`로(없는 키는 원문 키), 값 중 `source`는 `platformLabel`, `value`는 노드 라벨에 맞는 분류 한글 이름(`Hook`·`Angle`·`Format`·`Efficacy`는 `taxonomyNames`, 호출자가 `names`를 선택적 prop으로 넘기고 기본은 `taxonomyNames()`; 소구 `desire`는 `이상형 제시형`으로 나온다)으로 표시한다(원문 값 객체는 변형하지 않는다. 비문자열 값은 지금처럼 `JSON.stringify`). 서버의 닫힌 목록과 이 사전이 어긋나지 않게 새 파이썬 테스트가 `ontology_view.py`와 `graph.ts`를 대조한다(아래).
7. **새 시각 기준**: 모든 간격·색·반경은 토큰, 접힘이 없는 화면이라 아코디언 규칙은 해당 없음, 모션은 `prefers-reduced-motion: reduce`에서 정지, 영문 노드·관계·속성 이름 노출 없음(사전에 없는 값만 원문), 화면 제목 아래 한 문장(2번), 탭·필터는 기준마다 줄이 다르다.

**교체 단언(조언 세션 승인 범위: 사용자가 승인한 용어·화면 기준에서 생기는 결과. 이 표 밖의 기존 단언을 수정하지 마라)**

| # | 파일·행 | 이전 | 이후 | 이유 |
|---|---|---|---|---|
| G1 | `web/tests/graph-view.test.tsx` 95행(`it.each` "renders only server props and safe URL links") | `for (const text of ["Creative", "합성 노드", "synthetic_flag", "false", "synthetic_nested"]) expect(detail.textContent).toContain(text);` | 배열의 `"Creative"` → `"광고 소재"`(나머지 네 문구는 그대로: 사전에 없는 속성 키 `synthetic_flag`·`synthetic_nested`와 `false`는 원문 유지) | 노드 라벨의 영문 코드 노출 금지(새 시각 기준 1): `Creative` 라벨은 한글 `광고 소재`로 표시된다 |
| G2 | `web/tests/graph-view.test.tsx` 127행(`it("switches page tabs, preserves conversation and opens the command graph with the selected tenant")`) | `fireEvent.click(screen.getByRole("button", { name: "지식 그래프" }));`(근거 그래프를 연 뒤 사이드바로 스키마 화면에 진입) | `fireEvent.click(screen.getByRole("tab", { name: "스키마" }));`(`근거 그래프 보기`는 이제 같은 화면의 근거 경로 탭을 연다. 128행 `aria-current` 단언과 129행 `cy.create` 2회 단언·130행 광고 기획 복귀·`합성 응답` 단언은 수정하지 않는다) | 근거 그래프가 턴 안 인라인에서 지식 그래프 > 근거 경로 탭으로 이동했다(승인된 설계) |

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `ZOOM_LIMITS`, `latestGraphIds`, 한글 이름 사전 | `web/lib/graph.ts` | `GraphCanvas.tsx`, `GraphPage.tsx`, `NodeDetail.tsx`, `page.tsx`, 테스트 |
| `GRAPH_TABS`(탭 목록 한 곳) | `web/components/graph/tabs.tsx` | `GraphPage.tsx`, step 6 |
| `OpenGraphPathContext` | `web/components/graph/context.ts` | `TurnCard.tsx`, `page.tsx` |
| 사전 대조 테스트 | `tests/test_web_graph_names.py` | `src/beautyads/graph/ontology_view.py`, `web/lib/graph.ts` |

**공통 시각 기준(7c 시각 확인 반영, 이후 모든 새 화면이 따른다)**: 간격은 `tokens.css`의 `--gs-space-*`(4px 배수, 기본 리듬은 8px 단위)만 쓰고 색·반경·그림자·글자 크기도 `tokens.css` 변수만 쓴다. 화면에 보이는 문자열은 **한글**이다(영문 내부 코드·브랜드 슬러그·도구 이름·`value`·`n_top` 같은 필드명을 그대로 노출하지 않는다. `taxonomyNames`의 한글 이름, `web/lib/workspace.ts`의 `workspaceLabel`, 그리고 step 13의 한글 표시 매핑을 재사용하고 없는 이름은 새로 지어내지 말고 원문 대신 `기타`·`정보 없음` 같은 한글 대체를 쓴다). 펼침·접힘은 `grid-template-rows: 0fr → 1fr` 방식의 부드러운 아코디언(화살표 회전)이고, 모든 애니메이션·전환은 `@media (prefers-reduced-motion: reduce)`에서 즉시 동작·정지한다. 색에만 의존하지 않고 아이콘·글자를 함께 쓴다. 접힌 영역의 내용은 DOM에 유지하고 접힌 최종 상태는 기존처럼 `hidden` 속성이다(펼칠 때 `hidden`을 동기적으로 제거한 뒤 다음 프레임에 열림 클래스를 붙이고, 접을 때는 전환 뒤 `hidden`을 설정하되 reduced-motion·전환 시간 0이면 즉시 설정한다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/components/{GraphCanvas,GraphPanel,SchemaView,NodeDetail}.tsx`, `/web/lib/{graph,api,types,evidence,taxonomy}.ts*`, `/web/components/ui/*`, `/web/components/plan/TurnCard.tsx`, `/web/components/results/ResultsView.tsx`, `/web/app/page.tsx`, `/web/app/{globals,tokens,shell}.css`
- `/src/beautyads/graph/{ontology_view,fragment_queries}.py`(닫힌 목록·속성 키, 읽기 전용)
- `/web/tests/{graph,graph-view,shell,history-page}.test.ts*`, `/tests/test_architecture.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/lib/graph.ts`, `web/components/{GraphCanvas,GraphPanel,SchemaView,NodeDetail}.tsx`, `web/components/graph/{GraphPage.tsx,GraphFilters.tsx,tabs.tsx,context.ts}`, `web/app/graph.css`, `web/components/plan/TurnCard.tsx`, `web/app/page.tsx`, `web/tests/{graph.test.ts,graph-view.test.tsx,graph-page.test.tsx}`, `tests/test_web_graph_names.py`

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/lib/graph.ts`, `web/components/{GraphCanvas,GraphPanel,SchemaView,NodeDetail}.tsx`, `web/components/graph/{GraphPage.tsx,GraphFilters.tsx,tabs.tsx,context.ts}`, `web/app/graph.css`, `web/components/plan/TurnCard.tsx`, `web/app/page.tsx`, `web/tests/{graph.test.ts,graph-view.test.tsx,graph-page.test.tsx}`, `tests/test_web_graph_names.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `web/lib/graph.ts`(`ZOOM_LIMITS`, `latestGraphIds`, 한글 이름 사전, 엣지 `typeName`). **2.** `GraphCanvas.tsx`(줌 한계·버튼·높이 토큰·엣지 라벨), `NodeDetail.tsx`(한글 표시), `GraphPanel.tsx`·`SchemaView.tsx`(필터·문장). **3.** `web/components/graph/{GraphPage,GraphFilters}.tsx`, `tabs.tsx`, `context.ts`, `web/app/graph.css`. **4.** `TurnCard.tsx`(인라인 그래프 제거)와 `page.tsx`(상태·컨텍스트·본문 연결, 출처 지우기). **5.** 테스트(아래). 위 설계 결정 1~7과 교체 단언 표 G1·G2를 그대로 구현한다.

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `tests/test_web_graph_names.py`(새, 파이썬): (1) `ONTOLOGY_LABELS`의 모든 `label`이 `web/lib/graph.ts`의 `NODE_LABEL_NAMES` 키로 있고 값이 `name_ko`와 같다, (2) `ONTOLOGY_RELATIONSHIPS`의 모든 `type`이 `RELATIONSHIP_NAMES`에 있다(텍스트 검색으로 확인, 해시 순서에 기대지 않는다), (3) `fragment_queries._PROPERTIES`의 모든 속성 키가 `PROPERTY_NAMES`에 있다.
- `web/tests/graph.test.ts`(기존 단언 수정 없음, 새 단언 추가만): (4) `ZOOM_LIMITS`가 `{ min: 0.3, max: 2.5 }`이고 `min < max`, (5) `latestGraphIds`: 마지막 `show_graph_fragment`의 ids, 명령이 없으면 `null`, 입력 불변, (6) 엣지 요소의 `typeName`이 한글 이름이고 사전에 없는 유형은 원문이며 `type`은 원문 그대로, (7) `NODE_LABEL_NAMES`에 `Creative`가 `광고 소재`.
- `web/tests/graph-view.test.tsx`: 교체 G1·G2만. 새 단언 추가: (8) 캔버스 생성 옵션의 `minZoom`·`maxZoom`이 `ZOOM_LIMITS`, (9) 가짜 `cy`(`zoom`·`on` 모의)로 확대 버튼이 최대 한계에서, 축소 버튼이 최소 한계에서 `disabled`이고 첫 `cy.on` 호출은 `("tap","node")`, (10) `NodeDetail`: 속성 키가 한글(`url` → `원본 링크`, `latest_view_count` → `조회수`), 사전에 없는 키는 원문, `source: "youtube"`는 `YouTube`, `Hook`의 `value`는 스키마 이름, 값 `desire`(소구)는 `이상형 제시형`이고 입력 객체는 불변, (11) 엣지 라벨이 관계 한글 이름으로 캔버스 스타일에 연결(`label: data(typeName)`).
- `web/tests/graph-page.test.tsx`(새): (12) 탭 이름 목록이 `GRAPH_TABS`의 라벨 배열과 정확히 같고 첫 탭이 `스키마`다, (13) 활성 탭만 마운트(스키마 탭에서는 근거 경로의 `getGraphFragment`가 호출되지 않는다), (14) 근거 경로 탭: ids가 없으면 `EmptyState`와 `광고 기획으로` 버튼, 있으면 `getGraphFragment`가 정확히 그 ids로, (15) `광고 기획으로 돌아가기`: `OpenGraphPathContext`로 들어오면 있고 눌러 광고 기획으로 가며(탭·결과 그대로), 사이드바로 들어오면 없고, 떠났다가 사이드바로 돌아오면 없다, (16) 필터: 두 그룹(`층 필터`·`노드 종류 필터`)이 서로 다른 `role="group"`이고 층 하나를 끄면 그 층의 노드와 연결 엣지가 캔버스 `elements`에서 빠지며 노드 종류 필터와 독립이다, 기본 상태에서는 `elements`가 필터 없을 때와 같다, (17) `graph.css`가 `--gs-sidebar-width`·`--gs-sidebar-rail-width`를 참조하지 않고 캔버스 열이 `minmax(0, 1fr)`이며 `prefers-reduced-motion` 규칙이 있다, (18) 화면에 영문 라벨(`Creative`·`USES_HOOK`)이 노출되지 않는다.
- `web/tests/shell.test.tsx`: 수정 없음(지식 그래프 항목의 기존 단언이 그대로 통과해야 한다). 해시 시드·집합 순회 순서에 기대는 새 단언을 만들지 마라. 합성 데이터만 쓴다.
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
- 교체 단언 표(G1·G2) 밖의 기존 단언을 수정·삭제·약화하지 마라. 충돌이 나면 구현하지 말고 `blocked`로 멈춰 최소 교체안을 `reason`에 적어라. 이유: 승인된 교체만 허용된다.
- `web/components/{GraphCanvas,GraphPanel,SchemaView,NodeDetail}.tsx`를 삭제하거나 이름·경로를 바꾸지 마라(제자리 수정). `GraphLegend`의 출력 항목과 `GRAPH_LEGEND`·`LAYER_COLORS`·`LABEL_COLORS`의 기존 값을 바꾸지 마라. 이유: 기존 테스트의 import 경로와 정확 일치 단언이 있다.
- `web/lib/api.ts`의 `getGraphFragment`·`getSchema` 계약, `src/`(서버), `web/lib/types.ts`를 수정하지 마라. 서버가 보내지 않는 필드를 가정하지 마라. 이유: 서버 계약 불변.
- Neo4j·Cypher를 웹에서 직접 다루거나 질의 입력 칸을 만들지 마라. 영문 노드 라벨·관계 유형·속성 키를 마케터 화면에 그대로 노출하지 마라(사전에 없는 값만 원문). 원본 `props`·`nodes`를 변형하지 마라. 이유: 에이전트·사용자에게 Cypher를 쓰게 하지 않는다(AGENTS.md)와 새 시각 기준.
- `web/components/shell/*`·`web/components/plan/*`(`TurnCard.tsx` 제외)와 `web/components/history/*`를 수정하지 마라. 이유: 범위 분리.
- `web/app`·`web/components`·`web/lib` 소스에 `examples`·`.examples`·`예시 요청` 문자열을 쓰지 마라. 이유: `tests/test_demo_docs.py`의 예시 칩 금지 가드.
