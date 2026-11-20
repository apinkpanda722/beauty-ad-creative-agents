# Step 2: graph-api

## 설계 검토 기록

**배경(P7 설계 승인 b·c)**: 화면의 그래프 화면과 작업 공간 선택에는 서버가 아직 주지 않는 데이터가 있다. (1) `show_graph_fragment`의 본문은 `{"evidence_ids": [...]}`뿐이라(`api/ask_view.py` 260행) 노드·관계를 그릴 수 없다. (2) 전체 스키마를 줄 경로가 없다. (3) 작업 공간 목록·제품명·시안 이미지 사용 여부를 줄 경로가 없다. 이 step은 **읽기 전용 경로 세 개**(`GET /graph/fragment`, `GET /graph/schema`, `GET /workspaces`)와 이를 받치는 고정 질의·고정 스키마 상수를 만든다. 에이전트 도구가 아니다(ADR-011의 도구 등록 목록을 바꾸지 않는다).

**식별자 전수 대조(현재 코드, 모두 열어 확인)**:
- 그래프 사실(2026-11-20 읽기 전용 질의, 모델 호출 없음): 노드 레이블 17개 = `Creative`, `IngredientAlias`, `Ingredient`, `Product`, `ClaimRule`, `Form`, `Brand`, `Efficacy`, `SkinConcern`, `Hook`, `Angle`, `Format`, `Talent`, `CtaType`, `SkinType`, `Category`, `FunctionalCert`. 관계 유형 18개 = `CONTAINS`, `CLAIMS`, `ALIAS_OF`, `USES_HOOK`, `HAS_ANGLE`, `HAS_FORMAT`, `FEATURES`, `HAS_CTA`, `MENTIONS`, `PROMOTES`, `OWNS`, `IN_CATEGORY`, `HAS_EFFICACY`, `CERTIFIED_AS`, `HAS_FORM`, `APPLIES_TO`, `ADDRESSES`, `SUITS`. 아직 데이터에는 없지만 코드에 있는 것: `Feedback` 노드(`graph/schema.py`의 `FEEDBACK_CONSTRAINTS`)와 `ABOUT` 관계(`graph/feedback.py`). `Creative`는 7,429개이고 분류 축 관계(`USES_HOOK` 등)는 1,172개 소재에만 있다(분석된 소재만 라벨이 있다 → **라벨 없는 소재가 정상**이다).
- `graph/load.py`: `AXES = (("hook_type","Hook","USES_HOOK",HookType), ("angle","Angle","HAS_ANGLE",Angle), ("format","Format","HAS_FORMAT",Format), ("talent","Talent","FEATURES",Talent), ("cta_type","CtaType","HAS_CTA",CtaType))`, `CREATIVE_PROPERTIES`(`source`, `source_id`, `url`, `published_at`, `duration_s`, `language`, `brand`, `latest_view_count`, `latest_like_count`, `latest_comment_count`, `metrics_collected_at`, `advertiser_name`).
- `graph/layer1.py`: `(b)-[r:OWNS]->(p)`(Brand→Product), 제품 관계 튜플(`IN_CATEGORY`·`HAS_FORM`·`SUITS`·`CERTIFIED_AS`)은 문자열 상수로 있어 `[:관계]` 정규식만으로는 안 잡힌다. `graph/layer2.py`: `PROMOTES`·`CLAIMS`·`MENTIONS`.
- `graph/evidence_queries.py`: 소재 ID는 `c.source + ':' + c.source_id`, 읽기 전용 고정 질의 패턴(`product_name_query()`/`product_name_parameters(*, brand, url)`가 입력 검증 + 매개변수 모양의 선례). `domain/tools.py`: `EVIDENCE_ID_PATTERN = r"^[a-z]+:[A-Za-z0-9_-]{1,64}$"`.
- `graph/connection.py`: `GraphConnection.run(query, params) -> GraphResult(records, ...)`(`records`는 dict 목록). 값 타입은 `neo4j.time.DateTime` 등이다(FP-C03 추가 사례: 합성 문자열로만 테스트하면 직렬화 실패를 못 잡는다).
- `api/app.py`: `Assembly`(데이터클래스; **`graph` 필드는 Neo4j가 아니라 LangGraph 그래프**다), 이미 있는 `workspaces: Mapping[str, dict]`(`WorkspaceProfile` 덤프: `tenant_id`, `display_name`, `brand`, `own_product_url`, `tone`, `forbidden_terms`, `price_band_pct`), `image_enabled: bool`. `api/assembly.py`: `assemble_full` 안의 지역 변수 `product_names`(테넌트 → 쇼핑몰 공식 제품명)와 `graph_connection`은 `Assembly`로 나가지 않는다.
- `api/session.py`: `resolve_tenant(header, *, allowed_tenants) -> tenant_id`(없으면 400 `TENANT_CONTEXT_MISSING`, 허용 밖이면 403 `TENANT_NOT_ALLOWED`).
- `analysis/prompts.py`: `axis_glossary() -> {"hook_type"|"angle"|"format": [{"value","name","definition"}...]}`(`other` 제외), `CLAIM_DISPLAY_NAMES: {Claim: 표시 이름}`(`Claim.other` 포함). `api`는 `analysis`를 import할 수 있다(AGENTS.md 표).

