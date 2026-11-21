# Step 6: graph-data

## 설계 검토 기록

**목적(독립·삭제 가능 step)**: 지식 그래프 **데이터 탭**과 서버의 읽기 전용 탐색 엔드포인트 2개를 만든다. 이 step을 건너뛰어도 step 5까지의 화면은 그대로 동작해야 한다(탭이 목록에 나타나지 않을 뿐). 서버 변경은 `GET /graph/overview`·`GET /graph/neighbors`뿐이다(새 패키지·live 호출 없음). **기존 단언은 하나도 교체하지 않는다**(충돌 점검 결과 없음: 새 탭은 `tabs.tsx` 배열 한 줄이고 step 5의 탭 단언은 `GRAPH_TABS`와 비교한다). 충돌이 나면 구현하지 말고 `blocked`로 멈춰 최소 교체안을 `reason`에 적어라.

**코드를 열어 확인한 사실**
- `src/beautyads/api/graph_routes.py`의 `register_graph`가 `/graph/fragment`·`/graph/schema`·`/workspaces`를 등록하고 앞 둘은 `resolve_tenant(X-Tenant-Id, allowed_tenants)`를 먼저 호출한다. `/graph/fragment`는 `services.graph_fragment is None`이면 `503 GRAPH_UNAVAILABLE`, 질의 예외는 본문 없이 `500 GRAPH_QUERY_FAILED`(`# noqa: BLE001` 주석 포함 형식)이다.
- `src/beautyads/api/app.py`의 `Assembly` 데이터클래스에 `graph_fragment: Callable | None = None` 필드(`product_names` 앞)가 있고 `src/beautyads/api/assembly.py`가 `def graph_fragment(ids)`(`fragment_parameters` → `graph_connection.run(fragment_query(), params).records` → `build_fragment`)를 정의해 `Assembly(... graph_fragment=graph_fragment, ...)`로 주입한다. `tests/test_api_assembly.py`(1498행 부근)는 시작 시 `fragment_query()` 질의가 **실행되지 않음**을 단언하므로 새 함수도 요청 때만 질의해야 한다.
- 그래프 질의 변환은 `src/beautyads/graph/fragment_queries.py`의 고정 Cypher + 파라미터(`fragment_parameters`, `build_fragment`)이고 노드는 `{id, label, name, props}`, 엣지는 `{source, target, type}`다. 노드 id 규칙(`build_fragment`): Creative `creative:{source}:{source_id}`, 값 노드 `{Label}:{value}`(Hook·Angle·Format·Talent·CtaType·Efficacy), Product `Product:{brand}:{source_url}`, Brand `Brand:{name}`. `props`의 허용 키는 같은 파일의 `_PROPERTIES`다. `neo4j` import는 `graph` 계층에서만 허용된다(`tests/test_architecture.py`).
- 확정 사항: 제품 노드는 모든 브랜드 공용 카탈로그, **피드백만 작업 공간 범위**.
- 웹(step 5 결과): `web/components/graph/tabs.tsx`의 `GRAPH_TABS`(`{id, label, render(context)}` 배열; `GraphTabContext = { tenantId: string; pathIds: string[] | null }`), `GraphPage.tsx`는 이 배열을 순회하고 활성 탭만 마운트한다. `GraphFilters`(층·노드 종류 토글), `GraphLegend`, `NodeDetail`(한글 표시, `names` 선택 prop), `fragmentToElements`·`NODE_LABEL_NAMES`·`RELATIONSHIP_NAMES`·`ZOOM_LIMITS`가 있다. `web/lib/api.ts`의 `getGraphFragment`가 `X-Tenant-Id` 헤더·오류 `ApiError(status, code)` 처리의 기준 형식이다.

