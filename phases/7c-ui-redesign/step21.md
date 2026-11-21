# Step 21: graph-polish

## 설계 검토 기록

**목적**: 사용자가 목업 확인 뒤 승인한 4차 수정(지식 그래프 스키마·데이터 탭 스타일, 항목 1~11)을 한 step으로 처리한다. 새 패키지 없음(Cytoscape 3.35.0 내장 스타일·레이아웃만 쓴다. NVL 등 Neo4j 시각화 라이브러리는 라이선스가 Aura·상용 판 전용이라 금지). **서버(`src/`) 변경 없음**, live 호출 없음. 확대·축소 제한(`ZOOM_LIMITS` 0.3~2.5), 노드 클릭 확장(`이웃 펼치기`), 브랜드 표시(`brandDisplayName`), 한글 표시 사전, 노드 상세 패널 동작은 바꾸지 않는다. 기존 단언은 그대로 두고 아래 "교체 단언" 표만 바꾼다. 표의 대상이 통과하면 수정하지 않는다. 표 밖에서 충돌이 나면 구현하지 말고 `blocked`로 멈춰 최소 교체안(같은 사실·같은 엄격도)을 `reason`에 적어라.

**코드를 열어 확인한 사실**
- `web/components/GraphCanvas.tsx`: 내보내기 `GraphLegend`(`aria-label="그래프 범례"`, 두 그룹 `층`·`노드 종류`의 `h4`+`ul.graph-legend`+색 점)와 `GraphCanvas`. `GraphCanvas`는 `import("cytoscape")` 뒤 `cytoscape({ container, elements, minZoom, maxZoom, wheelSensitivity: 0.2, layout, style })`를 만들고 **첫 `cy.on`은 `("tap", "node", …)`, 다음이 `("zoom", …)`**다. 레이아웃: cose는 `{ name, animate: false, padding: space * 9, nodeRepulsion: 8192, idealEdgeLength: space * 25, nodeOverlap: space * 4, nodeDimensionsIncludeLabels: true }`, breadthfirst는 `{ name, animate: false, padding: space * 9 }`. 스타일은 토큰을 `getComputedStyle(container).getPropertyValue("--gs-…")`로 읽는다(jsdom에서는 빈 문자열이라 숫자 값은 `|| 기본값`). 노드 `font-size: fontSize * 5 / 6`(=10), 간선 `font-size: fontSize * 7 / 12`(=7), 간선 `width: border * 1.5`, 색 `--gs-border`. 버튼 그룹 `.gs-graph-controls`(`role=group` `aria-label="그래프 배율"`, 확대·축소·화면에 맞춤)는 `graph.css`에서 `position: absolute; top; right`. `화면에 맞춤`은 `core.current?.fit()`을 정확히 한 번 호출한다.
- `web/components/graph/GraphFilters.tsx`: `useGraphFilters(elements)`(`hiddenLayers`·`hiddenLabels`·`labels`·`toggleLayer`·`toggleLabel`·`elements`(필터 적용))와 `GraphFilters`(`.gs-graph-filters` 안에 `role=group` `aria-label="층 필터"`(`GRAPH_LEGEND[0].items`의 이름 버튼 3개)와 `aria-label="노드 종류 필터"`(`NODE_LABEL_NAMES[label] ?? label` 버튼들), 모두 `Button variant="ghost" size="sm"` `aria-pressed`). 사용처 3곳: `SchemaView.tsx`·`GraphPanel.tsx`(근거 경로)·`graph/DataTab.tsx`가 모두 `<GraphLegend />`와 `<GraphFilters {...filters} />`를 함께 그린다.
- `web/lib/graph.ts`: `LAYER_COLORS = { 1: "#427c69", 2: "#527cac", 3: "#8961a8" }`, `LABEL_COLORS = { Creative: "#365d89", Product: "#286550" }`, `GRAPH_LEGEND`(그룹 `층`(3개 항목, 색 = `LAYER_COLORS`)과 `노드 종류`(`제품`·`광고 소재`)), `nodeElement(node, displayName, layer)`가 `color: LABEL_COLORS[label] ?? LAYER_COLORS[layer]`를 넣고 `GraphElement`의 노드 `data`는 `GraphNode & { displayName, layer, color }`다. `fragmentToElements`(데이터·근거 경로 탭)와 `schemaToElements`(스키마 탭)가 같은 `nodeElement`를 쓴다.
- `web/app/graph.css`: `.gs-graph-filter-group button`(테두리·알약), `[aria-pressed="true"]`(accent), `.gs-graph-controls { top; right }`, `.gs-graph-page [aria-label="그래프 범례"] h4`, `.graph-legend` 3줄. `web/app/globals.css` 42~44행에도 `.graph-legend` 규칙 3줄이 있고 `web/tests/cleanup.test.ts`가 **globals.css의 소비자 없는 클래스 규칙**을 실패로 본다.
- 기존 테스트가 고정하는 것(수정하지 않는다): `graph-view.test.tsx`는 cytoscape를 `vi.mock`하고 반환 객체를 `{ destroy, on }`(어떤 테스트는 `{ on, destroy, zoom, fit }`)으로만 가짜 만든다 → **`cy.resize`·`cy.elements`·`cy.fit` 등을 초기 설정 때 무조건 호출하면 안 된다**(`resize`는 `?.`로 부르고 `fit`은 버튼 클릭 때만). `cy.on.mock.calls[0].slice(0, 2)`가 `["tap","node"]`이고 `zoom` 호출을 `find`로 찾는다. `화면에 맞춤` 클릭 뒤 `fit`이 정확히 1회. cose 옵션(`nodeRepulsion > 2048`, `idealEdgeLength > 32`, `nodeOverlap > 4`), 줌 경계, 노드 `text-margin-y`(0 이상 7 미만), 간선 `label === "data(typeName)"`. `graph-page.test.tsx`: `층 필터`·`노드 종류 필터` 그룹 이름, 두 그룹의 **같은 부모**, 버튼 `textContent` 배열 정확 일치(`["제품","광고 소재","훅 유형","피드백"]`, `["브랜드","제품","효능"]`), `aria-pressed`, `graph.css`의 `grid-template-columns: minmax(0, 1fr) var(--gs-graph-detail-width)`·`--gs-graph-height`·`height: var(--gs-graph-height)`·`prefers-reduced-motion`·`.gs-graph-filter-group { display: flex }`. `graph.test.ts`: `schemaToElements`의 노드 색 = `LABEL_COLORS[label] ?? LAYER_COLORS[layer]`(스키마 입력 `Product`·`Creative`·`Feedback`), 조각 노드 색이 모두 `GRAPH_LEGEND`의 어떤 항목 색, `LAYER_COLORS` 값 3개가 서로 다름, `GRAPH_LEGEND` 그룹 제목 `["층","노드 종류"]`, `GRAPH_LEGEND[0]` 색 = `Object.values(LAYER_COLORS)`, `GRAPH_LEGEND[1]` 색 집합 = `Object.values(LABEL_COLORS)` 집합.

