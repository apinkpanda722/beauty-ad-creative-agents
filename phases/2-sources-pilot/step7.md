# Step 7: media-download

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P2 sources-pilot"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/CONTRACTS.md` — TikTok 표의 "영상 파일" 행(`videos[].url`로 mp4를 직접 받음, 4~10MB, `Content-Length`와 받은 바이트 수가 같았다)과 Instagram 주의(`media_url`은 서명 임시 주소, 만료 시각은 `oe`)
- `/docs/PHASES.md` — P2 `media-upload-flow` 행(영상 파일 보관·삭제 규칙: 분석이 끝나면 지운다)
- `/src/beautyads/sources/youtube.py` — `httpx_get`의 방식(요청 실패를 안정된 코드로 바꾼다)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/sources/media.py`, `tests/test_media.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/sources/media.py`, `tests/test_media.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 라벨 키 파일을 읽는 채점 함수, 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

Instagram·TikTok 영상 파일을 받는 함수를 `sources/`에 둔다(`httpx`는 이 계층에서만 허용된다). **영상 바이트는 메모리에서만 다루고 디스크에 쓰지 않는다**(PRD: 영상 파일은 분석이 끝나면 지운다. 메모리에만 두면 임시 파일 정리 문제가 없다. 실측 크기: Instagram 1~4MB, TikTok 1.4~29.5MB. 동시에 여러 개를 받으면 메모리를 쓰므로 호출자가 동시 다운로드 수를 제한한다). 파이프라인 계층(다음 step들)이 이 함수를 호출해 받은 바이트를 Files API에 올린다. **테스트는 가짜 `MediaGet`으로만 하고 실제 다운로드는 하지 않는다.**

### 모듈 `sources/media.py` — 시그니처

```python
class MediaResponse(NamedTuple):
    status: int
    content_type: str | None
    content_length: int | None       # 응답 헤더의 Content-Length(없으면 None)
    data: bytes

MediaGet = Callable[[str, float, int], MediaResponse]      # (url, timeout_s, max_bytes)

class MediaError(Exception):         # 속성: code. 메시지에 URL(쿼리 포함)을 넣지 않는다
class DownloadedMedia(NamedTuple):
    data: bytes
    content_type: str
    size: int

def httpx_media_get(url: str, timeout_s: float, max_bytes: int) -> MediaResponse   # 이 모듈에서 httpx를 쓰는 유일한 함수
DEFAULT_TIMEOUT_S = 120.0                  # 실측: 8.19MB 영상 9.9초, TikTok에는 29.5MB급이 있다(약 36초 추정, 변동이 크다)
DEFAULT_MAX_BYTES = 50 * 1024 * 1024       # 실측 최대 29.5MB 위쪽으로 여유를 둔 상한

def download_media(get: MediaGet, url: str, *, timeout_s: float = DEFAULT_TIMEOUT_S, max_bytes: int = DEFAULT_MAX_BYTES,
                   min_bytes: int = 1) -> DownloadedMedia
```

- `httpx_media_get`: 스트리밍으로 받고(`httpx.stream`, 리다이렉트 허용) **누적 바이트가 `max_bytes`를 넘으면 중단하고 `MediaError("MEDIA_TOO_LARGE")`**. 요청 실패(`httpx.RequestError`)는 `MediaError("MEDIA_REQUEST_FAILED")`. 호출 객체를 돌려줄 때 헤더의 `Content-Type`·`Content-Length`를 담는다.
- `download_media` 판정(순서대로):
  1. 상태가 200이 아니면: 403·404·410이면 `MEDIA_URL_UNAVAILABLE`(만료되었거나 접근이 거부됨. **만료된 URL의 실제 응답 형태는 실측하지 못했다**), 그 밖이면 `MEDIA_HTTP_<상태>`
  2. `content_type`이 `video/`로 시작하지 않으면 `MEDIA_NOT_VIDEO`(비영상 바이트는 업로드는 성공하고 처리 단계에서 `error`가 된다)
  3. `len(data) < min_bytes`면 `MEDIA_EMPTY`
  4. `content_length`가 있고 `len(data)`와 다르면 `MEDIA_TRUNCATED`(실측: TikTok 영상은 둘이 같았다)
  5. 모두 통과하면 `DownloadedMedia`
- 두 상수 `DEFAULT_TIMEOUT_S`(120초)·`DEFAULT_MAX_BYTES`(50MB)는 이 모듈에 **한 곳에만** 두고, 실측 근거(위 주석)를 함께 적는다. 소요 참고(실측): 8.19MB 영상 다운로드 9.9초.

### 반드시 있어야 하는 테스트 (`tests/test_media.py`, 가짜 `MediaGet`)

- 정상 응답이 `DownloadedMedia`로 돌아오고 `size == len(data)`. `Content-Length`가 없어도 통과한다.
- 판정 순서별 실패: 403/404/410 → `MEDIA_URL_UNAVAILABLE`, 500 → `MEDIA_HTTP_500`, 비영상 `Content-Type`(`text/html`, `None`) → `MEDIA_NOT_VIDEO`, 빈 바이트 → `MEDIA_EMPTY`, `Content-Length` 불일치 → `MEDIA_TRUNCATED`.
- 가짜 `MediaGet`이 받은 인자(`timeout_s`, `max_bytes`)가 호출자가 준 값이다. `MediaError`의 메시지·`repr`에 쿼리가 든 테스트 URL 문자열이 없다.
- 상수: `DEFAULT_TIMEOUT_S == 120.0`·`DEFAULT_MAX_BYTES == 50 * 1024 * 1024`이고 `download_media`의 기본 인자가 이 상수와 같다(`inspect.signature`로 확인). 29MB급 응답을 합성할 필요는 없다.
- 이 모듈이 디스크에 쓰지 않음: 테스트가 임시 디렉터리를 현재 작업 디렉터리로 바꾼 뒤 `download_media`를 실행해 **파일이 생기지 않음**을 확인한다.

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

- 영상 바이트를 디스크에 쓰지 마라(임시 파일 포함). 메모리 바이트로만 다룬다. 이유: 영상 파일은 분석이 끝나면 지우는 규칙이고 메모리만 쓰면 정리 누락이 생기지 않는다(PRD, AGENTS.md).
- URL·쿼리를 오류 메시지·로그·출력에 넣지 마라. 이유: Instagram `media_url`은 서명이 붙은 임시 주소이고 TikTok 영상 주소도 만료되는 주소다.
- 받은 바이트를 영상이라고 가정하지 마라. `Content-Type`이 `video/`가 아니면 `MEDIA_NOT_VIDEO`다. 이유: 비영상은 업로드가 성공하고 분석 직전에야 400으로 실패한다.
- 상태 200이 아닌 응답을 재시도하거나 다른 주소를 추측해 요청하지 마라. 재시도·URL 갱신은 호출자의 몫이다. 이유: 만료된 URL은 같은 요청을 반복해도 풀리지 않고 갱신은 계정 단위 재조회가 필요하다.
- `media_url`·영상 주소를 `Creative`나 저장소에 저장하게 만들지 마라(이 모듈은 URL을 받아 바이트를 돌려줄 뿐이다). 이유: 서명 임시 주소는 저장해 두면 만료된다.
