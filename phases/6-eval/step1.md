# Step 1: step-scope-check

## 설계 검토 기록

이 phase(P6)는 설계 검토 3종(식별자 전수 대조, 상수 단언 grep, 새 칸 대응표)을 step마다 요구한다. 이 step은 그 점검을 사람이 손으로 하지 않도록 **경고만 출력하는 읽기 전용 점검 도구**를 만든다. 이후 모든 step 파일을 쓸 때 이 도구로 허용 파일과 본문의 충돌을 점검한다(조언 세션 승인 2026-11-19).

- 식별자 대조(bb0e64f 기준): `scripts/step_file_checks.py`의 `section`·`machine_lines`·`paths_in`·`is_inside`·`consumer_warnings`·`ROOT` 재사용, `scripts/test_step_files.py`의 import 방식(스크립트 폴더를 `sys.path`에 넣어 import) 참고. `scripts/execute.py`·`scripts/test_step_files.py`·`scripts/exempt_paths.json`은 **읽기 전용**(하네스 차단 로직 불변).
- 상수 단언 grep: 이 step이 다루는 상수 없음(`MAX_PER_PATH`는 `step_file_checks.py` 내부 값이며 불변).
- 새 칸 대응표: 새 칸 없음. 이 도구는 어떤 파일도 쓰지 않는다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL 규칙, `make verify`만이 검증 진입점
- `/scripts/step_file_checks.py`(읽기 전용: `section`·`machine_lines`·`paths_in`·`is_inside`·`consumer_warnings`·`ROOT`·`SCOPE_LINE`), `/scripts/test_step_files.py`(읽기 전용: 스크립트 import 방식), `/scripts/README.md`(도구 목록 형식)
- `/.claude/commands/harness.md`(설계 원칙 9·10·13의 점검 항목)
- `/.claude/skills/failure-patterns/SKILL.md`(FP-C11·B-FP-060·071: 소비자 테스트 누락)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `scripts/step_scope_check.py`(새 파일), `tests/test_step_scope_check.py`(새 파일), `scripts/README.md`(도구 한 줄 추가에 한함)

열람 금지 경로: `data/interim/`
수정 허용 경로: `scripts/step_scope_check.py`, `tests/test_step_scope_check.py`, `scripts/README.md`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로, 평가 정답을 읽는 채점 함수)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

step 파일 하나를 읽어 허용 범위와 본문의 충돌 의심을 **경고 문장**으로 출력하는 표준 라이브러리 전용 스크립트를 만든다. 하네스(`execute.py`)·`step_file_checks.py`·`make verify`에 연결하지 않는다.

**인터페이스(`scripts/step_scope_check.py`)**
- `check_step(text: str, root: Path = ROOT) -> list[str]`: 아래 다섯 점검의 경고 문장을 모아 돌려준다(순서 고정, 같은 입력이면 같은 출력).
- `main(argv: list[str] | None = None, *, out=sys.stdout) -> int`: `python scripts/step_scope_check.py phases/6-eval/step*.md [--root DIR]`. 각 파일마다 `경고 <파일>: <문장>` 줄을 출력하고 마지막에 파일별 경고 건수를 출력한다. **경고가 있어도 종료 코드는 0**이다. 파일을 못 읽거나 인자가 없으면 2.
- `step_file_checks`는 같은 폴더에서 `sys.path`에 `scripts`를 넣어 import한다(`scripts/test_step_files.py`의 방식). 그 파일의 함수는 읽기만 하고 고치지 않는다.

**다섯 점검**
1. 경로: `## 작업`과 `## 설계 검토 기록` 절의 백틱 경로(`step_file_checks.paths_in`) 중 `수정 허용 경로` 줄에 없는데 `root` 아래에 **존재하지 않는** 경로(새 파일이 허용 줄에 빠짐)와, 존재하는데 `**수정할 파일**` 문단에서 수정 대상으로 읽히지만 허용 줄에 없는 경로.
2. 좌표: `경로:줄`, `경로:줄-줄`, `경로:줄·줄` 꼴(예: `src/x.py:12`, `tests/y.py:31·53`)의 파일이 없거나 줄 번호가 파일 줄 수를 넘으면 경고. 같은 불릿 안에 뒤따르는 백틱 식별자가 있으면 그 식별자가 좌표 줄의 앞뒤 15줄 안에 나타나는지 확인하고 아니면 "좌표 불일치" 경고.
3. 식별자: 백틱 안 파이썬 식별자(밑줄이 있는 snake_case, CamelCase, 전부 대문자)가 `root`의 `src/`·`tests/`·`scripts/`에 단어로 한 번도 안 나오면 경고. 새로 만드는 식별자는 `## 작업`의 `새 식별자:` 줄(백틱 쉼표 나열)에 적으면 제외한다.
4. 상수 단언: 전부 대문자 식별자 중 `src/`의 모듈 수준 대입으로 정의된 것을 `tests/`에서 `assert`·`==`·`<=`·`>=`·`Fraction`과 같은 줄에 쓰는 곳을 `파일:줄` 목록으로 모아, 그 테스트 파일이 `수정 허용 경로`에 없으면 "상수 단언 N곳(허용 목록 밖: …)" 경고(정보 제공용, 건수 12개까지 나열).
5. 소비자 테스트: `step_file_checks.consumer_warnings(text, root)`의 경고를 그대로 포함한다.

**테스트(`tests/test_step_scope_check.py`)**: 합성 저장소 트리(`tmp_path`에 `src/`·`tests/`·`scripts/` 파일을 만든다)와 합성 step 문장만 쓴다. 각 점검에 대해 (a) 경고가 나는 입력, (b) 경고가 없는 입력, (c) `새 식별자:` 줄로 제외되는 입력을 검사한다. `main`의 종료 코드가 경고가 있어도 0이고 인자 없음이 2임, 출력이 입력 순서에 독립적으로 결정적임, 이 모듈이 `subprocess`·`socket`·`open(..., "w")`·`write_text`를 쓰지 않음(AST 검사)을 단언한다. 실제 `phases/`·`docs/` 내용은 읽지 않는다.

`scripts/README.md`에는 도구 한 줄(이름, 용도, "경고만, 읽기 전용, 하네스 비연결")만 추가한다.

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

- `scripts/step_file_checks.py`·`scripts/execute.py`·`scripts/test_step_files.py`·`scripts/exempt_paths.json`·`Makefile`을 고치거나 새 도구를 `make verify`·`execute.py`에 연결하지 마라. 이유: 하네스 차단 로직은 불변이다(조언 세션 승인). 이 도구는 설계자가 쓰는 경고 도구다.
- 점검 결과가 있어도 종료 코드를 0 이외로 만들거나 파일을 쓰지 마라. 이유: 경고만 출력하는 읽기 전용 도구다. 쓰기·네트워크·서브프로세스가 생기면 step 파일 작성 흐름이 위험해진다.
- 표준 라이브러리 밖 패키지를 추가하지 마라. 이유: 이 도구는 `uv add` 없이 어디서나 돌아야 한다(AGENTS.md 의존성 규칙).
- 테스트가 실제 `phases/`·`docs/`·`src/` 내용을 읽게 하지 마라. 이유: 저장소 내용에 따라 결과가 바뀌는 테스트가 된다(B-FP-076). 합성 트리만 쓴다.
