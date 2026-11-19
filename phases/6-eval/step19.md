# Step 19: top-k-50

## 설계 검토 기록

**배경(사용자 확정·조언 세션 승인)**: 사용자가 `TOP_K = 50`을 확정했다(dev 측정 근거: small 모델, 길이 1500, TOP_K 50에서 hit@k 0.80·recall@k 0.391이며 MAX_ANSWER_SET 50과 같다). 이 step은 `eval/vector_baseline.py`의 `TOP_K`를 10에서 50으로 바꾸고 그에 딸린 소비처가 함께 바뀌는지 코드로 점검한다. `MAX_ANSWER_SET`(50)·`SIZE_STRATUM_THRESHOLD`(10)·`MAX_DOC_CHARS`(1500)는 바꾸지 않는다.

**식별자 전수 대조(현재 코드, 모두 열어 확인)**: `eval/vector_baseline.py:10 TOP_K = 10`과 `def top_k(query_vec, doc_vecs, ids, k=TOP_K)`(기본 인자는 함수 정의 때 값을 잡는다), `eval/e3_live.py`(`TOP_K`·`top_k` 가져오기 `:38·:42`; `extra_frozen`이 `"동결 E3 TOP_K": str(TOP_K)`를 낸다 `:107`; `measure(... top_ks=None ...)`의 `ks = _candidates(top_ks, TOP_K)` `:347`, 선택 조합 `if length == MAX_DOC_CHARS and k == TOP_K` `:407`, 결과 `"top_k": TOP_K` `:436`; `run`의 벡터 팔이 `top_k(...)`를 기본 k로 부른다 `:503`; `report`의 `size_vs_top_k`가 **모듈 속성** `vector_baseline.TOP_K`로 나눈다 `:657-662`), `eval/prereg.py`(`render_preregistration`의 "E3 dev 측정 근거" 절: 모델별·조합별 표와 값 표, `DEV_MEASUREMENT_KEYS`, 문장 `:148`·`:243`·`:298-300`이 `TOP_K`를 이름으로만 언급하고 값을 적지 않는다).

**상수 단언 grep(전수)**: `TOP_K`·`top_k`·`top_ks`를 `tests/`에서 찾은 결과 **리터럴 10으로 단언하는 곳은 없다.** 사용처는 모두 상수 이름을 읽는다: `tests/test_e3_live.py:884`(`monkeypatch.setattr(vector_baseline, "TOP_K", 3)`), `:1244`(`range(e3.TOP_K)`로 문서 생성), `:1276`(`m["top_k"] == e3.TOP_K`), `:1069·:1125·:1142·:1158·:1365`(`top_ks=[1, 2]` 등 명시 인자), `tests/test_vector_baseline.py:34`(`top_k(..., k=2)` 명시), `tests/test_prereg.py:63`(문장에 "TOP_K"라는 이름이 있음). 따라서 상수 값을 바꿔도 기존 단언은 자동으로 맞춰지며 갱신이 필요한 기존 단언은 없다(`:1244`는 문서 50개, `:1276`은 조합 50을 읽는다). **새 테스트로 값과 연동을 고정한다.**

**dev 측정 근거와의 일치**: 사용자의 측정 파일은 TOP_K 10일 때 실행되어 최상위 `models`·`selected_model`은 k=10 결과이고, `combinations`에 k=10·30·50(길이 1500) 항목이 모두 있다. 사전 등록 문서가 동결 TOP_K와 다른 값의 근거만 보여 주지 않도록, **동결 조합(`TOP_K`, `MAX_DOC_CHARS`)의 측정 항목이 측정 파일에 있어야 한다**는 검사를 렌더링에 넣는다(아래).

