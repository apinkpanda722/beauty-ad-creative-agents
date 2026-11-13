# Step 11: batch-runner

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P2 sources-pilot"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/ARCHITECTURE.md` — "상태 관리"와 "요청 처리 공통 장치"(오류 처리), "데이터 흐름" 오프라인 4~6번
- `/docs/CONTRACTS.md` — Gemini 주의(일일 한도 429는 재시도하지 않는다, 분당 한도와 구분, 과부하 503·150초 지연)와 "LiteLLM SDK" 절
- `/docs/COST_ESTIMATE.md` — "보정" 절(공급사별 상한, thought 토큰)
- `/src/beautyads/pipeline/media_flow.py` — 이전 step 산출물(`analyze_creative`, `apply_outcome`, `prepare_instagram_plans`, `RETRYABLE_ERROR_CODES`)
- `/src/beautyads/analysis/batch.py` — P1의 단순 배치(`analyze_pending`). 이 step은 이것을 **바꾸지 않고** 새 실행기를 만든다
- `/src/beautyads/domain/protocols.py`(`requeue_jobs`, `job_counts`, `list_creatives`), `/src/beautyads/obs/ledger.py`(`provider_total`)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/pipeline/analyze.py`, `tests/test_analyze_runner.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/pipeline/analyze.py`, `tests/test_analyze_runner.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 라벨 키 파일을 읽는 채점 함수, 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

여러 소재를 분석하는 **배치 실행기**다. 중단 조건(일일·분당 한도, 비용 상한)과 소재별 실패 격리, 재시도 대상 오류의 재투입, 제한된 동시성을 담당한다. 이 step은 **함수 모듈만** 만든다(`make` 타깃과 CLI는 P3의 `analyze-target`과 P2의 시범 타깃이 이 함수를 감싼다). `pipeline/`은 모든 런타임 계층을 import할 수 있지만 `httpx`·`psycopg`·`litellm`을 직접 import하지 않는다. **테스트는 모두 가짜 의존성으로 한다.**

소비자 테스트 점검 결과: 이 step은 새 모듈 하나만 만든다(P1의 `analysis/batch.py`와 그 테스트는 건드리지 않는다). `tests/test_architecture.py`가 새 모듈을 계층 가드로 검사한다(의도된 관계).

### 모듈 `pipeline/analyze.py` — 시그니처

```python
MAX_CONCURRENCY = 4                         # 29MB급 영상 × 동시 4개 ≈ 120MB. 영상 바이트를 메모리로만 다루므로 상한을 둔다
RATE_LIMIT_WAIT_MAX_S = 120.0
AXES = ("content_type", "hook", "full")

class AnalysisDeps(NamedTuple):
    store: <CreativeRepository & AnalysisRepository를 만족하는 객체>
    media: MediaDeps
    plans: Callable[[Sequence[Creative]], dict[CreativeKey, UrlPlan]]      # 분석 직전에 호출해 영상 주소를 새로 받는다
    rerefresh: Callable[[Creative], Callable[[], str | None] | None]       # 소재별 한 번짜리 재조회 함수를 만든다(없으면 None)
    sleep: Callable[[float], None]
    now: Callable[[], datetime]

class AnalysisReport(BaseModel):
    processed: int
    by_status: dict[str, dict[str, int]]    # 축 이름 → {pending/done/held/failed: 건수}  (store.job_counts)
    error_codes: dict[str, int]             # 이번 실행에서 기록된 error_code별 건수
    cleanup_failed: int
    not_analyzable_marked: int
    stopped: str | None                     # "DAILY_LIMIT" | "RATE_LIMITED" | "COST_CAP:<공급사>" | None
    gemini_cost_usd: float                  # 이번 실행 동안 원장 gemini 합계의 증가분
    elapsed_s: float

def enqueue_targets(store, run_tag: str, *, brands: Collection[str] | None, sources: Collection[Source] | None,
                    limit: int | None) -> list[Creative]
    # list_creatives(analyzable_only=True, ...)로 대상을 고르고 enqueue_analysis(f"content_type@{run_tag}", ...)로 큐에 넣는다. 이미 큐에 있으면 그대로(멱등)

def run_analysis(deps: AnalysisDeps, *, run: AnalysisRun, limit: int, concurrency: int = 1,
                 retry_failed: bool = False, only_keys: Collection[CreativeKey] | None = None,
                 out: TextIO) -> AnalysisReport
```

