# Step 5: graph-core

## 설계 검토 기록

**목적**: 지식 그래프 화면을 3탭 구조로 만든다. 이 step은 **스키마**와 **근거 경로** 탭을 구현하고, **데이터 그래프** 탭은 step 6이 켠다(step 6이 없으면 탭이 목록에 나타나지 않는다).

**코드를 열어 확인한 사실**: `GraphCanvas.tsx`(cytoscape 동적 import, 높이 `28rem` 고정, 줌 한계 없음, `cose`/`breadthfirst`), `GraphPanel.tsx`(근거 경로: `getGraphFragment`+`getSchema`, 로딩·오류·재시도 상태), `SchemaView.tsx`, `NodeDetail.tsx`, `web/lib/graph.ts`(`LAYER_COLORS` 1층 `#427c69`, 2층 `#527cac`, 3층 `#8961a8`, `LABEL_COLORS`, `fragmentToElements`, `schemaToElements`). 확정 사항: **제품 노드는 모든 브랜드 공용 카탈로그, 피드백만 작업 공간 범위**.

**설계 결정**
- `web/components/graph/GraphPage.tsx`: `ui/Tabs` 3개 정의 `[{id:"schema"}, {id:"data"(step 6에서 추가)}, {id:"path"}]` — 탭 목록은 `web/components/graph/tabs.ts`의 배열 한 곳이고 이 step은 `schema`·`path`만 넣는다.
- 레이아웃: 좌측 범례·필터(층·노드 종류 토글), 중앙 캔버스, 우측 속성 패널(`NodeDetail` 재작성: 속성 키/값 표, 연결 수). 캔버스 상단 우측에 `＋ － 맞춤` 버튼.
- **확대·축소 한계**: `web/lib/graph.ts`에 `ZOOM_LIMITS = { min: 0.3, max: 2.5 }`, `GraphCanvas`가 cytoscape `minZoom`/`maxZoom`을 이 값으로 설정, `wheelSensitivity`는 낮춤(값은 상수). 버튼은 한계에서 비활성.
- 색은 기존 `LAYER_COLORS`·`LABEL_COLORS`를 유지(범례와 일치). 캔버스 높이는 화면에 맞춰 가변.
- **근거 경로 탭**: 세션의 **가장 최근 결과의 `show_graph_fragment` 근거 id**를 쓴다. 결과가 없으면 `EmptyState`("광고 기획에서 요청을 실행하면 근거 경로가 표시됩니다"). 기존 `GraphPanel`의 로딩·오류·재시도·`missing` 문구 동작을 유지한다.
- **스키마 탭**: `getSchema` 결과의 `schemaToElements`. 피드백 라벨도 스키마에는 표시(3층, 작업 공간 범위 데이터임을 범례에 표시).
- `TurnCard`의 "근거 그래프 열기" 버튼은 지식 그래프 > 근거 경로 탭으로 이동(`web/app/page.tsx`가 가진 `view` 상태 변경 + 탭 선택, 이 연결은 `session` 또는 콜백 props로 전달)으로 바꾼다.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `ZOOM_LIMITS` | `web/lib/graph.ts` | `GraphCanvas.tsx`, `graph.test.ts` |
| 탭 목록 | `web/components/graph/tabs.ts` | `GraphPage.tsx`, step 6 |
| 근거 경로 입력 | `web/lib/session.tsx`의 `latestGraphIds(state)` | `PathTab.tsx`, `TurnCard.tsx` |