**설계 결정**

**공통(스키마·데이터·근거 경로 탭, `GraphCanvas.tsx`·`graph.css`)**
1. **글자(항목 1)**: 노드 `font-size: fontSize`(=12, `--gs-text-xs`), 간선 `font-size: fontSize * 11 / 12`(=11). 노드 이름에 외곽선 `"text-outline-color": color("--gs-surface")`, `"text-outline-width": border * 2`, `"text-outline-opacity": 1`. 관계 이름에 작은 배경 알약: `"text-background-color": color("--gs-surface")`, `"text-background-opacity": 1`, `"text-background-shape": "roundrectangle"`, `"text-background-padding": "${space * 0.6}px"`(≈2.4px). 기존 노드 `text-margin-y`(= `space`)·`text-valign: bottom`·`text-wrap`은 유지.
2. **선(항목 2)**: 간선 `width: border * 2`(기존 1.5배보다 약 1.4배), 색 `line-color`·`target-arrow-color`는 `color("--gs-text-muted")`(`--gs-border-strong` 토큰이 없으므로), `"target-arrow-shape": "triangle"`, `"arrow-scale": 1.1`, `"curve-style": "unbundled-bezier"`, `"control-point-distances": [space * 4]`, `"control-point-weights": [0.5]`(약한 곡률, 읽기 우선으로 구현 세션이 조정 가능). 노드 기본 테두리 `border-width: border * 1.5`, `border-color: data(borderColor)`(없으면 기본), `node:selected`는 지금처럼 `border-color: --gs-text`, `border-width: border * 3` 유지.
3. **화면 맞춤(항목 3)**: 레이아웃 옵션에 `fit: true`와 `padding: space * 12`(=48px, 가장자리 라벨 잘림 방지와 오른쪽 아래 버튼 그룹 여백)를 준다(cose·breadthfirst 모두; cose의 기존 `nodeRepulsion`·`idealEdgeLength`·`nodeOverlap`·`nodeDimensionsIncludeLabels` 값은 그대로, breadthfirst에는 `spacingFactor: 1.25` 추가). **초기에 `cy.fit()`을 호출하지 않는다.** 컨테이너 크기 변화(탭 전환 직후 등)에는 `ResizeObserver`(없는 환경은 건너뜀)로 `cy.resize?.()`만 부르고 정리 시 `disconnect`한다(`fit` 호출 금지).
4. **버튼 위치(항목 4)**: `.gs-graph-controls`를 캔버스 **오른쪽 아래** 모서리로 옮긴다(`bottom: var(--gs-space-3); right: var(--gs-space-3)`, `top` 제거). 버튼 이름·아이콘·비활성 규칙·DOM 순서는 그대로.
5. **마우스 올림 강조(항목 5)**: `cy.on("tap", …)`·`cy.on("zoom", …)` **다음에** `cy.on("mouseover", "node", e => …)`·`cy.on("mouseout", "node", () => …)`를 등록한다(첫 `cy.on`이 `tap`이어야 한다). `mouseover`는 `const keep = e.target.closedNeighborhood(); cy.elements().not(keep).addClass("gs-dim")`, `mouseout`은 `cy.elements().removeClass("gs-dim")`. 스타일 배열에 `{ selector: ".gs-dim", style: { opacity: 0.3 } }`. 핸들러 안에서만 `cy.elements`를 부른다(초기 설정에서는 부르지 않는다).
6. **범례·필터 통합(항목 6)**: `GraphLegend`(컴포넌트)와 `aria-label="그래프 범례"` 컨테이너, 두 그룹 `층`/`노드 종류` `h4`를 렌더하지 않는다. `GraphLegend` export와 `SchemaView`·`GraphPanel`·`DataTab`·`graph-view.test.tsx`의 import·사용을 `rg`로 소비자 0이 되게 정리하고, `.graph-legend`(`globals.css` 3줄, `graph.css` 3줄)와 `[aria-label="그래프 범례"]` 규칙도 삭제한다(`cleanup.test.ts` 통과). `GraphCanvas.tsx`에서 `GRAPH_LEGEND` import가 남으면 제거. `GraphFilters`는 새 prop `colorBy: "layer" | "kind"`를 받는다(`SchemaView`는 `"layer"`, `GraphPanel`·`DataTab`은 `"kind"`): **층 필터**(`role=group` `aria-label="층 필터"`, `.gs-graph-filter-group.gs-graph-segmented`)는 버튼 3개의 작은 분할 컨트롤(버튼 이름·`aria-pressed`·숨김 토글 의미 불변, 테두리 한 겹의 묶음·버튼 사이 구분선, 눌림은 `--gs-accent-weak` 배경)이고 `colorBy="layer"`일 때만 각 버튼 앞에 층 색 점 `<span class="gs-graph-dot" style={ backgroundColor } aria-hidden="true" />`(`LAYER_COLORS`)을 둔다. **노드 종류 필터**(`aria-label="노드 종류 필터"`, `.gs-graph-filter-group.gs-graph-chips`)는 가벼운 칩(`Button variant="ghost" size="sm" className="gs-graph-chip"`, 테두리 없음, 눌림 해제는 `opacity` 낮춤)이고 각 칩 앞에 색 점(`aria-hidden`, 그 종류 노드의 실제 `data.color`; `useGraphFilters`가 필터 적용 전 `elements`에서 종류별 첫 노드 색을 `labelColors`로 돌려준다). **칩 텍스트에 노드 수 접미를 붙이지 않는다**(버튼 `textContent` 정확 일치 단언 유지). 두 그룹은 계속 같은 부모(`.gs-graph-filters`) 안에 있고 `.gs-graph-filter-group { display: flex; … }` 규칙을 유지한다. 필터 동작(층·종류 독립 필터, 원본 `elements` 불변)은 불변. `.gs-graph-filters`의 위·아래 여백은 `var(--gs-space-2)`로 줄인다(그래프가 화면 위쪽에서 시작).
7. **건수 문구(항목 7)**: `GraphCanvas`가 캔버스 위 오른쪽에 `<p class="gs-graph-count">{N}개 표시</p>`(N = `elements`의 노드 수, `font-size: var(--gs-text-sm)`, `color: var(--gs-text-muted)`, 오른쪽 정렬)를 그린다. `N개 중 M개`는 만들지 않는다. 잘림 안내 `일부만 표시합니다. 표시 상한을 넘는 노드는 보이지 않습니다.`(`DataTab`)는 그대로 유지.

