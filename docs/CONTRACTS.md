# 외부 계약 실측 목록

외부 서비스의 응답 형태를 **실제 응답으로 확인한 것만** 적는다. 문서나 추측으로 아는 것은 "미확인"에 따로 둔다. phase를 설계할 때 그 phase가 건드리는 외부 지점을 여기서 찾아 step 파일에 근거 경로와 함께 옮긴다. 여기에 없는 외부 지점을 쓰는 step은 먼저 실측하고 이 문서에 추가한 뒤 설계한다.

- 실측일: 2026-11-11 ~ 12
- 원본 응답: `tests/fixtures/contracts/` (비밀 값과 서명 문자열만 지우고 나머지는 응답 그대로)
- 픽스처를 만들 때는 이 원본을 복사해 쓴다. 손으로 새로 쓰지 않는다.

## YouTube Data API v3

| 확인한 것 | 실제 형태 | 원본 |
|---|---|---|
| 핸들로 채널 찾기 | `channels?forHandle=@핸들`. `items[0].id`가 채널 ID, `contentDetails.relatedPlaylists.uploads`가 업로드 목록 | `youtube_channels_forhandle.json` |
| 채널 통계 | `channels` 응답 항목에 `statistics`가 있고 값은 문자열이다(`viewCount`, `subscriberCount`, `videoCount: "107"`, `hiddenSubscriberCount`). 업로드 영상 수를 분할·진행률 판정에 쓰지 않는다(참고 값) | `youtube_channels_forhandle.json` |
| **없는 핸들** | 오류가 아니라 **200**이고 **`items` 키 자체가 없다**(빈 배열이 아님) | `youtube_channels_forhandle_missing.json` |
| 업로드 목록 | `playlistItems`의 `items[].contentDetails.videoId`(와 `videoPublishedAt`), 다음 쪽은 `nextPageToken`. **마지막 쪽에는 `nextPageToken` 키가 없다**(`null`이 아니라 키 부재. 마지막 쪽에 도달한 8개 채널 모두. 150개 상한에서 멈춘 채널은 마지막 쪽을 확인하지 않았다). 항상 `.get`으로 읽는다 | `youtube_playlistitems.json`, `instagram_mfds_youtube_probe.json` |
| 영상 상세 | `statistics`의 값이 **전부 문자열**(`"viewCount": "1973746"`). `contentDetails.duration`은 `PT2M14S` 형식 | `youtube_videos.json` |
| 잘못된 키 | 400, `error.code`는 정수, `error.status`는 `INVALID_ARGUMENT` | `youtube_error_bad_key.json` |

주의:
- `statistics`의 키는 영상마다 빠질 수 있다. 17개 채널 업로드 영상 1,349개를 확인한 결과 **`likeCount` 없음 26개(1.9%), `commentCount` 없음 7개, `viewCount` 없음 0개**였다(키가 빠진 영상의 다른 필드는 정상). 좋아요·댓글은 선택 필드로 읽고 없으면 `null`(0이 아님)로 저장한다. 조회수 기반 백분위에는 영향이 없다(`instagram_mfds_youtube_probe.json`).
- 채널을 이름으로 검색(`search?type=channel`)하면 공식 채널이 아닌 것이 섞인다. 8곳 중 3곳이 틀렸다. 채널은 `config/sources.yaml`의 ID로만 찾는다.
- 쿼터: 호출별 단위 비용과 하루 한도는 **미확인**이다(문서 요약과 기억이 서로 달랐고, 응답에 사용량이 나오지 않는다. 2026-11-12 약 60회 호출 중 `quotaExceeded`는 나오지 않아 그 오류 형태도 미실측이다). 채널 이름 검색은 쓰지 않으므로 수집은 `channels`·`playlistItems`·`videos` 세 호출만 쓴다. 사용량은 Cloud 콘솔에서 확인한다. 오류 파서는 HTTP 상태를 먼저 보고 `error.errors[0].reason`을 읽는다.

## Instagram Graph API (Business Discovery)

| 확인한 것 | 실제 형태 | 원본 |
|---|---|---|
| 호출 주체와 기본 URL | `GET https://graph.facebook.com/v21.0/{내 IG 사용자 ID}`에 `fields=business_discovery.username(대상){followers_count,media_count,media.limit(100){id,media_type,media_product_type,media_url,permalink,timestamp,caption,like_count,comments_count,view_count}}`와 `access_token`을 쿼리로 보낸다. v21.0·v23.0·버전 없는 URL 모두 같은 요청에 200이었다. 호출 주체 ID는 `.env`의 **`INSTAGRAM_USER_ID`**(사용자가 `.env`에 추가함, 2026-11-12). 앱 심사를 신청하지 않은 새 앱에서 동작했다 | `instagram_business_discovery_with_media_url.json` |
| **`media_url`이 없을 때** | `null`이 아니라 **키 자체가 빠진다**. 같은 계정 안에서도 게시물마다 다르다 | `instagram_business_discovery_without_media_url.json` |
| `view_count` | 묶음 게시물에는 **키가 없다**. 영상이라도 없을 수 있다(바이오던스 계정은 릴스 24건 모두 없었다. 이 사례의 원본은 저장하지 않았다) | `instagram_business_discovery_with_media_url.json` |
| 게시물 유형 | 원본에서 본 `media_type`은 `VIDEO`·`CAROUSEL_ALBUM`, `media_product_type`은 `REELS`·`FEED`다. `IMAGE` 등 다른 값은 **미확인**이므로 모르는 값이 와도 죽지 않게 읽는다. 묶음 게시물에도 `media_url`이 올 수 있다(영상이 아님) | 위와 같음 |
| 다음 쪽 | `media.paging.cursors.after`만 준다. `next` 주소는 없다. **다음 쪽은 `media.after(<커서>).limit(100){...}`로 요청한다**(`media.limit(N).after(<커서>)`도 같게 동작하고 쪽 사이 겹침이 0건이었다). 한 번에 **100건**이 반환된다. torriden_official을 끝까지 넘기면 쪽당 100건으로 8쪽, 고유 ID 650건이었고 **마지막 쪽(20건)에는 `cursors.after` 키가 없다**(종료 조건) | `instagram_requery_probe.json` |
| **없는 계정** | 400, `error.code` 110, `error_subcode` 포함 | `instagram_error_invalid_user.json` |
| 잘못된 토큰 | 400, `error.code` 190 | `instagram_error_bad_token.json` |
| **`me/accounts`** | 권한이 다 있어도 **빈 배열**이 온다. 연결된 IG 계정 ID는 페이지 ID로 직접 조회해야 나온다 | `instagram_me_accounts.json` |
| `permalink` | 4계정 × 최근 50건(200건) **모두**에 있었다. 키 부재 사례는 미확인이므로 없을 수 있다고 보고 읽는다. 블라인드 라벨링 시트의 링크로 쓴다(`media_url`은 만료되므로 쓰지 않는다) | `instagram_requery_probe.json` |
| **`media_count`는 참고 값** | 응답의 `media_count`는 612였는데 실제로 650건이 반환됐다. 수집 완료 판정·분할·진행률에 쓰지 않는다 | `instagram_requery_probe.json` |
| **`media_url` 반환 여부는 재조회해도 일관된다** | 4계정 × 50건에서 즉시(5초 뒤)·15분 뒤 재조회의 반환 여부 변화가 0건이었고, 전날 기록한 원본 8건과 약 20시간 뒤 값도 8/8 같았다. 계정 단위 편차가 크다: torriden_official 96%, skin1004official 100%, mediheal_official 0%(릴스 23건 모두 키 없음), beautyofjoseon_official 100%. 3일 뒤의 일관성은 미실측 | `instagram_requery_probe.json` |
| **`media_url` 만료** | URL의 쿼리 파라미터 `oe`(16진 Unix 시각)에 만료 시각이 있다. 49건 모두 받는 시점 기준 남은 시간이 **32~108시간**이었다. 재조회 직후 URL(199개)의 남은 시간은 최소 32.1시간, 대부분 약 104~108시간이었고, 재조회할 때 `oe`는 일부 게시물만 갱신되며(약 4시간 단위로 이동) 나머지는 같은 URL이 유지됐다. 바로 받으면 `Range` 요청에 206, `video/mp4`. 묶음 게시물의 `media_url`은 이미지(`.jpg`)다. **만료된 URL의 응답은 미확인** | `instagram_mfds_youtube_probe.json`, `instagram_requery_probe.json` |
| 계정 재스캔 | 특정 게시물만 조회하는 방법은 없다(Business Discovery는 계정 단위). 계정 재스캔은 `media.limit(100)`으로 계정당 1~2호출이다 | `instagram_requery_probe.json` |
| 사용량 헤더 | 응답 헤더 `x-app-usage`(JSON 문자열: `call_count`, `total_cputime`, `total_time`)가 온다. 9호출 뒤 `call_count`가 4(%)였다 → 호출당 약 0.5%로 추정했으나 **과소추정이었다**: 첫 `make live-collect`에서 13계정(약 26호출)만에 최댓값 기준 80%에 도달해 `INSTAGRAM_USAGE_HIGH`로 멈췄다(사용자 출력 기준. 어느 지표가 올랐는지는 당시 기록이 없어 미확인이며 수집기가 이후 지표별 값을 기록한다) | `instagram_requery_probe.json` |

주의:
- 릴스 영상 주소 반환율은 표본 195건 중 101건(52%)이었고 계정마다 0%~100%로 갈린다.
- **P2 전체 수집(2026-11-12)에서 4계정이 분석 가능 0건이었다**: `anua_global`(150건 중 `/reel/` 주소 82건), `medicube_global_official`(65건), `medicube_korea`(81건), `mediheal_official`(79건)은 각 150건을 수집했고 `/reel/` 주소를 가진 게시물이 65~82건, 그 모두에 조회수가 있는데 `analyzable`이 true인 소재는 0건이다(읽기 전용 DB 조회, 2026-11-13). 영상은 있는데 응답에 `media_url`이 없는 **계정 단위** 현상으로 보이며(위 표의 mediheal_official 0%와 같은 형태), **원인은 미확인**이다. 어댑터는 계약대로 `media_url` 키가 없으면 `analyzable=false`로 둔다. 코드는 바꾸지 않았고 E1 표본·전체 분석에서 이 계정들은 기여하지 않는다.
- `media_url`은 서명이 붙은 임시 주소다. 저장해 두고 나중에 쓰지 않는다. 목록을 조회한 뒤 수 시간 안에 받아 처리하고, 분석이 며칠 뒤면 분석 직전에 계정을 다시 조회해 새 주소를 받는다(위 표). `oe`가 임박(예: 남은 6시간 미만)하면 재조회한다.
- 영상 여부는 `media_type == "VIDEO"`로 판단한다. `media_url` 유무로 판단하면 묶음 게시물이 섞인다.
- 장기 토큰은 약 60일 뒤 만료된다(교환 응답의 `expires_in` 약 5,183,755초). 만료 전 재발급이 필요하다.
- 호출 한도는 **미확인**이다(위 `x-app-usage` 추정만 있다). Graph API의 앱·계정 사용량 오류로 알려진 코드(4, 17, 32, 613)는 이 프로젝트에서 **실측하지 못했다**.

