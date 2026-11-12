# 외부 계약 실측 목록

외부 서비스의 응답 형태를 **실제 응답으로 확인한 것만** 적는다. 문서나 추측으로 아는 것은 "미확인"에 따로 둔다. phase를 설계할 때 그 phase가 건드리는 외부 지점을 여기서 찾아 step 파일에 근거 경로와 함께 옮긴다. 여기에 없는 외부 지점을 쓰는 step은 먼저 실측하고 이 문서에 추가한 뒤 설계한다.

- 실측일: 2026-11-11 ~ 12
- 원본 응답: `tests/fixtures/contracts/` (비밀 값과 서명 문자열만 지우고 나머지는 응답 그대로)
- 픽스처를 만들 때는 이 원본을 복사해 쓴다. 손으로 새로 쓰지 않는다.

## YouTube Data API v3

| 확인한 것 | 실제 형태 | 원본 |
|---|---|---|
| 핸들로 채널 찾기 | `channels?forHandle=@핸들`. `items[0].id`가 채널 ID, `contentDetails.relatedPlaylists.uploads`가 업로드 목록 | `youtube_channels_forhandle.json` |
| **없는 핸들** | 오류가 아니라 **200**이고 **`items` 키 자체가 없다**(빈 배열이 아님) | `youtube_channels_forhandle_missing.json` |
| 업로드 목록 | `playlistItems`의 `items[].contentDetails.videoId`, 다음 쪽은 `nextPageToken`. 마지막 쪽에서 이 키가 어떻게 오는지는 원본으로 확인하지 못했다(**미확인**, 없을 수 있다고 보고 읽는다) | `youtube_playlistitems.json` |
| 영상 상세 | `statistics`의 값이 **전부 문자열**(`"viewCount": "1973746"`). `contentDetails.duration`은 `PT2M14S` 형식 | `youtube_videos.json` |
| 잘못된 키 | 400, `error.code`는 정수, `error.status`는 `INVALID_ARGUMENT` | `youtube_error_bad_key.json` |

주의:
- `statistics`의 키는 영상마다 빠질 수 있다(좋아요·댓글을 숨긴 영상). 이번 표본에서는 전부 있었고, 빠진 사례는 **미확인**이다. 없을 수 있다고 보고 읽는다.
- 채널을 이름으로 검색(`search?type=channel`)하면 공식 채널이 아닌 것이 섞인다. 8곳 중 3곳이 틀렸다. 채널은 `config/sources.yaml`의 ID로만 찾는다.
- 쿼터: 호출별 단위 비용과 하루 한도는 **미확인**이다(문서 요약과 기억이 서로 달랐다). 채널 이름 검색은 쓰지 않으므로 수집은 `channels`·`playlistItems`·`videos` 세 호출만 쓴다. M1 설계 전에 콘솔에서 실제 사용량을 확인한다.

## Instagram Graph API (Business Discovery)

| 확인한 것 | 실제 형태 | 원본 |
|---|---|---|
| 호출 주체 | `GET /{내 IG 사용자 ID}?fields=business_discovery.username(대상){...}`. 앱 심사를 신청하지 않은 새 앱에서 동작했다(앱의 모드 표시는 직접 확인하지 않았다) | `instagram_business_discovery_with_media_url.json` |
| **`media_url`이 없을 때** | `null`이 아니라 **키 자체가 빠진다**. 같은 계정 안에서도 게시물마다 다르다 | `instagram_business_discovery_without_media_url.json` |
| `view_count` | 묶음 게시물에는 **키가 없다**. 영상이라도 없을 수 있다(바이오던스 계정은 릴스 24건 모두 없었다. 이 사례의 원본은 저장하지 않았다) | `instagram_business_discovery_with_media_url.json` |
| 게시물 유형 | 원본에서 본 `media_type`은 `VIDEO`·`CAROUSEL_ALBUM`, `media_product_type`은 `REELS`·`FEED`다. `IMAGE` 등 다른 값은 **미확인**이므로 모르는 값이 와도 죽지 않게 읽는다. 묶음 게시물에도 `media_url`이 올 수 있다(영상이 아님) | 위와 같음 |
| 다음 쪽 | `media.paging.cursors.after`만 준다. `next` 주소는 없다 | 위와 같음 |
| **없는 계정** | 400, `error.code` 110, `error_subcode` 포함 | `instagram_error_invalid_user.json` |
| 잘못된 토큰 | 400, `error.code` 190 | `instagram_error_bad_token.json` |
| **`me/accounts`** | 권한이 다 있어도 **빈 배열**이 온다. 연결된 IG 계정 ID는 페이지 ID로 직접 조회해야 나온다 | `instagram_me_accounts.json` |

