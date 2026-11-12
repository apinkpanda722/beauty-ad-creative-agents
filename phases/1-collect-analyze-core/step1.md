# Step 1: settings-domain

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P1 collect-analyze-core"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드(step 0 산출물). 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/ARCHITECTURE.md`의 "데이터 흐름" 오프라인 1~2번과 "상태 관리"
- `/docs/TAXONOMY.md` — "1. 훅 유형" 절(값 목록은 초안 v0이며 P3에서 동결된다)
- `/docs/CONTRACTS.md` — YouTube 표의 `statistics` 주의(좋아요·댓글 키가 없는 영상이 있다)
- `/.env.example` — 키 **이름** 목록만 본다(`.env` 자체는 열지 않는다)
- `/pyproject.toml`, `/tests/test_architecture.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `pyproject.toml`, `uv.lock`, `src/beautyads/settings.py`, `src/beautyads/domain/__init__.py`, `src/beautyads/domain/creative.py`, `src/beautyads/domain/labels.py`, `src/beautyads/domain/protocols.py`, `tests/test_settings.py`, `tests/test_domain.py`

열람 금지 경로: (없음)
수정 허용 경로: `pyproject.toml`, `uv.lock`, `src/beautyads/settings.py`, `src/beautyads/domain/**`, `tests/test_settings.py`, `tests/test_domain.py`

이 step은 `.env`를 읽는 유일한 함수(`settings`)와 모든 계층이 공유하는 도메인 타입을 만든다. `uv add pydantic`으로 의존성을 추가한다(`pyproject.toml`과 `uv.lock` 갱신). 패키지 설치는 이 명령만 허용되고, 해석된 `pydantic` 버전을 완료 보고의 `summary`에 적는다. **`settings.py`와 `domain/`은 표준 라이브러리와 `pydantic`만 import할 수 있다**(계층 가드의 `PURE_EXTERNAL`).

### settings.py — 시그니처

```python
ThinkingLevel = Literal["default", "minimal", "low", "medium", "high"]   # "default" = 요청에 thinking_level을 보내지 않는 서버 기본(비교군). 설정 기본값은 "minimal"
DEFAULT_ENV_FILE = Path(".env")

class SettingError(Exception):  # 속성: name, code. 메시지에 값을 넣지 않는다(이름만)
class MissingSetting(SettingError)
class InvalidSetting(SettingError)

def read_env_file(path: Path) -> dict[str, str]
def get_setting(name: str, default: str | None = None, *, environ: Mapping[str, str] | None = None, env_file: Path | None = DEFAULT_ENV_FILE) -> str | None
def require_setting(name: str, *, environ=None, env_file=DEFAULT_ENV_FILE) -> str          # 없으면 MissingSetting
def neo4j_password(*, environ=None, env_file=DEFAULT_ENV_FILE) -> str                      # NEO4J_PASSWORD, 8자 미만이면 InvalidSetting

class Settings(BaseModel):
    ledger_path: Path = Path("data/manifest/costs.jsonl")
    analysis_window_max_s: int = 60      # 분석 구간 상한(초)
    video_length_cut_s: int = 600        # 이보다 긴 영상은 수집 시점에 analyzable=False로 판정한다(근거 없는 추정 기본값, 시범 뒤 조정)
    thinking_level: ThinkingLevel = "minimal"

def load_settings(*, environ=None, env_file=DEFAULT_ENV_FILE) -> Settings
```

- `.env`는 **표준 라이브러리로 직접 파싱**한다(`KEY=VALUE` 줄, `#` 주석과 빈 줄 무시, 첫 `=`에서 분리, 앞뒤 공백 제거, 값 양끝의 같은 따옴표 한 쌍 제거, 변수 확장 없음). `python-dotenv`·`pydantic-settings`는 쓰지 않는다.
- 값의 우선순위: `environ`(기본 `os.environ`)의 비공백 값 → `.env`의 비공백 값 → `default`. **빈 문자열과 공백뿐인 값은 설정되지 않은 것으로 본다**(기본값을 덮지 않는다). `env_file=None`이면 `.env`를 읽지 않는다.
- `load_settings`가 읽는 환경 변수 이름: `BEAUTYADS_LEDGER_PATH`, `BEAUTYADS_ANALYSIS_WINDOW_MAX_S`, `BEAUTYADS_VIDEO_LENGTH_CUT_S`, `BEAUTYADS_THINKING_LEVEL`. 정수가 아니거나 0 이하이거나 목록 밖 값이면 `InvalidSetting`(이름만 메시지에 넣는다).
- 이 함수들은 파일을 만들거나 고치지 않는다.

### domain — 모델과 Protocol (pydantic v2, 모든 모델 `extra="forbid"`)

- `Source`(`StrEnum`): `youtube`, `instagram`, `tiktok`
- `HookType`(`StrEnum`): `question`, `problem`, `result_first`, `bold_claim`, `product_first`, `person_first`, `other` (TAXONOMY v0 초안. P3에서 동결되므로 값 목록을 다른 곳에 복사하지 않는다)
- `JobStatus`(`StrEnum`): `pending`, `done`, `held`, `failed` (보류는 `held`)
- `Metrics`: `view_count`, `like_count`, `comment_count` 모두 `int | None = None`. **`None`은 "값 없음"이고 0과 다르다**
- `CreativeKey`: `source: Source`, `source_id: str`(빈 문자열 불가). 해시 가능하고 불변
- `Creative`: `source`, `source_id`, `url: str | None`, `title: str | None`, `caption: str | None`, `published_at: datetime | None`, `duration_s: float | None`, `language: str | None`, `analyzable: bool | None = None`, `metrics: Metrics = Metrics()`, `collected_at: datetime`(시간대 포함). 속성 `key -> CreativeKey`
- `is_analyzable(creative) -> bool`: **`analyzable is True`일 때만 True**. `None`(미판정)과 `False`, 키 없음은 모두 False다
- `HookResult`: `hook_type: HookType` 하나(목록 밖 값은 검증 오류)
- Protocol(모두 동기 메서드):

```python
class CreativeRepository(Protocol):
    def upsert_creatives(self, creatives: Sequence[Creative]) -> int
    def get_creative(self, key: CreativeKey) -> Creative | None

class AnalysisRepository(Protocol):
    def enqueue_analysis(self, kind: str, creatives: Sequence[Creative]) -> int   # is_analyzable인 것만 큐에 넣고 넣은 수를 돌려준다
    def next_pending(self, kind: str, limit: int) -> list[Creative]
    def record_analysis(self, kind: str, key: CreativeKey, *, status: JobStatus, model: str | None,
                        thinking_level: str | None, prompt_version: str | None, raw_output: str | None,
                        labels: Mapping[str, str] | None, error_code: str | None) -> None
```

### 반드시 있어야 하는 테스트

- `tests/test_settings.py`: 모두 `tmp_path`의 임시 `.env` 또는 `env_file=None`과 명시한 `environ` 딕셔너리만 쓴다. 파싱(주석·따옴표·`=`가 값에 들어 있는 경우), 우선순위, **빈 값·공백 값이 기본값을 덮지 않음**, `MissingSetting`/`InvalidSetting` 예외 메시지에 설정 **값이 들어 있지 않음**(이름만), `neo4j_password` 8자 미만 거부, `load_settings` 기본값(`thinking_level`은 `minimal`)과 잘못된 값 거부, `ThinkingLevel`의 모든 멤버(`default` 포함)를 받고 목록 밖 값(예: `maximum`)은 `InvalidSetting`, `.env` 파일이 없어도 오류 없이 기본값을 돌려줌.
- `tests/test_domain.py`: 통계가 없으면 `None`으로 남고 0이 되지 않음, `analyzable`을 안 주면 `None`이고 `is_analyzable`이 `None`·`False`·`True`를 각각 올바르게 가름(**`None`·키 없음이 분석 가능으로 취급되지 않음**), `HookResult`가 목록 밖 값을 거부하고 `HookType`의 **모든 멤버**를 받음(멤버를 순회한다), 알 수 없는 필드 거부, `CreativeKey` 해시·동등성, 시간대 없는 `collected_at` 거부.

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

- `.env`를 파싱하는 데 `python-dotenv`·`pydantic-settings`를 쓰지 마라. 이유: `settings`는 표준 라이브러리와 `pydantic`만 허용되고(가드의 `PURE_EXTERNAL`) 빈 값이 기본값을 덮는 동작을 우리가 직접 통제해야 한다(B-FP-030).
- 빈 문자열·공백뿐인 값을 "설정됨"으로 취급하지 마라. 이유: 빈 `.env` 항목이 기본값을 덮어 비용 상한이나 경로가 조용히 바뀐다(B-FP-030).
- 좋아요·댓글·조회수가 없을 때 0으로 바꾸지 마라(`None` 유지). 이유: 좋아요를 숨긴 영상(표본 1,349개 중 26개)을 0으로 저장하면 지표가 왜곡된다(`docs/CONTRACTS.md` YouTube).
- 테스트에서 실제 `.env`를 읽지 마라. 임시 `.env`(`tmp_path`)나 `env_file=None`만 쓴다. 이유: 비밀 값이 테스트 출력에 새는 것을 막고 환경에 따라 결과가 달라지지 않게 한다(A-FP-056).
- `HookType` 값 목록을 테스트에 복사해 비교하지 마라. 멤버를 순회한다. 이유: 분류 목록은 P3에서 동결되며 그때 한 곳만 바뀌어야 한다(FP-C03).
- 지시한 `uv add` 외의 패키지를 설치하거나 `pyproject.toml`에 다른 의존성을 추가하지 마라. 이유: 의존성 변경은 `uv.lock`과 함께 검토 대상이고 계층 가드의 SDK 표가 모르는 패키지는 검증되지 않는다.
