# Step 6: analyze-target

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P3 `analyze-target` 행, §5(첫 live에서 터질 수 있는 것), §8 결정 6번
- `/docs/results/e1_preregistration.md` — 전체 v1 동결 기록(읽기 전용. 없으면 `blocked`가 아니라 CLI의 `PREREGISTRATION_NOT_UPDATED` 점검이 처리한다)
- `/docs/results/2026-11-13-p2-live.md` — P2 live에서 관측한 사용량 중단·재시도
- `/docs/COST_ESTIMATE.md`, `/docs/CONTRACTS.md` — Gemini·Instagram 절(앱 사용량, 429, 서명 URL)
- `/src/beautyads/pipeline/analyze.py`, `/src/beautyads/pipeline/media_flow.py`, `/src/beautyads/pipeline/preflight.py`, `/src/beautyads/pipeline/collect.py` — 배치 실행기·플랜·점검·`with_retries`
- `/src/beautyads/analysis/models.py`, `/src/beautyads/analysis/batch.py` — `FINAL_RUN_TAG`, `PROMPT_VERSIONS`, `ANALYSIS_MODEL_ID`
- `/src/beautyads/eval/pilot_run.py` — 시범 실행기의 의존성 조립(`_live_deps`)과 재시도 요약(**참고만**. `pipeline`은 `eval`을 import할 수 없으므로 조립 코드를 새로 쓴다)
- `/src/beautyads/sources/instagram.py`, `/src/beautyads/sources/media.py` — `refresh_media_urls`(`scan_log`), `download_media`
- `/README.md`, `/Makefile`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/pipeline/analyze_target.py`(새 파일), `src/beautyads/pipeline/media_flow.py`(추가에 한함), `Makefile`, `README.md`, `tests/test_analyze_target.py`(새 파일), `tests/test_media_flow.py`(새 테스트 추가에 한함)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/pipeline/analyze_target.py`, `src/beautyads/pipeline/media_flow.py`(`AnalysisRun`에 기본값이 있는 필드 `purpose_by_axis: bool = False` 추가와 `_analyze`에서 그 값에 따라 호출 `purpose`를 정하는 것에 한함, 기존 동작·시그니처·단언 불변), `tests/test_media_flow.py`(새 테스트 추가에 한함, 기존 단언 약화 금지), `Makefile`(`live-analyze` 타깃과 `.PHONY` 추가에 한함, `verify` 불변), `README.md`(live-analyze 절 추가에 한함), `tests/test_analyze_target.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

소비자 테스트 점검 결과: `scripts/test_hooks.py`는 임시 디렉터리에 자기 `Makefile`을 만들어 쓰므로 영향이 없다. `tests/test_compose.py`·`tests/test_slice.py`·`tests/test_collect.py`·`tests/test_pilot.py`는 저장소 `Makefile`을 읽지만 `.PHONY`는 부분집합으로, 기존 타깃의 레시피 원문은 정확히, `verify` 레시피는 `live-`가 없음을 단언한다. 따라서 **새 타깃은 추가하되 기존 타깃의 레시피 원문·`verify` 레시피·그 뒤의 빈 줄 형식은 바꾸지 않는다.** `tests/test_architecture.py`는 새 모듈에 계층 규칙을 적용한다(통과해야 한다). 이 파일들은 수정하지 않는다. 깨지면 고치지 말고 `blocked`로 보고한다.

수집된 소재를 **전체 v1 분류로 일괄 분석**하는 실행기다(`make live-analyze` → `uv run python -m beautyads.pipeline.analyze_target`). 재개할 수 있고(DB의 작업 상태가 진행 위치다), 사용자가 E1 2단계 라벨링을 하는 동안 돈다. `pipeline/`에 두고 `httpx`·`psycopg`·`litellm`을 직접 import하지 않는다(각 계층의 함수를 부른다). 시범 실행기(`eval/pilot_run.py`)의 조립 코드를 import하지 않는다(`pipeline`은 `eval`을 import할 수 없다) — 같은 경계 함수들을 새로 연결한다. **이 step 안에서는 `make live-analyze`를 실행하지 않는다. 테스트는 모두 가짜 의존성으로 한다.**

### 읽고 쓰는 작업 종류는 `*@v1`뿐

모든 작업 종류 이름은 `f"{axis}@{FINAL_RUN_TAG}"`다(`content_type@v1`, `hook@v1`, `full@v1`). 시범의 `@minimal`·`@default` 작업은 읽지도 쓰지도 되돌리지도 않는다(`requeue_jobs`도 `@v1` 종류에만).

### 원장 `purpose`에 호출 종류를 넣는다 (첫 실행에서 종류별 비용을 재기 위해)

시범 원장의 `purpose`(`pilot-<태그>`)에는 호출 종류가 없어 `content_type`·`hook`·`full`별 비용을 나눌 수 없었다. `analyze-target`부터는 **호출 종류별로 `purpose`를 구분한다.**
- `media_flow.AnalysisRun`에 **기본값이 있는** 필드 `purpose_by_axis: bool = False`를 **마지막에** 추가한다(기존 `AnalysisRun(...)` 호출·시범 코드는 그대로 동작해야 한다). `True`이면 `_analyze`가 세 호출의 `purpose`를 각각 `f"{run.purpose}-{axis}"`(`analyze-target-content_type`, `analyze-target-hook`, `analyze-target-full`)로 넘긴다. `False`이면 기존처럼 `run.purpose` 그대로다(기존 테스트의 `call["purpose"] == run.purpose` 단언 유지).
- `analyze_target`은 `AnalysisRun(..., purpose="analyze-target", purpose_by_axis=True)`로 부른다.
- 요약에 **원장의 `analyze-target-*` 항목을 종류별로 집계한 호출 수·토큰 평균·비용 합계**를 낸다(`obs.ledger.read_entries` 재사용, 이번 실행에서 늘어난 항목만 — 실행 시작 시 원장 항목 수를 기억해 그 뒤 항목만 센다). 이 값이 `cost-recalc`가 못 낸 종류별 측정값이다. README에 "첫 배치 뒤 요약의 종류별 비용으로 전체 견적을 다시 계산한다"를 쓴다.
- `cost_source`가 `response_cost`가 아닌 항목이 있으면 그 수를 함께 보고한다.

### 옵션

`--sources`(기본 `youtube,instagram`; TikTok은 `tiktok-plans` step 뒤에 추가), `--brands`(기본 전체), `--limit`(기본 전체, 시험용), `--batch-size`(기본 100, 1~500), `--concurrency`(기본 1, 1~`MAX_CONCURRENCY`), `--thinking-level`(기본 `minimal`, 사용자가 비용 결정 뒤 바꾼다), `--content-type-window-s`·`--full-window-s`(기본 60), `--retry-failed`(재시도 대상 오류 코드의 작업만 `pending`으로 되돌려 다시 돈다. `RETRYABLE_ERROR_CODES` 재사용), `--dry-run`, `--items N`(`--dry-run`에서 계획 호출 수를 계산할 때만).

### 환경 점검(하나라도 있으면 `PREFLIGHT_FAILED <코드>`를 출력하고 종료 코드 2, 그 전에는 어떤 호출도 접속도 하지 않는다)

`ENV_MISSING:GEMINI_API_KEY`, `ENV_MISSING:POSTGRES_PASSWORD`, `ENV_MISSING:INSTAGRAM_ACCESS_TOKEN`·`ENV_MISSING:INSTAGRAM_USER_ID`(Instagram을 대상에 포함할 때), `DOCKER_DOWN`, `POSTGRES_UNREACHABLE`, `COST_CAP:gemini`(누적이 상한에 이미 닿음), `LEDGER_NOT_WRITABLE`, **`PREREGISTRATION_NOT_UPDATED`**(`docs/results/e1_preregistration.md`가 없거나, 거기에 현재 `ANALYSIS_MODEL_ID`, `PROMPT_VERSIONS`의 세 값 문자열, `전체 v1 동결: YYYY-MM-DD` 형식(날짜가 있는) 줄 중 하나라도 없다. "미기록" 같은 자리표시는 날짜가 아니다 — 사전 등록이 분류 v1 동결을 기록하기 전에 일괄 분석이 시작되는 것을 막는다). `StoreConnectError`는 코드를 출력한다(DSN·비밀번호 미출력).

### 실행 흐름

1. 점검 통과 뒤 `enqueue_targets`(실행 태그 `FINAL_RUN_TAG`)로 분석 가능한 소재를 `content_type@v1`에 대기열로 넣는다(이미 있는 작업은 바꾸지 않는다 — 재개).
2. **배치 반복**: `--batch-size`씩 `run_analysis`를 되풀이한다(`AnalysisRun(thinking_level=…, run_tag=FINAL_RUN_TAG, purpose="analyze-target", …)`). 한 배치 요약을 JSON 한 줄(`event: batch`, 처리 수, 상태 분포, 오류 코드, 이번 배치 비용, 누적 비용, 경과)로 출력한다. 멈춤 조건: `run_analysis`가 `stopped`를 돌려줌(`DAILY_LIMIT`·`COST_CAP`·사용량 중단 등), 대기열이 비었음, 한 배치에서 처리가 0건.
3. **Instagram 앱 사용량 중단**: 분석 직전 계정 재조회가 사용량으로 멈추면 못 찾은 소재는 `MEDIA_REFRESH_STOPPED`(재시도 대상)로 기록된다(P2에서 구현됨). 이 CLI는 멈춘 사유와 마지막 앱 사용량(`scan_log`)을 요약에 출력하고, **자동으로 계속 재시도하지 않는다**(사용량이 회복되기 전에 반복하면 한도만 깎는다). README에 "시간을 두고 `--retry-failed`로 다시 실행한다"를 쓴다. 계정 단위로 묶어 처리되는지(같은 계정의 소재가 같은 배치에 몰리는지)는 코드가 보장하지 않는다 — 요약에 계정별 재조회 횟수를 보고한다.
4. **429(일일 한도)·`COST_CAP`**: 재시도하지 않고 멈춰 남은 소재를 `pending`으로 둔다(래퍼 규칙). 요약에 `STOPPED <사유>`를 출력하고 종료 코드 3.
5. **진행 보고**(매 배치와 마지막): 출처별·모델이 고른 `category`별 `done` 건수, 실패·보류 건수와 실패율, **축별 `other` 비율**(`full@v1`의 닫힌 값 축에서 `other`가 나온 비율), 오류 코드별 건수, 대기 건수. `get_job_results`로 읽고 모델 값을 테스트 기대값으로 굳히지 않는다.
6. **`--dry-run`**: 네트워크·DB·모델 없이 계획만 출력한다(`ESTIMATE`: 실행 태그 `v1`, 분석 모델·프롬프트 버전, 배치 크기·동시성, `--items`가 있으면 호출 수 범위 `items`~`3×items`와 "비용은 원장에 기록되며 `cost-recalc` 결과를 따른다", 점검할 사전 등록 파일 경로).
- 종료 코드: 0 대기열이 비었음, 2 점검 실패, 3 중단 사유가 있음(남은 소재는 `pending`/재시도 대상).
- `Makefile`: `live-analyze` 타깃을 `.PHONY`와 함께 추가하고 `verify`는 바꾸지 않는다. README에 선행 조건(OrbStack, `make db-up`, `.env` 키 이름들, 수집 완료, 사전 등록 갱신), 이유 코드 표, 재개 방법, Instagram 사용량 중단 대응(시간을 두고 `--retry-failed`), 비용 확인(`make cost-recalc`)을 쓴다.

### 반드시 있어야 하는 테스트

(가짜 `AnalysisDeps`·가짜 저장소·가짜 모델·tmp 사전 등록 파일. 모델이 고른 값을 기대값으로 굳히지 않는다.)
- 점검: 각 이유 코드가 해당 조건에서 나오고(`PREREGISTRATION_NOT_UPDATED`는 파일 없음, `전체 v1 동결: YYYY-MM-DD` 줄 없음, `PROMPT_VERSIONS` 값 하나가 빠짐, `ANALYSIS_MODEL_ID` 없음 각각), 출력에 환경 변수 값·DSN이 없고, 점검 실패 시 `deps_factory`·모델 호출이 **한 번도** 불리지 않는다.
- **작업 종류**: 이 CLI가 저장소에서 읽고 쓰고 되돌리는 모든 `kind`가 `@v1`로 끝난다(가짜 저장소가 받은 `kind`를 모아 확인). 같은 소재에 시범 `@minimal`·`@default` 작업이 있어도 건드리지 않는다.
- 재개: 이미 `done`인 작업은 다시 호출되지 않고, `pending`만 처리된다. `--retry-failed`는 재시도 대상 오류 코드(`MEDIA_REFRESH_STOPPED` 포함)의 `failed`만 되돌리고 `MEDIA_URL_GONE`(held)·`MEDIA_URL_MISSING`·`INVALID_OUTPUT`은 되돌리지 않는다.
- 배치 반복: 대기열이 비면 끝, `stopped`가 오면 거기서 멈추고 종료 코드 3, 한 배치 처리가 0이면 멈춘다. 배치 요약 JSON 줄이 매 배치 출력되고 누적 비용이 단조 증가한다.
- Instagram 사용량 중단 시 `MEDIA_REFRESH_STOPPED`로 기록된 소재 수와 마지막 사용량이 요약에 나오고 자동 반복이 없다(모델·재조회 호출 횟수로 확인).
- 일일 한도(`DAILY_LIMIT`)와 `COST_CAP`에서 남은 소재가 `pending`으로 남는다.
- 진행 보고: 합성 `done` 결과에서 출처·`category`별 건수, 실패율, 축별 `other` 비율이 손계산 값과 같다.
- **`purpose`**: `analyze_target`이 만든 모든 호출의 `purpose`가 세 값(`analyze-target-content_type`·`-hook`·`-full`) 중 하나이고 호출 종류와 맞는다(가짜 모델이 받은 인자로 확인). `AnalysisRun`을 `purpose_by_axis` 없이 만든 기존 경로(시범)는 호출 `purpose`가 그대로 `run.purpose`다(`tests/test_media_flow.py`의 새 테스트로 두 경우 모두). 요약의 종류별 비용·호출 수가 합성 원장의 손계산 값과 같고 이번 실행 전 항목은 세지 않는다.
- `--dry-run`이 의존성 생성 함수·모델·네트워크를 부르지 않고 `ESTIMATE`를 출력한다(기대값은 작은 입력의 손계산 값), `--batch-size 0`·`501`, `--concurrency`가 범위 밖이면 오류 종료.
- `Makefile`: `verify` 레시피에 `live-`가 없고 `live-analyze` 타깃과 `.PHONY` 항목이 있다.

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

- `make live-analyze`를 실행하지 마라. 테스트는 가짜 의존성만 쓴다. 이유: 실제 호출·DB 접속·과금은 사용자의 live 실행이다.
- 사전 등록 갱신 점검(`PREREGISTRATION_NOT_UPDATED`)을 우회하는 옵션을 만들지 마라. 이유: 분류 v1 동결과 프롬프트 버전이 사전 등록에 기록되기 전에 일괄 분석이 시작되면 어떤 기준으로 만든 결과인지 증명할 수 없다.
- `AnalysisRun`의 필드 순서를 바꾸거나 `purpose_by_axis`에 기본값을 빼지 마라, 시범 경로의 `purpose`를 바꾸지 마라. 이유: 시범 코드와 기존 테스트가 같은 생성 방식을 쓰고 이미 쌓인 시범 원장 항목과 일관성을 유지한다.
- `@v1` 밖의 작업 종류(시범 `@minimal`·`@default`)를 읽거나 쓰거나 되돌리지 마라. 이유: 시범 결과와 최종 결과가 섞이면 `pilot-compare`와 E1 채점이 틀어진다.
- 사용량 중단·429·`COST_CAP` 뒤에 자동으로 계속 재시도하지 마라. 이유: 회복 전의 반복은 한도만 깎고 일일 한도 429는 재시도하지 않는다(AGENTS.md). 남은 소재는 대기 상태로 둔다.
- 중단을 "없음"으로 확정하지 마라(`MEDIA_URL_MISSING`은 재조회가 끝까지 돈 뒤에만). 이유: FP-C05 — 중단과 부재는 다른 상태다.
- `eval/`을 import하거나 시범 실행기 코드를 복사해서 수정하지 마라. 이유: 계층 가드(`pipeline`은 `eval`을 import할 수 없다). 필요한 경계 함수는 각 계층에서 직접 부른다.
- 환경 점검이 통과하기 전에 네트워크 호출·DB 접속·모델 호출을 하지 마라. `--dry-run`도 하지 않는다. 이유: 첫 live에서 Docker 꺼짐·키 누락·상한 초과가 호출 도중에 터지는 것을 막는다(B-FP-051).
- 비용 상한(공급사별 누적)을 우회하거나 `thinking_level` 기본값을 사용자 결정 없이 바꾸지 마라. 이유: 상한과 `thinking_level`은 `cost-recalc` 뒤 사용자가 정한다.
- 영상·이미지 파일을 디스크에 남기지 마라(메모리 바이트만, 분석 뒤 삭제). 이유: AGENTS.md 영상 저장 금지 규칙.
