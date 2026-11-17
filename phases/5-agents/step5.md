# Step 5: research-agent

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`agents`는 `domain`·`graph`·`checks`·`llm`·`store`·`obs`), CRITICAL 규칙(LangGraph 상태·하위 그래프 전용 상태, 테넌트, 재시도, `reasoning_effort` 명시·원장 기록)
- `/docs/ARCHITECTURE.md` — "컨텍스트 관리", "도구 설계 규칙", "요청 처리 공통 장치"
- `/docs/PRD.md` — 핵심 기능 5(리서치 에이전트)
- `/docs/CONTRACTS.md` — "LangGraph" 절과 "P5 step 0 시험" 절
- `/src/beautyads/agents/state.py`, `/src/beautyads/agents/skeleton.py`, `/src/beautyads/agents/tools.py`, `/src/beautyads/domain/tools.py`, `/src/beautyads/domain/evidence.py`, `/src/beautyads/llm/chat.py`, `/src/beautyads/llm/structured.py`, `/src/beautyads/llm/prices.py`, `/tests/test_agent_skeleton.py`, `/tests/test_architecture.py` — step 0·0b·1·2·5a 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/research.py`(새 파일), `src/beautyads/agents/research.py`(새 파일), `tests/test_research_domain.py`(새 파일), `tests/test_research_agent.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/research.py`, `src/beautyads/agents/research.py`, `tests/test_research_domain.py`, `tests/test_research_agent.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

리서치 에이전트를 **전용 상태를 가진 LangGraph 하위 그래프**로 만든다. 입력은 Supervisor가 줄 과제 지시서이고 출력은 구조화 핸드오프다. 이 step은 모델·그래프·네트워크를 부르지 않는다(가짜 `chat`·가짜 `tool_runner`·가짜 구조화 생성기만). **이 step 안에서는 실제 접속·실행을 하지 않는다.**

**`domain/research.py`**(표준 라이브러리·pydantic만): 
- `ResearchBrief`(`goal: str`, `category: Category`(`other` 제외), `claim: Claim | None`, `hook_type: HookType | None`, `angle: Angle | None`, `format: Format | None`, `skin_concern: SkinConcern | None`, `output: Literal["patterns", "examples", "both"]`, `max_tool_calls: int = 6`(1~10)). 테넌트·사용자·날짜 칸이 없다(`extra="forbid"`).
- `ResearchStatus`(StrEnum `ok`·`no_evidence`·`failed`), `Confidence`(`low`·`medium`·`high`), `ResearchHandoff`(`status`, `conclusion: str`, `evidence_ids: list[str]`(근거 ID는 **요약 문장 안이 아니라 이 별도 칸**), `aggregates: dict[str, Any]`, `confidence`, `unresolved: list[str]`, `no_evidence_tools: list[str]`(근거가 없었던 도구 이름), `basis_notes: list[str]`(도구 요약의 `category_basis`·"연결된 소재 기준" 주석을 그대로 모은 것), `structured_failure_rate: float | None`).
- 순수 함수 `restrict_evidence_ids(claimed, pool) -> tuple[list[str], list[str]]`: 이번 실행의 도구 결과가 돌려준 ID(`pool`)의 부분집합만 남기고(정렬·중복 제거) 밖의 ID를 따로 돌려준다.
- 모델이 채우는 칸의 스키마(`ResearchHandoffDraft`: `conclusion`, `evidence_ids`, `aggregates`, `confidence`, `unresolved`)는 별도 모델이다. `status`·`no_evidence_tools`·`basis_notes`·`structured_failure_rate`는 **코드가 채운다**(모델이 정하지 않는다).

**`agents/research.py`**(`agents` 계층): 
- 하위 그래프의 **전용 상태 스키마**(`TypedDict`, dict·기본 타입만): `brief`, `tool_log`(도구 이름·결과 요약·ID 개수의 dict 목록), `evidence_pool`(ID 목록), `raw_refs`(원출력 참조 ID 목록), `research_step_count`, `handoff`. **부모 상태(`agents/state.py`)와 키를 하나도 공유하지 않는다**(테스트가 키 집합 교집합 0을 단언). 부모와 하위 그래프 사이는 `run_research(brief: dict, *, ctx: ToolContext, chat, tool_runner, structured, raw_store=None) -> dict`가 변환한다(입력은 지시서 dict, 출력은 핸드오프 dict, 상태를 통째로 넘기지 않는다).
- 노드: (1) `act`: `llm.chat_complete(model="gpt-6-luna", reasoning_effort=RESEARCH_REASONING_EFFORT, tools=<등록 도구 중 display를 뺀 정의>)`(주입된 `chat`)를 부르고 도구 호출이 있으면 `tool_runner`로 실행한다. 상수 `RESEARCH_REASONING_EFFORT = "none"`(명시한다, 원장에 기록된다). 도구 결과는 `raw_store`(요청 단위 저장소, 상태 밖. 기본은 프로세스 안 dict)에 **전체**를 두고 상태에는 참조 ID와 요약·ID 목록만 넣는다. 모델에는 `top_rows`와 요약만 돌려준다(도구 반환 이원화). `research_step_count`가 `max_tool_calls`에 닿으면 도구를 더 부르지 않고 마무리로 간다(`recursion_limit`은 안전망). (2) `finalize`: 주입된 `structured`(`StructuredGenerator`, `reasoning_effort`는 step 0 규칙대로 luna `none`)로 `ResearchHandoffDraft`를 만든다(스키마 검증, 재요청 1회).
- **코드가 하는 일(모델이 하지 않는다)**: 도구 결과가 모두 `no_evidence`이거나 `evidence_pool`이 비면 모델을 부르지 않고 `status=no_evidence`, `conclusion`은 고정 문장("조건에 맞는 근거 소재가 없다. 근거를 지어내지 않는다.")으로 끝낸다. 그 밖에는 핸드오프의 `evidence_ids`를 `restrict_evidence_ids`로 풀 안으로 제한하고 밖의 ID는 `unresolved`에 사유("근거 풀 밖 ID 제거")와 함께 적는다. 도구 실패(`ToolFailure`)는 `unresolved`에 코드로 적고 다른 도구로 계속한다(예외로 끊지 않는다). 구조화 생성이 끝내 실패하면 예외 없이 `status=failed`, `evidence_ids`는 풀의 정렬된 앞 부분(상한 20), `conclusion`은 고정 문장("구조화 실패로 결론을 만들지 못했다.")으로 돌려준다. `no_evidence_tools`·`basis_notes`는 도구 결과에서 모으고 `structured_failure_rate`는 `StructuredStats`에서 읽는다.
- **테넌트**: `ToolContext`는 호출자가 서버 값으로 준다. 지시서·모델 출력 어디에도 테넌트를 받는 칸이 없다.

