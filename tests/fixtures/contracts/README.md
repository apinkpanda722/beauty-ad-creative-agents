# 외부 응답 원본

실제 API 응답을 기록한 원본이다(2026-11-11 ~ 12). 손으로 쓴 가짜 응답이 아니다.

- 지운 것: API 키·토큰, Gemini `signature` 문자열, Instagram CDN 주소의 서명 쿼리
- 그 밖의 필드와 값은 응답 그대로다
- 예외: `mall_cafe24_image_only.html`의 업체 이메일·전화번호는 공개 준비 때 가짜 값(`shop@example.com`, `000-0000-0000`)으로 바꿨다. HTML 구조는 그대로다
- `tiktok_ad_query_*.json`(쪽 넘김 3건)의 광고 항목에 있던 CDN 주소의 서명 쿼리(`x-signature`, `refresh_token` 등)는 기존 `tiktok_ad_query.json`과 같은 방식으로 `?<query omitted>`로 지웠다. `videos[].url`의 경로에 든 토큰은 그대로다(만료되는 주소이며 테스트는 키의 존재만 쓴다)
- `gemini_files_failures_thinking_burst_probe.json`·`gemini_video_tokens_per_second_probe.json`·`instagram_mfds_youtube_probe.json`·`instagram_requery_probe.json`·`tiktok_pagination_report.json`·`tiktok_video_download_headers.json` 6건은 HTTP 응답 본문이 아니라 **실행 결과 요약**이다(측정값·상태 코드·헤더 이름과 값의 요약. URL의 쿼리와 토큰은 기록하지 않았다). 응답 형태의 근거로 쓰지 않고 `docs/CONTRACTS.md`의 수치 근거로만 쓴다
- `litellm_*`·`langgraph_*`·`langfuse_probe` 6건은 HTTP 원문이 아니라 SDK 객체의 `model_dump`나 실행 결과다(LiteLLM 1.103.3, LangGraph 1.2.20, langfuse 3.15.0). 헤더와 본문 그대로가 아니므로 HTTP 형태의 근거로 쓰지 않는다
- `litellm_p5_*.json` 3건과 `gemini_image_completion_flash_lite_abridged.json`(2026-11-17 P5 step 0 시험)은 **축약본(원본 아님)**이다: 300자를 넘는 문자열(이미지 base64, `thought_signatures`)을 `<str len=N>`으로 줄였다. `_meta`·`response` 구조가 아니라 시험 스크립트가 호출 이름을 키로 모은 `{이름: {ok, response_cost, raw | error_type, status_code, message}}` 형태다(`gemini_image_*`는 이미지 mime을 알 수 없다). 키·토큰은 없음을 확인했다
- 파일마다 `_meta`(기록 시각, HTTP 상태, 무엇을 호출했는지)와 `response`가 있다

규칙:
- 테스트 픽스처는 이 원본을 복사하거나 읽어서 만든다. 응답 형태를 추측해 새로 쓰지 않는다.
- 이 폴더의 파일은 수정하지 않는다. 형태가 바뀐 것 같으면 다시 기록해 새 파일로 추가하고 `docs/CONTRACTS.md`를 고친다.
- 캡션과 자막에는 공개 게시물의 원문이 들어 있다.
- 공개 게시물 원문이 포함되어 있으며 권리는 원 소유자에게 있다.
