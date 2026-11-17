# Step 2: tool-registry

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙(테넌트, 도구 입력, Cypher 금지)
- `/docs/ARCHITECTURE.md` — "도구 설계 규칙", "스트리밍 이벤트와 화면 명령", "요청 처리 공통 장치"(프롬프트 캐시), "멀티테넌트", "컨텍스트 관리"의 도구 반환 이원화
- `/docs/ADR.md` — ADR-009(테넌트), ADR-012
- `/docs/COMPETENCY_QUESTIONS.md` — v1과 "질문별 현재 상태"(연결된 소재 기준 주석)
- `/tests/test_architecture.py` — 계층 가드
- `/src/beautyads/graph/queries.py`, `/src/beautyads/graph/connection.py`, `/src/beautyads/domain/labels.py`, `/src/beautyads/domain/skin.py`, `/tests/test_graph_queries.py` — step 구현의 입력(동결된 질의와 닫힌 값)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/tools.py`(새 파일), `src/beautyads/agents/__init__.py`(새 파일), `src/beautyads/agents/tools.py`(새 파일), `tests/test_agent_tools.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/tools.py`, `src/beautyads/agents/__init__.py`, `src/beautyads/agents/tools.py`, `tests/test_agent_tools.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

리서치 에이전트가 쓸 **그래프 도구 등록 목록**을 만든다. 도구는 동결된 CQ v1 질의(`graph/queries.py`의 `QUESTIONS`)를 고수준으로 감싼 것이고 **새 Cypher를 만들지 않는다**. 이 step은 모델을 호출하지 않으며 LangGraph도 쓰지 않는다(도구를 에이전트에 붙이는 것은 step 5). **이 step 안에서는 실제 접속·실행을 하지 않는다.**

**`domain/tools.py`**(표준 라이브러리·pydantic만): `ToolKind`(StrEnum: `lookup`·`aggregate`·`compare`·`display`), `PriceBand`(`price_min`, `price_max`, 둘 다 float), `ToolContext`(frozen: `tenant_id: str`, `as_of: date`, `last_collected_at: datetime | None`, `price_band: PriceBand | None`), `ToolErrorCode`(StrEnum: `TENANT_CONTEXT_MISSING`·`TOOL_UNKNOWN`·`INPUT_INVALID`·`GRAPH_UNAVAILABLE`·`PRICE_BAND_MISSING`·`TOOL_INTERNAL_ERROR`), `ToolFailure`(`code`, `retryable: bool`, `message: str`), `UiCommand`(`kind`: `show_evidence_cards`·`show_graph_fragment`·`show_distribution`·`show_plan`, `data: dict`), `ToolResult`(`tool`, `kind`, `summary: str`, `top_rows: list[dict]`(최대 5), `row_count: int`, `evidence_ids: list[str]`, `no_evidence: bool`, `linked_creative_count: int | None`, `ui_command: UiCommand | None`), `EVIDENCE_ID_PATTERN = r"^[a-z]+:[A-Za-z0-9_-]{1,64}$"`(근거 소재 ID 형식 상수. 2026-11-17 읽기 전용 조회로 Neo4j `Creative` 7,429건(youtube 1,566·instagram 3,235·tiktok 2,628)의 `source + ':' + source_id`가 전부 이 형식임을 확인했다: `source`는 소문자, YouTube ID에는 `-`·`_`가 있고 `:`·공백은 없다), 그래프 조회용 `Protocol` `GraphReader`(`run(query, params) -> 결과(.records 목록)`; `GraphConnection`이 만족한다).

**`agents/tools.py`**: `ToolSpec`(frozen dataclass: `name`, `kind`, `description`, `input_model`(pydantic, `extra="forbid"`), `question_id: str | None`). `TOOLS: tuple[ToolSpec, ...]`은 **이름순 고정**이다. 함수: `tool_definitions() -> list[dict]`(각 `{name, description, parameters}`, `parameters`는 입력 모델의 JSON 스키마, 정렬된 고정 순서, 시각·ID·날짜가 들어가지 않는다), `get_tool(name) -> ToolSpec | None`, `run_tool(name: str, arguments: Mapping | str, ctx: ToolContext | None, graph: GraphReader) -> ToolResult | ToolFailure`.

등록할 도구(질의 ID는 `QUESTIONS`의 키, 입력은 그 질의 `inputs`에 있는 닫힌 값만 받는다):

