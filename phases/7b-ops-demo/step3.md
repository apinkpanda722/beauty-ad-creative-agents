# Step 3: langfuse-sink

## 설계 검토 기록

**배경(P5에서 이월한 8b, P7 승인 추가 요구 3-b·3-e)**: 요청 하나의 trace를 Langfuse로 보내 **에이전트별 타임라인과 비용**을 화면에서 볼 수 있게 한다(ADR-016: 기본은 로컬 JSONL, Langfuse는 compose 선택 profile `obs`). step 2(8a)가 `TraceRecord`에 시간을 넣었으므로 이 step은 (1) `obs/langfuse_sink.py`가 그 기록을 시간 구간으로 보내고, (2) compose `obs` profile과 환경 변수를 더하고, (3) 서버 없이 시간 필드가 화면에 보이는지 사용자가 확인하는 도구(`make obs-check`)를 만든다. **"에이전트별 지연과 비용을 Langfuse에서 관측했다"는 문구는 사용자가 실제 화면에서 지연이 보이는 것을 확인한 뒤에만 DEMO.md·README·상세 페이지에 쓴다**(조언 세션 요구). 이 step의 완료는 그 확인이 아니다.

**외부 계약(`docs/CONTRACTS.md` Langfuse 절 332~346행, 원본 `tests/fixtures/contracts/langfuse_probe.json`)과 이번에 새로 확인한 것**:
- 측정된 것(2026-11-12): 서버 `langfuse/langfuse:3.225.11`, SDK **`langfuse==3.15.0` 고정**, OTLP(`/api/public/otel`)로 보낸 trace가 REST로 읽힌다. `user_id`에 `tenant_id`를 넣으면 `GET /api/public/traces?userId=`가 그 테넌트만 돌려준다. **서버가 모르는 모델(`gpt-6.1-terra`)은 `cost_details`를 주지 않으면 비용이 비어 합계에서 빠진다 → 항상 원장의 비용을 `cost_details`로 보낸다.** 서버가 꺼져 있으면 `flush`·`shutdown`은 멈추지 않지만 **`auth_check()`는 `False`가 아니라 `ConnectError`를 올린다** → 모든 예외를 삼켜 로컬 JSONL로 폴백한다. 같은 프로세스에서 같은 공개 키로 `Langfuse(...)`를 다시 만들면 다른 host를 줘도 기존 클라이언트를 재사용한다(테스트는 키를 다르게 한다). 읽은 관측 필드: `type`, `model`, `usage`, `usageDetails`, `costDetails`, `startTime`·`endTime`·`latency`(관측 키 목록에 있음), `parentObservationId`, `metadata`.
- **이번에 확인한 것(2026-11-20, 임시 가상환경에 `langfuse==3.15.0`을 설치해 시그니처만 조회, 서버 접속 없음)**: SDK 3.15.0의 공개 추적 API(`Langfuse.start_span`·`start_generation`·`start_observation`)에는 **시작 시각 인자가 없고**(종료만 `end(end_time=...)`) 사후 기록으로는 시작 시각을 지정할 수 없다. 대신 SDK가 제공하는 타입 있는 REST 클라이언트 **`Langfuse(...).api.ingestion.batch(batch=[...])`**의 이벤트 본문(`CreateSpanBody`·`CreateGenerationBody`·`TraceBody`)이 `start_time`·`end_time`·`cost_details`·`usage_details`·`parent_observation_id`를 받는다. **이 경로를 쓴다**(새 패키지 없음, 비공개 `_` 속성을 쓰지 않는다).
- **미확인(CONTRACTS에 "미확인"으로 적는다)**: 서버 3.225.11이 이 ingestion 이벤트의 시간·`cost_details`를 받아 **Langfuse 화면 타임라인에 그리는지**. 사용자가 `make obs-up` 후 `make obs-check`를 실행해 확인하고 그 결과로 CONTRACTS를 갱신한다(Codex는 서버를 띄우지 않는다). 컨테이너 5개의 메모리·처음 이미지 받는 시간도 미확인이다.

