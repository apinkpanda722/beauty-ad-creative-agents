# Step 2: evalset-freeze-guard

## 설계 검토 기록

**식별자 전수 대조(bb0e64f)**: `eval/p5_compare.py:90 preregistration_committed(path=PREREG_PATH, *, run=subprocess.run)`는 이미 경로를 인자로 받는다(P5 테스트 `tests/test_p5_compare.py:140-200`은 `compare.PREREG_PATH`와 이 함수를 쓴다). **이 파일은 고치지 않고 import만 한다.** 이 함수는 `git log -1 -- <path>`가 비어 있지 않고 `git status --porcelain -- <path>`가 비어 있을 때만 참이므로 "HEAD 이력에 포함되고 작업 트리·스테이징·미추적 변경이 없음"을 이미 본다. 파일이 이후 커밋에서 삭제된 경우(log 있음, status 깨끗, 파일 없음)는 보지 못하므로 `freeze_guard`가 파일 존재를 따로 확인한다. `domain/supervisor.py:20 MIN_DOMINANT_SHARE`·`:21 THIN_POOL_MAX`, `domain/evaluation.py:10 PASS_MIN_SCORE`, `agents/planning.py:17 PLANNING_PROMPT_VERSION`·`:19 _SYSTEM`, `agents/evaluation.py:14 EVALUATION_PROMPT_VERSION`·`:33 _SYSTEM`, `sources/workspaces.py:16 group: Literal["dev","test"]`, `eval/agents_live.py:420`(`w.group == "dev"`로 dev 작업 공간 집합), `api/assembly.py:138`(`group not in {"dev","test"}` 거부)·`:168`(`workspace.group != group` 필터).

**상수 단언 grep(파생 표현식·좌표 포함)**: `tests/test_domain_evaluation.py:33`(`PASS_MIN_SCORE == 3`)·`:37`(소스 줄 `PASS_MIN_SCORE =` 직접 검사), `tests/test_evaluation.py:223`(`"2026-11-18-2"` 리터럴), `tests/test_supervisor.py:498-543`(버전을 import해 비교하는 파생 표현식)·`:554`, `tests/test_domain_supervisor.py:260-281`(`Fraction(str(MIN_DOMINANT_SHARE))` 경계, `context["min_dominant_share"] == MIN_DOMINANT_SHARE`)·`:293-295`(`THIN_POOL_MAX + delta`)·`:318-336`. 이 step은 이 상수·테스트를 **바꾸지 않는다**. 기획 프롬프트 버전 문자열(`"2026-11-18-3"`)은 리터럴 단언이 없으므로 이 step의 동결 값 점검이 처음으로 고정한다.

**새 칸 대응표**: 세트 항목 `split`·`axes_used`·`reviewed`(만드는 쪽: step 3 후보 생성기와 사용자 편집 → 읽는 쪽: 이 step의 검증기, step 5 보조 분석, step 7·8 실행기), 세트 해시(이 step의 해시 함수 → step 10 사전 등록 문서 → 이 step의 가드 → step 7·8·9 실행기), 사전 등록 문서 줄 형식 상수(이 step의 `freeze_guard` → step 10 생성기가 import, 이 step의 파서), 동결 값 줄(코드 값 → step 10이 문서에 씀 → 이 step의 가드가 대조).

**E1 사용 방침(조언 세션)**: 미충족 7축(`hook_type`·`angle`·`talent`·`has_proof_segment`·`is_vertical`·`has_text_overlay`·`cta_type`)과 `claims`는 "라벨 신뢰도 낮음"으로 표시하고 결론 근거로 쓰지 않는다. κ 값은 `docs/results/2026-11-19-e1-scoring.md`에서 그대로 읽으며 코드에 κ 숫자를 적지 않는다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계(`eval`은 다른 계층을 import할 수 있다), CRITICAL: 동결 기준은 결과를 본 뒤 바꾸지 않는다, 사전 등록 파일을 먼저 커밋
- `/docs/EVAL.md`(읽기 전용: 동결 기준), `/docs/results/e1_preregistration.md`·`/docs/results/2026-11-19-e1-scoring.md`(읽기 전용: 충족·미충족 축 표), `/docs/results/p5_dev_compare_preregistration.md`(읽기 전용: 사전 등록 문서의 형식 선례)
- `/src/beautyads/eval/p5_compare.py`(읽기 전용: `preregistration_committed`·`_commit_hash`·`PREREG_PATH`), `/tests/test_p5_compare.py`(읽기 전용: 가짜 `run` 방식)
- `/src/beautyads/sources/workspaces.py`(`Workspace`·`load_workspaces`), `/config/workspaces.yaml`, `/src/beautyads/eval/agents_live.py`(읽기 전용: dev 작업 공간 집합과 `WORKSPACE_GROUP_INVALID` 사용 방식), `/src/beautyads/domain/supervisor.py`·`/src/beautyads/domain/evaluation.py`·`/src/beautyads/agents/planning.py`·`/src/beautyads/agents/evaluation.py`(읽기 전용: 동결 값)
- `/src/beautyads/domain/labels.py`(`Category`·`Claim` 등 닫힌 값), `/src/beautyads/domain/supervisor.py`의 `pattern_context`(축 이름), `/tests/test_architecture.py`(`importlib.import_module` 사용 금지 포함)
- `/docs/COMPETENCY_QUESTIONS.md`(CQ 번호는 문서 표가 정본)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/evalset.py`(새 파일), `src/beautyads/eval/freeze_guard.py`(새 파일), `tests/test_evalset.py`(새 파일), `tests/test_freeze_guard.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/evalset.py`, `src/beautyads/eval/freeze_guard.py`, `tests/test_evalset.py`, `tests/test_freeze_guard.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로, 평가 정답을 읽는 채점 함수)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

