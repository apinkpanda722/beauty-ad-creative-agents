# Step 13: pilot-live-target

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P2 sources-pilot"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P2 `pilot-live-target` 행과 live 순서(수집 → 수집량 확인 → 필요 시 재분할 → 그 뒤에 시범)
- `/docs/COST_ESTIMATE.md` — "보정" 절(thought 토큰, 공급사별 상한)
- `/src/beautyads/pipeline/analyze.py`, `/src/beautyads/pipeline/media_flow.py`, `/src/beautyads/pipeline/collect.py`, `/src/beautyads/pipeline/preflight.py` — 이전 step 산출물(읽기만. `docker_running`·`tcp_reachable`·점검 방식을 따른다)
- `/src/beautyads/eval/pilot.py`, `/src/beautyads/eval/sheets.py`, `/src/beautyads/sources/split.py` — 이전 step 산출물
- `/src/beautyads/pipeline/slice.py` — P1 CLI의 주입 방식(`deps_factory`, 점검 함수, 종료 코드)
- `/README.md`, `/Makefile`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/pilot_run.py`, `Makefile`, `README.md`, `tests/test_pilot.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/pilot_run.py`, `Makefile`(`live-pilot` 타깃과 `.PHONY` 추가에 한함, `verify` 불변), `README.md`(live-pilot 절 추가에 한함), `tests/test_pilot.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 라벨 키 파일을 읽는 채점 함수, 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

`make live-pilot`: **dev 브랜드에서 시범 20건을 골라 `thinking_level`이 다른 두 실행(minimal, default)으로 분석하고 블라인드 라벨링 시트를 만든다.** 사용자는 이 시트로 11-17~18에 시범 20건을 라벨링한다. **이 모듈은 `eval/`에 둔다**: 시범 실행기는 선정·시트(`eval.pilot`, `eval.sheets`)를 쓰는데 AGENTS.md 계층 표상 **다른 계층은 `eval`을 import할 수 없다**(`pipeline/`에 두면 계층 가드가 실패한다). `eval/`은 모든 계층을 import할 수 있지만 `httpx`·`psycopg`·`litellm`을 직접 import하지 않는다(각 계층의 함수를 부른다). **이 step 안에서는 `make live-pilot`을 실행하지 않는다. 테스트는 모두 가짜 의존성으로 한다.**

소비자 테스트 점검 결과: `scripts/test_hooks.py`는 임시 디렉터리에 자기 `Makefile`을 만들어 쓰므로 영향이 없다. `tests/test_compose.py`·`tests/test_slice.py`(그리고 수집 step의 `tests/test_collect.py`)는 저장소 `Makefile`을 읽지만 `.PHONY`는 부분집합으로, 기존 타깃의 레시피 원문은 정확히, `verify` 레시피는 `live-`가 없음을 단언한다. 따라서 **새 타깃은 추가하되 기존 타깃의 레시피 원문·`verify` 레시피·그 뒤의 빈 줄 형식은 바꾸지 않는다.** 이 step은 `pipeline/preflight.py`를 **고치지 않는다**(그 모듈의 `docker_running`·`tcp_reachable`을 import해 쓸 뿐이다). 이 파일들은 수정하지 않는다. 깨지면 고치지 말고 `blocked`로 보고한다.

### 모듈 `eval/pilot_run.py` — 시그니처

```python
RUN_TAGS = ("minimal", "default")        # thinking_level 값과 같다
DEFAULT_OUT_DIR = Path("data/interim/pilot")

class PilotDeps(NamedTuple):
    analysis: AnalysisDeps               # 이전 step의 배치 의존성
    store: <CreativeRepository & AnalysisRepository>
    now: Callable[[], datetime]

def estimate(*, n: int, runs: int, content_type_window_s: float, full_window_s: float,
             tokens_per_second: float = 91.0) -> dict      # 계획 호출 수 범위와 입력 토큰 추정. 비용(원·달러)은 계산하지 않는다
def run_pilot(deps: PilotDeps, *, n: int, seed: int, content_type_window_s: float, full_window_s: float,
              split: BrandSplit, split_sha256: str, ledger_path: Path, caps: Mapping[str, float],
              interact: Callable[..., InteractionResult], out_dir: Path, out: TextIO) -> PilotReport
def main(argv: Sequence[str] | None = None, *, environ=None, out: TextIO | None = None,
         docker_check=docker_running, tcp_check=tcp_reachable, deps_factory: Callable[[], PilotDeps] | None = None) -> int
```

