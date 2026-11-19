# Step 11: dev-split

## 설계 검토 기록

**배경(조언 세션 승인)**: `finalize`는 요청 dev 10·test 20, 질문 dev 10·test 40을 한꺼번에 확정해야 파일을 쓰고(`validate_set(final=True)`), `e3_live`는 dev에서도 `data/evalset/`를 읽으며 CLI에 경로 옵션이 없다. 그래서 dev 항목(요청 10·질문 10)만 먼저 확정해 임베딩 측정(step 8 `measure`)과 dev 스모크(step 7)를 할 수 없다. 이 step은 dev만 따로 확정하는 경로를 만든다. **`data/evalset/`(최종 확정 세트와 사전 등록 대상)는 건드리지 않는다.** 대안인 dev·test 동시 검수는 하지 않는다.

**식별자 전수 대조(현재 코드)**: `eval/evalset_candidates.py`(`CANDIDATE_DIR`·`REVIEW_COLUMNS`·`ReviewedSet`(NamedTuple, `shortages` 속성)·`_shortages(requests, questions, targets)`·`_FINAL_TARGETS`(`requests_dev` 10·`requests_test` 20·`questions_dev` 10·`questions_test_graph` 30·`questions_test_simple_search` 10)·`review_rows`·`write_review_sheet`·`apply_review(candidates, sheet_rows)`(시트 전 행이 채워져 있지 않으면 `REVIEW_INCOMPLETE`)·`load_candidates`·`_verify_hashes`·`_finalize(candidate_dir, final_dir, *, dry_run, out)`·`main(argv, *, out, candidate_dir, final_dir, ...)`), `eval/evalset.py`(`RequestItem`·`QuestionItem`·`AnswerItem`·`validate_set(requests, questions, answers, *, final, workspaces_path)`·`request_set_hash`·`question_set_hash(questions, answers)`·`read_jsonl`·`write_jsonl`·`EvalsetError(code)`·`EVALSET_DIR`·`QUESTIONS_PATH`·`ANSWERS_PATH`), `eval/e3_live.py`(`main(argv, *, questions_path=QUESTIONS_PATH, answers_path=ANSWERS_PATH, output_dir, check_fn, ...)`·`read_answers(path, *, questions, split, purpose)`·`measure(...)`·`E3Error`·`ANSWER_SPLIT_FORBIDDEN`), `eval/freeze_guard.py`(`check_run`, 읽기 전용, 수정하지 않는다).

**상수 단언 grep**: `tests/test_evalset_candidates.py:365 test_sheet_columns_instructions_and_hash_guard`가 `review_instructions.md`에 "칸의 뜻"·"기준"·"예시"·"기록 방법"과 두 해시 문자열이 있음을 단언한다(기존 문장은 그대로 두고 **절만 추가**한다. 단언을 약화하지 않는다). `_FINAL_TARGETS`·`REVIEW_COLUMNS`는 값을 바꾸지 않는다. `tests/test_e3_live.py`의 `e3.main([...], **injected)` 호출(`:514-520`)은 기본 인자로 그대로 통과해야 한다(새 옵션은 모두 선택). `tests/test_schema_guard.py:480`이 `from test_e3_live import arm_options, question`으로 두 헬퍼(`:61`·`:21`)를 가져다 쓰므로 **이름·시그니처를 바꾸지 않는다**. `tests/test_prereg.py`는 `test_evalset.synthetic_set`·`workspaces_path`를 가져다 쓰므로 `tests/test_evalset.py`의 기존 헬퍼도 바꾸지 않는다.

