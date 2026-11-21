# Step 3: langfuse-io

## 설계 검토 기록

**배경(7d 브리프 3-나)**: Langfuse 화면에서 요청·단계·호출마다 **무엇이 들어가고 무엇이 나왔는지**가 비어 있다(7b는 메타데이터만 보냈다). 채용관이 워크플로를 판단하려면 입력과 출력이 보여야 한다. 단, **로컬 JSONL trace의 기존 규칙(메시지·모델 문장·키 없음)은 그대로** 두고, **Langfuse로 보낼 때만** input/output을 붙인다. 이 데이터는 `TraceRecord`에 넣지 않고 `api/assembly.py`가 sink로 **직접 넘긴다**(JSONL에는 저장되지 않는다).

**두 단계로 구현한다(승인안: 1단계 필수, 2단계 권장)**:
- **1단계(요약 input/output)**: 요청(`ask`)의 input = 요청 문장과 선택한 효능, output = 결과 종류와 기획안 요약. 단계 span의 output: `supervisor` = 의도·효능·훅 유형·소구·형식, `research` = 사용한 도구·결과 건수·결론, `planning`/`evaluation` = 기획안과 점수·통과 여부·재검토 항목, `image` = image_brief.
- **2단계(호출별 프롬프트·응답)**: 모델 호출(generation)마다 **실제 프롬프트와 응답**을 각 4,000자 상한(넘으면 `(생략됨)`)으로 붙인다. **`llm/chat.py`는 바꾸지 않고**, 모든 온라인 모델 호출이 이미 지나가는 **`api/assembly.py`의 경계**(`chat()` 클로저, `_ConfiguredStructured.generate`, 이미지 호출 `model_calls["image"]`)에서 요청 범위 수집기로 모은다. 이유: 승인안은 `llm/chat.py`에 선택적 기록 장치를 두라고 했지만, (a) `llm` 계층은 재시도·비용·원장·호출 전 검증이 한곳에 모인 **동결 호출 경로**라서 변경 위험이 크고 (b) 조립 경계는 `purpose`·`messages`·결과를 이미 모두 보며 (c) 비활성일 때 `llm/` 출력·원장·동결 호출이 **바이트까지 같다**는 것을 `llm/`을 건드리지 않는 것으로 구조적으로 보장할 수 있다. 이 변경이 승인안과 다름을 최종 응답 `summary`에 적는다. 재시도로 원장 항목이 수집분보다 많으면 일부 호출의 입력·출력이 비는 한계도 `summary`에 적는다.