- **환경 점검**(이 모듈에 시범용 점검 함수 `preflight_pilot`을 둔다. 기존 `pipeline/preflight.py`는 바꾸지 않는다. 하나라도 있으면 `PREFLIGHT_FAILED <코드>`를 출력하고 종료 코드 2, **그 전에는 어떤 호출도 접속도 하지 않는다**): `ENV_MISSING:GEMINI_API_KEY`, `ENV_MISSING:POSTGRES_PASSWORD`, `ENV_MISSING:INSTAGRAM_ACCESS_TOKEN`·`ENV_MISSING:INSTAGRAM_USER_ID`(시범 대상에 Instagram이 있을 때. 대상을 알 수 없는 점검 단계에서는 둘 다 점검한다), `DOCKER_DOWN`, `POSTGRES_UNREACHABLE`, `COST_CAP:gemini`, `LEDGER_NOT_WRITABLE`, 분할 파일 문제 `PILOT_SPLIT_FILE_INVALID`(`load_brand_split` 실패). `StoreConnectError`는 코드를 출력한다(DSN·비밀번호 미출력).
- **수집량 점검(코드로 강제)**: 점검을 통과한 뒤 저장소에 접속해 `collection_stats()`로 `volume_violations(split, ...)`를 계산한다. **위반이 하나라도 있으면 `PILOT_SPLIT_NOT_VERIFIED`를 출력하고 종료 코드 2**(수집량이 모자란 분할로 시범을 뽑지 않는다. 분할이 바뀌면 시범 20건이 바뀌기 때문이다). `analyzable`이 `True`인 dev 소재가 하나도 없으면 `PILOT_NO_COLLECTION`. 이 점검은 `--skip-volume-check`로 건너뛸 수 없다.
- **실행 흐름**: ① `list_creatives(brands=dev, sources=(youtube, instagram), analyzable_only=True)` → `select_pilot(..., n, seed)`로 선정(모자라면 `PILOT_SHORTFALL <k>`를 출력하고 계속) ② 실행 태그마다(`minimal`, `default` 순서) `enqueue_analysis(f"content_type@{태그}", 선정 소재)` 뒤 `run_analysis(..., only_keys=선정 키, run=AnalysisRun(thinking_level=태그, run_tag=태그, purpose=f"pilot-{태그}", ...), retry_failed=False)`. **두 번째 실행은 첫 번째 실행에서 `DAILY_LIMIT`·`COST_CAP`으로 멈췄다면 시작하지 않는다.** ③ 선정 소재의 세 축 종류 × 두 태그의 결과를 `get_job_results`로 모아 `build_blind_sheet`(`split_sha256`는 `sha256_of`로 계산한 분할 파일 해시)·`write_sheet_files`로 `out_dir`에 쓴다 ④ 요약을 출력한다(실행 태그별 상태 분포, 이번 실행의 `gemini_cost_usd`, 쓴 파일 경로(시트·코드북·`pilot_instructions.md`·키), `split_sha256`, 라벨링 안내: **"키 파일(pilot_key.json)은 라벨링을 마치기 전에 열지 마세요"**).
- **옵션**: `--n`(기본 20, 1~40), `--seed`(기본 20261112), `--out-dir`(기본 `data/interim/pilot`, `data/interim` 밖이면 오류 종료), `--content-type-window-s`(기본 60), `--full-window-s`(기본 60), `--dry-run`. `--dry-run`은 네트워크 호출·DB 접속·모델 호출 없이 `estimate`가 계산한 계획 호출 수와 입력 토큰 추정을 `ESTIMATE ...` 한 줄로 출력하고 0으로 끝난다(출력에 "비용은 원장에 기록되며 시범 뒤 `cost-recalc`가 계산한다"를 적는다).
- `Makefile`: `live-pilot` 타깃(`uv run python -m beautyads.eval.pilot_run`)을 추가하고 `.PHONY`에 더한다. **`verify` 타깃은 바꾸지 않고 `live-pilot`을 호출하지 않는다.** `README.md`: "live-pilot (P2)" 절에 **live 순서**(`make live-collect` → 수집량 확인 → 필요 시 재분할 → 그 뒤에 `make live-pilot`), 선행 조건(OrbStack, `make db-up`, `.env` 키 이름들, 수집 완료), 사용법(`--dry-run` 먼저), 이유 코드 표(`PILOT_SPLIT_NOT_VERIFIED`·`PILOT_NO_COLLECTION`·`PILOT_SHORTFALL` 포함), 라벨링 안내(시트로 라벨링 → 코드북 참고 → **키 파일은 라벨링 뒤에 연다**), 시범 비용 안내(두 실행이라 호출이 두 배)를 쓴다.

