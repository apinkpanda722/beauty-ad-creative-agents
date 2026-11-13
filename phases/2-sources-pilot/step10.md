# Step 10: media-flow

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P2 sources-pilot"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/CONTRACTS.md` — Instagram 주의(`media_url`은 서명 임시 주소, 만료는 `oe`), TikTok 표(`ad.videos[].url`로 mp4 다운로드, 만료 시각 미확인), "LiteLLM SDK" 절의 Gemini Files 행
- `/docs/PHASES.md` — P2 `instagram-source`·`media-upload-flow` 행(분석 직전 재조회, 받기 실패는 재조회 후 1회 재시도 뒤 `held`)
- `/src/beautyads/sources/instagram.py`(`refresh_media_urls`, `RefreshResult`), `/src/beautyads/sources/media.py`(`download_media`) — 이전 step 산출물
- `/src/beautyads/llm/files.py`(`upload_video`, `wait_processed`, `delete_file`, `FileError`) — 이전 step 산출물
- `/src/beautyads/analysis/` 전체(`axes.py`, `models.py`, `hook.py`) — 이전 step 산출물
- `/src/beautyads/domain/protocols.py`, `/src/beautyads/domain/jobs.py` — `AnalysisRepository`, `JobResult`
- `/src/beautyads/pipeline/slice.py` — P1 파이프라인의 주입 방식

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/pipeline/media_flow.py`, `tests/test_media_flow.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/pipeline/media_flow.py`, `tests/test_media_flow.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 라벨 키 파일을 읽는 채점 함수, 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

소재 하나를 분석하는 흐름을 조립한다: **(Instagram·TikTok) 영상 주소 확보 → 다운로드 → Gemini Files 업로드 → 처리 대기 → 분석(콘텐츠 유형 → 제품이면 훅·전체) → 파일 삭제**. YouTube는 파일 없이 주소를 그대로 쓴다. **이 step이 구현하는 주소 확보는 Instagram(`prepare_instagram_plans`)뿐이다.** TikTok은 영상 주소를 저장하지 않으므로 분석 직전에 같은 `UrlPlan` 형태로 받아야 하며, 그 `prepare_tiktok_plans`는 `refresh_tiktok_video_urls`(P2 마지막 step)가 있어야 만들 수 있어 **P3 첫 step(`tiktok-plans`)에서 추가한다.** 그때까지 TikTok 소재는 `UrlPlan`을 받지 못하면 `missing`으로 처리된다(`MEDIA_URL_MISSING`). `pipeline/`은 모든 런타임 계층을 import할 수 있지만 `httpx`·`psycopg`·`litellm`을 직접 import하지 않는다(각 계층의 함수를 주입받아 부른다). 이 step의 핵심은 **정리 순서**다: 파일을 올렸으면 분석이 성공하든, 실패하든, 한도 중단 예외가 나든 반드시 `delete_file`을 부른다. **테스트는 모두 가짜 의존성으로 한다.**

소비자 테스트 점검 결과: 이 step은 새 모듈 하나만 만든다. `tests/test_architecture.py`가 새 모듈을 계층 가드로 검사한다(의도된 관계, 수정하지 않는다).

### 모듈 `pipeline/media_flow.py` — 시그니처