**새 칸 대응표**: `TOP_K = 50`(상수 → `extra_frozen`의 동결 줄·`measure` 기본 후보·`report`의 `size_vs_top_k`·벡터 팔 `top_k` 기본 k → 사전 등록 동결 줄), 동결 조합 측정 항목(`combinations`의 `top_k == TOP_K and max_doc_chars == MAX_DOC_CHARS` → 사전 등록 렌더링 검사).

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건(합성 테스트만). 벡터 팔 최종 실행 입력은 질문당 문서 50개(실측 문서당 약 37토큰)로 늘어 50건에 약 $0.02다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 동결된 기준은 결과를 본 뒤 바꾸지 않는다(TOP_K 50은 사전 등록 전 사용자 확정이다), 모델이 만든 값을 테스트 기대값으로 굳히지 않는다
- `/src/beautyads/eval/vector_baseline.py`(전체), `/src/beautyads/eval/e3_live.py`(`TOP_K` 사용처 전부), `/src/beautyads/eval/prereg.py`(`render_preregistration`·"E3 dev 측정 근거" 절·`validate_dev_measurement`)
- `/tests/test_vector_baseline.py`, `/tests/test_e3_live.py`(`:880-900`·`:1240-1280`·`measure`·`report` 테스트), `/tests/test_prereg.py`(`dev_measurement` 픽스처 `:181`·`cli_inputs` `:214`·`:471-640`)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/vector_baseline.py`, `src/beautyads/eval/e3_live.py`(필요할 때만), `src/beautyads/eval/prereg.py`, `tests/test_vector_baseline.py`, `tests/test_e3_live.py`, `tests/test_prereg.py`

열람 금지 경로: `data/interim/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `src/beautyads/eval/vector_baseline.py`, `src/beautyads/eval/e3_live.py`, `src/beautyads/eval/prereg.py`, `tests/test_vector_baseline.py`, `tests/test_e3_live.py`, `tests/test_prereg.py`

`TOP_K`를 50으로 바꾸고 동결 연동을 테스트로 고정하며 사전 등록 렌더링에 동결 조합 근거 검사를 넣는다. **모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: (없음)

**1. 상수(`eval/vector_baseline.py`)**: `TOP_K = 50`. 변경은 이 한 줄이다(`MAX_DOC_CHARS = 1500`·`top_k` 함수 본문·정렬 규칙 불변). `eval/e3_live.py`는 상수 이름만 읽으므로 수정이 필요 없을 수 있다(필요하면 최소한으로).

**2. 사전 등록 렌더링(`eval/prereg.py`)**
- `render_preregistration`이 `dev_measurement`를 받았을 때, **`selected_model`의 `combinations` 항목 중 `top_k == e3_live.TOP_K`이고 `max_doc_chars == e3_live.MAX_DOC_CHARS`인 것이 없으면** `ValueError("PREREG_INPUT_INVALID")`를 던진다(동결 조합의 근거가 측정 파일에 있어야 한다; 비교는 `extra_frozen`이 쓰는 같은 이름 `e3_live.TOP_K`·`e3_live.MAX_DOC_CHARS`로 한다). `validate_dev_measurement`는 바꾸지 않는다(측정기 출력 검증은 조합 값과 무관해야 한다).
- "E3 dev 측정 근거" 절의 값 표(c)에 행을 더한다: `측정 파일 기본 TOP_K`(측정 파일의 `top_k` 키, 없으면 "해당 없음"), `동결 TOP_K`(코드 `e3_live.TOP_K`), `동결 MAX_DOC_CHARS`(코드 `e3_live.MAX_DOC_CHARS`). 새 줄에 `:` 문자를 넣지 않는다(`parse_preregistration`이 라벨 줄로 읽는다). 기존 행·순서·표는 불변이다.

