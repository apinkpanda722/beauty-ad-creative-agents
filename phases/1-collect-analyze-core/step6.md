# Step 6: youtube-source

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P1 collect-analyze-core"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드(step 0 산출물). 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/CONTRACTS.md` — "YouTube Data API v3" 표와 주의(`items` 키 없음, 문자열 통계, 오류 형태)
- `/docs/TROUBLESHOOTING_LOG.md` — 2026-11-11 "브랜드 채널을 검색으로 찾았더니 엉뚱한 채널이 잡혔다"
- `/config/sources.yaml` — `youtube` 절의 구조(읽기만)
- `/tests/fixtures/contracts/youtube_channels_forhandle.json`, `youtube_channels_forhandle_missing.json`, `youtube_playlistitems.json`, `youtube_videos.json`, `youtube_error_bad_key.json` — 응답 원본(수정 금지)
- `/src/beautyads/domain/` — step 1 산출물(`Creative`, `Metrics`)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `pyproject.toml`, `uv.lock`, `src/beautyads/sources/__init__.py`, `src/beautyads/sources/config.py`, `src/beautyads/sources/youtube.py`, `tests/test_youtube.py`, `tests/test_sources_config.py`

열람 금지 경로: (없음)
수정 허용 경로: `pyproject.toml`, `uv.lock`, `src/beautyads/sources/**`, `tests/test_youtube.py`, `tests/test_sources_config.py`

이 step은 YouTube 수집 어댑터(`sources/youtube`)와 `config/sources.yaml`의 YouTube 절 로더를 만든다. `uv add httpx`로 의존성을 추가한다. 패키지 설치는 이 명령만 허용되고, 해석된 `httpx` 버전을 완료 보고의 `summary`에 적는다. `sources/`는 `domain`과 `settings`만 import할 수 있고 **`httpx`는 이 계층에서만** import한다. 테스트는 가짜 `HttpGet`과 원본 픽스처로만 하고 실제 호출은 하지 않는다.

### 설정 로더 (`config.py`)

```python
class YouTubeChannel(BaseModel):   # brand, handle, channel_id, verified
class ConfigError(Exception)
def load_youtube_channels(path: Path) -> list[YouTubeChannel]
```

`sources.yaml`의 `youtube` 절만 읽는다(`instagram`·`tiktok` 절은 이 step에서 해석하지 않고 무시한다). 필수 필드가 빠졌거나 `channel_id`가 중복되면 `ConfigError`.

### 어댑터 (`youtube.py`) — 시그니처

```python
class HttpResponse(NamedTuple):
    status: int
    body: Any | None            # JSON이 아니면 None

HttpGet = Callable[[str, Mapping[str, str], float], HttpResponse]    # (url, params, timeout_s)
def httpx_get(url: str, params: Mapping[str, str], timeout_s: float) -> HttpResponse    # 이 모듈에서 httpx를 쓰는 유일한 함수

class YouTubeError(Exception):  # 속성: code
def find_uploads_playlist(get: HttpGet, api_key: str, channel: YouTubeChannel) -> str
def list_upload_video_ids(get: HttpGet, api_key: str, playlist_id: str, *, max_items: int) -> list[str]
def fetch_videos(get: HttpGet, api_key: str, video_ids: Sequence[str], *, collected_at: datetime, video_length_cut_s: float) -> list[Creative]
def parse_duration_seconds(iso: str | None) -> float | None

class CollectResult(NamedTuple):
    creatives: list[Creative]
    errors: dict[str, str]      # 채널 handle → 오류 코드
    stopped: str | None         # 전체를 멈춘 사유 코드

def collect_youtube(get: HttpGet, api_key: str, channels: Sequence[YouTubeChannel], *, max_items_per_channel: int, collected_at: datetime, video_length_cut_s: float) -> CollectResult
```