**설계 결정**:
- `settings.py`에 `langfuse_settings(*, environ=None, env_file=DEFAULT_ENV_FILE) -> LangfuseSettings | None`을 더한다(`.env`를 읽는 유일한 함수 규칙). `LANGFUSE_HOST`(기본 `http://127.0.0.1:3001`), `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`를 `get_setting`으로 읽고 **키 둘 중 하나라도 없거나 빈 값이면 `None`**(= Langfuse 꺼짐, 로컬 JSONL만). 빈 문자열·공백은 기본값을 덮지 않는다(B-FP-030). 값은 로그·예외·trace에 남기지 않는다.
- `obs/langfuse_sink.py`:
  - 순수 함수 `build_timeline(record: TraceRecord) -> list[Observation]`(SDK 없이 테스트): `Observation = {id, kind("span"|"generation"|"event"), name, start, end, parent_id, attrs}`. 결정적 ID는 `trace_id`와 순번에서 만든다(재전송해도 같은 ID).
  - 구간 규칙: **루트 span `ask`** = `[started_at, started_at + duration_ms]`. `steps[].at`이 있으면 경계 시각의 연속으로 단계 span을 만든다: 첫 경계 앞 구간은 `[started_at, supervisor 끝 at]`(이름 `supervisor`), `research`는 `[앞 경계, research 끝 at]`, `planning`이 시작 이벤트(`phase == "start"`)이므로 기획안마다 `[planning 시작 at, 그 뒤 첫 evaluation 끝 at]`을 span `plan`으로(기획안이 여러 개면 각각), `rework`는 시각 `at`의 event, `image`는 `[앞 경계, image 끝 at]`, `supervisor`의 `done`은 span이 아니라 루트의 끝이다. **generation**은 `duration_ms`와 `ended_at`이 있는 호출마다 `[ended_at − duration_ms, ended_at]`이고 부모는 **그 구간을 포함하는 가장 작은 단계 span**(없으면 루트)이다. 단계 시각(`at`)이 하나도 없거나 호출에 시간이 없는 **옛 기록은 시간 없이**(start·end `None`) 보낸다(조용히 추측한 시간을 넣지 않는다).
  - generation 속성: `name = purpose`, `model`, `usage_details`(`input`·`output`, 캐시 토큰이 0이 아니면 `cache_read_input_tokens`, 합계 `total`), **`cost_details = {"total": cost_usd}`(항상, 원장 비용)**, `metadata = {purpose, reasoning_effort, cost_source, thought_tokens}`. **프롬프트·응답 본문·`input`/`output` 필드는 보내지 않는다**(trace가 메타데이터만 담는 규칙).
  - trace: `id = trace_id`, `name = "ask"`, `user_id = tenant_id`, `timestamp = started_at`, `tags`는 `kind:<kind>`·`outcome:<ok|error>`, `metadata = {kind, intent, outcome, cost_total_usd, text_spent_usd, limit_hit, prompt_versions}`. `session_id`는 보내지 않는다(`thread_id`가 trace에 없다).
  - `export_trace(record, *, settings, client_factory=Langfuse) -> bool`: 설정이 `None`이면 `False`. 아니면 `client_factory(public_key=..., secret_key=..., host=..., tracing_enabled=False, timeout=3)`로 클라이언트를 만들고 `client.api.ingestion.batch(batch=[trace-create, span-create..., generation-create..., event-create...])`를 **한 번** 보낸다(이벤트 `id`는 이벤트마다 새 UUID, 본문 `id`는 위 결정적 ID). **모든 예외를 삼키고 `False`**를 돌려준다(예외 메시지·키·본문을 기록하지 않는다). 응답에 오류 항목이 있으면 `False`.
