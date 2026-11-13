# Step 5: collect-runner

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P2 sources-pilot"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/ARCHITECTURE.md` — "데이터 흐름" 오프라인 1~2번과 "지표 정규화"
- `/docs/PHASES.md` — P2 `collect-runner` 행, §5(첫 live에서 터질 수 있는 것)
- `/src/beautyads/sources/youtube.py`, `/src/beautyads/sources/instagram.py`, `/src/beautyads/sources/split.py`, `/src/beautyads/sources/config.py` — 수집 어댑터와 분할 로더(이전 step 산출물)
- `/src/beautyads/pipeline/slice.py`, `/src/beautyads/pipeline/preflight.py` — P1의 CLI·점검 방식(주입 지점, 이유 코드, 종료 코드)
- `/src/beautyads/store/` — `collection_stats`와 업서트(이전 step 산출물)
- `/README.md`, `/Makefile`, `/.env.example`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/pipeline/collect.py`, `src/beautyads/pipeline/preflight.py`, `Makefile`, `README.md`, `.env.example`, `tests/test_collect.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/pipeline/collect.py`, `src/beautyads/pipeline/preflight.py`(수집용 점검 추가에 한함, 기존 동작 불변), `Makefile`(`live-collect` 타깃과 `.PHONY` 추가에 한함, `verify` 불변), `README.md`(live-collect 절 추가에 한함), `.env.example`(변수 이름 추가에 한함), `tests/test_collect.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 라벨 키 파일을 읽는 채점 함수, 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

YouTube와 Instagram의 **전체 수집 실행기**(`make live-collect`)를 만든다. 수집은 메타데이터만 쓰고(영상 파일은 받지 않는다) 모델을 부르지 않으므로 비용이 없다. 사용자가 11-15~16에 한 번 돌려 test 브랜드의 수집량을 확인한다. **live 순서**: `make live-collect` → 수집량 확인(`SPLIT_VOLUME_INSUFFICIENT` 유무) → (필요하면 라벨링 전에 1회 재분할: `python -m beautyads.sources.split --resplit --reason "..." --path config/brand_split.yaml`) → **그 뒤에** `make live-pilot`. 분할이 바뀌면 시범 20건이 바뀌므로 이 순서를 README에 적는다. `pipeline/`은 모든 런타임 계층을 import할 수 있지만 `httpx`·`psycopg`를 직접 import하지 않는다(어댑터와 `store`의 함수를 호출한다). **이 step 안에서는 `make live-collect`를 실행하지 않는다. 테스트는 모두 가짜 의존성으로 한다.**

소비자 테스트 점검 결과: `scripts/test_hooks.py`는 임시 디렉터리에 자기 `Makefile`을 만들어 쓰므로 영향이 없다. `tests/test_compose.py`·`tests/test_slice.py`는 저장소 `Makefile`을 읽지만 `.PHONY` 줄은 부분집합으로, `db-up`·`db-down`·`graph-reset` 레시피와 `live-slice:\n\tuv run python -m beautyads.pipeline.slice` 원문은 정확히, `verify` 레시피(뒤에 빈 줄이 있어야 한다)는 `live-`가 없음을 단언한다. 따라서 **새 타깃은 추가하되 기존 타깃의 레시피 원문·`verify` 레시피·그 뒤의 빈 줄 형식은 바꾸지 않는다.** `tests/test_slice.py`는 `pipeline.preflight`를 import하는데 이 step은 거기에 함수를 **추가**할 뿐이다. 이 파일들은 수정하지 않는다. 깨지면 고치지 말고 `blocked`로 보고한다.

> **확정된 설정(실측)**: Instagram 호출 주체 ID는 `.env`의 **`INSTAGRAM_USER_ID`**(아직 `.env`에 없다. 값은 사용자가 추가해야 한다)이고, 기본 URL은 `collect.py`의 상수 `DEFAULT_INSTAGRAM_BASE_URL = "https://graph.facebook.com/v21.0"`이며 선택 환경 변수 `BEAUTYADS_INSTAGRAM_BASE_URL`(`settings.get_setting`으로 읽는다, `settings.py`는 수정하지 않는다)로 바꿀 수 있다.

