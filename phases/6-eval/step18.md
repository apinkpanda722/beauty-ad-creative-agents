# Step 18: prereg-dev-evidence

## 설계 검토 기록

**배경(조언 세션 승인)**: 사용자가 실행한 E3 dev 임베딩 측정(`data/interim/e3/measurement.json`, `e3_live measure`의 출력)이 모델 선택과 `TOP_K` 후보별 재현율의 근거다. 사전 등록 문서에는 모델 이름(`embedding`)만 들어가고 이 근거 수치를 싣는 칸이 없다. 이 step은 `render_preregistration`에 측정 결과 입력을 추가하고 문서에 "E3 dev 측정 근거" 표를 넣는다. **수치는 코드 상수로 박지 않고 측정 파일에서 그대로 옮기며, 필수 키가 없으면 고정 오류로 끝난다.** `TOP_K` 상수(10)·`MAX_DOC_CHARS`는 이 step에서 바꾸지 않는다(사용자 확정 뒤 별도 step).

**식별자 전수 대조(현재 코드)**: `eval/prereg.py`(`EMBEDDING_MEASUREMENT_PATH = e3_live.OUTPUT_DIR / "measurement.json"`(`:39`), `render_preregistration(*, request_hash, question_hash, extra, embedding, isolation_hash, today) -> str`(`:149`: 동결 값 줄 → "## 코드에서 읽은 절차 값" 표(`| 항목 | 값 |`, `| 임베딩 모델 | {embedding} |`) → "## 절차와 한계"(`REQUIRED_SENTENCES` 번호 목록) → "## 정정 기록"), `main(argv=None, *, out=sys.stdout)`(`:339`: 배타적 `--print`·`--write PATH`·`--results-template`, `json.loads(EMBEDDING_MEASUREMENT_PATH.read_text(...))`로 `selected_model`을 읽고 `embedding not in EMBEDDING_PRICES`이면 `ValueError("PREREG_INPUT_INVALID")`, 예외는 `PREREG_INPUT_INVALID`·`EVALSET_*` 고정 코드로 출력), `REQUIRED_SENTENCES` 17개(불변)), `eval/e3_live.py`(읽기 전용: `measure(...)`의 결과 딕셔너리 키 — 최상위 `models`(항목: `embedding_model`·`price_per_million`·`hit_at_k`·`recall_at_k`·`n_with_target`·`n_no_target`·`hit_at_k_all_questions`·`questions`·`input_tokens`·`cost_usd`)·`combinations`(항목: 위 키 + `top_k`·`max_doc_chars`)·`selected_model`·`dev_question_hash`·`selection_rule`·`truncated_document_ratio`·`truncated_dev_evidence_ratio`·`n_set_questions_values_not_in_corpus`·`top_k`·`max_doc_chars`·`corpus_fields`), `eval/freeze_guard.py`(읽기 전용: `parse_preregistration(text)`는 **`:`가 있는 모든 줄을 `라벨: 값`으로 읽고 같은 라벨이 두 번 나오면 `FROZEN_VALUE_MISMATCH`**).

**상수 단언 grep**: 기존 테스트 중 이 step이 건드리는 것만 갱신한다.
- `tests/test_prereg.py:190-199` CLI 픽스처(`cli_inputs`): 측정 파일이 `{"selected_model": "text-embedding-3-small"}`뿐이다. CLI가 필수 키를 요구하게 되므로 **완전한 합성 측정 딕셔너리**(실제 측정값을 복사하지 않은 합성 수치)로 갱신한다. 이 픽스처를 쓰는 기존 CLI 테스트(`--print` 읽기 전용·`--write`·고정 코드 등)는 그대로 통과해야 한다.
- `tests/test_prereg.py:302-322`(`test_missing_cli_inputs_fail_with_fixed_codes`·`test_invalid_embedding_selection_is_not_guessed`: `"{"`·`"{}"`·`"[]"`·`'{"selected_model":""}'`가 `PREREG_INPUT_INVALID`): 불변이다.
- `render_preregistration`을 `dev_measurement` 없이 부르는 기존 테스트(`render_inputs` 픽스처 사용)의 출력은 **바이트 단위로 같아야 한다**(새 인자는 선택이고 기본 `None`이면 새 절이 없다).
- `REQUIRED_SENTENCES`의 개수 단언(`== 17`)과 번호·문장은 불변이다.
- `tests/test_e3_live.py`의 `measure` 호출 테스트와 결과 키 단언은 불변이다(읽기 전용으로 결과 형태를 이 step의 검증기에 대입만 한다).

