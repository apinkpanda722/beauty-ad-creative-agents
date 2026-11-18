# Step 6a: image-design

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`litellm`은 `llm`만), CRITICAL 규칙(영상·이미지 저장 규칙은 수집 소재 파일에 대한 것이고 생성 시안은 별개: ARCHITECTURE "상태 관리"), 비밀 값, 공급사 상한
- `/docs/ARCHITECTURE.md` — "상태 관리"의 파일 시스템 행(생성 시안 이미지는 로컬 gitignore, 텍스트 기획서만 입력)
- `/docs/CONTRACTS.md` — "P5 step 0 시험" 절의 이미지 생성 호출 행(`modalities`, `choices[0].message.images[0]`, `thought_signatures`, `response_cost`)
- `/tests/fixtures/contracts/gemini_image_completion_flash_lite_abridged.json`(축약본, 읽기 전용: base64·서명이 길이만 남아 있다), `/src/beautyads/llm/chat.py`, `/src/beautyads/llm/prices.py`, `/src/beautyads/llm/errors.py`, `/src/beautyads/llm/__init__.py`, `/src/beautyads/obs/ledger.py`, `/src/beautyads/domain/plan.py`, `/tests/test_llm_param_guard.py`, `/tests/test_llm_chat.py`, `/.gitignore`, `/tests/test_architecture.py` — step 0·1c·3 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/llm/image.py`(새 파일), `src/beautyads/llm/__init__.py`, `src/beautyads/agents/design_images.py`(새 파일), `.gitignore`, `tests/test_llm_image.py`(새 파일), `tests/test_design_images.py`(새 파일), `tests/test_llm_param_guard.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/llm/image.py`, `src/beautyads/llm/__init__.py`(export 추가에 한함), `src/beautyads/agents/design_images.py`, `.gitignore`(`data/design/` 한 줄 추가에 한함), `tests/test_llm_image.py`, `tests/test_design_images.py`, `tests/test_llm_param_guard.py`(이미지 호출 모양 조합 추가에 한함, 기존 조합과 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

기획안의 이미지 시안을 만드는 호출 래퍼와 로컬 저장을 만든다. 이미지 모델은 `gemini-3.1-flash-lite-image`(1K, 2026-11-17 시험: `litellm.completion(..., modalities=["image","text"])`가 성공, `response_cost` $0.0341885). 이 step은 모델·네트워크를 부르지 않는다. **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

**`llm/image.py`**(`llm` 계층): `generate_image(*, prompt: str, purpose_suffix: str = "plan", ledger_path, caps, purpose_caps, model="gemini-3.1-flash-lite-image", api_key=None, timeout_s=120.0, max_attempts=3, backoff_s=(2.0, 5.0, 15.0), completion_fn=None, sleep=time.sleep, now=None) -> ImageOutcome`.
- **입력은 텍스트 프롬프트(`str`) 하나뿐이다**(이미지·파일 입력 인자가 없다: 수집한 경쟁 소재 이미지를 넣을 방법이 없다). 장부 목적은 `"image-" + purpose_suffix`(접두어 `image`가 고정이라 이미지 목적 상한 `purpose_caps["image"]`에 합산된다).
- 호출 직전(시도마다): `check_cap(ledger_path, "gemini", caps, additional_usd=IMAGE_PRICE_USD)`와 `check_purpose_cap(ledger_path, "image", purpose_caps["image"], additional_usd=IMAGE_PRICE_USD)`를 모두 통과해야 한다(`IMAGE_PRICE_USD = 0.0336`, 1K 이미지 1장 공식 단가 2026-11-17, `llm/image.py`의 상수와 출처·날짜 주석). 둘 중 하나라도 넘으면 호출 없이 `CostCapExceeded`.
- 재시도는 `classify_error`가 `RETRYABLE`로 분류한 503·연결 실패·시간 초과에만 한다(일일 한도 429·크레딧 소진은 `DailyLimitReached`, 전송 후 실패를 재시도해 이중 과금하지 않는다).
- 응답 읽기: `choices` 아래 `message.images` 목록에서 `type == "image_url"`인 항목을 **이름으로** 찾고(위치로 찾지 않는다) `image_url.url`의 data URL(`data:<mime>;base64,<본문>`)을 푼다. `provider_specific_fields.thought_signatures`는 **읽지도 저장하지도 않고 버린다**(약 82만 자, 원장·로그·상태·trace·예외 메시지 어디에도 남기지 않는다). base64 본문도 디코딩 직후 바이트로만 다루고 문자열 형태로 로그·예외에 남기지 않는다.
- **검증**: 바이트의 **매직 바이트**로 형식을 정한다(PNG `89 50 4E 47 0D 0A 1A 0A`, JPEG `FF D8 FF`, WebP `RIFF`+4바이트+`WEBP`). data URL 머리의 mime이 아니라 매직 바이트가 기준이다. PNG·JPEG·WebP가 아니면 `IMAGE_MIME_UNSUPPORTED`, **크기 상한 10MB(10,485,760바이트)**를 넘으면 `IMAGE_TOO_LARGE`, 이미지 항목이 없거나 비어 있으면 `IMAGE_MISSING`, base64가 깨졌으면 `IMAGE_DECODE_FAILED`. 이 실패는 예외가 아니라 `ImageOutcome(ok=False, code=...)`로 돌려준다(호출이 과금됐으면 비용은 원장에 기록한다).
- 원장: `provider gemini`, 모델, 목적 `image-<suffix>`, 입력·출력 토큰(`usage.prompt_tokens`·`completion_tokens`), 비용은 응답 `response_cost`가 양수면 그대로(`cost_source="response_cost"`), 0·`None`이면 `IMAGE_PRICE_USD`(`cost_source="price_table"`), `reasoning_effort`는 `None`. 응답 전문·base64·서명은 기록하지 않는다.
- `ImageOutcome`(`ok`, `image_bytes: bytes | None`, `mime`, `size`, `sha256`, `cost_usd`, `model`, `code`): `repr`와 `str`에 바이트가 나오지 않는다(`image_bytes`는 `repr=False`).
- `llm/__init__.py`에 `generate_image`·`ImageOutcome`을 export한다.

**`agents/design_images.py`**(`agents` 계층, 외부 SDK 없음): `image_prompt(plan: Plan) -> str`(기획안의 `image_brief`·`hook_text`·`scenes` 같은 **텍스트 필드만**으로 시안 프롬프트를 만드는 순수 함수, 길이 상한 2,000자로 자르고 자른 사실은 반환하지 않아도 된다. 입력에 이미지·URL이 들어가지 않는다), `save_design_image(outcome: ImageOutcome, *, request_key: str, index: int, base_dir: Path = Path("data/design")) -> SavedImage`(`SavedImage`: `path`, `sha256`, `size`, `mime`만, 바이트 없음). 저장 경로는 `base_dir/<sha256(request_key)[:16]>/<index:02d>.<png|jpg|webp>`이고 요청 키가 경로에 직접 들어가지 않는다(경로 조작 불가). 임시 파일에 쓰고 이름을 바꿔 원자적으로 저장한다. `ok=False`인 결과는 저장하지 않고 `ValueError`. 이미지 끄기: 호출부가 `with_image=False`(기본)이면 이 모듈을 부르지 않는다(6c).

**`.gitignore`**: `data/design/` 한 줄을 추가한다(생성 시안은 로컬에만 두고 커밋하지 않는다).

**FP-C13 가드(필수)**: `tests/test_llm_param_guard.py`에 이미지 호출 모양(래퍼가 가짜 `completion_fn`에 넘긴 인자: `model="gemini/gemini-3.1-flash-lite-image"`, `modalities=["image","text"]`)을 실제 `litellm.get_optional_params`(`custom_llm_provider="gemini"`)에 넣어 예외가 없음을 단언한다. 이 조합이 거부되면(2026-11-17 live 시험에서는 호출이 성공했다) `blocked`로 보고하고 reason에 거부 메시지의 첫 줄만 적는다(우회 인자를 추측해 넣지 않는다).

**반드시 있어야 하는 테스트**(가짜 `completion_fn`, 원본 축약본 픽스처의 구조에서 만든 합성 응답. 실제 이미지 바이트는 만들어 쓰는 최소 합성 바이트(매직 바이트 + 임의 패딩)만 쓴다):
- 성공 경로: 합성 PNG·JPEG·WebP 바이트가 맞는 `mime`·`size`·`sha256`으로 돌아오고, data URL 머리가 틀려도(예: `image/png`로 적혔지만 JPEG 바이트) 매직 바이트 기준 mime이 나온다. 이미지 항목이 응답의 두 번째·세 번째 위치에 있어도 `type`으로 찾는다.
- 실패 코드: GIF·텍스트 바이트는 `IMAGE_MIME_UNSUPPORTED`, 10MB 초과(합성 큰 바이트는 상한을 낮춰 주입할 수 있는 인자나 상수 패치로 만든다. 10MB를 실제로 만들지 않아도 된다)는 `IMAGE_TOO_LARGE`, `images`가 없거나 비면 `IMAGE_MISSING`, 깨진 base64는 `IMAGE_DECODE_FAILED`. 모두 예외가 아니라 `ok=False`이고 과금된 호출은 원장에 기록된다.
- 폐기·비노출: 응답에 합성 `thought_signatures`(식별 가능한 합성 문자열)와 합성 base64가 있을 때 원장 행·`ImageOutcome`의 `repr`·예외 메시지·로그 어디에도 그 문자열이 없다(원장 파일 전체를 읽어 확인한다).
- 상한: 공급사 누적액이나 이미지 목적 합계가 상한 이상이면 호출 없이 `CostCapExceeded`(가짜가 불리지 않는다), 시도마다 재검사. 이미지 목적 합계가 `image-plan`·`image-probe`만 합산하고 다른 목적은 합산하지 않는다. 재시도는 503·연결 실패·시간 초과에만, 429·인증 오류는 재시도 없음.
- 원장: `response_cost` 양수는 `response_cost`, 0은 `price_table`로 `IMAGE_PRICE_USD`. `reasoning_effort`는 `None`. 목적은 `image-plan`.
- 입력은 텍스트뿐: `generate_image`의 시그니처에 이미지·파일 인자가 없다(`inspect.signature`로 단언). `image_prompt`가 `Plan`의 텍스트 필드로만 만들어지고 URL·바이트가 들어가지 않으며 2,000자를 넘지 않는다.
- 저장: `save_design_image`가 `tmp_path` 아래 `<해시16자>/<번호>.<확장자>`에 바이트를 쓰고 `SavedImage`에 바이트가 없다. 요청 키에 `../`가 있어도 경로가 `base_dir` 밖으로 나가지 않는다. `ok=False`는 거부. `.gitignore`에 `data/design/`가 있다(파일 내용 한 줄 확인).
- FP-C13 가드(위). `tests/test_architecture.py`가 통과한다(`litellm`은 `llm`만).

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

- 이미지·파일 입력을 받는 인자를 `generate_image`에 만들지 마라. 이유: 시안 생성 입력에는 수집한 경쟁 소재 이미지를 넣지 않고 텍스트 기획서만 넣는다(ARCHITECTURE 상태 관리).
- `thought_signatures`나 base64 문자열을 원장·로그·상태·예외 메시지에 남기지 마라. 이유: 서명 값 하나가 약 82만 자였고 키·서명 노출 금지다(CONTRACTS 2026-11-17, AGENTS.md 비밀 값).
- data URL 머리의 mime을 믿지 마라. 이유: 매직 바이트가 기준이다(검증 없이 저장하면 이미지가 아닌 바이트를 저장할 수 있다). 허용은 PNG·JPEG·WebP, 크기 상한 10MB.
- 생성 시안을 `data/design/` 밖에 저장하거나 커밋하지 마라. 이유: 생성 시안은 로컬(gitignore)에만 두고 커밋하지 않는다(데모 공개는 사용자 승인).
- 이미지 응답의 `images[0]`처럼 위치로 항목을 찾지 마라. 이유: 답은 항목의 `type`으로 찾는다(FP-C02). 응답에 첫 항목이 다른 종류일 수 있다.
- 이미지 호출의 상한 검사를 공급사 상한 하나로 끝내지 마라. 이유: 이미지 목적 상한(`image`, 기본 $3.5)이 따로 승인됐다. 둘 다 호출 직전에 검사한다.
