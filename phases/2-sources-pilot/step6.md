# Step 6: gemini-files

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P2 sources-pilot"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/CONTRACTS.md` — "LiteLLM SDK 경유 OpenAI·Anthropic·Gemini Files" 절의 Gemini Files 두 행(지원, 삭제와 삭제 뒤 조회)과 "Gemini API" 절
- `/tests/fixtures/contracts/litellm_gemini_files_flow.json` — `create_file`·`file_retrieve`·`file_delete`의 성공 응답 형태(수정 금지)
- `/tests/fixtures/contracts/gemini_files_failures_thinking_burst_probe.json` — 실패 형태 원본: 비영상 업로드(`status: error`), 빈 파일(`ValueError`), 삭제·없는 파일로 분석한 403, 비활성 파일 400. **이 파일은 계약 PR로 `tests/fixtures/contracts/`에 들어온 뒤에만 존재한다. 없으면 코드를 쓰지 말고 `blocked`로 보고한다**
- `/src/beautyads/llm/gemini.py`, `/src/beautyads/llm/errors.py`, `/src/beautyads/llm/__init__.py`, `/tests/test_llm.py` — P1 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/llm/files.py`, `src/beautyads/llm/gemini.py`, `src/beautyads/llm/__init__.py`, `tests/test_llm_files.py`, `tests/test_llm.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/llm/files.py`, `src/beautyads/llm/gemini.py`(`video_part`의 `mime_type` 인자와 파일 오류 코드 적용 추가에 한함, 기존 동작 불변), `src/beautyads/llm/__init__.py`(공개 이름 추가에 한함), `tests/test_llm_files.py`, `tests/test_llm.py`(추가에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 라벨 키 파일을 읽는 채점 함수, 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

Instagram·TikTok 영상은 파일을 받아 Gemini Files API에 올린 뒤 분석한다(YouTube는 주소를 그대로 넣는다). 이 step은 LiteLLM SDK의 Files 함수를 감싸는 `llm/files.py`를 만든다. `llm/`은 `domain`, `settings`, `obs`만 import할 수 있고 `litellm`은 이 계층에서만 쓴다. **테스트는 가짜 함수와 원본 픽스처로만 하고 실제 호출은 하지 않는다.** 업로드·삭제는 토큰 비용이 없으므로 비용 원장에 기록하지 않는다.

소비자 테스트 점검 결과: `tests/test_llm.py`는 `gemini_interact`의 동작을 검사하며, 이 step은 `FATAL` 오류의 **코드 문자열만** 메시지가 파일 오류 패턴일 때 바꾼다(다른 메시지는 기존 코드 그대로). `video_part`는 선택 인자만 추가한다. `tests/test_analysis.py`·`tests/test_slice.py`·`tests/test_architecture.py`가 `llm`의 이름(`text_part`, `UsageInfo`, 패키지 import)을 쓰지만 이 step은 이름을 **추가**할 뿐 기존 이름·시그니처를 바꾸지 않아 영향이 없다. 그 파일들은 수정하지 않고, 깨지면 고치지 말고 `blocked`로 보고한다. 위 두 가지에 대해서는 기존 단언을 고치지 않고 새 테스트를 **추가**한다.

### 모듈 `llm/files.py` — 시그니처

```python
class UploadedFile(NamedTuple):
    id: str                  # 실측: 전체 주소(https://generativelanguage.googleapis.com/v1beta/files/<id>). 그대로 interactions의 uri로 쓴다
    size_bytes: int

class FileError(Exception):  # 속성: code, retryable: bool. 메시지에 API 키를 넣지 않는다
    # code: "EMPTY_FILE" | "FILE_UPLOAD_FAILED" | "FILE_STATUS_ERROR" | "FILE_PROCESS_TIMEOUT" | "FILE_RETRIEVE_FAILED"

def upload_video(data: bytes, *, filename: str, mime_type: str = "video/mp4", api_key: str | None = None,
                 create_file_fn: Callable[..., Any] | None = None) -> UploadedFile