**스키마 탭(항목 8·9)**
8. `lib/graph.ts`: `LAYER_COLORS = { 1: "#1D9E75", 2: "#378ADD", 3: "#7F77DD" }`와 새 `LAYER_BORDER_COLORS = { 1: "#0F6E56", 2: "#185FA5", 3: "#534AB7" }`. `schemaToElements`는 **층 색**(`LAYER_COLORS[layer]`, `borderColor: LAYER_BORDER_COLORS[layer]`)으로 노드를 칠한다(레이아웃 `breadthfirst` 유지, 간격 `spacingFactor: 1.25`).
9. 노드 종류 필터 18개 칩은 위 칩 스타일(`.gs-graph-chip`: 작은 글자 `--gs-text-xs`, 패딩 `--gs-space-1` `--gs-space-2`, 칩 사이 `gap: var(--gs-space-1)`)로 줄여 두 줄 이내로 정리한다(큰 알약 금지).

**데이터 탭(항목 10·11)**
10. `lib/graph.ts`: `LABEL_COLORS = { Brand: "#7F77DD", Product: "#1D9E75", Efficacy: "#EF9F27", Creative: "#378ADD", Other: "#888780" }`, 새 `LABEL_BORDER_COLORS = { Brand: "#534AB7", Product: "#0F6E56", Efficacy: "#854F0B", Creative: "#185FA5", Other: "#5F5E5A" }`, `GRAPH_LEGEND[1]`(`노드 종류`) 항목을 `브랜드`·`제품`·`효능`·`광고 소재`·`그 밖`(색 = 위 `LABEL_COLORS`)으로 확장(그룹 제목 `["층","노드 종류"]`·`GRAPH_LEGEND[0]`은 불변). `fragmentToElements`는 **종류 색**(`LABEL_COLORS[label] ?? LABEL_COLORS.Other`, `borderColor`는 `LABEL_BORDER_COLORS`의 같은 키)으로 칠하고, 각 노드의 연결 수 `degree`(그 노드가 `source` 또는 `target`인 간선 수)를 계산해 `data.degree`에 넣는다(입력 `fragment` JSON은 불변). `GraphElement` 노드 `data`에는 `borderColor?: string; degree?: number`를 **선택 필드**로 추가한다(테스트가 이 필드 없이 만든 요소 객체가 타입 검사를 통과해야 한다). 스타일: `{ selector: "node[degree]", style: { width: "mapData(degree, min, max, ${space * 6}, ${space * 14})", height: 같은 값 } }`(min·max는 `elements`의 `degree` 최솟값·최댓값을 코드에서 계산해 문자열에 넣고, min === max이면 이 규칙을 만들지 않는다; 스키마 요소는 `degree`가 없어 기본 크기).
11. 데이터 탭(`colorBy="kind"`)의 종류 칩 색 점은 위 종류 색, 층 필터는 색 점 없이 분할 컨트롤만. `GraphPanel`(근거 경로)도 `fragmentToElements`를 쓰므로 같은 종류 색과 `colorBy="kind"`를 쓴다.