## TikTok Commercial Content API

| 확인한 것 | 실제 형태 | 원본 |
|---|---|---|
| 자격 증명 위치 | 승인되면 연구용 클라이언트가 자동으로 생긴다. 개발자 포털의 **My research**에 있고 **Manage apps**에는 없다. Manage apps에서 앱을 새로 만들면 그 키로도 토큰은 발급되지만 조회는 401로 거부된다 | `tiktok_error_bad_token.json`과 같은 형태 |
| 토큰 발급 | `POST /v2/oauth/token/`, 폼 인코딩(`client_key`, `client_secret`, `grant_type=client_credentials`). `expires_in` 7200초, 리프레시 토큰 없음. 만료되면 다시 발급한다 | `tiktok_oauth_token.json` |
| 광고 조회 | `POST https://open.tiktokapis.com/v2/research/adlib/ad/query/?fields=<쉼표로 이은 경로>`, 본문 JSON. `fields`는 `ad.id,ad.first_shown_date,ad.last_shown_date,ad.status,ad.videos,ad.image_urls,ad.reach,advertiser.business_id,advertiser.business_name,advertiser.paid_for_by`로 200을 확인했다. 본문 최상위: `filters`(`ad_published_date_range`, `country_code_list`), **`search_term`, `search_type`**(`"exact_phrase"`가 유효, 잘못된 값은 400 `invalid_params`로 "`search_type: <값>` is not recognized"), **`max_count`(최대 10)와 `search_id`도 본문 최상위**(`filters`와 같은 층)다. 토큰은 `POST /v2/oauth/token/`을 `application/x-www-form-urlencoded`로 | `tiktok_ad_query.json` |
| **성공 응답에도 `error`가 있다** | 200이어도 `{"data": ..., "error": {"code": "ok", "message": "", "log_id"}}`. `error` 키의 존재로 실패를 판단하면 안 된다. HTTP 상태와 `error.code == "ok"`로 판단한다 | 위와 같음 |
| **날짜는 문자열** | `ad_published_date_range`의 `min`·`max`는 `"YYYYMMDD"` 문자열이어야 한다. 숫자로 보내면 400 | `tiktok_error_date_as_number.json` |
| **`max`는 오늘보다 앞** | 오늘 날짜를 넣으면 400("Please provide a value before today's date"). 기준일은 어제 이전으로 둔다 | `tiktok_error_date_max_not_before_today.json` |
| 날짜 범위 필수 | `ad_published_date_range`가 없으면 400 | `tiktok_error_missing_filter.json` |
| 국가 필터 | `country_code_list` 배열이 동작한다(문서 예시의 `country_code`는 쓰지 않았다) | `tiktok_ad_query.json` |
| 잘못된 토큰 | 401, `error.code` = `access_token_invalid` | `tiktok_error_bad_token.json` |
| 응답 항목 | `ad.id`(숫자), `first_shown_date`·`last_shown_date`(`"YYYYMMDD"` 문자열), `status`(소문자), `videos[].url`·`cover_image_url`, `image_urls[]`, `reach.unique_users_seen`(구간 문자열), `advertiser.business_id`(숫자)·`business_name`·`paid_for_by` | `tiktok_ad_query.json` |
| 영상 파일 | **`ad.videos[].url`**(`videos`는 최상위가 아니라 `ad` 안)로 mp4를 직접 받을 수 있다. 광고 한 건은 `{"ad": {...}, "advertiser": {...}}`다. 검색어 dalba 광고 10건 모두 `videos[].url`이 있었고 3건을 받았다: 모두 200, `Content-Type: video/mp4`, 리다이렉트 없음, 매직 바이트 `ftypisom`, 크기 **29,172,979바이트(29.2MB)·1,450,844(1.4MB)·29,495,861(29.5MB)**. 앞선 3건 표본의 4.3~10.0MB는 표본이 작았다. 영상 URL 만료 시각은 미확인 | `tiktok_video_download_headers.json` |
| **쪽 넘김** | 모든 쪽의 `data` 키는 `ads`, `has_more`, `search_id` 세 개다. 종료는 **`has_more == false`**인 쪽이다. **마지막 쪽에도 `search_id`가 온다**(그 유무로 종료를 판정하지 않는다). 마지막 쪽은 10건보다 적을 수 있다(9건). 다음 쪽은 같은 본문에 직전 `search_id`를 더해 보낸다. 쪽당 2~3초. 최근 330일·6개국 기준 dalba 3쪽, mixsoon 5쪽 | `tiktok_ad_query_mixsoon_page2.json`, `tiktok_ad_query_mixsoon_last.json`, `tiktok_ad_query_dalba_last.json`, `tiktok_pagination_report.json` |
| **쪽 사이 중복** | 같은 광고 ID가 다른 쪽에 다시 온다(dalba 29건 받아 28 고유, mixsoon 49건 받아 43 고유). `ad.id`로 중복을 제거한다 | `tiktok_pagination_report.json` |
| `image_urls` 키 부재 | 요청한 `ad.image_urls`는 이미지가 없는 광고에서 **키 자체가 없다**(`ad`의 키가 광고마다 다르다) | `tiktok_ad_query_*.json` |

주의:
- **도달 수는 숫자가 아니라 구간 문자열**이다(`"600K-700K"`, `"1M-10M"`). 정렬·비교하려면 구간의 하한이나 중앙값으로 바꿔 쓰고, 바꾼 방식을 결과 문서에 적는다.
- **광고주 이름이 숫자 문자열로 오는 경우가 많다.** 브랜드 3곳 30건 중 12건이 `"7648220666696564758"` 같은 숫자였다. 저장된 원본 38건의 분포: 숫자 이름 16건, 빈 이름 1건, 대행사로 보이는 `"JJ Media Ltd"` 12건, 나머지는 판매처·브랜드 법인(`"Mixsoon Limited"`, `"Etos B.V."`, `"Cosibella"`, `"Pilulka Lékárny a.s."`, `"PHARMACONTINENTE - SAÚDE E HIGIENE, S.A."` 등). **법인 접미사(`Limited`, `B.V.`, `a.s.`)가 붙어 전체 일치로는 브랜드·판매처를 알아볼 수 없다.** 빈 이름과 `null`도 다른 검색에서 관측됐다. 광고주 이름으로 브랜드를 판정하지 않는다.
- **검색어는 광고 내용에 걸린다.** 브랜드 이름으로 찾으면 그 브랜드가 집행한 광고뿐 아니라 그 제품을 파는 소매점(세포라, `Etos` 등. 문서 초안의 "에토스(Ethos)"는 원본의 광고주 이름 `Etos B.V.`와 다르다) 광고와 일반인 광고가 섞인다. 코스알엑스는 광고주 이름이 브랜드와 일치했지만 메디큐브·바이오던스는 대부분 소매점이었다.
- **서버 오류(500 `internal_error`)가 간헐적으로 난다.** 아비브 조회가 한 번 500으로 실패했고 다시 보내자 성공했다. 503·429와 함께 대기 후 재시도 대상으로 둔다.
- 영상 파일이 최대 29.5MB까지 있고(실측) Gemini 인라인 입력이 아니라 Files API 업로드 경로를 쓴다. 영상 바이트를 메모리에서 다루는 코드는 동시 다운로드 수를 제한한다.
- 영상 주소의 만료 시간은 **미확인**이다(주소에 만료 표시 인자가 보이지 않았다. 경로에 16진 토큰이 들어 있으나 의미는 확인하지 못했다). 받을 때마다 새로 조회한다.
- 호출 한도는 **미확인**이다. 응답 헤더에 한도 정보가 없었다.
- EU 게재 광고만 조회된다(신청 페이지 기준). 조회 가능 기간은 최근 1년이다.
- **쪽 수 관찰(2026-11-14, P3 첫 실서비스 수집)**: 14개 브랜드 모두 `--max-pages 20`(쪽당 10건)까지 받아도 `has_more`가 계속 참이었다(브랜드당 200건 수신, 그중 고유 `ad.id` 162~199건, 전체 고유 2,617건). 위 표의 "dalba 3쪽, mixsoon 5쪽에서 끝났다"는 계약 측정 시점의 값과 다르다(원인 미확인: 측정 시점의 차이이거나 검색 범위가 넓어졌을 수 있다). **수집은 20쪽 상한에서 잘렸으므로 브랜드별 총 광고 수·점유율 같은 전체 수치로 쓰지 않는다.** 응답 구조(`{ad, advertiser}`, `ad.id`·`first_shown_date`·`last_shown_date`·`status`·`reach`·`videos`·`image_urls`)와 쪽 사이 중복 제거는 계약과 같았고 오류·429·5xx는 없었다(280회 조회, 호출당 약 1초).
- **조회 결과 집합이 실행마다 달라질 수 있다(2026-11-14)**: 수집 때는 14개 브랜드 모두 20쪽 상한까지 갔는데 같은 날 재조회에서는 일부 브랜드가 1~12쪽에서 `has_more`가 거짓으로 끝났다. 재조회에서 광고가 안 보인다고 해서 없는 광고로 단정하지 않는다(쪽 상한에서 끊긴 조회는 `TIKTOK_PAGES_INCOMPLETE`, 첫 못 찾음은 재시도 대상). 재조회에서는 500이 간헐적으로 잦았다(브랜드 14곳 중 4곳)가 5xx를 2·5·15초 백오프로 재시도한다.
- **영상 주소 관찰(2026-11-14)**: 호스트 `tiktokcdn.com`, 쿼리 인자 이름 `a, bt, btag, bti, ft, l, mime_type, rc, vvpl`(만료를 뜻하는 이름 없음). 받은 직후·3분·8분 뒤 모두 `Range` 요청에 `206 video/mp4`였다(약 23.0MB, 4.4MB). 만료 시간은 여전히 미확인이며 최소 8분 유효만 확인했다. 분석 직전에 재조회해 받는 설계를 유지한다.

## 식약처 공공 API (공공데이터포털)

공통: `https://apis.data.go.kr/1471000/{서비스}/{오퍼레이션}?serviceKey=...&type=json&pageNo=&numOfRows=`. 인증키는 `.env`의 `DATA_GO_KR_SERVICE_KEY`(디코딩 키). 성공 응답은 `{"header": {"resultCode": "00", ...}, "body": {"pageNo", "totalCount", "numOfRows", "items": [...]}}`.