- `api/assembly.py`: `ask()`의 `finally`에서 `append_trace(...)` **뒤에** `export_trace`를 **데몬 스레드**로 부른다(Langfuse가 느리거나 꺼져 있어도 응답을 늦추지 않는다, 기존 `except Exception: pass` 안에서). 설정은 `ask()`가 아니라 조립 시점에 한 번 읽는다(`langfuse_settings(environ=..., env_file=...)`). 로컬 JSONL 기록은 항상 먼저 일어나고 Langfuse 실패와 무관하다.
- `obs/langfuse_check.py`(사용자 실행용 `python -m beautyads.obs.langfuse_check [preflight]`): `preflight`는 compose `obs` 서버용 필수 환경 변수 이름이 비어 있지 않은지만 검사해 부족한 **이름**을 `PREFLIGHT_FAILED OBS_ENV_MISSING:<이름>`으로 출력(종료 코드 2, 값 출력 없음). 인자 없이 실행하면 합성 `TraceRecord`(합성 시각 3개 단계·호출 2개, 비용 합성값)를 `export_trace`로 보내고 SDK로 다시 읽어(`client.api.trace.get(trace_id)`, 최대 15초 폴링) **관측의 `startTime`·`endTime`·`latency`·`costDetails`가 있는지와 부모 관계**를 요약 한 줄씩 출력한다(키·호스트 값 출력 없음, 종료 코드 0 성공·3 읽기 실패). 이 도구가 CONTRACTS의 미확인을 닫는 근거다.
- `deploy/docker-compose.yml`에 **profile `obs`**로 서비스를 더한다(기본 `up`에는 안 뜬다): `langfuse-web`(`langfuse/langfuse:3.225.11`, 호스트 `127.0.0.1:3001:3000`), `langfuse-worker`(`langfuse/langfuse-worker:3.225.11`), `langfuse-postgres`(`postgres:17.11`, **기존 postgres와 별도 컨테이너·볼륨** `beautyads_langfuse_pgdata`, `POSTGRES_DB=langfuse` — 기존 볼륨의 초기화 스크립트가 빈 볼륨에서만 돌기 때문이다), `clickhouse`(`clickhouse/clickhouse-server:25.12.9.61`), `redis`(`redis:7.4.11`), `minio`(`cgr.dev/chainguard/minio@sha256:4cf4831a2bbcf13ddca09c1cbcc9faff716dd3c4247e0babc32864b8ee8e0034`: 이 맥에 있는 이미지의 다이제스트이고 CONTRACTS에 태그가 없었다. **`docker image inspect`의 `Descriptor.mediaType`이 `application/vnd.oci.image.index.v1+json`이라 이 다이제스트는 아키텍처 전용이 아니라 멀티 아키텍처 인덱스 다이제스트다**(2026-11-20 확인, 로컬 이미지는 arm64). 인덱스 다이제스트이므로 다른 아키텍처에서도 같은 값으로 받을 수 있다고 보지만 **실제 다른 환경에서 pull되는지는 미확인**이다). Langfuse 서버 설정(DB·ClickHouse·Redis·S3 연결, `NEXTAUTH_URL=http://127.0.0.1:3001`, 무인 초기화 `LANGFUSE_INIT_ORG_ID`·`LANGFUSE_INIT_PROJECT_ID`·`LANGFUSE_INIT_PROJECT_PUBLIC_KEY`·`LANGFUSE_INIT_PROJECT_SECRET_KEY`·`LANGFUSE_INIT_USER_EMAIL`·`LANGFUSE_INIT_USER_NAME`·`LANGFUSE_INIT_USER_PASSWORD`)은 Langfuse v3 자체 호스팅 구성의 환경 변수 이름을 따른다(CONTRACTS 338~339행). 비밀 값은 모두 `.env`에서 `${변수:-}` 참조로 받는다(**`${변수:?}`는 쓰지 않는다**: compose는 활성화되지 않은 profile의 변수도 해석해, 기본 `make db-up`이 `.env`에 Langfuse 값이 없다고 실패하게 된다). 필요한 변수 이름(값 없이 `.env.example`에 주석으로 적는다): `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`(초기화 프로젝트 키와 같은 값을 쓴다), `LANGFUSE_INIT_USER_EMAIL`, `LANGFUSE_INIT_USER_PASSWORD`, `LANGFUSE_NEXTAUTH_SECRET`, `LANGFUSE_SALT`, `LANGFUSE_ENCRYPTION_KEY`, `LANGFUSE_PG_PASSWORD`, `LANGFUSE_CLICKHOUSE_PASSWORD`, `LANGFUSE_REDIS_AUTH`, `LANGFUSE_MINIO_PASSWORD`.
- `Makefile`: `.PHONY: obs-up obs-down obs-check` 블록(`demo-clarify`처럼 별도 블록): `obs-up` = `uv run python -m beautyads.obs.langfuse_check preflight` 다음 `$(COMPOSE) --profile obs up -d`, `obs-down` = `$(COMPOSE) --profile obs stop` 후 `rm -f`(**볼륨은 지우지 않는다**), `obs-check` = `uv run python -m beautyads.obs.langfuse_check`. `verify` 레시피는 바꾸지 않는다.
- `pyproject.toml`·`uv.lock`: `uv add langfuse==3.15.0`(승인된 고정 버전). 설치된 버전과 함께 들어온 의존성 목록 변화를 `summary`에 적는다.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `LangfuseSettings`·`langfuse_settings` | `settings.py` | `obs/langfuse_check.py`, `api/assembly.py`(조립) |
| `build_timeline`·`export_trace` | `obs/langfuse_sink.py` | `api/assembly.py`(`ask()`), `obs/langfuse_check.py`, 테스트 |
| `obs-up`·`obs-down`·`obs-check` | `Makefile` | 사용자, DEMO.md(step 5) |
| profile `obs` 서비스 | `deploy/docker-compose.yml` | `tests/test_compose.py`(기존 단언은 부분 집합·태그·루프백 검사) |
| 환경 변수 이름 | `.env.example` | 사용자 |

