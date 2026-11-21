# Step 2: langfuse-spans

## 설계 검토 기록

**배경(사용자 화면 확인: Langfuse 타임라인)**: 7b가 만든 `obs/langfuse_sink.py`의 `build_timeline`은 타임라인을 보내지만 **구조가 에이전트 워크플로를 보여 주지 못한다**: `plan` span 하나 안에 기획·평가 호출이 섞이고, `image` 단계는 시간이 없으며, 이미지 생성 호출이 `plan` 아래에 들어 있다. 이 step은 span 구조를 **Supervisor → 리서치 → 기획(시도마다) → 평가(시도마다) → 시안** 순서로 별도 span으로 나눈다(재작업 루프는 기획과 평가가 번갈아 나타난다). 목적은 4개 에이전트가 순서대로 일하는 모습이 보이는 것이다. 시간 필드 규칙·결정적 ID(UUID5)·시각 없는 옛 기록 처리 방식은 7b 그대로다(7d 브리프). **입력·출력(input/output) 채우기는 step 3**이다.

**왜 기획·평가·시안 구간을 단계 이벤트가 아니라 호출 시각에서 구하는가(코드 확인)**: `agents/supervisor.py`는 `planning`의 **시작** 이벤트를 `run_plan_eval` 호출 전에 내보내지만, 그 호출이 끝난 **뒤에** `evaluation` 끝(`_step(..., "evaluation", "end", ...)`, 538행 부근)·`rework` 끝(540행)·`image` 끝(543~552행)을 **한꺼번에** 내보낸다(`agents/plan_eval.py`에는 `on_event`가 없다, 2026-11-21 확인). 그래서 이 세 이벤트의 `at`은 같은 시각의 묶음이고(`tests/test_supervisor.py::test_events_arrive_at_stage_boundaries_including_tools_reworks_image`가 이벤트 순서를 고정한다), 평가·시안의 실제 구간은 이벤트로 알 수 없다. 반면 `supervisor`·`research`의 끝 이벤트는 각 단계가 끝난 **그 시점**에 나가므로 구간 경계로 쓸 수 있다. 호출 시각은 7b가 만든 `TraceCall.duration_ms`·`ended_at`(원장 `ts`와 `duration_ms`)이다. **이 step은 SSE 이벤트의 순서·시점을 바꾸지 않는다**(화면 계약 불변, 이벤트를 앞당기려고 `plan_eval.py`를 고치지 않는다).

**식별자 전수 대조(현재 코드)**:
- `obs/langfuse_sink.py`(205줄): `Observation`(TypedDict: `id`, `kind`(`span`|`generation`|`event`), `name`, `start`, `end`, `parent_id`, `attrs`), `build_timeline(record: TraceRecord) -> list[Observation]`(루트 `ask`, `steps`로 `supervisor`·`research`·`image` span과 `plan` span(planning 시작 → evaluation 끝), `rework` event, 호출별 generation(부모는 시간 구간을 포함하는 가장 작은 단계 span)), `export_trace(record, *, settings, client_factory=Langfuse) -> bool`(관측마다 `uuid4()` 이벤트 ID, 본문 `id`는 `uuid5(NAMESPACE_URL, f"{record.trace_id}:{순번}").hex`).
- `obs/trace.py`: `TraceRecord`(`steps: list[TraceStep(agent, phase, status, at)]`, `calls: list[TraceCall(purpose, model, input_tokens, output_tokens, thought_tokens, cached_tokens, cost_usd, cost_source, reasoning_effort, duration_ms, ended_at)]`, `started_at`, `duration_ms`, `kind`, `intent`, `outcome`, ...).
- 호출 목적(원장 `purpose`, 2026-11-20 live 실행 원장 49줄에서 확인한 값): `supervisor`, `research`, `plan`, `evaluate`, `image-plan`(이미지는 `"image-" + purpose_suffix`, `llm/image.py`).
- `obs/langfuse_check.py`(사용자 실행 도구)가 합성 `TraceRecord`를 만든다(7b step 3). 새 구조를 보여 주도록 합성 기록을 같은 형태로 바꿔야 한다.
- 소비자 테스트: `tests/test_langfuse_sink.py`(385줄, 7b step 3)가 `build_timeline`의 구조(루트·단계 span 이름과 구간, `rework` event, generation 부모, 옛 기록은 시간 없음, 결정적 ID)를 단언한다.

