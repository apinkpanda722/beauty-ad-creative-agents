# Step 4: instagram-source

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P2 sources-pilot"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/CONTRACTS.md` — "Instagram Graph API (Business Discovery)" 표와 주의(`media_url` 키 부재, 오류 110·190, 다음 쪽은 `media.paging.cursors.after`, `media_url`은 서명 임시 주소)
- `/tests/fixtures/contracts/instagram_business_discovery_with_media_url.json`, `instagram_business_discovery_without_media_url.json`, `instagram_error_invalid_user.json`, `instagram_error_bad_token.json` — 응답 원본(수정 금지)
- `/tests/fixtures/contracts/README.md` — 원본은 서명 쿼리를 지운 상태다(`oe` 파라미터 파싱 테스트는 합성 URL을 쓴다)
- `/config/sources.yaml` — `instagram` 절의 구조(`brand`, `username`, `region`, `verified`). 읽기만 한다
- `/src/beautyads/sources/youtube.py`, `/src/beautyads/sources/config.py` — P1 어댑터와 로더의 방식(주입형 HTTP 함수, 오류 코드, 채널 단위 격리)
- `/src/beautyads/domain/creative.py` — `Creative`(step 2가 추가한 `brand`·`account` 포함)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/sources/instagram.py`, `src/beautyads/sources/config.py`, `tests/test_instagram.py`, `tests/test_sources_config.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/sources/instagram.py`, `src/beautyads/sources/config.py`(`load_instagram_accounts` 추가에 한함, 기존 동작 불변), `tests/test_instagram.py`, `tests/test_sources_config.py`(추가에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 라벨 키 파일을 읽는 채점 함수, 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

Instagram 공식 계정의 게시물을 Business Discovery로 수집하는 어댑터와 `sources.yaml`의 `instagram` 절 로더를 만든다. `sources/`는 `domain`과 `settings`만 import하고 `httpx`는 이 계층에서만 쓴다. **테스트는 가짜 HTTP 함수와 `tests/fixtures/contracts/`의 원본으로만 하고 실제 호출은 하지 않는다.**

> **실측으로 확정된 호출 형태(2026-11-12, 실제 토큰)**: ① 기본 URL은 `https://graph.facebook.com/v21.0/{IG 사용자 ID}`다(v21.0·v23.0·버전 없는 URL이 모두 같은 요청에 200). 어댑터는 `base_url`을 인자로 받고 기본값은 호출자(다음 step)가 `https://graph.facebook.com/v21.0`으로 넘긴다. ② 호출 주체 ID는 `.env`의 `INSTAGRAM_USER_ID`다(어댑터는 `ig_user_id` 인자로만 받는다). ③ **다음 쪽은 `media.after(<커서>).limit(100){...}` 형태로 요청한다**(`media.limit(N).after(<커서>)`도 같게 동작하고 쪽 사이 겹침 0건이었다). 실측: torriden_official을 끝까지 넘기면 쪽당 100건으로 8쪽, 고유 ID 650건이고, **마지막 쪽(20건)에는 `cursors.after` 키가 없고 `next`도 없다**(`after` 부재가 종료).
> **주의**: 같은 응답의 `media_count`는 612였는데 실제로 650건이 반환됐다. **`media_count`는 참고 값일 뿐**이고 수집 완료 판정·분할 제약·진행률에 쓰지 않는다.

### 설정 로더 (`config.py`에 추가)

```python
class InstagramAccount(BaseModel):   # 필수: brand, username. 선택: region, verified (실제 파일은 22개 모두 갖지만 필수로 보지 않는다)
def load_instagram_accounts(path: Path) -> list[InstagramAccount]   # `instagram` 절만 읽는다. username 중복·필드 누락은 ConfigError
```

소비자 테스트 점검 결과: `src/beautyads/sources/config.py`를 import하는 `tests/test_slice.py`·`tests/test_youtube.py`는 `YouTubeChannel`·`load_youtube_channels`만 쓰고 이 step은 함수를 **추가**할 뿐이라 영향이 없다. `tests/test_architecture.py`는 새 모듈을 가드로 검사한다(의도된 관계). 그 파일들은 수정하지 않는다.

