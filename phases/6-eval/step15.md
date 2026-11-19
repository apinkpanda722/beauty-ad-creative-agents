# Step 15: rule-corpus

## 설계 검토 기록

**배경(조언 세션 승인)**: E3 코퍼스는 소재 문서와 제품 문서뿐이고 표현 규칙 문서가 없어, 정답이 규칙 ID 집합인 질문(CQ-11 계열)은 벡터 팔이 정의상 도달할 수 없다. 단순 검색형 test 10건이 거의 CQ-03과 CQ-11이라 벡터 팔에 공정해야 할 부분집합이 구조적으로 불리했다. 이 step은 코퍼스에 표현 규칙 문서를 추가하고(규칙이 직접 걸리는 대상 `APPLIES_TO`만 적고 상속 관계를 미리 펼치지 않는다 — 상속·범위 추론은 그래프의 강점이므로 벡터 팔이 직접 해야 한다), 규칙 ID를 문서 id로 대응시키며, "코퍼스에서 도달 가능한 질문만"의 부분집합 결과를 참고용으로 보고하고, 사전 등록 문장을 갱신한다. **판정(`graph_adopted` 등)은 기존 전체 질문 기준 그대로다.**

**식별자 전수 대조(현재 코드)**: `graph/queries.py:136 CQ-11`(`MATCH (r:ClaimRule)-[:APPLIES_TO]->(scope) WHERE (scope:Efficacy AND scope.value = $claim) OR (scope:SkinConcern AND scope.value = $concern) OR (scope:Category AND scope.value = $category) RETURN DISTINCT r.rule_id, r.rule_json, scope.value` — 정답 값은 `rule_id` 문자열(예: `CR-011`), `evidence_ids`는 비어 있다), `graph/layer1.py:337-345`(`APPLIES_TO`는 `s.status in {"advisor_approved", "confirmed"}`인 범위만 적재, `SCOPE_LABELS`: `efficacy`→`Efficacy`·`skin_concern`→`SkinConcern`·`category`→`Category`; 모든 규칙이 `ClaimRule` 노드로 적재), `sources/claim_rules.py:load_claim_rules(path: Path) -> list[ClaimRule]`(`config/claim_rules.yaml`을 읽는 **기존 읽기**이며 `pipeline/sync.py:435`·`api/assembly.py:207`·`eval/e2e5_live.py:244`도 같은 경로 리터럴로 쓴다), `domain/claims.py`(`ClaimRule`: `rule_id`·`rule_type: RuleType`·`group`·`terms_ko`·`applies_to: list[ClaimScope]`, `ClaimScope`: `kind`·`value`·`status`), `eval/vector_baseline.py`(`_CREATIVE_FIELDS`·`_PRODUCT_FIELDS`·`CORPUS_FIELDS = tuple(dict.fromkeys((...)))`·`_document(id_, values, fields)`(줄 `key: json`, 필드 순서대로)·`build_corpus(creative_source, product_source, *, run_tag="v1")`(문서 id 중복 시 `CORPUS_ID_DUPLICATE`)·`CorpusDoc.embedding_text`가 `MAX_DOC_CHARS`로 자름), `eval/e3_live.py`(`load_corpus()`: `build_corpus(PostgresGraphSyncSource(conn), PostgresLayer1Source(conn))`·`target_ids(truth, doc_ids)`(정답 값이 문서 id와 같으면 대상, 이미 `:254`)·`report(records, questions, *, answers_path, split)`·`main`·`extra_frozen`의 `CORPUS_FIELDS` 줄), `eval/prereg.py`(`REQUIRED_SENTENCES` 16개, 16번째의 한계 문장이 `표현 규칙 ID·효능·카테고리 값`을 도달 불가로 적고 있다 → 규칙 ID는 이제 도달 가능하므로 **이 괄호만 고친다**).

