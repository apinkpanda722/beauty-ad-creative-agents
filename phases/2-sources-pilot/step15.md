# Step 15: tiktok-source

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P2 sources-pilot"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/CONTRACTS.md` — "TikTok Commercial Content API" 표와 주의 전체(토큰 발급, 광고 조회, 성공 응답에도 `error`가 있다, 날짜는 문자열, `max`는 오늘보다 앞, 광고주 이름 40%가 숫자, 500 간헐 오류)
- `/tests/fixtures/contracts/tiktok_ad_query.json`, `tiktok_oauth_token.json`, `tiktok_error_bad_token.json`, `tiktok_error_date_as_number.json`, `tiktok_error_missing_filter.json`, `tiktok_error_date_max_not_before_today.json` — 응답 원본(수정 금지). 광고 한 건은 `{"ad": {...}, "advertiser": {...}}` 구조다
- `/tests/fixtures/contracts/tiktok_ad_query_mixsoon_page2.json`, `tiktok_ad_query_mixsoon_last.json`, `tiktok_ad_query_dalba_last.json` — 쪽 넘김·마지막 쪽 원본과 광고주 이름 분포(이 파일들은 계약 PR로 들어온 뒤에만 존재한다. 없으면 `blocked`로 보고한다)
- `/config/sources.yaml` — `tiktok` 절(`countries`, `lookback_days`, `search_type`, `brands[]`는 `{brand, search_term}`)과 `/config/product_candidates.yaml` 머리말. 읽기만 한다
- `/src/beautyads/sources/youtube.py`, `/src/beautyads/sources/instagram.py`, `/src/beautyads/sources/config.py`, `/src/beautyads/sources/media.py` — 이전 어댑터의 방식(주입형 HTTP, 안정된 오류 코드, 계정 단위 격리, `CollectResult`)
- `/src/beautyads/domain/creative.py` — `Creative`(`brand`·`account`·`attributes` 포함)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/sources/tiktok.py`, `src/beautyads/sources/config.py`, `config/retailers.yaml`, `tests/test_tiktok.py`, `tests/test_sources_config.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/sources/tiktok.py`, `src/beautyads/sources/config.py`(`load_tiktok_config`·`load_retailers` 추가에 한함, 기존 동작 불변), `config/retailers.yaml`, `tests/test_tiktok.py`, `tests/test_sources_config.py`(추가에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 라벨 키 파일을 읽는 채점 함수, 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

TikTok Commercial Content API(EU 게재 광고) 수집 어댑터를 만든다. TikTok은 **E1 표본에서 제외**하고 그래프·에이전트 데이터로만 쓴다. 소재 언어는 주로 영어·유럽 언어다. `sources/`는 `domain`과 `settings`만 import하고 `httpx`는 이 계층에서만 쓴다. **테스트는 가짜 HTTP 함수와 `tests/fixtures/contracts/`의 원본으로만 하고 실제 호출은 하지 않는다.**

> **확정된 호출 형태(실측, 2026-11-12)**: ① 호스트 `https://open.tiktokapis.com`(어댑터는 `base_url` 인자로 받고 기본값 상수 `TIKTOK_BASE_URL`), 토큰 `POST /v2/oauth/token/`, 조회 `POST /v2/research/adlib/ad/query/`. ② `fields` 쿼리 값은 쉼표로 이은 경로: `ad.id,ad.first_shown_date,ad.last_shown_date,ad.status,ad.videos,ad.image_urls,ad.reach,advertiser.business_id,advertiser.business_name,advertiser.paid_for_by`(상수 `QUERY_FIELDS`). ③ 본문 최상위에 `search_term`(검색어)과 **`search_type`**(`sources.yaml`의 `search_type` 값 `"exact_phrase"`를 그대로 넣는다. 잘못된 값은 400 `invalid_params`로 `` `search_type: <값>` is not recognized ``가 온다). ④ **`max_count`(최대 10)와 `search_id`도 본문 최상위**(`filters`와 같은 층)이고 다음 쪽은 같은 본문에 직전 응답 `data.search_id`를 `search_id`로 추가한다. 본문 예: `{"filters": {"ad_published_date_range": {"min": "YYYYMMDD", "max": "YYYYMMDD"}, "country_code_list": ["DE", "FR"]}, "search_term": "<검색어>", "search_type": "exact_phrase", "max_count": 10}`. 토큰 요청은 `application/x-www-form-urlencoded`로 `client_key`·`client_secret`·`grant_type=client_credentials`(응답 `access_token`, `expires_in` 7200, `token_type`). 이 형태를 `build_query_body` 한 함수에 모은다.