기존 `YouTubeChannel`·`load_youtube_channels`·`ConfigError`는 바꾸지 않는다(오류 코드 `INSTAGRAM_CONFIG_UNREADABLE`·`INSTAGRAM_CONFIG_INVALID`·`INSTAGRAM_USERNAME_DUPLICATE`를 새로 쓴다).

### 어댑터 (`instagram.py`) — 시그니처

```python
class InstagramHttpResponse(NamedTuple):
    status: int
    body: Any | None
    headers: Mapping[str, str]          # 키는 소문자로 정규화

InstagramGet = Callable[[str, Mapping[str, str], float], InstagramHttpResponse]
def instagram_httpx_get(url: str, params: Mapping[str, str], timeout_s: float) -> InstagramHttpResponse   # 이 모듈에서 httpx를 쓰는 유일한 함수. 요청 실패는 InstagramError("INSTAGRAM_REQUEST_FAILED")

class InstagramError(Exception):         # 속성: code. 토큰·URL 쿼리를 메시지에 넣지 않는다

def business_discovery_fields(username: str, *, limit: int = 100, after: str | None = None) -> str
    # after가 없으면 `media.limit(100){...}`, 있으면 `media.after(<커서>).limit(100){...}`
def parse_usage_pct(headers: Mapping[str, str]) -> float | None
def media_to_creative(post: Mapping[str, Any], *, account: InstagramAccount, collected_at: datetime) -> Creative

class AccountPage(NamedTuple):
    posts: list[Mapping[str, Any]]
    next_after: str | None
    followers_count: int | None
    media_count: int | None              # 참고 값일 뿐이다(실측: 612로 보고됐으나 650건 반환). 완료 판정·진행률에 쓰지 않는다
    usage_pct: float | None

def fetch_account_page(get, token: str, ig_user_id: str, account: InstagramAccount, *, base_url: str, after: str | None = None, limit: int = 100) -> AccountPage
def collect_instagram(get, token: str, ig_user_id: str, accounts: Sequence[InstagramAccount], *, base_url: str,
                      max_posts_per_account: int, collected_at: datetime, usage_stop_pct: float = 80.0) -> CollectResult
    # CollectResult는 beautyads.sources.youtube의 것과 같은 모양(creatives, errors: {username: 코드}, stopped)을 쓴다. youtube 모듈에서 import해 재사용한다

def parse_oe_expiry(url: str) -> datetime | None
def needs_refresh(url: str | None, now: datetime, *, min_remaining_s: float = 21600.0) -> bool

class RefreshResult(NamedTuple):
    urls: dict[str, str]                 # id → 새 media_url(영상으로 받을 수 있는 것)
    gone: set[str]                       # 게시물은 찾았는데 media_url 키가 없는 id
    missing: set[str]                    # 최대 쪽 수 안에서 찾지 못한 id
    stopped: str | None

def refresh_media_urls(get, token: str, ig_user_id: str, account: InstagramAccount, wanted_ids: Collection[str], *,
                       base_url: str, now: datetime, max_pages: int = 5, usage_stop_pct: float = 80.0) -> RefreshResult
```