### 반드시 있어야 하는 테스트 (`tests/test_pilot.py`, 모두 가짜)

- **점검**: 각 이유 코드가 해당 조건에서 나오고(키 이름, `DOCKER_DOWN`, `POSTGRES_UNREACHABLE`, `COST_CAP:gemini`, `LEDGER_NOT_WRITABLE`, 분할 파일 문제, `StoreConnectError` 코드), 점검 출력에 환경 변수 값·DSN이 없다. 점검 실패 시 `deps_factory`·모델 호출이 **한 번도** 불리지 않는다.
- **수집량 강제**: 가짜 `collection_stats`가 수집량 기준 미달이면 `PILOT_SPLIT_NOT_VERIFIED`이고 종료 코드 2이며 선정·분석 호출이 없다, `--skip-volume-check` 같은 우회 옵션이 존재하지 않는다(파서 옵션 목록 확인), dev의 `analyzable` 소재가 0이면 `PILOT_NO_COLLECTION`.
- **흐름**: 선정된 키만 분석 대상이 되고(나머지 소재는 `pending`으로 남음), 두 실행 태그가 `minimal`→`default` 순서로 `thinking_level`을 그대로 `AnalysisRun`에 넘긴다, 첫 실행이 `DAILY_LIMIT`으로 멈추면 두 번째 실행을 시작하지 않는다, 시트·키·코드북 파일이 임시 `data/interim/pilot`에 만들어지고 시트 텍스트에 키 파일 정보(브랜드·모델 라벨 감시 문자열)가 없다, 요약에 `split_sha256`와 안내 문구가 있다, `PILOT_SHORTFALL`이 모자란 만큼 출력된다.
- **옵션**: `--n 0`·`41`, `--out-dir`이 `data/interim` 밖이면 오류 종료, `--dry-run`이 의존성 생성 함수·모델 호출을 한 번도 부르지 않고 `ESTIMATE`를 출력한다(기대값은 작은 입력의 손계산 값).
- `Makefile`: `verify` 레시피 줄에 `live-`가 없고 `live-pilot` 타깃과 `.PHONY` 항목이 있다.

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

- `make live-pilot`을 실행하지 마라. 테스트는 가짜 의존성만 쓴다. 이유: 실제 호출·DB 접속·과금은 사용자의 live 실행이다.
- 수집량 점검(`PILOT_SPLIT_NOT_VERIFIED`)을 우회하는 옵션을 만들지 마라. 이유: 수집량이 모자란 분할로 시범을 뽑은 뒤 분할이 바뀌면 시범 20건이 달라져 사용자의 라벨링이 헛수고가 된다.
- 환경 점검이 통과하기 전에 네트워크 호출·DB 접속·모델 호출을 하지 마라. `--dry-run`도 하지 않는다. 이유: 첫 live에서 Docker 꺼짐·키 누락·상한 초과가 호출 도중에 터지는 것을 막는다(B-FP-051).
- 시범 선정에 분석 결과나 지표를 쓰거나 키 파일을 이 명령이 읽어 출력하지 마라. 키 파일은 쓰기만 한다. 이유: 라벨링 전에 모델 라벨이 사람에게 보이면 블라인드가 깨진다.
- `--out-dir`을 `data/interim` 밖에 허용하지 마라(`OUTPUT_NOT_IGNORED`와 같은 규칙). 이유: 키 파일이 커밋되는 경로로 쓰이면 라벨이 저장소에 남는다.
- `pipeline/`에 시범 실행기를 두거나 `pipeline/preflight.py`를 고치지 마라. 시범 실행기는 `eval/`에 있어야 한다. 이유: `eval`을 import하는 코드는 `eval/` 안에만 있을 수 있다(계층 가드).