| 이름 | 종류 | 질의 | 모델 입력 |
|---|---|---|---|
| `lookup_products_by_efficacy` | lookup | CQ-01 | `category`(`other` 제외), `claim` |
| `lookup_products_by_concern` | lookup | CQ-02 | `category`(`other` 제외), `concern` |
| `lookup_certified_products` | lookup | CQ-03 | 없음 |
| `count_claim_supported_ads` | aggregate | CQ-04 | `category`(`other` 제외), `claim` |
| `top_claims_of_ingredient_ads` | aggregate | CQ-05 | 없음 |
| `ad_angles_formats_by_skin_type` | aggregate | CQ-08 | `skin_type` |
| `ingredient_ad_trend` | aggregate | CQ-15 | 없음 |
| `compare_hooks_by_category` | compare | CQ-06 | 없음 |
| `compare_competitor_claims` | compare | CQ-13 | 없음 |
| `unclaimed_efficacy_gaps` | compare | CQ-14 | 없음 |
| `compare_price_band_competitors` | compare | CQ-16 | 없음(가격대는 `ctx.price_band`에서만 온다) |
| `show_evidence_cards` | display | — | `evidence_ids`(최대 20개, 각각 `EVIDENCE_ID_PATTERN`에 맞는 문자열) |
| `show_graph_fragment` | display | — | `evidence_ids`(같은 규칙) |
| `show_distribution` | display | — | `axis`(`hook_type`·`angle`·`format`·`claim`·`category` 중 하나, 닫힌 값), `evidence_ids` |
| `show_plan` | display | — | `plan_id`(비어 있지 않은 문자열) |

동작 규칙:
- **테넌트 fail-closed**: `run_tool`의 첫 동작은 `ctx`가 `None`이거나 `tenant_id`가 비었거나 공백뿐인지 검사하는 것이고, 그렇다면 `TENANT_CONTEXT_MISSING`(재시도 불가)으로 돌려준다. 이 검사 전에는 그래프를 부르지 않는다. 도구 입력 모델에는 테넌트·사용자·날짜·시각 칸이 없고(`extra="forbid"`라 모델이 이름을 지어내도 `INPUT_INVALID`), `as_of`·`price_band`는 `ctx`에서만 읽는다.
- `arguments`가 문자열이면 JSON으로 파싱한다(도구 호출 `arguments`는 JSON 문자열이며 `docs/CONTRACTS.md`). 파싱 실패와 스키마 위반은 `INPUT_INVALID`다. 예외를 호출자에게 던지지 않는다. 모르는 이름은 `TOOL_UNKNOWN`.
- 질의 실행은 `graph.queries.question_parameters`로 파라미터를 만들고(`as_of`는 `ctx.as_of`, `context`는 `{"tenant_id": ctx.tenant_id, ...}`에 CQ-16일 때만 `price_min`·`price_max`를 `ctx.price_band`에서 채운다) `graph.run(spec.cypher, params)`를 한 번 부른다. CQ-16 도구에서 `ctx.price_band`가 없으면 그래프를 부르지 않고 `PRICE_BAND_MISSING`(재시도 불가)이다.
- 그래프 오류는 `GraphError`의 `code`가 `NEO4J_UNREACHABLE`이면 `GRAPH_UNAVAILABLE`(재시도 가능), 그 밖의 `GraphError`는 `GRAPH_UNAVAILABLE`(재시도 불가). 예상 밖 예외는 `TOOL_INTERNAL_ERROR`이고 메시지에는 예외 타입 이름만 넣는다(값·키·질의 본문을 넣지 않는다). **그래프 오류는 `no_evidence`가 아니다**(조회가 중단된 것과 답이 없는 것을 구분한다, FP-C05).
- 결과 가공(조회·집계·비교 도구): 모델에는 `top_rows`(앞 5행)와 `row_count`, `summary`만 준다. `evidence_ids`는 행의 `creative_ids`(목록)·`creative_id`(문자열) 키에서 모은 중복 없는 정렬 목록(최대 50개)이며 요약 문장 안이 아니라 이 별도 칸으로만 넘긴다. 행이 0이면 `no_evidence=True`이고 `summary`는 "근거 없음"이 사실만 밝히며 이유를 추측하지 않는다. `PROMOTES`를 거치는 도구(CQ-04·05·06·08·13·14·15·16)는 `linked_creative_count`에 `evidence_ids` 수를 넣고 `summary`에 "연결된 소재 기준" 주석을 붙인다. 이 도구 집합은 상수 하나로 정의한다.
- 표시 도구는 그래프를 부르지 않는다. `UiCommand`(종류, 입력 데이터)를 만들어 `ui_command`에 담고, 모델용 `summary`는 "표시 명령을 보냈다"는 사실만이다(데이터를 되돌려주지 않는다). 테넌트 값은 명령 데이터에 넣지 않는다(서버가 세션에서 처리한다).
- 도구 설명(`description`)은 한국어 두 줄이다: `쓰는 때:`와 `쓰지 않는 때:`를 각각 적는다. 입력 칸마다 `Field(description=...)`을 단다. 도구 목록은 이름순 고정이고 정의에 시각·ID·날짜를 넣지 않는다(프롬프트 캐시 앞부분).