def wait_processed(file_id: str, *, api_key: str | None = None, retrieve_fn: Callable[..., Any] | None = None,
                   sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic,
                   interval_s: float = 2.0, timeout_s: float = 120.0) -> None
def delete_file(file_id: str, *, api_key: str | None = None, delete_fn: Callable[..., Any] | None = None) -> bool
def file_error_code(message: str) -> str | None
```

- `upload_video`: **`len(data) == 0`이면 호출하지 않고 `FileError("EMPTY_FILE")`**(빈 파일 업로드는 SDK가 깨끗한 오류가 아닌 `ValueError("Error parsing file upload response: 'sizeBytes'")`를 올린다). 호출은 `litellm.create_file(file=(filename, data, mime_type), purpose="user_data", custom_llm_provider="gemini", api_key=...)`이고 `api_key`가 없으면 `require_setting("GEMINI_API_KEY")`다. 반환 객체(딕셔너리 또는 `model_dump()`를 가진 객체)의 `id`를 `UploadedFile.id`로 쓴다. 호출이 예외를 올리면 `classify_error`가 `RETRYABLE`이면 `retryable=True`로 `FileError("FILE_UPLOAD_FAILED")`, 그 밖이면 `retryable=False`(`ValueError` 포함). 메시지에서 `api_key`를 치환해 제거한다.
- `wait_processed`: `litellm.file_retrieve(file_id=..., custom_llm_provider="gemini", api_key=...)`를 `interval_s`마다 불러 `status`를 읽는다(객체 속성 또는 딕셔너리 키). 실측: `uploaded` → `processed`(3초 영상에서 2초 간격 조회 2번째). **`processed`면 반환**, **`error`면 `FileError("FILE_STATUS_ERROR")`**(비영상 바이트를 올리면 업로드는 성공하고 `status`가 `error`가 된다), `timeout_s`를 넘으면 `FileError("FILE_PROCESS_TIMEOUT", retryable=True)`, 조회 자체가 예외이면 `FileError("FILE_RETRIEVE_FAILED")`. 시계는 주입한 `monotonic`·`sleep`만 쓴다.
- `delete_file`: `litellm.file_delete(file_id=..., custom_llm_provider="gemini", api_key=...)`. **반환값의 `deleted`가 `True`일 때만 `True`**를 돌려주고, 그 밖이거나 예외이면 `False`다(예외를 올리지 않는다. 호출자가 정리 실패를 기록하고 넘어간다. 업로드한 파일은 약 48시간 뒤 만료된다). **삭제 확인에 `file_retrieve`를 쓰지 않는다**(삭제 뒤 조회는 깨끗한 NotFound가 아니라 `ValueError("Error parsing file retrieve response: 'createTime'")`를 올리고 ERROR 로그를 남긴다).
- `file_error_code(message)`: 메시지(대소문자 무시)에 `permission_denied`가 있거나 `may not exist`가 있으면 `"FILE_NOT_FOUND"`(없거나 삭제된 파일로 분석하면 404가 아니라 **403**으로 온다), `not in an ACTIVE state`가 있으면 `"FILE_NOT_ACTIVE"`(400 `invalid_request`), 그 밖이면 `None`.

### 기존 모듈에 추가 (추가에 한함)

- `gemini.py`의 `video_part`에 키워드 인자 `mime_type: str | None = None`을 추가한다. 주면 부분에 `"mime_type": mime_type`을 넣는다(실측: Files로 올린 파일은 `{"type": "video", "uri": <id>, "mime_type": "video/mp4"}`로 분석된다. 구간 지정은 Files 파일에서도 동작한다).
- `gemini_interact`가 `FATAL` 오류를 `LlmCallError`로 바꿀 때, 메시지에 대해 `file_error_code`가 코드를 돌려주면 그 코드를 `LlmCallError.code`로 쓴다(그 밖의 경우 기존 코드 그대로). 재시도 판정과 다른 동작은 바꾸지 않는다.
- `llm/__init__.py`의 공개 이름에 `UploadedFile`, `FileError`, `upload_video`, `wait_processed`, `delete_file`, `file_error_code`를 추가한다.

### 반드시 있어야 하는 테스트 (`tests/test_llm_files.py` + `tests/test_llm.py` 추가분)

- 성공 흐름: `litellm_gemini_files_flow.json`의 `create_file`·`retrieve_first`(`uploaded`)·`retrieve_processed`(`processed`)·`file_delete` 응답을 가짜 함수가 돌려주게 해 `upload_video` → `wait_processed`(첫 조회 `uploaded`, 둘째 `processed`: `sleep`이 `interval_s`로 한 번 불림) → `delete_file`(`True`)이 동작한다. `UploadedFile.id`가 원본의 전체 주소이고 크기가 `bytes`와 같다. `delete_file`의 가짜 호출 인자에 `file_retrieve` 호출이 없다.
- 실패 형태: 빈 바이트는 가짜 `create_file_fn`이 **한 번도 불리지 않고** `EMPTY_FILE`. `gemini_files_failures_thinking_burst_probe.json`의 `junk_upload`에 해당하는 `status: error`가 `FILE_STATUS_ERROR`, 시계를 앞당기는 가짜 `monotonic`으로 `FILE_PROCESS_TIMEOUT`(`retryable`), 업로드 예외가 503 계열이면 `retryable=True`이고 `ValueError`·400 계열이면 `False`, 조회 예외는 `FILE_RETRIEVE_FAILED`, `deleted: false`·예외는 `delete_file`이 `False`를 돌려주고 예외를 올리지 않는다. API 키 문자열이 `FileError`의 메시지에 없다.
- `file_error_code`: 원본의 `analyze_deleted_file`·`analyze_missing_file`의 오류 메시지가 `FILE_NOT_FOUND`, `analyze_junk`의 메시지가 `FILE_NOT_ACTIVE`, 관계없는 메시지는 `None`.
- `tests/test_llm.py`에 추가: 가짜 호출이 위 두 메시지를 담은 예외를 올리면 `gemini_interact`가 각각 `FILE_NOT_FOUND`·`FILE_NOT_ACTIVE` 코드의 `LlmCallError`(재시도 없음)를 올린다. 파일 오류와 관계없는 `FATAL`은 기존 코드 그대로다. `video_part`는 `mime_type`을 주면 부분에 넣고 안 주면 기존 출력과 같다.

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

- 삭제 확인에 `file_retrieve`를 쓰지 마라. `file_delete`의 `deleted`로만 판단한다. 이유: 삭제 뒤 조회는 깨끗한 NotFound가 아니라 `ValueError`를 올리고 ERROR 로그를 남긴다(`docs/CONTRACTS.md`).
- 빈 파일을 SDK에 올리지 마라. 호출 전에 `EMPTY_FILE`로 거부한다. 이유: SDK가 깨끗하지 않은 `ValueError`를 올린다(실측).
- `processed`가 아닌 파일로 분석을 진행하게 만들지 마라. `error`는 즉시 `FILE_STATUS_ERROR`, 시간 초과는 `FILE_PROCESS_TIMEOUT`이다. 이유: 비영상 바이트도 업로드는 성공하고 그 파일로 분석하면 400이 난다(실측).
- `delete_file`이 예외를 올리게 하지 마라. 정리 실패는 `False`로 알린다. 이유: 정리 단계의 실패가 소재 분석 결과를 덮으면 안 되고, 올린 파일은 약 48시간 뒤 만료된다.
- 기존 `gemini_interact`의 재시도·분류·원장 동작을 바꾸지 마라. 바꾸는 것은 파일 오류 메시지의 `code` 문자열뿐이다. 이유: P1에서 승인된 429 구분과 비용 상한 동작이 조용히 바뀌면 안 된다(A-FP-035).