**교체 단언(조언 세션 요청의 알려진 충돌 + 선점검 확인분. 행은 HEAD 기준, 어긋나면 테스트 이름으로 찾는다. 이 표 밖의 기존 단언은 수정하지 마라)**

| # | 파일·행 | 이전 | 이후 |
|---|---|---|---|
| G1 | `web/tests/graph-view.test.tsx` 30행(`loads fragment, creates cose canvas, shows missing and node details, and destroys on unmount` 안) | `expect(screen.getByLabelText("그래프 범례")).toBeTruthy();` | `expect(screen.queryByLabelText("그래프 범례")).toBeNull();` + 같은 자리에서 `expect(screen.getByRole("group", { name: "층 필터" })).toBeTruthy(); expect(screen.getByRole("group", { name: "노드 종류 필터" })).toBeTruthy();`(범례가 필터로 통합됐다는 같은 사실) |
| G2 | 같은 파일 약 133~140행 `it("renders separate layer and node kind legend groups")`(+ 상단 `GraphLegend` import) | `render(<GraphLegend />)`로 `그래프 범례` 안 제목 `["층","노드 종류"]`과 두 `ul`의 항목 텍스트(`["1층 · 제품 지식","2층 · 광고 관찰","3층 · 피드백"]`, `["제품","광고 소재"]`) | 이름을 `merges the legend colors into the layer and kind filters`로: 스키마 뷰(`SchemaView`, 스키마 픽스처에 `Creative`·`Product`·`Feedback` 라벨 포함)를 렌더해 `층 필터` 버튼 텍스트 `["1층 · 제품 지식","2층 · 광고 관찰","3층 · 피드백"]` 정확 일치, 각 층 버튼에 `span[aria-hidden="true"].gs-graph-dot`이 있고 그 `backgroundColor`가 `LAYER_COLORS` 값(hex→`rgb()` 변환 후 정확 일치)과 같다; 근거 경로 뷰(`GraphPanel`)에서는 층 버튼에 점이 없고 `노드 종류 필터` 칩 각각에 점이 있으며 색이 `fragmentToElements`가 만든 해당 종류 노드 색과 같다; 칩 `textContent`에 숫자 접미가 없다; `그래프 범례` 요소와 `h4` 제목이 없다 |
| G3 | 같은 파일 약 141~156행 `it("uses smaller labels and spreads cose nodes with built-in layout options")` | `node["font-size"]`가 9 이상 10 이하, `edge["font-size"]`가 `7`, 나머지(`text-margin-y`, cose 옵션 `nodeRepulsion > 2048`·`idealEdgeLength > 32`·`nodeOverlap > 4`)는 유지 | 이름을 `uses readable label sizes, outlines and edge pills and spreads cose nodes with built-in layout options`로: `node["font-size"]`가 `12`, `edge["font-size"]`가 `11`, 노드 `text-outline-width`가 0보다 크고 `text-outline-opacity`가 `1`, 간선 `text-background-opacity`가 `1`·`text-background-shape`가 `roundrectangle`·`text-background-padding`가 2~3px(`parseFloat`)·`arrow-scale`이 1 이상·`target-arrow-shape`가 `triangle`·`curve-style`이 `unbundled-bezier`, 간선 `width`가 `border * 1.5`(=1.5)보다 크고, 레이아웃 `fit === true`·`padding >= 40`, cose 옵션 단언은 **그대로 유지**(`name === "cose"` 포함), 스키마(breadthfirst) 레이아웃의 `fit === true`·`padding >= 40`·`spacingFactor > 1`(별도 `it`로 추가 가능) |
| G4 | `web/tests/graph.test.ts` 약 39행(`converts every fragment node…`의 마지막 줄)·47~50행(`maps nonempty schema labels…`)·76~79행(`groups the legend into layers and node kinds without losing any colors`) | 값 비교(`LABEL_COLORS[label] ?? LAYER_COLORS[layer]`, 조각 노드 색 ∈ `GRAPH_LEGEND` 색, `GRAPH_LEGEND[1]` 색 집합 = `Object.values(LABEL_COLORS)`) | **새 색 값(LABEL_COLORS 5종·LAYER_COLORS 새 값)으로 통과해야 하므로 수정하지 않는다**(확인용 행: `LAYER_COLORS[1]`·`[2]`가 `LABEL_COLORS.Product`·`Creative`와 같은 값이라 스키마 단언이 통과, `Hook`·`Angle`은 `LABEL_COLORS.Other`가 `GRAPH_LEGEND[1]`에 있어 통과). 이 중 실제로 깨지는 단언이 나오면 `blocked`로 멈추고 보고한다 |