**테스트(합성 데이터·`tmp_path`, 모델·접속 없음)**
- `tests/test_vector_baseline.py`: (1) `TOP_K == 50`이고 `MAX_DOC_CHARS == 1500`이다(동결 값이라 리터럴로 고정한다). (2) `TOP_K >= evalset_candidates.MAX_ANSWER_SET`이다(정답 집합 상한까지 한 번에 검색 가능, 같은 출처 비교). (3) `top_k`의 기본 인자 k가 `TOP_K`와 같다(`inspect.signature`). 기존 테스트는 그대로 통과한다.
- `tests/test_e3_live.py`: (4) `extra_frozen("m")`의 `"동결 E3 TOP_K"`가 `"50"`, `"동결 E3 MAX_DOC_CHARS"`가 `"1500"`이다. (5) `measure`를 `top_ks` 없이 부르면 조합의 `top_k`가 `{TOP_K}` 하나뿐이고 결과 `top_k`가 `TOP_K`이며 선택 조합이 그 조합이다. (6) `report`의 `size_vs_top_k`가 **상수 TOP_K(monkeypatch 없음)**로 나뉜다: 정답 크기 10·50은 `size_le_top_k`, 51은 `size_gt_top_k`에 들어가고, 같은 질문들의 `size_strata`(임계값 `SIZE_STRATUM_THRESHOLD = 10`)에서는 11~50 크기가 `size_gt10`에 들어가 두 층화가 서로 다름을 단언한다. (7) `SIZE_STRATUM_THRESHOLD == 10`과 `MAX_ANSWER_SET == 50`이 불변이다. (8) 벡터 팔 `run`이 `top_k`에 k를 따로 넘기지 않고도 `TOP_K`개 문서를 증거로 쓴다(합성 코퍼스 60개 이상, 가짜 `structured`가 받은 증거 항목 수 == `TOP_K`).
- `tests/test_prereg.py`: (9) 합성 `dev_measurement`에 동결 조합(`e3_live.TOP_K`·`e3_live.MAX_DOC_CHARS`를 읽어 만든 항목)이 있으면 렌더링이 성공하고 값 표에 `동결 TOP_K`·`동결 MAX_DOC_CHARS`·`측정 파일 기본 TOP_K` 행이 있다. (10) 그 항목이 없으면 `PREREG_INPUT_INVALID`다(매개변수화: 항목 없음·다른 모델의 항목만 있음·길이만 다름). (11) `dev_measurement=None`의 출력은 변경 전과 바이트 단위로 같다. (12) 새 절의 모든 줄에 `:`가 없고 `parse_preregistration`이 절 유무와 상관없이 같은 값 집합을 돌려주며 동결 줄 `동결 E3 TOP_K`가 `"50"`이다. 기존 `dev_measurement`·`cli_inputs` 픽스처는 동결 조합 항목을 포함하도록 갱신하되(리터럴이 아니라 `e3_live.TOP_K`·`e3_live.MAX_DOC_CHARS`로 만든다) 기존 단언은 약화하지 않는다.
- 합성 문장·분류 값·실제 측정값을 기대값으로 굳히지 않는다(형식·경계·동결 값·같은 출처 비교만 검사).

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

- `TOP_K` 외의 상수(`MAX_ANSWER_SET`·`SIZE_STRATUM_THRESHOLD`·`MAX_DOC_CHARS`·`CORPUS_FIELDS`)와 `REQUIRED_SENTENCES`의 기존 문장·번호, `top_k`의 정렬·점수 규칙, 판정 로직을 바꾸지 마라. 이유: 동결 대상이며 TOP_K 50만 사용자가 확정했다.
- 실제 측정값(예: 실제 hit@k·recall@k)을 코드·테스트에 상수나 기대값으로 적지 마라. 이유: 수치는 측정 파일에서 복사하며 테스트는 합성 값만 쓴다.
- `data/interim/e3/measurement.json`(실제 파일)을 읽거나 `docs/results/`에 파일을 만들지 마라. 이유: 열람 금지 경로이며 사전 등록 문서 생성은 사용자가 11-26에 한다.
- `eval/e2*.py`·`eval/evalset*.py`·`eval/freeze_guard.py`·`Makefile`을 수정하거나 새 의존성을 추가하지 마라. 이유: 허용 범위 밖이다(필요하면 `blocked`로 보고).
- 기존 테스트의 단언을 약화하지 마라(픽스처에 동결 조합 항목을 더하는 갱신만 허용). 이유: 이미 통과한 step의 계약이다.