| 확인한 것 | 실제 형태 | 원본 |
|---|---|---|
| 원료성분정보 오퍼레이션 | `CsmtcsIngdCpntInfoService01/getCsmtcsIngdCpntInfoService01`, 검색 파라미터 `INGR_KOR_NAME` | `mfds_ingredient_query.json` |
| 원료성분 응답 항목 | `INGR_KOR_NAME`, `INGR_ENG_NAME`, `CAS_NO`, `INGR_SYNONYM`, `ORIGIN_MAJOR_KOR_NAME`. `INGR_SYNONYM`은 표본에서 전부 `null` | 위와 같음 |
| **영문명 검색 파라미터는 없다** | `INGR_ENG_NAME`을 넣어도 무시되고 전체 목록(`totalCount` 21968)이 목록 앞쪽 그대로 돌아온다. 영문명 4종(영문 2종·`Water`·공백 없는 한 단어)으로 읽기 전용 호출 4건을 보냈고 모두 같은 첫 20행이었다(2026-11-15). 그래서 영문 일치는 전체 목록을 한 번 내려받아(`pipeline/ingredient_catalog.py`, 100건씩 쪽 단위 재개) DB에서 한다. 응답 항목에 성분 코드는 없고 `INGR_ENG_NAME`은 null일 수 있다 | (측정 기록만, 원본 픽스처 없음) |
| **검색은 부분 일치** | "병풀추출물"이 "하이드롤라이즈드병풀추출물" 등 7건을 돌려준다. "시카"는 "시카카이열매추출물" 같은 무관한 성분 20건을 돌려준다 | 위와 같음 |
| **통용명은 표준명이 아니다** | "히알루론산" 0건(표준명은 "하이알루로닉애씨드" 계열), "센텔라" 0건. 광고·상세페이지의 표기를 그대로 넣으면 못 찾는다 | 콘솔 출력 |
| 결과 없음 | 200, `totalCount` 0 | `mfds_ingredient_query_no_match.json` |
| 기능성화장품 보고품목 오퍼레이션 | `FtnltCosmRptPrdlstInfoService01/getRptPrdlstInq01`, 검색 파라미터 `item_name`. 포털 설명의 오퍼레이션 이름 후보 4개는 400 `NO_OPENAPI_SERVICE_ERROR`였고, 실제 이름은 포털 페이지 원문의 `operationId`에서 찾았다 | `mfds_functional_report_query.json` |
| 보고품목 응답 항목 | `ITEM_NAME`, `ENTP_NAME`, `REPORT_DATE`, `EFFECT_YN1`~`3`, `SPF`, `PA`, `WATER_PROOFING_NAME`, `CANCEL_APPROVAL_YN` 등 36개 | 위와 같음 |
| 품목명 검색 | 부분 일치. 품목명에 브랜드명이 들어 있어 "메디큐브" 234건, "코스알엑스" 91건, "스킨1004" 75건, "아누아" 97건, "조선미녀" 51건 | 콘솔 출력 |
| **업체명 파라미터는 걸리지 않는다** | `entp_name`을 넣어도 전체 197,889건이 그대로 나온다. 이 오퍼레이션에서는 업체명으로 거를 수 없다 | 콘솔 출력 |

주의:
- **성분 별칭 사전은 직접 만들어야 한다.** 공공 API에 통용명→표준명 연결이 없다(`INGR_SYNONYM` 비어 있음). 상세페이지의 전성분 표기는 대부분 표준명이라 그대로 묶일 것으로 보이지만(미확인), 광고의 "시카", "히알루론산" 같은 표기는 별칭 표로 연결한다.
- 부분 일치라 정확히 같은 표준명만 고르는 처리가 필요하다.
- **기능성 종류는 `EE_NAME`(효능효과명)으로 판정한다.** 포털 명세상 `EFFECT_YN1`~`3`은 "2호효능효과_미백/주름개선/자외선"으로 다른 구분이고, 상세페이지에 "주름개선 / 미백 기능성"이라 적힌 코스알엑스 세럼은 세 값이 모두 `N`이었지만 `EE_NAME`이 "피부의 미백에 도움을 준다. 피부의 주름개선에 도움을 준다."였다. 브랜드 3곳 표본에서 `EE_NAME`은 미백, 주름 개선, 둘 다, `null` 중 하나였다. 자외선 차단 제품은 `SPF`·`PA`로 판정하되 **값이 있을 때만** 인증으로 인정한다(아래 선케어 실측).
- 이 API는 보고품목만 다룬다. 심사품목은 별도 API이고(아래 "심사품목 API" 절) 같은 제품이 두 쪽에 모두 있는지, 한쪽에만 있는지는 **미확인**이다. 코스알엑스 색소침착케어세럼은 심사품목에 있었다.
- **선케어 `SPF`·`PA`(2026-11-12 실측, 보고품목)**: 값은 **문자열**이다(`SPF` 예: `"30"`, `"33"`, `"50+"`, `"83"`, `PA` 예: `"0"`, `"2"`, `"3"`, `"4"`. `"4"`가 PA++++인지는 미확인). **대부분 비어 있다(null)**: "선크림" 검색 첫 30건과 "선스크린" 30건은 전부 null, "선스틱" 30건 중 11건만 값이 있다. 제품명에 "에스피에프33"이 있어도 필드가 null인 품목이 있다. `EE_NAME`·`EE_CODE`·`EE_DOC_DATA`·`EFFECT_YN1~3`으로 보완되지 않는다. **null은 "인증 없음"이 아니라 "판정 불가(`unknown`)"로 둔다.** 취하(`CANCEL_APPROVAL_YN`)는 이번 표본에서 모두 `"N"`(`instagram_mfds_youtube_probe.json`).
- **보고품목과 심사품목은 겹치지 않는 모집단으로 보인다**: "선크림" 보고품목 4,837건, 심사품목 1,222건이고 첫 쪽(30건)끼리 품목명이 겹친 것이 0건이었다. 제품마다 두 API를 모두 조회한다(겹침의 전체 규모는 미확인).
- **품목명은 띄어쓰기가 없다.** "코스알엑스더6펩타이드스킨부스터세럼"처럼 붙어 있어, "펩타이드 스킨 부스터"(띄어 씀)는 0건, "펩타이드스킨부스터"는 11건이었다. 검색어의 공백을 지우고 보낸다.
- 취하된 품목(`CANCEL_APPROVAL_YN`)을 걸러야 한다.
- 일일 한도는 **미확인**이다.

기능성화장품 **심사**품목 API (2026-11-12 실측)

| 확인한 것 | 실제 형태 | 원본 |
|---|---|---|
| 오퍼레이션 | 데이터셋 15056939. **기관 코드가 다르다**: `https://apis.data.go.kr/1471057/FtnltCosmSrngPrdlstInfoService05/getSrngPrdlstInq05`(보고품목은 `1471000`). 업체 오퍼레이션 `getSrngEntpInq05`도 있다. 포털 명세상 파라미터는 `serviceKey, pageNo, numOfRows, type, item_seq, item_name`이고 효능은 `EE_DOC_DATA`(보고품목의 `EE_NAME`과 **필드 이름이 다르다**) | 포털 명세 |
| **활용신청 안 된 키** | 현재 키로 **403**, `{"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR", "returnAuthMsg": "등록되지 않은 서비스키", "returnReasonCode": "30"}}}`. 잘못된 키도 같은 응답이다. 이 API는 활용신청이 따로 필요하다. 이 오류 본문은 성공 응답(`header`/`body`)과 **형태가 완전히 다르다** | `mfds_error_key_not_registered.json` |

활용신청 승인 뒤 성공 응답 (2026-11-12, 같은 `DATA_GO_KR_SERVICE_KEY`로 200, `NORMAL SERVICE.`)

| 확인한 것 | 실제 형태 | 원본 |
|---|---|---|
| 응답 구조 | 보고품목과 같은 `{"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."}, "body": {"pageNo", "totalCount", "numOfRows", "items": [...]}}`. **`items`는 배열**(`{"item": ...}` 래퍼가 아님) | `mfds_screening_query.json`(검색어 "코스알엑스", 2건) |
| **결과 없음** | 200이고 `body`에 `pageNo`·`totalCount`(0)·`numOfRows`만 있고 **`items` 키 자체가 없다**(빈 배열이 아님) | `mfds_screening_query_no_match.json` |
| 항목 키 | 표본 2건 모두 50개 키. **`SPF`·`PA`·`CANCEL_APPROVAL_YN`이 없다**(보고품목에는 있다). `PERMIT_KIND_NAME`은 "심사" | `mfds_screening_query.json` |
| **`EE_DOC_DATA`는 XML 문자열** | `<DOC title="효능효과" type="EE">…<PARAGRAPH …><![CDATA[피부의 미백에 도움을 준다.]]></PARAGRAPH>…</DOC>`. 텍스트는 XML을 파싱해 `PARAGRAPH`에서 꺼낸다(보고품목의 `EE_NAME`은 평문). 줄바꿈은 `\r\n` | 위와 같음 |
| 부분 일치 | "코스알엑스" 2건(`코스알엑스색소침착케어세럼`, `코스알엑스알로에수딩선크림01`) | 위와 같음 |

- **`ENTP_NAME`은 브랜드와 다를 수 있다.** 표본의 `코스알엑스색소침착케어세럼`은 업체명이 "(주)아모레퍼시픽", `코스알엑스알로에수딩선크림01`은 "(주)코리아나화장품"이다. 브랜드를 업체명으로 판정하지 않고 품목명·공식몰 제품과 대조한다.
- **자외선 차단(`SPF`·`PA`)은 이 API에서 얻을 수 없다.** 심사품목은 효능(미백·주름)에 쓰고 자외선 차단은 보고품목 API의 `SPF`·`PA`로 판정한다. 품목명에 SPF가 들어 있는 경우가 있으나 코드로 파싱해 판정하지 않는다. 취하 여부 필드가 없다는 점도 한계다.
- `EE_DOC_DATA`가 `null`인 품목이 있다는 보고(조언 세션 관측: "선크림" 검색 결과 중 한 건)가 있으나 **저장한 원본에는 없다**. `null`일 수 있다고 보고 읽는다.
- **200 응답 헤더의 `resultCode`(2026-11-15 처리 규칙)**: `00`이 성공이다. 실측: 광고 소재 성분 대조 중 `resultCode` **`01`**, `resultMsg` `System Error!!`(HTTP 200)가 나왔다. 처리: **`03`(데이터 없음)은 완료된 빈 결과**(재시도·오류 아님), 계정 수준 코드 **`20`·`22`·`30`·`31`·`32`는 즉시 중단**(`MFDS_API_ERROR`), 그 밖의 비`00` 코드(`01` 등)는 그 조회 하나의 일시 오류로 보고 **1·2·4초 백오프로 3번 재시도**한 뒤 `MFDS_LOOKUP_FAILED`(영구 실패가 아니라 재시도 가능한 대기, 배치는 계속)로 둔다. 조회가 연속 20번 `MFDS_LOOKUP_FAILED`이면 `MFDS_CONSECUTIVE_FAILURES`로 중단한다(성공 한 번이면 횟수가 0이 된다). 재시도도 호출 수 상한에 센다. 계정 수준 코드의 의미는 조언 세션 기억에 따른 것이며 `01` 외의 코드는 아직 실측하지 않았다
- 호출 한도는 여전히 **미확인**이다. 어댑터는 HTTP 상태를 먼저 보고, 오류 본문의 형태가 성공 응답과 다름을 받아야 한다(FP-C01).