**설계 결정(새 `build_timeline`)**:
- 루트 `ask`: 이전과 같다(시각 있는 기록이면 `[started_at, started_at + duration_ms]`).
- **`supervisor`·`research` span**: 이전처럼 단계 끝 이벤트의 `at`으로 구한다(`supervisor`: `[started_at, supervisor 끝 at]`, `research`: `[supervisor 끝 at, research 끝 at]`). 이벤트 시각이 없으면(옛 기록) 이 span은 만들지 않는다.
- **`planning #k`·`evaluation #k`·`image` span: 모델 호출 구간에서 만든다.** 시각 있는 호출(`duration_ms`와 `ended_at`이 모두 있음)만 대상이고 호출 하나 = span 하나다. 구간은 `[ended_at − duration_ms, ended_at]`. 목적 `plan`은 `planning #1, #2, …`(호출 순서대로 번호), `evaluate`는 `evaluation #1, #2, …`, `image` 접두사는 `image`(이미지 호출이 여러 번이면 `image #1, #2`). 번호는 **요청 전체의 호출 순서**다(기획안이 여러 개이거나 재작업이 있으면 `planning #1 → evaluation #1 → planning #2 → evaluation #2 …`처럼 번갈아 나타난다. 어느 기획안의 재작업인지는 호출만으로는 알 수 없으므로 span 이름에 기획안 번호를 넣지 않는다).
- generation(호출 자체)의 부모는 **자기 구간과 같은 구간의 단계 span**이다(위 규칙으로 만든 span이면 그 span, `supervisor`·`research` 호출은 시간 포함 관계로 해당 span, 어느 span에도 안 들어가면 루트). 이전처럼 "시간 구간을 포함하는 가장 작은 span" 규칙을 쓰되 **동률이면 이름이 `planning`·`evaluation`·`image`로 시작하는 span을 우선**한다. **이미지 생성 호출은 `image` span 아래**에 둔다.
- `rework` event는 **만들지 않는다**(`rework` 이벤트의 `at`은 평가 끝과 같은 묶음 시각이라 타임라인에서 위치가 틀린다). 대신 루트 `metadata`에 `rework_count`(`steps`의 `rework` 이벤트 수)를 더한다. 이미지 단계 이벤트(`image`)가 `failed`인데 이미지 호출이 없으면(상한 도달 등) 시각 없는 `event`(`image_failed`)만 만든다.
- 시각이 없는 옛 기록(`steps[].at` 없음, 호출에 `duration_ms` 없음): 시간 없이(start·end `None`) 보낸다. `supervisor`·`research` span은 만들지 않고 generation은 루트 아래에 둔다. **시간을 추측해 채우지 않는다.**
- 결정적 ID: 관측 순번에서 `uuid5(NAMESPACE_URL, f"{trace_id}:{순번}")`(7b 그대로). 순번은 **구간 시작 시각 오름차순**으로 정한 뒤 span → 그 안의 generation 순으로 매겨 같은 입력이면 같은 ID가 되게 한다.
- 모든 span의 `start <= end`이고 모든 관측의 부모가 목록 안에 있다(7b 테스트의 불변식 유지).

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| 새 span 구조·이름(`planning #k`·`evaluation #k`·`image`) | `obs/langfuse_sink.py`(`build_timeline`) | `export_trace`, `obs/langfuse_check.py`, `tests/test_langfuse_sink.py`, step 3의 input/output 매핑 |
| 루트 metadata `rework_count` | `obs/langfuse_sink.py` | Langfuse 화면(사용자), step 3 |
| 새 합성 기록 | `obs/langfuse_check.py`(`obs-check`가 보내는 합성 trace) | 사용자가 `make obs-check`로 새 타임라인 구조를 확인 |

**기존 단언과의 충돌 점검**: `tests/test_langfuse_sink.py`의 `build_timeline` 구조 단언은 **새 구조에 맞게 갱신**해야 한다(기대값이 바뀌는 것이므로 단언을 지우거나 부분 비교로 약화하지 않고 **같은 엄격도**로 새 이름·구간·부모를 단언한다: 루트 구간, `planning #1`·`evaluation #1` 이름과 호출 구간, generation의 부모, `image` 아래 이미지 호출, `rework` event 없음, 옛 기록 시간 없음, 결정적 ID, 모든 부모가 목록 안에 있음, 검사 관측 수 0이면 실패). `export_trace`(이벤트 종류 집합·한 번의 `batch` 호출·예외 삼킴·`tracing_enabled=False`) 단언은 불변이다. `tests/test_api_assembly.py`의 export 호출 테스트는 `build_timeline`을 부르지 않으므로 영향이 없다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`(CRITICAL: 비밀 값·실제 호출), `/docs/ADR.md`(ADR-016), `/docs/CONTRACTS.md`(Langfuse 절, 7b가 추가한 줄 포함)
- `/src/beautyads/obs/langfuse_sink.py`, `/src/beautyads/obs/langfuse_check.py`, `/src/beautyads/obs/trace.py`(`TraceRecord`·`TraceStep`·`TraceCall`), `/src/beautyads/agents/supervisor.py`(단계 이벤트 발행 지점, 읽기 전용), `/src/beautyads/agents/plan_eval.py`(읽기 전용: 평가·재작업 루프)
- `/tests/test_langfuse_sink.py`, `/tests/test_supervisor.py`(`test_events_arrive_at_stage_boundaries_including_tools_reworks_image`: 읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/obs/langfuse_sink.py`, `src/beautyads/obs/langfuse_check.py`, `tests/test_langfuse_sink.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `src/beautyads/obs/langfuse_sink.py`, `src/beautyads/obs/langfuse_check.py`, `tests/test_langfuse_sink.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1. `obs/langfuse_sink.py`의 `build_timeline`**: 위 "설계 결정"대로 다시 쓴다. `export_trace`는 바꾸지 않는다(`Observation`의 필드 이름도 그대로 둔다. 새 칸이 필요하면 `attrs`에 넣는다).

