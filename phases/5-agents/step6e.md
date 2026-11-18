# Step 6e: compare-diagnostics

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`domain`은 표준 라이브러리·pydantic만, `agents`, `eval`), CRITICAL 규칙(모델이 만든 값을 기대값으로 굳히지 않기, 비밀 값, LangGraph 상태 dict·기본 타입)
- `/docs/CONTRACTS.md` — "OpenAI Structured Outputs strict 스키마 규칙(2026-11-18 조회)" 행(공식 문서에서 확인한 규칙과 조회 날짜)과 "LiteLLM SDK 경유" 절
- `/src/beautyads/domain/research.py`, `/src/beautyads/agents/research.py`, `/src/beautyads/agents/planning.py`, `/src/beautyads/agents/evaluation.py`, `/src/beautyads/agents/skeleton.py`, `/src/beautyads/llm/structured.py`, `/src/beautyads/eval/p5_compare.py`, `/src/beautyads/eval/live_agent.py`(오류 출력 방식의 선례), `/tests/test_research_domain.py`, `/tests/test_research_agent.py`, `/tests/test_planning.py`, `/tests/test_p5_compare.py`, `/tests/test_llm_param_guard.py`, `/tests/test_architecture.py` — step 5·6b·6d 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/research.py`, `src/beautyads/agents/research.py`, `src/beautyads/eval/p5_compare.py`, `tests/test_research_domain.py`, `tests/test_research_agent.py`, `tests/test_p5_compare.py`, `tests/test_schema_guard.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/research.py`(`AggregateItem`·`aggregates_from_items` 추가와 `ResearchHandoffDraft.aggregates`의 형태 변경, 필드 설명 추가에 한함. `ResearchHandoff`의 칸·타입·기존 함수 불변), `src/beautyads/agents/research.py`(`finalize`에서 초안의 항목 목록을 `ResearchHandoff.aggregates` 딕셔너리로 바꾸는 부분에 한함, 하위 그래프 상태 키·근거 풀 제한·상태 판정·`result_counts` 불변), `src/beautyads/eval/p5_compare.py`(실패 출력·결과 json의 `error` 칸 추가에 한함, 판정·상한·해시·저장 규칙·기존 종료 코드 불변), `tests/test_research_domain.py`(합성 값의 `aggregates`를 딕셔너리에서 항목 목록 형태로 바꾸는 갱신과 케이스 추가에 한함. 갱신한 줄은 합성 값의 형태만 바꾸고 단언 약화·삭제는 금지), `tests/test_research_agent.py`(합성 값의 `aggregates` 형태 갱신과 케이스 추가에 한함. 85행의 모델 초안 합성 값 `{"n": 1}`과 `model_draft["aggregates"].update(model_counts)` 부분을 항목 목록 형태로 바꾸는 갱신만 허용하고 그 밖의 단언 약화·삭제는 금지), `tests/test_p5_compare.py`(합성 초안의 `aggregates` 형태 갱신과 케이스 추가에 한함, 단언 약화·삭제 금지), `tests/test_schema_guard.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

첫 `make live-compare ARGS='inputs'`가 `COMPARE_FAILED`로 실패했다(litellm 예외, 청구된 호출 1건, 오류 코드·예외 클래스가 출력에 없었다). 오프라인 진단(2026-11-18, 네트워크·모델 호출 없음): 리서치 `finalize`가 구조화 스펙에 `ResearchHandoffDraft.model_json_schema()`를 그대로 넘기는데 이 스키마의 `aggregates`가 `{"type":"object","additionalProperties":true}`(속성 없는 자유 형식 객체)다. OpenAI Structured Outputs strict 규칙은 "`additionalProperties: false` must always be set in objects"와 "all fields must be `required`"이므로 위반이다(`strict_plan_schema()`로 변환하는 기획 스키마는 위반이 없다). 이 step은 (a) `p5_compare` 실패 출력에 오류 코드와 예외 클래스 이름을 남기고, (b) 초안의 `aggregates`를 strict 호환 형태로 바꾸고, (c) 같은 유형을 호출 전에 잡는 오프라인 검증기를 만든다. 모델·네트워크는 쓰지 않는다. **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다(수정 전 코드로 새 검증기 테스트가 `ResearchHandoffDraft` 스키마에서 실패함을 먼저 확인한 뒤 통과시킨다).**

