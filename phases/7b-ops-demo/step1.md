# Step 1: ci-verify

## 설계 검토 기록

**배경(P7 설계 승인, 7b)**: `AGENTS.md`는 "`make verify`는 Stop hook, execute.py, CI가 모두 부른다"고 적고 있지만 이 저장소에는 `.github/`가 없어 CI가 한 번도 돈 적이 없다(2026-11-20 확인). 이 step은 `make verify`를 부르는 최소 워크플로를 만든다. **서비스(PostgreSQL·Neo4j)와 키가 없는 환경에서 통과하는지**를 먼저 확인했고 아래 결과가 있다.

**실측 결과(2026-11-20, 읽기 전용 확인)**: 저장소를 클론한 깨끗한 디렉터리에서 키 환경 변수를 모두 지우고 `make verify`를 돌리면 **6,093건 통과·1건 실패(65초, 이 맥, xdist)**였다. 실패 테스트는 `tests/test_products_pipeline.py::test_model_contract_cost_summary_and_bytes_never_written`(`assert report["cost_by_purpose"]["product-detail"]["calls"] == 1`이 0). 같은 클론에서 `GEMINI_API_KEY=fake`만 주면 통과한다 → `extract_product_detail`이 `llm/gemini.py` 175행 `require_setting("GEMINI_API_KEY")`로 키를 읽는데 테스트가 키를 주입하지 않아 **원 저장소에서는 `.env`·환경의 실제 키 덕에 통과하고 있었다**(AGENTS.md "키 없이 통과" 위반). 클린 실행 중에도 로컬 PostgreSQL·Neo4j가 켜져 있었으므로 서비스 독립은 따로 확인했다: **7a 완료 상태(`a755152`)의 클린 클론에서 `.env` 없이·키 환경 변수 없이·`sandbox-exec -p '(version 1)(allow default)(deny network*)'`로 루프백을 포함한 모든 네트워크를 막고 `make verify`의 파이썬 부분을 돌리면 6,216건 통과·1건 실패(같은 키 의존 테스트 한 건뿐, 63.6초)**였고, 같은 조건에서 웹 `pnpm lint`·`typecheck`·`test`는 125건 통과했다(2026-11-20, 의존성 설치는 네트워크 허용 상태에서 먼저 했다). 즉 **걸리는 테스트는 이 한 건뿐**이다(서비스 접속 시도로 실패하는 테스트 없음). 이 확인은 작업자가 했고 Codex는 실행하지 않는다. 실제 GitHub 러너에서의 통과는 **미확인**이다.

**수정 방침(승인)**: 테스트가 `monkeypatch.setenv("GEMINI_API_KEY", "fake-key")`로 키를 고정한다. **워크플로에 더미 키를 넣지 않는다.**

**외부 액션 버전(2026-11-20 `gh api`로 조회, 커밋 SHA로 고정)**:

| 액션 | 태그 | 커밋 SHA |
|---|---|---|
| `actions/checkout` | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `astral-sh/setup-uv` | v10.3.3 | `68559e99cc807c1eb7e9238fd43a15bba460eec2` |
| `actions/setup-node` | v7.1.0 | `949feb2413d6458794dcd2491c4babbbce0c15c1` |
| `pnpm/action-setup` | v6.1.1 | `73e46992e05b19abd31f2f3c20e0e7370d762115` |

`uses:` 줄은 `owner/repo@<커밋 SHA> # <태그>` 형식이다.

**런타임 요구**: 파이썬은 `.python-version`(3.12)과 `pyproject.toml`의 `python-preference = "only-managed"`에 따라 uv가 관리 파이썬을 받는다. node는 `jsdom@31.0.1`이 `^22.22.2 || ^24.15.0 || >=26`을 요구하므로 `actions/setup-node`에 **`node-version: "24"`**를 쓴다(이 맥은 v26.4.0). pnpm은 `web/package.json`의 `"packageManager": "pnpm@12.8.1"`을 `pnpm/action-setup`이 읽게 한다(`package_json_file: web/package.json`). 웹 의존성 버전 조합은 step 4(7a)에서 확정됐다: typescript 6.0.3, eslint 9.39.5, vite 7.3.8.

