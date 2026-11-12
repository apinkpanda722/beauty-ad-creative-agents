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

프로젝트 B에서 겪은 것: LiteLLM은 응답 본문의 `model`을 일관되게 채우지 않았고(별칭이 오거나 제공자 ID가 옴) 실제 모델은 헤더로 확인해야 했다. 이 프로젝트에서도 LiteLLM을 쓰므로 M2 설계 전에 같은 지점을 다시 실측한다.
