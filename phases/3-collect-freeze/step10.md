# Step 10: tiktok-plans

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P3 `tiktok-plans` 행과 "P2에서 넘어온 P3 항목"
- `/docs/CONTRACTS.md` — TikTok 절(영상 주소 만료, 다운로드 헤더, 재조회)
- `/src/beautyads/sources/tiktok.py` — `refresh_tiktok_video_urls`(`max_pages` 필수, `RefreshResult(urls, gone, missing, stopped)`), `TokenProvider`
- `/src/beautyads/sources/config.py` — `TikTokConfig`, `TikTokBrand`
- `/src/beautyads/pipeline/media_flow.py` — `prepare_instagram_plans`, `UrlPlan`(상태 `ok`/`gone`/`missing`/`refresh_stopped`/`none`), `analyze_creative`, `RETRYABLE_ERROR_CODES`
- `/src/beautyads/pipeline/analyze_target.py` — 조립(이전 step 산출물)
- `/tests/test_media_flow.py`, `/tests/test_analyze_target.py` — 기존 테스트(깨면 `blocked`)
- `/README.md`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/pipeline/media_flow.py`, `src/beautyads/pipeline/analyze_target.py`, `README.md`, `tests/test_media_flow.py`, `tests/test_analyze_target.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/pipeline/media_flow.py`(`prepare_tiktok_plans` 추가에 한함, 기존 함수·시그니처·동작 불변), `src/beautyads/pipeline/analyze_target.py`(TikTok 출처 추가와 두 출처 플랜 합성에 한함, 기존 동작 불변), `README.md`(live-analyze 절의 TikTok 설명 추가에 한함), `tests/test_media_flow.py`(새 테스트 추가에 한함, 기존 단언 약화 금지), `tests/test_analyze_target.py`(새 테스트 추가에 한함, 기존 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

소비자 테스트 점검 결과: `tests/test_pilot.py`·`tests/test_analyze_runner.py`는 `pipeline/media_flow.py`의 `prepare_instagram_plans`·`AnalysisDeps`·`UrlPlan`을 쓴다. 이 step은 **추가만** 하므로 영향이 없어야 한다. 깨지면 고치지 말고 `blocked`로 보고한다.

TikTok 소재는 영상 주소를 저장하지 않으므로 **분석 직전에 브랜드별로 한 번 재조회**해 플랜을 만들고 `analyze_creative`에 연결한다. Instagram 플랜(`prepare_instagram_plans`)과 같은 형태다.

```python
def prepare_tiktok_plans(
    creatives: Sequence[Creative],
    brands: Mapping[str, TikTokBrand],
    *,
    refresh: Callable[[TikTokBrand, set[str]], RefreshResult],
) -> dict[CreativeKey, UrlPlan]
```

- TikTok 소재(`source == tiktok`)만 대상이다. 소재마다 기본 플랜은 `UrlPlan(None, "missing")`이고, **브랜드별로 한 번** `refresh(brand, 그 브랜드 소재 id 집합)`을 부른다(소재마다 부르지 않는다). 결과가 `urls`에 있으면 `UrlPlan(url, "ok")`, `gone`에 있으면 `UrlPlan(None, "gone")`, 둘 다 아닌데 `stopped`가 있으면 `UrlPlan(None, "refresh_stopped")`(**중단을 "없음"으로 확정하지 않는다** — FP-C05), 둘 다 아니고 중단도 없으면 `missing`으로 둔다. 설정에 없는 브랜드의 소재는 `missing`.
- `analyze_creative`의 기존 처리(`refresh_stopped` → `MEDIA_REFRESH_STOPPED`, `gone` → held 등)를 그대로 쓴다. 재조회 후 다운로드 실패 시 1회 재조회하는 흐름(`rerefresh`)도 TikTok에 연결한다(브랜드 단위 재조회는 `refresh_tiktok_video_urls`를 `{source_id}` 하나로 호출).
- **`max_pages`**: 재조회에 넘기는 `max_pages`는 **수집 때 쓴 값 이상**이어야 한다(필수 인자). `analyze_target`은 `--tiktok-max-pages`(기본 수집 기본값 이상의 상수 한 곳, README에 "수집 때 쓴 `--max-pages`보다 작게 주지 말 것")를 받고, 값이 1 미만이면 오류 종료한다. 이 값이 수집 때보다 작을 때 못 찾은 소재가 `missing`이 아니라 `refresh_stopped`/재시도 대상이 되게 하려면 `refresh_tiktok_video_urls`의 결과를 있는 그대로 쓴다(코드가 "쪽 수 부족"을 판단하지 않는다).
- **`analyze_target` 연결**: `--sources`에 `tiktok`을 허용하고, `AnalysisDeps.plans`를 **출처별 플랜 함수의 합성**으로 만든다(Instagram은 기존 그대로). `TIKTOK_CLIENT_KEY`·`TIKTOK_CLIENT_SECRET`은 TikTok을 대상에 포함할 때만 점검한다(`ENV_MISSING:…`). 토큰은 `TokenProvider`가 7200초 만료를 처리하며 이 CLI가 출력하지 않는다.
- 기존 `AnalysisDeps` 필드와 `prepare_instagram_plans` 시그니처·동작은 바꾸지 않는다(시범 코드와 기존 테스트가 쓴다).

### 브랜드당 표본 `--per-brand-limit` (사용자 결정 2026-11-14)

TikTok 분석 가능 소재가 많아(수천 건) 비용 상한 안에서 돌리도록 **브랜드당 N건 표본**만 분석한다. `analyze_target`에 옵션을 추가한다.

- `--per-brand-limit N`(정수 1~500): 대상 소재(`analyzable == true`, `--sources`·`--brands` 필터 적용 뒤)를 브랜드별로 모은 뒤 **시드 고정 무작위로 N건**을 고른다. **최신순·인기순 같은 정렬 선택을 하지 않는다.** 브랜드의 대상이 N건 이하이면 전부.
- 선택 규칙(코드 상수 한 곳 `PER_BRAND_SAMPLE_SEED = 20261114`와 함수 `select_per_brand(creatives, per_brand_limit, seed)`): 브랜드마다 대상을 `source_id` 오름차순으로 정렬한 뒤 `random.Random(f"{seed}:{brand}")`로 섞고 앞에서 N건을 취한다. 브랜드별로 독립 시드라 **`N=10`의 선택은 `N=40`의 선택의 앞부분(prefix)**이고, 소재의 입력 순서나 다른 브랜드의 소재 수가 바뀌어도 그 브랜드의 선택은 같다(같은 소재 집합에서). `brand`가 없는 소재는 `None` 브랜드로 한 묶음이다.
- 이 옵션이 있으면 선택된 소재만 대기열에 넣고(`enqueue_analysis`) `run_analysis(..., only_keys=…)`로 그 소재만 처리한다(`--only-keys-file`과 같은 방식). 이미 `done`인 작업은 다시 호출되지 않는다. 같은 옵션·시드·소재 집합으로 다시 실행하면 같은 소재가 선택되어 재개된다.
- `--only-keys-file`·`--limit`와 함께 쓰면 `PER_BRAND_CONFLICT`(종료 코드 2). `--brands`와는 함께 쓸 수 있다.
- 요약과 `--dry-run`에 시드, N, 브랜드별 선택 건수의 **합계**(출력에 브랜드별 건수는 쓰지 않는다)와 선택 규칙 문구를 출력한다. README에 "시드 20261114, 분석 가능 소재를 브랜드별로 `source_id` 정렬 후 섞어 앞에서 N건(최신순 아님)"을 쓰고 결과 문서에 옮길 수 있게 한다.
- 수집 때 쓴 쪽 수는 20이었으므로 `--tiktok-max-pages`의 기본값은 **20**(수집의 `--max-pages 20`과 같은 값 이상)으로 둔다.

### 반드시 있어야 하는 테스트

(가짜 `refresh`는 `RefreshResult`를 돌려준다. 모델 값을 기대값으로 굳히지 않는다.)
- `prepare_tiktok_plans`: 브랜드 두 개, 소재 여러 개일 때 `refresh`가 **브랜드마다 정확히 한 번** 불린다(호출 인자의 id 집합 확인). 결과별 플랜(`ok`/`gone`)이 맞다.
- **중단**: `stopped`가 있고 id가 `urls`·`gone`에 없으면 `refresh_stopped`이고 **`missing`이 아니다**. 중단이 없고 어디에도 없으면 `missing`.
- 설정에 없는 브랜드나 TikTok이 아닌 소재는 이 함수가 다루지 않는다(Instagram·YouTube 소재가 섞여도 결과에 키가 없다).
- `analyze_creative`가 `refresh_stopped` TikTok 플랜에서 `MEDIA_REFRESH_STOPPED`(failed, 재시도 대상)를 기록한다(기존 동작 재확인), `ok` 플랜은 다운로드 경로로 간다.
- **`--per-brand-limit`**(합성 소재): 브랜드마다 정확히 N건(대상이 N건 이하면 전부)만 선택되고 `analyzable`이 아닌 소재는 선택되지 않는다. 선택이 **게시 시각·소재 입력 순서에 의존하지 않는다**(최신순이 아님: 게시 시각이 서로 다른 합성 소재의 선택이 입력 순서를 뒤집어도 같고, 가장 최신 N건과 같은 집합이 아니라는 것을 시드 한 개로 확인하지 말고 여러 시드/소재 구성으로 최신순과 일치하지 않는 경우가 있음을 확인한다). 같은 입력은 같은 선택, 시드가 다르면 달라질 수 있다. **N이 작은 선택이 큰 선택의 앞부분(prefix)**이다. 한 브랜드의 소재를 추가해도 다른 브랜드의 선택은 같다. 선택된 소재만 대기열에 들어가고 `run_analysis`의 `only_keys`로 처리된다(가짜 저장소로 확인), 이미 `done`인 작업은 다시 호출되지 않는다. `--only-keys-file`·`--limit`와 함께 쓰면 `PER_BRAND_CONFLICT`, N이 0·501이면 오류 종료. 출력에 브랜드별 선택 건수가 없다(합계만). `--dry-run`이 시드와 N을 출력한다.
- `--tiktok-max-pages`의 기본값이 20이다.
- `analyze_target`: `--sources tiktok`을 허용하고, TikTok 키가 없으면 `ENV_MISSING:TIKTOK_CLIENT_KEY`(TikTok을 대상에 포함할 때만, 포함하지 않으면 점검하지 않음), `--tiktok-max-pages 0`은 오류 종료, 합성된 플랜에서 Instagram 소재는 기존 `prepare_instagram_plans`로·TikTok 소재는 새 함수로 처리된다. 기존 `tests/test_analyze_target.py`·`tests/test_media_flow.py`·`tests/test_pilot.py`의 단언이 그대로 통과한다.

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

- `prepare_instagram_plans`·`AnalysisDeps` 필드·`UrlPlan` 정의를 바꾸지 마라. 이유: 시범 실행기(`eval/pilot_run.py`)와 기존 테스트가 같은 시그니처를 쓴다.
- 소재마다 재조회하지 마라(브랜드마다 한 번). 이유: TikTok 쪽 넘김 호출은 비싸고 레이트 리밋이 있다.
- 재조회가 중단됐는데 못 찾은 소재를 `missing`("없음")으로 확정하지 마라. 이유: FP-C05 — 중단과 부재는 다른 상태이고 중단은 재시도 대상이다.
- 영상 주소를 DB·로그·출력에 남기지 마라. 이유: 서명 URL은 만료되고 저장 금지다.
- `max_pages`를 수집 때보다 작게 고정하는 기본값을 두지 마라. 이유: 작으면 있는 광고도 못 찾는다(`refresh_tiktok_video_urls`는 수집의 `max_pages` 이상을 요구한다).
- 모델·네트워크를 호출하지 마라(테스트는 가짜). `make live-analyze`를 실행하지 마라. 이유: 실제 호출·과금은 사용자의 live 실행이다.
- 표본을 게시 시각·조회수·도달 구간으로 정렬해 뽑지 마라(최신순·인기순 금지). 이유: 사용자 결정 — 시드 고정 무작위로 뽑아야 선택 편향이 없고 재개해도 같다.
- `--per-brand-limit`의 출력에 브랜드별 건수를 쓰지 마라. 이유: 분포를 보고하지 않는 규칙(합계만).