**새 칸 대응표**: `DEV_SPLIT_DIR`(`data/interim/evalset/dev/`, 이 step `_finalize_dev` → 사용자의 dev 스모크 `e2e5_live --requests`와 임베딩 측정 `e3_live --questions/--answers`), `dev_request_hash`·`dev_question_hash`(`request_set_hash`·`question_set_hash`로 dev 부분집합 계산 → `finalize --split dev` 출력, 이후 전체 `finalize`의 비교 경고, `e3_live measure` 보고 `dev_question_hash`), 고정 오류 코드 `E3_PATH_OPTION_FORBIDDEN`(`e3_live.main` → 테스트), 경고 코드 `DEV_SPLIT_CHANGED`(전체 `finalize` → 출력 줄).

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건. 이 step은 파일과 `argparse`만 다룬다(실행은 사용자가 `make live-evalset ARGS="finalize --split dev"`).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 실제 호출은 사용자가 실행한다, 동결된 기준은 결과를 본 뒤 바꾸지 않는다
- `/src/beautyads/eval/evalset_candidates.py`(전체: `ReviewedSet`·`_shortages`·`apply_review`·`_finalize`·`main`·`write_review_sheet`의 지침 문자열), `/src/beautyads/eval/evalset.py`(`validate_set`·해시 함수·`read_jsonl`·`write_jsonl`)
- `/src/beautyads/eval/e3_live.py`(`main`·`read_answers`·`measure`의 보고 딕셔너리), `/src/beautyads/eval/freeze_guard.py`(읽기 전용: `check_run`이 dev에서 파일을 읽지 않음)
- `/tests/test_evalset_candidates.py`(`synthetic` 픽스처·`generate_files`·finalize 테스트 `:443-:576`), `/tests/test_e3_live.py`(`injected`·`:295`·`:353`·`:473-:520`), `/tests/test_evalset.py`
- `/src/beautyads/eval/e2e5_live.py`(읽기 전용: `--requests PATH`가 dev 요청 파일만 받는 규칙, 수정하지 않는다)
- `/Makefile`(읽기 전용: `live-evalset`·`live-e3`는 `$(ARGS)`를 그대로 넘기므로 수정하지 않는다)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/evalset_candidates.py`, `src/beautyads/eval/e3_live.py`, `tests/test_evalset_candidates.py`, `tests/test_e3_live.py`, `src/beautyads/eval/evalset.py`(필요할 때만, 해시 함수·상수 추가에 한함), `tests/test_evalset.py`(필요할 때만, 새 테스트 함수 추가에 한함)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/evalset_candidates.py`, `src/beautyads/eval/e3_live.py`, `tests/test_evalset_candidates.py`, `tests/test_e3_live.py`, `src/beautyads/eval/evalset.py`, `tests/test_evalset.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로 `data/interim/evalset/dev/`)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

평가셋 dev 항목(요청 10·질문 10)만 먼저 확정하는 `finalize --split dev`와 `e3_live`의 `--questions`·`--answers` 옵션을 만든다. **모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: `DEV_SPLIT_DIR`, `DEV_TARGETS`, `E3_PATH_OPTION_FORBIDDEN`, `DEV_SPLIT_CHANGED`

**1. `finalize --split dev`(`eval/evalset_candidates.py`)**
- `main`의 인자 파서에 `--split`(선택지 `dev` 하나뿐, 기본 없음)을 추가한다. `finalize`와 함께일 때만 의미가 있고 `generate`와 함께 쓰면 `ARGUMENT_ERROR`(기존 인자 오류 경로)다. `test`는 선택지에 없다(전체 확정만 test를 만든다).
- `DEV_SPLIT_DIR = CANDIDATE_DIR / "dev"`, `DEV_TARGETS = {"requests_dev": 10, "questions_dev": 10}`(`_FINAL_TARGETS`의 dev 값과 **같은 출처에서 만든다**: `_FINAL_TARGETS`에서 두 키를 뽑아 만들고 숫자를 다시 적지 않는다. 값 비교 테스트로 고정한다).
- `apply_review(candidates, sheet_rows, *, split=None)`: `split`이 주어지면 **그 split의 후보에 대한 시트 행만** 검사·적용한다. 다른 split 행은 비어 있어도·고쳐져 있어도 검사하지 않고 무시한다(단, `item_id`가 후보에 아예 없으면 기존처럼 `REVIEW_INVALID`). 그 split의 행이 하나라도 빠지면 `REVIEW_INCOMPLETE`다. `split=None`은 현재 동작과 같다(기존 테스트 통과).
- `_finalize_dev(candidate_dir, dev_dir, *, dry_run, out)`: 후보 파일 읽기 → `validate_set(..., final=False)`(후보 전체) → `_verify_hashes`(후보 전체, 기존과 같다) → 시트 읽기 → `apply_review(..., split="dev")` → 결과의 모든 항목이 `split == "dev"`임을 확인 → 부족 건수를 `DEV_TARGETS`로 `_shortages`와 같은 방식으로 계산한다. **부족하면 부족 건수 JSON을 출력하고 아무 파일도 쓰지 않고 종료 코드 3**(`_finalize`의 부족 경로와 같다). 부족이 없으면 `validate_set(요청, 질문, 정답, final=False)`(dev 항목끼리, 정답 집합 일치 검증 포함)를 통과시킨 뒤 `dev_dir`에 `requests.jsonl`·`questions.jsonl`·`answers.jsonl`을 `write_jsonl`로 쓴다. `dry_run`이면 접속·쓰기 없이 건수와 부족 건수만 출력한다.
- 출력은 개수·부족 건수·해시뿐이다: `{"requests": N, "questions": N, "shortages": {...}}`와 쓴 경우 `{"dev_request_hash": …, "dev_question_hash": …}`(`request_set_hash`·`question_set_hash(questions, answers)`). **test 항목의 문장·건수·내용은 출력·예외 메시지·로그에 나오지 않는다**(시트의 test 행은 읽어도 처리하지 않는다).
- **`data/evalset/`(`final_dir`)는 만들지도 쓰지도 않는다**(테스트가 `final_dir`이 만들어지지 않음을 확인한다).
- **전체 `finalize`(`--split` 없음)의 추가 동작**: `DEV_SPLIT_DIR`에 세 파일이 모두 있으면 읽어 dev 부분집합의 해시를 계산하고, 이번 전체 확정 결과에서 `split == "dev"`인 항목으로 같은 해시를 계산해 **다르면** 출력에 경고 줄 `DEV_SPLIT_CHANGED`(코드 문자열만)을 한 번 낸다. 경고는 종료 코드·파일 쓰기에 영향을 주지 않는다. 파일이 없거나 일부만 있으면 경고하지 않는다(읽기 오류도 조용히 넘기되 예외 문장을 싣지 않는다).
- **`review_instructions.md` 추가 절**("dev 먼저 확정", 기존 문장·해시 줄은 그대로, 해시 줄 앞에 절만 추가): dev 행만 먼저 기록하고 `finalize --split dev`로 dev만 확정하는 방법, dev 행은 **X로 제외하는 행도 포함해 모든 dev 행의 네 칸을 채워야** 하며(빈 칸 금지) test 행은 비워 둬도 된다는 점, dev만 확정해도 최종 사전 등록 세트는 아니라는 점(전체 확정은 test까지 끝낸 뒤 `finalize`)을 적는다.

**2. `e3_live`의 `--questions`·`--answers`(`eval/e3_live.py`)**
- `main`의 인자 파서에 `--questions PATH`·`--answers PATH`(`Path`, 기본 없음)를 추가한다. 함수 인자 `questions_path`·`answers_path`(기본 `QUESTIONS_PATH`·`ANSWERS_PATH`)는 그대로 두고, 옵션이 주어진 `dev` 모드에서만 그 값을 쓴다.
- **`--mode final`에서 둘 중 하나라도 주어지면** 가드(`check_fn`)·파일 읽기·런타임 생성 **이전에** 고정 오류 코드 `E3_PATH_OPTION_FORBIDDEN`(`{"code": "E3_PATH_OPTION_FORBIDDEN"}`)을 출력하고 종료 코드 1이다(`main`의 기존 오류 출력 형식).
- `measure` 보고(`measure`의 결과 딕셔너리, `measurement.json`)에 **사용한 dev 세트 해시** `dev_question_hash`를 싣는다: `measure`가 읽은 dev 질문과 `read_answers`가 돌려준 정답(`AnswerItem`)으로 `question_set_hash`를 계산한다(해시만 밖으로 나가고 정답은 임베딩·`chat` 입력에 넣지 않는다. 정답을 읽는 지점은 step 8의 "정답을 읽는 지점 표"와 같이 `check_run`·`measure`·`report` 셋뿐이며 이 해시 계산은 `measure` 안이다). `--dry-run`은 정답을 읽지 않으므로 해시를 내지 않는다.

**테스트(합성 데이터·`tmp_path`, 모델·접속 없음)**
- `tests/test_evalset_candidates.py`: (1) `finalize --split dev`가 dev만 채운 시트(test 행은 비워 둠)에서 dev 요청 10·질문 10으로 `DEV_SPLIT_DIR`에 세 파일을 쓰고 `final_dir`은 만들어지지 않는다. (2) dev 행이 하나 비면 `REVIEW_INCOMPLETE`, dev 부족(예: dev 요청 9건 채택)이면 부족 건수 출력·파일 없음·종료 코드 3. (3) test 행이 채워져 있어도·깨져 있어도 dev 확정에 영향이 없고 출력·예외에 test 문구(합성 표식 `SENTINEL_TEST_…`)가 없다. (4) `--split test`·`generate --split dev`는 `ARGUMENT_ERROR`. (5) 전체 `finalize`에서 dev 부분집합이 `DEV_SPLIT_DIR` 파일과 같으면 경고 없음, 다르면 `DEV_SPLIT_CHANGED` 한 줄(파일 쓰기·종료 코드 불변), 파일이 없으면 경고 없음. (6) `DEV_TARGETS`가 `_FINAL_TARGETS`의 dev 값과 같다(같은 출처 값 비교, 리터럴 10 금지). (7) `apply_review(split=None)`의 기존 동작이 그대로다(기존 테스트 통과). (8) 지침 문서에 "dev 먼저 확정" 절과 기존 문구·해시가 모두 있다.
- `tests/test_e3_live.py`: (9) `final`에서 `--questions`·`--answers` 각각 단독·함께 주어지면 `E3_PATH_OPTION_FORBIDDEN`이고 가짜 `check_fn`·`corpus_loader`·`runtime_factory`·파일 열기 호출이 0건이다. (10) **final은 `data/evalset/`만 읽는다**: 옵션 없는 final 실행에서 가짜 `check_fn`이 받은 `questions_path`·`answers_path`와 파일 열기 감시가 기본 상수(`QUESTIONS_PATH`·`ANSWERS_PATH`)뿐이다. (11) dev에서 옵션 경로(합성 `tmp_path`)를 읽고 기본 경로를 열지 않는다. (12) `measure` 결과의 `dev_question_hash`가 같은 합성 dev 질문·정답으로 `question_set_hash`를 직접 계산한 값과 같고, 같은 합성 세트로 `finalize --split dev`가 출력한 `dev_question_hash`와도 같다(두 모듈 값 일치). (13) 가짜 `embed`·`chat`·`structured`가 받은 입력에 정답·해시 문자열이 없다(`SENTINEL_…` 표식). (14) 기존 `e3.main([...], **injected)` 호출 테스트가 새 옵션 없이 그대로 통과한다.
- 합성 문장·분류 값을 기대값으로 굳히지 않는다(형식·건수·코드·해시 일치만 검사).

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

- `data/evalset/`를 만들거나 쓰는 코드를 넣거나 최종 확정 세트의 검증 기준(`validate_set(final=True)`의 건수 10/20/10/40/10)을 바꾸지 마라. 이유: dev 확정은 최종 세트와 별개이며, 최종 세트와 해시는 사전 등록 대상이다(AGENTS.md, 동결 기준).
- `finalize --split dev`가 test 항목의 문장·건수·내용을 출력·로그·예외 메시지·`dev` 출력 파일에 싣거나 `--split test`를 허용하지 마라. 이유: dev를 확정하는 동안 test 항목은 보지 않는다(평가셋 분리).
- `e3_live`의 final 모드에서 경로 옵션을 받거나 `freeze_guard.py`·`e2e5_live.py`·`Makefile`을 수정하지 마라. 이유: final은 `data/evalset/`만 읽어야 하고 가드·실행기는 이미 완료된 step의 산출물이다(필요하면 `blocked`로 보고).
- 기존 테스트의 단언을 약화하거나(특히 `test_sheet_columns_instructions_and_hash_guard`·finalize 테스트·`e3.main` 테스트) `_FINAL_TARGETS`·`REVIEW_COLUMNS`의 값을 바꾸지 마라. 이유: 이미 통과한 step의 계약이다.
- 정답을 새 경로에서 읽거나 정답·해시를 임베딩·`chat` 호출 입력에 넣지 마라. 이유: 정답 접근은 step 8의 "정답을 읽는 지점 표"의 셋뿐이다(B-FP-042).
- 합성 문장·모델이 만든 분류 값을 테스트 기대값으로 굳히지 마라. 이유: 테스트는 형식과 코드가 하는 일을 검사한다(AGENTS.md CRITICAL).
