# Step 7: web-graph

## 설계 검토 기록

**배경(PRD 온톨로지 그래프 화면)**: 응답에 쓰인 노드와 관계를 그래프로 그리고, 전체 스키마(1층 제품 지식 · 2층 광고 관찰 · 3층 피드백)를 보여 준다. 서버 경로는 step 2가 만들었다(`GET /graph/fragment`, `GET /graph/schema`). 이 step은 `cytoscape`로 그리는 화면과 step 6의 "근거 그래프 보기" 버튼 연결, 빌드 확인이다.

**서버 계약(step 2가 만든 것, 코드를 열어 확인하고 맞춘다)**:
- `GET /api/graph/fragment?ids=<쉼표로 이은 소재 ID>`(1~30개, 헤더 `X-Tenant-Id`) → `{nodes: [{id, label, name, props}], edges: [{source, target, type}], missing: [소재 ID]}`. 노드 `id`는 소재가 `creative:<소재 ID>`, 그 밖에는 `<레이블>:<값>`. 오류: 422 `GRAPH_IDS_INVALID`, 503 `GRAPH_UNAVAILABLE`, 500 `GRAPH_QUERY_FAILED`(본문 `{"detail": 코드}`).
- `GET /api/graph/schema` → `{labels: [{label, layer, name_ko}], relationships: [{type, from, to, layer}], taxonomy, claims}`(`layer`는 1·2·3).
- `show_graph_fragment.data = {evidence_ids: [...]}`(`api/ask_view.py` 260행). 분석된 소재만 분류 축 관계가 있으므로(그래프 소재 7,429개 중 라벨 있는 것 1,172개, 2026-11-20 읽기 전용 확인) **라벨 없는 소재 노드는 이웃 없이 나오는 것이 정상**이다. 소재가 그래프에 아직 없으면 `missing`에 온다.

**설계 결정**:
- 화면은 두 곳: ① 기획안·근거 결과 아래 "근거 그래프 보기" 버튼(`show_graph_fragment`가 있을 때만)이 여는 **그래프 패널**, ② 화면 상단 탭 "전체 스키마"(`/graph/schema`). 둘 다 같은 `GraphCanvas` 컴포넌트와 범례를 쓴다.
- `cytoscape`는 `window`가 필요하므로 **클라이언트에서만 동적 import**(`useEffect` 안, `"use client"`)하고, 언마운트 때 `cy.destroy()`를 부른다. 배치는 내장 `cose`(조각)와 `breadthfirst` 또는 `cose`(스키마) 중 보기 좋은 쪽을 고르되 **외부 레이아웃 확장 패키지를 추가하지 않는다**.
- 순수 함수 `fragmentToElements(fragment, names)`·`schemaToElements(schema)`가 `cytoscape` 요소 목록을 만들고(테스트 대상), 컴포넌트는 그것을 넘기기만 한다. 노드 색은 층(layer)과 레이블 종류로 구분하고 범례에 같은 색을 쓴다. 노드 라벨은 분류 값이면 `taxonomy`·`claims`의 한국어 이름, 아니면 서버 `name`.
- 노드를 누르면 오른쪽(좁은 화면은 아래)에 상세 패널: 레이블, 이름, 서버가 준 `props`만(허용 속성은 서버가 이미 제한). `url`은 step 6의 안전한 링크 규칙(`http(s)`만, `rel="noopener noreferrer"`)을 **같은 함수로** 쓴다(복제하지 않는다).
- 상태: 불러오는 중 / 비어 있음("표시할 노드가 없습니다") / 오류(오류 코드와 "다시 시도") / `missing` 안내("그래프에 아직 없는 소재 N건").
- 시연 화면 원칙: 그래프 화면은 "응답에 쓴 근거가 실제 그래프 노드와 관계로 연결돼 있다"를 보여 주는 용도다. 그래프가 벡터 검색보다 낫다는 식의 비교 문구를 화면에 넣지 않는다(사용자 원칙, E3 결과는 `docs/results/2026-11-20-p6-final.md`의 판정 그대로가 아니면 쓰지 않는다).

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `getGraphFragment(tenantId, ids)` | `web/lib/api.ts`(**추가만**) | `GraphPanel.tsx` |
| `fragmentToElements`·`schemaToElements` | `web/lib/graph.ts` | `GraphCanvas.tsx`, 테스트 |
| `GraphCanvas`·`GraphPanel`·`SchemaView`·`NodeDetail` | `web/components/` | `CommandSlot.tsx`(버튼·패널), `app/page.tsx`(탭) |
| 안전 링크 함수 | step 6이 만든 함수를 재사용(위치는 코드에서 확인) | `NodeDetail.tsx` |