**2. `obs/langfuse_check.py`**: 합성 `TraceRecord`를 새 구조를 보여 주도록 바꾼다: 요청 하나에 `supervisor`·`research`(단계 `at` 있음), 호출 `plan`·`evaluate`·`plan`·`evaluate`(재작업 1회)·`image-plan`(각각 `duration_ms`·`ended_at`)을 시간이 겹치지 않게 순서대로 넣는다. 읽어 오는 요약(관측의 `startTime`·`endTime`·`latency`·`costDetails`·부모 관계)은 그대로 두되 **span 이름 목록**(`ask`, `supervisor`, `research`, `planning #1`, `evaluation #1`, `planning #2`, `evaluation #2`, `image`)이 서버에서 읽혀 오는지 한 줄 더 출력한다. 키·호스트 값은 출력하지 않는다.

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음, 가짜 클라이언트)**
- `tests/test_langfuse_sink.py`: (1) 위 합성 시나리오(재작업 1회·이미지 있음)에서 루트·`supervisor`·`research`·`planning #1`·`evaluation #1`·`planning #2`·`evaluation #2`·`image` span이 **이 이름과 구간**으로 나오고 span 구간은 시작 시각 순서로 겹치지 않는다(기획·평가가 번갈아), (2) 각 generation의 부모는 같은 구간의 단계 span이고 **이미지 생성 호출의 부모가 `image` span**이다, (3) `rework` event가 없고 루트 `metadata.rework_count`가 `steps`의 `rework` 이벤트 수다, (4) 단계 끝 이벤트가 같은 시각 묶음이어도(합성: `evaluation`·`rework`·`image`의 `at`이 모두 같음) 구간이 **호출 시각**에서 나오므로 `image` span 길이가 0이 아니다(이미지 호출 `duration_ms`만큼), (5) 기획안이 둘(호출 `plan`·`evaluate`·`plan`·`evaluate`)이어도 번호가 호출 순서대로 이어진다, (6) 이미지 호출 없이 `image` 단계 이벤트가 `failed`이면 시각 없는 `image_failed` event만 있다, (7) 옛 기록(단계 `at` 없음·호출 시간 없음)은 모든 관측의 시간이 `None`이고 `supervisor`·`research` span이 없고 generation이 루트 아래이며 예외가 없다, (8) 같은 입력의 두 번 호출이 **관측 ID까지 같다**, (9) 모든 span의 `start <= end`, 모든 부모가 목록 안에 있음(검사한 관측이 0이면 실패, B-FP-069), (10) generation 속성(`cost_details == {"total": cost_usd}`, 사용량, `input`·`output`·프롬프트 본문 필드 없음)과 `export_trace`의 기존 단언(이벤트 종류 집합, 한 번의 `batch` 호출, 예외 삼킴, `tracing_enabled=False`)은 **불변**.
- 시간 값은 합성 값이다(모델 출력 값을 기대값으로 굳히지 않는다).

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

- `make obs-up`·`make obs-check`·`uv run python -m beautyads.obs.langfuse_check`·`docker compose --profile obs up`을 실행하지 마라. 이유: 컨테이너 기동과 Langfuse 접속은 실제 서비스이고 사용자가 한다(AGENTS.md CRITICAL, A-FP-040). 테스트는 가짜 클라이언트로만 한다.
- `agents/supervisor.py`·`agents/plan_eval.py`·SSE `step` 이벤트의 순서·시점·키를 바꾸지 마라(이벤트를 앞당기려는 변경 포함). `TraceRecord`의 필드를 더하지 마라. 이유: 이벤트 순서는 화면 단계 표시줄이 쓰는 계약이고(`tests/test_supervisor.py`가 고정) 이 step은 이미 있는 호출 시각만 쓴다.
- 시간을 추측해 채우지 마라(시각 없는 기록은 `None`). `input`·`output`·프롬프트 본문을 이 step에서 보내지 마라. 이유: 시간을 지어내면 타임라인이 거짓이 되고, 입력·출력은 step 3의 범위와 규칙이 따로 있다.
- SDK의 비공개 `_` 속성·`opentelemetry` 직접 호출을 쓰지 마라. 전송을 요청 스레드에서 동기로 기다리게 하지 마라. 이유: 7b에서 승인한 공개 API(`api.ingestion.batch`)만 쓴다.
- 기존 `export_trace` 단언·`tests/test_langfuse_sink.py`의 다른 단언을 약화·삭제하지 마라(구조 단언은 새 구조로 같은 엄격도로 갱신). 이유: 가드를 약화하면 회귀를 못 잡는다.