```python
# 오류 코드 분류. 배치 실행기가 재시도 대상을 고를 때 쓴다
RETRYABLE_ERROR_CODES = frozenset({"MEDIA_REQUEST_FAILED", "MEDIA_TRUNCATED", "FILE_UPLOAD_FAILED",
                                   "FILE_PROCESS_TIMEOUT", "FILE_RETRIEVE_FAILED", "LLM_RETRYABLE"})
# 보류(held, 사람이 보는 항목, 다시 집지 않는다)가 되는 코드: MEDIA_NOT_VIDEO, MEDIA_EMPTY, MEDIA_UNAVAILABLE, MEDIA_URL_GONE, FILE_STATUS_ERROR, EMPTY_FILE, INVALID_OUTPUT

class UrlPlan(NamedTuple):
    url: str | None            # 새로 받은 영상 주소(메모리에서만 쓴다. 저장·출력하지 않는다)
    state: str                 # "ok" | "gone"(게시물은 찾았으나 media_url이 없음) | "missing"(찾지 못함) | "none"(주소가 필요 없음: YouTube)

class AnalysisRun(NamedTuple):
    thinking_level: ThinkingLevel; run_tag: str; purpose: str
    ledger_path: Path; caps: Mapping[str, float]
    content_type_window_s: float; full_window_s: float; hook_window_max_s: float
    interact: Callable[..., InteractionResult]

class MediaDeps(NamedTuple):
    download: Callable[[str], DownloadedMedia]
    upload: Callable[[bytes, str], UploadedFile]
    wait: Callable[[str], None]
    delete: Callable[[str], bool]

class CreativeOutcome(BaseModel):
    key: CreativeKey
    records: list[AxisRecord]          # 저장할 결과들(아래)
    cleanup: str                       # "none"(올린 파일 없음) | "deleted" | "delete_failed"
    mark_not_analyzable: bool          # 분석 직전 재조회에서 영상이 사라진 것으로 확인됨

class AxisRecord(BaseModel):           # 저장소에 한 줄로 기록할 단위
    kind: str                          # 예: "content_type@minimal"
    status: JobStatus; labels: dict[str, Any] | None; model: str | None
    thinking_level: str; prompt_version: str | None; raw_output: str | None; error_code: str | None

def prepare_instagram_plans(creatives: Sequence[Creative], accounts: Mapping[str, InstagramAccount], *,
                            refresh: Callable[[InstagramAccount, set[str]], RefreshResult]) -> dict[CreativeKey, UrlPlan]
    # 계정(username)별로 소재를 묶어 refresh를 **계정당 한 번만** 부른다. urls → ok, gone → gone, missing → missing. 계정이 설정에 없는 소재는 missing
def analyze_creative(creative: Creative, *, plan: UrlPlan, run: AnalysisRun, media: MediaDeps,
                     rerefresh: Callable[[], str | None] | None = None) -> CreativeOutcome
def apply_outcome(store: SliceStore-like(CreativeRepository & AnalysisRepository), creative: Creative, outcome: CreativeOutcome) -> None
    # outcome.records를 record_analysis로 저장하고, mark_not_analyzable이면 analyzable=False로 바꾼 소재를 upsert한다
```

### `analyze_creative`의 흐름과 규칙