**기존 단언과의 충돌 점검**: `tests/test_compose.py`는 `{"postgres","neo4j"} <= services`(부분 집합)·**모든 서비스 이미지에 명시 태그가 있고 `latest`가 아님**(minio는 다이제스트 고정 `이름@sha256:...`가 `partition(":")`로 태그 자리를 채워 통과한다)·**모든 `ports`가 `127.0.0.1:`로 시작하고 호스트 포트가 5432·3000·7474·7687이 아님**(3001은 통과)·postgres·neo4j 비밀번호의 `${변수:?...}` 형식을 검사한다 → 새 서비스가 이 규칙을 지키게 쓰고 기존 단언은 바꾸지 않는다. `tests/test_architecture.py`는 `langfuse`를 `obs`에서만 허용한다(새 import는 `obs/`에만). `settings.py`를 읽는 `tests/test_settings*.py`·`tests/test_caps_guard.py`(조립이 설정 상한을 깎지 않는지 AST 스캔)에 영향이 없음을 확인한다. `api/assembly.py`는 `tests/test_api_assembly.py`가 가짜 서비스로 조립해 `ask()`의 trace 기록을 검사하므로 Langfuse 설정이 없는 기본 경로에서 **동작·호출 목록이 그대로**여야 한다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`(계층 경계, 외부 SDK 표, CRITICAL: 비밀 값·실제 호출·키를 trace에 남기지 않음), `/docs/ADR.md`(ADR-016), `/docs/CONTRACTS.md`(Langfuse 절 332~346행), `/docs/ARCHITECTURE.md`(관측)
- `/tests/fixtures/contracts/langfuse_probe.json`(읽기 전용: 실제 관측 키 목록)
- `/src/beautyads/obs/trace.py`(step 2가 넣은 `TraceStep.at`·`TraceCall.duration_ms`·`ended_at`), `/src/beautyads/obs/ledger.py`, `/src/beautyads/obs/__init__.py`, `/src/beautyads/settings.py`
- `/src/beautyads/api/assembly.py`(`ask()`의 `finally` 안 trace 기록부), `/deploy/docker-compose.yml`, `/Makefile`, `/.env.example`, `/pyproject.toml`
- `/tests/test_compose.py`, `/tests/test_trace.py`, `/tests/test_api_assembly.py`(trace 기록 테스트), `/tests/test_architecture.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/obs/langfuse_sink.py`, `src/beautyads/obs/langfuse_check.py`, `src/beautyads/settings.py`, `src/beautyads/api/assembly.py`, `deploy/docker-compose.yml`, `Makefile`, `.env.example`, `pyproject.toml`, `uv.lock`, `docs/CONTRACTS.md`, `tests/test_langfuse_sink.py`, `tests/test_compose.py`, `tests/test_api_assembly.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `src/beautyads/obs/langfuse_sink.py`, `src/beautyads/obs/langfuse_check.py`, `src/beautyads/settings.py`, `src/beautyads/api/assembly.py`, `deploy/docker-compose.yml`, `Makefile`, `.env.example`, `pyproject.toml`, `uv.lock`, `docs/CONTRACTS.md`, `tests/test_langfuse_sink.py`, `tests/test_compose.py`, `tests/test_api_assembly.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

위 "설계 결정"을 구현한다. `uv add langfuse==3.15.0`을 실행한다(승인된 고정 버전, 네트워크 허용). `docs/CONTRACTS.md`의 Langfuse 절에는 (1) "SDK 3.15.0 공개 추적 API에 시작 시각 인자가 없고 `api.ingestion.batch`의 이벤트 본문이 `start_time`·`end_time`·`cost_details`를 받는다(2026-11-20, 시그니처 조회)", (2) **미확인**: "서버 3.225.11이 ingestion 이벤트의 시간으로 타임라인을 그리는지는 `make obs-check` 실행 뒤 갱신"을 **추가**한다(기존 측정 줄은 고치지 않는다).

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음, 가짜 클라이언트 주입)**
- `tests/test_langfuse_sink.py`(새): (1) `langfuse_settings`: 키 하나라도 없음·빈 문자열·공백이면 `None`, 호스트 기본값, 빈 호스트 값이 기본값을 덮지 않음. (2) `build_timeline`: 합성 `TraceRecord`(단계 `at` 4개·기획안 1개·호출 2개)에서 루트가 `[started_at, started_at+duration_ms]`, 단계 span 이름과 구간(첫 경계·research·plan(planning 시작 → evaluation 끝)), rework event, **generation이 `[ended_at−duration_ms, ended_at]`이고 부모가 그 구간을 포함하는 가장 작은 단계 span**, 모든 구간이 `start <= end`, 모든 관측의 부모가 목록 안에 있음(검사한 관측이 0이면 실패, B-FP-069). (3) 기획안이 둘이면 plan span이 둘. (4) **옛 기록(단계 `at` 없음·호출 `duration_ms` 없음)은 시간 없이**(start·end `None`) 나가고 예외가 없다. (5) generation 속성: `cost_details == {"total": cost_usd}`가 **항상** 있고(비용 0도 포함), `usage_details`의 토큰, 캐시 토큰 0이면 `cache_read_input_tokens` 없음, **`input`·`output`·프롬프트·메시지 본문 필드 없음**(합성 비밀 문자열이 결과 어디에도 없음). (6) 결정적 ID: 같은 입력이면 같은 ID. (7) `export_trace`: 설정 `None`이면 `False`이고 `client_factory`가 호출되지 않는다, 가짜 클라이언트의 `api.ingestion.batch`가 **한 번** 호출되고 그 이벤트 종류 집합이 trace·span·generation(·event), 가짜가 예외를 올리면 `False`이고 예외 메시지(합성 비밀)가 반환·출력에 없음, 응답에 오류 항목이 있으면 `False`. (8) 클라이언트 생성 인자에 `tracing_enabled=False`·`timeout`이 있음.
- `tests/test_api_assembly.py`(케이스 추가에 한함): (9) Langfuse 설정이 없으면 `ask()` 후 `export_trace`가 불리지 않고 기존 trace 기록 테스트가 그대로 통과, (10) 설정이 있으면 `append_trace` **뒤에** `export_trace`가 데몬 스레드로 불리고(가짜 주입, 스레드 종료를 기다리는 장치로 순서 단언이 아니라 호출 여부·인자 단언), 가짜 `export_trace`가 예외를 올려도 `ask()` 결과가 바뀌지 않는다.
- `tests/test_compose.py`(케이스 추가에 한함): (11) `obs` 서비스 6개가 모두 `profiles: ["obs"]`를 가지고 기본 서비스(postgres·neo4j)에는 profile이 없음, (12) 새 서비스 이미지는 위 고정 태그·다이제스트와 같음, (13) 새 서비스의 비밀 값 환경 변수가 `${변수:-}` 형식이고 `:?` 형식이 **없음**, (14) `langfuse-postgres`가 별도 볼륨(`beautyads_langfuse_pgdata`)을 쓰고 기존 `beautyads_pgdata`를 참조하지 않음, (15) Makefile의 `obs-up`·`obs-down`·`obs-check`가 별도 `.PHONY` 블록이고 `verify` 본문에 `obs-`가 없으며 `obs-down`이 `volume rm`·`down -v`를 쓰지 않음.
- 시간·비용 값은 합성 값이다(모델 출력 값을 기대값으로 굳히지 않는다).

## Acceptance Criteria

```bash
uv add langfuse==3.15.0   # 승인된 고정 버전(네트워크 허용, 이 step에서만)
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