- 요청: `GET {base_url}/{ig_user_id}`에 `fields=business_discovery.username(<대상>){followers_count,media_count,media.limit(100){id,media_type,media_product_type,media_url,permalink,timestamp,caption,like_count,comments_count,view_count}}`와 `access_token=<token>`을 쿼리로 보낸다. `permalink`를 요청한다(표본 8건 모두에 있었다. 키가 없을 수 있다고 보고 읽는다). 한 번에 최대 100건을 받는다(실측: 200 OK, 100건).
- 다음 쪽: 응답의 `business_discovery.media.paging.cursors.after`로 이어 가고 **그 키가 없으면 마지막 쪽이다**(`next` 주소는 없다). `max_posts_per_account`에 도달하면 멈추고 잘라낸다.
- `media_to_creative`: `source=instagram`, `source_id`=게시물 `id`(문자열), `url`=`permalink`(없으면 `None`), `caption`, `published_at`=`timestamp`(`2026-10-11T02:00:12+0000` 형태를 시간대 포함 값으로 파싱, 실패하면 `None`), `duration_s=None`, `language=None`, `brand=account.brand`, `account=account.username`, `collected_at`. 지표: `view_count`·`like_count`·`comment_count`(`comments_count`)는 **키가 없으면 `None`**(0이 아니다. 묶음 게시물은 `view_count` 키가 없고 영상이라도 없을 수 있다). **`media_url`은 `Creative`에 저장하지 않는다**(서명이 붙은 임시 주소이고 `Creative`에 그 필드가 없다).
- **`analyzable`**: `media_type == "VIDEO"`이고 `media_url` 키가 있으면 `True`, `media_type == "VIDEO"`인데 `media_url`이 없으면 `False`, 알려진 다른 값(`IMAGE`, `CAROUSEL_ALBUM` 등)이면 `False`, `media_type` 키가 없거나 알 수 없는 값이면 `None`. (실측: 릴스의 `media_url` 반환 여부는 5초·15분·약 20시간 뒤 재조회에서도 같았고 계정 단위 편차가 크다: 0%~100%.)
- `parse_usage_pct`: 응답 헤더 `x-app-usage`(JSON 문자열, `call_count`·`total_cputime`·`total_time`)에서 세 값의 **최댓값(%)**을 돌려준다. 헤더가 없거나 JSON이 아니면 `None`. 호출마다 읽어 `usage_stop_pct`(기본 80) 이상이면 그 시점까지 모은 것을 돌려주고 `stopped="INSTAGRAM_USAGE_HIGH"`로 끝낸다.
- 오류(HTTP 상태를 먼저 본다, 본문 `error.code`는 `.get`으로 읽는다): 400이고 `error.code == 110`이면 그 계정만 `INSTAGRAM_ACCOUNT_NOT_FOUND`로 기록하고 다음 계정으로, `error.code == 190`이면 `INSTAGRAM_TOKEN_INVALID`로 전체를 멈춘다(`stopped`), **`error.code`가 `4`·`17`·`32`·`613`(Graph API의 앱·계정 사용량 한도로 알려진 코드. 이 프로젝트에서 실측하지 못한 값이다)이면 `INSTAGRAM_RATE_LIMITED`로 출처 전체를 멈추고(`stopped`) 재시도하지 않는다**(계정마다 반복하면 한도만 더 깎는다), 그 밖에 200이 아니면 그 계정만 `INSTAGRAM_ERROR_<error.code 또는 HTTP 상태>`. 요청 실패(`INSTAGRAM_REQUEST_FAILED`)는 그 계정만 기록한다. **한 계정의 오류로 전체를 끝내지 않는다.**
- `parse_oe_expiry`: 미디어 URL의 쿼리 파라미터 `oe`(16진 Unix 시각, 초)를 시간대 포함 `datetime`으로. 없거나 해석할 수 없으면 `None`. `needs_refresh`: `url`이 `None`이거나 `oe`를 해석할 수 없거나 남은 시간이 `min_remaining_s`(기본 6시간) 미만이면 `True`(안전하게 재조회).
- `refresh_media_urls`: **특정 게시물만 조회하는 방법은 없으므로** 계정의 미디어 목록을 최대 `max_pages` 쪽(쪽당 100건) 훑어 `wanted_ids`를 찾는다. 찾은 게시물이 `media_type == "VIDEO"`이고 `media_url`이 있으면 `urls`에, 게시물은 찾았는데 `media_url`이 없으면 `gone`에(호출자가 `analyzable=False`로 갱신한다), 끝까지 못 찾으면 `missing`에 담는다. 모두 찾으면 일찍 멈춘다. 사용량 방어는 `collect_instagram`과 같다.

### 반드시 있어야 하는 테스트