**(a) `eval/p5_compare.py` 에러 가시성**(`eval/live_agent.py`와 같은 방식): 하위 명령 실행 중 예상 밖 예외로 실패하면 터미널에 `COMPARE_FAILED`에 이어 `error_code=<코드>`(예외에 문자열 `code` 속성이 있고 `^[A-Za-z0-9_:]{1,64}$`에 맞을 때만)와 `detail=<예외 클래스 이름>`을 출력하고(예외 메시지·인자·`__cause__` 문자열·키·값은 출력하지 않는다), 결과 json의 실패 기록에 같은 두 칸을 `error: {"code": ..., "detail": ...}`로 남긴다(`code`가 없으면 `null`). 기존 종료 코드와 `complete: false` 기록은 바꾸지 않는다. 합성 비밀을 메시지·인자에 담은 예외로 출력·json에 그 비밀이 없음을 테스트한다.

**(b) `domain/research.py`**: `AggregateItem`(`name: str`, `value: str`, `extra="forbid"`)을 추가하고 **`ResearchHandoffDraft.aggregates`를 `list[AggregateItem]`로 바꾼다**(자유 형식 딕셔너리 금지). 순수 함수 `aggregates_from_items(items) -> dict[str, str]`: 같은 `name`이 여러 번이면 **첫 항목만** 쓰고(나중 항목은 버린다), 빈 목록은 `{}`다. `ResearchHandoff.aggregates`의 타입·기존 칸은 바꾸지 않는다(기획 입력·결과 계약 불변: 값은 문자열이 될 수 있다). **`ResearchHandoff.aggregates`와 `ResearchHandoffDraft.aggregates`의 필드 설명(`Field(description=...)`)에 "모델이 작성한 값이며 검증된 수치가 아니다"를 적는다.** 모델이 채우는 칸 이름 집합(`set(ResearchHandoffDraft.model_fields)`)은 바뀌지 않는다.

**`agents/research.py`**: `finalize`가 구조화 결과의 `aggregates` 항목 목록을 `aggregates_from_items`로 딕셔너리로 바꿔 `ResearchHandoff.aggregates`를 채운다. 스키마는 `ResearchHandoffDraft.model_json_schema()`를 쓰되 strict 호환이 되도록 이 step이 만든 형태(항목 목록, 각 객체에 `additionalProperties: false`·모든 속성 `required`)를 만족해야 한다(필요하면 기획 쪽 `strict_plan_schema`와 같은 변환을 적용한다. 단 `agents/planning.py`는 이 step의 수정 대상이 아니므로 변환 함수를 import하지 않고, 필요한 변환이 있다면 `agents/research.py` 안에 같은 모양의 작은 함수를 둔다). 도구 출력에 없는 수치를 `unresolved`로 옮기는 코드 검증은 **이 step에서 하지 않는다**(step 7 설계 요구사항).

