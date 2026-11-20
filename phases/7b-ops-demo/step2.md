# Step 2: trace-time

## 설계 검토 기록

**배경(P7 승인 추가 요구 3-a·3-d, 7b의 8a)**: 채용관이 구성도가 아니라 실제 워크플로를 판단할 수 있도록 **단계별·호출별 소요 시간이 Langfuse에서 타임라인으로 보여야 한다**(사용자 결정). 지금 `TraceRecord`에는 시간 정보가 요청 전체 `started_at`·`duration_ms`뿐이다(`obs/trace.py`). 이 step(8a)은 **trace에 시간 필드를 추가하고 그것을 만드는 곳에서 채우는 것**까지이고, Langfuse로 보내는 것은 step 3(8b)이다. 프롬프트·생성 문장·요청 본문은 trace에 넣지 않는다(기존 규칙 그대로).

**확인한 사실(코드를 열어 확인)**:
- **단계 이벤트는 경계 표시다**: `agents/supervisor.py` `_emit(state, event, on_event)`가 `state["sv_steps"]`에 `{agent, phase, status}`를 쌓는다(`_step`이 호출). supervisor·research는 **끝 이벤트만** 있고 planning은 **시작 이벤트만** 있다(평가의 끝이 기획+평가를 닫는다). 그래서 단계의 시작·끝 시각은 **이벤트 시각의 연속**에서 구한다(8b가 계산).
- `result["steps"]`는 `state["sv_steps"]`이고(`supervisor.py` 689행 부근), `obs/trace.py` `build_trace`가 `TraceStep(**_project(TraceStep, step))`로 읽는다. `_project`는 `TraceStep.model_fields`에 있는 키만 가져간다. 그래서 `sv_steps` 항목에 키 `at`을 더하면 `TraceStep.at`이 채워진다.
- SSE로 나가는 `step` 이벤트는 `api/ask.py` `_event()`가 `("agent","phase","status")` 세 키만 뽑는다 → **`at`은 화면으로 나가지 않는다**(`on_event`로 가는 이벤트 dict에도 넣지 않는다. 저장되는 `sv_steps` 사본에만 넣는다).
- 모델 호출은 비용 원장 `LedgerEntry`(`obs/ledger.py`: `ts`, `provider`, `model`, `purpose`, 토큰, `cost_usd`, `cost_source`, `reasoning_effort`; `extra="forbid"`)에 한 줄씩 남고, `build_trace`가 요청 구간의 원장 항목으로 `TraceCall`을 만든다. 채팅 호출은 `llm/chat.py` `record_usage(...)`(`chat_complete` 안에서 호출, `ts=now()`는 **호출이 끝난 뒤**의 시각)가 쓰고, 이미지는 `llm/image.py` `generate_image` 안에서 직접 `append_entry`한다.
- `tests/test_llm_image.py` 321행 부근이 `set(inspect.signature(generate_image).parameters) == {...}`로 **시그니처를 정확 일치**로 고정한다 → `generate_image`에 **인자를 더하지 않는다**.