소비자 테스트 점검 결과: `src/beautyads/sources/config.py`를 import하는 기존 테스트는 YouTube·Instagram 로더만 쓰고 이 step은 함수를 **추가**할 뿐이다. `tests/test_architecture.py`는 새 모듈을 가드로 검사한다(의도된 관계). 그 파일들은 수정하지 않는다.

### 설정 (`config.py`에 추가, `config/retailers.yaml`)

```python
class TikTokConfig(BaseModel):
    countries: list[str]; lookback_days: int; search_type: str
    brands: list[TikTokBrand]              # TikTokBrand: brand, search_term
def load_tiktok_config(path: Path) -> TikTokConfig      # sources.yaml의 tiktok 절은 **리스트가 아니라 dict**다. 구조가 다르면 ConfigError("TIKTOK_CONFIG_INVALID")
class Retailers(BaseModel): names: frozenset[str]       # 정규화된 판매처 이름
def load_retailers(path: Path) -> Retailers
```

- `config/retailers.yaml`: `retailers:` 아래에 판매처 이름 목록(소문자로 정규화해 비교한다). **시드는 관측 기반이다: `sephora`(CONTRACTS가 언급, 이번 원본에는 없음), `etos`, `cosibella`, `pilulka`, `pharmacontinente`.** CONTRACTS는 "에토스(Ethos)"라고 적었지만 **원본의 광고주 이름은 `Etos B.V.`다**(문서 표기를 그대로 믿지 말고 원본을 따른다). 이 목록은 **사용자 확인이 필요한 초안**이라는 주석을 파일 맨 위에 유지한다.

### 어댑터 (`tiktok.py`) — 시그니처

```python
class TikTokHttpResponse(NamedTuple): status: int; body: Any | None
TikTokPost = Callable[[str, Mapping[str, str], Mapping[str, Any] | None, Mapping[str, str] | None, float], TikTokHttpResponse]
    # (url, params, json_body, form_body, timeout_s) — POST 하나로 토큰 발급(form)과 조회(json)를 모두 다룬다
def tiktok_httpx_post(...) -> TikTokHttpResponse            # 이 모듈에서 httpx를 쓰는 유일한 함수. 요청 실패는 TikTokError("TIKTOK_REQUEST_FAILED")
class TikTokError(Exception): code                           # 토큰·비밀 문자열을 메시지에 넣지 않는다

class TokenProvider:                                         # client_credentials 토큰 발급과 캐시
    def __init__(self, post, *, base_url, client_key, client_secret, now: Callable[[], datetime])
    def token(self) -> str                                   # 만료 60초 전이면 재발급. expires_in은 응답 값(실측 7200초)
    def invalidate(self) -> None                             # 401 access_token_invalid를 받았을 때

def build_query_body(brand: TikTokBrand, config: TikTokConfig, *, today: date, search_id: str | None) -> dict   # 위 확정된 본문 형태를 만드는 유일한 곳
def classify_executor(advertiser: Mapping[str, Any], *, brand_names: Collection[str], retailers: Retailers) -> str
def ad_to_creative(item: Mapping[str, Any], *, brand: str, collected_at: datetime, executor: str) -> Creative
def collect_tiktok(post, token: TokenProvider, config: TikTokConfig, retailers: Retailers, *, base_url: str,
                   max_pages: int, collected_at: datetime, brands: Collection[str] | None = None) -> CollectResult

def refresh_tiktok_video_urls(post, token, config, brand: TikTokBrand, wanted_ids: Collection[str], *, base_url: str,
                              today: date, max_pages: int) -> RefreshResult   # 이전 step의 RefreshResult와 같은 모양. max_pages는 필수 인자
```

