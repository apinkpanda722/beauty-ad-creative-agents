# Step 6: graph-data

## 설계 검토 기록

**목적(독립·삭제 가능 step)**: 지식 그래프 **데이터 그래프 탭**과 서버의 읽기 전용 탐색 엔드포인트 2개를 만든다. 이 step을 건너뛰어도 step 5까지의 화면은 그대로 동작해야 한다(탭이 목록에 나타나지 않을 뿐).

**코드를 열어 확인한 사실**: `src/beautyads/api/graph_routes.py`의 `register_graph`는 `/graph/fragment`·`/graph/schema`·`/workspaces`를 등록하고 모든 경로가 `resolve_tenant`로 세션을 검사한다. `services.graph_fragment`는 `api/assembly.py`(291행 부근 정의, 705행 부근 주입)가 만든 함수이고 없으면 `503 GRAPH_UNAVAILABLE`. 그래프 질의는 `src/beautyads/graph/fragment_queries.py`의 **고정 Cypher + 파라미터**(`fragment_parameters`, `build_fragment`, 노드·관계 변환)이고 `neo4j` import는 `graph` 계층에서만 허용된다(`tests/test_architecture.py`). 확정 사항: 제품 노드는 모든 브랜드 공용, **피드백만 작업 공간 범위**.

**설계 결정**
- 새 `src/beautyads/graph/explore_queries.py`: 고정 Cypher 두 개와 파라미터 검증·응답 변환. `overview`: 공용 카탈로그(`Brand`·`Product`·`Efficacy` 노드와 그 사이 관계)에서 상한 60개 노드. `neighbors(id)`: 노드 한 개의 이웃을 상한 50개로. **어느 질의도 `Feedback` 라벨 노드를 반환하지 않는다**(`WHERE NOT n:Feedback`류로 **질의 단계에서** 제외하고 응답 변환 단계에서도 거른다: 이중 방어). 노드 id 표현은 `build_fragment`가 쓰는 `GraphNode`(`id`, `label`, `name`, `props`) 형식을 **그대로** 따른다(기존 `fragmentToElements`가 쓰려면 같아야 함, Codex가 `build_fragment`를 열어 확인하고 다르면 blocked).
- 응답 형식은 `/graph/fragment`와 같은 `{nodes, edges}`(+ `truncated: bool`)로 웹의 `fragmentToElements`를 재사용한다.
- 라우트(`graph_routes.py`): `GET /graph/overview`, `GET /graph/neighbors?id=`. 둘 다 `resolve_tenant`를 먼저 호출하고(검사 실패 시 거부), `id`는 정규식으로 검증(`GRAPH_ID_INVALID` 422, 길이 상한), 그래프가 없으면 503 `GRAPH_UNAVAILABLE`, 질의 오류는 본문 없이 500 `GRAPH_QUERY_FAILED`(기존 `/graph/fragment`와 같은 처리). `assembly.py`에는 기존 `graph_fragment`와 같은 방식으로 두 함수를 **주입만** 추가한다.
- 웹: `web/lib/api.ts`에 `getGraphOverview(tenantId)`, `getGraphNeighbors(tenantId, id)`(기존 `getGraphFragment` 형식), `web/components/graph/DataTab.tsx`(처음 카탈로그를 보여 주고 노드 선택 → `이웃 펼치기` → 응답을 병합(`id`로 중복 제거)해 캔버스 갱신, `truncated`면 "일부만 표시" 문구), `tabs.ts`에 `data` 탭 한 줄 추가.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| 탐색 Cypher·변환 | `src/beautyads/graph/explore_queries.py` | `api/assembly.py`(주입), `tests/test_graph_explore.py` |
| 라우트 2개 | `src/beautyads/api/graph_routes.py` | `web/lib/api.ts` |
| `data` 탭 | `web/components/graph/tabs.ts` | `GraphPage.tsx` |