평가셋 형식·해시와 "test 실행 코드 가드"를 만든다. 모델·그래프·DB·네트워크에 접속하지 않는다. **테스트를 먼저 쓴다.**

새 식별자: `AXIS_NAMES`, `E1_RELIABLE_AXES`, `E1_UNMET_AXES`, `RequestItem`, `QuestionItem`, `AnswerItem`, `EvalsetError`, `request_set_hash`, `question_set_hash`, `stratum`, `validate_set`, `FreezeError`, `check_run`, `RunIdentity`, `run_identity`, `parse_preregistration`

**`eval/evalset.py`**
- 경로 상수: 후보 `data/interim/evalset/`(커밋하지 않음, 이 step은 다루지 않는다), 확정본 `EVALSET_DIR = Path("data/evalset")`의 `requests.jsonl`·`questions.jsonl`·`answers.jsonl`(커밋 대상). **정답 파일은 질문 파일과 분리**한다(B-FP-042).
- 축 이름 닫힌 목록 `AXIS_NAMES`(튜플): `category`·`content_type`·`hook_type`·`angle`·`format`·`talent`·`has_demo_segment`·`has_proof_segment`·`has_cta`·`is_vertical`·`has_text_overlay`·`has_voice`·`has_music_only`·`has_subtitles`·`cta_type`·`claims`·`graph_structure`(그래프 구조만 쓰는 질의 표시). `E1_RELIABLE_AXES`(frozenset): `category`·`content_type`·`format`·`has_demo_segment`·`has_cta`·`has_voice`·`has_music_only`·`has_subtitles`·`graph_structure`. `E1_UNMET_AXES`(frozenset): `hook_type`·`angle`·`talent`·`has_proof_segment`·`is_vertical`·`has_text_overlay`·`cta_type`·`claims`. 두 집합은 서로소이고 합이 `AXIS_NAMES`와 같다(테스트).
- `stratum(axes_used) -> str`: `axes_used`가 비어 있거나 전부 `E1_RELIABLE_AXES`면 `"reliable"`, 하나라도 `E1_UNMET_AXES`면 `"unreliable"`. `AXIS_NAMES` 밖의 값은 `EvalsetError("AXIS_UNKNOWN")`.
- 항목 모델(pydantic, `extra="forbid"`, `frozen=True`):
  - `RequestItem`: `id`(예 `req-dev-01`), `split`(`dev`|`test`), `tenant_id`, `message`(비어 있지 않고 2000자 이하), `source_cq`(예 `CQ-06`), `axes_used: list[str]`, `needs_human_review: bool`, `reviewed: bool`.
  - `QuestionItem`: `id`, `split`, `kind`(`graph`|`simple_search`), `tenant_id`(도구 실행 컨텍스트용, 같은 split의 작업 공간), `text`, `source_cq`, `cq_inputs: dict[str, str]`(질의 입력 닫힌 값), `answer_type`(`count`|`set`), `axes_used`, `needs_human_review`, `reviewed`.
  - `AnswerItem`: `question_id`, `answer_type`, `value`(`count`면 정수, `set`이면 문자열 목록), `tolerance_abs: float`(기본 0.0, `count`에만 의미), `evidence_ids: list[str]`(정답을 만든 소재 ID), `confirmed: bool`. `axes_used`는 **코드가 정한 값이며 모델이 정하지 않는다**.
