# Step 6f: json-safe-records

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`neo4j`는 `graph`만, `agents`는 `graph` import 가능), CRITICAL 규칙(모델이 만든 값을 기대값으로 굳히지 않기, LangGraph 상태 dict·기본 타입, 비밀 값)
- `/docs/ARCHITECTURE.md` — "컨텍스트 관리"의 도구 반환 이원화
- `/src/beautyads/agents/tools.py`, `/src/beautyads/agents/tool_messages.py`, `/src/beautyads/agents/research.py`, `/src/beautyads/domain/tools.py`, `/src/beautyads/graph/connection.py`, `/src/beautyads/graph/evidence_queries.py`, `/src/beautyads/eval/p5_compare.py`, `/tests/test_agent_tools.py`, `/tests/test_tool_messages.py`, `/tests/test_research_agent.py`, `/tests/test_p5_compare.py`, `/tests/test_architecture.py` — step 2·1d·5·5a·5b·6d·6e 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/graph/values.py`(새 파일), `src/beautyads/agents/tools.py`, `src/beautyads/agents/tool_messages.py`, `src/beautyads/agents/research.py`, `src/beautyads/eval/p5_compare.py`, `tests/test_graph_values.py`(새 파일), `tests/test_agent_tools.py`, `tests/test_tool_messages.py`, `tests/test_research_agent.py`, `tests/test_p5_compare.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/graph/values.py`, `src/beautyads/agents/tools.py`(도구 반환 경계에서 `to_json_safe`를 호출하는 변환 추가에 한함, 도구 이름·입력·설명·동작·`ToolSpec` 불변), `src/beautyads/agents/tool_messages.py`(알 수 없는 모양을 돌려주는 경로를 명시적 오류 표지로 바꾸고 코드만 로그에 남기는 변경에 한함, 성공 payload의 필드·상한·`shown_count`·데이터 전용 규칙 불변), `src/beautyads/agents/research.py`(읽을 수 없는 도구 결과를 `tool_log`의 `code`로 기록하는 변경에 한함, 하위 그래프 상태 키·근거 풀 제한·상태 판정·`result_counts` 불변), `src/beautyads/eval/p5_compare.py`(`inputs` 결과 행에 `unresolved` 코드 목록 칸 추가에 한함, 판정·상한·해시·저장 규칙·종료 코드 불변), `tests/test_graph_values.py`, `tests/test_agent_tools.py`(케이스 추가에 한함, 기존 단언 변경 0줄), `tests/test_tool_messages.py`(케이스 추가와, 알 수 없는 모양의 기대값 `{"tool": ..., "summary": "결과를 읽을 수 없다"}`를 새 오류 표지(`failure: TOOL_RESULT_UNREADABLE`)로 바꾸는 갱신(208·232·244행 부근)에 한함. 갱신한 줄은 그 기대 dict만 바꾸고 다른 값·조건은 불변이며 단언 약화·삭제는 금지), `tests/test_research_agent.py`(케이스 추가에 한함, 기존 단언 변경 0줄), `tests/test_p5_compare.py`(케이스 추가에 한함, 기존 단언 변경 0줄)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

`make live-compare ARGS='inputs'`가 `COMPARE_FAILED detail=PydanticSerializationError`로 실패했다. 오프라인 재현(2026-11-18, 실제 Neo4j 읽기 전용 조회, 모델 호출 없음): `find_example_creatives`(`graph/evidence_queries.py` `example_query`)와 `ingredient_ad_trend`(동결 CQ-15)의 결과 행에 `published_at`이 **`neo4j.time.DateTime` 객체**로 들어 있고, `ToolResult.model_dump(mode="json")`(`agents/research.py`의 원출력 저장)가 `PydanticSerializationError`로 실패한다. 별개로 `tool_message_content`가 같은 입력에서 예외 없이 "결과를 읽을 수 없다"로 **조용히 대체**한다(1d·6e 테스트가 합성 문자열 값만 써서 못 잡았다). 다른 도구의 열은 전부 `str`·`int`·`float`·`list[str]`이다. 이 step은 도구 반환 경계 **한 곳**에서 Neo4j 값을 JSON 안전한 값으로 바꾸고, 조용한 대체를 명시적 오류 표지로 바꾼다. 모델·네트워크는 쓰지 않는다. **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다(수정 전 코드로 새 회귀 테스트가 `PydanticSerializationError`와 조용한 대체로 실패함을 먼저 확인한 뒤 통과시킨다).**

**`graph/values.py`**(`graph` 계층, `neo4j` import 허용): `to_json_safe(value, *, _depth=0)` 순수 함수. 규칙:
- `None`·`bool`·`int`·`str`은 그대로. `float`은 유한값이면 그대로, `nan`·`inf`는 `"<unserializable:float>"`.
- `neo4j.time.DateTime`·`Date`·`Time`·`Duration`은 각각 `iso_format()`의 문자열(ISO 8601). 시간대가 있으면 그 정보를 유지한다.
- `neo4j.spatial.Point`는 `{"srid": ..., "coordinates": [...]}`. `bytes`·`bytearray`는 `"<unserializable:bytes>"`.
- `neo4j.graph.Node`는 `{"element_id": ..., "labels": 정렬된 목록, "properties": to_json_safe(속성 dict)}`, `Relationship`은 `{"element_id", "type", "start_node_element_id", "end_node_element_id", "properties"}`, `Path`는 `{"nodes": [...], "relationships": [...]}`(모두 JSON dict, 값은 재귀 변환).
- `dict`는 키를 `str`로 바꾸고(문자열이 아닌 키는 `str(key)`) 값을 재귀 변환. `list`·`tuple`은 목록, `set`·`frozenset`은 변환한 값의 `json.dumps` 문자열 기준 **정렬된 목록**(순서 결정적).
- **알 수 없는 타입은 예외 없이 `"<unserializable:타입이름>"` 문자열**로 바꾼다(**값은 노출하지 않는다**, 조용히 `str(value)`로 대체하지 않는다). 재귀 깊이가 20을 넘으면(순환 포함) 같은 표지 `"<unserializable:depth>"`.
- 어떤 입력에서도 예외를 던지지 않는다.

**`agents/tools.py`**: 그래프 결과(`graph.run(...).records`)를 `ToolResult`로 만들기 **직전 한 곳**에서 모든 행(dict)의 값에 `to_json_safe`를 적용한다(조회·집계·비교·근거 확장·인증 도구가 공유하는 경계가 한 곳이면 그 한 곳, 여러 갈래면 공통 함수 하나로 모은다. 새 도구마다 변환하지 않는다). `GraphConnection.run`·동결 질의·`sync`·`cq_verify`의 소비는 바꾸지 않는다. 값이 이미 JSON 안전이면 결과가 변하지 않는다(항등).

**`agents/tool_messages.py`**: 알 수 없는 모양(문자열·목록·알 수 없는 dict·잘못된 필드·순환 값 등)에서 `{"tool": 이름, "summary": "결과를 읽을 수 없다"}`를 돌려주던 경로를 **명시적 오류 표지**로 바꾼다: `TOOL_RESULT_UNREADABLE = "TOOL_RESULT_UNREADABLE"` 상수를 추가하고 payload를 `{"tool": 이름, "failure": "TOOL_RESULT_UNREADABLE", "retryable": False}`(`ToolFailure` payload와 같은 모양)로 한다. `summary`만으로 대체하지 않는다. 이 경로를 탈 때마다 표준 `logging`(`logging.getLogger("beautyads.agents.tool_messages")`)으로 **코드와 도구 이름만** 경고로 남긴다(값·행·메시지 본문·키 없음). 성공 payload의 필드(`row_count`·`shown_count`·`rows`·`evidence_ids`·`truncated`)·상한·데이터 전용 규칙은 바꾸지 않는다.

**`agents/research.py`**: `act`가 도구 결과를 원출력 저장소에 둔 뒤 `tool_result_payload`가 `TOOL_RESULT_UNREADABLE`을 돌려주면 그 호출을 `tool_log`의 `code="TOOL_RESULT_UNREADABLE"`로 기록한다(그러면 기존 코드가 `unresolved`에 `"<도구>: TOOL_RESULT_UNREADABLE"`을 싣는다). 정상 도구의 `tool_log` 항목 모양은 바뀌지 않는다.

**`eval/p5_compare.py`**: `inputs`의 입력별 결과 행에 `unresolved` 코드 목록(핸드오프의 `unresolved` 문자열, 도구 이름과 코드만)을 싣는다. 값·본문은 싣지 않는다.

**반드시 있어야 하는 테스트**(**합성 문자열이 아니라 실제 `neo4j.time.DateTime`·`Date`·`Time`·`Duration` 객체**를 쓴다. 가능하면 실제 `neo4j.graph.Node`·`Relationship`·`Path` 객체도 만든다. 만들 수 없으면 같은 공개 속성(`element_id`·`labels`·`items()` 등)을 가진 대체 객체를 쓰되 테스트 이름에 대체임을 적는다. 모델이 만든 문장·값을 기대값으로 굳히지 않는다):
- `to_json_safe`: 각 neo4j 시간 타입이 ISO 문자열이 되고 `json.dumps`가 통과, 시간대가 있는 `DateTime`이 시간대를 유지, `Point`·`bytes`·`nan`·`inf`·알 수 없는 객체가 표지 문자열(값 미노출: 객체의 `repr`에 합성 비밀을 넣어 결과에 비밀이 없음을 확인), 중첩 dict·list·set 재귀와 set 정렬의 결정성, 문자열이 아닌 dict 키, 순환 구조가 예외 없이 깊이 표지, 항등(이미 안전한 값은 그대로), 어떤 입력에서도 예외 없음.
- **전 경로 회귀(도구 종류별 대표 행으로 파라미터화)**: 가짜 `GraphReader`가 실제 neo4j 객체가 든 행을 돌려줄 때 모든 비표시 도구에서 `run_tool`이 `ToolResult`를 돌려주고 `model_dump(mode="json")`·`model_dump_json()`·`json.dumps(top_rows)`·`tool_message_content`가 모두 통과하며, **`tool_message_content`가 `TOOL_RESULT_UNREADABLE`이 아니라 ISO 문자열 값을 `rows`에 담는다**(조용한 대체가 일어나지 않음). 리서치 흐름(`act` → 원출력 저장소 → `finalize` → 핸드오프)을 실제 neo4j 객체가 든 행으로 돌려 예외 없이 끝나고 핸드오프가 `json.dumps`로 직렬화되며 `unresolved`에 `TOOL_RESULT_UNREADABLE`이 없다. `p5_compare`의 `inputs` 저장 경로(기존 테스트의 주입 지점 사용)를 같은 행으로 돌려 결과 파일과 핸드오프 파일이 만들어지고 읽힌다.
- 명시적 오류 표지: 알 수 없는 모양에서 `tool_message_content`가 `failure: TOOL_RESULT_UNREADABLE`(`summary`만이 아님)을 돌려주고, 로거(`caplog`)에 코드와 도구 이름만 경고로 남으며 행·값·합성 비밀이 로그에 없다. 리서치 `act`가 그 경우 `tool_log.code`와 `unresolved`에 표지를 싣는다(가짜 `tool_runner`가 알 수 없는 모양을 돌려주게 해서 이 경로가 실제로 타는지 확인한다). `p5_compare` 결과 행의 `unresolved`에 도구 이름·코드만 있다.
- 기존 단언: `tests/test_agent_tools.py`·`tests/test_research_agent.py`·`tests/test_p5_compare.py`의 기존 줄 변경 0줄, `tests/test_tool_messages.py`는 알 수 없는 모양 기대 dict만 갱신. `tests/test_architecture.py` 통과(`neo4j`는 `graph`만, `agents`는 `graph.values`만 import).

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

- `GraphConnection.run`이나 동결 질의·`sync`·`cq_verify`의 레코드 소비를 바꾸지 마라. 이유: 같은 레코드를 날짜 객체로 쓰는 소비자가 있다. 변환은 도구 반환 경계 한 곳에서 한다.
- 알 수 없는 타입을 `str(value)`로 조용히 바꾸거나 값을 표지에 넣지 마라. 이유: 값에 키·기획안·본문이 들어갈 수 있고 조용한 대체가 이번 은폐 결함의 형태다. `"<unserializable:타입이름>"`만 쓴다.
- `tool_message_content`의 알 수 없는 모양을 `summary`만으로 대체하는 경로를 남기지 마라. 이유: 모델이 원인을 모른 채 "읽을 수 없다"를 받으면 live에서 조용히 실패한다. `TOOL_RESULT_UNREADABLE` 표지를 모델에 전달하고 코드만 로그에 남긴다.
- 새 도구마다 변환 코드를 따로 넣지 마라. 이유: 같은 결함이 도구가 늘 때마다 반복된다(5a·5b 도구가 이미 같은 경계를 쓴다). 공통 경계 한 곳에서 한다.
- 테스트 값을 합성 문자열 날짜(`"2026-11-18"`)로만 만들지 마라. 이유: 합성 값이 같은 가정을 공유해 실제 SDK 값 타입의 직렬화 실패를 못 잡았다(FP-C03, B-FP-020). 실제 `neo4j.time` 객체를 쓴다.
- 기존 단언을 약화·삭제하거나 `tests/test_agent_tools.py`·`test_research_agent.py`·`test_p5_compare.py`의 기존 줄을 바꾸지 마라. 이유: 변환은 이미 안전한 값에 항등이다. 바뀌는 기대값은 `tests/test_tool_messages.py`의 알 수 없는 모양 세 곳뿐이다(B-FP-071).