**공통 시각 기준(7c 시각 확인 반영, 이후 모든 새 화면이 따른다)**: 간격은 `tokens.css`의 `--gs-space-*`(4px 배수, 기본 리듬은 8px 단위)만 쓰고 색·반경·그림자·글자 크기도 `tokens.css` 변수만 쓴다. 화면에 보이는 문자열은 **한글**이다(영문 내부 코드·브랜드 슬러그·도구 이름·`value`·`n_top` 같은 필드명을 그대로 노출하지 않는다. `taxonomyNames`의 한글 이름, `web/lib/workspace.ts`의 `workspaceLabel`, 그리고 step 13의 한글 표시 매핑을 재사용하고 없는 이름은 새로 지어내지 말고 원문 대신 `기타`·`정보 없음` 같은 한글 대체를 쓴다). 펼침·접힘은 `grid-template-rows: 0fr → 1fr` 방식의 부드러운 아코디언(화살표 회전)이고, 모든 애니메이션·전환은 `@media (prefers-reduced-motion: reduce)`에서 즉시 동작·정지한다. 색에만 의존하지 않고 아이콘·글자를 함께 쓴다. 접힌 영역의 내용은 DOM에 유지하고 접힌 최종 상태는 기존처럼 `hidden` 속성이다(펼칠 때 `hidden`을 동기적으로 제거한 뒤 다음 프레임에 열림 클래스를 붙이고, 접을 때는 전환 뒤 `hidden`을 설정하되 reduced-motion·전환 시간 0이면 즉시 설정한다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/src/beautyads/api/graph_routes.py`, `/src/beautyads/api/assembly.py`(graph_fragment 정의·주입부), `/src/beautyads/api/session.py`, `/src/beautyads/graph/fragment_queries.py`, `/src/beautyads/graph/ontology_view.py`, `/tests/test_architecture.py`, `/docs/ARCHITECTURE.md`, `/docs/TAXONOMY.md`
- `/tests/test_caps_guard.py`·`/tests/test_architecture.py`(`src/` 전체 `.py`를 훑는다: 새 파일이 계층 규칙과 캡 가드를 통과해야 한다), `/tests/`의 기존 `/graph/fragment` 라우트 테스트(`rg -n "graph/fragment" tests`로 찾는다), `/web/components/graph/*`, `/web/lib/{api,graph}.ts`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/graph/explore_queries.py`, `src/beautyads/api/graph_routes.py`, `src/beautyads/api/assembly.py`(주입만), `tests/test_graph_explore.py`, `tests/test_api_graph_explore.py`, `web/lib/api.ts`, `web/components/graph/{DataTab.tsx,tabs.ts}`, `web/tests/graph-data.test.tsx`

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `src/beautyads/graph/explore_queries.py`, `src/beautyads/api/graph_routes.py`, `src/beautyads/api/assembly.py`(주입만), `tests/test_graph_explore.py`, `tests/test_api_graph_explore.py`, `web/lib/api.ts`, `web/components/graph/{DataTab.tsx,tabs.ts}`, `web/tests/graph-data.test.tsx`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `graph/explore_queries.py`(고정 Cypher, 파라미터 검증, 응답 변환). **2.** `graph_routes.py`에 라우트 2개, `assembly.py`에 주입 한 곳. **3.** 웹 API 함수·`DataTab`·탭 한 줄.

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `tests/test_graph_explore.py`(가짜 neo4j 세션·행 픽스처만): (1) `overview` 변환은 노드 상한 60을 넘기지 않고 `truncated`를 표시, (2) **`Feedback` 라벨 행이 입력에 섞여 있어도 응답 노드·엣지에 없다**(질의 문자열에 `Feedback` 제외 조건이 있는지도 단언), (3) `neighbors`는 id 형식이 틀리면 `ValueError`, (4) 상한 50, (5) 노드 필드가 `{id,label,name,props}`이고 값 형식은 `fragment`와 같다.
- 라우트 테스트(`TestClient`, 가짜 assembly): (6) 허용되지 않은 `X-Tenant-Id`는 거부(기존 `resolve_tenant` 동작과 같은 상태 코드), (7) 그래프 주입이 없으면 503 `GRAPH_UNAVAILABLE`, (8) id 형식 오류 422 `GRAPH_ID_INVALID`, (9) 내부 오류 시 500 `GRAPH_QUERY_FAILED`이고 본문에 예외 문자열이 없다, (10) 기존 `/graph/fragment`·`/graph/schema`·`/workspaces` 응답은 그대로.
- 웹(`web/tests/graph-data.test.tsx`): (11) 데이터 탭은 `tabs.ts`에 있을 때만 표시, (12) 노드 선택 후 `이웃 펼치기`가 `getGraphNeighbors`를 그 id로 호출하고 결과를 중복 없이 병합, (13) `truncated`이면 안내 문구, (14) 오류 시 재시도.
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
- `graph/fragment_queries.py`·`graph/ontology_view.py`·`graph/schema` 적재 코드·`store/`를 수정하지 마라. 이유: 기존 읽기·적재 경로는 불변이고 이 step은 새 읽기 전용 질의만 더한다.
- 응답에 `Feedback` 노드나 작업 공간 범위 데이터를 포함하지 마라(질의와 변환 양쪽에서 제외). 이유: 제품 노드만 공용 카탈로그이고 피드백만 작업 공간 범위다(확정 사항, ADR-009).
- Cypher를 요청 입력으로 받거나 조립하지 마라. id만 검증된 파라미터로 전달하라. 이유: 에이전트·사용자에게 Cypher를 쓰게 하지 않는다.
- `make db-up`·`make serve`·`make demo-up`을 실행하거나 Neo4j에 연결하지 마라(실제 쿼리 검증은 사용자가 로컬에서 한다).