**새 칸 대응표**: 측정 파일 필수 키(`e3_live.measure` 출력 → `prereg.validate_dev_measurement` → 문서 표 → 사용자의 `TOP_K` 확정 근거), `--dev-measurement PATH`(`main` → 측정 파일 경로, 기본 `EMBEDDING_MEASUREMENT_PATH`).

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건(합성 파일만).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 사전 등록 전에 결과를 내지 않는다, 동결된 기준은 결과를 본 뒤 바꾸지 않는다, 모델이 만든 값을 테스트 기대값으로 굳히지 않는다
- `/src/beautyads/eval/prereg.py`(전체), `/src/beautyads/eval/e3_live.py`(`measure`의 결과 구성, 읽기 전용), `/src/beautyads/eval/freeze_guard.py`(`parse_preregistration`, 읽기 전용)
- `/tests/test_prereg.py`(전체: `render_inputs`·`cli_inputs` 픽스처), `/tests/test_e3_live.py`(`measure` 테스트, 읽기 전용 참고)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/prereg.py`, `tests/test_prereg.py`, `src/beautyads/eval/vector_baseline.py`(표 렌더링에 필요할 때만, `TOP_K`·`MAX_DOC_CHARS` 상수는 바꾸지 않는다), `tests/test_vector_baseline.py`, `tests/test_e3_live.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/prereg.py`, `tests/test_prereg.py`, `src/beautyads/eval/vector_baseline.py`, `tests/test_vector_baseline.py`, `tests/test_e3_live.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 측정 파일 경로 `e3_live.OUTPUT_DIR / "measurement.json"`을 읽는 CLI)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

사전 등록 문서에 E3 dev 측정 근거 표를 추가한다. **모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: `validate_dev_measurement`, `DEV_MEASUREMENT_KEYS`

**1. 검증기(`eval/prereg.py`)**
- `DEV_MEASUREMENT_KEYS`: 필수 키를 담은 구조(최상위 `selected_model`·`dev_question_hash`·`selection_rule`·`truncated_document_ratio`·`truncated_dev_evidence_ratio`·`n_set_questions_values_not_in_corpus`·`models`·`combinations`, `models` 항목 `embedding_model`·`price_per_million`·`hit_at_k`·`recall_at_k`·`n_with_target`·`n_no_target`·`hit_at_k_all_questions`, `combinations` 항목 `embedding_model`·`top_k`·`max_doc_chars`·`hit_at_k`·`recall_at_k`·`n_with_target`·`n_no_target`).
- `validate_dev_measurement(measurement) -> None`: 딕셔너리가 아니거나, 필수 키가 하나라도 없거나, `selected_model`이 `EMBEDDING_PRICES`에 없거나, `models`·`combinations`가 비어 있거나 리스트가 아니거나, `models` 항목의 `embedding_model`이 `EMBEDDING_PRICES`에 없거나, `top_k`·`max_doc_chars`가 양의 정수가 아니거나, `n_with_target`·`n_no_target`·`n_set_questions_values_not_in_corpus`가 음이 아닌 정수가 아니거나, 지표 값(`hit_at_k`·`recall_at_k`·`hit_at_k_all_questions`·`price_per_million`·잘린 비율)이 숫자도 `None`도 아니거나(`bool` 제외), 렌더링할 문자열 값에 `:`가 들어 있거나, `dev_question_hash`가 64자리 소문자 16진이 아니면 `ValueError("PREREG_INPUT_INVALID")`를 던진다. **`selected_model`이 `models` 항목의 `embedding_model` 중에 있어야** 한다. 측정 파일의 모델 목록·`TOP_K` 후보는 **파일에 있는 것을 그대로** 쓰고 코드의 `TOP_K`·`EMBEDDING_PRICES` 키 목록과 일치시키려고 거르거나 채우지 않는다.

**2. 렌더링(`render_preregistration(..., dev_measurement=None)`)**
- 새 인자 `dev_measurement=None`. `None`이면 출력은 변경 전과 **같다**. 주어지면 `validate_dev_measurement`를 먼저 부르고(실패 시 `ValueError("PREREG_INPUT_INVALID")`) "## 절차와 한계" **앞에** 다음 절을 넣는다: 제목 `## E3 dev 측정 근거`, 설명 한 줄(측정 파일의 값을 그대로 옮긴 것이며 모델 선택은 6번 문장의 규칙(hit@k 최고, 동률이면 저가)을 따르고 `TOP_K`·`MAX_DOC_CHARS`는 사용자가 사전 등록 전에 확정한다는 취지), (a) 모델별 표(열: 모델·단가(100만 토큰당 USD)·hit@k·recall@k·대상 질문 수·대상 없는 질문 수·옛 정의 hit@k(전체 질문 기준)), (b) 조합별 표(열: 모델·TOP_K·MAX_DOC_CHARS·hit@k·recall@k·대상 질문 수·대상 없는 질문 수), (c) 값 표(선택 모델·선택 규칙·dev 질문 세트 해시·잘린 문서 비율·정답 근거 소재 문서 중 잘린 비율·정답 값이 코퍼스에 없는 집합 질문 수). 표 행은 파일의 순서를 유지한다. `None` 값은 "해당 없음"으로 적는다. **새 절의 어떤 줄에도 `:` 문자를 넣지 않는다**(`freeze_guard.parse_preregistration`이 라벨 줄로 오인한다; 설명 문장은 `:` 없이 쓴다).
- `REQUIRED_SENTENCES`·번호·인덱스 참조·기존 절의 순서는 바꾸지 않는다. 같은 입력이면 같은 출력이다(결정적).