식약처 안내서 PDF 내려받기 (2026-11-15, `claim-rules`의 원문)

| 확인한 것 | 내용 |
|---|---|
| 출처 | 식약처 공식 사이트 게시글 `https://www.mfds.go.kr/brd/m_1060/view.do?seq=15700`(등록번호 안내서-0086-07, 2025-08-14). 첨부 `https://www.mfds.go.kr/brd/m_1060/down.do?brd_id=data0011&seq=15700&data_tp=A&file_seq=2` |
| 응답 | HTTP 200, `Content-Type: application/octet-stream`, `Content-Disposition`에 파일명 `「화장품 표시·광고 관리 지침(민원인안내서)」.pdf`, 360,654바이트, PDF 1.4, **17쪽** |
| SHA-256 | `a3efa6c204c73cb1bfd08bb7be5598c7344c9494c3180256577e315bbfdeb8bf` |
| 저장 | `data/raw/claim_guide/`(gitignore). 원문은 저장소에 복사하지 않는다 |
| 추출 | 이 환경에는 `pdftotext`가 없어 macOS PDFKit(Swift)로 쪽별 텍스트를 뽑았다. **별표 표는 열이 섞여 나오므로 쪽 이미지로 열(구분·금지표현·비고)을 확인해야 한다** |

## 브랜드 공식몰 상세페이지 (2026-11-12 실측: 코스알엑스 1개, 아누아 1개 상품)

| 확인한 것 | 실제 형태 |
|---|---|
| 가격 | HTML 메타 태그에 있다. `product:price:amount`(정가), `product:sale_price:amount`(판매가), `product:price:currency`(KRW). 두 몰 모두 같은 형식(카페24) |
| 전성분: 아누아 | 상세 탭의 상품정보제공고시 표에 **텍스트로** 있다("화장품법에 따라 기재해야 하는 모든 성분", "용량 또는 중량", "제품 주요 사양", "식품의약품안전처 심사필 여부"). 주석 안이 아니라 실제 표시되는 영역 |
| 전성분: 코스알엑스 | HTML에 텍스트가 없고 **상세 이미지 안에만** 있다. 상세 이미지는 `id="prdDetail"` 안의 `img`의 `ec-data-src`(지연 로딩)이고 외부 이미지 서버에 있다 |
| 상세 이미지 규모 | 코스알엑스 1개 상품: 이미지 9장, 가로 1,000px, 세로 합계 50,881px, 내려받은 용량 약 50MB(움직이는 GIF가 최대 16MB) |
| Gemini 추출 | 가로 1,000px로 맞추고 세로 2,000px 조각(400px 겹침) 36장으로 나눠 10장씩 4번 호출. 호출당 15~23초, 입력 약 6,700~11,000토큰. 전성분 44개를 인쇄 순서대로 추출했고, 마지막 묶음에서만 나왔다 |
| 표준명 대조 | 추출한 전성분 44개가 **전부** 식약처 원료성분정보의 표준명과 정확히 일치했다(괄호 안 함량 표기를 떼고 비교) |
| 효능·피부 타입 | 효능 문구, 핵심 성분, 피부 타입, 제형, 기능성 표기("주름개선 / 미백 기능성 제품")를 원문 그대로 뽑았다. 묶음마다 다른 문구가 나오므로 합쳐서 중복을 지운다 |

나머지 공식몰 확인 (2026-11-12, 첫 화면에 노출된 상품 1개씩)

| 몰 | 메타 태그 가격 | 전성분 텍스트 | 상세 이미지 수 | 판정 |
|---|---|---|---|---|
| 아누아 | 있음 | 있음 | - | 사용 |
| 코스알엑스 | 있음 | 없음(이미지) | 9 | 사용 |
| 메디힐 | 있음 | 있음 | 14 | 사용 |
| 바이오던스 | 있음 | 있음 | 27 | 사용 |
| 이즈앤트리 | 있음 | 있음 | 39 | 사용 |
| 스킨1004 | 있음 | 없음(이미지) | 11 | 사용 |
| 메디큐브 | 있음 | 없음(이미지) | 123 | 사용(이미지가 많아 비용이 큼) |
| 아비브 | 있음 | 없음(이미지) | 7 | 사용 |
| 라운드랩 | 있음 | 없음(이미지) | 17 | 사용 |
| 믹순 | 있음(카페24, `mixsoon.co.kr`) | 없음(이미지) | 17 | 사용. 아래 "믹순·달바·조선미녀" 참고 |
| 달바 | **없음**(고도몰, `dalba.co.kr`) | 없음(이미지) | 23 | 사용(형식 별도). 아래 참고 |
| 넘버즈인 | - | - | - | 제외(접근 시 401) |
| 조선미녀 | 있음(카페24, `beautyofjoseon.co.kr`) | 없음(이미지) | 10 | 사용. 아래 참고 |
| 토리든 | - | - | - | 제외(robots.txt가 AI 크롤러 차단) |

믹순·달바·조선미녀 (2026-11-12, 첫 화면·상품 1개씩)
- **믹순**: robots.txt가 `*`에 상품 경로를 막지 않고 AI 크롤러 언급이 없다. 메타 태그 `product:price:amount` 38000 / `sale_price` 26600(두유 세럼 50ml). **단종 상품 주소(`product_no=552`)는 HTTP 200에 "페이지가 사라졌거나" 안내 HTML(3.4KB)로 온다 → HTTP 200만으로 성공을 판정하지 않고 가격 메타 유무로 판정한다.**
- **달바**: 고도몰이다. robots.txt는 이름을 지정한 봇에만 규칙이 있고 `*` 그룹이 없다(ClaudeBot 등 미지정 봇은 제한 없음). 지정 봇에 `Crawl-delay: 10`이 있어 우리도 10초 간격을 둔다. **메타 태그가 없다.** JSON-LD `offers.price`가 `"34000.00"`(문자열), hidden input `set_goods_price` 34000, `set_goods_fixedPrice`는 `0.00`(정가 없음). "비교에는 정가"(ARCHITECTURE) 규칙과 충돌하므로 정가가 0이면 판매가를 쓰고 `price_basis` 속성에 어느 쪽인지 남긴다. 응답이 gzip이라 클라이언트가 압축을 풀어야 한다. 성분 탭 텍스트는 비어 있다.
- **조선미녀**: 메타 태그 가격(맑은쌀선크림 18000/18000). 몰 첫 화면이 sources.yaml에 확인된 `instagram.com/beautyofjoseon_official`로 연결돼 국내 공식몰로 판단한다. `beautyofjoseon.com`은 미국 스토어다.
- 세 곳 모두 이용약관에 기존 9곳과 같은 조항(지적재산권 귀속 정보를 사전 승낙 없이 영리 목적으로 이용 금지)만 있고 크롤링 금지 조항은 없다. 결과: 사용 가능 12곳, 제외 2곳(토리든·넘버즈인).

- 판정 키워드("화장품법에 따라 기재", "모든 성분", "전성분")가 HTML에 있는지로 텍스트 여부를 봤다. 상품마다 다를 수 있다.
- 이용약관은 확인한 9개 몰 모두 "사이트에 지적재산권이 있는 정보를 영리 목적으로 복제·배포 금지" 조항만 있었다. 스킨1004의 "무단 복제" 문구는 디자인 스크립트에 대한 것이었다.
- 한글이 든 상품 주소는 퍼센트 인코딩해야 요청이 성공한다(처음 시도에서 한글 주소 요청이 전부 실패했다).

주의:
- **가격은 이미지에서 뽑지 않는다.** 이미지에서 "16,000원"이 추출됐지만 메타 태그의 정가는 46,000원, 판매가는 31,000원이었다(행사 문구로 보임). 가격은 메타 태그로만 읽는다.
- **세트 상품을 피한다.** 시험한 상품이 "1+1" 세트라 단위당 가격 계산이 틀어진다. 대표 제품은 단품 페이지로 고른다.
- 상세 이미지 수집량이 크다(상품당 수십 MB). 전성분은 보통 끝부분에 있으므로 뒤쪽 이미지부터 읽고, 전성분을 찾으면 멈춘다. 이미지는 저장하지 않는다.
- 몰마다 형식이 다르다(텍스트 표 / 이미지). 텍스트 표가 있으면 그것을 먼저 쓰고 없을 때만 이미지를 읽는다.
- 아누아의 클렌징 폼 페이지가 "기능성 화장품 심사(또는 보고)를 필함"이라고 적혀 있었다. 클렌징 폼에 맞지 않아 보이는 문구라, 페이지의 고시 문구를 그대로 믿지 말고 식약처 보고품목정보로 대조한다.
- 이용약관(두 몰): 사이트에 지적재산권이 있는 정보를 사전 승낙 없이 **영리 목적으로** 복제·배포하는 것을 금지한다. 크롤링 자체를 금지하는 조항은 찾지 못했다. 비영리로 사실 정보(전성분·가격·효능 표기)만 추출하고 이미지는 저장·재배포하지 않는다.

공식몰 재실측 (2026-11-15, 페이지 5개 + dalba 첫 화면, robots.txt 5개, 호스트마다 최소 6초 간격·dalba 11초, User-Agent `beautyads-research/0.1`, 원본은 `data/raw/mall/`(gitignore), 테스트용 최소본은 `tests/fixtures/contracts/mall_*`)