**설계 결정**:
- **세 경로 모두 읽기 전용·고정 질의·테넌트 비전용 공개 지식만**이다. 그래프 조각에는 `Feedback`·`ClaimRule`을 넣지 않는다(ADR-009: 테넌트 전용 데이터는 이 경로로 나가지 않는다). 허용 노드는 `Creative`와 그 분류 축 노드(`Hook`·`Angle`·`Format`·`Talent`·`CtaType`), 효능(`Efficacy`, `CLAIMS`), 제품(`Product`, `PROMOTES`)과 그 브랜드(`Brand`, `OWNS`)이다.
- `GET /graph/fragment`·`GET /graph/schema`는 `X-Tenant-Id` 검사를 거친다(`resolve_tenant`). `GET /workspaces`는 **테넌트를 고르기 전에** 부르는 경로라 헤더 없이 허용 목록의 이름만 돌려준다(예외로 ADR-009 주석을 코드에 단다).
- `GET /workspaces` 응답: `{"workspaces": [{"tenant_id","display_name","brand","product_name"}...], "image_enabled": bool}`, `tenant_id`로 정렬. `product_name`은 쇼핑몰 공식 제품명이며 없으면 `null`이다. `own_product_url`·`tone`·`forbidden_terms`·`price_band_pct`는 내보내지 않는다.
- `GET /graph/schema` 응답: `{"labels": [{"label","layer","name_ko"}], "relationships": [{"type","from","to","layer"}], "taxonomy": axis_glossary(), "claims": [{"value","name"}]}`. `layer`는 1(제품 지식)·2(광고 관찰)·3(피드백). `claims`는 `Claim.other`를 뺀 표시 이름이다(화면이 분류 값의 한국어 이름을 쓰는 단일 출처).
- `GET /graph/fragment?ids=a,b,c` 응답: `{"nodes": [{"id","label","name","props"}], "edges": [{"source","target","type"}], "missing": [그래프에 없는 소재 ID]}`. 노드 `id`는 소재가 `creative:<소재 ID>`, 그 밖에는 `<레이블>:<값>`. `props`는 레이블별 **허용 속성 목록**만(소재: `source`·`url`·`brand`·`published_at`·`latest_view_count`·`latest_like_count`, 시각은 ISO 문자열). 질의 행은 상한 500, ids는 1~30개(`handoff_max_evidence_ids` 기본값 30과 같다).
- `Assembly`에 필드 둘을 **뒤에 기본값으로** 더한다: `graph_fragment: Callable | None = None`(ids → 조각 dict), `product_names: Mapping[str, str] = field(default_factory=dict)`. `assemble_full`이 `graph_connection`으로 `graph_fragment`를, 기존 `product_names`로 같은 이름 필드를 채운다. 라우트는 **요청 시점에** `request.app.state.assembly`에서 읽는다(B-FP-070).