- **재시도 투입**: `retry_failed=True`이면 시작할 때 각 축 종류(`content_type@태그`·`hook@태그`·`full@태그`)에 대해 `store.requeue_jobs(kind, RETRYABLE_ERROR_CODES)`를 부른다. `held`는 건드리지 않는다. **`retry_failed=False`(기본)이면 `failed` 작업을 다시 집지 않는다.**
- **대상**: `store.next_pending(f"content_type@{태그}", limit)`에서 가져온다. `only_keys`가 주어지면 그 키만 처리한다(시범 대상 20건 제한용. 나머지 `pending`은 건드리지 않는다). 제품 대상이 되어 큐에 새로 들어간 `hook@`·`full@` 작업은 `analyze_creative`가 같은 소재에서 한 번에 처리하므로 별도로 집지 않는다. (이전 실행에서 `content_type`만 `done`인데 `hook`·`full`이 `failed`·`pending`으로 남은 소재는 `retry_failed`로 `requeue`한 뒤 `analyze_creative`를 다시 돌린다.)
- **영상 주소**: 한 번에 처리할 소재 묶음(`limit`)을 정한 직후, **분석을 시작하기 전에** `deps.plans(묶음)`으로 주소를 새로 받는다(Instagram은 계정당 재조회 한 번. 수 시간 안에 받아 처리한다). 주소를 저장하지 않는다.
- **동시성**: `concurrency`는 1~`MAX_CONCURRENCY`이고 범위 밖이면 `ValueError`(기본 1). 스레드 풀로 소재를 병렬 처리하되 한 번에 `concurrency`개를 넘기지 않는다. **저장소의 모든 호출(읽기 포함)을 한 락으로 직렬화한다**: 저장소를 호출마다 락을 잡는 얇은 래퍼(`SerializedStore`, `CreativeRepository`·`AnalysisRepository`의 모든 메서드를 감싼다)로 감싸 `AnalysisDeps.store`로 쓴다. 이유: 스레드들이 연결 하나를 공유하고 읽기의 `rollback()`은 연결 단위라, 읽기가 다른 스레드의 쓰기 도중(INSERT 뒤 `commit` 전) 트랜잭션을 롤백해 기록이 조용히 사라질 수 있다.
- **소재별 실패 격리**: `analyze_creative`의 결과를 `apply_outcome`으로 저장하고 다음 소재로 넘어간다. 소재 하나의 `held`·`failed`로 멈추지 않는다.
- **중단 조건**(처리 중인 소재는 `analyze_creative`가 파일 정리를 끝낸 뒤 예외를 올리므로 이 실행기는 그 예외를 받아 멈춘다): `DailyLimitReached` → `stopped="DAILY_LIMIT"`, `CostCapExceeded` → `stopped=f"COST_CAP:{provider}"`, RATE_LIMIT인 `LlmCallError` → **같은 소재를 한 번만** `min(retry_after_s 또는 기본 30초, RATE_LIMIT_WAIT_MAX_S)`초 기다린 뒤 다시 처리하고(`sleep` 주입), 연이어 또 RATE_LIMIT이면 `stopped="RATE_LIMITED"`. 중단되면 새 소재를 시작하지 않고 진행 중인 소재는 끝낼 수 있는 만큼만 끝낸다(한도 예외가 난 소재는 기록하지 않아 `pending`으로 남는다).
- **보고**: 소재마다 JSON 한 줄(`event`, `source`, `brand`, `account`, `kinds`·`status`·`error_code`)을 `out`에 출력한다(영상 주소·`file_id` 제외). 끝에 `AnalysisReport`를 출력한다. `gemini_cost_usd`는 실행 전후의 `provider_total(ledger, "gemini")` 차이다. 같은 입력으로 다시 실행하면 `done` 소재는 다시 처리하지 않는다(이미 비용을 쓴 호출을 반복하지 않는다).

### 반드시 있어야 하는 테스트 (`tests/test_analyze_runner.py`, 가짜 의존성)

