# Step 13: e3-reporting

## 설계 검토 기록

**배경(조언 세션 승인)**: (1) E3 `set` 질문은 정규화한 집합의 완전 일치로만 판정하고 벡터 팔은 `TOP_K = 10` 문서만 보므로, 정답 집합이 10을 넘으면 구조적으로 불리하다. 정답 크기 10 이하 대 초과로 나눈 층화 보고와 참고용 부분 점수(F1)가 필요하다. (2) `measure`의 hit@k는 `truth.evidence_ids`와의 교집합만 보는데, 현재 유효 후보 질문의 대부분(제품 링크 집합을 정답으로 하는 CQ-01·02·03·10과 규칙 ID 집합 CQ-11)은 `evidence_ids`가 비어 있어 **항상 미적중으로 센다** → 임베딩 모델 선택이 소수 질문에 좌우된다. 정답 값이 코퍼스 문서 id로 대응되는 경우(제품 링크 → `product:{브랜드}:{링크}` 문서, `source:id` 형식 소재 ID)를 대상으로 삼는 재현율이 필요하다. (3) `TOP_K`(10)·`MAX_DOC_CHARS`(1500)는 임시 값이며 dev 재현율과 비용을 보고 사용자가 사전 등록 전에 확정한다. 이 step은 보고·측정 코드와 사전 등록 문장을 만든다. **판정 기준(`graph_adopted`·`not_adopted`·`undecidable`)은 기존 완전 일치 기준 그대로다.**

**식별자 전수 대조(현재 코드)**: `eval/e3_live.py`(`TOP_K`·`MAX_DOC_CHARS` 가져오기, `read_answers(path, *, questions, split, purpose)`(`purpose` `measure`/`report`만, `measure`는 dev만)·`score_answer(answer, truth) -> {"correct", "evidence_hit_rate"}`·`_summary(questions, scores)`·`report(records, questions, *, answers_path, split)`·`measure(docs, questions, *, answers_path, models, embed, split="dev", dry_run=False, cache_dir=OUTPUT_DIR)`(현재 hit = `set(top_k(...)) & set(truth.evidence_ids)`가 비어 있지 않음, 평균 `hit_at_k`)·`_corpus_vectors(docs, model, embed, cache_dir)`·`E3Answer`·`E3Error`·`ANSWER_SPLIT_FORBIDDEN`·`main`(`--mode`·`--arms`·`--models`·`--limit`·`--dry-run`·`--questions`·`--answers`)), `eval/vector_baseline.py`(`TOP_K = 10`·`MAX_DOC_CHARS = 1500`·`CorpusDoc(id, text).embedding_text`(= `text[:MAX_DOC_CHARS]`, 모듈 상수를 호출 때 읽는다)·`top_k(query_vec, doc_vecs, ids, k=TOP_K)`·`build_corpus`(소재 문서 id `{source}:{source_id}`, 제품 문서 id `product:{brand}:{source_url}`)·`_paths(root, model)`·`_fingerprint(docs)`·`save_cache`·`load_cache`), `eval/prereg.py`(`REQUIRED_SENTENCES` 15개, 끝에 추가만 한다), `eval/evalset.py`(`AnswerItem`: `value: StrictInt | list[str]`·`evidence_ids`; 읽기 전용).

**상수 단언 grep**: 기존 단언 중 이 step이 건드리는 것만 갱신하고 나머지는 약화하지 않는다.
- `tests/test_e3_live.py:136` `score_answer(...) == {"correct": True, "evidence_hit_rate": None}`(정확 일치): **`score_answer`의 반환 딕셔너리는 바꾸지 않는다**(키 추가 금지). 부분 점수는 새 함수 `set_f1`로 따로 만든다.
- `tests/test_e3_live.py:164` `result["models"][0]["hit_at_k"] == 1.0`(합성): 합성 정답에 `evidence_ids`가 있으므로 새 정의(대상 있는 질문 기준)에서도 1.0이어야 한다.
- `tests/test_e3_live.py:251·252·572·573`(`strata`의 `status`·`decision`), `:426·427`(`truncated_*` 비율): 불변이다. 새 층(`size_*`)은 기존 `strata` 키를 바꾸지 않고 **새 키**로 추가한다.
- `tests/test_vector_baseline.py:43-47`(캐시 왕복: 모델 이름이 다르면 섞이지 않음, 문서 텍스트가 바뀌면 무효): 기본 인자(현재 `MAX_DOC_CHARS`)에서는 그대로 통과해야 한다.
- `tests/test_prereg.py`의 문장 수 `== 15`: 16개가 되므로 `== 16`으로 갱신하고 새 문장 존재 단언을 추가한다.
- `tests/test_schema_guard.py:480`이 `from test_e3_live import arm_options, question`을 쓰므로 두 헬퍼의 이름·시그니처를 바꾸지 않는다.