**반드시 있어야 하는 테스트**(가짜 `chat`·`tool_runner`·`structured`와 합성 값. 모델이 만든 문장·값을 기대값으로 굳히지 않는다):
- 핸드오프: `restrict_evidence_ids`가 풀 밖 ID를 제거해 `unresolved`로 보낸다(합성 풀), 풀이 비면 결과도 비어 있다, 중복·정렬. `ResearchBrief`에 테넌트·날짜 칸이 없고 `extra`가 거부된다.
- 근거 없음: 모든 도구가 `no_evidence`이면 `structured`가 **불리지 않고** `status=no_evidence`·고정 문장이며 `evidence_ids`가 빈 목록이다(지어내지 않음). 도구 일부만 `no_evidence`이면 `no_evidence_tools`에 이름이 남고 `status=ok`다.
- 도구 실패는 예외 없이 `unresolved`에 코드로 남고 다음 도구로 계속한다. `max_tool_calls`에 닿으면 추가 도구 호출 없이 마무리하고 `research_step_count`가 상한을 넘지 않는다.
- 구조화 실패(가짜 `structured`가 `ok=False`)는 예외가 아니라 `status=failed`다. 모델이 풀 밖 ID를 낸 경우(가짜)에도 최종 핸드오프의 `evidence_ids`는 풀의 부분집합이다.
- 상태: 하위 그래프 상태의 모든 값이 dict·기본 타입이다, 상태 스키마 키 집합과 부모 상태(`agents/state.py`)의 키 집합의 교집합이 비어 있다. 원출력은 상태가 아니라 `raw_store`에만 있고 상태에는 참조 ID만 있다(상태를 직렬화해 크기가 도구 원출력 크기에 비례하지 않음을 단언).
- 모델 호출 인자: `chat`이 `model="gpt-6-luna"`, `reasoning_effort="none"`으로 불리고 도구 정의에 display 도구와 `tenant`·`user`·`date` 칸이 없다. 가짜 `structured`가 받은 `reasoning_effort`도 `"none"`이다.
- `basis_notes`가 도구 요약의 `category_basis` 문구("모델 라벨 기준(E1 채점 전)" 또는 "제품 연결 기준")를 그대로 모은다(합성 요약).
- `tests/test_architecture.py`가 통과한다(`agents`는 `domain`·`graph`·`checks`·`llm`·`store`·`obs`만, `langgraph`는 `agents`·`api`만).

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

- 하위 그래프 상태에 부모 상태 키를 쓰거나 pydantic 객체(`ToolResult`·`ResearchHandoff` 등)를 넣지 마라. 이유: 하위 그래프는 부모와 키를 공유하지 않는 전용 상태 스키마를 쓰고 상태에는 dict·기본 타입만 넣는다(AGENTS.md CRITICAL).
- 근거 0건을 모델이 채우게 하거나 모델이 만든 `evidence_ids`를 검증 없이 쓰지 마라. 이유: 근거 ID는 이번 실행의 도구 결과 안에서만 인정하고 근거가 없으면 "근거 없음"으로 끝낸다(PRD S5, ARCHITECTURE 컨텍스트 관리).
- `status`·`no_evidence_tools`·`basis_notes`를 모델 출력에서 가져오지 마라. 이유: 판정할 수 있는 것은 코드가 판정한다(AGENTS.md CRITICAL).
- 도구 원출력 전체를 모델 입력이나 LangGraph 상태에 넣지 마라. 이유: 원자료는 상태 저장소에 두고 ID로 참조하며 모델에는 요약과 상위 몇 건만 준다(ARCHITECTURE 도구 반환 이원화).
- `reasoning_effort`를 생략하거나 `temperature`를 지정하지 마라. 이유: luna는 추론이 기본으로 켜져 비용이 약 100배 차이난다(AGENTS.md). 값은 상수로 명시하고 원장에 기록된다(step 0).
- 테스트 기대값에 모델이 만든 문장·분류 값을 굳히지 마라. 이유: FP-C03. 합성 도구 결과와 구조(키·상태·호출 인자)만 단언한다.