- **채널 찾기**: `channels` 호출에 `part=contentDetails`, `forHandle=<sources.yaml의 handle(@ 포함)>`를 쓴다(이 형태만 실측됐다). `items` 키가 없으면 `YouTubeError("CHANNEL_NOT_FOUND")`. `items[0].id`가 설정의 `channel_id`와 다르면 `YouTubeError("CHANNEL_MISMATCH")`. 맞으면 `contentDetails.relatedPlaylists.uploads`가 업로드 목록 ID다. **채널 이름 검색(`search`)은 쓰지 않는다.**
- **업로드 목록**: `playlistItems` 호출(`part=contentDetails`, `playlistId`, `maxResults=50`)의 `items[].contentDetails.videoId`를 모은다. 다음 쪽은 `nextPageToken`으로 이어 가고 **그 키가 없으면 마지막 쪽이다**(`null`이 아니라 키 부재. `.get`으로 읽는다). `max_items`에 도달하면 멈추고 잘라낸다.
- **영상 상세**: `videos` 호출(`part=snippet,statistics,contentDetails,status`, `id`는 쉼표로 이은 최대 50개)을 50개씩 나눠 부른다. `Creative`로 변환할 때: `source=youtube`, `source_id`=영상 ID, `url=https://www.youtube.com/watch?v=<id>`, `title`, `caption`=`snippet.description`, `published_at`=`snippet.publishedAt`, `language`=`snippet.defaultLanguage`(없으면 `None`), `duration_s`=`parse_duration_seconds(contentDetails.duration)`. **통계는 모두 문자열이므로 `int`로 바꾸고, 키가 없으면 `None`이다(0이 아니다).** `analyzable`(**길이 컷을 정하는 유일한 지점이다**. 분석 쪽 선별은 방어용으로만 다시 확인한다): `snippet.liveBroadcastContent`가 `"live"`·`"upcoming"`이면 `False`, `duration_s`가 0 이하이면(`PT0S`) `False`, `duration_s > video_length_cut_s`이면 `False`, `0 < duration_s <= video_length_cut_s`이면 `True`, 길이를 해석할 수 없어 `duration_s`가 `None`이면 `None`.
- `parse_duration_seconds`: `PT2M14S`→134.0, `PT1H2M3S`, `PT45S`, `PT0S`→0.0(길이 0은 해석 가능한 값이다)을 처리하고, 해석할 수 없는 값(`P0D`, 빈 값, `None`)은 `None`.
- **오류**(HTTP 상태를 먼저 본다): 200이 아닐 때 본문의 `error.errors[0].reason`·`error.message`·`error.status`를 **방어적으로**(`.get`) 읽는다. 400이고 메시지에 `API key`가 있으면 `YOUTUBE_KEY_INVALID`, 403이고 `reason`이 `quotaExceeded`·`dailyLimitExceeded`·`rateLimitExceeded`(대소문자 무시)면 `YOUTUBE_QUOTA`(쿼터 초과의 응답 형태는 실측하지 않았다), 그 밖은 `YOUTUBE_HTTP_<상태>`.
- `collect_youtube`: **한 채널의 오류는 `errors`에 기록하고 다음 채널로 넘어간다.** 단 `YOUTUBE_KEY_INVALID`·`YOUTUBE_QUOTA`는 `stopped`에 담고 전체를 멈춘다. 오류 코드·메시지에 API 키나 요청 URL의 쿼리를 넣지 않는다.

### 반드시 있어야 하는 테스트

- `tests/test_sources_config.py`: 임시 YAML로 정상·필드 누락·`channel_id` 중복을 확인한다. 실제 `config/sources.yaml`을 읽어 채널이 1개 이상이고 `channel_id`가 서로 다르며 모두 `UC`로 시작함을 확인한다(채널 수를 고정값으로 단언하지 않는다).
- `tests/test_youtube.py`(가짜 `HttpGet`, 응답 본문은 원본 픽스처의 `response`에서 만든다): `forHandle` 성공·`items` 키 없음(`CHANNEL_NOT_FOUND`)·ID 불일치(`CHANNEL_MISMATCH`), 첫 쪽에는 `nextPageToken`이 있고 둘째 쪽은 그 키를 지운 복사본일 때 정확히 두 번 호출하고 멈춤, `max_items`로 자르기, `videos` 호출이 ID를 50개씩 나눔(호출 수는 `ceil(n/50)`로 계산해 비교), 통계가 문자열→정수, **통계 키(`likeCount`·`commentCount`)를 지운 영상은 `None`**(0 아님), `parse_duration_seconds` 사례들(`PT0S`→0.0, `P0D`·빈 값·`None`→`None`), `analyzable`의 모든 분기(`liveBroadcastContent`, 길이 0, 컷 초과, 컷 이내, 길이 불명), 채널 하나가 실패해도 나머지가 수집됨, 키 오류·쿼터 오류는 `stopped`로 전체 중단, 어떤 호출도 URL에 `/search`를 쓰지 않음, `api_key` 문자열이 `errors`·`stopped`·예외 메시지에 없음.

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

- 채널 이름 검색(`search` 엔드포인트)으로 채널을 찾지 마라. 이유: 검색은 공식 채널이 아닌 것을 섞어 8곳 중 3곳이 틀렸다(`docs/TROUBLESHOOTING_LOG.md` 2026-11-11).
- 통계 키가 없을 때 0으로 바꾸지 마라(`None`). 이유: 좋아요를 숨긴 영상이 있고(1,349개 중 26개) 값은 모두 문자열로 온다(`docs/CONTRACTS.md` YouTube).
- `nextPageToken`을 `[]`로 직접 읽지 마라. 키가 없으면 마지막 쪽이다. 이유: 업로드 목록의 마지막 쪽에는 이 키가 없다(`null`이 아니다). `items`도 없을 수 있다(FP-C01).
- 한 채널의 오류로 전체 수집을 끝내지 마라. 인증 오류와 쿼터 오류만 전체를 멈춘다. 이유: 소재·채널 하나의 실패가 배치를 멈추면 안 된다(A-FP-030).
- 테스트 픽스처를 손으로 새로 쓰지 마라. `youtube_*.json` 원본에서 만들고 변형(키 지우기 등)은 코드로 한다. 이유: 코드와 가짜 응답이 같은 추측을 공유하면 틀려도 통과한다(B-FP-020).
- 지시한 `uv add` 외의 패키지를 설치하거나 `pyproject.toml`에 다른 의존성을 추가하지 마라. 이유: 의존성 변경은 `uv.lock`과 함께 검토 대상이고 계층 가드의 SDK 표가 모르는 패키지는 검증되지 않는다.
