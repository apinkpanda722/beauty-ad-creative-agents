# Step 8a: trace-jsonl

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`obs`는 `domain`·`settings`만, `api`는 모든 런타임 계층), CRITICAL 규칙(비밀 값·키·Authorization을 코드·테스트·문서·로그·trace에 남기지 않는다, 테넌트는 세션에서만, 실제 서비스 접속 금지)
- `/docs/ARCHITECTURE.md` — "컨텍스트 관리"의 입력 예산·"요청 처리 공통 장치"의 trace 항목, "멀티테넌트"의 "trace에도 테넌트를 남긴다"(411행 부근), "프롬프트 캐시"(캐시 적중량을 trace에 남긴다)
- `/docs/results/p5_dev_compare_preregistration.md` — §8(StructuredStats 실패 종류·평가 점수 실측 맥락)
- `/src/beautyads/obs/ledger.py`, `/src/beautyads/api/assembly.py`, `/src/beautyads/domain/supervisor.py`, `/src/beautyads/agents/supervisor.py`, `/src/beautyads/agents/plan_eval.py`, `/src/beautyads/llm/structured.py`(`StructuredStats`, `StructuredFailure`), `/src/beautyads/domain/evaluation.py`, `/src/beautyads/domain/research.py`(`ResultCount`), `/tests/test_api_assembly.py`, `/tests/test_ledger.py`, `/tests/test_architecture.py` — step 7a·7d 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/obs/trace.py`(새 파일), `src/beautyads/api/assembly.py`, `.gitignore`, `tests/test_trace.py`(새 파일), `tests/test_api_assembly.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/obs/trace.py`, `src/beautyads/api/assembly.py`(`assemble_full`의 `ask` 래퍼에 trace 기록을 더하고 `trace_path` 인자를 추가하는 데 한함. 기존 인자·반환·동작·모델 호출 모양 불변), `.gitignore`(`data/manifest/traces.jsonl` 한 줄 추가에 한함), `tests/test_trace.py`, `tests/test_api_assembly.py`(케이스 추가에 한함, 기존 단언 변경 0줄. 기존 케이스는 `Settings(ledger_path=tmp_path/…)`를 쓰므로 trace도 임시 폴더에 쓰인다)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

요청 1건 = trace 1줄(JSONL)로 단계·도구·모델 호출·구조화 실패 종류·한도·입력 예산 자름·되돌림 점수 경로를 남기고 테넌트별로 집계하는 **로컬 trace**를 만든다. Langfuse(8b)는 P7로 이월했으므로 이 step에 없다. 이 step은 모델·실제 서비스를 부르지 않는다. **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

**`obs/trace.py`**(`obs` 계층, 표준 라이브러리·pydantic·`beautyads.obs.ledger`만. `llm`·`domain` 밖 타입은 import하지 않는다: 구조화 통계는 순수 dict로 받는다):
- `TraceRecord`(`extra="forbid"`, `allow_inf_nan=False`): `trace_id`(`uuid4().hex`), `tenant_id`, `started_at`(UTC), `duration_ms: int`, `outcome: Literal["ok","error"]`, `error_class: str | None`·`error_code: str | None`(각각 `[A-Za-z0-9_:]{1,64}`만 허용, 아니면 `None`), `kind: str | None`(`research`·`plan`·`out_of_scope`·`no_evidence`·`failed`), `intent: str | None`, `message_chars: int`, `message_trimmed: bool`(**메시지 원문·사유 원문·모델 문장은 trace에 없다**), `steps: list[TraceStep(agent, phase, status)]`, `tools: list[TraceTool(tool, row_count, shown_count)]`(핸드오프 `result_counts`에서), `plans: list[TracePlan]`(`status`, `rework_count`, `unknown_count`, `efficacy_status`(문자열 값만), `attempts: list[TraceAttempt(attempt, passed, scores: dict[str,int] | None, failed_check_codes, cost_usd)]`: **`scores`는 정수 값만 남기고 문자열(사유 등)은 버린다**), `limit_hit: bool`, `limit_kinds: list[str]`, `input_trims: list[{field, kept, total}]`, `aggregates_removed_count: int`, `text_spent_usd: float | None`, `calls: list[TraceCall(purpose, model, reasoning_effort, input_tokens, output_tokens, thought_tokens, cached_tokens, cost_usd, cost_source)]`(원장 항목에서), `cost_total_usd: float`, `cost_by_purpose: dict[str, float]`, `structured: dict[str, TraceStructured(calls, failed_after_retry, first_attempt_failures: dict[str,int])]`(모델 이름 키).
- 순수 함수 `build_trace(*, tenant_id, started_at, duration_ms, message, result, failure, ledger_entries, structured) -> TraceRecord`: `result`는 Supervisor 결과 dict 또는 `None`, `failure`는 `{"class", "code"}` 또는 `None`. `message`는 길이만 센다(`message_chars`, 7a의 `decide_max_chars`를 넘으면 `message_trimmed`). `result`의 알 수 없는 키는 무시하고(누락 키는 기본값) 본문 필드(`brief`·`handoff.conclusion`·기획안 텍스트·`aggregates` 값)는 복사하지 않는다.
- `append_trace(path, record)`: 부모 폴더를 만들고 한 줄을 **한 번의 쓰기**로 덧붙인다(스레드 잠금). `read_traces(path) -> TraceRead(records, skipped_lines)`: 형식이 어긋난 줄은 값을 노출하지 않고 건너뛴다. `summarize_by_tenant(records) -> dict[str, dict]`: 테넌트별 `requests`·`errors`·`calls`·`cost_usd`·`cost_by_purpose`·`first_attempt_failures`(종류별 합)·`structured_calls`.

**`api/assembly.py`**(추가에 한함): `assemble_full`에 `trace_path: Path | None = None`을 더한다(기본값 `settings.ledger_path.with_name("traces.jsonl")`). `ask` 래퍼가 요청 시작 시각(UTC)과 단조 시계를 잡고, 구조화 생성기 래퍼(`_ConfiguredStructured`)를 요청 안에서 만든 것만 목록에 모아 `finally`에서 `build_trace`+`append_trace`를 부른다: 정상이면 `result`, 예외면 `failure={"class": 예외 클래스 이름, "code": 안전한 code 속성}`을 싣고 **원래 예외를 그대로 다시 올린다**. `ledger_entries`는 `read_entries(settings.ledger_path)`에서 `ts >= 요청 시작 시각`인 항목이다(**한계: 동시 요청의 원장 구간이 겹칠 수 있다. 데모는 단일 사용자이고 주석에 적는다**). `structured`는 각 생성기의 `stats`(`calls`·`failed_after_retry`·`first_attempt_failures`)를 모델 이름별로 합친 dict다. **trace 기록의 어떤 실패도 요청 결과·예외를 바꾸지 않는다**(예외는 삼키고 진단을 남기지 않는다). 모델 호출 모양·`ask` 인자·반환값은 바뀌지 않는다.

**`.gitignore`**: `data/manifest/traces.jsonl`을 추가한다(테넌트·비용이 든 로컬 파일이라 커밋하지 않는다).

**반드시 있어야 하는 테스트**(합성 값. 모델 문장·값을 기대값으로 굳히지 않는다):
- `build_trace`: 합성 Supervisor 결과(research·plan·out_of_scope·no_evidence·failed)와 합성 원장 항목에서 위 필드가 구조화 칸 그대로 나온다(숫자·코드·개수 비교). `scores`의 문자열 값이 버려지고 정수만 남는다. **합성 비밀 문자열(`SYNTHETIC-SECRET-…`)을 메시지·`brief`·`conclusion`·기획안 제목·점수 사유·오류 메시지에 넣어도 `record.model_dump_json()`에 없다**(`message_chars`는 길이만). 형식 밖 `error_code`는 `None`이다. 알 수 없는 키가 있어도 실패하지 않고 `extra`는 거부된다(스키마 검증).
- 파일: `append_trace`가 부모 폴더를 만들고 줄마다 JSON이다. **여러 스레드(예: 8개×25줄)가 동시에 써도 모든 줄이 유효한 JSON이고 줄 수가 같다**. `read_traces`가 깨진 줄을 건너뛰고 `skipped_lines`를 센다(값 미노출). 파일이 없으면 빈 결과다.
- `summarize_by_tenant`: 두 테넌트의 합성 레코드가 섞이지 않고 각각의 요청 수·오류 수·호출 수·비용·실패 종류 합이 맞다(합성 값 비교).
- 조립 경유(가짜 모델·가짜 연결, 기존 `tests/test_api_assembly.py`의 장치 사용): `ask` 한 번에 trace가 **정확히 한 줄** 생기고 `tenant_id`가 컨텍스트 값이며 `calls`가 요청 시작 이후 원장 항목뿐이다(요청 전 항목 제외). 이미지 항목(`image-plan`)이 `calls`·`cost_by_purpose`에 있고 `text_spent_usd`에는 포함되지 않는다. 구조화 통계가 모델 이름별로 trace에 있다. 예외를 던지는 가짜 모델이면 `outcome="error"`, `error_class`가 클래스 이름이고 **원래 예외가 그대로 올라온다**. trace 경로가 쓸 수 없는 위치여도 요청 결과가 그대로 반환되고 예외가 없다. 기본 `trace_path`가 원장 폴더의 `traces.jsonl`이다. 기존 `tests/test_api_assembly.py` 단언은 그대로 통과한다.
- `tests/test_architecture.py` 통과(`obs`가 `llm`·`api`·`agents`를 import하지 않는다).

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

- trace에 메시지 원문·사유 원문·모델 문장·키·DSN·파일 경로를 넣지 마라. 이유: 노출 면을 PostgreSQL 한 곳으로 제한하고(ADR-009) 비밀 값은 어디에도 남기지 않는다(AGENTS.md CRITICAL). 길이·개수·코드·종류만 기록한다.
- `obs/trace.py`에서 `llm`·`api`·`agents`를 import하거나 `StructuredStats` 타입을 직접 쓰지 마라. 이유: 계층 경계(`obs`는 `domain`·`settings`만). 통계는 순수 dict로 받는다.
- trace 기록 실패가 요청 결과나 원래 예외를 바꾸게 하지 마라. 이유: 관측은 부수 장치이고 사용자 응답을 막으면 안 된다. 예외는 삼키되 진단 값을 남기지 않는다.
- `ask` 래퍼에서 모델 호출 인자·반환값·`reasoning_effort`를 바꾸지 마라. 이유: 7d까지 검증한 호출 모양이다(FP-C13). trace는 읽기만 한다.
- `traces.jsonl`을 커밋하거나 `data/manifest/costs.jsonl`을 수정·되돌리지 마라. 이유: 비용 원장은 사용자의 실행 기록이다. trace는 gitignore에 둔다.
- 같은 값(필드 목록·키 집합·개수)을 본문과 테스트에서 다르게 적지 마라. 이유: P5 step 7d에서 열 개수 모순으로 blocked됐다(TROUBLESHOOTING 2026-11-18).