- `tests/test_sources_config.py`: 임시 YAML로 정상·**`region`·`verified`가 없는 항목도 통과**·`brand`·`username` 누락·`username` 중복, 실제 `config/sources.yaml`의 `instagram` 절을 읽어 1개 이상이고 `username`이 서로 다름(개수 고정 단언 금지), 기존 YouTube 로더 테스트는 그대로 통과.
- `tests/test_instagram.py`(가짜 `InstagramGet`, 응답 본문은 원본 `instagram_*.json`의 `response`에서 만든다):
  - 원본 게시물이 `Creative`로 변환되고 `brand`·`account`·`url`(permalink)·지표가 맞다. **`view_count`·`like_count`가 없는 게시물은 `None`(0 아님)**, `media_url`이 `Creative` 어디에도 없다.
  - `analyzable`의 모든 분기: VIDEO+`media_url` → True, VIDEO+키 없음(`without_media_url` 원본의 게시물) → False, `CAROUSEL_ALBUM` → False(묶음 게시물에 `media_url`이 있어도), 알 수 없는 `media_type` → None.
  - 쪽 넘김: 첫 쪽이 `after` 커서를 갖고 둘째 쪽은 그 키를 지운 복사본일 때 정확히 두 번 호출하고 멈춤, `max_posts_per_account`로 자르기, 요청 `fields`가 `limit`·`after`를 반영하고 `permalink`를 포함, 100건 쪽을 원본 게시물을 복제(`id`만 바꿈)해 합성해도 처리됨.
  - 오류: 110 원본 → 그 계정만 `INSTAGRAM_ACCOUNT_NOT_FOUND`하고 다음 계정은 수집됨, 190 원본 → `stopped == "INSTAGRAM_TOKEN_INVALID"`, `4`·`17`·`32`·`613` → `stopped == "INSTAGRAM_RATE_LIMITED"`이고 **이후 계정을 호출하지 않으며 재시도하지 않는다**(테스트는 `instagram_error_bad_token.json` 원본의 구조를 복사해 `error.code`와 메시지만 바꾼 합성 본문을 쓴다. 코드 값 외의 형태는 원본을 따른다), 그 밖의 400 → `INSTAGRAM_ERROR_<코드>`. 토큰 문자열이 `errors`·`stopped`·예외 메시지·`repr`에 없다.
  - 사용량: `x-app-usage` 헤더가 80% 이상이면 `INSTAGRAM_USAGE_HIGH`로 그때까지 모은 것을 돌려주고 멈춤, 헤더 없음·깨진 JSON은 계속 진행, `parse_usage_pct`가 세 값의 최댓값을 돌려줌.
  - `oe` 파싱·`needs_refresh`: **합성 URL**(`https://example.invalid/v.mp4?oe=<16진 시각>&oh=x`)로 만료 시각 파싱, 남은 시간이 6시간 미만·정확히 경계·충분함, `oe` 없음·`None`·해석 불가는 `True`. (원본은 서명 쿼리를 지워서 `oe`가 없으므로 URL 파싱만 합성 문자열을 쓴다. API 응답 형태는 합성하지 않는다.)
  - `refresh_media_urls`: 찾은 영상은 `urls`, 찾았지만 `media_url` 없음은 `gone`, 못 찾은 것은 `missing`, `max_pages`에서 멈춤, 모두 찾으면 조기 종료.

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

- `media_url`(서명 임시 주소)을 `Creative`에 저장하거나 로그·오류 메시지·출력에 남기지 마라. 이유: 만료되는 주소이고 서명이 포함된다. 분석 직전에 `refresh_media_urls`로 새로 받는다(CONTRACTS Instagram).
- 게시물 유형을 `media_url` 유무로 판정하지 마라. `media_type == "VIDEO"`로 판정한다. 이유: 묶음 게시물에도 `media_url`이 올 수 있고 그것은 영상이 아니다. 모르는 `media_type` 값이 와도 죽지 않고 `None`(미판정)으로 둔다(FP-C01).
- `media_url`·`permalink`·`view_count`가 없는 응답을 오류로 취급하거나 `[]`로 직접 읽지 마라. 키는 없을 수 있다고 보고 `.get`으로 읽는다. 이유: `null`이 아니라 키 자체가 빠지고 같은 계정 안에서도 게시물마다 다르다(FP-C01).
- 한 계정의 오류로 전체 수집을 끝내지 마라. 토큰 오류(190)와 사용량 방어만 전체를 멈춘다. 이유: 계정 하나의 실패가 배치를 막으면 안 된다(A-FP-030).
- API 응답 형태를 손으로 새로 쓴 가짜로 검증하지 마라. 응답 본문은 `instagram_*.json` 원본에서 만들고 변형(키 지우기, 게시물 복제)은 코드로 한다. 합성 문자열은 `oe` URL 파싱에만 쓴다. 이유: 코드와 가짜 응답이 같은 추측을 공유하면 틀려도 통과한다(B-FP-020).