주의:
- 릴스 영상 주소 반환율은 표본 195건 중 101건(52%)이었고 계정마다 0%~100%로 갈린다.
- `media_url`은 서명이 붙은 임시 주소다. 저장해 두고 나중에 받으면 만료돼 있을 수 있다. 만료 시간은 **미확인**이다. 받을 때마다 새로 조회한다.
- 영상 여부는 `media_type == "VIDEO"`로 판단한다. `media_url` 유무로 판단하면 묶음 게시물이 섞인다.
- 장기 토큰은 약 60일 뒤 만료된다(교환 응답의 `expires_in` 약 5,183,755초). 만료 전 재발급이 필요하다.
- 호출 한도는 **미확인**이다.

## TikTok Commercial Content API

| 확인한 것 | 실제 형태 | 원본 |
|---|---|---|
| 자격 증명 위치 | 승인되면 연구용 클라이언트가 자동으로 생긴다. 개발자 포털의 **My research**에 있고 **Manage apps**에는 없다. Manage apps에서 앱을 새로 만들면 그 키로도 토큰은 발급되지만 조회는 401로 거부된다 | `tiktok_error_bad_token.json`과 같은 형태 |
| 토큰 발급 | `POST /v2/oauth/token/`, 폼 인코딩(`client_key`, `client_secret`, `grant_type=client_credentials`). `expires_in` 7200초, 리프레시 토큰 없음. 만료되면 다시 발급한다 | `tiktok_oauth_token.json` |
| 광고 조회 | `POST /v2/research/adlib/ad/query/?fields=...`, 본문 JSON. `max_count` 최대 10, 다음 쪽은 응답의 `search_id`를 다시 넣는다 | `tiktok_ad_query.json` |
| **성공 응답에도 `error`가 있다** | 200이어도 `{"data": ..., "error": {"code": "ok", "message": "", "log_id"}}`. `error` 키의 존재로 실패를 판단하면 안 된다. HTTP 상태와 `error.code == "ok"`로 판단한다 | 위와 같음 |
| **날짜는 문자열** | `ad_published_date_range`의 `min`·`max`는 `"YYYYMMDD"` 문자열이어야 한다. 숫자로 보내면 400 | `tiktok_error_date_as_number.json` |
| **`max`는 오늘보다 앞** | 오늘 날짜를 넣으면 400("Please provide a value before today's date"). 기준일은 어제 이전으로 둔다 | `tiktok_error_date_max_not_before_today.json` |
| 날짜 범위 필수 | `ad_published_date_range`가 없으면 400 | `tiktok_error_missing_filter.json` |
| 국가 필터 | `country_code_list` 배열이 동작한다(문서 예시의 `country_code`는 쓰지 않았다) | `tiktok_ad_query.json` |
| 잘못된 토큰 | 401, `error.code` = `access_token_invalid` | `tiktok_error_bad_token.json` |
| 응답 항목 | `ad.id`(숫자), `first_shown_date`·`last_shown_date`(`"YYYYMMDD"` 문자열), `status`(소문자), `videos[].url`·`cover_image_url`, `image_urls[]`, `reach.unique_users_seen`(구간 문자열), `advertiser.business_id`(숫자)·`business_name`·`paid_for_by` | `tiktok_ad_query.json` |
| 영상 파일 | `videos[].url`로 mp4를 직접 받을 수 있다. 3건 확인: 4.3~10.0MB, `Content-Length`와 받은 바이트 수가 같았다(잘리지 않음). 10MB 파일 하나에 약 12초 | 원본 미저장(파일이 큼) |