위 표 밖에서 아래는 **수정하지 않는다(통과해야 한다)**: `graph-view.test.tsx`의 `tap node → onNodeClick`(`cy.on.mock.calls[0].slice(0, 2)`), `sets zoom bounds, clamps button changes, follows zoom events and fits the graph`(`화면에 맞춤` 후 `fit` 정확히 1회, 버튼 이름·아이콘, 캔버스 `style.height === ""`), 약 22행 cose 생성·약 60~100행 캔버스 교체·정리 테스트(요소 객체에 `borderColor`·`degree`가 없어도 타입 통과), `graph-page.test.tsx`의 `independently filters layers and kinds…`(그룹 이름·같은 부모·`textContent` 배열·`aria-pressed`·`3층 피드백은 이 작업 공간의 데이터입니다.`)·`uses independent responsive graph geometry and reduced motion`(CSS 정규식), `graph-data.test.tsx` 전체(36행 설명 문구·`reuses separate layer and kind filters…`·`shows the truncation note…`·136행 브랜드 표시), `tests/test_web_graph_names.py`와 `web/lib/graph.ts`의 한글 이름 사전(`NODE_LABEL_NAMES`·`RELATIONSHIP_NAMES`·`PROPERTY_NAMES`), `web/tests/cleanup.test.ts`.

**새 파일·값 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `LAYER_BORDER_COLORS`·`LABEL_BORDER_COLORS`·`LABEL_COLORS`(5종)·`GRAPH_LEGEND[1]` 확장·`degree`·`borderColor` | `web/lib/graph.ts` | `GraphCanvas.tsx`(스타일), `GraphFilters.tsx`(색 점), `graph.test.ts`·`graph-view.test.tsx`·`contrast.test.ts` |
| `colorBy`·`labelColors`·분할 컨트롤·칩 | `web/components/graph/GraphFilters.tsx`, `web/app/graph.css` | `SchemaView.tsx`·`GraphPanel.tsx`·`DataTab.tsx`, `graph-page.test.tsx`·`graph-data.test.tsx` |
| `mouseover`/`mouseout`·`.gs-dim`·`ResizeObserver`·`N개 표시` | `web/components/GraphCanvas.tsx` | 새 `graph-view.test.tsx` 단언 |