**식별자 전수 대조(현재 코드, 모두 열어 확인)**:
- `settings.py`: `LangfuseSettings`(pydantic, 7b step 3, 필드 `public_key`·`secret_key`·`host`), `langfuse_settings(*, environ=None, env_file=DEFAULT_ENV_FILE) -> LangfuseSettings | None`(키 둘 중 하나라도 비면 `None`), `get_setting`, `InvalidSetting`.
- `obs/langfuse_sink.py`(step 2 이후): `build_timeline(record) -> list[Observation]`(`Observation`: `id`, `kind`, `name`, `start`, `end`, `parent_id`, `attrs`; 단계 span 이름 `supervisor`·`research`·`planning #k`·`evaluation #k`·`image`), `export_trace(record, *, settings, client_factory=Langfuse) -> bool`(루트 trace 본문 `TraceBody(id, name="ask", user_id, timestamp, tags, metadata)`, 관측 본문에 `input`·`output` 칸이 SDK 타입(`CreateSpanBody`·`CreateGenerationBody`·`TraceBody`)에 있다).
- `api/assembly.py`: `ask(message, ctx, profile, feedback, with_image, on_event=None, *, context_mode="on", claim_choice=None)`의 `finally`에서 `build_trace(...)` → `append_trace(...)` → `observation_settings`가 있으면 `Thread(daemon=True)`로 `export_trace(record, settings=observation_settings)`를 부른다(예외 삼킴). `result`는 `run_request(...)`의 반환(`ask()` 안 지역 변수 `result`, 예외 시 `None`), `message`·`claim_choice`는 인자. 모델 호출 경계: 지역 함수 `chat(**options)`(`model_calls["chat"]` 호출, `research_chat`가 감쌈), 클래스 `_ConfiguredStructured`(`generate(self, spec, **options)`가 `self.guard()` 후 `self.inner.generate(spec, **{**options, **self.options})`, 결과 `StructuredResult(ok, value, failure, attempts, cost_usd, calls)`, `options`에 `messages`·`purpose`), 이미지 `model_calls["image"](prompt=..., ...)`(`image_fn` 안).
- `result`(`agents/supervisor.py`의 반환 키, 읽기 전용): `kind`, `intent`, `brief`(`ResearchBrief`: `goal`, `category`, `claim`, `hook_type`, `angle`, `format`, `skin_concern`, `output`, `max_tool_calls`), `handoff`(`conclusion`, `result_counts[{tool,row_count,shown_count}]`, `aggregates`, `evidence_ids` …), `claim_choice`, `plans[]`(`plan`(`title`, `hook_text`, `copy_lines`, `claimed_efficacy`, `evidence_ids`, `image_brief` …), `attempts[{attempt, scores, low_items, checks_passed, final_passed, cost_usd?}]`, `status`, `unknown_count` …).
- 소비자 테스트: `tests/test_api_assembly.py`의 7b step 3 케이스(`test_ask_without_langfuse_configuration_does_not_export`, `test_ask_exports_after_local_append_in_daemon_without_affecting_result`)가 가짜 `export_trace(record, *, settings)`를 `monkeypatch`한다 → 새 호출이 `io=` 키워드를 더 넘기므로 **그 가짜의 시그니처를 `io=None`을 받도록 갱신**해야 한다(호출 여부·순서·예외 삼킴 단언은 불변). 이 파일에는 해시 시드에 따라 달라지는 순회 순서(`frozenset` 등)에 기대는 새 단언을 만들지 않는다(7b step 4가 같은 원인으로 blocked됐다).

**설계 결정**:
- **환경 변수 하나로 끈다**: `BEAUTYADS_LANGFUSE_IO`(`1`/`0`, 기본 `1`). Langfuse 설정(키 둘)이 있을 때만 의미가 있다. `LangfuseSettings`에 `capture_io: bool = True`를 더하고 `langfuse_settings`가 이 변수를 `get_setting`으로만 읽는다(빈 값·공백은 기본값, `1`·`0` 외는 `InvalidSetting("BEAUTYADS_LANGFUSE_IO")`). `.env.example`에 이름만 주석으로 더한다.
- 새 모듈 **`obs/langfuse_io.py`**(계층: obs, `domain`·`settings` 외 import 없음, 순수 함수):
  - `REDACTED = "[가림]"`, `OMITTED = "(생략됨)"`, `CLIP_CHARS = 4000`.
  - `redact(text: str) -> str`: API 키·토큰 패턴을 `[가림]`으로 바꾼다: `sk-` 시작 키(`sk-[A-Za-z0-9_-]{8,}`, `sk-ant-…` 포함), `AIza[0-9A-Za-z_-]{20,}`, `Bearer\s+\S+`, `Authorization:` 줄, JWT(`eyJ…\.….\.…`), `이름=값` 형태에서 이름에 `KEY`·`TOKEN`·`SECRET`·`PASSWORD`가 든 값. **이미지 바이트·base64를 가린다**: `data:<mime>;base64,…`와 200자 이상 이어지는 base64 문자열은 `(이미지 데이터 생략)`으로 바꾼다.
  - `clip(text: str, limit: int = CLIP_CHARS) -> str`: 한도를 넘으면 앞 `limit`자 + `"\n" + OMITTED`.
  - `to_text(value) -> str`: 문자열은 그대로, 그 밖은 `json.dumps(value, ensure_ascii=False, default=str)`; 직렬화 실패는 `OMITTED`가 아니라 고정 문구 `(직렬화 불가)`.
  - `Capture`(frozen dataclass: `purpose: str`, `ended_at: datetime`(UTC, 수집 시각), `input: str`, `output: str`)와 `RequestIO`(frozen dataclass: `message: str`, `claim_choice: dict | None`, `result: dict | None`, `captures: tuple[Capture, ...]`).
  - `trace_input(io) -> dict`, `trace_output(io) -> dict`, `stage_io(io) -> dict`(span 이름 → `{"input"?, "output"?}`): **허용 키만 골라** 만든다(위 `result` 키에서). `trace_input` = `{"요청": message, "효능 선택": claim_choice 요약(mode·claims·requested_claim)}`. `trace_output` = `{"결과": kind, "기획안": [{"제목","훅","카피","주장 효능","근거 ID"} ...]}`. `stage_io`: `supervisor` output = `{"의도": intent, "효능": brief.claim, "훅 유형": brief.hook_type, "소구": brief.angle, "형식": brief.format}`, `research` output = `{"도구": [tool, ...], "결과 건수": result_counts, "결론": handoff.conclusion}`, `planning #k` output = 그 기획안의 요약(**모든 시도를 합친 `attempts`를 기획안 순서대로 펼친 k번째 시도가 그 기획안의 마지막 시도일 때만** 최종 기획안을 붙이고 아니면 output을 생략: 앞선 시도의 본문은 보관하지 않으므로 추측하지 않는다), `evaluation #k` output = k번째 시도의 `{"점수": scores, "통과": final_passed, "코드 검사": checks_passed, "재검토 항목": low_items}`(**`rationale`·모델이 쓴 문장은 넣지 않는다**), `image` input = `image_brief`. 결과에 없는 키는 건너뛴다(`[]` 직접 접근 금지).
  - `match_captures(calls, captures) -> dict[int, Capture]`: 호출(`TraceCall`)마다 **같은 `purpose`이고 `ended_at`이 가장 가까운** 미사용 수집분을 짝짓는다(호출 순서대로 탐욕적으로, 한 수집분은 한 번만, 시간 차이가 5초를 넘으면 짝짓지 않는다). 재시도로 원장 항목이 더 많으면 짝이 없는 호출은 input/output 없이 둔다.