- `make obs-up`·`make obs-down`·`make obs-check`·`uv run python -m beautyads.obs.langfuse_check`·`docker compose --profile obs up`을 실행하지 마라. 이유: 컨테이너 기동·Langfuse 접속은 실제 서비스이고 이미지 pull이 든다(AGENTS.md CRITICAL, A-FP-040). 확인은 사용자가 한다. 테스트는 가짜 클라이언트로만 한다.
- 프롬프트·응답 본문·`input`/`output`을 Langfuse로 보내지 마라. 키·호스트·예외 메시지를 로그·반환·trace에 남기지 마라. 이유: trace는 메타데이터만 담고, 비밀 값은 어디에도 남기지 않는다(AGENTS.md CRITICAL, ADR-016).
- SDK의 비공개 속성(`_`로 시작하는 것)이나 `opentelemetry` 직접 호출을 쓰지 마라. Langfuse 전송을 요청 처리 스레드에서 동기로 기다리게 하지 마라. 이유: 공개 API(`api.ingestion.batch`)만 쓴다. 느리거나 꺼진 Langfuse가 응답을 늦추면 안 된다(CONTRACTS: 서버 꺼짐에서도 멈추지 않는 동작만 측정됨).
- 단계·호출의 시간을 추측해 채우지 마라(시각이 없는 옛 기록은 `None`으로 보낸다). `cost_details`를 빼지 마라. 이유: 시간을 지어내면 타임라인이 거짓이 되고, `cost_details`가 없으면 서버가 모르는 모델 비용이 합계에서 빠진다(CONTRACTS 343행).
- compose의 기본 서비스(postgres·neo4j)·기존 볼륨·포트를 바꾸거나 `${변수:?}`를 새 서비스에 쓰지 마라. `docs/CONTRACTS.md`의 기존 측정 줄을 고치지 마라. 이유: 기본 `make db-up`이 Langfuse 변수 없이 계속 동작해야 한다(기존 `test_compose.py` 단언). 측정값은 실측 뒤에만 바꾼다.