| 확인한 것 | 실제 형태 | 원본(최소본) |
|---|---|---|
| **전성분 텍스트는 구조가 몰마다 다르고, "키워드가 있다"와 "값이 있다"가 다르다** | 아누아: `<table>`이 아니라 `div.info-row`의 `div.info-label`("화장품법에 따라 기재해야 하는 모든 성분")과 `div.info-content.ingredients`에 **값이 있다**. 이즈앤트리: `<table class="contents__table">`의 "모든 성분" 행이 있지만 **`<td>`가 비어 있다**. 코스알엑스: 텍스트 없음(이미지). 달바: 성분 탭이 비어 있음. **키워드 유무로 텍스트 여부를 판정하면 틀린다(이즈앤트리). 값 칸이 비어 있지 않은지로 판정한다** | `mall_cafe24_text_div.html`, `mall_cafe24_table_empty.html`, `mall_cafe24_image_only.html`, `mall_godomall_product.html` |
| 가격 메타(카페24) | `product:price:amount`, `product:sale_price:amount`, `product:price:currency`는 세 몰 모두 있다. 정가와 판매가가 같은 상품이 있다 | 위 |
| 고도몰(달바) | 메타 태그 없음. JSON-LD `offers.price` `"29900.00"`(문자열), hidden input `set_goods_price`가 `29900`, `set_goods_fixedPrice`가 `0.00`(정가 없음, 2026-11-12 관측과 같다) | `mall_godomall_product.html` |
| **단종 상품이 HTTP 404로 왔다** | 믹순 `product_no=552`가 2026-11-12에는 HTTP 200 안내 HTML이었는데 2026-11-15에는 **HTTP 404**(본문 3.3KB 안내 HTML)였다. 단종 표현이 200과 404 두 형태일 수 있으므로 HTTP 상태를 먼저 보고, 200이면 가격 메타 유무로 판정한다 | `mall_discontinued_404.html` |
| robots.txt | 아누아 `User-agent: *` `Allow: /`. 코스알엑스·이즈앤트리·믹순은 `*`에 관리·주문·검색 경로만 막고 상품 경로는 막지 않는다. 달바는 `*` 그룹이 없고 이름 지정 봇 목록에만 규칙·`Crawl-delay: 10`이 있으며 응답은 CRLF 줄바꿈이다 | `mall_robots_mixsoon.txt`, `mall_robots_dalba.txt` |
| **이미지 전용 호스트의 robots.txt** | 코스알엑스 상세 이미지는 `cosrxinc.jpg3.kr`에 있고 그 호스트의 `/robots.txt`는 **404**(HTML 오류 페이지)다. robots.txt가 없는 호스트는 제한이 없는 것으로 읽고(RFC 9309, 404·410), 오류 페이지 본문을 규칙으로 읽지 않는다. 401·403·5xx·연결 실패·너무 큰 파일은 읽을 수 없음으로 거부한다. 요청 간격은 그대로 지킨다. 어댑터가 404를 읽을 수 없음으로 거부해 코스알엑스·바이오던스 제품 2개의 이미지 4장씩이 모두 `MALL_ROBOTS_UNREADABLE`이었다(2026-11-15) | `tests/test_mall.py` |
| **robots.txt 리다이렉트** | 달바 이미지 호스트(`cdn-saas-web-116-52.cdn-nhncommerce.com`)는 `/robots.txt`에 **302**로 `https://godomall.cdn-nhncommerce.com/error.html`(HTML 오류 페이지)을 돌려준다. robots.txt 요청에 한해 리다이렉트를 최대 5번 직접 따라가고(각 요청이 호스트별 간격을 지킨다), 최종 응답이 `text/html`이거나 404·410이면 유효한 robots.txt 없음(허용)으로, `Location`이 없거나 http(s)가 아니거나 6번째 리다이렉트이면 읽을 수 없음으로 거부한다. 상품·이미지 요청은 리다이렉트를 따라가지 않는다(`MALL_HTTP_302`) | `tests/test_mall.py` |
| **abib은 전성분이 HTML 텍스트(영문 INCI 이름)다** | 아코디언 항목 `<li>전성분<span class="ico"></span><ul class="acco-inner"><li class="ingr2">Water (Aqua), Methylpropanediol, …`. 값이 비어 있으면 텍스트가 아니다. 이전 어댑터는 이 구조를 몰라 이미지 경로로 가서 이미지 7장을 읽고도 성분 0개로 끝났다(2026-11-15). **텍스트가 영문 INCI 이름이라 식약처 원료성분정보의 한글 표준명(`INGR_KOR_NAME`) 정확 일치로는 연결되지 않고 대부분 미해결이 된다**(영문명 대조는 원료성분 전체 목록 DB로 한다. 위의 영문명 검색 파라미터 없음 행 참조) | `mall_cafe24_accordion_ingredients.html` |
| **메디큐브는 전성분이 팝업 레이어 텍스트다(한글 표준명)** | 상세 정보 목록의 `전성분 보기` 링크가 여는 `<div class="dePop_layer" id="cpopBody1"><div class="dePop"><div class="pp_header">전성분 보기…</div><div class="depContent">정제수, 부틸렌글라이콜, …</div></div></div>`. 같은 구조의 `cpopBody2`는 주의사항이다. 이전 어댑터는 이 구조를 몰라 이미지 6~53장을 읽고도 성분 0개로 끝났다(2026-11-15 제품 1건 실측) | `mall_cafe24_popup_ingredients.html` |
| **바이오던스는 전성분이 상품정보고시 문단의 인라인 텍스트다(한글 표준명)** | 라벨·값 요소가 아니라 `<span>` 안의 텍스트 줄 `[전성분] 정제수, 갈락토미세스발효여과물, …`로 있고, 같은 문단에 `사용방법`·사용기한이 이어진다. 이전 어댑터는 읽지 못해 이미지 13~26장을 읽고도 성분을 못 찾아 보류했고 "이미지에 전성분이 없다"고 단정했다(2026-11-15 제품 1건 실측, FP-C09). 변형: 라벨 `[전성분]&nbsp;`이 한 텍스트 조각에서 끝나고 목록이 **다음 텍스트 조각**에 있는 경우(문단·중첩 `<span>`·라벨 뒤 인라인 `<style>` 블록)가 3건 더 있었다(2026-11-15 실측 3건, 이 중 20·22·23번은 같은 이유로 보류였음). 목록은 쉼표 2개 이상이어야 하고 `<style>`·`<script>` 텍스트는 값이 아니다. 다음 `[라벨]` 줄 앞에서 끊는다 | `mall_cafe24_inline_ingredients.html`, `..._paragraph.html`, `..._next_run.html`, `..._style.html` |
| **이미지 CDN의 robots.txt가 S3 XML 오류(403)면 규칙 없음으로 본다(좁은 예외)** | 바이오던스 상세 이미지는 CloudFront(`dayjsrwbk0r7f.cloudfront.net`)에 있고 그 `/robots.txt`는 파일이 없어서 403, `content-type: application/xml`, 본문 `<Error><Code>AccessDenied</Code><Message>Access Denied</Message></Error>`(서버 AmazonS3)로 답한다(2026-11-15 실측 2회). 이전 규칙은 모든 401/403을 거부해 바이오던스 5개가 `MALL_ROBOTS_UNREADABLE`로 끝났다. 이유: 파일이 없는 것이지 접근을 막은 것이 아니고(RFC 9309는 4xx를 규칙 없음으로 본다), 같은 브랜드의 본 사이트 robots.txt는 200으로 읽혀 규칙이 확인된다. **세 조건을 모두 만족할 때만** 적용한다: ① 상세 이미지 내려받기 요청이고 호스트가 제품 페이지 호스트와 다르다 ② 같은 브랜드 본 사이트의 robots.txt가 진짜 규칙 파일(200, HTML 오류 페이지 아님)이다 ③ 403에 XML 본문이 `<Error>`와 `<Code>AccessDenied</Code>`를 담는다. 그 밖의 401·403·5xx와 본 사이트 자신의 403은 계속 거부한다. 403 응답 본문은 최대 4096바이트만 읽는다 | `mall_robots_s3_access_denied.xml` |
| **상세 이미지의 위치는 몰마다 다르다**(2026-11-15 원본 6쪽 확인) | 코스알엑스·아누아: `#prdDetail` 안, `ec-data-src`(지연 로딩). 이즈앤트리: `#prdDetail`이 탭 컨테이너이고 이미지는 그 뒤 `#prdInfo` 앞에 일반 `src`. abib: `#prdDetail`이 **빈 앵커**이고 바로 뒤에 리뷰 앵커(`#prdReview`)가 오며 실제 이미지(`ec-data-src`)는 `#prdRelated` 앞에 있다(앵커 앞에도 무관한 이미지가 있다). round_lab: 탭 컨테이너 뒤 `#prdInfo` 앞에 일반 `src`(`gi.esmplus.com`). 달바(고도몰): `#detail` 구획에 일반 `src` 이미지(`cdn-nhncommerce.com`)가 있고 `#delivery`에서 끝난다(이미지 경로는 `/data/img/product/detail/…`이며 `/data/editor`가 아니다). 읽는 규칙: 상세 앵커(`prdDetail`·`detail`) 이후부터 다음 구획 앵커 전까지의 이미지를 문서 순서로 읽고, 이미지가 없는 구획은 다음 구획 앵커까지 늘린다. 지연 로딩 속성이 자리표시 `src`보다 우선이고 아이콘·버튼·로고·스페이서는 제외한다 | `mall_cafe24_tab_src.html`, `mall_cafe24_empty_anchor.html`, `mall_cafe24_tab_cont.html`, `mall_godomall_detail.html` |
| 달바 제품 주소 | `https://dalba.co.kr/goods/goods_view.php?goodsNo=<숫자>`, 첫 화면의 링크에서 찾았다 | — |
| 후보 파일의 범위 | `config/product_candidates.yaml`에는 abib·anua·cosrx·isntree·mediheal·round_lab·skin1004 7개 브랜드만 있고 믹순·달바 등 나머지 몰 브랜드는 후보가 없다 | — |

## Gemini API