주의:
- **도달 수는 숫자가 아니라 구간 문자열**이다(`"600K-700K"`, `"1M-10M"`). 정렬·비교하려면 구간의 하한이나 중앙값으로 바꿔 쓰고, 바꾼 방식을 결과 문서에 적는다.
- **광고주 이름이 숫자 문자열로 오는 경우가 많다.** 브랜드 3곳 30건 중 12건이 `"7648220666696564758"` 같은 숫자였다. 빈 문자열과 `null`도 다른 검색에서 관측됐다. 광고주 이름으로 브랜드를 판정하지 않는다.
- **검색어는 광고 내용에 걸린다.** 브랜드 이름으로 찾으면 그 브랜드가 집행한 광고뿐 아니라 그 제품을 파는 소매점(세포라, 에토스 등) 광고와 일반인 광고가 섞인다. 코스알엑스는 광고주 이름이 브랜드와 일치했지만 메디큐브·바이오던스는 대부분 소매점이었다.
- **서버 오류(500 `internal_error`)가 간헐적으로 난다.** 아비브 조회가 한 번 500으로 실패했고 다시 보내자 성공했다. 503·429와 함께 대기 후 재시도 대상으로 둔다.
- 영상 파일이 최대 10MB 정도라 Gemini 인라인 입력이 아니라 Files API 업로드 경로를 쓴다.
- 영상 주소의 만료 시간은 **미확인**이다(주소에 만료 표시 인자가 보이지 않았다). 받을 때마다 새로 조회한다.
- 호출 한도는 **미확인**이다. 응답 헤더에 한도 정보가 없었다.
- EU 게재 광고만 조회된다(신청 페이지 기준). 조회 가능 기간은 최근 1년이다.

## 식약처 공공 API (공공데이터포털)

공통: `https://apis.data.go.kr/1471000/{서비스}/{오퍼레이션}?serviceKey=...&type=json&pageNo=&numOfRows=`. 인증키는 `.env`의 `DATA_GO_KR_SERVICE_KEY`(디코딩 키). 성공 응답은 `{"header": {"resultCode": "00", ...}, "body": {"pageNo", "totalCount", "numOfRows", "items": [...]}}`.

| 확인한 것 | 실제 형태 | 원본 |
|---|---|---|
| 원료성분정보 오퍼레이션 | `CsmtcsIngdCpntInfoService01/getCsmtcsIngdCpntInfoService01`, 검색 파라미터 `INGR_KOR_NAME` | `mfds_ingredient_query.json` |
| 원료성분 응답 항목 | `INGR_KOR_NAME`, `INGR_ENG_NAME`, `CAS_NO`, `INGR_SYNONYM`, `ORIGIN_MAJOR_KOR_NAME`. `INGR_SYNONYM`은 표본에서 전부 `null` | 위와 같음 |
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
- **`EFFECT_YN1`~`3`은 미백·주름 개선 여부가 아니다.** 상세페이지에 "주름개선 / 미백 기능성"이라고 적힌 코스알엑스 세럼이 보고품목정보에 있는데(2023-06-05 보고) 세 값이 모두 `N`이었다. 필드의 뜻은 **미확인**이며, 기능성 종류를 어느 필드로 판정할지 포털 명세로 확인해야 한다.
- **품목명은 띄어쓰기가 없다.** "코스알엑스더6펩타이드스킨부스터세럼"처럼 붙어 있어, "펩타이드 스킨 부스터"(띄어 씀)는 0건, "펩타이드스킨부스터"는 11건이었다. 검색어의 공백을 지우고 보낸다.
- 취하된 품목(`CANCEL_APPROVAL_YN`)을 걸러야 한다.
- 일일 한도는 **미확인**이다.

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

주의:
- **가격은 이미지에서 뽑지 않는다.** 이미지에서 "16,000원"이 추출됐지만 메타 태그의 정가는 46,000원, 판매가는 31,000원이었다(행사 문구로 보임). 가격은 메타 태그로만 읽는다.
- **세트 상품을 피한다.** 시험한 상품이 "1+1" 세트라 단위당 가격 계산이 틀어진다. 대표 제품은 단품 페이지로 고른다.
- 상세 이미지 수집량이 크다(상품당 수십 MB). 전성분은 보통 끝부분에 있으므로 뒤쪽 이미지부터 읽고, 전성분을 찾으면 멈춘다. 이미지는 저장하지 않는다.
- 몰마다 형식이 다르다(텍스트 표 / 이미지). 텍스트 표가 있으면 그것을 먼저 쓰고 없을 때만 이미지를 읽는다.
- 아누아의 클렌징 폼 페이지가 "기능성 화장품 심사(또는 보고)를 필함"이라고 적혀 있었다. 클렌징 폼에 맞지 않아 보이는 문구라, 페이지의 고시 문구를 그대로 믿지 말고 식약처 보고품목정보로 대조한다.
- 이용약관(두 몰): 사이트에 지적재산권이 있는 정보를 사전 승낙 없이 **영리 목적으로** 복제·배포하는 것을 금지한다. 크롤링 자체를 금지하는 조항은 찾지 못했다. 비영리로 사실 정보(전성분·가격·효능 표기)만 추출하고 이미지는 저장·재배포하지 않는다.

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