1. **YouTube**(`plan.state == "none"`): `video_input_for(creative)`로 주소를 쓰고 파일을 올리지 않는다(`cleanup="none"`). 곧바로 5로 간다.
2. **`gone`**: 분석하지 않는다. `mark_not_analyzable=True`, 기록 1건(`content_type@<태그>`, `held`, `MEDIA_URL_GONE`). **`missing`**: 기록 1건(`failed`, `MEDIA_URL_MISSING`, 재시도 대상 코드로 취급하지 않는다. 다음 재조회에서 찾을 수 있다). `url`이 없는 `ok`도 `missing`으로 본다.
3. **다운로드**: `media.download(plan.url)`. `MEDIA_URL_UNAVAILABLE`이면 `rerefresh`가 주어졌을 때 **한 번만** 새 주소를 받아(`rerefresh()`) 다시 다운로드한다(`rerefresh`가 `None`을 돌려주거나 다시 실패하면 `held`·`MEDIA_UNAVAILABLE`). 그 밖의 `MediaError`: `MEDIA_NOT_VIDEO`·`MEDIA_EMPTY`는 `held`(같은 코드), `MEDIA_REQUEST_FAILED`·`MEDIA_TRUNCATED`·`MEDIA_HTTP_<상태>`는 `failed`(같은 코드). 기록은 `content_type@<태그>` 한 건이고 이후 단계로 가지 않는다.
4. **업로드·대기**: `media.upload(data, filename)` 뒤 `media.wait(file_id)`. `FileError`는 코드별로: `EMPTY_FILE`·`FILE_STATUS_ERROR`는 `held`(같은 코드), `FILE_UPLOAD_FAILED`·`FILE_PROCESS_TIMEOUT`·`FILE_RETRIEVE_FAILED`는 `failed`(같은 코드). 대기에서 실패해도 **업로드가 끝나 `file_id`가 생겼다면 그 파일을 삭제한다**. 다운로드한 바이트는 업로드 직후 참조를 버린다(메모리에 오래 두지 않는다).
5. **분석**: 입력은 `VideoInput`(YouTube는 영상 주소와 `None`, 파일은 `file_id`와 `"video/mp4"`). 순서: `analyze_content_type`(창 = `run.content_type_window_s`) → `is_product_target`이면 `analyze_hook`(첫 3초, `video` 인자)과 `analyze_full`(창 = `run.full_window_s`). 제품 대상이 아니면 훅·전체는 부르지 않고 콘텐츠 유형 기록만 남긴다(`done`). 각 결과를 `AxisRecord`로 만든다: 종류 `content_type@<태그>`·`hook@<태그>`(라벨 `{"hook_type": 값}`)·`full@<태그>`, 라벨은 `model_dump(mode="json")`. 한 단계가 `HELD`·`FAILED`면 그 기록을 남기고 **다음 단계는 하지 않는다**.
6. **정리(반드시)**: 업로드에 성공해 `file_id`가 있으면 `try/finally`로 **분석 성공·실패·예외와 관계없이** `media.delete(file_id)`를 정확히 한 번 부른다. 삭제가 `False`면 `cleanup="delete_failed"`로 알리되 분석 결과는 바꾸지 않는다(파일은 약 48시간 뒤 만료된다). `DailyLimitReached`·`kind == RATE_LIMIT`인 `LlmCallError`·`CostCapExceeded`와 `KeyboardInterrupt`는 **잡지 않고 올리되 그 전에 삭제를 끝낸다.** 이 예외가 나면 그 소재는 기록하지 않는다(`pending`으로 남는다).

- `apply_outcome`: 각 `AxisRecord`를 `store.record_analysis(kind, key, status=..., model=..., thinking_level=..., prompt_version=..., raw_output=..., labels=..., error_code=...)`로 저장한다. 해당 `kind`의 작업이 아직 큐에 없으면 먼저 `enqueue_analysis`로 넣는다(제품 대상이 된 소재의 `hook@`·`full@` 작업은 여기서 만들어진다). `mark_not_analyzable`이면 `creative.model_copy(update={"analyzable": False})`를 `upsert_creatives`로 저장한다.
- 영상 주소·`file_id`를 저장하거나 출력·로그에 남기지 않는다(결과 객체에도 담지 않는다).

### 반드시 있어야 하는 테스트 (`tests/test_media_flow.py`, 모두 가짜)