**3. CLI(`main`)**
- `--dev-measurement PATH`(`Path`, 기본 없음)를 추가한다. 주어지면 그 파일을, 없으면 `EMBEDDING_MEASUREMENT_PATH`를 **한 번만** 읽어 `selected_model`과 `dev_measurement`를 같은 딕셔너리에서 가져온다. 읽기·검증 실패는 기존 `PREREG_INPUT_INVALID` 고정 코드다(경로·내용 미출력). `--print`·`--write PATH`·`--results-template`의 기존 동작(덮어쓰기 금지 `PREREG_FILE_EXISTS`, 읽기 전용 `--print`)은 불변이다.

**테스트(합성 데이터·`tmp_path`, 모델·접속 없음)**
- `tests/test_prereg.py`: (1) `dev_measurement=None`이면 출력이 변경 전과 같고 "E3 dev 측정 근거"가 없다. (2) 합성 측정 딕셔너리(**실제 측정값을 복사하지 않은 합성 수치**, 모델 2개·조합 4개 이상)를 주면 절이 있고 모델별·조합별 표의 행 수가 파일의 목록 길이와 같으며 각 셀이 합성 값을 그대로 보여 준다(모델 이름·`top_k`·`max_doc_chars`·숫자, 코드 상수와 무관), `None`은 "해당 없음". (3) 새 절의 모든 줄에 `:`가 없고 `freeze_guard.parse_preregistration`이 절 유무와 상관없이 같은 값 집합을 돌려준다(라벨 충돌 없음), 기존 왕복 테스트가 통과한다. (4) 필수 키를 하나씩 빼거나(매개변수화) 타입·값이 잘못된 경우(모델 이름이 `EMBEDDING_PRICES`에 없음, 빈 `models`·`combinations`, `top_k` 0·음수·문자열, `bool` 지표, 해시 형식 오류, `selected_model`이 `models`에 없음, 문자열에 `:`)가 `ValueError("PREREG_INPUT_INVALID")`다. (5) CLI: 갱신한 `cli_inputs` 픽스처로 `--print`가 읽기 전용이고 새 절을 출력하며 `--dev-measurement PATH`가 기본 경로(없는 파일로 바꿔 둠)를 대신 읽고, 필수 키가 빠진 파일은 `PREREG_INPUT_INVALID`·파일 미생성이다. (6) 같은 입력 두 번 렌더링이 같다. (7) 기존 테스트가 위 "상수 단언 grep"의 갱신 대상 외에는 그대로 통과한다.
- `tests/test_e3_live.py`: (8) **생산자-소비자 일치**: 기존 `measure` 테스트 방식(가짜 `embed`·합성 코퍼스·합성 정답)으로 `measure(...)`를 실행한 결과 딕셔너리(`--top-ks`·`--max-doc-chars` 조합이 둘 이상인 호출)를 `prereg.validate_dev_measurement`에 넣어 예외 없이 통과함을 단언한다(측정 출력 형태와 이 step의 검증기가 어긋나면 실패). 기존 `measure` 단언은 건드리지 않는다.
- `tests/test_vector_baseline.py`·`eval/vector_baseline.py`는 이 step에 필요 없으면 수정하지 않는다.
- 합성 문장·분류 값·모델이 만든 값을 기대값으로 굳히지 않는다(형식·행 수·고정 코드만 검사).

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

- `TOP_K`·`MAX_DOC_CHARS`·`MAX_ANSWER_SET`·`CORPUS_FIELDS`나 `REQUIRED_SENTENCES`의 기존 문장·번호를 바꾸지 마라. 이유: `TOP_K` 확정은 사용자가 사전 등록 전에 하며 별도 step으로 다룬다. 사전 등록 문장은 기존 항목을 고치지 않는다(B-FP-043).
- 실제 측정값(예: 실제 hit@k·recall@k)을 코드·테스트에 상수나 기대값으로 적지 마라. 이유: 수치는 측정 파일에서 복사하며, 테스트는 합성 값만 쓴다(AGENTS.md CRITICAL).
- `data/interim/e3/measurement.json`(실제 파일)을 읽거나 `docs/results/`에 파일을 만들지 마라. 이유: 열람 금지 경로이며 사전 등록 문서 생성은 사용자가 11-26에 한다.
- `eval/e3_live.py`·`eval/freeze_guard.py`·`eval/evalset*.py`·`Makefile`을 수정하거나 새 의존성을 추가하지 마라. 이유: 허용 범위 밖이며 이미 완료된 step의 계약이다(필요하면 `blocked`로 보고, 단 `tests/test_e3_live.py`는 허용이다).
- 새 절의 줄에 `:`를 넣거나 기존 테스트의 단언을 약화하지 마라. 이유: `parse_preregistration`이 `:` 줄을 라벨로 읽어 충돌하며, 이미 통과한 step의 계약이다.