**문서 동기화(DEMO.md, 이 step의 수정 허용 경로)**: `DEMO.md`의 리허설 확인 ㉖만 **같은 형식**(`뜻 —`·`판정 —`(칸마다 `(n) 이름: … O … X`, 번호 연속, 판정 안 괄호 문자 `(`·`)` 금지)·`예시 —`(하나)·`기록 방법 —`(`칸 번호별 O/X와 한 줄 메모`)·`결과 기록: ______.`)으로 갱신한다. 기존 (1)~(6)은 그대로 두고 칸 `(7) 노드 색·크기: 스키마 탭은 층별 색이고 데이터 탭은 브랜드 보라·제품 초록·효능 주황·광고 소재 파랑·그 밖 회색이며 연결이 많은 노드가 더 크면 O, 색이 구분되지 않거나 크기가 모두 같으면 X`, `(8) 글자·선: 노드 이름이 외곽선으로 선 위에서도 읽히고 관계 이름이 작은 배경 알약 위에 읽히며 선이 진하고 화살표 방향이 분명하고 약한 곡선이면 O, 글자가 선에 묻히거나 화살표가 안 보이면 X`, `(9) 마우스 올림 강조: 노드에 포인터를 올리면 그 노드와 이웃·연결선만 선명하고 나머지가 흐려지며 벗어나면 복원되면 O, 흐려진 채 남거나 반응이 없으면 X`, `(10) 필터와 범례 통합: 별도 범례 없이 층 필터가 분할 컨트롤이고 노드 종류 필터가 색 점 달린 가벼운 칩으로 두 줄 이내이며 눌러 숨기고 보이는 동작이 그대로면 O, 범례가 따로 남거나 칩이 큰 알약이거나 동작이 바뀌면 X`, `(11) 맞춤·버튼·건수: 처음 그릴 때 모든 노드가 가장자리 라벨까지 잘리지 않고 보이며 확대·축소·화면 맞춤 버튼이 캔버스 오른쪽 아래에 노드를 가리지 않고 캔버스 위 오른쪽에 N개 표시가 보이면 O, 노드가 잘리거나 버튼이 노드를 가리거나 건수가 없으면 X`를 이어서 추가한다(칸 번호 연속). `예시 —` 문장은 데이터 탭에서 제품에 포인터를 올려 연결된 브랜드·효능만 선명해지면 (9) 칸 O로 바꾼다. 번호·개수(`⑰~㉗` 11개)·`tests/test_demo_docs.py`는 바꾸지 않는다. `README.md`·`docs/PHASES.md`·`docs/portfolio/DETAIL_PAGE.md`는 그래프 모양 관련 문구가 `rg`로 확인될 때만 맞추고 `docs/PHASES.md`의 `| 58 |` 행·`DETAIL_PAGE.md`의 수치 표 행·`docs/TROUBLESHOOTING_LOG.md`는 수정하지 않는다.

**시각 확인 필요(사용자 화면, 완료 보고에 항목별로 적는다)**: 노드 색 구분(스키마 층별·데이터 종류별), 글자 가독성(노드 외곽선·관계 이름 알약), 곡선 교차(약한 곡률로 선이 덜 겹치는지), 허브 노드 크기 차이, 마우스 올림 강조와 복원, 화면 가장자리에서 노드·라벨이 잘리지 않는지(48px 여백), 오른쪽 아래 버튼 그룹이 노드를 가리지 않는지, 필터 칩 두 줄 이내와 층 분할 컨트롤, 캔버스 위 N개 표시, 탭 전환 직후 크기(`resize`).