**기존 단언과의 충돌 점검**: step 6의 `CommandSlot`은 "근거 그래프 보기" 버튼 prop(`onOpenGraph`)이 **없으면** 버튼을 그리지 않게 만들어 두었다. 이 step은 그 prop을 연결한다. step 6 테스트 중 `show_graph_fragment`를 포함한 턴에서 버튼이 없음을 단언한 것이 있으면 약화하지 말고 `onOpenGraph`가 없는 렌더에 대한 단언으로 유지하고 새 테스트는 prop을 준 렌더로 쓴다. `web/app/page.tsx`는 탭을 더하므로 step 5의 `smoke.test.tsx`는 새 구조에 맞게 통과해야 한다(단언 삭제·약화 금지, 렌더 대상 문구만 갱신 허용).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/PRD.md`(온톨로지 그래프 화면), `/docs/ARCHITECTURE.md`(온톨로지 노드·관계 표, 스트리밍 이벤트와 화면 명령)
- `/src/beautyads/api/graph_routes.py`, `/src/beautyads/graph/fragment_queries.py`, `/src/beautyads/graph/ontology_view.py`(응답 모양과 레이블·관계 목록)
- `/web/lib/types.ts`, `/web/lib/api.ts`, `/web/lib/taxonomy.ts`, `/web/components/CommandSlot.tsx`, `/web/components/EvidenceCards.tsx`(안전 링크), `/web/app/page.tsx`, `/web/tests/`(step 4~6 산출물)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `web/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1. `web/lib/`**: `api.ts`에 `getGraphFragment(tenantId, ids)`(`GET /api/graph/fragment?ids=...`, 각 ID는 URL 인코딩, 쉼표로 잇는다, 30개 초과는 호출 전에 거부)를 **추가**한다. `graph.ts`: `fragmentToElements`·`schemaToElements`와 층·레이블 색 상수, 범례 항목. 타입은 서버 코드에서 읽은 키만(`types.ts`에 **추가만**).

**2. `web/components/`**: `GraphCanvas.tsx`(`cytoscape` 동적 import, `destroy`, 노드 클릭 콜백, 컨테이너 높이 고정), `GraphPanel.tsx`(조각 조회와 상태 4가지, 범례, 상세), `SchemaView.tsx`(스키마 조회와 같은 캔버스), `NodeDetail.tsx`. `CommandSlot.tsx`의 `onOpenGraph` 연결과 `web/app/page.tsx`의 상단 탭("대화" · "전체 스키마")을 더한다.

**3. 테스트(`web/tests/`, 가짜 `fetch`와 `vi.mock("cytoscape")` — jsdom에는 canvas가 없으므로 실제 렌더 대신 요소·호출을 검사)**
- (1) `fragmentToElements`: 합성 조각에서 노드·엣지 수와 ID, 모든 엣지의 양 끝이 노드에 있음, 라벨 없는 소재(이웃 없음)도 노드로 나옴, 분류 값 노드는 한국어 이름·없으면 원 이름, `missing`은 요소로 만들지 않음. `schemaToElements`: 서버 `labels`·`relationships` 개수와 같고(**검사한 요소가 0이면 실패**) 층별 색 구분.
- (2) `getGraphFragment`: URL·헤더(`X-Tenant-Id`) 정확 일치, ID 인코딩, 31개 이상 호출 전 거부(`fetch` 호출 없음), 비-200 `ApiError`.
- (3) `GraphPanel`: 불러오는 중 → 성공(캔버스 생성 호출, `missing` 안내), 빈 조각 안내, 오류 코드와 "다시 시도"(누르면 재조회), 언마운트 때 `destroy` 호출. `SchemaView` 동일 패턴.
- (4) `NodeDetail`: `props`만 표시, `url`은 `http(s)`만 링크(`javascript:`는 링크 없음).
- (5) `CommandSlot`: `show_graph_fragment`가 있고 `onOpenGraph`를 주면 버튼이 있고 누르면 그 명령의 `evidence_ids`로 호출, 없으면 버튼 없음. `page.tsx` 탭 전환.
- 서버가 만든 문장·분류 값을 기대값으로 굳히지 않는다(합성 값과 구조만).

## Acceptance Criteria

```bash
make verify   # ruff + pytest + pnpm lint·typecheck·test 통과
NEXT_TELEMETRY_DISABLED=1 pnpm --dir web build   # 프로덕션 빌드(타입·컴파일) 통과, 서버 연결 불필요
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

- `cytoscape` 외 그래프·레이아웃 패키지를 설치하지 마라. 이유: 승인한 패키지만 허용한다(AGENTS.md CRITICAL). `cytoscape`는 step 4에서 설치돼 있다.
- 서버 모듈(`src/`)·파이썬 테스트·`Makefile`을 수정하지 마라. 조각 응답에 필요한 칸이 없으면 만들지 말고 `blocked`로 보고하라. 이유: 서버 계약은 step 2·3에서 끝났다.
- 이웃이 없는 소재 노드를 오류로 처리하거나 숨기지 마라. 이유: 분석된 소재만 분류 축 관계가 있어 라벨 없는 소재가 정상이다(그래프 1,172/7,429).
- 그래프 화면에 다른 방식과의 정확도 비교·우열 문구를 넣지 마라. 이유: 실험 결과를 사실과 다르게 말하지 않는다(사용자 원칙, `docs/results/2026-11-20-p6-final.md` 3.2: E3 비교 구성의 한계).
- `pnpm dev`나 `pnpm start`를 서버가 연결된 상태로 실행하지 마라. 이유: 서버 실행과 화면 확인은 사용자가 한다. 빌드(`pnpm --dir web build`)는 AC에서 허용되며 서버 연결이 필요 없다.
