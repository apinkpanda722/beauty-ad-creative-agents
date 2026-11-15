# 프로젝트: beauty-ad-creative-agents

> 이 파일이 에이전트 규칙의 단일 원본이다. Codex는 AGENTS.md를, Claude Code는 이 파일을 import하는 CLAUDE.md를 읽는다.

뷰티 광고 소재를 모아 영상 분석으로 지식그래프(Neo4j)에 넣고, 역할이 나뉜 에이전트(Supervisor·리서치·기획·평가)가 그 그래프를 근거로 기획안을 만든다. 설계 문서는 `docs/`(PRD, ARCHITECTURE, ADR, EVAL, CONTRACTS, TAXONOMY)에 있고, 작업 전에 해당 문서를 읽는다.

## 기술 스택
- Python 3.12 (uv 관리 파이썬만 사용), 패키지 이름 `beautyads`, 소스는 `src/beautyads/`
- FastAPI(SSE), LangGraph, PostgreSQL(원본·체크포인터), Neo4j(그래프, 파생물), Langfuse(관측, compose `obs` profile)
- 모델 호출은 LiteLLM **파이썬 SDK**(proxy 없음). 영상 분석 Gemini, Supervisor·리서치 OpenAI, 기획 OpenAI, 평가 Anthropic (`docs/ADR.md` ADR-005)
- 테스트 pytest(+timeout, xdist), 린트 ruff
- 웹(Next.js)은 M3 phase에서 추가한다. 지금은 `web/`이 없다.

## 계층 경계

`src/beautyads/` 아래 계층. 표의 "import 허용"에 없는 계층은 import하지 않는다. 계층 의존 테스트(`tests/test_architecture.py`)가 이 표와 아래 외부 SDK 표를 AST로 강제한다. 가드 테스트를 약화하지 않는다.

| 계층 | 하는 일 | import 허용 |
|---|---|---|
| `domain` | 소재·라벨·기획안·근거 타입, 분류 값(닫힌 목록), 저장소·조회용 Protocol | 표준 라이브러리, pydantic만 |
| `settings` (루트 모듈) | `.env`를 읽는 유일한 함수 | 표준 라이브러리, pydantic |
| `obs` | trace(JSONL, Langfuse), 비용 원장 기록 | domain, settings |
| `llm` | 모델 호출 래퍼(LiteLLM SDK), 재시도·대기·비용 집계·공급사별 누적액 검사 | domain, settings, obs |
| `sources` | 출처 어댑터(youtube, instagram, tiktok, mfds, mall)가 공통 형식으로 변환 | domain, settings |
| `store` | PostgreSQL 원본(소재, 지표 이력, 모델 출력 원문, 작업 상태, 테넌트 전용 데이터) | domain, settings |
| `graph` | 온톨로지 스키마, 적재, 그래프 탐색 도구 | domain, settings |
| `checks` | 결정론 검사(근거 존재, 금지 표현, 분류 값 유효성). 그래프 조회는 domain의 Protocol로 주입받는다 | domain만 |
| `analysis` | 콘텐츠 유형 선별, 소재 분석, 출력 스키마 검증 | domain, llm |
| `agents` | supervisor, research, planning, evaluation, 상태 정의 | domain, graph, checks, llm, store, obs |
| `api`, `pipeline` | 조립. 모든 런타임 계층을 import해 의존성을 연결한다 | domain~agents 전부(서로·eval 제외) |
| `eval` | 평가셋, 실험 실행기, 채점기 | 다른 모든 계층(api·pipeline 포함). 다른 계층은 eval을 import하지 않는다 |

외부 SDK는 지정한 계층에서만 import한다.

| 패키지 | 허용 계층 |
|---|---|
| `litellm` | `llm` |
| `neo4j` | `graph` |
| `psycopg` | `store`, `api`(LangGraph 체크포인터 조립) |
| `langgraph` | `agents`, `api`(실행 조립) |
| `fastapi` | `api` |
| `httpx` | `sources` |
| `langfuse` | `obs` |

