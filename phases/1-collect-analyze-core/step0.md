# Step 0: architecture-guard

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — "계층 경계" 절의 두 표(내부 계층 표, 외부 SDK 표)가 이 step이 테스트로 강제할 규칙이다. 이 파일은 읽기만 한다.
- `/docs/ARCHITECTURE.md` — "디렉토리 구조"와 "패턴" 절
- `/docs/PHASES.md` — "P1 collect-analyze-core"의 step 0 설명
- `/pyproject.toml` — pytest 설정(`testpaths`, `timeout`, xdist)
- `/src/beautyads/__init__.py` — 지금 패키지에 있는 유일한 소스 파일(빈 파일)

`tests/test_architecture.py`는 **이 step 전에는 존재하지 않는다.** 공통 금지사항 블록이 이 파일을 "계층 경계 가드"로 참조하지만, 이 step이 그 파일을 처음 만든다.

## 작업

**수정할 파일**: `tests/test_architecture.py` (새 파일)

열람 금지 경로: (없음)
수정 허용 경로: `tests/test_architecture.py`

`src/beautyads/` 아래 모든 `.py` 파일의 import를 구문 분석(`ast`)해 AGENTS.md의 계층 경계 규칙을 어기는 import를 찾아내는 테스트 파일 하나를 만든다. 가드가 실제로 위반을 잡는지는 임시 디렉터리에 만든 위반 모듈로 확인한다. 이 step은 `src/` 아래 아무것도 추가하지 않는다.

### 규칙 상수 (이 테스트 파일 안에 둔다)

내부 계층 표. 값은 "그 계층이 import해도 되는 다른 `beautyads` 계층"이다(자기 계층 안의 import는 항상 허용).

| 계층 | 허용 |
|---|---|
| `domain` | (없음) |
| `settings` (루트 모듈 `settings.py`) | (없음) |
| `obs` | `domain`, `settings` |
| `llm` | `domain`, `settings`, `obs` |
| `sources` | `domain`, `settings` |
| `store` | `domain`, `settings` |
| `graph` | `domain`, `settings` |
| `checks` | `domain` |
| `analysis` | `domain`, `llm` |
| `agents` | `domain`, `graph`, `checks`, `llm`, `store`, `obs` |
| `api` | `domain`, `settings`, `obs`, `llm`, `sources`, `store`, `graph`, `checks`, `analysis`, `agents` |
| `pipeline` | `api`와 같은 목록(서로 import하지 않는다) |
| `eval` | 다른 모든 계층(`api`·`pipeline` 포함) |

- `domain`과 `settings`는 표준 라이브러리(`sys.stdlib_module_names`)와 `pydantic` 외의 외부 패키지를 import하지 못한다.
- 어떤 계층도 `eval`을 import하지 못한다(`eval` 자신 제외). 위 표에서 `eval`은 허용 목록에 나타나지 않으므로 규칙 하나로 처리된다.
- `src/beautyads/__init__.py`(패키지 루트)는 검사 대상 파일 수에는 세지만 계층 규칙은 적용하지 않는다.

외부 SDK 표. 키는 import 최상위 이름이고 값은 허용 계층이다.

| import 최상위 이름 | 허용 계층 |
|---|---|
| `litellm` | `llm` |
| `neo4j` | `graph` |
| `psycopg` | `store`, `api` |
| `psycopg_pool` | `psycopg`와 같음(별칭) |
| `langgraph` | `agents`, `api` |
| `fastapi` | `api` |
| `httpx` | `sources` |
| `langfuse` | `obs` |

표에 없는 외부 패키지(`yaml`, `pydantic` 등)는 `domain`·`settings` 외 계층에서 자유롭게 import할 수 있다.

### 공개 함수 시그니처 (테스트 파일 안에 정의한다)

- `class Violation(NamedTuple)`: `file: str`(패키지 루트 기준 상대 경로, `/` 구분), `target: str`(import한 모듈 또는 계층), `rule: str`
- `python_files(package_root: Path) -> list[Path]`: 패키지 루트 아래 모든 `.py`(`__init__.py` 포함). `__pycache__`는 제외한다.
- `find_violations(package_root: Path) -> set[Violation]`: **`.py` 파일이 하나도 없으면 `ValueError`를 올린다.** 위반이 없으면 빈 집합.

규칙 코드(`rule`)는 다음 다섯 개뿐이다.

- `LAYER`: 계층 표의 허용 목록에 없는 `beautyads` 계층을 import했다(`eval` import 포함)
- `SDK`: 외부 SDK 표의 허용 계층 밖에서 그 패키지를 import했다
- `PURE_EXTERNAL`: `domain`·`settings`가 표준 라이브러리와 `pydantic` 밖의 외부 패키지를 import했다
- `UNKNOWN_LAYER`: 패키지 루트 아래에서 `.py`를 하나 이상 포함하는 디렉터리(하위 디렉터리 포함, `__pycache__` 제외) 중 이름이 표에 없는 것, 또는 표에 없는 루트 모듈(`__init__.py`·`settings.py` 제외)이 있다. 새 계층은 AGENTS.md 표와 이 파일의 상수를 함께 고쳐야 한다는 뜻이다. `.py`가 없는 디렉터리(리소스·빈 디렉터리)는 판정하지 않는다
- `DYNAMIC_IMPORT`: `importlib.import_module(...)` 또는 `__import__(...)`의 인자가 문자열 리터럴이 아니다(검증할 수 없다)

리터럴 인자의 동적 import(`importlib.import_module("beautyads.llm")` 등)는 별도 규칙 코드 없이 일반 import와 똑같이 판정한다.

import 해석 규칙(구문 분석으로만 한다):