**설계 결정**
- 새 `src/beautyads/graph/explore_queries.py`: **고정 Cypher 문자열 상수**와 파라미터 검증·응답 변환. `overview`: 공용 카탈로그(`Brand`·`Product`·`Efficacy` 노드와 그 사이 관계 `OWNS`·`HAS_EFFICACY` 등 서버 온톨로지에 있는 관계)에서 상한 60개 노드. `neighbors(id)`: 노드 한 개의 이웃을 상한 50개로. id의 접두 라벨이 허용 목록(`Brand`·`Product`·`Creative`·`Hook`·`Angle`·`Format`·`Talent`·`CtaType`·`Efficacy`)에 있을 때만 **그 라벨 전용 고정 Cypher 상수**를 쓴다(라벨이나 id를 문자열로 이어 붙여 Cypher를 만들지 마라; id의 각 구성요소는 파라미터). Cypher 안에 이름을 적는 관계 유형은 `ONTOLOGY_RELATIONSHIPS`에 있는 유형만 쓴다(`tests/test_graph_fragment.py`가 `src/beautyads/graph/*.py`의 `[:TYPE` 패턴을 모두 찾아 온톨로지 목록의 부분집합임을 단언한다; 관계 유형을 쓰지 않는 `-[r]-` 패턴은 허용). **어느 질의도 `Feedback` 라벨 노드를 반환하지 않는다**(질의 단계에서 제외하고 응답 변환 단계에서도 거른다: 이중 방어). 노드 id·필드 표현은 `build_fragment`의 `{id, label, name, props}` 규칙을 **그대로** 따른다(Codex가 `build_fragment`를 열어 확인하고 다르면 `blocked`).
- 응답 형식: `{nodes, edges, truncated: bool}`(`missing` 없음). 웹은 `fragmentToElements({ ...response, missing: [] }, names)`로 재사용한다.
- 라우트(`graph_routes.py`): `GET /graph/overview`, `GET /graph/neighbors?id=`. 둘 다 `resolve_tenant`를 먼저 호출하고(검사 실패 시 거부), `id`는 검증(길이 상한 300, 제어 문자 없음, 허용 라벨 접두, 아니면 `422 GRAPH_ID_INVALID`), 그래프가 없으면 `503 GRAPH_UNAVAILABLE`, 질의 오류는 본문 없이 `500 GRAPH_QUERY_FAILED`(기존 `/graph/fragment`와 같은 처리). `app.py`의 `Assembly`에 필드 `graph_overview: Callable | None = None`·`graph_neighbors: Callable | None = None`을 **추가만** 하고 `assembly.py`는 기존 `graph_fragment`와 같은 방식으로 두 함수를 **주입만** 추가한다(시작 시 질의 없음).
- 웹: `web/lib/api.ts`에 `getGraphOverview(tenantId)`·`getGraphNeighbors(tenantId, id)`(기존 `getGraphFragment` 형식, `X-Tenant-Id` 헤더, `id`는 `encodeURIComponent`, 오류는 `ApiError(status, code)`)와 응답 타입 `GraphExploreResponse`(`Pick<GraphFragment, "nodes" | "edges"> & { truncated: boolean }`, `web/lib/types.ts`의 기존 `GraphFragment`를 import해 `api.ts`에서 내보낸다; `types.ts`는 수정하지 않는다. `GraphEdge`라는 별도 타입은 없다). `web/components/graph/DataTab.tsx`: 탭 위 문장 `공용 카탈로그(브랜드·제품·효능)를 먼저 보여 주고, 노드를 선택해 연결된 이웃을 펼칩니다.`(`<p class="gs-graph-note">`), 범례·`GraphFilters`·캔버스·`NodeDetail`을 step 5와 같은 레이아웃(`graph.css`의 같은 클래스)으로 그린다. 노드를 선택하면 `NodeDetail` 아래에 `이웃 펼치기` 버튼이 나타나고(이미 펼친 노드는 비활성) 누르면 `getGraphNeighbors`를 그 id로 호출해 결과를 **id로 중복 제거해 병합**한다. `truncated`이면 `일부만 표시합니다. 표시 상한을 넘는 노드는 보이지 않습니다.` 문구. 로딩 `role="status"`, 오류 `role="alert"`(상태·코드 표시)와 `다시 시도`, 빈 응답은 `표시할 노드가 없습니다`. 한글 이름 표시는 `fragmentToElements`·`NodeDetail`을 재사용한다(영문 라벨·관계·속성 키 노출 없음). `tabs.tsx`의 `GRAPH_TABS`에 `{ id: "data", label: "데이터", render: ... }`를 **`schema` 다음, `path` 앞**에 한 줄 추가한다(`GraphPage.tsx`는 수정하지 않는다).
- 새 시각 기준: 간격·색은 토큰, 처음 보는 용어에 뜻(탭 위 문장), 필터는 기준마다 줄을 나눈 step 5의 `GraphFilters` 재사용, 폭은 사이드바 폭 토큰을 참조하지 않는 `graph.css` 클래스만 사용, 모션은 `prefers-reduced-motion`에서 정지.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| 탐색 Cypher·변환 | `src/beautyads/graph/explore_queries.py` | `api/assembly.py`(주입), `tests/test_graph_explore.py` |
| `Assembly.graph_overview`·`graph_neighbors` | `src/beautyads/api/app.py` | `graph_routes.py`, `assembly.py` |
| 라우트 2개 | `src/beautyads/api/graph_routes.py` | `web/lib/api.ts` |
| `data` 탭 한 줄 | `web/components/graph/tabs.tsx` | `GraphPage.tsx` |

