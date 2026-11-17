# Step 4: llm-image-input

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조, 온톨로지 절, 데이터 흐름
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P4 절과 변경 기록 #36
- `/docs/COMPETENCY_QUESTIONS.md` — v1(2026-11-15 동결), 홉 정의와 한계
- `/docs/CONTRACTS.md` — **"Gemini 이미지 입력 (2026-11-15 실측)"** 절(요청 형태, 응답, 토큰은 크기에 비례하지 않음, `input_tokens_by_modality` 순서가 호출마다 다름)
- `/tests/fixtures/contracts/gemini_interactions_image_input.json` — 실측 원본(**픽스처는 이 파일에서만 만든다**)
- `/src/beautyads/llm/gemini.py`, `/src/beautyads/llm/errors.py`, `/tests/test_llm.py` — 기존 호출·비용 기록·오류 분류(**기존 함수·단언은 바꾸지 않는다**)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/llm/gemini.py`, `tests/test_llm.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/llm/gemini.py`(`image_part`·`usage_by_modality` 추가에 한함, 기존 함수·상수·동작 불변), `tests/test_llm.py`(해당 케이스 추가에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

Gemini Interactions에 **이미지(인라인 바이트)를 넣는 입력 항목**을 만든다. 호출 자체(`gemini_interact`)는 이미 임의의 `input_parts`를 받으므로 바꾸지 않는다. 재시도(503·연결 실패·시간 초과만)·일일 한도 429·크레딧 소진 402 중단·호출 직전 상한 검사·원장 기록은 기존 동작 그대로다. **이 step 안에서는 실제 호출을 하지 않는다.**

- **`image_part(data: bytes, mime_type: str, *, max_bytes: int)`**: `{"type": "image", "data": <base64 문자열>, "mime_type": <mime_type>}`를 돌려준다(실측 원본의 요청 형태와 같은 키). `mime_type`이 `image/`로 시작하지 않으면 `ValueError("IMAGE_MIME_INVALID")`, 바이트가 비어 있으면 `IMAGE_EMPTY`, `max_bytes`를 넘으면 `IMAGE_TOO_LARGE`다(`max_bytes`는 필수 인자이고 이 step이 값을 정하지 않는다 — 크기 상한은 미실측). 실측한 것은 `image/png`뿐이다(다른 mime은 호출 쪽이 책임진다).
- **`usage_by_modality(response) -> dict[str, int]`**: 응답의 `usage.input_tokens_by_modality`에서 `modality` 값을 키로 토큰 수를 돌려준다. **위치(`[0]`)가 아니라 `modality` 값으로 찾는다**(실측에서 순서가 호출마다 달랐다, FP-C02). 키가 없으면 빈 딕셔너리다.
- Files API 주소(`uri`)를 쓰는 이미지 항목은 만들지 않는다(미실측).

### 반드시 있어야 하는 테스트

(가짜 `interactions_fn`은 `gemini_interactions_image_input.json`의 `probes[].response`를 돌려준다. 값은 픽스처에서 읽어 비교하고 숫자를 테스트에 박지 않는다.)
- `image_part`: 결과의 키 집합이 픽스처 `request_shape.input`의 이미지 항목(데이터 생략 필드 제외)의 키 집합과 같고, `data`가 base64로 디코드하면 원래 바이트다, 빈 바이트·잘못된 mime·`max_bytes` 초과가 각각 코드로 거부된다, `max_bytes` 없이는 호출할 수 없다.
- `usage_by_modality`: 픽스처 두 응답(모달리티 순서가 다르다)에서 `image`·`text` 토큰 수가 응답의 값과 같고, 순서를 바꿔도 같은 결과다, `input_tokens_by_modality`가 없거나 비어 있으면 빈 딕셔너리다.
- 통합: 가짜 `interactions_fn`으로 `gemini_interact(input_parts=[text_part(...), image_part(...)])`를 부르면 `extract_output_text`가 픽스처 응답의 답을 돌려주고, 원장에 `purpose`와 토큰이 기록되며(tmp 원장), 호출 인자에 `temperature`가 없고 `generation_config`에 `thinking_level`이 들어간다, 호출 직전 상한 검사가 불린다(상한을 넘으면 호출하지 않고 `COST_CAP`), 이미지 데이터(base64)가 원장·오류 메시지에 남지 않는다(감시 문자열).
- 기존 `tests/test_llm.py`가 그대로 통과하고 `tests/test_architecture.py`가 통과한다(`litellm`은 `llm`만).

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
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약(설치한 패키지 버전 포함)"`
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

- 실제 Gemini를 호출하지 마라. 테스트는 가짜 `interactions_fn`만 쓴다. 이유: 비용이 든다(AGENTS.md CRITICAL).
- 이미지 토큰 수·비용을 테스트나 코드의 기준값으로 박지 마라. 이유: 합성 이미지 2장의 실측값이다(조각 크기·실제 이미지에 따라 다르다, FP-C06).
- Files API 이미지 경로를 추측해 만들지 마라. 이유: 미실측이다(B-FP-050).
- `temperature`를 지정하지 마라. 이유: 추론 모델이 거부한다(AGENTS.md CRITICAL).
- 이미지 바이트·base64를 로그·원장·예외 메시지에 남기지 마라. 이유: 비밀은 아니지만 공식몰 이미지를 저장·재배포하지 않는다는 규칙의 일부다.
- 기존 `gemini_interact`·`video_part`·`UsageInfo`의 동작과 테스트를 바꾸지 마라. 이유: 분석 전체가 이 함수 위에 있다.