- **조회**: `POST {base_url}/v2/research/adlib/ad/query/?fields=...`, 헤더 `Authorization: Bearer <토큰>`. 필터는 `ad_published_date_range`(`min`·`max` **`"YYYYMMDD"` 문자열**. `max`는 **어제 이전**: 오늘 날짜를 넣으면 400이고 숫자로 보내면 400이다)와 `country_code_list`(배열). `min`은 `today - lookback_days`. `max_count`는 최대 10.
- **쪽 넘김**: 응답 `data`에 `ads`, `has_more`, `search_id`가 온다. **종료는 `has_more == false`**이다(마지막 쪽에도 `search_id`가 오므로 그 유무로 판정하지 않는다. 마지막 쪽은 10건 미만일 수 있다). 다음 쪽 요청에 마지막으로 받은 `search_id`를 넣는다. **쪽 사이에 같은 광고가 다시 오므로(실측: 29건 받아 28 고유, 49건 받아 43 고유) `ad.id`로 중복을 제거한다.** 쪽당 2~3초. `max_pages`에 도달하면 멈춘다.
- **성공 판정**: HTTP 상태를 먼저 본다. 200이어도 본문에 `error` 키가 있으니 **`error.code == "ok"`일 때만 성공**이다(`error`의 존재로 실패를 판정하지 않는다). 401이고 `error.code == "access_token_invalid"`면 `TokenProvider.invalidate()` 뒤 **한 번만** 재발급해 다시 요청하고, 그래도 401이면 `TIKTOK_TOKEN_INVALID`로 전체를 멈춘다(`stopped`). 400이면 `TIKTOK_INVALID_PARAMS`로 전체를 멈춘다(우리 요청 오류다). 500(`internal_error`, 간헐적)·503·429는 이 모듈이 재시도하지 않고 그 브랜드만 `TIKTOK_HTTP_<상태>`로 기록한다(재시도는 호출자의 `with_retries`가 한다). 한 브랜드의 오류로 전체를 끝내지 않는다.
- **`ad_to_creative`**: 광고 한 건은 `{"ad": {...}, "advertiser": {...}}`다. `source=tiktok`, `source_id=str(ad.id)`(광고 ID는 숫자), `url=None`(안정적인 보기 링크가 없다), `title`·`caption`·`duration_s`·`language`는 `None`, `published_at` = `ad.first_shown_date`(`YYYYMMDD`)의 UTC 자정, `brand`=조회한 브랜드, `account`=광고주 `business_id` 문자열, 지표 열(`metrics`)은 모두 `None`(**도달 구간은 지표 열에 넣지 않는다**). **`analyzable`**: `ad.videos` 중 `url` 키가 있는 항목이 있으면 `True`, 없으면 `False`. **`attributes`**: `first_shown_date`, `last_shown_date`, `status`, `reach_unique_users_seen`(문자열 구간 그대로), `advertiser_business_id`·`advertiser_business_name`·`advertiser_paid_for_by`, `executor`, `has_image_urls`(불리언. `image_urls`는 이미지 없는 광고에서 키 자체가 없다). **영상 주소(`videos[].url`)·커버 이미지 주소는 저장하지 않는다**(만료 시각이 미확인인 서명 주소다).
- **`classify_executor`**: 광고주 `business_name`을 **정규화**한다(소문자로 바꾸고 문자·숫자가 아닌 글자를 공백으로 바꿔 공백으로 나눈 **단어 토큰 목록**). ① 이름이 `None`·빈 문자열이거나 **숫자로만 이루어져 있으면 `"unknown"`**(광고주 이름의 상당수가 숫자 ID로 온다: 실측 38건 중 16건이 숫자, 1건이 빈 이름) ② **브랜드 이름·검색어**(`brand_names`, 같은 방식으로 정규화한 토큰 목록)의 토큰이 광고주 이름 토큰 목록 안에 **연속된 부분 수열로 들어 있으면** `"brand_direct"`(예: `"Mixsoon Limited"` → 토큰 `[mixsoon, limited]`에 브랜드 `mixsoon`이 있다. 여러 단어 브랜드(`beauty of joseon`)는 그 단어들이 이어서 나와야 한다) ③ 그렇지 않고 **판매처 이름**이 같은 방식으로 들어 있으면 `"retailer"`(예: `"Etos B.V."` → `[etos, b, v]`에 `etos`) ④ 그 밖이면 `"unknown"`(예: 대행사로 보이는 `"JJ Media Ltd"`는 판매처 목록에도 없으므로 `unknown`이다). 브랜드가 판매처보다 먼저 판정된다. **전체 일치로 비교하지 않는다**(법인 접미사 `Limited`, `B.V.`, `a.s.`가 붙어 전체 일치는 실제 이름을 놓친다). 개인 광고는 이름으로 구분할 수 없으므로 판정하지 않는다. **광고주 이름만으로 브랜드를 판정하지 않는다**: `brand`는 조회한 브랜드이고 `executor`는 별도 속성이다.
- **`refresh_tiktok_video_urls`**: 분석 직전에 새 영상 주소가 필요하다. 특정 광고만 조회하는 방법이 있는지 확인하지 못했으므로 **그 브랜드 검색을 다시 훑어(최대 `max_pages`쪽)** `wanted_ids`를 찾는다. **`max_pages`는 수집 때 쓴 값과 같거나 더 크게 넘겨야 한다**(재조회가 수집보다 적게 훑으면 `missing`이 늘어난다. 그래서 기본값을 두지 않는 필수 인자다). 찾은 광고에 `videos[].url`이 있으면 `urls`, 광고는 찾았는데 영상 주소가 없으면 `gone`, 못 찾으면 `missing`. 영상 주소 만료 시각은 미확인이다.

