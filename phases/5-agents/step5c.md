# Step 5c: handoff-counts

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`agents`는 `domain`만 import하는 순수 함수와 `llm` 사용 가능), CRITICAL 규칙(판정할 수 있는 것은 코드가 한다)
- `/docs/ARCHITECTURE.md` — "컨텍스트 관리"(도구 반환 이원화, 핸드오프 구조화 칸)
- `/src/beautyads/agents/tool_messages.py`, `/src/beautyads/agents/skeleton.py`, `/src/beautyads/agents/research.py`, `/src/beautyads/domain/research.py`, `/tests/test_tool_messages.py`, `/tests/test_agent_skeleton.py`, `/tests/test_research_agent.py`, `/tests/test_research_domain.py`, `/tests/test_architecture.py` — step 1d·5 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/research.py`, `src/beautyads/agents/tool_messages.py`, `src/beautyads/agents/skeleton.py`, `src/beautyads/agents/research.py`, `tests/test_research_domain.py`, `tests/test_tool_messages.py`, `tests/test_agent_skeleton.py`, `tests/test_research_agent.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/research.py`(`ResultCount`·`count_label` 추가와 `ResearchHandoff`에 `result_counts` 칸 추가에 한함, 기존 칸·함수 불변), `src/beautyads/agents/tool_messages.py`(`shown_count` 필드와 `PARTIAL_RESULT_RULE` 추가에 한함, 기존 필드·상한·동작 불변), `src/beautyads/agents/skeleton.py`(시스템 메시지에 한 줄 추가에 한함), `src/beautyads/agents/research.py`(`result_counts` 채우기와 `_SYSTEM`에 한 줄 추가에 한함, 상태 키·근거 풀·상태 판정 불변), `tests/test_research_domain.py`(케이스 추가에 한함, 단언 약화 금지), `tests/test_tool_messages.py`(`shown_count` 추가에 필요한 기대값 갱신과 케이스 추가에 한함: 기대 dict와 `SUCCESS_KEYS`에 `shown_count`를 더하는 갱신. 갱신한 줄은 기존 기대값에 `shown_count`의 정확한 값 하나만 더하고 `>=`·부분 비교로 바꾸지 않으며, 기존 단언의 다른 값·조건은 불변이고 약화·삭제는 금지), `tests/test_agent_skeleton.py`(`shown_count`와 새 시스템 지시 한 줄 추가에 필요한 기대값 갱신과 케이스 추가에 한함: tool 메시지 `content`의 기대 dict에 `shown_count`를, 시스템 메시지 기대값에 새 지시를 더하는 갱신. 갱신한 줄은 기존 기대값에 새 키·새 지시 하나만 더하고 `>=`·부분 비교로 바꾸지 않으며, 기존 단언의 다른 값·조건은 불변이고 약화·삭제는 금지), `tests/test_research_agent.py`(`shown_count`와 새 시스템 지시 한 줄 추가에 필요한 기대값 갱신과 케이스 추가에 한함: `observations` 기대 dict에 `shown_count`를, 시스템 메시지 기대값에 새 지시를 더하는 갱신. 갱신한 줄은 기존 기대값에 새 키·새 지시 하나만 더하고 `>=`·부분 비교로 바꾸지 않으며, 기존 단언의 다른 값·조건은 불변이고 약화·삭제는 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

두 번째 `make live-agent`에서 도구가 `row_count` 13을 돌려줬는데 모델에는 상위 5건만 전달돼 최종 답이 "조회된 제품은 다음과 같다"로 쓰여 **전체 건수를 밝히지 않았다**. 이 step은 (1) 모델 지시문에 "일부만 보여줄 때는 전체 건수와 표시 건수를 함께 말한다"를 넣고, (2) 전체 건수·표시 건수를 **코드가 구조화 칸으로** 핸드오프에 싣고(문자열 매칭에 의존하지 않는다), (3) 화면용 "N건 중 M건 표시" 문구를 코드가 만드는 순수 함수를 만든다. 모델 호출·네트워크는 쓰지 않는다. **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

**`agents/tool_messages.py`**: `tool_result_payload`에 `shown_count`(= 실제로 `rows`에 담은 행 수, `row_count`와 별도 필드)를 추가한다(기존 `row_count`·`rows`·`truncated` 필드·상한은 그대로). 상수 `PARTIAL_RESULT_RULE = "결과 중 일부만 보여줄 때는 전체 건수와 표시 건수를 함께 말한다."`를 추가한다.

**시스템 지시**: `agents/skeleton.py`의 시스템 메시지(`TOOL_DATA_RULE`)와 `agents/research.py`의 `_SYSTEM`에 `PARTIAL_RESULT_RULE` 한 줄을 더한다(같은 상수를 쓴다. skeleton은 두 문장을 한 시스템 메시지로 이어서 보내고, 저장 상태 `messages`에는 넣지 않는 기존 규칙을 유지한다).

**`domain/research.py`**: `ResultCount`(`tool: str`, `row_count: int`, `shown_count: int`, `truncated: bool` = `shown_count < row_count`)를 추가하고 `ResearchHandoff`에 `result_counts: list[ResultCount]`를 추가한다(기본 빈 목록. **모델이 채우는 `ResearchHandoffDraft`에는 넣지 않는다**: 코드가 채운다). 순수 함수 `count_label(row_count: int, shown_count: int) -> str`: 같으면 `"N건"`, 표시가 적으면 `"N건 중 M건 표시"`(N은 전체, M은 표시), 음수·`shown_count > row_count`는 `ValueError`. 화면(step 7)과 평가 결과가 이 함수를 쓴다.

**`agents/research.py`**: 도구를 실행할 때마다 `tool_log`의 항목에 `row_count`와 `shown_count`를 dict·기본 타입으로 기록하고(`shown_count`는 `tool_result_payload`와 같은 규칙: `min(row_count, MAX_ROWS)`와 실제 행 수 중 작은 값), `finalize`에서 `result_counts`를 만들어 최종 핸드오프에 싣는다(같은 도구를 여러 번 부르면 호출 순서대로 항목이 따로 있다. `ToolFailure`·표시 도구는 넣지 않는다). 하위 그래프 상태 키 목록은 바꾸지 않는다(`tool_log` 항목의 필드만 늘어난다).

**반드시 있어야 하는 테스트**(합성 결과, 모델 문장을 기대값으로 굳히지 않는다):
- `tool_result_payload`: 행이 5개를 넘는 합성 결과에서 `shown_count == 5`이고 `row_count`는 전체다. 행이 적으면 같다. 기존 1d 테스트가 그대로 통과한다.
- `count_label`: `(13, 5)` → `"13건 중 5건 표시"`, `(3, 3)` → `"3건"`, `(0, 0)` → `"0건"`, 잘못된 입력은 `ValueError`(정확한 문자열은 이 순수 함수의 계약이라 단언한다. 모델 문장이 아니다).
- 시스템 지시: skeleton이 모델 호출마다 보내는 첫 메시지(가짜 `chat`이 받은 `messages` 인자를 직접 검사)와 research의 시스템 메시지에 `PARTIAL_RESULT_RULE`이 들어 있고, 저장 상태 `messages`에는 없다.
- research: 합성 도구 결과(행 7개, 5개 표시)에서 최종 핸드오프의 `result_counts`가 `[ResultCount(tool, 7, 5, True)]`이고 **모델 초안(가짜 `structured`)이 건수를 틀리게 써도(또는 쓰지 않아도) `result_counts`는 코드가 만든 값**이다. `ToolFailure`와 표시 도구는 `result_counts`에 없다. 근거 0건 경로(`no_evidence`)는 `result_counts`에 `row_count 0, shown_count 0`이 들어간다.
- `tests/test_architecture.py`가 통과한다.

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

- 전체 건수·표시 건수를 모델이 쓴 문장에서 읽거나 문자열 매칭으로 검증하지 마라. 이유: 판정할 수 있는 것은 코드가 한다(AGENTS.md CRITICAL). 도구 결과의 `row_count`·`rows` 길이에서 코드가 만든 구조화 칸만 믿는다.
- `result_counts`를 `ResearchHandoffDraft`(모델이 채우는 칸)에 넣지 마라. 이유: 건수는 코드가 정한다. 모델이 건수를 지어내거나 틀리게 쓸 수 있다.
- 하위 그래프 상태 키 목록을 바꾸거나 pydantic 객체를 상태에 넣지 마라. 이유: 전용 상태 스키마와 dict·기본 타입 규칙(AGENTS.md CRITICAL). 항목 필드만 늘리고 직렬화한 dict를 쓴다.
- 모델 문장 전체나 "조회된 제품은 다음과 같다" 같은 표현을 테스트 기대값으로 굳히지 마라. 이유: FP-C03. 구조(`result_counts`, 시스템 메시지의 지시 상수 포함 여부)만 단언한다.