**설계 결정**:
1. `LedgerEntry`에 `duration_ms: int | None = Field(default=None, ge=0, exclude_if=lambda value: value is None)`를 더한다. **None이면 직렬화에서 빠진다**(기존 `costs.jsonl` 줄·기존 출력이 바이트까지 같다. `obs/trace.py`가 `TraceStructured.first_attempt_failure_details`에 쓴 `exclude_if` 방식과 같다). 값은 모델 호출 한 번의 소요 시간(밀리초)이다.
2. `llm/chat.py`: `chat_complete`가 **성공한 디스패치 시도**(재시도 대기 제외)의 시작부터 응답 처리(스트림이면 모든 청크를 받은 뒤)가 끝날 때까지를 재서 `record_usage(..., duration_ms=...)`에 넘긴다. 시간 측정은 모듈 수준 함수 `_monotonic = time.monotonic`을 쓰고(테스트가 `monkeypatch`로 바꾼다), `chat_complete`·`record_usage`의 기존 인자·반환은 **그대로 두고 `duration_ms`는 `record_usage`의 선택 키워드 인자로만** 더한다.
3. `llm/image.py`: 같은 방식으로 `call(**kwargs)` 시도의 소요를 재서 `LedgerEntry(duration_ms=...)`에 넣는다(**함수 시그니처 불변**).
4. `agents/supervisor.py`: 모듈 수준 `_utcnow()`(= `datetime.now(UTC)`, 테스트가 바꾼다)를 두고 `_emit`이 `sv_steps`에 쌓는 **사본에만** `"at": _utcnow().isoformat()`을 더한다.
5. `obs/trace.py`: `TraceStep.at: datetime | None = Field(default=None, exclude_if=...)`(타임존 필수·UTC로 정규화, `started_at`과 같은 검사), `TraceCall.duration_ms: int | None`(같은 `exclude_if`), `TraceCall.ended_at: datetime | None`(같은 `exclude_if`). `build_trace`는 원장 항목의 `duration_ms`가 있을 때만 `ended_at=entry.ts`를 채운다(**옛 항목은 시간 없이** 그대로 나가 기존 `calls[0].model_dump() == ledger().model_dump(include=...)` 단언이 불변). `summarize_by_tenant`는 호출 기록에 `duration_ms`가 하나라도 있을 때만 `duration_ms_by_purpose`(목적별 합)를 더한다(`pattern_distribution`처럼 조건부로, 없으면 기존 요약과 같다).

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `LedgerEntry.duration_ms` | `llm/chat.py`(`record_usage`), `llm/image.py` | `obs/trace.py`(`build_trace`), step 3의 `obs/langfuse_sink.py` |
| `sv_steps[].at` | `agents/supervisor.py`(`_emit`) | `obs/trace.py`(`TraceStep.at`), step 3 |
| `TraceStep.at`·`TraceCall.duration_ms`·`TraceCall.ended_at` | `obs/trace.py`(`build_trace`) | step 3의 `obs/langfuse_sink.py`, `summarize_by_tenant` |
| `duration_ms_by_purpose` | `obs/trace.py`(`summarize_by_tenant`) | `eval/` 요약 소비자(있으면 조건부 키라 영향 없음) |