### 모듈 `pipeline/collect.py` — 시그니처

```python
RETRY_STATUSES = frozenset({500, 502, 503, 504})
RETRY_ERROR_CODES = frozenset({"YOUTUBE_REQUEST_FAILED", "INSTAGRAM_REQUEST_FAILED"})

def with_retries(get: Callable[..., Any], *, attempts: int = 3, backoff_s: Sequence[float] = (2.0, 5.0, 15.0),
                 sleep: Callable[[float], None] = time.sleep) -> Callable[..., Any]
    # get(url, params, timeout_s)를 감싼다. 응답 status가 RETRY_STATUSES이거나 예외의 .code가 RETRY_ERROR_CODES이면 backoff 후 재시도.
    # 시도가 끝나면 마지막 응답을 돌려주거나 마지막 예외를 다시 올린다. 그 밖의 상태·예외는 재시도하지 않는다. 읽기 요청만 감싼다.

class CollectDeps(NamedTuple):
    youtube_get: Callable[..., Any]
    instagram_get: Callable[..., Any]
    store: CreativeRepository
    now: Callable[[], datetime]
    sleep: Callable[[float], None]

class AccountReport(BaseModel):
    source: str; brand: str | None; account: str; fetched: int
    analyzable_true: int; analyzable_false: int; analyzable_null: int
    error: str | None; skipped: bool

class CollectReport(BaseModel):
    accounts: list[AccountReport]
    stopped: dict[str, str]              # 출처 → 중단 사유 코드
    volume_violations: list[str]
    elapsed_s: float

def estimate(*, youtube_accounts: int, instagram_accounts: int, max_per_account: int,
             youtube_s_per_call: float = 1.0, instagram_s_per_call: float = 2.0) -> dict   # 호출 수와 예상 분. 호출당 시간은 미실측 가정이다
def run_collect(deps: CollectDeps, *, sources: Collection[str], youtube_api_key: str, instagram_token: str,
                ig_user_id: str, instagram_base_url: str, youtube_channels, instagram_accounts, max_per_account: int,
                skip_recent_hours: float, only_accounts: Collection[str] | None, video_length_cut_s: float,
                split: BrandSplit, out: TextIO) -> CollectReport
def main(argv: Sequence[str] | None = None, *, environ=None, out: TextIO | None = None,
         docker_check=docker_running, tcp_check=tcp_reachable, deps_factory: Callable[[], CollectDeps] | None = None) -> int
```