| 확인한 것 | 실제 형태 | 원본 |
|---|---|---|
| 요청 | `POST /v1beta/interactions`, 본문 `{"model", "input": [{"type":"text",...}, {"type":"video","uri":...}]}` | `gemini_interactions_youtube_url_offset.json` |
| YouTube 주소 입력 | `uri`에 YouTube 주소를 그대로 넣으면 된다. `processing: {type: "static", start_offset, end_offset, fps}`가 YouTube 주소에도 동작한다 | 위와 같음 |
| **응답 본문 위치** | 답은 `steps[]` 중 `type == "model_output"`인 항목의 `content[].text`에 있다. `steps[0]`은 보통 `thought`이며 `signature`만 있다. **위치(`steps[-1]`)가 아니라 `type`으로 찾는다** | `gemini_interactions_file_uri.json` |
| **JSON 출력** | 프롬프트로 "JSON만"을 요구해도 본문이 ```` ```json ```` 울타리로 감싸져 온다 | 위와 같음 |
| 토큰 | `usage.total_input_tokens`, `usage.input_tokens_by_modality[]`(영상·글자 따로), `total_thought_tokens`가 별도 | 위와 같음 |
| 실제 응답한 모델 | 응답 최상위 `model` | 위와 같음 |
| 파일 업로드 | 2단계(시작 → 바이트 전송). 완료 응답은 `file.state == "PROCESSING"`으로 온다 | `gemini_files_upload_finalize.json` |
| 처리 대기 | `GET /v1beta/{file.name}`을 반복해 `state == "ACTIVE"`를 기다린다. `videoMetadata`는 ACTIVE가 된 뒤에만 있다. `sizeBytes`는 **문자열** | `gemini_files_get_active.json` |
| 파일 삭제 | 200과 빈 객체 `{}` | `gemini_files_delete.json` |
| **과부하** | 503, `{"error": {"message", "code": "service_unavailable"}}`. **`code`가 문자열** | `gemini_error_overloaded.json` |
| **잘못된 키** | 400인데 본문이 **객체가 아니라 배열**이고 `error.code`는 **정수** | `gemini_error_bad_key.json` |
| **무료 등급 일일 한도** | `gemini-3.6-flash`는 무료 등급에서 하루 20회. 429, `{"error": {"message": "Rate limit exceeded ... (limit: 20 requests per day on Free Tier)...", "code": "too_many_requests"}}`(`code`는 문자열), 헤더 `retry-after: 15555`(초). 503과 429가 번갈아 났고 503 요청도 한도에 셈된 것으로 보인다(집계 방식 미확인). 이 프로젝트는 유료 등급(2026-11-12 전환) | `gemini_error_free_tier_daily_limit.json` |
| 구조화 출력 | `response_format: {"type":"text","mime_type":"application/json","schema":{...enum...}}`와 헤더 `Api-Revision: 2026-05-20`. 울타리 없는 JSON이 오고 값은 enum 안(`person_first`). 구 방식(`response_mime_type`+`response_format`, 헤더 없음)도 동작. 응답 속 위치는 여전히 `steps[]`의 `type == "model_output"` | `gemini_interactions_36flash_response_format_schema.json`(3.6-flash), `gemini_interactions_response_format_schema.json`(3.5-flash-lite) |
| 3.6-flash 구간 지정 | `processing: {type: static, start_offset: "0s", end_offset: "6s", fps: 2}`가 동작, 영상 토큰 943. 호출당 약 6~7초 | `gemini_interactions_36flash_youtube_offset.json` |
| thought 토큰 | 3.6-flash는 출력 15토큰에 `total_thought_tokens` 345~360이 따로 온다(호출당 260~490). thought 토큰은 `response_cost`에 **포함**된다(입력 956×$0.75/M + (출력 18+thought 355)×$3.75/M = LiteLLM `response_cost`) | 위 두 원본의 `usage` |
| LiteLLM SDK 경유 | `litellm.interactions.create/acreate(model="gemini/<모델>", input=[...])`가 `POST /v1beta/interactions`로 가고 `Api-Revision: 2026-05-20`을 항상 붙인다. `input`을 그대로 전달해 `processing`이 동작한다. 응답 `model_dump()` 최상위에 `agent`·`outputs` 키가 **추가**된다. 응답 `model`은 실제 모델 이름. 비용은 `resp._hidden_params["response_cost"]`. 503은 `litellm.ServiceUnavailableError`. `litellm==1.103.3` 고정. proxy 경유는 실측하지 않았다 | 원본 없음(SDK 객체, 조언 세션 실측) |

주의:
- **오류 본문의 형태가 두 가지다.** 과부하는 객체에 문자열 코드, 잘못된 키는 배열에 정수 코드다. 오류를 해석하는 코드는 HTTP 상태를 먼저 보고, 본문은 두 형태를 모두 받아야 한다.
- 과부하(503)는 실측 중 여러 번 났고, 한 번은 144초가 걸렸으며 한 번은 150초 넘게 응답이 없었다. 호출에는 시간 제한을 두고, 503·429·시간 초과만 대기 후 다시 시도한다.
- 프롬프트가 느슨하면 답의 뜻이 달라진다. "첫 구간에 무슨 일이 일어나는가"를 물었는데 `"00:03"`처럼 시각만 돌려준 사례가 있다. 형식은 프롬프트가 아니라 구조화 출력(위 표)으로 강제한다. 단 enum으로 값 목록은 지켜지지만 어느 값을 고르는지는 호출마다 달라질 수 있다(FP-C03).
- 같은 영상의 분류가 호출마다 달라진 사례가 있다(`question`과 `problem`). 모델도 달랐다.
- 업로드한 파일은 약 48시간 뒤 만료된다(`expirationTime`). 분석 직후 삭제를 요청한다.
- **일일 한도 429는 재시도하지 않는다.** `retry-after`가 수 시간이면 고정 간격 재시도는 한도만 깎는다. 래퍼는 429를 본문·`retry-after`로 일일 한도와 분당 한도로 가르고, 일일 한도면 배치를 멈춰 남은 소재를 대기 상태로 둔다(실측 중 실제로 그렇게 당일 한도를 소진했다).
- 유료 단가는 2027-01-01부터 두 배가 된다(가격 페이지, 2026-11-12 확인). 소재 분석은 12월 안에 끝낸다. thought가 호출당 260~490토큰이라 분석 1건 비용이 견적(출력 600)보다 커질 수 있다. thinking 수준은 `generation_config.thinking_level`로 낮출 수 있다(아래 "Gemini 분석 비용·Files 실측 2차").
- LiteLLM SDK가 Gemini **Files API 업로드**(Instagram·TikTok 영상 경로)를 지원하는지는 **미확인**이다.

## Gemini 분석 비용·Files 실측 2차 (2026-11-12)

| 확인한 것 | 결과 | 원본 |
|---|---|---|
| **영상 입력 토큰은 길이에 비례, 약 91토큰/초** | TikTok 광고 23.6초 → 2,173토큰, 42.0초 → 3,822토큰, YouTube 14분 33초(873초) 영상 전체 → 79,435토큰, 같은 영상 0~60초 구간(fps 1) → 5,461토큰. 오디오는 별도 항목 없이 영상 토큰에 포함돼 보인다. 기본 샘플링과 `fps: 1`이 같은 밀도, `fps: 2`는 약 1.7배(10초에 910 대 1,570) | `gemini_video_tokens_per_second_probe.json` |
| 구간 지정 | `processing: {type: static, start_offset, end_offset, fps}`가 **Files로 올린 파일에서도** 동작한다(10초 구간 910토큰) | `gemini_video_tokens_per_second_probe.json` |
| **thinking 설정** | `generation_config: {"thinking_level": ...}`. 같은 3초 영상(각 1회) thought 토큰: 기본 186, `minimal` 0, `low` 26, `medium` 187, `high` 164. LiteLLM `generation_config`로도 전달된다. **`thinking_budget`은 400** `invalid_request`("Unknown parameter 'thinking_budget'"). 기본값은 `medium`과 비슷하다 | `gemini_files_failures_thinking_burst_probe.json` |
| 큰 파일 한 건의 전 과정(8.19MB TikTok 광고) | 다운로드 9.9초, `create_file` 3.9초, `processed`까지 4.9초, 분석 16.6초(입력 5,560토큰), 전체 약 25초 | `gemini_files_failures_thinking_burst_probe.json` |
| **삭제됐거나 없는 파일로 분석** | **403** `{"error": {"message": "You do not have permission to access the File <id> or it may not exist.", "code": "permission_denied"}}`(404가 아니다) | 위와 같음 |
| **영상이 아닌 바이트 업로드** | 업로드는 성공하고 `file_retrieve`의 `status`가 **`error`**가 된다. 이 파일로 분석하면 **400** `invalid_request`("The File <id> is not in an ACTIVE state and usage is not allowed.") | 위와 같음 |
| **빈 파일 업로드** | 깨끗한 오류가 아니라 LiteLLM이 `ValueError("Error parsing file upload response: 'sizeBytes'")`를 올린다 | 위와 같음 |
| 병렬 호출 | 텍스트 호출 60개를 동시 30개로 보냈을 때 전부 200(총 8.5초). 유료 등급의 실제 분당 한도 수치는 알 수 없다(응답에 한도 헤더 없음) | 위와 같음 |

- 분석 비용 영향(추정, 실측 값 아님): 소재 1건은 콘텐츠 유형·훅·전체 호출의 입력(길이 × 91토큰/초, 구간 상한 적용)과 출력·thought로 이루어진다. 45초 광고 두 호출을 가정하면 `minimal` 약 $0.0062, 기본 약 $0.0085이고 호출이 세 번이면 더 크다. 1,500건이면 $9.3~$12.8 범위의 추정이다. 시범 직후 `cost-recalc`가 원장으로 다시 계산한다.

## Gemini 이미지 입력 (2026-11-15 실측, `litellm==1.103.3`, 호출 2회 합계 $0.00183)

| 확인한 것 | 실제 형태 | 원본 |
|---|---|---|
| 요청 형태 | `litellm.interactions.create`의 `input`에 `{"type": "image", "data": "<base64>", "mime_type": "image/png"}`(인라인) 항목을 텍스트 항목과 함께 넣는다. 공식 문서(`ai.google.dev` Image understanding·Interactions API)에는 Files API 주소를 쓰는 `{"type": "image", "uri": ..., "mime_type": ...}`도 있다(이번에는 미실측). 첫 시도가 성공했다. `thinking_level` `minimal`, `response_format` 구조화 출력이 이미지 입력과 함께 동작했다 | `gemini_interactions_image_input.json` |
| 응답 | 영상 입력과 같은 구조: `steps`에 `thought`, `model_output`. 답은 `type == "model_output"`의 `content[].text`다(`extract_output_text`가 그대로 동작) | 위와 같음 |
| **이미지 토큰은 크기에 비례하지 않는다** | 합성 PNG 1000×2000 → 입력 1,108토큰(이미지 1,081 + 텍스트 27), 1000×4000 → 1,083토큰(이미지 1,056 + 텍스트 27). **높이가 두 배여도 토큰이 같다 = 큰 이미지는 고정 예산으로 축소된다.** 상세 이미지처럼 긴 이미지는 조각(예: 가로 1,000px·세로 2,000px)으로 나눠야 글자가 읽힐 해상도가 남는다(축소 뒤의 판독성은 미실측) | 위와 같음 |
| 호출당 비용 | 1000×2000 → $0.00092, 1000×4000 → $0.00091(원장 `cost_source: response_cost`, `thinking_level` `minimal`, 출력 약 25토큰). **합성 이미지 2장의 값이며 실제 상세 이미지·긴 출력(전성분 목록)에서는 달라진다** | 원장 `purpose: probe-image-input` |
| **`usage.input_tokens_by_modality`의 순서가 호출마다 다르다** | 첫 응답은 `text`가 앞, 둘째 응답은 `image`가 앞이었다. 모달리티는 위치가 아니라 `modality` 값으로 찾는다(FP-C02) | 위와 같음 |
| 미실측 | 실제 상세 이미지의 글자 판독 정확도, 이미지 크기·바이트 상한, 지원 mime 종류(png만 확인), 인라인 한도, Files 경유 이미지 | — |

## LiteLLM SDK 경유 OpenAI·Anthropic·Gemini Files (2026-11-12 실측, `litellm==1.103.3`)

원본은 HTTP 원문이 아니라 SDK 객체의 `model_dump`와 실행 결과다(`tests/fixtures/contracts/README.md`). 호출 전에 막는 오류와 공급사 오류가 모두 `litellm.exceptions`의 예외로 올라온다.

| 확인한 것 | 실제 형태 | 원본 |
|---|---|---|
| 응답 `model` | SDK에 실제 모델 이름을 주면 응답 `model`도 실제 이름이다(`gpt-6-luna`, `gpt-6.1-terra`, `claude-haiku-5-5`, `claude-sonnet-5-5`). 프로젝트 B의 별칭 문제는 proxy와 별칭 조합에서 생긴 것으로 보인다. `_hidden_params["litellm_model_name"]`은 `openai/gpt-6-luna`처럼 공급사 접두어가 붙는다. **Router나 별칭을 쓰면 다시 확인한다** | `litellm_openai_anthropic_probe.json` |
| 비용(비스트리밍) | `resp._hidden_params["response_cost"]`. 단가표 `litellm.model_cost`는 luna·haiku $0.10/$0.50, terra $1/$5, sonnet $2/$10으로 COST_ESTIMATE와 일치한다 | 위와 같음 |
| **스트리밍 비용** | 스트리밍 응답의 `_hidden_params["response_cost"]`는 `None`이다. `stream_options={"include_usage": True}`를 주고 청크를 `litellm.stream_chunk_builder(chunks, messages=...)`로 합친 응답에 `litellm.completion_cost(completion_response=built)`를 쓰면 값이 나온다. 사용량은 마지막 청크에 온다 | `litellm_reasoning_effort_and_stream_cost.json` |
| **`temperature`** | `litellm.UnsupportedParamsError`(`status_code` 400, `llm_provider` 없음)로 **네트워크 호출 전에** 거부된다. 추론이 켜진 luna는 "doesn't support temperature=0 while reasoning is active. Only temperature=1 is supported unless reasoning_effort resolves to 'none'", haiku는 항상 "Only temperature=1 is supported"(0.5도 거부, 1만 성공). **luna·terra는 `reasoning_effort="none"`일 때만 temperature를 줄 수 있다**: luna `none`에서 0·0.5·1이 모두 성공했고 `low`+0은 거부됐으며, terra `none`+0은 성공했다. 추론이 켜진 terra는 측정하지 않았다. 각 조건 1회 측정 → 기본은 `temperature`를 지정하지 않는다 | `litellm_openai_anthropic_probe.json`(`temp0_*`), `litellm_temperature_with_reasoning_none.json` |
| **luna 추론 기본값** | 추론이 기본으로 켜져 있다. 같은 한 줄 계산에서 `reasoning_effort` 미지정 273토큰(추론 242), `none` 19, `low` 5, `medium` 56, `high` 1,201(추론 1,158). **비용이 약 100배 차이**(미지정 1.4e-04, `none` 1.4e-05, `high` 6.1e-04). `minimal`은 `UnsupportedParamsError`. 한 번씩만 잰 값이라 분포가 아니다. haiku의 `reasoning_tokens`는 0이었고 Anthropic thinking 설정은 **미확인** | `litellm_reasoning_effort_and_stream_cost.json` |
| 도구 호출 | 두 공급사 모두 `message.tool_calls[{id, type: "function", function: {name, arguments}, index}]`, `finish_reason: "tool_calls"`. **`arguments`는 JSON 문자열**이라 파싱 실패를 처리한다. id는 `call_…`(OpenAI)·`toolu_…`(Anthropic). Anthropic에는 `caller: {type: "direct"}`가 붙는다. `tool_choice="required"`가 둘 다 동작 | `litellm_openai_anthropic_probe.json`(`tool_*`) |
| 구조화 출력 | `response_format={"type":"json_schema","json_schema":{"strict":true,...}}`가 luna·haiku 모두 동작하고 울타리 없는 JSON이 온다 | 위와 같음(`schema_*`) |
| 프롬프트 캐시 | 같은 긴 접두(약 5.7k·8.6k 토큰)를 두 번 보냈다. OpenAI는 자동이며 `prompt_tokens_details.cached_tokens` 5,742. Anthropic은 시스템 블록에 `cache_control: {"type":"ephemeral"}`가 필요하고 `cache_read_input_tokens` 8,600. 첫 호출은 LiteLLM 단가표가 **캐시 쓰기 단가(입력의 1.25배)**로 계산한다(haiku 첫 호출 0.0010785, 이후 8.95e-05). OpenAI가 실제로 쓰기 가산을 청구하는지는 단가표의 가정일 뿐 **미확인**. 최소 캐시 길이는 위 두 크기에서만 확인했다 | 위와 같음(`cache_*`) |
| usage 필드 | 공통: `prompt_tokens`, `completion_tokens`, `total_tokens`, `prompt_tokens_details.cached_tokens`, `completion_tokens_details.reasoning_tokens`. Anthropic은 `cache_read_input_tokens`, `cache_creation_input_tokens`, `cache_creation_token_details` 등이 추가된다. 비용 원장은 이름으로 읽고 없으면 0으로 본다 | 위와 같음 |
| 오류 | 잘못된 키 `litellm.AuthenticationError`(401, `llm_provider`가 `openai`/`anthropic`), 없는 모델 `litellm.NotFoundError`(404), 호출 전 거부 `litellm.UnsupportedParamsError`(400). 본문은 예외의 **문자열**(`OpenAIException - ...`, `AnthropicException - {"type":"error",...}`)이다. **OpenAI·Anthropic의 429·503은 유도하지 못해 미확인** | 위와 같음(`err_*`) |
| 한도 값 | `max_completion_tokens=0`을 Anthropic에 주면 오류 없이 출력 0토큰으로 성공한다. 한도 값 검증은 래퍼가 한다 | 위와 같음(`err_tooLongOutputParam`) |
| **Gemini Files (SDK 지원)** | `litellm.create_file(file=(이름, 바이트, "video/mp4"), purpose="user_data", custom_llm_provider="gemini", api_key=...)`, `file_retrieve`, `file_delete`. 반환 `id`가 **전체 주소**(`https://generativelanguage.googleapis.com/v1beta/files/<id>`)라 그대로 `interactions` 입력의 `{"type":"video","uri": id,"mime_type":"video/mp4"}`에 넣으면 분석된다(3.6-flash, 영상 토큰 189). `expires_at`은 `null`. 처리 대기: `status`가 `uploaded` → `processed`(3초 영상에서 2초 간격 조회 2번째). 시험 영상은 ffmpeg가 만든 3초 생성물 | `litellm_gemini_files_flow.json` |
| **삭제와 삭제 뒤 조회** | `file_delete`는 `{"id": "files/<id>", "deleted": true}`(id가 업로드 때와 다른 형태). 삭제 뒤 `file_retrieve`는 깨끗한 NotFound가 아니라 **`ValueError("Error parsing file retrieve response: 'createTime'")`**이고 LiteLLM이 ERROR 로그를 남긴다 → 삭제 확인에 `file_retrieve`를 쓰지 않고 `file_delete`의 `deleted`로 판단한다 | 위와 같음 |