주의:
- **오류 본문의 형태가 두 가지다.** 과부하는 객체에 문자열 코드, 잘못된 키는 배열에 정수 코드다. 오류를 해석하는 코드는 HTTP 상태를 먼저 보고, 본문은 두 형태를 모두 받아야 한다.
- 과부하(503)는 실측 중 여러 번 났고, 한 번은 144초가 걸렸으며 한 번은 150초 넘게 응답이 없었다. 호출에는 시간 제한을 두고, 503·429·시간 초과만 대기 후 다시 시도한다.
- 프롬프트가 느슨하면 답의 뜻이 달라진다. "첫 구간에 무슨 일이 일어나는가"를 물었는데 `"00:03"`처럼 시각만 돌려준 사례가 있다. 구조화 출력 기능으로 형식을 강제하는 방식은 **미확인**이다. M1 설계 전에 실측한다.
- 같은 영상의 분류가 호출마다 달라진 사례가 있다(`question`과 `problem`). 모델도 달랐다.
- 업로드한 파일은 약 48시간 뒤 만료된다(`expirationTime`). 분석 직후 삭제를 요청한다.
- 무료 범위의 한도 수치는 **미확인**이다. 유료 단가는 2027-01-01부터 두 배가 된다(가격 페이지, 2026-11-12 확인).

## 로컬 환경

| 확인한 것 | 내용 |
|---|---|
| Python HTTPS | 이 맥의 python.org 3.12는 그대로 쓰면 인증서 검증에 실패한다. `SSL_CERT_FILE=/etc/ssl/cert.pem`을 줘야 한다. 프로젝트 가상 환경에서는 `certifi`로 해결되는지 **미확인** |
| 셸 | 기본 셸이 zsh다. 변수의 공백 분리가 bash와 다르다. 스크립트는 `#!/usr/bin/env bash`를 명시한다 |
| `.env` | 키 5개(`YOUTUBE_API_KEY`, `GEMINI_API_KEY`, `INSTAGRAM_ACCESS_TOKEN`, `META_APP_ID`, `META_APP_SECRET`). 빈 값이 기본값을 덮지 않게 읽는다 |

## 미확인 (쓰기 전에 실측할 것)

| 외부 지점 | 무엇을 모르는가 | 언제 필요한가 |
|---|---|---|
| Gemini 구조화 출력 | 스키마를 주면 울타리 없이 오는지, 닫힌 값 목록을 강제할 수 있는지 | M1 소재 분석 |
| Gemini 무료 범위 한도 | 분당·일일 요청 수 | M1 분석 일괄 실행 |
| OpenAI·Anthropic 호출(LiteLLM 경유) | 응답 본문의 모델 이름, 오류 형태, 도구 호출 형식 | M2 에이전트 |
| Neo4j | 드라이버 버전과 MERGE 동작, 컨테이너 기동 시간 | M1 그래프 적재 |
| LangGraph | 체크포인터, 하위 그래프 호출, 스트리밍 이벤트의 실제 형태 | M2 에이전트 |
| Langfuse | 로컬 실행 구성과 trace 필드 | M2 관측 |
| YouTube `statistics` 누락 | 좋아요·댓글을 숨긴 영상의 형태 | M1 수집 |
| Instagram `media_url` 만료 | 주소의 유효 시간 | M1 수집 |
| 이미지 생성 | 요청·응답 형태와 비용 | M2 기획 |
| 식약처 공공 API | `EFFECT_YN1`~`3`의 뜻, 심사품목정보 API, 일일 한도, 잘못된 키의 오류 형태 | M1 1층 구축 |
| 브랜드 공식몰 상세페이지 | 나머지 11개 몰의 형식(텍스트 표인지 이미지인지), 대표 단품 목록 | M1 1층 구축 |

프로젝트 B에서 겪은 것: LiteLLM은 응답 본문의 `model`을 일관되게 채우지 않았고(별칭이 오거나 제공자 ID가 옴) 실제 모델은 헤더로 확인해야 했다. 이 프로젝트에서도 LiteLLM을 쓰므로 M2 설계 전에 같은 지점을 다시 실측한다.