- **삭제 보장**: 가짜 `upload`가 `file_id`를 돌려준 모든 경로에서 `delete`가 정확히 한 번 불린다 — 분석 성공, `HELD`, `FAILED`, `wait`의 `FILE_STATUS_ERROR`·`FILE_PROCESS_TIMEOUT`, 분석 중 `DailyLimitReached`·`CostCapExceeded`·RATE_LIMIT `LlmCallError`·임의 예외·`KeyboardInterrupt`. 업로드가 실패한 경로(`upload`가 예외)에서는 `delete`가 불리지 않는다. 한도 예외는 `delete` 호출 **뒤에** 올라온다(호출 순서를 기록해 단언한다). `delete`가 `False`면 `cleanup == "delete_failed"`이고 결과 기록은 그대로다.
- **분기별 기록**: `gone` → `mark_not_analyzable`과 `held`·`MEDIA_URL_GONE`(다운로드 호출 없음), `missing`·`url=None` → `failed`·`MEDIA_URL_MISSING`, 다운로드 `MEDIA_URL_UNAVAILABLE` → `rerefresh`가 한 번 불리고 성공하면 진행·실패하면 `held`·`MEDIA_UNAVAILABLE`(`rerefresh`가 두 번 불리지 않음), `MEDIA_NOT_VIDEO`·`MEDIA_EMPTY` → `held`, `MEDIA_REQUEST_FAILED`·`MEDIA_TRUNCATED` → `failed`이고 `RETRYABLE_ERROR_CODES`에 들어 있으며 `held` 코드들은 들어 있지 않다.
- **제품 게이트**: 가짜 `interact`가 제품 대상이 아닌 조합(예: `event_place`)을 돌려주면 훅·전체 호출이 **한 번도** 일어나지 않고 콘텐츠 유형 기록만 `done`이다. 제품 대상 조합이면 세 기록이 `content_type@태그`·`hook@태그`·`full@태그`로 나온다. 앞 단계가 `HELD`면 뒤 단계를 호출하지 않는다. 가짜가 돌려준 분류 값은 특정 값으로 고정하지 않고(enum 멤버를 순회한다) 기록의 `labels`가 그 값과 같음만 확인한다.
- **YouTube**: 파일 업로드·삭제·다운로드가 한 번도 불리지 않고 `cleanup == "none"`, 분석 입력의 `uri`가 소재의 `url`이다.
- **창 인자**: 콘텐츠 유형 호출의 구간이 `content_type_window_s`, 전체 호출이 `full_window_s`, 훅이 3초(`hook_window_max_s` 이내)임을 가짜 `interact`가 받은 입력으로 확인한다.
- **`prepare_instagram_plans`**: 같은 계정의 소재 여러 개에 `refresh`가 **계정당 한 번**만 불린다(계정 수와 호출 수가 같음), `urls`·`gone`·`missing`이 각각 `ok`·`gone`·`missing`으로 매핑된다, 설정에 없는 계정의 소재는 `missing`, `refresh`가 빈 결과를 돌려줘도 예외로 끝나지 않는다.
- **`apply_outcome`**: 기록마다 올바른 `kind`·`status`·`labels`가 `record_analysis`에 전달되고 큐에 없는 `kind`는 `enqueue_analysis`가 먼저 불린다, `mark_not_analyzable`이면 `analyzable=False`인 소재가 업서트된다.
- **비노출**: 영상 주소·`file_id`에 감시용 문자열을 넣고 결과 객체의 `model_dump_json()`·저장소가 받은 모든 인자·`CreativeOutcome`의 `repr`에 그 문자열이 없다.

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

- 업로드에 성공한 파일의 삭제를 `finally`가 아닌 곳에 두지 마라. 분석 예외·한도 중단·`KeyboardInterrupt`에서도 `delete_file`이 먼저 불리고 그 뒤 예외가 올라간다. 이유: 올린 파일은 약 48시간 뒤에야 만료되고 영상을 오래 두지 않는 규칙이다(AGENTS.md, PRD).
- `DailyLimitReached`·RATE_LIMIT·`CostCapExceeded`를 잡아 소재 실패로 기록하지 마라(정리 뒤 그대로 올린다). 이유: 한도 중단을 소재 실패로 기록하면 그 소재가 영구 실패로 남고 배치가 멈추지 않아 한도만 더 깎는다(A-FP-030, 실측 2026-11-12).
- 영상 주소·`file_id`·다운로드한 바이트를 결과 객체·저장소·출력에 남기지 마라. 이유: 서명 임시 주소이고 영상은 분석이 끝나면 지우는 규칙이다.
- 주소 재조회를 소재마다 하지 마라. `prepare_instagram_plans`는 계정당 한 번만 부르고, 다운로드 실패 뒤의 재조회(`rerefresh`)는 소재당 최대 한 번이다. 이유: 특정 게시물만 조회하는 방법이 없어 재조회는 계정 목록을 훑는 호출이고 호출당 앱 사용량이 약 0.5%다.
- `held` 코드를 `RETRYABLE_ERROR_CODES`에 넣지 마라. 이유: `held`는 사람이 보는 항목이고 재시도하면 같은 실패에 비용만 반복된다(A-FP-035).