**공통 시각 기준(7c 시각 확인 반영, 이후 모든 새 화면이 따른다)**: 간격은 `tokens.css`의 `--gs-space-*`(4px 배수, 기본 리듬은 8px 단위)만 쓰고 색·반경·그림자·글자 크기도 `tokens.css` 변수만 쓴다. 화면에 보이는 문자열은 **한글**이다(영문 내부 코드·브랜드 슬러그·도구 이름·`value`·`n_top` 같은 필드명을 그대로 노출하지 않는다. `taxonomyNames`의 한글 이름, `web/lib/workspace.ts`의 `workspaceLabel`, 그리고 step 13의 한글 표시 매핑을 재사용하고 없는 이름은 새로 지어내지 말고 원문 대신 `기타`·`정보 없음` 같은 한글 대체를 쓴다). 펼침·접힘은 `grid-template-rows: 0fr → 1fr` 방식의 부드러운 아코디언(화살표 회전)이고, 모든 애니메이션·전환은 `@media (prefers-reduced-motion: reduce)`에서 즉시 동작·정지한다. 색에만 의존하지 않고 아이콘·글자를 함께 쓴다. 접힌 영역의 내용은 DOM에 유지하고 접힌 최종 상태는 기존처럼 `hidden` 속성이다(펼칠 때 `hidden`을 동기적으로 제거한 뒤 다음 프레임에 열림 클래스를 붙이고, 접을 때는 전환 뒤 `hidden`을 설정하되 reduced-motion·전환 시간 0이면 즉시 설정한다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/src/beautyads/api/{graph_routes,assembly,app,session}.py`(graph_fragment 정의·주입부, `Assembly` 필드), `/src/beautyads/graph/{fragment_queries,ontology_view,connection}.py`, `/tests/test_architecture.py`, `/tests/test_graph_fragment.py`(`graph/*.py` 관계 유형 단언), `/tests/test_caps_guard.py`(`src/` 전체 `.py`를 훑는다: 새 파일이 계층 규칙과 캡 가드를 통과해야 한다), `/tests/test_api_graph.py`·`/tests/test_api_assembly.py`(기존 `/graph/fragment` 라우트·주입 테스트), `/docs/TAXONOMY.md`
- `/web/components/graph/*`, `/web/components/{GraphCanvas,NodeDetail}.tsx`, `/web/lib/{api,graph,types}.ts`, `/web/app/graph.css`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/graph/explore_queries.py`, `src/beautyads/api/graph_routes.py`, `src/beautyads/api/app.py`(`Assembly` 필드 추가만), `src/beautyads/api/assembly.py`(주입만), `tests/test_graph_explore.py`, `tests/test_api_graph_explore.py`, `web/lib/api.ts`, `web/components/graph/{DataTab.tsx,tabs.tsx}`, `web/tests/graph-data.test.tsx`

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `src/beautyads/graph/explore_queries.py`, `src/beautyads/api/graph_routes.py`, `src/beautyads/api/app.py`(`Assembly` 필드 추가만), `src/beautyads/api/assembly.py`(주입만), `tests/test_graph_explore.py`, `tests/test_api_graph_explore.py`, `web/lib/api.ts`, `web/components/graph/{DataTab.tsx,tabs.tsx}`, `web/tests/graph-data.test.tsx`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `graph/explore_queries.py`(고정 Cypher 상수, 파라미터 검증, 응답 변환). **2.** `app.py`에 필드 추가, `graph_routes.py`에 라우트 2개, `assembly.py`에 주입. **3.** 웹 API 함수·`DataTab`·`tabs.tsx` 한 줄. **4.** 테스트(아래).

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `tests/test_graph_explore.py`(가짜 neo4j 세션·행 픽스처만, 실제 연결 금지): (1) `overview` 변환은 노드 상한 60을 넘기지 않고 `truncated`를 표시, (2) **`Feedback` 라벨 행이 입력에 섞여 있어도 응답 노드·엣지에 없다**(질의 문자열 상수에 `Feedback` 제외 조건이 있는지도 단언), (3) `neighbors`는 id 형식이 틀리거나 허용 라벨이 아니거나 300자를 넘거나 제어 문자가 있으면 `ValueError`, (4) 상한 50, (5) 노드 필드가 `{id,label,name,props}`이고 id·값 형식이 `build_fragment`와 같다(같은 입력 행에서 같은 id), (6) 라벨별 질의 상수가 허용 라벨마다 하나씩 있고 id 문자열이 질의 문자열에 들어 있지 않다(파라미터로만 전달). (6b) **관계 유형 가드**: `explore_queries.py`의 모든 Cypher 상수에서 `[:TYPE` 패턴으로 찾은 관계 유형이 `ONTOLOGY_RELATIONSHIPS`의 유형 집합의 부분집합이고 비어 있지 않다(테스트가 직접 정규식으로 찾는다).
- `tests/test_api_graph_explore.py`(`TestClient`, 가짜 assembly): (7) 허용되지 않은 `X-Tenant-Id`는 거부(기존 `resolve_tenant` 동작과 같은 상태 코드), (8) 주입이 없으면 `503 GRAPH_UNAVAILABLE`, (9) id 형식 오류 `422 GRAPH_ID_INVALID`, (10) 내부 오류 시 `500 GRAPH_QUERY_FAILED`이고 본문에 예외 문자열이 없다, (11) 기존 `/graph/fragment`·`/graph/schema`·`/workspaces` 응답과 `tests/test_api_graph.py`·`tests/test_api_assembly.py`의 기존 단언은 수정 없이 통과.
- `web/tests/graph-data.test.tsx`(새): (12) 데이터 탭은 `GRAPH_TABS`에 있을 때만 표시되고 탭 순서가 `스키마`·`데이터`·`근거 경로`다, (13) 노드 선택 후 `이웃 펼치기`가 `getGraphNeighbors`를 그 id로 호출하고 결과를 중복 없이 병합(캔버스 `elements` 개수로 단언), (14) `truncated`이면 안내 문구, (15) 오류 시 상태·코드와 `다시 시도`, (16) 영문 라벨·관계 유형이 화면에 없다(`Product`·`OWNS` 등), (17) 필터 그룹 두 개가 step 5와 같은 이름으로 있다, (18) `web/lib/api.ts`: 두 함수가 `X-Tenant-Id`를 보내고 `id`를 인코딩하며 오류를 `ApiError(code)`로 전달.
- 해시 시드·집합·딕셔너리 순회 순서에 기대는 새 단언을 만들지 마라(리스트와 명시적 순서로 단언).
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
- 기존 단언을 수정·삭제·약화하지 마라(이 step은 교체 단언이 없다). 충돌이 나면 구현하지 말고 `blocked`로 멈춰 최소 교체안을 `reason`에 적어라. 이유: 승인된 교체가 없다.
- `graph/fragment_queries.py`·`graph/ontology_view.py`·적재 코드·`store/`·`web/lib/types.ts`·`web/components/graph/GraphPage.tsx`를 수정하지 마라. 이유: 기존 읽기·적재 경로와 화면 틀은 불변이고 이 step은 새 읽기 전용 질의와 탭 한 줄만 더한다.
- 응답에 `Feedback` 노드나 작업 공간 범위 데이터를 포함하지 마라(질의와 변환 양쪽에서 제외). 이유: 제품 노드만 공용 카탈로그이고 피드백만 작업 공간 범위다(확정 사항, ADR-009).
- Cypher를 요청 입력으로 받거나 라벨·id를 이어 붙여 조립하지 마라(라벨별 고정 상수 + 검증된 파라미터). 이유: 에이전트·사용자에게 Cypher를 쓰게 하지 않는다.
- `make db-up`·`make serve`·`make demo-up`을 실행하거나 Neo4j에 연결하지 마라(실제 질의 검증은 사용자가 로컬에서 한다).
- 엔드포인트를 `GET /graph/overview`·`GET /graph/neighbors` 외에 추가하지 마라. `app.py`는 `Assembly` 필드 추가만 하고 이 밖의 `src/` 변경이 필요하면 구현하지 말고 `blocked`로 멈춰 `reason`에 적어라. 이유: 승인된 서버 변경 범위.
- `web/app`·`web/components`·`web/lib` 소스에 `examples`·`.examples`·`예시 요청` 문자열을 쓰지 마라. 이유: `tests/test_demo_docs.py`의 예시 칩 금지 가드.