**기존 단언과의 충돌 점검**: `tests/test_products_pipeline.py`에서 위 테스트 **한 개만** `monkeypatch`를 받아 환경 변수를 설정하도록 갱신한다(다른 테스트·다른 단언 불변, 약화 금지). 새 `tests/test_ci_workflow.py`는 `.github/workflows/verify.yml`을 읽는 새 파일이다(소비자 없음).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`(CRITICAL: `make verify`는 키·네트워크·실제 서비스 없이 통과, 명령어 절), `/Makefile`(`verify`·`web-install`), `/pyproject.toml`, `/.python-version`, `/web/package.json`
- `/tests/test_products_pipeline.py`(`test_model_contract_cost_summary_and_bytes_never_written`와 `deps()` 헬퍼), `/src/beautyads/llm/gemini.py`(175행 부근), `/src/beautyads/analysis/product_detail.py`
- `/tests/test_compose.py`(`recipe()` 헬퍼, YAML을 읽는 방식 참고)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `.github/workflows/verify.yml`, `tests/test_products_pipeline.py`, `tests/test_ci_workflow.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `.github/workflows/verify.yml`, `tests/test_products_pipeline.py`, `tests/test_ci_workflow.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1. `tests/test_products_pipeline.py`**: `test_model_contract_cost_summary_and_bytes_never_written`가 `monkeypatch`(pytest 내장 픽스처)를 인자로 받아 시작할 때 `monkeypatch.setenv("GEMINI_API_KEY", "fake-key")`를 호출한다. 그 밖의 줄은 바꾸지 않는다. 이 테스트를 `.env` 없이·키 환경 변수 없이 단독 실행해 통과함을 확인한다(`env -u GEMINI_API_KEY`로 실행해도 통과해야 한다, 이 확인은 최종 응답에 적는다).

**2. `.github/workflows/verify.yml`(새)**:
- 이름 `verify`. 트리거 `push`(모든 브랜치)와 `pull_request`. `permissions: contents: read`. 작업 하나(`verify`)에 `runs-on: ubuntu-latest`, `timeout-minutes: 20`, `concurrency`(같은 ref의 이전 실행 취소).
- 단계: `actions/checkout` → `astral-sh/setup-uv`(캐시 사용) → `uv sync --locked` → `pnpm/action-setup` → `actions/setup-node`(`node-version: "24"`, pnpm 캐시, 캐시 의존 경로 `web/pnpm-lock.yaml`) → `make web-install` → `make verify`.
- **`env:`·`secrets.`를 쓰지 않는다**(키 없이 통과해야 한다). 서비스 컨테이너(`services:`)를 쓰지 않는다. 외부 액션은 위 표의 커밋 SHA로만 고정한다.

**3. `tests/test_ci_workflow.py`(새, 합성 입력 없음, `.github/workflows/verify.yml`만 읽는다)**: (1) `yaml.safe_load`로 읽혀 `jobs.verify`가 있다. (2) 모든 `uses:`가 `@<40자리 16진 SHA>` 형식이고 위 표의 액션 네 개가 모두 있다(검사한 `uses` 수가 0이면 실패, B-FP-069). (3) 단계 순서에서 `make web-install`이 `make verify`보다 앞에 있고 `uv sync --locked`가 있다. (4) 워크플로 어디에도 `secrets`·`env`·`services` 키가 없다. (5) `node-version`이 `"24"`이고 `web/package.json`의 `packageManager`가 `pnpm@12.8.1`이다. (6) `timeout-minutes`가 있다(B-FP-066).

## Acceptance Criteria

```bash
make verify   # ruff + pytest + pnpm lint·typecheck·test 통과
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - AGENTS.md CRITICAL 규칙을 위반하지 않았는가?
3. 결과를 최종 응답(JSON)으로 보고한다. `phases/` 아래 파일은 수정하지 않고 git commit도 하지 않는다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약(설치한 패키지 버전 포함, 승인 목록에서 조정한 것은 이유까지)"`
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

- 워크플로에 더미 API 키·`env:`·`secrets`를 넣지 마라. 서비스 컨테이너를 추가하지 마라. 이유: `make verify`는 키·서비스 없이 통과해야 하고(AGENTS.md CRITICAL), 더미 키로 가리면 키 의존 결함을 숨긴다. 키 의존은 테스트 쪽에서 고친다.
- 액션을 태그나 `@main`·`@v7`로 고정하지 마라(위 표의 커밋 SHA만). 이유: 태그는 움직일 수 있어 공급망 위험이다(승인: 조회한 버전으로 고정).
- `test_products_pipeline.py`의 다른 테스트·단언을 바꾸거나 `monkeypatch`를 모듈 전체 픽스처로 넓히지 마라. `src/`·`Makefile`·`pyproject.toml`·`web/`을 수정하지 마라. 이유: 결함 하나(키 의존)만 고치고 가드를 약화하지 않는다(B-FP-060). 소비자 점검: 이 테스트 파일을 읽는 다른 테스트는 없다.
- GitHub에 접속하거나 워크플로를 실행하려고 시도하지 마라(푸시·`gh workflow run` 포함). 이유: 실제 서비스 접속은 사용자가 한다(A-FP-040). 워크플로는 정적 테스트(`tests/test_ci_workflow.py`)로만 검증한다.
- CI가 로컬에서 통과한다는 사실만으로 "CI 통과"를 보고하지 마라. 최종 응답에는 "워크플로 구조 검증 통과, 실제 러너 실행은 미확인"이라고 적어라. 이유: 로컬 통과가 CI 통과를 보장하지 않는다(B-FP-032).