- `obs/langfuse_sink.py`: `export_trace(record, *, settings, io=None, client_factory=Langfuse)`와 `build_timeline(record, io=None)`가 `io`가 있고 `settings.capture_io`일 때만 위 값을 관측의 `input`/`output`에 붙인다. 모든 문자열은 **`clip(redact(...))`** 를 거친다. `io`가 `None`이거나 `capture_io`가 거짓이면 **이 step 이전과 같은 batch**를 보낸다(테스트로 고정). 모든 예외는 삼키고 `False`를 돌려주는 기존 방침 불변.
- `api/assembly.py`: `ask()` 시작에서 **`observation_settings`가 `None`이 아니고 `capture_io`가 참일 때만** 요청 범위 수집기(`captures: list[Capture]`)를 만든다. 아니면 수집기는 `None`이고 아래 모든 분기가 **지금과 완전히 같은 코드 경로**다. 수집기가 있을 때: (a) `chat(**options)`는 응답을 받은 뒤 `messages`(= `options["messages"]`)·`purpose`·응답(`text`와 `tool_calls`의 이름·인자 문자열)을 `Capture`로 더한다, (b) `_ConfiguredStructured`에 선택 인자 `capture=None`을 더하고 `generate`가 성공 반환 직후 `messages`·`purpose`·`result.value`(JSON 직렬화)를 더한다, (c) 이미지 호출은 `prompt`와 결과 요약(`mime`·`size`, **바이트 없음**)을 더한다. 수집은 호출 결과·예외·반환값을 바꾸지 않는다(수집 자체의 예외는 삼킨다). 끝에서 `RequestIO(message, claim_choice, result, tuple(captures))`를 만들어 `export_trace(record, settings=..., io=...)`로 넘긴다.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `LangfuseSettings.capture_io`·`BEAUTYADS_LANGFUSE_IO` | `settings.py` | `api/assembly.py`, `obs/langfuse_sink.py`, `.env.example`(이름) |
| `redact`·`clip`·`to_text`·`Capture`·`RequestIO`·`stage_io`·`match_captures` | `obs/langfuse_io.py` | `obs/langfuse_sink.py`, `api/assembly.py`, 테스트 |
| 요청 범위 수집기와 `capture=` 인자 | `api/assembly.py` | `obs/langfuse_io.py`(`RequestIO`), `obs/langfuse_sink.py`(`export_trace(io=)`) |
| 관측의 `input`·`output` | `obs/langfuse_sink.py` | Langfuse 화면(사용자) |