- `read_jsonl(path) -> list[dict]`, `write_jsonl(path, rows)`(정렬·`ensure_ascii=False`·한 줄 한 항목), 정규형 `canonical(item) -> str`(키 정렬 JSON, 구분자 `(",", ":")`).
- 해시: `request_set_hash(items) -> str`는 `id` 오름차순 정규형을 `"\n"`으로 이은 문자열의 sha256 16진 소문자. `question_set_hash(questions, answers) -> str`는 질문 정규형 묶음 + 구분 줄 `"--answers--"` + `question_id` 오름차순 정답 정규형 묶음의 sha256(정답이 바뀌면 해시가 바뀐다). 항목 순서를 바꿔도 해시가 같다.
- 검증 `validate_set(requests, questions, answers, *, final: bool, workspaces_path=Path("config/workspaces.yaml"))`: 항상 (a) id 유일, (b) 요청 `tenant_id`가 `load_workspaces`에 있고 `split`과 그 작업 공간의 `group`이 같다(dev 요청은 `dev-*`만, test 요청은 `test-*`만), (c) `axes_used ⊂ AXIS_NAMES`, (d) 질문마다 정답이 있고 `answer_type`이 같다. `final=True`이면 추가로 요청 dev 10·test 20, 질문 dev 10·test 40, test 질문 중 `simple_search` 10, 모든 항목 `reviewed`가 참이고 `needs_human_review`가 거짓, 정답 `confirmed`가 참이다. 위반은 고정 코드(`EVALSET_COUNT_INVALID`·`EVALSET_SPLIT_INVALID`·`EVALSET_NOT_REVIEWED` 등)의 `EvalsetError`로만 낸다(항목 본문·키는 메시지에 넣지 않는다).

**`eval/freeze_guard.py`**
- 상수 `PREREG_PATH = Path("docs/results/p6_preregistration.md")`와 사전 등록 문서의 **줄 형식**(step 10 생성기가 같은 상수를 import한다): 줄 하나는 `"{라벨}: {값}"`. 라벨 상수: `REQUEST_HASH_LABEL = "세트 해시 요청"`, `QUESTION_HASH_LABEL = "세트 해시 질문"`, 동결 값 라벨 `동결 기획 프롬프트 버전`·`동결 평가 프롬프트 버전`·`동결 MIN_DOMINANT_SHARE`·`동결 THIN_POOL_MAX`·`동결 PASS_MIN_SCORE`·`동결 기획 _SYSTEM sha256`·`동결 평가 _SYSTEM sha256`.
- `frozen_values() -> dict[str, str]`: 코드의 현재 값을 문자열로 돌려준다. 버전은 `PLANNING_PROMPT_VERSION`·`EVALUATION_PROMPT_VERSION`, 상수는 `repr`가 아니라 `str`(`0.4`·`10`·`3`), `_SYSTEM` sha256은 `agents.planning._SYSTEM`·`agents.evaluation._SYSTEM`의 UTF-8 sha256 16진 소문자(모듈 속성 접근, `importlib.import_module` 금지).
- `parse_preregistration(text) -> dict[str, str]`: 문서에서 `"{라벨}: {값}"` 줄을 읽는다(앞뒤 공백 제거, 같은 라벨이 두 번이면 `FreezeError("FROZEN_VALUE_MISMATCH")`).
- `class FreezeError(Exception)`: `.code`만 갖는다. 코드는 `PREREG_NOT_COMMITTED`·`EVALSET_HASH_MISMATCH`·`FROZEN_VALUE_MISMATCH`와, dev 실행기용 기존 코드 `WORKSPACE_GROUP_INVALID`뿐이다.
- `check_run(*, mode, groups, requests_path=..., questions_path=..., answers_path=..., extra=None, prereg_path=PREREG_PATH, committed_fn=preregistration_committed, run=subprocess.run, workspaces_path=...) -> RunIdentity`:
  - `mode="dev"`: `groups`에 `"test"`가 있으면 `FreezeError("WORKSPACE_GROUP_INVALID")`. 그 밖에는 통과(사전 등록 없이 개발 반복 가능).
  - `mode="final"`(test 작업 공간이나 test split을 쓰는 실행, **격리 최종 실행도 같다**): 순서대로 (1) `committed_fn(prereg_path)`가 거짓이거나 파일이 없거나 읽을 수 없으면 `PREREG_NOT_COMMITTED`(문서가 수정된 채면 `committed_fn`이 거짓), (2) 확정 세트를 읽어 `validate_set(final=True)`를 통과시킨 뒤 요청·질문 해시를 계산해 문서 줄과 다르면(줄이 없어도) `EVALSET_HASH_MISMATCH`, (3) `frozen_values()`와 `extra`(호출한 실행기가 가진 추가 동결 값, 라벨→값)가 문서 줄과 다르면(줄이 없어도) `FROZEN_VALUE_MISMATCH`, (4) `src/`·`config/`·`data/evalset/` 아래 작업 트리 변경이 있으면(`git status --porcelain -- src config data/evalset`가 비어 있지 않음) `FROZEN_VALUE_MISMATCH`(동결 코드와 다른 실행). 오류 문장에 값·본문·키를 넣지 않는다.
  - `RunIdentity`: `code_commit`(`git rev-parse HEAD`), `prereg_commit`(`git log -1 --format=%H -- <prereg_path>`), `request_hash`·`question_hash`. dev 모드는 해시가 `None`이다. 두 커밋 해시는 결과 문서에 적는다(조언 세션 결정). git 호출은 `run` 주입으로만 하고 `eval` 계층 읽기 전용 점검으로 한정한다.