- **계정 단위 수집과 저장**: 출처별로 계정(채널)을 하나씩 수집하고 **계정 하나가 끝날 때마다** `store.upsert_creatives`로 저장한다(중간에 끊겨도 앞 계정의 결과가 남는다). 한 계정의 오류는 `AccountReport.error`에 기록하고 다음 계정으로 넘어간다. 출처별 중단 사유(`YOUTUBE_KEY_INVALID`, `YOUTUBE_QUOTA`, `INSTAGRAM_TOKEN_INVALID`, `INSTAGRAM_USAGE_HIGH`, `INSTAGRAM_RATE_LIMITED`)는 **그 출처만** 멈추고 다른 출처는 계속한다. 모든 HTTP 함수는 `with_retries`로 감싼다.
- **재개**: `--skip-recent-hours H`(기본 0 = 끄기)이면 `store.collection_stats()`의 `last_collected_at`이 지금보다 `H`시간 안인 계정을 건너뛴다(`AccountReport.skipped=True`). `--accounts a,b`는 지정한 계정(YouTube handle 또는 Instagram username)만 수집한다(실패한 계정만 다시 돌릴 때). 수집은 업서트라 다시 돌려도 안전하다.
- **상한**: `--max-per-account N`(기본 150, 범위 1~1000)은 YouTube는 채널당 영상 수, Instagram은 계정당 게시물 수의 상한이다. `--sources youtube,instagram`(기본 둘 다).
- **미리보기**: `--dry-run`은 네트워크 호출과 DB 접속 없이 `estimate`로 계산한 호출 수와 예상 소요(분)를 `ESTIMATE ...` 한 줄로 출력하고 0으로 끝난다. 출력에 **"호출당 시간은 가정(미실측)"과 "YouTube 쿼터 사용량은 미확인(Cloud 콘솔에서 확인)"**을 함께 적고, Instagram은 "호출당 앱 사용량 약 0.5%(실측 추정)"를 이용해 `예상 앱 사용량 ≈ 호출 수 × 0.5%`를 함께 출력한다(예: 22계정 × 2쪽 = 44호출 ≈ 22%). YouTube 채널당 호출은 `1 + 2 * ceil(N / 50)`, Instagram 계정당 호출은 `ceil(N / 100)`로 센다.
- **환경 점검**(`preflight.py`에 수집용 함수 추가, 기존 `preflight`는 불변): `ENV_MISSING:YOUTUBE_API_KEY`, `ENV_MISSING:INSTAGRAM_ACCESS_TOKEN`, `ENV_MISSING:INSTAGRAM_USER_ID`, `ENV_MISSING:POSTGRES_PASSWORD`(사용하는 출처만 점검), `DOCKER_DOWN`, `POSTGRES_UNREACHABLE`. 하나라도 있으면 `PREFLIGHT_FAILED <코드>`를 출력하고 종료 코드 2, **그 전에는 어떤 호출도 접속도 하지 않는다**. `StoreConnectError`는 코드를 `PREFLIGHT_FAILED <코드>`로 출력한다(DSN·비밀번호 미출력).
- **보고**: 계정마다 JSON 한 줄(`event`, `source`, `brand`, `account`, `fetched`, `analyzable_true`·`false`·`null`, `error`)을 진행 중에 출력하고, 끝에 요약을 출력한다. 요약에는 출처·브랜드별 `analyzable` 분포, 중단 사유, **`config/brand_split.yaml`의 분할로 본 dev·test별 `analyzable_true` 합계와 `volume_violations`**(`store.collection_stats()` 전체를 기준으로 `volume_violations`를 부른다. 위반이 있으면 `SPLIT_VOLUME_INSUFFICIENT`를 함께 출력하지만 종료 코드는 바꾸지 않는다), 총 소요를 담는다. 중단이 있으면 종료 코드 3, 그 밖에 0. 키·토큰·URL 쿼리·`media_url`은 출력하지 않는다.
- `Makefile`: `live-collect` 타깃(`uv run python -m beautyads.pipeline.collect`)을 추가하고 `.PHONY`에 더한다. **`verify` 타깃은 바꾸지 않고 `live-collect`를 호출하지 않는다.** `README.md`: "live-collect (P2)" 절에 선행 조건(OrbStack, `make db-up`, `.env` 키 이름들), 사용법(`--dry-run`으로 먼저 호출 수와 시간을 보고 실행, `--max-per-account`, 재개 방법), 이유 코드 표, 결과 읽는 법(`SPLIT_VOLUME_INSUFFICIENT`가 나오면 라벨링 시작 전에 한해 1회 재분할할 수 있음)과 위 **live 순서**(수집 → 수집량 확인 → 필요 시 재분할 → 그 뒤에 `make live-pilot`)를 쓴다. `INSTAGRAM_USER_ID`는 사용자가 `.env`에 값을 추가해야 한다는 안내를 넣는다. `.env.example`에 `INSTAGRAM_USER_ID`(이름만)와 주석 처리한 `# BEAUTYADS_INSTAGRAM_BASE_URL=`(선택)을 추가한다.

### 반드시 있어야 하는 테스트 (`tests/test_collect.py`, 모두 가짜)