- 계층은 패키지 루트 아래 **첫 경로 요소**로 판정한다(`graph/tools/x.py`는 `graph`).
- `import beautyads.x.y`, `from beautyads.x import z`, `from beautyads import x, y as w`(별칭 이름이 아니라 원래 이름으로 판정), 상대 import(`from ..llm import a`, `from . import b`)를 모두 같은 방식으로 `beautyads` 계층으로 해석한다.
- `if TYPE_CHECKING:` 안의 import도 똑같이 검사한다(예외 없음).
- 패키지 루트 밖으로 나가는 상대 import는 `LAYER` 위반이다.
- `from beautyads import <이름>`에서 이름이 계층 이름이 아니고 `beautyads` 아래 모듈 이름도 아니면(예: `__version__`) 위반이 아니다. 계층 이름이면 그 계층 import로 판정한다.

### 반드시 있어야 하는 테스트

1. **실제 저장소 검사**: `src/beautyads`에 `find_violations`를 돌려 빈 집합임을 단언하고, `python_files`가 **1개 이상**임을 단언한다(정확한 개수는 단언하지 않는다).
2. **빈 트리 거부**: 임시 디렉터리에 `.py`가 없는 패키지 루트를 만들면 `find_violations`가 `ValueError`를 올린다.
3. **위반 검출 확인**(모두 `tmp_path` 안의 임시 모듈, 각각 기대 위반을 `(file, target, rule)` 집합으로 단언):
   - `domain`이 `beautyads.llm`을 import → `LAYER`
   - `domain`이 표준 라이브러리와 `pydantic`만 import → 위반 없음
   - `domain`이 `yaml`을 import → `PURE_EXTERNAL`
   - `domain`이 `from ..llm import x`(상대 import) → `LAYER`
   - `domain`이 `from beautyads import llm` → `LAYER`
   - `settings.py`가 `beautyads.llm`을 import → `LAYER`, `domain`이 `beautyads.settings`를 import → `LAYER`
   - `checks`가 `beautyads.llm`을 import → `LAYER`
   - `sources`가 `litellm`을 import → `SDK`, `llm`이 `litellm`을 import → 위반 없음
   - `agents`가 `psycopg`를 import → `SDK`, `api`가 `psycopg`를 import → 위반 없음
   - `agents`가 `langgraph`를 import → 위반 없음, `llm`이 `langgraph`를 import → `SDK`
   - `agents`가 `beautyads.eval`을 import → `LAYER`, `eval`이 `beautyads.agents`를 import → 위반 없음
   - `if TYPE_CHECKING:` 안에서 `domain`이 `beautyads.llm`을 import → `LAYER`
   - 표에 없는 디렉터리 `foo/`에 `.py`가 있으면 → `UNKNOWN_LAYER`, `.py`가 없는 빈 디렉터리·`data/` 같은 리소스 디렉터리만 있으면 → 위반 없음
   - `graph/tools/x.py`가 `beautyads.llm`을 import → `LAYER`(첫 경로 요소 `graph`로 판정)
   - `from beautyads import __version__` → 위반 없음
   - `importlib.import_module(name)`(변수 인자) → `DYNAMIC_IMPORT`, `importlib.import_module("beautyads.llm")`을 `domain`에서 → `LAYER`
   - 표에 없는 외부 패키지(`yaml`)를 `sources`에서 import → 위반 없음
4. **AGENTS.md 표와 상수의 일치**: `AGENTS.md`의 "## 계층 경계" 절을 읽어 (a) 내부 계층 표 첫 열의 계층 이름 집합이 이 파일의 계층 상수 키 집합과 같고, (b) 외부 SDK 표의 `패키지 → 허용 계층 집합`이 이 파일의 SDK 상수와(`psycopg_pool` 별칭 제외하고) 같음을 단언한다. 표의 열 머리글과 괄호 설명은 무시하고 백틱으로 감싼 이름만 읽는다. 표를 읽을 수 없으면 실패한다(0행이면 실패).

테스트는 `tests/`에 `__init__.py` 없이 pytest 기본 방식으로 동작해야 한다(`from tests...` 같은 import를 쓰지 않는다). 저장소 루트는 `Path(__file__).resolve().parents[1]`로 구한다.

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

- 검사 대상이 0건이어도 통과하게 만들지 마라. `find_violations`는 `.py`가 없으면 `ValueError`를 올리고 실제 저장소 검사는 파일이 1개 이상임을 단언한다. 이유: 가드가 아무것도 검사하지 않은 채 통과하는 것을 막는다(B-FP-069). 단 파일 개수를 고정값으로 단언하지 마라. 이후 step이 파일을 계속 늘린다(B-FP-061).
- 위반 검출 확인용 모듈을 `src/` 아래에 만들지 마라. `tmp_path` 안에서만 만든다. 이유: `src/`에 위반 모듈이 있으면 실제 가드가 실패해 이후 모든 step의 검증이 깨진다.
- import 판정에 문자열·정규식 검색을 쓰지 마라. `ast`로 구문 분석한다. 이유: 주석과 문자열 속 단어를 오탐하고 별칭 import(`from beautyads import llm as m`)를 놓친다.
- `AGENTS.md`, `pyproject.toml`, `src/` 아래 파일을 만들거나 고치지 마라. 표가 이 파일의 상수와 다르면 상수를 표에 맞추고, 표 자체가 틀렸다고 판단되면 고치지 말고 `blocked`로 보고한다. 이유: 계층 표의 원본은 AGENTS.md이고 수정 허용 경로 밖이다.
- 위반 결과를 개수(`len(...) == 3`)로 단언하지 마라. `(file, target, rule)` 집합으로 단언한다. 이유: 이후 step이 규칙을 늘려도 이 테스트가 깨지지 않게 한다(B-FP-061).