### 반드시 있어야 하는 테스트

- `tests/test_sources_config.py`: 임시 YAML로 `tiktok`이 **dict**인 정상 구조, 리스트 구조는 `TIKTOK_CONFIG_INVALID`, `brands` 항목의 필드 누락, 실제 `config/sources.yaml`의 `tiktok` 절을 읽어 `countries`가 비어 있지 않고 `brands`가 1개 이상이며 `brand`가 서로 다름(개수 고정 금지). `load_retailers`가 정규화된 이름을 돌려주고 실제 `config/retailers.yaml`을 읽을 수 있다.
- `tests/test_tiktok.py`(가짜 `TikTokPost`, 응답 본문은 `tiktok_*.json` 원본의 `response`에서 만든다):
  - 토큰: 원본 토큰 응답으로 `TokenProvider.token()`이 토큰을 돌려주고 만료 60초 전까지 재사용(발급 호출 1회), 만료가 가까우면 재발급, `invalidate()` 뒤 재발급. 비밀(`client_secret`)이 오류·`repr`에 없다.
  - 조회 본문: 날짜가 **문자열**이고 `max`가 어제(오늘이 아님), `min`이 `today - lookback_days`, `country_code_list`가 배열이며 `max_count <= 10`.
  - 쪽 넘김: 첫 쪽 원본(`has_more: true`)과 마지막 쪽(첫 쪽을 복사해 `has_more`를 `false`로, 광고 수를 9건으로)을 이어 정확히 두 번 호출하고 멈춤, **마지막 쪽에 `search_id`가 있어도 `has_more`로만 종료**, 둘째 요청 본문에 첫 쪽의 `search_id`가 들어 있다, **쪽 사이 중복 `ad.id`가 한 건으로 합쳐진다**, `max_pages`로 멈춤.
  - 성공·오류 판정: 200이고 `error.code == "ok"`면 성공, 401 `access_token_invalid` 원본 → 토큰을 다시 받아 **한 번** 재요청하고 성공하면 계속, 재요청도 401이면 `stopped == "TIKTOK_TOKEN_INVALID"`, 400 원본(날짜 숫자·`max`가 오늘·필터 누락) → `stopped == "TIKTOK_INVALID_PARAMS"`, 500은 그 브랜드만 `TIKTOK_HTTP_500`이고 다음 브랜드는 수집됨.
  - `ad_to_creative`: 원본 광고가 `Creative`로 변환되고(`source_id`가 문자열, `published_at`이 UTC 자정, `account`가 광고주 ID 문자열, `analyzable`이 영상 주소 유무에 따라 `True`/`False`, 지표 열이 모두 `None`) `attributes`에 도달 구간 문자열이 **그대로** 들어 있고 영상 주소·커버 이미지 주소 문자열이 `Creative` 어디에도 없다(감시 문자열로 확인). `image_urls`가 없는 광고도 오류 없이 처리되고 `has_image_urls`가 `False`.
  - `classify_executor`: **이름은 원본에서 읽어 쓴다**(감시 문자열을 지어내지 않는다). 테스트는 `tiktok_ad_query.json`·`tiktok_ad_query_mixsoon_*.json`·`tiktok_ad_query_dalba_last.json`의 `advertiser.business_name`을 읽고, 아래 표의 각 이름이 **실제로 그 원본들에 존재함**을 먼저 단언한 뒤 분류를 단언한다: `"Mixsoon Limited"`(검색 브랜드 `mixsoon`) → `brand_direct`, `"Etos B.V."`·`"Cosibella"`·`"Pilulka Lékárny a.s."`·`"PHARMACONTINENTE - SAÚDE E HIGIENE, S.A."` → `retailer`(시드 `etos`·`cosibella`·`pilulka`·`pharmacontinente`), `"JJ Media Ltd"` → `unknown`, 숫자만으로 된 이름들·빈 문자열·`None` → `unknown`. 정규화 단위 테스트: 대소문자·구두점·악센트가 있는 글자·여러 단어 브랜드(`beauty of joseon`)의 연속 일치, 단어의 일부만 일치하는 경우(`mix`가 `mixsoon`을 `brand_direct`로 만들지 않음)는 일치가 아니다, 브랜드와 판매처가 모두 들어 있으면 `brand_direct`. **이름이 브랜드와 비슷해도 `Creative.brand` 필드는 조회한 브랜드 그대로다.**
  - `refresh_tiktok_video_urls`: 찾은 영상은 `urls`, 영상 주소 없음은 `gone`, 못 찾음은 `missing`, `max_pages`에서 멈춤, 모두 찾으면 조기 종료.
  - 한 브랜드의 오류로 전체를 끝내지 않음, 어떤 오류 코드·`stopped`·예외 메시지에도 토큰·비밀 문자열이 없음.

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