- **재시도 투입**: `retry_failed=False`면 `requeue_jobs`를 부르지 않고 `failed` 소재가 처리 대상에 없다, `True`면 세 축 종류 각각에 `RETRYABLE_ERROR_CODES`로 `requeue_jobs`가 불리고 `held`를 되돌리는 호출이 없다.
- **격리**: 소재 하나가 `FAILED`·`HELD`여도 나머지가 처리되고 `stopped is None`이다. 소재 하나에서 임의 예외가 나도(가짜 `analyze_creative`) 배치가 멈추지 않고 그 소재는 `failed`로 기록된다(`error_code="UNEXPECTED"`). 단 한도 예외는 아래처럼 멈춘다.
- **중단**: `DailyLimitReached` → `DAILY_LIMIT`로 멈추고 그 소재와 남은 소재가 `pending`으로 남는다, `CostCapExceeded` → `COST_CAP:gemini`, RATE_LIMIT 한 번 → 대기(가짜 `sleep`이 `retry_after_s`·상한으로 불림) 후 같은 소재가 다시 처리되고 성공하면 계속된다, RATE_LIMIT이 연이어 나면 `RATE_LIMITED`로 멈춘다. 중단 뒤 새 소재를 시작하지 않는다.
- **동시성**: `concurrency=0`·`MAX_CONCURRENCY+1`은 `ValueError`. 동시에 실행 중인 `analyze_creative` 수의 최댓값이 `concurrency`를 넘지 않음을 가짜가 기록한 값으로 확인한다. 결과 **집합**(처리된 키 집합, 저장된 기록 수)은 단언하되 **처리 순서는 단언하지 않는다**(B-FP-012). **저장소 호출이 겹치지 않는다**: 가짜 저장소가 동시에 실행 중인 호출 수를 세어(읽기·쓰기 모두) **그 최댓값이 1**임을 단언한다(`SerializedStore`가 모든 메서드를 감쌌는지 확인한다. 한 메서드라도 빠지면 실패해야 한다).
- **`only_keys`**: 지정한 키만 처리되고 나머지는 `pending`으로 남는다. `limit`이 처리 수를 제한한다.
- **재실행 멱등성**: 같은 입력으로 두 번 실행하면 두 번째에 `done` 소재의 `analyze_creative`가 다시 불리지 않는다. 영상 주소는 처리 묶음마다 `plans`로 새로 받는다(주소를 재사용하지 않음).
- **보고**: `error_codes` 집계, `by_status`가 `job_counts` 결과, `gemini_cost_usd`가 가짜 원장 합계의 증가분(임시 원장 경로), 출력 줄이 JSON이고 영상 주소·`file_id` 감시 문자열이 없다. `enqueue_targets`가 `analyzable == True`인 소재만 큐에 넣고 두 번 호출해도 큐 수가 늘지 않는다.

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

- 소재 하나의 실패(`held`·`failed`·예상 밖 예외)로 배치를 멈추지 마라. 멈추는 것은 일일·분당 한도와 비용 상한뿐이다. 이유: 소재 하나의 결함이 수천 건의 분석을 막으면 안 된다(A-FP-030).
- 일일 한도를 재시도하지 마라. RATE_LIMIT(분당)은 같은 소재를 한 번만 기다렸다 다시 하고 연이으면 멈춘다. 이유: 고정 간격 재시도가 당일 한도를 소진시킨 사례가 있다(TROUBLESHOOTING 2026-11-12). 재시도로 성공한 호출만 과금되고 한도 거부는 과금되지 않지만 한도 소진은 되돌릴 수 없다.
- `done` 소재를 다시 분석하거나 `held`를 `requeue`하지 마라. 재시도는 `RETRYABLE_ERROR_CODES`의 `failed`만 대상으로 한다. 이유: 완료된 호출을 반복하면 이중 과금이다(A-FP-035).
- 읽기 메서드를 락 밖에서 부르지 마라. 저장소의 모든 호출을 `SerializedStore`를 거치게 한다. 이유: 읽기의 `rollback()`이 다른 스레드의 열린 쓰기 트랜잭션을 끝낼 수 있다.
- 동시성 상한(`MAX_CONCURRENCY`)을 넘기거나 영상 바이트를 큐에 쌓아 두지 마라. 소재 하나를 처리하는 동안만 바이트를 갖는다. 이유: 영상은 메모리에서만 다루고 29MB급 파일이 있어 동시 수만큼 메모리를 쓴다.
- 처리 순서나 스레드 실행 순서를 단언하지 마라. 처리된 키의 집합과 개수만 단언한다. 이유: 동시 실행에서 순서는 보장되지 않는다(B-FP-012).