**기존 단언과의 충돌 점검(`rg`로 확인한 소비자)**: `tests/test_trace.py` 150행 `record.steps[0].model_dump() == result["steps"][0]`(`at` 없는 합성 입력에서는 `exclude_if`로 키가 빠져 같다), 167행 `record.calls[0].model_dump() == ledger().model_dump(include=...)`, 310행 요약 정확 일치(조건부 키라 불변), `tests/test_ledger.py` 79·186행 `model_dump()` 왕복(None 제외로 불변). `tests/test_llm_image.py` 321행 시그니처 정확 일치(불변). `tests/test_supervisor.py`는 `sv_steps`를 상태 키 목록(`sv_steps` 키 이름)으로만 단언하고 `steps` 항목을 정확 일치로 단언하지 않는다 → 새 상태 키를 만들지 않는다. 위 테스트들은 **케이스 추가에 한함, 단언 약화 금지**로 허용한다(깨지면 약화하지 말고 `blocked`로 보고한다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`(CRITICAL: 비용 원장 기록, 키·프롬프트를 trace에 남기지 않음), `/docs/ARCHITECTURE.md`(관측), `/docs/ADR.md`(ADR-016)
- `/src/beautyads/obs/ledger.py`, `/src/beautyads/obs/trace.py`, `/src/beautyads/obs/__init__.py`
- `/src/beautyads/llm/chat.py`(`record_usage`, `chat_complete`), `/src/beautyads/llm/image.py`(`generate_image`), `/src/beautyads/agents/supervisor.py`(`_emit`·`_step`·결과 조립부)
- `/tests/test_ledger.py`, `/tests/test_trace.py`, `/tests/test_llm_chat.py`, `/tests/test_llm_image.py`, `/tests/test_supervisor.py`, `/tests/test_api_assembly.py`(trace 기록 부분)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/obs/ledger.py`, `src/beautyads/obs/trace.py`, `src/beautyads/llm/chat.py`, `src/beautyads/llm/image.py`, `src/beautyads/agents/supervisor.py`, `tests/test_ledger.py`, `tests/test_trace.py`, `tests/test_llm_chat.py`, `tests/test_llm_image.py`, `tests/test_supervisor.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `src/beautyads/obs/ledger.py`, `src/beautyads/obs/trace.py`, `src/beautyads/llm/chat.py`, `src/beautyads/llm/image.py`, `src/beautyads/agents/supervisor.py`, `tests/test_ledger.py`, `tests/test_trace.py`, `tests/test_llm_chat.py`, `tests/test_llm_image.py`, `tests/test_supervisor.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

위 "설계 결정" 1~5를 구현한다. `agents/supervisor.py`는 `_emit`에 `at`을 더하고 `_utcnow`를 두는 것 외에는 바꾸지 않는다(동결 프롬프트·상수·한도 로직 불변).

**테스트(합성 데이터, 모델·네트워크·`.env` 없음, 시계는 `monkeypatch`로 고정)**
- `tests/test_ledger.py`(케이스 추가에 한함): (1) `duration_ms=None`인 항목의 `model_dump_json()`에 `duration_ms` 키가 **없고** 옛 줄(키 없음)을 읽어도 통과, (2) 값이 있으면 왕복 후 같음, (3) 음수·문자열·`NaN`은 거부.
- `tests/test_llm_chat.py`(케이스 추가에 한함): (4) `_monotonic`을 가짜로 바꿔 시작 1.0초·끝 2.5초이면 원장 항목 `duration_ms == 1500`, (5) 스트림 호출도 같은 규칙, (6) 첫 시도가 재시도 가능 오류로 실패하고 두 번째가 성공해도 **성공한 시도의 시간만** 기록(대기 `sleep` 시간 불포함). 기존 호출 단언은 불변.
- `tests/test_llm_image.py`(케이스 추가에 한함): (7) 이미지 항목에 `duration_ms`가 기록됨, (8) `generate_image` 시그니처 단언은 **그대로 통과**한다.
- `tests/test_supervisor.py`(케이스 추가에 한함): (9) `_utcnow`를 가짜로 바꿔 `result["steps"]`의 모든 항목에 UTC ISO 문자열 `at`이 있고 비감소 순서이다, (10) **`on_event`로 간 이벤트 dict와 SSE 이벤트 정확 일치 단언은 불변**(`at`이 이벤트에 없음), (11) 상태 키 이름 집합 단언 불변.
- `tests/test_trace.py`(케이스 추가에 한함): (12) `at`·`duration_ms`·`ended_at`이 없는 합성 결과·원장 항목에서 `TraceRecord.model_dump_json()`이 **이 step 이전과 같다**(새 키가 출력에 없음), (13) `at`이 있는 `steps`와 `duration_ms`가 있는 원장 항목에서 `TraceStep.at`(UTC)·`TraceCall.duration_ms`·`TraceCall.ended_at(== entry.ts)`가 채워지고 JSONL 왕복(`append_trace` → `read_traces`)이 같다, (14) 옛 JSONL 줄(새 키 없음)을 `read_traces`가 읽는다, (15) `summarize_by_tenant`가 `duration_ms`가 없으면 기존 키 집합 그대로이고 있으면 `duration_ms_by_purpose`가 목적별 합이다, (16) 프롬프트·메시지·응답 본문이 trace JSON에 없음(기존 비밀 누출 단언 유지).
- 시간 값을 모델이 만든 값처럼 굳히지 않는다(가짜 시계의 숫자는 합성 값이다).

## Acceptance Criteria

```bash
make verify   # ruff + pytest + pnpm lint·typecheck·test 통과
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

- `generate_image`·`chat_complete`·`record_usage`의 기존 인자 이름·순서·반환을 바꾸거나 필수 인자를 더하지 마라(`record_usage`의 선택 키워드 `duration_ms`만 허용). 이유: `tests/test_llm_image.py`가 시그니처를 정확 일치로 고정하고 호출자(`api/assembly.py`·`eval/`)가 많다(B-FP-071).
- `supervisor.py`에 새 상태 키(`sv_*`)나 새 결과 키를 더하지 마라. `at`을 SSE 이벤트·`on_event` 이벤트 dict에 넣지 마라. 이유: 상태 키 집합을 정확 일치로 단언하는 테스트가 있고, 화면 계약(`step` 이벤트 세 키)을 바꾸지 않는다.
- 새 필드를 `None`일 때 출력에 남기지 마라(`exclude_if`). 기존 `costs.jsonl`·`traces.jsonl` 줄의 형식을 바꾸거나 다시 쓰지 마라. 이유: 기존 기록과 호환돼야 하고 원장은 append-only다(FP-C12).
- 프롬프트·메시지·응답 본문·키를 trace나 원장에 넣지 마라. 호출 시간에 예외 메시지를 넣지 마라. 이유: 기존 규칙(trace는 메타데이터만)과 AGENTS.md 비밀 값 규칙이다.
- 동결 프롬프트·점수 기준·상수·`docs/results/`·`data/evalset/`을 건드리지 마라(`tests/test_prereg.py`가 동결 줄을 검사한다). 이유: 동결 값은 결과를 본 뒤 바꾸지 않는다(AGENTS.md CRITICAL).