**공통 시각 기준(7c 시각 확인 반영, 이후 모든 새 화면이 따른다)**: 간격은 `tokens.css`의 `--gs-space-*`(4px 배수, 기본 리듬은 8px 단위)만 쓰고 색·반경·그림자·글자 크기도 `tokens.css` 변수만 쓴다. 화면에 보이는 문자열은 **한글**이다(영문 내부 코드·브랜드 슬러그·도구 이름·`value`·`n_top` 같은 필드명을 그대로 노출하지 않는다. `taxonomyNames`의 한글 이름, `web/lib/workspace.ts`의 `workspaceLabel`, 그리고 step 13의 한글 표시 매핑을 재사용하고 없는 이름은 새로 지어내지 말고 원문 대신 `기타`·`정보 없음` 같은 한글 대체를 쓴다). 펼침·접힘은 `grid-template-rows: 0fr → 1fr` 방식의 부드러운 아코디언(화살표 회전)이고, 모든 애니메이션·전환은 `@media (prefers-reduced-motion: reduce)`에서 즉시 동작·정지한다. 색에만 의존하지 않고 아이콘·글자를 함께 쓴다. 접힌 영역의 내용은 DOM에 유지하고 접힌 최종 상태는 기존처럼 `hidden` 속성이다(펼칠 때 `hidden`을 동기적으로 제거한 뒤 다음 프레임에 열림 클래스를 붙이고, 접을 때는 전환 뒤 `hidden`을 설정하되 reduced-motion·전환 시간 0이면 즉시 설정한다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/components/{GraphCanvas,SchemaView,GraphPanel,NodeDetail}.tsx`, `/web/components/graph/{GraphFilters,DataTab,GraphPage,tabs.tsx}`, `/web/lib/graph.ts`, `/web/app/{graph.css,globals.css,tokens.css}`, `/DEMO.md`(리허설 확인 ㉖)
- `/web/tests/{graph-view,graph-page,graph-data,graph,cleanup,contrast}.test.ts*`, `/tests/test_web_graph_names.py`(읽기 전용), `/tests/test_demo_docs.py`(읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/components/{GraphCanvas,SchemaView,GraphPanel}.tsx`, `web/components/graph/{GraphFilters,DataTab}.tsx`, `web/lib/graph.ts`(색·`degree`·`borderColor`·`GRAPH_LEGEND`·`schemaToElements`·`fragmentToElements`만), `web/app/{graph.css,globals.css}`(`.graph-legend` 삭제 포함), `DEMO.md`(㉖만), `README.md`·`docs/PHASES.md`·`docs/portfolio/DETAIL_PAGE.md`(문구가 틀려지는 곳만), `web/tests/{graph,graph-view,graph-page,graph-data,contrast}.test.ts*`

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/components/{GraphCanvas,SchemaView,GraphPanel}.tsx`, `web/components/graph/{GraphFilters,DataTab}.tsx`, `web/lib/graph.ts`(색·`degree`·`borderColor`·`GRAPH_LEGEND`·`schemaToElements`·`fragmentToElements`만), `web/app/{graph.css,globals.css}`(`.graph-legend` 삭제 포함), `DEMO.md`(㉖만), `README.md`·`docs/PHASES.md`·`docs/portfolio/DETAIL_PAGE.md`(문구가 틀려지는 곳만), `web/tests/{graph,graph-view,graph-page,graph-data,contrast}.test.ts*`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `lib/graph.ts`(색 상수·`degree`·`borderColor`·`GRAPH_LEGEND` 확장·`schemaToElements` 층 색·`fragmentToElements` 종류 색, 입력 불변). **2.** `GraphFilters.tsx`(`colorBy`·`labelColors`·분할 컨트롤·칩)와 `SchemaView`·`GraphPanel`·`DataTab`(`GraphLegend` 제거, `colorBy` 전달). **3.** `GraphCanvas.tsx`(스타일·레이아웃 `fit`/`padding`·호버·`ResizeObserver`·`N개 표시`, `GraphLegend` 삭제). **4.** `graph.css`·`globals.css`(`.graph-legend` 삭제). **5.** 교체 단언 표 적용, 새 테스트 작성, `DEMO.md` ㉖ 갱신. 모든 간격·색·반경·글자 크기는 `tokens.css` 변수만 쓴다(노드·종류·층 색은 `lib/graph.ts` 상수, 승인된 목업 값). 마케터 화면에 영문 코드·내부 도구명·스키마 키를 표시하지 않는다.

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `web/tests/graph.test.ts`(기존 `it` 변경 없음, 새 `it` 추가): (1) `LAYER_COLORS`가 `{1:"#1D9E75",2:"#378ADD",3:"#7F77DD"}`, `LAYER_BORDER_COLORS`가 `{1:"#0F6E56",2:"#185FA5",3:"#534AB7"}`, `LABEL_COLORS`가 `{Brand:"#7F77DD",Product:"#1D9E75",Efficacy:"#EF9F27",Creative:"#378ADD",Other:"#888780"}`, `LABEL_BORDER_COLORS`가 `{Brand:"#534AB7",Product:"#0F6E56",Efficacy:"#854F0B",Creative:"#185FA5",Other:"#5F5E5A"}` 정확 일치, (2) `schemaToElements`는 모든 노드를 **층 색**과 층 테두리 색으로 칠한다(스키마에 `Brand`(layer 1)를 넣으면 보라가 아니라 `LAYER_COLORS[1]`), (3) `fragmentToElements`는 `Brand`·`Product`·`Efficacy`·`Creative`를 종류 색과 종류 테두리 색으로, 그 밖의 종류(`Hook` 등)는 `Other` 색과 테두리로 칠하고 `degree`가 간선 끝점 수와 같다(허브 노드 3, 고립 노드 0, 같은 노드가 source·target인 간선 수 합), (4) 입력 `fragment`·`schema` JSON 스냅샷이 변하지 않는다, (5) `GRAPH_LEGEND[1]` 항목 이름이 `["브랜드","제품","효능","광고 소재","그 밖"]`이고 색이 위 `LABEL_COLORS` 값과 일치한다.
- `web/tests/graph-view.test.tsx`: 교체 G1·G2·G3만(기존 `tap`/줌/`fit`/교체·정리 단언 불변). 새 `it` 추가: (6) 첫 `cy.on`이 `("tap","node")`이고 그 뒤에 `"mouseover"`·`"mouseout"`(`"node"`)이 등록된다(`cy.on.mock.calls.map(call => call[0])`), (7) `mouseover` 핸들러를 가짜 `event.target.closedNeighborhood()`와 가짜 `cy.elements().not(...).addClass`로 호출하면 이웃에 포함되지 않은 요소에만 `gs-dim`이 붙고 `mouseout` 핸들러는 `removeClass("gs-dim")`, 스타일 배열에 `.gs-dim` 규칙의 `opacity`가 `0.3`, (8) 초기 설정에서 `fit`·`resize`를 호출하지 않는다(`{ on, destroy, zoom, fit }` 가짜에서 `화면에 맞춤`을 누르기 전 `fit` 0회), (9) `ResizeObserver`가 있으면(전역 스텁) 크기 변화 콜백이 `cy.resize`만 부르고(`fit` 0회) 정리 시 `disconnect`가 호출되며, 없으면 오류 없이 건너뛴다, (10) `degree` 있는 요소는 `node[degree]` 규칙(`mapData(degree, min, max, …)`의 min·max가 요소의 최솟값·최댓값)을 갖고 모든 `degree`가 같거나 없으면 그 규칙이 없다, (11) `GraphCanvas`가 `N개 표시`(노드 요소 수만, 간선 제외)를 보인다(`elements=[]`이면 `0개 표시`).
- `web/tests/graph-page.test.tsx`·`graph-data.test.tsx`(기존 단언 변경 없음, 새 `it` 추가): (12) `graph.css`에서 `.gs-graph-controls`가 `bottom`과 `right`를 쓰고 `top`을 쓰지 않는다, `.gs-graph-segmented`·`.gs-graph-chip`·`.gs-graph-dot`·`.gs-graph-count` 규칙이 있고 `var(--gs-…)` 토큰만 쓴다(`#` 색 하드코딩 없음), `.graph-legend`·`그래프 범례` 규칙이 없고 `globals.css`에도 `.graph-legend`가 없다, (13) 스키마 뷰 층 버튼에는 색 점이 있고 종류 칩 점 색이 층 색과 같다, 데이터 탭에서는 층 버튼에 점이 없고 칩 점이 종류 색(브랜드 보라·제품 초록·효능 주황)이다.
- `web/tests/contrast.test.ts`(기존 `it` 불변, 새 `it` 추가): (14) `lib/graph.ts`의 모든 노드 테두리 색(`LAYER_BORDER_COLORS`·`LABEL_BORDER_COLORS`)이 `--gs-bg` 위에서 비텍스트 대비 3 이상이고, 같은 `colors` 객체의 채우기 색들이 서로 다르다(층 색 3종끼리, 종류 색 5종끼리 중복 없음).
- 해시 시드·집합·객체 순회 순서에 기대는 새 단언을 만들지 마라(리스트·명시적 순서로 단언). 합성 데이터만 쓴다.
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
- 위 "교체 단언" 표(G1~G4)에 없는 기존 단언을 수정·삭제·약화하지 마라. 표의 대상이 통과하면 수정하지 마라(G4는 수정 금지 확인행). 충돌이 나면 구현하지 말고 `blocked`로 멈춰 최소 교체안을 `reason`에 적어라. 이유: 승인된 교체만 허용된다.
- 새 패키지를 설치하지 마라. NVL 등 Neo4j 시각화 라이브러리·Cytoscape 확장(`cytoscape-*`)을 쓰지 마라(Cytoscape 3.35.0 내장 스타일·레이아웃만). 서버(`src/`)·`web/lib/{api,types,taxonomy}.ts`·`tests/test_web_graph_names.py`·`web/lib/graph.ts`의 한글 이름 사전(`NODE_LABEL_NAMES`·`RELATIONSHIP_NAMES`·`PROPERTY_NAMES`)을 수정하지 마라. 이유: 라이선스와 범위.
- `ZOOM_LIMITS`(0.3~2.5), 노드 클릭 확장(`이웃 펼치기`·`getGraphNeighbors`), `DataTab.displayNode`의 브랜드 표시(`brandDisplayName`), `NodeDetail`의 동작을 바꾸지 마라. 초기 설정에서 `cy.fit()`·무조건 `cy.resize()`를 호출하지 마라(`resize`는 `ResizeObserver` 콜백 안에서 `?.`로만, `fit`은 `화면에 맞춤` 클릭에서만). 첫 `cy.on`을 `tap`이 아닌 것으로 바꾸지 마라. 이유: 기존 단언이 cytoscape 가짜 객체와 호출 순서·횟수를 고정한다.
- 필터 칩 텍스트에 노드 수 같은 접미를 붙이지 마라. `층 필터`·`노드 종류 필터`의 그룹 이름·`aria-pressed`·같은 부모·`.gs-graph-filter-group { display: flex }` 규칙을 바꾸지 마라. 원본 `elements`·`fragment`·`schema` 객체를 변형하지 마라(복사본에만 색·`degree`). `GraphElement`의 새 필드는 선택 필드로 둔다. 이유: 기존 단언과 타입 검사.
- `.graph-legend` 삭제 뒤 `web/app/globals.css`에 소비자 없는 클래스 규칙을 남기지 마라(`cleanup.test.ts`). 색 하드코딩은 `lib/graph.ts`의 승인된 목업 값 상수에만 둔다(CSS·컴포넌트에 `#` 색 직접 쓰기 금지, 토큰 사용). 이유: 시각 기준.
- `docs/PHASES.md`의 `| 58 |` 행, `docs/portfolio/DETAIL_PAGE.md`의 수치 표 행, `docs/TROUBLESHOOTING_LOG.md`, `DEMO.md`의 ⑰~㉗ 번호·개수·형식 규칙(`뜻 —`·`판정 —`·`예시 —`·`기록 방법 —`, 칸 번호 연속, 판정 안 괄호 문자 금지, `결과 기록: ______.`)을 깨지 마라. 사용자 live 결과를 지어내지 마라. 이유: 문서 가드 테스트.
- 6b-clarify 동작·`web/lib/reducer.ts`·`web/components/{plan,shell,results,history,evidence}/*`를 수정하지 마라. `web/app`·`web/components`·`web/lib` 소스에 `examples`·`.examples`·`예시 요청` 문자열을 쓰지 마라. 이유: 범위 분리와 `tests/test_demo_docs.py`의 예시 칩 금지 가드.