- 성공 판정을 `error` 키의 존재로 하지 마라. 200이어도 `error`가 오며 `error.code == "ok"`일 때만 성공이다. 이유: 성공 응답에도 `error` 객체가 들어 있다(`docs/CONTRACTS.md` TikTok).
- `search_id`의 유무로 쪽 넘김을 끝내지 마라. `has_more == false`로만 끝낸다. 이유: 마지막 쪽에도 `search_id`가 온다(실측).
- 쪽 사이 중복을 그대로 저장하지 마라. `ad.id`로 중복을 제거한다. 이유: 같은 광고가 다른 쪽에 다시 오고(실측: 49건 중 6건 중복) 중복 키가 (출처, 원본 ID)다(A-FP-033).
- 광고주 이름으로 브랜드를 판정하지 마라. `brand`는 조회한 브랜드이고 집행 주체는 `attributes.executor`로 따로 둔다. 숫자 이름과 목록 밖은 `unknown`이다. 이유: 광고주 이름의 40%가 숫자이고 브랜드 이름으로 검색하면 판매처·개인 광고가 섞인다(`docs/CONTRACTS.md` TikTok).
- 영상·커버 이미지 주소와 토큰·비밀을 `Creative`·`attributes`·오류 메시지·출력에 남기지 마라. 도달 구간을 지표 열(`metrics`)에 넣지 마라. 이유: 만료 시각이 미확인인 서명 주소이고, 출처마다 지표의 뜻이 달라 직접 비교하면 안 된다(ADR-004).