**기존 단언과의 충돌 점검**: (1) `tests/test_api_assembly.py` 7b step 3 케이스의 가짜 `export`를 `io=None`을 받게 **시그니처만 갱신**(호출 여부·순서·예외 삼킴·스레드 단언 불변, 약화 금지). 이 파일의 나머지(모델 호출 목록, 원장, trace JSONL 정확 일치)는 불변이어야 한다: **수집기가 꺼진 기본 경로**(Langfuse 설정 없음)는 호출 인자·반환·원장이 바이트까지 같다(기존 테스트가 그대로 통과). (2) `tests/test_langfuse_sink.py`는 `io=None`일 때 batch 내용이 불변임을 단언하는 케이스를 **더한다**(기존 단언 불변). (3) `tests/test_caps_guard.py`(AST로 `api/` 전체에서 `min(caps)` 등 상한 우회 패턴 금지)·`tests/test_schema_guard.py`(`StructuredSpec(` 호출 모듈 목록)는 새 코드가 이 패턴을 쓰지 않으므로 영향이 없음을 확인한다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`(CRITICAL: 비밀 값·키를 trace·로그에 남기지 않는다, 호출 경로는 한 곳), `/docs/ADR.md`(ADR-016), `/docs/CONTRACTS.md`(Langfuse 절)
- `/src/beautyads/settings.py`, `/src/beautyads/obs/langfuse_sink.py`, `/src/beautyads/obs/trace.py`, `/src/beautyads/api/assembly.py`(`_ConfiguredStructured`, `chat()`, `ask()`의 `finally`와 `image_fn`), `/src/beautyads/llm/structured.py`·`/src/beautyads/llm/chat.py`(읽기 전용: 결과 타입), `/src/beautyads/agents/supervisor.py`(결과 키, 읽기 전용), `/src/beautyads/domain/research.py`(`ResearchBrief`)
- `/tests/test_api_assembly.py`(7b step 3의 export 케이스와 `rig`·`invoke`), `/tests/test_langfuse_sink.py`, `/tests/test_caps_guard.py`, `/tests/test_schema_guard.py`(읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/obs/langfuse_io.py`, `src/beautyads/obs/langfuse_sink.py`, `src/beautyads/settings.py`, `src/beautyads/api/assembly.py`, `.env.example`, `tests/test_langfuse_io.py`, `tests/test_langfuse_sink.py`, `tests/test_api_assembly.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `src/beautyads/obs/langfuse_io.py`, `src/beautyads/obs/langfuse_sink.py`, `src/beautyads/settings.py`, `src/beautyads/api/assembly.py`, `.env.example`, `tests/test_langfuse_io.py`, `tests/test_langfuse_sink.py`, `tests/test_api_assembly.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