- Gemini Files의 큰 파일 소요와 실패 형태는 "Gemini 분석 비용·Files 실측 2차" 절에 있다(8.19MB 한 건 약 25초, 비영상은 `status: error`, 없는 파일 403, 빈 파일 `ValueError`).
- 이 실측으로 `llm`에서 `httpx`를 직접 쓸 필요가 없어졌다(Files도 SDK로 된다). `AGENTS.md`의 SDK 허용 표에서 `llm`의 `httpx`를 뺐다.

## LangGraph (2026-11-12 실측, 외부 API 호출 없음)

버전: `langgraph 1.2.20`, `langgraph-checkpoint 4.3.1`, `langgraph-checkpoint-postgres 3.2.0`, `langgraph-prebuilt 1.1.1`, `psycopg 3.3.8`, `psycopg-pool 3.3.3`, `pydantic 2.14.3`. Postgres는 `postgres:17.11` 임시 컨테이너. 원본: `langgraph_checkpointer_probe.json`(실행 결과).

| 확인한 것 | 결과 |
|---|---|
| **연결 설정** | `AsyncConnectionPool(kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})`가 필요하다. autocommit 없이 `setup()`을 부르면 `psycopg.errors.ActiveSqlTransaction: CREATE INDEX CONCURRENTLY cannot run inside a transaction block`. `setup()`은 두 번 불러도 오류가 없다 |
| 테이블 | `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`(v9까지). 상태는 채널마다 msgpack 바이너리 blob이라 사람이 바로 읽을 수 없다 |
| **상태 속 pydantic** | pydantic 객체를 상태에 넣으면 왕복 시 타입은 보존되지만 `Deserializing unregistered type ... will be blocked in a future version` 경고가 난다 → 상태에는 dict·기본 타입만 넣거나 타입을 등록하고 `LANGGRAPH_STRICT_MSGPACK=true`로 테스트한다 |
| **하위 그래프와 상태 키 공유** | 부모와 같은 키(리듀서 `operator.add`)를 하위 그래프가 공유하면 입력이 출력에 다시 합쳐져 `trace`에 `supervisor`가 **두 번** 들어갔다 → 하위 그래프는 자기 전용 상태 스키마를 쓰고 부모 노드가 입력·출력을 명시적으로 매핑한다(ADR-008과 같은 방향) |
| 스트리밍 | `astream(input, config, context=..., stream_mode=["updates","custom"], subgraphs=True)`는 `(네임스페이스 튜플, 모드, 청크)`를 낸다. 하위 그래프 이벤트의 네임스페이스는 `['research:<uuid>']`. 노드 안의 `get_stream_writer()`는 하위 그래프 안에서도 `custom` 청크로 나온다 → SSE 이벤트는 `custom` 모드로 보낸다. `updates` 청크에는 **원본 파이썬 객체**가 들어 있어 SSE 직전에 직렬화한다. `astream_events(version="v2")`는 LangChain 모델을 쓰지 않는 노드에서 `on_chain_*`만 내므로 쓰지 않는다 |
| **컨텍스트(테넌트)** | `context_schema` + `ainvoke(..., context={"tenant_id": "A"})`로 넘기고 노드는 `runtime.context["tenant_id"]`로 읽는다. thread·컨텍스트가 다르면 값이 섞이지 않았다. **컨텍스트 없이 호출하면 `runtime.context`가 `None`이라 노드 안에서 `TypeError: 'NoneType' object is not subscriptable`**이 난다 → api가 호출 전에 테넌트를 검사하고(fail-closed) 도구의 범위 검사 함수가 명시적 오류를 올린다 |
| 스냅샷 | `StateSnapshot` 필드: `values, next, config, metadata, created_at, parent_config, tasks, interrupts`. `metadata` 키는 `parents, source, step`뿐이고 `config.configurable`은 `checkpoint_id, checkpoint_ns, thread_id` |
| **되돌림 상한** | `recursion_limit`을 넘으면 `langgraph.errors.GraphRecursionError`이고 상태는 **보존**된다(`attempts` 3, `next` `['planning']`). `recursion_limit`은 기획 횟수가 아니라 노드 실행(슈퍼스텝) 수라 `recursion_limit=8`에서 기획이 3번 돌고 멈췄다 → "평가→기획 되돌림 최대 2회"는 상태의 카운터로 구현하고 `recursion_limit`은 넉넉한 안전망으로 둔다 |
| 노드 라우팅·삭제 | 노드가 `Command(goto=..., update=...)`를 돌려주는 방식이 동작하고 도착지는 `add_node(..., destinations=(...))`로 알린다. `await checkpointer.adelete_thread(thread_id)` 뒤 `checkpoints` 행이 0이 되고 `aget_state`는 빈 `values`를 돌려준다(보존 기간 정리에 쓴다) |
| **테넌트 격리** | `thread_id`는 단순 문자열이고 DB 수준의 격리가 없다. 격리는 `thread_id = "<tenant>:<...>"` 규칙과 **api가 모든 읽기·재개에서 소유 테넌트를 검증**하는 것으로만 이뤄진다 |