**새 칸 대응표**: `set_f1`(`e3_live` 새 함수 → `report`의 팔별 `set_f1` 요약, 참고용), 크기 층 `size_le10`·`size_gt10`·`size_count`(고정 임계값 `SIZE_STRATUM_THRESHOLD = 10`)와 `size_le_top_k`·`size_gt_top_k`(실행에 쓴 `TOP_K` 기준)(`report` → 보고 JSON → 사전 등록 문장 16번), 재현율 대상 id 집합(`measure` 안에서만 정답 → 코퍼스 문서 id로 사상, 모델·임베딩 입력에 넣지 않음), `hit_at_k`(대상 있는 질문 기준으로 재정의)·`recall_at_k`·`n_with_target`·`n_no_target`·`hit_at_k_all_questions`(옛 정의, 투명성용)·`top_ks`별 결과(`measure` → `measurement.json` → 사용자의 `TOP_K` 확정), `--top-ks`·`--max-doc-chars`(`main` → `measure`; `run`·`report`에는 쓰지 않는다).

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건(합성 테스트만). 측정 실행은 사용자 승인 뒤에만 한다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 모델이 만든 값을 테스트 기대값으로 굳히지 않는다, 동결된 기준은 결과를 본 뒤 바꾸지 않는다, 정답 접근은 step 8 "정답을 읽는 지점 표"의 셋뿐이다(B-FP-042)
- `/src/beautyads/eval/e3_live.py`(전체), `/src/beautyads/eval/vector_baseline.py`(전체), `/src/beautyads/eval/prereg.py`(`REQUIRED_SENTENCES`), `/src/beautyads/eval/evalset.py`(읽기 전용), `/src/beautyads/eval/e2_scoring.py`(읽기 전용: `bootstrap_ci`·`MIN_STRATUM_N`)
- `/tests/test_e3_live.py`(전체), `/tests/test_vector_baseline.py`, `/tests/test_prereg.py`, `/phases/6-eval/step8.md`·`/phases/6-eval/step11.md`(정답을 읽는 지점 표와 `--questions`·`--answers` 규칙, 읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/e3_live.py`, `tests/test_e3_live.py`, `src/beautyads/eval/prereg.py`, `tests/test_prereg.py`, `src/beautyads/eval/vector_baseline.py`, `tests/test_vector_baseline.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/e3_live.py`, `tests/test_e3_live.py`, `src/beautyads/eval/prereg.py`, `tests/test_prereg.py`, `src/beautyads/eval/vector_baseline.py`, `tests/test_vector_baseline.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

E3 보고에 정답 크기 층화와 참고용 F1을 더하고, `measure`의 적중 정의를 고쳐 재현율과 `TOP_K` 후보별 결과를 내며, 사전 등록 문장을 추가한다. **모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: `SIZE_STRATUM_THRESHOLD`, `set_f1`, `target_ids`

**1. 참고용 부분 점수와 크기 층(`report`)**
- `set_f1(answer, truth) -> dict | None`: `truth.answer_type == "set"`이면 정규화(앞뒤 공백 제거·중복 제거)한 `answer.items`와 `truth.value` 집합으로 `{"precision", "recall", "f1"}`(분모가 0이면 해당 값 0.0, 정답은 비어 있지 않다), `count`이면 `None`. `score_answer`는 바꾸지 않는다.
- `_summary`는 팔별 `set_f1`(`f1` 평균과 `n`, 집합 질문만)을 **추가 키**로 싣는다(기존 키·값 불변, `decision` 로직 불변). 판정은 어디서도 F1을 쓰지 않는다.
- `report` 결과에 새 키를 추가한다(기존 `overall`·`graph_questions`·`simple_search`·`strata` 불변): `size_strata` = `{"size_le10", "size_gt10", "size_count"}`(`SIZE_STRATUM_THRESHOLD = 10`: `set` 질문을 정답 `len(truth.value)`로 나눈다. `count` 질문은 `size_count`) 와 `size_vs_top_k` = `{"size_le_top_k", "size_gt_top_k"}`(`vector_baseline.TOP_K` 기준, `set` 질문만). 각 층은 `_summary` 결과에 `status`(`n < MIN_STRATUM_N`이면 `undecidable`, 아니면 `descriptive_only`)와 `decision: "undecidable"`을 붙인다(참고용, 채택 판정 없음, 기존 `strata`와 같은 규칙). 층 계산에 쓴 정답 크기는 보고 JSON에 질문별로 싣지 않는다(건수만).
- 정답을 읽는 지점은 기존 `report`의 `read_answers(..., purpose="report")` 하나뿐이다(새 읽기 지점을 만들지 않는다).

**2. `measure`: 적중 정의와 재현율, `TOP_K` 후보**
- `target_ids(truth, doc_ids) -> set[str]`: 질문의 재현율 **대상 문서 id 집합** = `truth.evidence_ids` 중 `doc_ids`에 있는 것 ∪ (`truth.value`가 `list[str]`일 때) 각 값 중 (a) 그 자체가 문서 id인 것, (b) 값이 `product:`로 시작하는 문서 id의 `{브랜드}:` 뒤 부분(= `source_url`)과 같은 것(`id.split(":", 2)[2]`)의 문서 id. `count` 값은 쓰지 않는다. 코퍼스에 없는 값(표현 규칙 ID·효능·카테고리 값 등)은 대상이 되지 못한다. 이 사상은 `measure` 안에서만 정답을 읽어 id 집합만 만들고, **정답 문자열은 임베딩·`chat` 호출 입력에 넣지 않으며** 출력·로그·예외에 싣지 않는다(`ANSWER_SPLIT_FORBIDDEN`과 정답 접근 지점 규칙 유지).
- 모델마다·`TOP_K` 후보 k마다: 대상이 있는 질문만 평균한 `hit_at_k`(상위 k 안에 대상이 하나라도 있는 질문의 비율)와 `recall_at_k`(질문별 `|대상 ∩ 상위 k| / |대상|`의 평균), `n_with_target`, `n_no_target`(대상이 없는 질문 수, 평균에서 제외), `hit_at_k_all_questions`(옛 정의: 모든 질문 중 `evidence_ids`와 교집합이 있는 비율, 투명성용)를 낸다. 기존 `models[...]["hit_at_k"]` 키는 유지하되 값은 **대상 있는 질문 기준**이다(`n_with_target == 0`이면 `None`). 기존 `selected_model`·`selection_rule` 문자열은 유지하고 최고 `hit_at_k`(None은 최하)·동률이면 저가 규칙을 새 정의로 적용한다. 선택은 기본 `TOP_K`(상수)에서만 한다(다른 k는 보고만, `TOP_K` 확정은 사용자 결정).
- `main`에 `measure` 전용 옵션 `--top-ks`(쉼표 구분 양의 정수 목록, 기본은 `TOP_K` 하나)와 `--max-doc-chars`(쉼표 구분 양의 정수 목록, 기본은 `MAX_DOC_CHARS` 하나)를 추가한다. `--top-ks`는 같은 코퍼스·질문 벡터에서 k만 바꿔 재계산하므로 **추가 임베딩 호출이 없다**. `--max-doc-chars`의 각 값은 문서를 그 길이로 자른 텍스트를 다시 임베딩하므로 값마다 별도 코퍼스 벡터가 필요하다(캐시 키에 길이를 넣는다, 아래). `measure`가 아닌 명령에서 이 옵션을 주면 고정 오류 `E3_ARGUMENTS_INVALID`다. 같은 `measure` 호출의 결과(`measurement.json`)의 기존 최상위 키(`models`·`selected_model`·`truncated_*` 등)는 **기본 길이·기본 `TOP_K`** 결과 그대로 두고, (길이, 모델, k) 조합별 항목은 새 키 `combinations`(리스트)로 싣는다. `--dry-run`은 정답을 읽지 않고(해시·재현율을 내지 않는다) 길이별 문서 수와 추정 토큰만 출력한다("가정, 미실측").
- 최종 `run`·`report`는 상수 `TOP_K`·`MAX_DOC_CHARS`만 쓴다(옵션 없음).
- `measure` 결과에 `n_set_questions_values_not_in_corpus`(정답 값이 하나도 코퍼스 문서에 대응되지 않는 `set` 질문 수, 건수만)를 추가한다(벡터 팔이 정의상 도달할 수 없는 질문의 규모 보고용).

**3. `eval/vector_baseline.py`: 길이별 코퍼스·캐시**
- 임베딩 텍스트 길이를 인자로 받을 수 있게 한다: `CorpusDoc.embedding_text`는 기본 동작(모듈 상수 `MAX_DOC_CHARS`로 자름)을 그대로 두고, 길이를 지정하는 방법(예: `embedding_text_for(max_chars)`)을 추가한다. `save_cache`·`load_cache`·`_paths`·`_fingerprint`는 선택 인자 `max_chars=None`(기본 = 현재 동작)을 받고, 기본이 아닌 길이일 때만 캐시 파일 이름과 지문에 길이를 넣어 서로 섞이지 않게 한다. 기본값에서 기존 캐시 형식·이름은 불변이다.
- `top_k`의 시그니처와 정렬(점수 내림차순, 같은 점수는 `id` 오름차순)은 불변이다.

**4. 사전 등록 문장(`eval/prereg.py`)**
- `REQUIRED_SENTENCES` **끝에 16번째** 문장을 추가한다(기존 15개의 순서·문장 불변): (a) E3의 채택 판정은 기존 완전 일치 기준 그대로이고 `set` 질문의 부분 점수(F1)는 참고용이며 판정에 쓰지 않는다. (b) 정답 집합 크기 10 이하 대 초과(`SIZE_STRATUM_THRESHOLD`의 값을 f-string으로 싣는다)와 실행에 쓴 `TOP_K` 이하 대 초과로 나눈 층화 보고를 하며, 벡터 팔은 `TOP_K` 문서만 보는 구조적 한계가 있어 이 층 구분이 필요하다(참고용, 채택 판정 없음). (c) `TOP_K`와 `MAX_DOC_CHARS`는 dev 질문의 재현율과 비용을 보고 사용자가 **사전 등록 전에 확정**하며 test 결과를 본 뒤에는 바꾸지 않는다. (d) 임베딩 측정의 hit@k는 정답에서 대응되는 코퍼스 문서(`evidence_ids`와 문서 id로 대응되는 정답 값)가 있는 질문만 평균하고 대상이 없는 질문 수를 함께 보고한다. (e) 현재 코퍼스 필드에 없는 값(표현 규칙 ID·효능·카테고리 값 등)을 정답으로 하는 질문은 벡터 팔이 정의상 도달할 수 없고 이 한계를 결과에 적는다.
- `render_preregistration`의 번호 매김·인덱스 참조는 바꾸지 않는다.

**테스트(합성 데이터·`tmp_path`, 모델·접속 없음)**
- `tests/test_e3_live.py`: (1) `set_f1`: 완전 일치·부분 겹침·무겹침·빈 답·중복·공백 정규화, `count`는 `None`. (2) `report`의 `size_strata`·`size_vs_top_k`가 합성 정답 크기(경계 10·`TOP_K`, `count` 별도)대로 나뉘고 `status`·`decision`이 규칙대로이며 기존 `strata`·`overall` 키·값이 불변이다. (3) F1이 `decision`에 영향을 주지 않는다(같은 정답 판정에서 F1만 다른 두 기록의 `decision`이 같다). (4) `target_ids`: 증거 id만 있는 질문, 제품 링크 값이 `product:{브랜드}:{링크}` 문서에 대응되는 질문, 소재 id 값, 코퍼스에 없는 값(→ 대상 없음), `count` 질문을 손으로 센 값과 비교한다. (5) `measure`: `hit_at_k`·`recall_at_k`·`n_with_target`·`n_no_target`·`hit_at_k_all_questions`가 합성 코퍼스에서 손으로 센 값과 같고, `n_with_target == 0`이면 `hit_at_k`가 `None`이며 모델 선택이 그 모델을 최하로 본다. (6) `--top-ks`가 추가 임베딩 호출 없이(가짜 `embed` 호출 횟수 불변) k별 결과를 내고 k가 커질수록 재현율이 줄지 않는다. (7) `--max-doc-chars`가 길이별로 별도 임베딩 호출·별도 캐시를 쓰며 서로 섞이지 않는다. (8) `measure` 전용 옵션을 `run`·`report`에 주면 `E3_ARGUMENTS_INVALID`. (9) 정답 표식(`SENTINEL_TRUTH` 등)이 가짜 `embed`·`chat`·`structured` 입력, 결과 파일, 로그, 예외 메시지에 없고, `measure`의 `"test"` 요청은 여전히 `ANSWER_SPLIT_FORBIDDEN`이다. (10) 기존 테스트가 그대로 통과한다(위 "상수 단언 grep"의 갱신 대상 제외).
- `tests/test_vector_baseline.py`: 길이 지정 임베딩 텍스트, 기본 인자에서 기존 캐시 이름·형식 불변, 다른 길이 캐시가 서로 섞이지 않음.
- `tests/test_prereg.py`: `== 16`과 새 문장 존재(`SIZE_STRATUM_THRESHOLD` 값·"F1"·"참고용"·"사전 등록 전에 확정"이 들어 있음, 리터럴 10은 상수에서 읽는다).
- 합성 문장·분류 값을 기대값으로 굳히지 않는다(형식·건수·계산값만 검사).

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

- `score_answer`의 반환 키·판정 규칙(`set` 완전 일치, `count` 허용 오차)이나 `graph_adopted`·`not_adopted`·`undecidable` 판정 로직·임계값을 바꾸지 마라. 이유: 판정 기준은 동결되어 있고 F1과 층화는 참고용이다(docs/EVAL.md).
- 정답 값을 임베딩·`chat`·`structured` 호출 입력이나 출력·로그·예외 메시지·결과 파일에 넣거나 새 정답 읽기 지점을 만들지 마라. 이유: 정답 접근은 `check_run`·`measure`(dev)·`report` 셋뿐이다(B-FP-042).
- 코퍼스 필드(`CORPUS_FIELDS`)·`TOP_K`·`MAX_DOC_CHARS`의 기본값을 바꾸거나 표현 규칙 문서 등 새 문서 종류를 코퍼스에 넣지 마라. 이유: 값은 사용자가 dev 측정 뒤 확정하며 코퍼스 확장은 별도 결정 사항이다.
- `--top-ks`·`--max-doc-chars`를 `run`·`report`·final 경로에서 받지 마라. 이유: 최종 실행은 사전 등록된 상수만 쓴다.
- `eval/evalset.py`·`eval/e2_scoring.py`·`eval/freeze_guard.py`·`Makefile`·`graph/queries.py`를 수정하거나 새 의존성을 추가하지 마라. 이유: 허용 범위 밖이며 이미 완료된 step의 계약이다(필요하면 `blocked`로 보고).
- 기존 테스트의 단언을 약화하지 마라(위 "상수 단언 grep"에 적힌 갱신만 허용). 합성 문장·모델이 만든 값을 기대값으로 굳히지 마라. 이유: 이미 통과한 step의 계약이며 테스트는 형식과 코드가 하는 일을 검사한다(AGENTS.md CRITICAL).