**근거 카드 분석 속성(P7 승인 추가, 서버 절반)**: 근거 카드(`show_evidence_cards`)에 경쟁사 광고의 멀티모달 분석 결과(훅 유형·소구·형식·출연자·CTA·효능 주장)를 싣는다. 카드 데이터는 PostgreSQL `creatives`에서 읽는 `hydrate`(`api/assembly.py`)가 만들고, 분석 라벨은 그래프에만 있으므로(`Creative`→`Hook`·`Angle`·`Format`·`Talent`·`CtaType` 관계와 `CLAIMS`→`Efficacy`) **`hydrate`가 그래프 질의 하나로 라벨을 합친다**. 이 step은 질의와 `hydrate` 합치기까지이고, 카드 필드로 내보내는 것(`ask_view.py` `_CARD_FIELDS`)은 step 3이다.
- 새 고정 질의 `creative_labels_query()`와 `creative_labels_parameters(ids)`를 **`graph/evidence_queries.py`**에 더한다(`product_name_query()`처럼 읽기 전용·고정 문장·매개변수만. 동결 CQ 질의·기존 질의 문자열은 바꾸지 않는다). 입력 `$ids`는 `c.source + ':' + c.source_id` 형식의 소재 ID 목록(`EVIDENCE_ID_PATTERN`, 최대 30개). 반환 열: `creative_id`, `hook_type`(`h.value`), `angle`, `format`, `talent`(`FEATURES`), `cta_type`(`HAS_CTA`), `claims`(`collect(DISTINCT e.value)`, `CLAIMS`). 관계 이름은 `graph/load.py`의 `AXES`와 `graph/layer2.py`에서 확인한 것만 쓴다.
- 순수 함수 `card_labels_by_id(rows) -> dict[str, dict]`(같은 파일): 행을 `{소재 ID: {"hook_type","angle","format","talent","cta_type","claims"}}`로 만든다. 값이 없으면 `None`, `claims`는 항상 목록(없으면 `[]`)이다. **라벨이 하나도 없는 소재(분류 축 관계가 없음, 그래프 소재 7,429개 중 1,172개만 라벨이 있다)는 모든 값이 `None`·`[]`인 정상 결과다.**
- `hydrate`는 Postgres 카드(기존 7열 질의 그대로)를 만든 뒤 **그 소재 ID들로 라벨 질의를 한 번만** 보내 각 카드에 위 여섯 키를 더한다. 라벨 질의가 실패하면(`Exception`) **카드를 막지 않고** 여섯 키를 `None`·`[]`로 두며 예외 메시지·값을 기록하지 않는다(라벨은 부가 정보). 기존 Postgres 질의·롤백 처리·`ASSEMBLY_HYDRATE_FAILED` 규칙은 바꾸지 않는다.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| 카드 라벨 질의·변환 | `graph/evidence_queries.py` | `api/assembly.py`(`hydrate`), `tests/test_graph_evidence_queries.py` |
| 카드의 여섯 키(`hook_type`·`angle`·`format`·`talent`·`cta_type`·`claims`) | `api/assembly.py`(`hydrate`) | `api/ask_view.py`(step 3의 `_CARD_FIELDS`), 웹 `EvidenceCards`(step 6) |
| `Assembly.graph_fragment` | `api/assembly.py`(조립) | `api/graph_routes.py` |
| `Assembly.product_names` | `api/assembly.py` | `api/graph_routes.py`(`/workspaces`) |
| 고정 질의·조각 변환 | `graph/fragment_queries.py` | `api/assembly.py`(조립), `tests/test_graph_fragment.py` |
| 스키마 상수 | `graph/ontology_view.py` | `api/graph_routes.py`(`/graph/schema`), `tests/test_graph_fragment.py`(상수 대조) |
| 세 경로 | `api/graph_routes.py` | `api/app.py`(`register_graph(app)`), 웹(step 4~7) |