위 "설계 결정"을 구현한다. `llm/`·`agents/`·`web/`은 수정하지 않는다.

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음, 가짜 클라이언트·가짜 모델)**
- `tests/test_langfuse_io.py`(새): (1) `redact`: `sk-`·`sk-ant-`·`AIza…`·`Bearer …`·JWT·`API_KEY=값`·`Authorization:` 합성 문자열이 모두 `[가림]`이 되고 일반 문장·한국어는 그대로, `data:image/png;base64,…`와 긴 base64 문자열이 `(이미지 데이터 생략)`으로 바뀜. (2) `clip`: 4,000자 이하는 그대로, 초과는 앞 4,000자 + `(생략됨)`. (3) `to_text`: 한국어가 `\u` 이스케이프 없이 나옴, 직렬화 불가 객체는 `(직렬화 불가)`. (4) `trace_input`/`trace_output`/`stage_io`: 합성 `result`로 **허용 키만** 나옴(합성 비밀·`rationale`·알 수 없는 키가 결과 어디에도 없음), 결과에 키가 없어도 예외가 없음, `planning #k` output은 마지막 시도에서만 붙음, `evaluation #k` output에 점수·통과·재검토 항목만. (5) `match_captures`: 같은 목적·가장 가까운 시각끼리 짝, 한 수집분은 한 번만, 5초 초과는 짝 없음, 호출이 수집분보다 많아도 예외 없음.
- `tests/test_langfuse_sink.py`(케이스 추가, 기존 단언 불변): (6) `io=None`이면 batch가 이 step 이전과 **같다**(관측에 `input`·`output` 없음), `settings.capture_io=False`이면 `io`가 있어도 같다, (7) `io`가 있고 `capture_io`이면 루트·단계 span·generation에 `input`/`output`이 붙고 모든 문자열이 4,000자 이하이며 합성 비밀 문자열이 batch 어디에도 없다, (8) 가짜 클라이언트가 예외를 올려도 `False`이고 예외 메시지가 반환·출력에 없음.
- `tests/test_api_assembly.py`(케이스 추가 + 가짜 `export` 시그니처 갱신): (9) Langfuse 설정이 없거나 `capture_io`가 거짓이면 **수집기가 만들어지지 않고** 모델 호출에 넘기는 인자·반환·원장·trace JSONL이 **지금과 같다**(기존 테스트 통과 + 수집 경로가 호출되지 않음 단언), (10) 설정이 있고 `capture_io`이면 가짜 모델 호출의 `messages`와 응답이 `export_trace`의 `io.captures`에 들어가고(목적별), **trace JSONL(`TraceRecord`)에는 메시지·응답이 없다**(기존 비밀 누출 단언 유지), (11) 수집이 예외를 올려도 `ask()` 결과가 같다, (12) 이미지 호출 수집에 이미지 바이트·base64가 없다, (13) `export_trace`가 데몬 스레드로 불리는 기존 단언 불변.
- 설정 케이스는 7b가 `langfuse_settings` 테스트를 둔 `tests/test_langfuse_sink.py`에 더한다(새 설정 테스트 파일을 만들지 마라): (14) `BEAUTYADS_LANGFUSE_IO` 미설정·빈 값·공백이면 `capture_io is True`, `0`이면 거짓, 그 밖은 `InvalidSetting`(예외 문자열에 입력 값 없음), 키가 없으면 `langfuse_settings`가 여전히 `None`.
- 합성 문장·비밀만 쓴다(모델 출력 값을 기대값으로 굳히지 않는다).

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

- `llm/chat.py`·`llm/structured.py`·`llm/image.py`·`obs/trace.py`·`obs/ledger.py`·`agents/`를 수정하지 마라. 로컬 JSONL trace(`TraceRecord`)에 메시지·응답·입력·출력을 넣지 마라. 이유: JSONL의 "메시지·모델 문장·키 없음" 규칙과 동결 호출 경로는 그대로이고, 입력·출력은 조립에서 Langfuse로 직접 넘긴다(7d 브리프).
- API 키·`.env` 값·인증 헤더·토큰, 이미지 바이트·base64를 Langfuse로 보내거나 로그·예외·반환에 남기지 마라(`redact`를 모든 문자열에 적용). 수집 실패나 전송 실패 메시지를 노출하지 마라. 이유: 비밀 값은 어디에도 남기지 않는다(AGENTS.md CRITICAL, B-FP-072).
- 수집기가 꺼져 있을 때(Langfuse 설정 없음·`capture_io` 거짓) 모델 호출 경로·인자·반환·원장을 바꾸지 마라. 수집 때문에 요청을 느리게 하거나 실패시키지 마라(수집은 메모리에 더하기만, 전송은 데몬 스레드). 이유: 기본 동작은 바이트까지 같아야 한다(7d 브리프, 승인된 서버 변경의 조건).
- 모델이 쓴 `rationale`·평가 사유 문장을 단계 output에 넣지 마라(점수·통과·재검토 항목만). 앞선 기획 시도의 본문을 추측해 채우지 마라. 이유: 판정할 수 있는 것은 코드 값만 보이고, 보관하지 않은 데이터는 지어내지 않는다(FP-C03, AGENTS.md).
- `make obs-up`·`make obs-check`·`uv run python -m beautyads.obs.langfuse_check`·`docker compose --profile obs up`을 실행하지 마라. 기존 단언을 약화·삭제하지 마라(가짜 `export` 시그니처 갱신만 허용). 이유: 실제 서비스 접속은 사용자가 한다(A-FP-040).