**상수 단언 grep**: 기존 단언 중 이 step이 건드리는 것만 갱신한다.
- `tests/test_vector_baseline.py:94-101`(`build_corpus(Source(), products)` 결과 id 집합 `{"youtube:a", "product:brand:https://example.invalid/p"}`와 `fields <= set(CORPUS_FIELDS)`): 규칙 인자 없이 부르면 불변이어야 한다(새 인자는 기본 빈 값).
- `tests/test_prereg.py:39`의 `== 16`: 17개가 되므로 `== 17`로 갱신하고 새 문장 존재 단언을 추가한다.
- `tests/test_prereg.py:64`의 `"표현 규칙 ID"` 포함 단언(16번째 문장): 16번째 문장에서 이 어구가 빠지므로 목록에서 제거하고 `"효능"`·`"카테고리"` 단언은 유지한다(한계가 약해지는 것이 아니라 코퍼스 변경으로 사실이 바뀐 것이다).
- `tests/test_e3_live.py`의 `corpus_loader` 주입 호출(`:375·511·598·638`)과 `report(...)` 호출·결과 키(`strata`·`size_strata` 등): 불변이다. `report`의 새 인자는 선택이다.
- `tests/test_schema_guard.py:480`의 `from test_e3_live import arm_options, question`: 이름·시그니처 불변이다.