**(c) 오프라인 검증기 `tests/test_schema_guard.py`**(새 파일, 가짜 `chat`·가짜 `structured`·가짜 그래프만, 네트워크 없음):
- **OpenAI Structured Outputs strict 규칙 검증기**(공식 문서 `https://platform.openai.com/docs/guides/structured-outputs`를 2026-11-18에 조회해 확인한 규칙만 구현한다. **규칙을 추측해 더하지 않는다**: 조회 날짜와 출처 주소, 규칙 목록을 테스트 파일 맨 위 주석에 적는다. 문서 자체의 날짜는 페이지에 표시돼 있지 않았다): (1) 루트는 객체이고 `anyOf`를 쓰지 않는다, (2) 모든 객체에 `additionalProperties: false`가 있고 `required`가 모든 속성을 담는다, (3) 객체 속성 총 5,000개 이하·중첩 10단계 이하, 열거값 총 1,000개 이하, (4) `allOf`·`not`·`dependentRequired`·`dependentSchemas`·`if`·`then`·`else`를 쓰지 않는다, (5) `$ref`는 `$defs` 안을 가리킨다(정의·재귀는 지원). 위반은 (경로, 사유) 목록으로 돌려준다.
- **스펙 가드**: 가짜 `structured`가 `generate(spec, ...)`로 받은 `StructuredSpec`을 모아 실제 흐름에서 검증한다: 리서치 `finalize`(`ResearchHandoffDraft`), 기획(`make_plan`의 `Plan`), 평가(`evaluate_plan`의 `EvaluationScores`). 모델이 OpenAI(`gpt-6-luna`·`gpt-6.1-terra`)인 흐름의 스펙은 strict 검증기를 **통과해야 하고**, Anthropic 흐름은 루트가 객체인지만 확인한다. **새 `StructuredSpec(` 호출이 생기면 이 테스트가 실패한다**: `src/beautyads/`의 AST에서 `StructuredSpec(`을 호출하는 모듈 목록을 구해 테스트의 `GUARDED_MODULES`와 같음을 단언한다(목록에 없는 새 모듈이 생기면 실패). **검사한 스펙이 0건이면 실패**한다(공허한 통과 금지). 수정 전 코드에서 리서치 스펙이 위반 `('#/properties/aggregates', ...)`으로 실패한다.
- **검증기 자체 테스트**: 합성 스키마로 위반 각각(자유 형식 객체, `required` 누락, `additionalProperties` 누락·참, 루트가 `anyOf`, 금지 키워드, 깊이 초과, 열거값 초과)을 잡고 올바른 스키마는 통과시킨다.
- **메시지 시퀀스 검증기**(OpenAI chat completions 규칙): `assistant` 메시지의 `tool_calls`에 있는 **모든 `id`에 대해 바로 뒤에 `role: "tool"` 메시지**(`tool_call_id` 일치)가 있고, `tool` 메시지가 대응하는 `tool_calls` 없이 혼자 있지 않으며(고아 금지), 허용 역할은 `system`·`user`·`assistant`·`tool`이다. 검증기 자체 테스트(위반 합성 시퀀스를 잡는다)와 함께, skeleton 흐름과 리서치 흐름에서 가짜 `chat`이 받은 `messages` 호출 인자에 적용한다.
- 기존 `tests/test_llm_param_guard.py`는 건드리지 않는다.

**반드시 있어야 하는 테스트**: 위 검증기·가드와 함께 (1) `aggregates_from_items`(빈 목록, 중복 이름은 첫 항목, 값은 문자열), (2) 초안 스키마가 strict 규칙을 통과하고 모델이 채우는 칸 이름 집합이 불변, (3) `finalize` 결과 `ResearchHandoff.aggregates`가 항목 목록에서 변환된 딕셔너리이고 `result_counts`·상태 판정이 불변, (4) 두 `aggregates` 필드 설명에 "검증된 수치가 아니다"가 있다, (5) `p5_compare` 오류 가시성(합성 비밀 미노출, `code`가 없으면 `null`), (6) `tests/test_architecture.py` 통과(`domain`은 표준 라이브러리·pydantic만).

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

- `aggregates`를 자유 형식 딕셔너리로 되돌리거나 `additionalProperties: true`를 허용하지 마라. 이유: OpenAI strict 규칙 위반이다(공식 문서 2026-11-18 조회: `additionalProperties: false` must always be set). 항목 목록으로 받고 코드가 딕셔너리로 바꾼다.
- strict 규칙을 문서에서 확인한 것 외에 추측해 검증기에 넣지 마라. 이유: 확인하지 않은 규칙으로 정상 스키마를 막거나 위반을 놓칠 수 있다(FP-C01). 조회 날짜와 출처를 주석에 적는다.
- 예외 메시지·인자·`__cause__`·키를 `p5_compare` 출력이나 결과 json에 넣지 마라. 이유: 모델·드라이버 예외에 키와 기획안 전문이 들어갈 수 있다(AGENTS.md 비밀 값). 예외 클래스 이름과 안전한 형식의 `code`만 남긴다.
- `agents/planning.py`·`agents/evaluation.py`·`llm/structured.py`를 고치지 마라. 이유: 이 step의 수정 허용 목록 밖이다. 검증기가 그 스키마를 통과하면 되고 위반이 나오면 `blocked`로 보고한다.
- 기존 테스트의 단언을 약화·삭제하지 마라. 변경은 합성 값의 `aggregates` 형태(딕셔너리→항목 목록) 갱신뿐이다. 이유: 결과 계약(`ResearchHandoff.aggregates` 딕셔너리)은 바뀌지 않는다(B-FP-071).
- 도구 출력에 없는 수치를 `unresolved`로 옮기는 검증을 이 step에 넣지 마라. 이유: step 7 설계 요구사항이다. 이 step은 `aggregates`가 모델 작성값이며 검증된 수치가 아님을 필드 설명으로만 표시한다.