**공통 시각 기준(7c 시각 확인 반영, 이후 모든 새 화면이 따른다)**: 간격은 `tokens.css`의 `--gs-space-*`(4px 배수, 기본 리듬은 8px 단위)만 쓰고 색·반경·그림자·글자 크기도 `tokens.css` 변수만 쓴다. 화면에 보이는 문자열은 **한글**이다(영문 내부 코드·브랜드 슬러그·도구 이름·`value`·`n_top` 같은 필드명을 그대로 노출하지 않는다. `taxonomyNames`의 한글 이름, `web/lib/workspace.ts`의 `workspaceLabel`, 그리고 step 13의 한글 표시 매핑을 재사용하고 없는 이름은 새로 지어내지 말고 원문 대신 `기타`·`정보 없음` 같은 한글 대체를 쓴다). 펼침·접힘은 `grid-template-rows: 0fr → 1fr` 방식의 부드러운 아코디언(화살표 회전)이고, 모든 애니메이션·전환은 `@media (prefers-reduced-motion: reduce)`에서 즉시 동작·정지한다. 색에만 의존하지 않고 아이콘·글자를 함께 쓴다. 접힌 영역의 내용은 DOM에 유지하고 접힌 최종 상태는 기존처럼 `hidden` 속성이다(펼칠 때 `hidden`을 동기적으로 제거한 뒤 다음 프레임에 열림 클래스를 붙이고, 접을 때는 전환 뒤 `hidden`을 설정하되 reduced-motion·전환 시간 0이면 즉시 설정한다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/components/{GraphCanvas,GraphPanel,SchemaView,NodeDetail}.tsx`, `/web/lib/{graph,api,types,session}.ts*`, `/web/components/ui/*`, `/web/components/plan/*`, `/web/components/shell/*`
- `/web/tests/{graph,graph-view}.test.ts*`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/components/graph/*`, `web/app/graph.css`, `web/lib/graph.ts`, `web/lib/session.tsx`(`latestGraphIds`만), `web/components/plan/TurnCard.tsx`(버튼 이동만), `web/app/page.tsx`(본문 연결), 옛 `web/components/{GraphCanvas,GraphPanel,SchemaView,NodeDetail}.tsx`(삭제), `web/tests/{graph,graph-view}.test.ts*`, `web/app/page.tsx`(옛 `SchemaView` import 제거만, 지식 그래프 본문은 `AppShell`이 연결)

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/components/graph/*`, `web/app/graph.css`, `web/lib/graph.ts`, `web/lib/session.tsx`(`latestGraphIds`만), `web/components/plan/TurnCard.tsx`(버튼 이동만), `web/app/page.tsx`(본문 연결), 옛 `web/components/{GraphCanvas,GraphPanel,SchemaView,NodeDetail}.tsx`(삭제), `web/tests/{graph,graph-view}.test.ts*`, `web/app/page.tsx`(옛 `SchemaView` import 제거만, 지식 그래프 본문은 `AppShell`이 연결)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `web/lib/graph.ts`에 `ZOOM_LIMITS` 추가(기존 export는 그대로). **2.** `web/components/graph/*` 재작성(옛 `GraphCanvas`·`GraphPanel`·`SchemaView`·`NodeDetail` 삭제). **3.** `web/app/page.tsx`의 지식 그래프 본문 연결(옛 `SchemaView` 렌더와 "대화"·"전체 스키마" 임시 탭 제거), `TurnCard`의 버튼 이동 동작.

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `web/tests/graph.test.ts`: 기존 단언 유지 + (1) `ZOOM_LIMITS`가 `{min:0.3,max:2.5}`이고 `min < max`.
- `web/tests/graph-view.test.tsx`(**기존 모든 행동 단언을 새 구조에서 같은 엄격도로 옮긴다**: 그래프 로딩·오류·재시도, `missing` 문구, 노드 클릭 → 상세, `GRAPH_RENDER_FAILED` 재시도, 범례 층·노드 종류): (2) 탭은 `스키마`·`근거 경로`만 있고 순서가 고정(데이터 탭은 아직 없음), (3) 캔버스는 `minZoom`/`maxZoom`이 `ZOOM_LIMITS`로 설정(cytoscape 가짜 모듈에서 생성 옵션을 검사), (4) 확대 버튼은 최대 한계에서 비활성, (5) 근거 경로 탭은 결과가 없으면 빈 상태, 결과가 있으면 `getGraphFragment`가 그 id로 호출, (6) 스키마 탭 범례에 피드백(3층)이 작업 공간 범위임이 표시.
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
- `web/lib/api.ts`의 `getGraphFragment`·`getSchema` 계약을 바꾸지 마라. 이유: 서버 계약 불변.
- Neo4j·Cypher를 웹에서 직접 다루거나 클라이언트에 질의 입력 칸을 만들지 마라. 이유: 에이전트·사용자에게 Cypher를 쓰게 하지 않는다(AGENTS.md).