**테스트**
- `tests/test_evalset.py`: 합성 항목(`tmp_path`의 합성 작업 공간 YAML)으로 해시의 순서 독립성·정답 변경 시 질문 해시 변화·요청 해시 불변, `validate_set`의 각 위반 코드, `stratum` 경계(빈 목록·충족만·미충족 하나), 축 집합이 서로소이고 `AXIS_NAMES`를 이룸. **E1 문서 대조**: `docs/results/2026-11-19-e1-scoring.md`의 §2 표를 읽어 `미충족`으로 적힌 축(14축 중 `claims` 제외)이 `E1_UNMET_AXES - {"claims"}`와 같고 `충족`으로 적힌 축이 `E1_RELIABLE_AXES`의 부분집합임을 단언한다(표 행 형식은 `| 축 | n | 일치율 | κ | 충족 |`, 굵은 표기·괄호 제거 후 비교; 표를 못 찾으면 실패, 검사한 행 수 0은 실패).
- `tests/test_freeze_guard.py`: 가짜 `committed_fn`·가짜 `run`·`tmp_path`의 가짜 사전 등록 문서로만 한다(step 10의 문서에 의존하지 않는다). 사례: 커밋 안 됨→`PREREG_NOT_COMMITTED`, **커밋됐지만 수정됨**(`status`가 비어 있지 않음)→`PREREG_NOT_COMMITTED`, 문서 파일 없음→`PREREG_NOT_COMMITTED`, 요청·질문 해시 불일치·줄 누락→`EVALSET_HASH_MISMATCH`, 버전·상수·`_SYSTEM` sha256·`extra` 불일치·줄 누락→`FROZEN_VALUE_MISMATCH`, `src` 변경→`FROZEN_VALUE_MISMATCH`, 모두 일치→`RunIdentity` 반환, dev 모드는 `groups={"test"}`에서 `WORKSPACE_GROUP_INVALID`이고 `{"dev"}`에서 통과. 오류 문장에 합성 값(`SENTINEL_…`)이 들어 있지 않음. 오류 코드 집합이 위 네 개와 정확히 같음. 모든 사례에서 검사한 가드 호출 수 0은 실패.
- **소비 테스트**: `check_run`이 `p5_compare.preregistration_committed`를 기본값으로 쓰고 P5 함수 객체가 그대로 `committed_fn` 기본값임을 단언한다(P5 파일 불변 확인).

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

- `eval/p5_compare.py`와 `tests/test_p5_compare.py`를 고치지 마라. 이유: 함수는 이미 경로를 인자로 받고 P5 테스트가 `PREREG_PATH`를 쓴다. import만 한다(조언 세션 결정).
- 동결 값(프롬프트 버전, `MIN_DOMINANT_SHARE`, `THIN_POOL_MAX`, `PASS_MIN_SCORE`)이나 프롬프트 문자열을 바꾸거나 테스트에 새 리터럴로 굳히지 마라. 이유: 값은 사전 등록 문서와 `frozen_values()`가 대조하며 개발 중 바꿀 수 있다. 동결은 11-26 커밋 때 일어난다(B-FP-043).
- κ 숫자나 모델이 만든 문장을 코드·테스트 기대값에 넣지 마라. 이유: 축 충족 여부는 E1 결과 문서 표에서 읽어 대조한다. 모델 값을 테스트로 굳히면 안 된다(FP-C03).
- `importlib.import_module`·`__import__`를 쓰거나 가드 오류에 값·본문·키를 싣지 마라. 이유: `tests/test_architecture.py`가 동적 import를 막고, 오류는 고정 코드로만 낸다(AGENTS.md 비밀 규칙).
- 검사한 항목이 0건인 가드 테스트를 통과로 두지 마라. 이유: 빈 집합에 대한 `all()`은 통과로 보이지만 아무것도 검사하지 않는다(B-FP-069).