**새 칸 대응표**: 규칙 문서(`rule_id`·`rule_type`·`group`·`applies_to`·`terms_ko`)(`config/claim_rules.yaml` → `load_claim_rules` → `build_corpus` → `CORPUS_FIELDS`·`extra_frozen`의 `CORPUS_FIELDS` 줄 → 사전 등록 문장), 문서 id = `rule_id`(코퍼스 문서 → `target_ids`의 "값이 문서 id" 규칙으로 CQ-11 정답 값과 대응 → `hit_at_k`·`recall_at_k`), `corpus_doc_ids.json`(`run` → 문서 id 목록만 → `report`의 도달 가능 부분집합), `reachable_subset`(`report` → 보고 JSON → 사전 등록 문장 17번).

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건(합성 테스트만). 규칙 문서는 YAML 파일 읽기뿐이고 임베딩 문서 수는 규칙 수(수십 건)만큼 늘어난다(토큰 영향 미미). 측정 실행은 사용자 승인 뒤에만 한다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 모델이 만든 값을 테스트 기대값으로 굳히지 않는다, 정답 접근은 step 8 "정답을 읽는 지점 표"의 셋뿐이다(B-FP-042), 새 SQL·Cypher 금지
- `/src/beautyads/eval/vector_baseline.py`(전체), `/src/beautyads/eval/e3_live.py`(전체), `/src/beautyads/eval/prereg.py`(`REQUIRED_SENTENCES`)
- `/src/beautyads/sources/claim_rules.py`·`/src/beautyads/domain/claims.py`(읽기 전용), `/src/beautyads/graph/layer1.py`(`:330-350`, 읽기 전용: 적재되는 범위 상태), `/src/beautyads/graph/queries.py`(`CQ-11`, 읽기 전용), `/config/claim_rules.yaml`(읽기 전용, 필드 형태 확인용)
- `/tests/test_vector_baseline.py`, `/tests/test_e3_live.py`, `/tests/test_prereg.py`, `/phases/6-eval/step8.md`·`/phases/6-eval/step13.md`(정답을 읽는 지점 표와 `target_ids`·`report` 규칙, 읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/vector_baseline.py`, `src/beautyads/eval/e3_live.py`, `src/beautyads/eval/prereg.py`, `tests/test_vector_baseline.py`, `tests/test_e3_live.py`, `tests/test_prereg.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/vector_baseline.py`, `src/beautyads/eval/e3_live.py`, `src/beautyads/eval/prereg.py`, `tests/test_vector_baseline.py`, `tests/test_e3_live.py`, `tests/test_prereg.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

E3 코퍼스에 표현 규칙 문서를 추가하고 도달 가능 부분집합 보고와 사전 등록 문장을 만든다. **모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: `_RULE_FIELDS`, `is_reachable`

**1. 규칙 문서(`eval/vector_baseline.py`)**
- `_RULE_FIELDS = ("rule_id", "rule_type", "group", "applies_to", "terms_ko")`(**이 순서**: 문서 길이 자르기가 `terms_ko`부터 잘라 규칙 ID·적용 대상이 남게 한다). `CORPUS_FIELDS`는 기존 두 튜플에 `_RULE_FIELDS`를 더한 같은 방식(`dict.fromkeys`로 중복 제거)으로 만든다. 기존 필드의 순서·값은 불변이다.
- `build_corpus(creative_source, product_source, *, run_tag="v1", rules=())`: `rules`(`ClaimRule` 시퀀스)마다 문서를 만든다. **문서 id는 `rule.rule_id` 그대로**다(예: `CR-011`). 값: `rule_id`, `rule_type`(문자열 값), `group`, `applies_to`(각 범위를 `"{kind}:{value}"` 문자열로, **그래프가 적재하는 범위 상태 `advisor_approved`·`confirmed`인 것만**: `graph/layer1.py:343`과 같은 기준이며 초안 상태 범위는 넣지 않는다), `terms_ko`. `_document`의 줄 형식(`key: json`)과 `rules=()`일 때의 기존 동작·문서 순서(최종 `docs.sort(key=id)`)는 불변이다.
- **상속을 펼치지 않는다**: 규칙 문서에는 그 규칙의 `applies_to`에 직접 적힌 범위만 들어가고, 카테고리·효능·피부 고민 사이의 관계나 다른 범위로의 확장을 넣지 않는다. 규칙 본문 원문(`source_items`)·예외 문구·영어 용어는 넣지 않는다(`_RULE_FIELDS`가 전부다).
- 규칙 문서 id가 다른 문서 id와 겹치면 기존 `CORPUS_ID_DUPLICATE`로 끝난다.

**2. 코퍼스 로드와 도달 가능 부분집합(`eval/e3_live.py`)**
- `load_corpus()`: `build_corpus(..., rules=load_claim_rules(Path("config/claim_rules.yaml")))`로 규칙을 넘긴다(`sources.claim_rules.load_claim_rules`는 기존 읽기이며 다른 모듈과 같은 경로 리터럴이다. 새 SQL·Cypher·새 읽기 메서드 없음). 읽기 실패는 기존 `ConfigError`를 `E3Error`의 고정 코드(`E3_CORPUS_RULES_INVALID`)로 바꿔 던진다(예외 문장에 경로·내용 없음).
- `is_reachable(truth, doc_ids) -> bool`: `set` 질문은 **정답 값이 모두** 문서 id(값 자체 또는 `product:*:{값}` 대응, `target_ids`와 같은 규칙)에 대응되고 `truth.evidence_ids`가 있으면 모두 `doc_ids`에 있을 때 참이다. `count` 질문은 `truth.evidence_ids`가 비어 있지 않고 모두 `doc_ids`에 있을 때 참이다. 그 밖은 거짓이다(코퍼스에 없는 효능·카테고리 값 정답 등).
- `run` 명령(main)이 코퍼스를 로드한 경우(`vector` 팔 포함) `output_dir / f"{mode}_corpus_ids.json"`에 `{"ids": [정렬된 문서 id]}`만 쓴다(문서 본문·정답 없음). 그래프 팔만 돌리는 실행은 파일을 쓰지 않는다.
- `report(records, questions, *, answers_path, split, corpus_doc_ids=None)`: 기존 결과 키·값은 불변이다. `corpus_doc_ids`가 주어지면 새 키 `reachable_subset` = `{"n_reachable": n, "n_total": m, <_summary 결과>, "status": ("undecidable" if n < MIN_STRATUM_N else "descriptive_only"), "decision": "undecidable"}`(참고용, 채택 판정 없음, 기존 `strata`와 같은 규칙)을 추가한다. 주어지지 않으면 `reachable_subset = {"status": "corpus_ids_missing"}`다. `report` 명령은 `{mode}_corpus_ids.json`이 있으면 읽어 넘긴다(없으면 `None`). 정답을 읽는 지점은 기존 `report`의 `read_answers(..., purpose="report")` 하나뿐이다.
- `measure`는 변경 없이 새 코퍼스를 쓰며(`target_ids`가 규칙 ID 값을 문서 id로 대응시킨다), `n_set_questions_values_not_in_corpus`는 그대로다. `extra_frozen`의 `CORPUS_FIELDS` 줄은 새 `CORPUS_FIELDS`를 자동으로 반영한다.

**3. 사전 등록 문장(`eval/prereg.py`)**
- 16번째 문장의 한계 어구 `현재 코퍼스 필드에 없는 값(표현 규칙 ID·효능·카테고리 값 등)`을 `현재 코퍼스 필드에 없는 값(효능·카테고리 값 등)`으로 고친다(규칙 ID는 이제 코퍼스에 있다). 다른 부분은 불변이다.
- `REQUIRED_SENTENCES` **끝에 17번째** 문장을 추가한다(기존 16개의 순서 불변): (a) E3 코퍼스에는 표현 규칙 문서가 포함되며 문서 id는 규칙 ID이고 규칙이 직접 걸리는 대상(`APPLIES_TO`, 그래프가 적재하는 범위 상태만)만 적고 상속 관계를 미리 펼치지 않는다(상속·범위 추론은 벡터 팔이 직접 해야 한다). (b) 코퍼스에서 도달 가능한 질문만의 부분집합 결과(`reachable_subset`)는 참고용이며 채택 판정(`graph_adopted` 등)은 기존 전체 질문 기준이다. (c) 코퍼스에 없는 값(효능·카테고리 값 등)을 정답으로 하는 질문은 도달 불가이며 한계로 적고 도달 가능 질문 수를 함께 보고한다.
- `render_preregistration`의 번호 매김·인덱스 참조는 바꾸지 않는다.

**테스트(합성 데이터·`tmp_path`, 모델·접속 없음)**
- `tests/test_vector_baseline.py`: (1) `rules` 없이 부른 `build_corpus`가 기존 결과와 같다(위 상수 단언 유지). (2) 합성 `ClaimRule`(실제 `ClaimRule` 모델로 만든 최소 유효 값) 2개가 문서 id `rule_id`로 들어가고 문서 줄 순서가 `_RULE_FIELDS` 순서이며 `terms_ko`가 마지막이다. (3) 초안(`draft`) 범위는 `applies_to`에 없고 `advisor_approved`·`confirmed` 범위만 있으며 각 문서에는 그 규칙의 범위만 있다(다른 규칙·다른 범위로 확장된 값이 없다: 상속 미전개). (4) `CORPUS_FIELDS`가 `_RULE_FIELDS`를 포함하고 문서 줄 필드 집합이 `CORPUS_FIELDS`의 부분집합이다. (5) 규칙 id가 기존 문서 id와 겹치면 `CORPUS_ID_DUPLICATE`.
- `tests/test_e3_live.py`: (6) `target_ids`가 규칙 ID 집합 정답(`evidence_ids` 빈 `set` 질문)을 규칙 문서 id로 대응시키고 `measure`의 `hit_at_k`·`recall_at_k`가 손으로 센 값과 같다(합성 코퍼스에 규칙 문서 포함). (7) `is_reachable`: 규칙 ID 집합·제품 링크 집합·소재 ID 집합 → 참, 코퍼스에 없는 값(효능 값)·`count` 증거 없음·일부 값만 대응 → 거짓. (8) `report(corpus_doc_ids=...)`의 `reachable_subset`이 `n_reachable`·`n_total`·`status`·`decision`을 규칙대로 내고 `corpus_doc_ids=None`이면 `{"status": "corpus_ids_missing"}`이며 기존 `overall`·`graph_questions`·`simple_search`·`strata`·`size_strata`·`size_vs_top_k`의 키·값이 불변이다. (9) `run` 명령이 `{mode}_corpus_ids.json`에 문서 id만 쓰고(문서 본문·정답 표식 없음) 그래프 팔만이면 쓰지 않으며 `report` 명령이 그 파일을 읽어 넘긴다. (10) `load_corpus`가 `load_claim_rules`를 통해 규칙을 넘기고(가짜 읽기·가짜 연결로) 규칙 읽기 실패가 `E3_CORPUS_RULES_INVALID`이며 예외에 경로가 없다. (11) 정답 표식(`SENTINEL_TRUTH` 등)이 가짜 `embed`·`chat`·`structured` 입력, 결과 파일, `corpus_ids.json`, 로그, 예외 메시지에 없고 `measure`의 `"test"` 요청은 여전히 `ANSWER_SPLIT_FORBIDDEN`이다. (12) 기존 테스트가 위 "상수 단언 grep"의 갱신 대상 외에는 그대로 통과한다.
- `tests/test_prereg.py`: `== 17`, 16번째 문장에서 `표현 규칙 ID`가 빠지고 `효능`·`카테고리`가 남음, 17번째 문장 존재(`규칙`·`APPLIES_TO`·`상속`·`참고용`·`전체 질문 기준`이 들어 있음).
- 합성 문장·분류 값·규칙 문구를 기대값으로 굳히지 않는다(형식·건수·id 대응·계산값만 검사).

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

- 규칙 문서에 상속·범위 확장(예: 카테고리에 걸린 규칙을 그 카테고리의 효능·피부 고민 문서로 복제, 다른 범위의 값 추가)을 넣거나 `source_items`·예외 문구·영어 용어를 넣지 마라. 이유: 상속 추론은 그래프의 강점이므로 벡터 팔이 직접 해야 한다(조언 세션 결정).
- 새 SQL·새 Cypher·`graph/`·`store/` 읽기 메서드를 만들거나 `config/claim_rules.yaml`을 수정하지 마라. 이유: 규칙은 기존 읽기(`sources.claim_rules.load_claim_rules`)만 쓴다(AGENTS.md, step 8). 필요하면 `blocked`로 보고한다.
- 판정 로직(`graph_adopted`·`not_adopted`·`undecidable`, `score_answer`, `set_f1`)이나 `TOP_K`·`MAX_DOC_CHARS`·`MAX_ANSWER_SET`의 값을 바꾸거나 `reachable_subset`으로 채택 판정을 하지 마라. 이유: 도달 가능 부분집합은 참고용이고 판정 기준은 동결되어 있다.
- 정답 값을 임베딩·`chat`·`structured` 호출 입력이나 출력·로그·예외 메시지·결과 파일·`corpus_ids.json`에 넣거나 새 정답 읽기 지점을 만들지 마라. 이유: 정답 접근은 `check_run`·`measure`(dev)·`report` 셋뿐이다(B-FP-042).
- `eval/evalset.py`·`eval/evalset_candidates.py`·`eval/freeze_guard.py`·`Makefile`·`graph/queries.py`를 수정하거나 새 의존성을 추가하지 마라. 이유: 허용 범위 밖이며 이미 완료된 step의 계약이다(필요하면 `blocked`로 보고).
- 기존 테스트의 단언을 약화하지 마라(위 "상수 단언 grep"에 적힌 갱신만 허용). 합성 문장·모델이 만든 값을 기대값으로 굳히지 마라. 이유: 이미 통과한 step의 계약이며 테스트는 형식과 코드가 하는 일을 검사한다(AGENTS.md CRITICAL).
