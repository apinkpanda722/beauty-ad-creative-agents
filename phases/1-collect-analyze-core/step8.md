# Step 8: slice-live-target

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P1 collect-analyze-core"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드(step 0 산출물). 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — "P1" 절의 머지 뒤 안내와 §5(첫 live에서 터질 수 있는 것)
- `/docs/CONTRACTS.md` — "로컬 환경"(OrbStack), "Neo4j" 절의 첫 live 함정(이 step은 Neo4j를 쓰지 않는다)
- `/README.md`, `/Makefile`, `/deploy/docker-compose.yml` — step 2 산출물
- `/src/beautyads/` 전체 — step 0~7 산출물(`settings`, `domain`, `store`, `obs`, `llm`, `sources`, `analysis`)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/pipeline/__init__.py`, `src/beautyads/pipeline/preflight.py`, `src/beautyads/pipeline/slice.py`, `Makefile`, `README.md`, `tests/test_slice.py`

열람 금지 경로: (없음)
수정 허용 경로: `src/beautyads/pipeline/**`, `Makefile`(`live-slice` 타깃과 `.PHONY` 추가에 한함, `verify` 타깃 불변), `README.md`(live-slice 절 추가에 한함), `tests/test_slice.py`

이 step은 P1의 끝에서 끝까지 한 줄을 조립한다: **YouTube 소재 1건 수집 → 분석 → PostgreSQL 저장**을 CLI로 확인하는 `make live-slice` 타깃이다(그래프와 에이전트는 P4·P5). `pipeline/`은 모든 런타임 계층을 import할 수 있지만 `httpx`·`psycopg`·`litellm`을 직접 import하지 않는다(`sources.youtube.httpx_get`, `store.connect`를 호출한다). **이 step 안에서는 `make live-slice`를 실행하지 않는다. 테스트는 모두 가짜 의존성으로 한다.**

소비자 테스트 점검 결과: `scripts/test_hooks.py`가 `Makefile`을 언급하지만 임시 디렉터리에 자기 `Makefile`을 만들어 쓰므로 저장소 `Makefile` 변경의 영향을 받지 않는다(확인함). 그 파일은 수정하지 않는다.

### 환경 점검 (`preflight.py`)

```python
class Problem(NamedTuple): code: str

def docker_running() -> bool                 # subprocess로 `docker info`를 짧은 시간 제한으로 호출. 실행 파일이 없거나 실패하면 False
def tcp_reachable(host: str, port: int, timeout_s: float) -> bool

def preflight(*, environ=None, env_file=DEFAULT_ENV_FILE, ledger_path: Path, caps: Mapping[str, float],
              docker_check: Callable[[], bool] = docker_running,
              tcp_check: Callable[[str, int, float], bool] = tcp_reachable) -> list[Problem]
```

점검과 이유 코드(모두 호출 전에 한다. 하나라도 있으면 시작하지 않는다):

- `ENV_MISSING:YOUTUBE_API_KEY`, `ENV_MISSING:GEMINI_API_KEY`, `ENV_MISSING:POSTGRES_PASSWORD` — 이름이 없거나 값이 공백이면. **값은 출력하지 않는다.**
- `DOCKER_DOWN` — `docker_check()`가 False
- `POSTGRES_UNREACHABLE` — `127.0.0.1`의 PostgreSQL 포트(기본 5433, `BEAUTYADS_POSTGRES_PORT`)에 연결할 수 없음
- `COST_CAP:gemini` — 원장의 Gemini 누적액이 이미 상한 이상
- `LEDGER_NOT_WRITABLE` — 원장 경로의 부모 디렉터리를 만들거나 쓸 수 없음

### 실행 (`slice.py`)

```python
class SliceStore(CreativeRepository, AnalysisRepository, Protocol): ...   # 두 저장소 Protocol을 모두 만족하는 객체

class SliceDeps(NamedTuple):
    http_get: HttpGet
    store: SliceStore
    interact: Callable[..., InteractionResult]
    channels: list[YouTubeChannel]
    now: Callable[[], datetime]

class SliceReport(BaseModel): collected: int; analyzed: dict[str, int]; stopped: str | None; items: list[dict]; gemini_total_usd: float

def run_slice(deps: SliceDeps, *, count: int, youtube_api_key: str, thinking_level: ThinkingLevel,
              window_max_s: float, length_cut_s: float, ledger_path: Path, caps: Mapping[str, float],
              out: TextIO) -> SliceReport

def main(argv: Sequence[str] | None = None, *, environ=None, out: TextIO | None = None,
         docker_check: Callable[[], bool] = docker_running,
         tcp_check: Callable[[str, int, float], bool] = tcp_reachable,
         deps_factory: Callable[[], SliceDeps] | None = None) -> int   # 모듈 끝에 `if __name__ == "__main__": raise SystemExit(main())`
```

- `main`: 인자 `--count`(기본 1, **상한 5**, 범위 밖이면 오류 종료)와 `--preflight-only`. 설정을 읽고 `preflight`를 한다. **문제가 있으면 `PREFLIGHT_FAILED <코드>`를 한 줄씩 출력하고 종료 코드 2로 끝낸다 — 이때 네트워크 호출도 DB 접속도 하지 않는다.** `--preflight-only`는 점검만 하고 0으로 끝난다. 통과하면 `deps_factory()`(기본값은 실제 의존성을 만드는 함수)로 의존성을 만들어(`store.connect(postgres_dsn())`, `apply_migrations`, `sources.youtube.httpx_get`, `llm.gemini_interact`, `load_youtube_channels(Path("config/sources.yaml"))`) `run_slice`를 부르고 요약을 출력한 뒤 0으로 끝낸다. `DailyLimitReached`·`CostCapExceeded` 등으로 멈추면 `STOPPED <사유>`를 출력하고 종료 코드 3. **`store.connect`가 `StoreConnectError`를 올리면 그 `code`(`POSTGRES_AUTH_FAILED` 또는 `POSTGRES_CONNECT_FAILED`)를 `PREFLIGHT_FAILED <코드>`로 출력하고 종료 코드 2로 끝낸다. DSN·비밀번호·예외 원문은 출력하지 않는다.** (PostgreSQL 비밀번호도 Neo4j처럼 데이터 볼륨을 처음 만들 때만 적용되므로 `.env`를 나중에 바꾸면 TCP 점검은 통과해도 여기서 인증 오류가 난다.)
- `run_slice`: 설정 순서의 채널을 하나씩 `collect_youtube`(`video_length_cut_s=length_cut_s`를 넘긴다)로 시도해 `count`개가 모일 때까지 모으되(채널 오류는 기록하고 다음 채널로, 키·쿼터 오류는 멈춤), `upsert_creatives` → `select_for_analysis`로 거른 소재만 `enqueue_analysis("hook", ...)` → `analyze_pending("hook", limit=count, ...)`. 출력은 JSON 한 줄씩(`event`·`source`·`source_id`·`url`·`status`·`hook_type`·`error_code`)과 마지막 요약(수집·분석 상태별 건수·`stopped`·`provider_total("gemini")`). **키·DSN·요청 URL의 쿼리·영상 파일 경로를 출력하지 않는다.** 영상 파일은 받지 않는다(YouTube는 주소 입력).

### Makefile과 README

- `Makefile`: `live-slice` 타깃을 추가하고(`uv run python -m beautyads.pipeline.slice`) `.PHONY`에 이름을 더한다. **`verify` 타깃은 바꾸지 않으며 `live-slice`를 호출하지 않는다.**
- `README.md`: "live-slice (P1)" 절을 추가한다. 선행 조건(OrbStack 켜기, `.env`의 키 이름 목록, `make db-up`), 실행 `make live-slice`(기본 1건)와 `python -m beautyads.pipeline.slice --preflight-only`, 정상 출력의 예(필드 이름만, 값은 쓰지 않는다), 위 이유 코드 표와 각 코드의 조치, 비용 안내(분석 1건은 약 $0.006 추정, 원장 `data/manifest/costs.jsonl`에 기록됨)를 쓴다. 또 두 가지를 적는다: (1) `make db-up` 직후에는 컨테이너가 준비되기까지 수 초가 걸리므로 잠시 기다린 뒤 실행하고 `POSTGRES_UNREACHABLE`이면 다시 시도한다. (2) 이유 코드 표에 `POSTGRES_AUTH_FAILED`·`POSTGRES_CONNECT_FAILED`를 넣고 조치를 적는다: "PostgreSQL 비밀번호는 데이터 볼륨을 처음 만들 때만 적용된다. P1은 데이터가 없으니 `.env`의 `POSTGRES_PASSWORD`를 원래 값으로 되돌리거나 볼륨을 직접 삭제한다(삭제 타깃은 만들지 않았다)."

### 반드시 있어야 하는 테스트 (`tests/test_slice.py`, 모두 가짜)

- `preflight`: 키가 없거나 공백이면 각각의 `ENV_MISSING:<이름>`, `docker_check`가 False면 `DOCKER_DOWN`, `tcp_check`가 False면 `POSTGRES_UNREACHABLE`, 원장 합계가 상한 이상이면 `COST_CAP:gemini`(임시 원장), 모두 정상이면 빈 목록. 점검 출력에 환경 변수 **값**이 없다(감시용 값을 환경에 넣고 출력에 없음을 확인한다).
- `main`: 가짜 `docker_check`·`tcp_check`를 주입해(실제 Docker·소켓을 쓰지 않는다) 키가 빠진 환경 딕셔너리에서 종료 코드 2와 `PREFLIGHT_FAILED ENV_MISSING:...` 출력, **이때 가짜 `deps_factory`가 한 번도 불리지 않음**(점검 전에 호출·접속이 없음), `--count 0`·`--count 6`은 오류 종료, `--preflight-only`는 0.
- `run_slice`(가짜 `http_get`은 `youtube_*.json` 원본에서 만든 본문을, 메모리 저장소와 가짜 `interact`를 사용): 수집된 소재가 저장소에 들어가고 분석 대상만 큐에 들어가며(`analyzable`이 `None`인 소재는 제외) 요청한 `count`를 넘지 않는다, 한 채널이 실패해도 다음 채널로 넘어간다, `DailyLimitReached`면 `stopped`가 채워지고 소재는 `pending`으로 남는다, 출력 줄이 JSON이고 키 문자열이 없다.
- `main`에서 `deps_factory`가 `StoreConnectError("POSTGRES_AUTH_FAILED")`를 올리면(가짜 `StoreConnectError`를 직접 만든다) 출력에 `PREFLIGHT_FAILED POSTGRES_AUTH_FAILED`가 있고 종료 코드 2이며 출력에 DSN·비밀번호 문자열(테스트가 넣은 감시용 값)이 없다. `POSTGRES_CONNECT_FAILED`도 같다.
- `Makefile`: `verify` 레시피 줄에 `live-`가 없고 `live-slice` 타깃과 `.PHONY` 항목이 있다.

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
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
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

- `make live-slice`를 실행하지 마라. 테스트는 가짜 의존성만 쓴다. 이유: 실제 호출·DB 접속·과금은 사용자의 live 실행이다.
- `make verify`가 `live-slice`나 실제 서비스를 호출하게 만들지 마라(`verify` 레시피에 `live-`를 넣지 않는다). 이유: `verify`는 키·네트워크·서비스 없이 통과해야 한다.
- 환경 점검이 통과하기 전에 네트워크 호출·DB 접속·모델 호출을 하지 마라. 점검 실패는 이유 코드를 출력하고 시작하지 않는다. 이유: 첫 live에서 Docker 꺼짐·키 누락·상한 초과가 호출 도중에 터지는 것을 막는다(B-FP-051).
- `--count`에 5를 넘는 값을 허용하지 마라(기본 1). 이유: 이 타깃은 연결 확인용이고 분석 1건이 약 $0.006이라 실수로 대량 호출이 나가면 상한을 갉아먹는다.
- `pipeline/`에서 `httpx`·`psycopg`·`litellm`을 직접 import하지 마라. 각 계층의 함수(`sources.youtube.httpx_get`, `store.connect`, `llm.gemini_interact`)를 호출한다. 이유: 외부 SDK 허용 계층 표(AGENTS.md)와 계층 가드가 이를 막는다.