- `with_retries`: 503이 두 번 난 뒤 성공하면 3번 호출되고 `sleep`이 `backoff_s`의 앞 두 값으로 불린다, `INSTAGRAM_REQUEST_FAILED`·`YOUTUBE_REQUEST_FAILED` 예외도 재시도된다, 400·401·403·404와 다른 예외는 재시도하지 않는다, 시도가 끝나면 마지막 응답(또는 예외)이 나온다.
- `run_collect`(가짜 HTTP 함수는 `youtube_*.json`·`instagram_*.json` 원본에서 만든 본문, 메모리 저장소): 계정 하나가 실패해도 나머지가 저장된다, 계정 하나가 끝날 때마다 저장된다(중간에 예외가 나도 앞 계정은 저장소에 남음), YouTube 쿼터 중단이 Instagram 수집을 막지 않고 **`INSTAGRAM_RATE_LIMITED` 중단은 YouTube 수집을 막지 않으며 이후 Instagram 계정을 호출하지 않는다**, `--skip-recent-hours`·`--accounts` 동작, 저장되는 모든 소재에 `brand`·`account`가 채워진다, `AccountReport`의 `analyzable` 분포가 저장된 소재와 일치, 보고·출력에 키·토큰·`media_url` 문자열이 없다(감시용 값을 주입해 확인).
- `estimate`와 `--dry-run`: 호출 수 공식이 맞고(기대값은 테스트가 같은 공식을 쓰지 말고 작은 입력의 손계산 값으로 둔다), `--dry-run`이 **의존성 생성 함수·HTTP 함수를 한 번도 부르지 않는다**.
- `main`: 키가 빠진 환경에서 종료 코드 2와 `PREFLIGHT_FAILED ENV_MISSING:...`, 이때 `deps_factory`가 불리지 않음(가짜 `docker_check`·`tcp_check` 주입), `--max-per-account 0`·`1001` 오류 종료, `StoreConnectError`를 코드로 출력하고 DSN·비밀번호가 없음, 중단이 있으면 종료 코드 3.
- 분할 보고: 가짜 `collection_stats`로 dev·test 합계가 `brand_group`에 맞게 나뉘고 수집량이 모자라면 `SPLIT_VOLUME_INSUFFICIENT`가 출력되되 종료 코드는 0이다. 분할 파일에 없는 브랜드의 소재는 보고에서 `unassigned`로 따로 센다(예외로 끝내지 않는다).
- `Makefile`: `verify` 레시피 줄에 `live-`가 없고 `live-collect` 타깃과 `.PHONY` 항목이 있다.

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

- `make live-collect`를 실행하지 마라. 테스트는 가짜 의존성만 쓴다. 이유: 실제 호출·DB 접속은 사용자의 live 실행이다.
- `make verify`가 `live-collect`나 실제 서비스를 호출하게 만들지 마라(`verify` 레시피에 `live-`를 넣지 않는다). 이유: `verify`는 키·네트워크·서비스 없이 통과해야 한다.
- 환경 점검이 통과하기 전에 네트워크 호출·DB 접속을 하지 마라. `--dry-run`도 호출·접속을 하지 않는다. 이유: 첫 live에서 Docker 꺼짐·키 누락이 호출 도중에 터지는 것을 막는다(B-FP-051).
- 한 계정의 실패나 한 출처의 중단으로 전체 수집을 끝내지 마라. 중단은 그 출처만 멈춘다. 이유: 계정·출처 하나의 결함이 다른 출처의 수집을 막으면 안 된다(A-FP-030).
- 쓰기 요청(POST 등)이나 400대 응답을 재시도하지 마라. `with_retries`는 읽기 요청의 500·502·503·504와 연결 실패만 다시 시도한다. 이유: 인증·요청 오류를 반복하면 사용량 한도만 깎는다.
- 수집량 기준 미달을 보고 분할을 바꾸거나 `config/brand_split.yaml`을 고치지 마라. 보고만 한다. 이유: 재분할은 사람이 이유를 적고 1회만 하는 사전 등록 절차다.