**반드시 있어야 하는 테스트**(`tests/test_agent_tools.py`, 가짜 `GraphReader`와 합성 records만, 도구 수·행 수를 `== N`으로 단언하지 않는다):
- 등록 목록: 이름이 중복 없이 정렬돼 있고, 모든 `ToolKind`가 하나 이상 쓰이며, 모든 `description`에 `쓰는 때:`와 `쓰지 않는 때:`가 있고, 모든 입력 모델이 `extra="forbid"`이며 JSON 스키마의 모든 속성에 `description`이 있다. `tool_definitions()`를 두 번 부르면 같고 `tenant`·`user`·`date`·`today`·`time` 이름을 가진 칸이 어느 도구에도 없다.
- 도구 이름에서 질의 ID를 거쳐 `QUESTIONS`의 같은 `inputs`를 쓴다(입력 칸 이름 집합이 해당 질의의 `inputs`와 같다).
- 닫힌 값 밖 입력(`category="other"`, 모르는 `claim`)은 `INPUT_INVALID`이고 그래프가 불리지 않는다. 테넌트·날짜 칸을 지어낸 인자는 `INPUT_INVALID`다. JSON 문자열 인자 파싱 실패도 `INPUT_INVALID`다.
- `ctx=None`, 빈 `tenant_id`, 공백 `tenant_id`는 모든 도구에서 `TENANT_CONTEXT_MISSING`이고 그래프(호출하면 실패하는 가짜)가 불리지 않는다.
- 가짜 `GraphReader`가 `GraphError("NEO4J_UNREACHABLE")`를 던지면 `GRAPH_UNAVAILABLE`·`retryable=True`이고 `no_evidence`가 아니다. 빈 records는 `no_evidence=True`다. 다른 예외는 `TOOL_INTERNAL_ERROR`이고 메시지에 예외 값이 없다.
- 행이 5개보다 많은 합성 결과에서 `top_rows`가 5행이고 `row_count`는 전체이며 `evidence_ids`가 중복 없는 정렬 목록이다. `PROMOTES` 도구에는 `linked_creative_count`와 주석이 있고 CQ-01·02·03 도구에는 없다.
- `compare_price_band_competitors`: `ctx.price_band`가 없으면 `PRICE_BAND_MISSING`이고 그래프가 불리지 않으며, 있으면 가짜가 받은 `params["context"]`에 `price_min`·`price_max`와 `tenant_id`가 있다.
- 표시 도구는 그래프를 부르지 않고 `ui_command.kind`가 네 값 중 하나이며, `summary`에 입력 데이터가 들어 있지 않다. `evidence_ids`가 21개이거나 형식이 틀리면 `INPUT_INVALID`다. `-`·`_`가 들어간 YouTube 형식 ID(합성)는 통과한다.
- `tests/test_architecture.py`가 통과한다(`agents`는 `domain`·`graph`만 import하고 `langgraph`·`litellm`을 import하지 않는다).

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
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약(설치한 패키지 버전 포함)"`
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

- `src/beautyads/graph/queries.py`를 고치거나 `agents/`에 Cypher 문자열을 쓰지 마라. 이유: CQ v1이 동결돼 있고 에이전트에게 Cypher를 쓰게 하지 않는다(AGENTS.md).
- 도구 입력에 테넌트·사용자·날짜·시각 칸을 두지 마라. 이유: `tenant_id`는 세션에서만 나오고 날짜는 서버가 푼다(ADR-009, 요청 공통 장치).
- 그래프 오류와 빈 결과를 같은 값으로 합치지 마라. 이유: 중단을 "없음"으로 확정한 실패가 있었다(FP-C05). 오류는 `ToolFailure`, 빈 결과만 `no_evidence`다.
- 테스트 기대값에 실제 그래프나 모델이 만든 값·문장을 굳히지 마라. 합성 records만 쓰고 도구 수·행 수를 `== N`으로 단언하지 마라. 이유: FP-C03, B-FP-061.
- 도구 정의에 시각·ID·날짜를 넣거나 순서를 바꾸지 마라. 이유: 도구 정의는 프롬프트 캐시 앞부분이라 매번 같아야 한다(ARCHITECTURE 요청 공통 장치).
- `GraphError` 밖 예외의 메시지에 값·키·질의 본문을 넣지 마라. 이유: 키와 질의 값이 로그·trace에 남지 않아야 한다(AGENTS.md 비밀 값).
