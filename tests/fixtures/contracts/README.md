# 외부 응답 원본

실제 API 응답을 기록한 원본이다(2026-11-11 ~ 12). 손으로 쓴 가짜 응답이 아니다.

- 지운 것: API 키·토큰, Gemini `signature` 문자열, Instagram CDN 주소의 서명 쿼리
- 그 밖의 필드와 값은 응답 그대로다
- `litellm_*`·`langgraph_*`·`langfuse_probe` 6건은 HTTP 원문이 아니라 SDK 객체의 `model_dump`나 실행 결과다(LiteLLM 1.103.3, LangGraph 1.2.20, langfuse 3.15.0). 헤더와 본문 그대로가 아니므로 HTTP 형태의 근거로 쓰지 않는다
- 파일마다 `_meta`(기록 시각, HTTP 상태, 무엇을 호출했는지)와 `response`가 있다

규칙:
- 테스트 픽스처는 이 원본을 복사하거나 읽어서 만든다. 응답 형태를 추측해 새로 쓰지 않는다.
- 이 폴더의 파일은 수정하지 않는다. 형태가 바뀐 것 같으면 다시 기록해 새 파일로 추가하고 `docs/CONTRACTS.md`를 고친다.
- 캡션과 자막에는 공개 게시물의 원문이 들어 있다.