## 아키텍처 규칙
- CRITICAL: 외부 호출은 래퍼 하나를 거친다. 모델 호출은 `llm/` 한 곳에서만(LiteLLM SDK), 출처 API 호출은 각 어댑터만 한다.
- CRITICAL: 비밀 값은 `.env`에서 `settings`의 한 함수로만 읽는다. 미설정·빈 문자열·공백뿐인 값이 기본값을 덮지 않게 한다. 키·토큰·Authorization 헤더를 코드·테스트·문서·로그·trace에 남기지 않는다. `.env`를 열거나 출력하지 않는다. 변수 이름은 `.env.example`에 있다.
- CRITICAL: 실제 API 호출과 다운로드는 사용자가 실행한다. 패키지 설치는 step이 `uv add`로 지시한 패키지만 허용하고 그 밖의 설치·의존성 추가는 금지하며, 설치된 버전은 완료 보고(`summary`)에 적는다. `make verify`는 키·네트워크·실제 서비스 없이 통과해야 한다. 테스트는 가짜 환경과 `tests/fixtures/contracts/`의 응답 원본에서 만든 픽스처만 쓴다.
- CRITICAL: 외부 응답은 `docs/CONTRACTS.md`에 실측된 형태만 전제한다. 키는 없을 수 있다고 보고 읽고(`[]` 직접 접근 금지), 오류는 HTTP 상태를 먼저 본 뒤 본문의 실측된 모든 형태를 받는다. 응답 속 답은 위치가 아니라 `type`으로 찾는다. 문서에 없는 외부 지점은 먼저 실측해 CONTRACTS에 추가한다.
- CRITICAL: 모델이 만든 문장·분류 값을 테스트 기대값으로 굳히지 않는다. 테스트는 형식(스키마, 닫힌 값 목록)과 코드가 하는 일(검증, 재요청, 보류)을 검사한다. 정확도는 평가(E1)에서 잰다.
- CRITICAL: 유료 모델 호출 직전에 공급사별 누적액(`data/manifest/costs.jsonl` 합계)을 검사한다. 상한은 Gemini $12, OpenAI $10, Anthropic $8이고 넘으면 호출하지 않고 멈춘다. 개발 반복의 기본 모델은 `gpt-6-luna`와 `claude-haiku-5-5`이며 공식 구성은 명시적으로 켤 때만 쓴다.
- CRITICAL: 모델 호출에 `temperature`를 지정하지 않는다(추론이 켜진 luna와 haiku는 `UnsupportedParamsError`로 호출 전 거부). luna·terra에서 `reasoning_effort`를 `none`으로 둔 호출에만 예외적으로 줄 수 있고(`docs/CONTRACTS.md`), 평가(haiku)는 줄 수 없다. luna는 추론이 기본으로 켜져 비용이 `reasoning_effort`에 따라 약 100배 달라지므로 에이전트마다 값을 명시하고 비용 원장에 기록한다. 스트리밍 응답은 `response_cost`가 없으므로 `stream_chunk_builder`와 `completion_cost`로 계산한다. 도구 호출 `arguments`는 JSON 문자열이라 파싱 실패를 처리한다.
- CRITICAL: LangGraph 상태에는 dict·기본 타입만 넣고(pydantic 객체 금지), 하위 그래프는 부모와 키를 공유하지 않는 전용 상태 스키마를 쓴다. 체크포인터 풀은 `autocommit=True`·`row_factory=dict_row`·`prepare_threshold=0`으로 만들고, api가 호출 전에 `tenant_id`와 thread 소유 테넌트를 검사한다. 되돌림 횟수는 상태 카운터로 세고 `recursion_limit`은 안전망으로만 쓴다.
- CRITICAL: 모델 호출 재시도는 503·연결 실패·시간 초과에만 한다. 일일 한도 429(`retry-after`가 수 시간)는 재시도하지 않고 배치를 멈춰 남은 소재를 대기 상태로 둔다. 한 소재의 실패는 기록하고 다음으로 넘어간다.
- CRITICAL: `tenant_id`는 세션에서만 나온다. 도구 입력에 테넌트·사용자·오늘 날짜 칸을 두지 않고, 모든 도구가 실행 컨텍스트의 `tenant_id`로 범위를 건다. 검사가 실패하면 요청을 거부한다(ADR-009).
- CRITICAL: PostgreSQL이 원본이고 Neo4j는 거기서 만든 파생물이다. 그래프 적재는 MERGE로 반복해도 결과가 같게 하고, "바뀐 행"은 PostgreSQL의 변경 시각으로 판정한다(그래프 카운터로 판정하지 않는다).
- CRITICAL: 판정할 수 있는 것(근거 ID 존재, 분류 값 유효성, 금지 표현)은 `checks/`가 코드로 판정한다. LLM 채점은 차별성과 요청 적합성에만 쓴다.
- CRITICAL: 영상·이미지 파일은 분석이 끝나면 지우고 저장하지 않는다. 남기는 것은 추출한 사실, 원본 링크, 수집 시각뿐이다. 공식몰은 robots.txt와 요청 간격을 지키고(달바 Crawl-delay 10초) 이미지를 저장·재배포하지 않는다. `data/raw`·`data/interim`은 커밋하지 않는다.
- CRITICAL: `docs/EVAL.md`의 동결된 기준은 결과를 본 뒤 바꾸지 않는다. 결과를 내기 전에 사전 등록 파일을 커밋한다.
- 도메인 로직과 입출력 계층을 분리한다. 에이전트에게 Cypher를 쓰게 하지 않고 분류의 닫힌 값만 받는 고수준 도구를 준다.

## 개발 프로세스
- CRITICAL: 새 기능 구현 시 반드시 테스트를 먼저 작성하고, 테스트가 통과하는 구현을 작성할 것 (TDD)
- CRITICAL: `make verify` 가 유일한 검증 진입점이다. 검증 항목을 추가할 때는 Makefile 의 verify 타깃에 넣는다.
- 커밋 메시지는 conventional commits 형식을 따를 것 (feat:, fix:, docs:, refactor:)
- 실제로 겪은 문제는 `docs/TROUBLESHOOTING_LOG.md`에 적는다.
- 대기 루프는 `pgrep -f`처럼 명령줄 문자열 검색으로 자기 자신을 찾지 않게 PID(`kill -0`)와 완료 신호(`index.json` 상태·로그의 `completed!` 줄)로 확인하고, 상한(timeout)을 둔다.

## 명령어
make verify      # ruff check + ruff format --check + pytest (Stop hook, execute.py, CI가 모두 이 명령을 부른다)
uv run pytest -q # 테스트만
uv run ruff check . && uv run ruff format .   # 린트와 포맷
uv run python scripts/step_file_checks.py phases/<phase>/step*.md   # step 파일 점검