**기존 단언과의 충돌 점검**: `Assembly` 생성자는 새 필드가 기본값을 가져 기존 호출(`tests/test_api_chat.py::assembly`, `tests/test_api_ask.py::services`)이 그대로 동작한다. `tests/test_api_assembly.py`는 `assemble_full`을 가짜 서비스로 조립해 결과 `Assembly`를 검사하므로 필드를 정확 일치로 비교하는 단언이 있으면 확인하고 "기대값에 새 필드만 더함"으로 갱신한다(약화 금지). `assemble_full`은 시작 때 새 질의를 보내지 않는다(조각 질의는 요청 때만, 가짜 그래프의 호출 목록 단언 불변). **카드 라벨 질의는 `hydrate` 호출마다 1회 추가된다**: `tests/test_api_assembly.py::test_hydrate_uses_seven_columns_and_bound_keys_and_json_dates`는 `rig.queries`(Postgres와 가짜 그래프가 **같은 목록**에 기록한다)에 대해 `len(rig.queries) == 1`·`rig.queries[0]`로 Postgres 질의를 단언하므로, 그 줄을 "Postgres 질의 1건 + 그래프 라벨 질의 1건(총 2건), Postgres 질의는 `SELECT` 7열·바인딩 키 단언 그대로"로 **갱신만** 한다(질의 종류로 골라 읽고, 부분 비교·길이 비교로 약화하지 않는다). 가짜 그래프는 알 수 없는 질의에 `[{"creative_id": EID}]` 행을 돌려주므로(라벨 값 없음) 라벨 질의는 `None`·`[]` 키가 붙는 정상 경로로 지나간다. `tests/test_graph_evidence_queries.py`는 **케이스 추가에 한함**(기존 질의 문자열·매개변수 단언 불변).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`(계층 경계, 외부 SDK 표, CRITICAL: 에이전트에게 Cypher를 쓰게 하지 않는다, 테넌트 규칙)
- `/docs/ARCHITECTURE.md`(온톨로지, 스트리밍 이벤트와 화면 명령), `/docs/ADR.md`(ADR-009, ADR-011), `/docs/CONTRACTS.md`(Neo4j 절: 값 타입)
- `/src/beautyads/api/app.py`, `/src/beautyads/api/assembly.py`, `/src/beautyads/api/session.py`, `/src/beautyads/api/feedback.py`(오류를 코드로만 돌려주는 패턴)
- `/src/beautyads/graph/connection.py`, `/src/beautyads/graph/evidence_queries.py`, `/src/beautyads/graph/load.py`, `/src/beautyads/graph/layer1.py`, `/src/beautyads/graph/layer2.py`, `/src/beautyads/graph/feedback.py`, `/src/beautyads/graph/schema.py`
- `/src/beautyads/domain/tools.py`(`EVIDENCE_ID_PATTERN`), `/src/beautyads/analysis/prompts.py`(`axis_glossary`, `CLAIM_DISPLAY_NAMES`)
- `/tests/test_api_ask.py`(`services`), `/tests/test_api_chat.py`(`assembly`), `/tests/test_api_assembly.py`, `/tests/test_graph_queries.py`, `/tests/test_graph_evidence_queries.py`, `/tests/test_architecture.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/graph/fragment_queries.py`, `src/beautyads/graph/ontology_view.py`, `src/beautyads/api/graph_routes.py`, `src/beautyads/api/app.py`, `src/beautyads/api/assembly.py`, `src/beautyads/graph/evidence_queries.py`, `tests/test_graph_fragment.py`, `tests/test_api_graph.py`, `tests/test_api_assembly.py`, `tests/test_graph_evidence_queries.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `src/beautyads/graph/fragment_queries.py`, `src/beautyads/graph/ontology_view.py`, `src/beautyads/api/graph_routes.py`, `src/beautyads/api/app.py`, `src/beautyads/api/assembly.py`, `src/beautyads/graph/evidence_queries.py`, `tests/test_graph_fragment.py`, `tests/test_api_graph.py`, `tests/test_api_assembly.py`, `tests/test_graph_evidence_queries.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1. `graph/fragment_queries.py`(새, 계층: graph, import 허용 domain·settings만)**
- `def fragment_query() -> str`: **고정 Cypher 문자열 하나**(상수). 입력은 `$ids`와 `$limit` 매개변수로만 들어가고 문자열 보간이 없다. 소재(`c:Creative`)를 `c.source + ':' + c.source_id IN $ids`로 찾고 위 "허용 노드·관계"만 `OPTIONAL MATCH`로 잇는다.
- `def fragment_parameters(ids) -> dict`: 목록이 아니거나 비었거나 30개 초과이거나 각 항목이 `EVIDENCE_ID_PATTERN`에 맞지 않으면 `ValueError("GRAPH_FRAGMENT_IDS_INVALID")`. 중복은 순서를 유지해 제거한다. 반환 `{"ids": [...], "limit": 500}`.
- `def build_fragment(requested_ids, rows) -> dict`: 질의 행을 위 응답 모양으로 바꾼다(노드 중복 제거, 모든 엣지의 양 끝이 노드 목록에 있음, 요청 ID 중 행에 없는 것은 `missing`). **드라이버 값 타입(`neo4j.time.DateTime` 등)은 JSON 값(ISO 문자열)으로 바꾼다**. 알 수 없는 값 타입은 조용히 버리지 말고 `ValueError("GRAPH_FRAGMENT_VALUE_INVALID")`로 올린다(FP-C03).

**2. `graph/ontology_view.py`(새, 계층: graph)**
- `ONTOLOGY_LABELS`: 위 17개 레이블 + `Feedback`(layer 3)의 닫힌 튜플. 각 항목 `{"label","layer","name_ko"}`.
- `ONTOLOGY_RELATIONSHIPS`: 위 18개 관계 유형 + `ABOUT`(layer 3)의 닫힌 튜플. 각 항목 `{"type","from","to","layer"}`. **끝점(from/to)은 `graph/` 적재 코드(`load.py` `AXES`, `layer1.py`, `layer2.py`, `feedback.py`)의 MERGE 문에서 읽어 정한다**(추측하지 않는다. 한 유형이 여러 끝점 쌍을 가지면 항목을 나눈다).

**3. `api/graph_routes.py`(새)**: `def register_graph(app: FastAPI) -> None`로 위 세 경로를 등록한다.
- `/graph/fragment`: `ids`는 쉼표로 나눈 쿼리 문자열. 헤더 검사 → ids 검증(실패 422 `{"detail": "GRAPH_IDS_INVALID"}`) → `services.graph_fragment`가 `None`이면 503 `GRAPH_UNAVAILABLE` → `asyncio.to_thread`로 조각 조회(예외는 500 `{"detail": "GRAPH_QUERY_FAILED"}`, **예외 메시지·입력 값을 응답·로그에 넣지 않는다**).
- `/graph/schema`: 헤더 검사 후 위 응답. `claims`는 `Claim.other`를 뺀다.
- `/workspaces`: 위 응답(헤더 없음). `workspaces` 값에서 허용 필드만 꺼낸다(나머지 필드는 읽지 않는다).

**4. `api/app.py`**: `Assembly`에 `graph_fragment`·`product_names`를 **기존 필드 뒤에 기본값으로** 더하고 `create_app`에서 `register_graph(app)`을 호출한다. 그 밖의 필드·라우트·`/chat`은 바꾸지 않는다.

**5. `api/assembly.py`**: `Assembly(...)` 생성에 `graph_fragment=`(질의를 `graph_connection.run(fragment_query(), fragment_parameters(ids)).records`로 돌려 `build_fragment`에 넘기는 함수)와 `product_names=product_names`를 더한다. 그 밖의 줄은 바꾸지 않는다.

**6. `graph/evidence_queries.py`**: 위 "근거 카드 분석 속성" 항목의 `creative_labels_query()`·`creative_labels_parameters(ids)`·`card_labels_by_id(rows)`를 **더하기만** 한다(기존 함수·상수·`EXAMPLES` 등 매핑은 바꾸지 않는다).

**7. `api/assembly.py`의 `hydrate`**: 위 규칙대로 라벨을 합친다(라벨 질의 실패는 카드를 막지 않음, 질의는 호출마다 1회, 입력 ID는 이미 `EVIDENCE_ID_PATTERN` 검사를 통과한 것만).

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `tests/test_graph_fragment.py`: (1) `fragment_parameters`: 잘못된 ID·31개·빈 목록·문자열 입력 거부, 중복 제거와 순서 유지. (2) `fragment_query()`가 호출마다 같은 문자열이고 `Feedback`·`tenant`·`ClaimRule`이 없으며 `$ids`·`$limit` 매개변수만 쓴다. (3) `build_fragment`: 합성 행에 **실제 `neo4j.time.DateTime` 객체**를 넣어도 `json.dumps(..., allow_nan=False)`가 통과, 엣지 양 끝이 노드에 있음, 노드 중복 없음, 라벨 없는 소재(분류 축 관계가 없는 행)도 소재 노드로 나옴, `missing` 계산, 알 수 없는 값 타입은 `GRAPH_FRAGMENT_VALUE_INVALID`. (4) 스키마 상수 드리프트 가드: `graph/schema.py`의 모든 `CONSTRAINTS`·`LAYER1_CONSTRAINTS`·`FEEDBACK_CONSTRAINTS`의 레이블이 `ONTOLOGY_LABELS`에 있고, `load.py` `AXES`의 레이블·관계와 `graph/*.py`에서 정규식으로 찾은 `[:관계]`·`[r:관계]` 유형과 `layer1.py`의 관계 문자열 상수가 모두 `ONTOLOGY_RELATIONSHIPS`에 있으며, 위 "측정한 18개"가 전부 들어 있다. 검사한 항목 수가 0이면 실패(B-FP-069).
- `tests/test_api_graph.py`: `tests/test_api_ask.py`의 `services()` 형식 가짜 `Assembly`를 `create_app(lambda: assembly)`로 시작해 (1) 헤더 없음 400·허용 밖 403(`/graph/*`), (2) ids 검증 422, `graph_fragment=None`이면 503, 성공 시 응답 모양, 가짜가 `RuntimeError("PRIVATE")`를 올리면 500 본문에 `PRIVATE`가 없음, (3) **시작한 뒤** `app.state.assembly.graph_fragment`를 바꾸면 다음 요청이 바뀐 것을 부른다(B-FP-070), (4) `/graph/schema`의 `labels`가 `ONTOLOGY_LABELS`와 같고 `taxonomy` 키 집합이 정확히 `{"hook_type","angle","format"}`, `claims`에 `other`가 없음, (5) `/workspaces`: 헤더 없이 200, 항목 키 집합이 정확히 `{"tenant_id","display_name","brand","product_name"}`, `own_product_url`·`tone`·`forbidden_terms`·`price_band_pct` 문자열이 응답 어디에도 없음, `image_enabled`가 `Assembly.image_enabled`를 따름, `tenant_id` 정렬.
- `tests/test_api_assembly.py`: 케이스 추가에 한함: 가짜 서비스로 조립한 `Assembly`에 `graph_fragment`가 호출 가능하고 `product_names`가 워크스페이스 제품명을 담으며, 시작할 때 조각 질의가 나가지 않는다. 기존 단언은 약화·삭제하지 않는다(정확 일치 단언은 기대값에 새 필드만 더하는 갱신만 허용). 카드 라벨: (a) 가짜 그래프가 라벨 행(훅·소구·형식·출연자·CTA·효능 목록)을 주면 `hydrate` 카드에 여섯 키가 그대로 붙는다, (b) 라벨 행이 없거나 값이 `None`이면 `None`·`[]`, (c) **라벨 질의가 예외를 올려도 카드는 정상이고 여섯 키가 `None`·`[]`이며 예외 문자열이 결과에 없다**, (d) 라벨 질의는 `hydrate` 한 번에 한 번이고 매개변수가 카드 ID 목록이다.
- `tests/test_graph_evidence_queries.py`(케이스 추가에 한함): `creative_labels_query()`가 호출마다 같은 문자열이고 읽기 전용(`CREATE`·`MERGE`·`SET`·`DELETE`가 없음)이며 `Feedback`·`tenant`가 없고 `$ids`만 쓴다, `creative_labels_parameters`가 잘못된 ID·31개·빈 목록을 거부, `card_labels_by_id`가 라벨 없는 소재(모든 값 `None`)·`claims` 여러 값·다른 소재 행을 섞지 않는 것을 검사한다. 합성 값만 쓴다.
- 합성 문장·분류 값을 기대값으로 굳히지 않는다.

## Acceptance Criteria

```bash
make verify   # lint + test 통과
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

- 이 경로들을 에이전트 도구(`agents/tools.py` 등록 목록)나 모델이 부를 수 있는 곳에 연결하지 마라. 질의 문자열에 `$ids` 외 입력을 보간하지 마라. 이유: 에이전트에게 Cypher를 쓰게 하지 않고 고수준 도구만 준다(AGENTS.md), 입력 보간은 주입 통로다.
- **그래프 조각(`/graph/fragment`)**에 `Feedback`·`ClaimRule`·테넌트 전용 **데이터**를 넣지 마라(스키마 `/graph/schema`는 레이블·관계 **이름** 메타데이터만이라 `ONTOLOGY_LABELS`에 `Feedback`·`ClaimRule`이 이름으로 있어도 된다. 데이터·속성 값은 내보내지 않는다). `/workspaces`에 `own_product_url`·`tone`·`forbidden_terms`·`price_band_pct`를 내보내지 마라. 이유: 테넌트 전용 데이터는 이 경로로 나가지 않는다(ADR-009).
- `Assembly.graph`를 Neo4j 연결로 쓰지 마라. 새 필드 `graph_fragment`만 쓰고 경로는 요청 시점에 `request.app.state.assembly`에서 읽어라. 이유: 이 필드는 LangGraph 그래프이고, 생성 시점 값을 붙잡으면 시작 때 교체한 가짜를 못 부른다(B-FP-070).
- 합성 문자열 값만으로 조각 변환을 테스트하지 마라(실제 `neo4j.time.DateTime`을 쓴다). 알 수 없는 값 타입을 조용히 버리지 마라. 이유: 합성 값 테스트가 드라이버 값 타입의 직렬화 실패를 못 잡았다(FP-C03 추가 사례).
- 카드 라벨 질의 실패를 카드 오류로 올리지 마라. 라벨이 없는 소재를 오류·누락으로 처리하지 마라. 이유: 라벨은 부가 정보이고 분석된 소재만 라벨이 있다(그래프 1,172/7,429). 동결 CQ 질의와 기존 `evidence_queries.py` 질의 문자열은 바꾸지 마라(동결 가드).
- 오류 응답·로그에 예외 메시지·질의·입력 ID 원문을 넣지 마라. 기존 `ask`·`feedback`·`chat` 라우트와 `ask_view.py`를 수정하지 마라. 이유: 드라이버·DB 오류에는 자격 증명이나 값이 섞일 수 있다(FP-C13). 화면 명령 계약 변경은 step 3의 범위다.