- **미확인**: `interrupt`(승인 대기), 병렬 노드, 동시 요청에서의 체크포인터 동작, 압축 요약 저장 방식.

## Langfuse (2026-11-12 실측, 임시 컨테이너 5개, 끝난 뒤 볼륨까지 삭제)

서버: 프로젝트 B와 같은 구성(`langfuse/langfuse:3.225.11`, worker, `clickhouse/clickhouse-server:25.12.9.61`, `redis:7.4.11`, minio, `postgres:17.11`)을 호스트 포트만 바꿔(Postgres 15434, 웹 3001) 올렸다. 원본: `langfuse_probe.json`(REST 응답과 SDK 결과).

| 확인한 것 | 결과 |
|---|---|
| 기동 | `docker compose --profile obs up -d`에서 약 19초 만에 `/api/public/health`·`/api/public/ready`가 `{"status":"OK","version":"3.225.11"}`. 이미지는 이 맥에 이미 있었다(처음 받는 시간 **미확인**). Postgres 초기화 스크립트(`CREATE DATABASE langfuse`)가 반드시 필요하다 |
| **무인 초기화** | 웹 서비스에 `LANGFUSE_INIT_ORG_ID`, `LANGFUSE_INIT_PROJECT_ID`, `LANGFUSE_INIT_PROJECT_PUBLIC_KEY`, `LANGFUSE_INIT_PROJECT_SECRET_KEY`, `LANGFUSE_INIT_USER_EMAIL`, `LANGFUSE_INIT_USER_NAME`, `LANGFUSE_INIT_USER_PASSWORD`를 주면 첫 기동에 조직·프로젝트·키·사용자가 만들어진다(UI 없이 `auth_check` 통과). 키는 `.env`에서만 읽는다 |
| SDK | `langfuse==3.15.0`과 `5.2.0` 둘 다 이 서버로 trace를 보냈다(OTLP `/api/public/otel`). **`3.15.0` 고정**(서버 세대와 같고 실측을 전부 이것으로 했다). 3.x의 `start_as_current_generation`은 deprecated라 `start_as_current_observation(as_type="generation")`을 쓴다. 5.2.0은 `start_as_current_span`이 없고 `start_as_current_observation(as_type=...)` + `propagate_attributes(user_id, session_id, tags, metadata)`를 쓴다(5.x의 나머지는 얇게만 확인) |
| 수집 지연 | 전송이 비동기라 REST로 읽히기까지 수 초가 걸린다. 테스트는 `flush()` 뒤 폴링한다 |
| 읽은 필드 | trace: `id, name, userId, sessionId, tags, metadata, input, output, latency, totalCost, timestamp, environment`. 관측: `type`(`SPAN`·`GENERATION`), `model`, `usage`, `usageDetails`, `costDetails`, `calculated*Cost`, `parentObservationId`, `metadata`. `metadata`에는 우리가 준 `tenant_id`에 SDK가 `resourceAttributes`·`scope`를 덧붙인다 |
| **비용** | 서버가 모르는 모델(`gpt-6.1-terra`)에 `cost_details`를 주지 않으면 비용이 비어 합계에서 빠진다 → **항상 원장의 `response_cost`를 `cost_details`로 보낸다** |
| **테넌트 분리** | `user_id`에 `tenant_id`, `session_id`에 thread id를 넣으면 `GET /api/public/traces?userId=tenantA`가 그 테넌트 trace만 돌려준다(tenantA 1건, tenantB 0건) |
| 서버 꺼짐 | `flush()` 0.8초, `shutdown()` 1.2초(`timeout=3`)로 멈추지 않고 로그에 `Transient error ... Failed to export spans batch`를 남긴다. 단 **`auth_check()`는 `False`가 아니라 `ConnectError`를 올린다** → `obs` 래퍼가 예외를 삼키고 로컬 JSONL로 폴백한다 |
| **함정** | 같은 프로세스에서 같은 공개 키로 `Langfuse(...)`를 다시 만들면 다른 host를 줘도 기존 클라이언트를 재사용한다. 테스트는 키를 다르게 하거나 별도 프로세스로 한다. 잘못된 키는 REST 401 `{"message":"Invalid credentials. Confirm that you've configured the correct host."}` |

- **미확인**: 컨테이너 5개의 메모리 사용량, 처음 이미지 받는 시간, 대량 trace 지연, SDK 5.x의 상세 호환.

## Neo4j (2026-11-12 실측, 임시 컨테이너, 끝난 뒤 삭제)

| 확인한 것 | 결과 |
|---|---|
| 이미지·드라이버 | 이미지 `neo4j:2026.10.1-community`(같은 날 나온 2026.10.2는 피함), 드라이버 `neo4j==6.4.1`. pull 13초, 로그 `Started.`까지 7초. server agent `Neo4j/2026.10.1`, Bolt 6.1 |
| 복합 유일 제약 | `CREATE CONSTRAINT ... FOR (c:Creative) REQUIRE (c.source, c.source_id) IS UNIQUE`가 community에서 동작. `IF NOT EXISTS` 재실행은 `constraints_added 0`, 오류 없음 |
| MERGE 반복 | 같은 입력 2회째: `nodes_created 0`, `relationships_created 0`, **`properties_set 1`, `contains_updates true`**(값이 같아도 `SET`은 다시 쓴 것으로 센다). **"바뀐 행만 반영"은 그래프 카운터로 판정하지 않고 PostgreSQL의 변경 시각으로 판정한다.** 노드·관계 수 불변은 `count`로 검사 |
| 정수 | `2**40` 왕복 시 `int` 유지. 문자열 숫자는 문자열 그대로(YouTube `statistics`는 문자열이라 적재 전에 변환) |
| 제약 위반 | `ConstraintError`, `code` `Neo.ClientError.Schema.ConstraintValidationFailed`, `gql_status` `22N79` |
| 문법 오류 | `CypherSyntaxError`, `Neo.ClientError.Statement.SyntaxError`, `42001` |
| 없는 라벨·속성 | 오류가 아니라 **빈 결과** + 드라이버 WARNING 알림(`01N50`, `01N52`) 로그. 시끄러우면 `notifications_min_severity`로 거른다 |
| 잘못된 비밀번호 / 서버 없음 | `AuthError`(`Neo.ClientError.Security.Unauthorized`) / `ServiceUnavailable` |
| **첫 live 함정** | `NEO4J_AUTH` 비밀번호는 **데이터 볼륨을 처음 만들 때만** 적용된다. 나중에 `.env`를 바꾸면 기존 볼륨에서는 인증 실패이고 볼륨 삭제(명시 타깃)로만 해결된다 |
| 비밀번호 길이 | 8자 미만이면 기동 실패: "Invalid value for password. The minimum password length is 8 characters." |

원본 응답 파일은 없다(드라이버 출력과 카운터를 직접 확인). 적재 코드의 테스트는 이 표의 오류 종류를 가짜로 재현한다.

## 로컬 환경

| 확인한 것 | 내용 |
|---|---|
| Python HTTPS | uv 관리 파이썬 3.12.13은 `SSL_CERT_FILE` 없이 `urllib`(·httpx)가 HTTPS를 통과한다(2026-11-12, 이 저장소 `.venv`에서 `urllib.request.urlopen("https://pypi.org/simple/")` 200 확인). python.org 3.12.10은 `urllib`만 `CERTIFICATE_VERIFY_FAILED`(httpx는 certifi로 통과). 그래서 `pyproject.toml`에 `python-preference = "only-managed"`를 둔다 |
| 셸 | 기본 셸이 zsh다. 변수의 공백 분리가 bash와 다르다. 스크립트는 `#!/usr/bin/env bash`를 명시한다 |
| `.env` | 키 이름은 `.env.example`이 기준이다(출처 7개, 모델 3개, 로컬 compose 2개). **Instagram 호출 주체 ID는 `INSTAGRAM_USER_ID`로 정했고(2026-11-12) 사용자가 `.env`에 추가했다.** 빈 값이 기본값을 덮지 않게 읽는다 |
| OrbStack | docker 데몬이 꺼져 있으면 `docker.sock` 오류가 난다(2026-11-12 실제로 꺼져 있었음). compose를 쓰는 live 전에 켠다 |

## 미확인 (쓰기 전에 실측할 것)

| 외부 지점 | 무엇을 모르는가 | 언제 필요한가 |
|---|---|---|
| OpenAI·Anthropic 오류 | 429·503의 예외 형태(유도하지 못함), Anthropic thinking 설정, 캐시 최소 길이, OpenAI의 캐시 쓰기 가산 청구 여부 | M2 에이전트 |
| LangGraph | `interrupt`, 병렬 노드, 동시 요청에서의 체크포인터, 압축 요약 저장 방식 | M2 에이전트 |
| Langfuse | 컨테이너 5개의 메모리, 처음 이미지 받는 시간, 대량 trace 지연, SDK 5.x 상세 호환 | M2 관측 |
| 이미지 생성 | 요청·응답 형태와 비용 | M2 기획 |
| Instagram 사용 | 만료된 `media_url`의 응답 형태, 3일 뒤 `media_url` 반환 여부 일관성, 앱·계정 사용량 오류 코드(4·17·32·613은 알려진 코드이며 미실측), 호출 한도의 정확한 정의와 어느 지표가 먼저 차는지(호출당 0.5%는 과소추정으로 확인됨) | M1 수집·분석 |
| TikTok 영상 URL | 만료 시각과 만료 뒤 응답 형태 | M1 분석 |
| YouTube 쿼터 | 호출별 단위 비용·하루 한도, `quotaExceeded` 응답 형태 | M1 수집 |
| Gemini 유료 한도 | 실제 분당·일일 한도 수치(동시 30개 60호출은 전부 200) | M1 분석 일괄 |
| 식약처 공공 API | 보고·심사 두 API 겹침의 전체 규모, 일일 한도, 잘못된 키의 오류 형태(보고품목), `PA` 값(`"4"` 등)의 PA++++ 대응 | M1 1층 구축 |

프로젝트 B에서 겪은 것: LiteLLM 응답 본문의 `model`이 별칭이나 제공자 ID로 와서 실제 모델을 헤더로 확인해야 했다. 이 프로젝트의 SDK 직접 호출 실측(2026-11-12)에서는 실제 모델 이름이 왔다. Router나 별칭을 도입하면 같은 지점을 다시 실측한다.
