# Step 22: e2e5-repeats

## 설계 검토 기록

**배경(사용자 확정·조언 세션 승인)**: E2·E5를 **같은 요청을 팔마다 2회** 실행해 요청별로 평균하고, 요청을 단위로 부트스트랩(10,000회, 고정 시드)한다. 반복은 모델 비결정성의 영향을 줄이기 위한 것이다. E3(질문 40건)와 격리(200건)는 반복하지 않는다. 판정 기준(CI 하한 > 0, E5 30%·-0.05)과 임계값은 `docs/EVAL.md` 그대로다. **같은 입력(모든 기록의 `repeat == 1`)에서는 step 21까지의 결과와 숫자가 같아야 한다**(기존 테스트가 단언 변경 없이 통과하는 것이 그 증거다).

**식별자 전수 대조(현재 코드, 모두 열어 확인)**: `eval/e2_scoring.py`(`ARMS`·`SCORING_SEED = 20261126`·`BOOTSTRAP_RESAMPLES`·`WORST_*`(step 21)·`ArmRecord`(`extra="forbid"`; 칸 `run_id`·`item_id`·`arm`·…·`axes_used_observed`; **`repeat` 칸이 없다**)·`_records(records)`(중복 키 `(r.item_id, r.arm)` → `ARM_RECORD_DUPLICATE`)·`_check_requests`·`blind_items(records, *, requests, seed)`(`sorted(rows, key=(item_id, arm))`, 숨김 id = `sha256(f"{seed}:{item_id}:{arm}")[:12]`, 키 항목 `{"arm","item_id","run_id","code_commit","evalset_hash"}`, `order_seed`)·`score_plans`·`reveal_scores(scores, key)`(요청 → 팔 → `{**row, **source}`, 같은 요청·팔이 둘이면 `SCORING_KEY_INVALID`)·`bootstrap_ci`·`evidence_validity`·`_paired_summary(diffs, total)`·`_pairs(index, reqs, left, right, *, plans=False)`(키 `(item, arm)`)·`_descriptive`·`_check_identity(rows, scores)`(`index = {(r.item_id, r.arm): r}`, `scores` 항목의 `run_id`·`code_commit`·`evalset_hash` 비교, `scoring_run_id` 배치가 둘 이상이면 `RunIdentityMismatch`)·`_validity_summary`·`_e2_metrics(pairs, scores, total)`(`scores.get(item,{}).get(arm,{})`)·`_e2_verdict`·`_e5_verdict`·`_imputed_counts`·`_failure_rates`·`analyze(...)`(E5 토큰: `on_tokens, off_tokens = sum(pair[i].input_tokens for pair in e5_pairs)`)·`build_claim_sheet(records, *, evidence_texts, seed, size=200, out_dir)`(후보 = 기획안이 있는 기록의 `plan.evidence_ids` 고유 값마다 한 행, 숨김 id = `sha256(json.dumps([seed, item_id, arm, evidence_id]))[:12]`)·`load_claim_matches`), `eval/e2e5_live.py`(`_RecordedArm(ArmRecord)`(runner 전용 칸: `prereg_commit`·`prompt_versions`·`input_tokens_by_purpose`·`model_calls_by_purpose`·`brief_axes`·`dominant_axes`)·`_load_records`(중복 키 `(r.item_id, r.arm)`)·`_plain`(`ArmRecord.model_fields`만)·`_record(...)`·`_run_batch(...)`: `seen = {(r.item_id, r.arm) for r in rows}`, 순서 `for item in items: for arm in ARMS_DEFAULT:`, `previous_spend + ledger_total - baseline >= args.budget_usd`이면 `STOPPED BUDGET_REACHED`, 요청마다 `before = len(read_entries(...).entries)`·`ledger_delta`·`ledger_purpose_totals`·`records.jsonl`에 한 줄 추가·`_e5_supplement(rows, items)`(`index = {(r.item_id, r.arm): r}`로 요청 단위 짝)·`_axis_adherence(rows, items)`(기록 단위)·`_report`·`main`(인자 `command`·`--mode`·`--arms`·`--limit`·`--budget-usd`·`--dry-run`·`--run-id`·`--requests`; `run.json` 메타 `mode`·`identity`·`evalset_hash`·`item_ids`·`scoring_spent_usd`; dry-run `count = len(items) * len(args.arms)`; `DEV_SCORE_MAX_ITEMS` 검사), `eval/prereg.py`(`REQUIRED_SENTENCES` 19개: **3번째 문장 "반복 횟수는 요청당 팔마다 1회(요청 20건), …"**, 4번째 "사람 claim 일치 판정 약 200건…", 5번째 E5 (a) 재사용, 19번째 step 21 문장, `render_results_template`).

**상수 단언 grep**: 기존 테스트 중 이 step이 값을 바꾸는 것만 갱신하고 나머지는 약화하지 않는다.
- `tests/test_e2_scoring.py:176-186 test_blinding_whitelists_and_reproducible_shuffle`: 기대 숨김 id가 `sha256(f"{SEED}:{item_id}:{arm}")`이다 → `…:{arm}:{repeat}`(`repeat=1`)로 갱신한다(새 형식으로 일괄 전환, 최종 실행 전이라 옛 기록 호환 불필요). 같은 테스트의 나머지 단언(화이트리스트·시드 재현·팔 이름 숨김)은 그대로 유지한다.
- `tests/test_e2_scoring.py`의 점수 합성(`population()`의 `scores[req.id][arm] = {...}` 평면 구조)은 **그대로 통과해야 한다**: `analyze`는 평면 구조(`"status"` 키가 있는 딕셔너리)를 반복 1의 점수로도 받아들인다.
- `tests/test_e2_scoring.py:212` 부근의 `hashlib` 단언(`build_claim_sheet`의 숨김 id 형식): `repeat == 1`만 쓰므로 **형식 불변**이다.
- `tests/test_e2e5_live.py:233 test_arm_order_keyword_image_identity_and_resume`·`:291 test_budget_stops_before_next_arm_and_resume_counts_previous_spend`: `--repeat` 미지정(기본 1)에서 순서·재개·예산 동작이 불변이어야 한다. `:419` `scores.json` 읽는 부분은 새 구조(`{요청: {팔: {"1": 점수}}}`)에 맞게 갱신한다.
- `tests/test_prereg.py`: 문장 수 `== 19` → `== 20`, **문장 해시를 고정하는 기존 테스트가 세 곳**이다(선점검에서 확인된 사실): (a) `test_none_measurement_preserves_original_bytes`(`dev_measurement=None` 렌더링 전체의 SHA-256), (b) `test_first_seventeen_procedures_remain_byte_identical`(`:113-117`, `REQUIRED_SENTENCES[:17]`을 JSON으로 만든 SHA-256 — **3번째·4번째 문장이 이 범위에 있어 바뀐다**), (c) `test_failure_as_worst_procedure_is_nineteenth`(`:120-145`, `REQUIRED_SENTENCES[:18]`의 SHA-256 — 같은 이유로 바뀐다; 같은 테스트의 문구 단언은 유지하고 19번째 문장의 새 구절 단언을 더한다). **세 기대 해시 각각 한 줄씩만** 새 값으로 갱신한다(`uv run python`으로 계산). 이 해시들은 사전 등록 문서가 생성·커밋되기 전의 문장 수정을 막지 않으며(문서 생성 전이라 기존 문장 수정이 허용된다) 사전 등록 이후의 문장 변경을 막는 장치로 그대로 남는다. 각 테스트의 나머지 단언은 그대로 유지한다. 3·4·19번째 문장의 문구를 단언하는 기존 테스트가 있으면 새 문구로 갱신한다(구절을 더하는 변경이며 기존 의미를 약화하지 않는다).

**새 칸 대응표**: `ArmRecord.repeat`(runner `--repeat` → 기록 → 채점 숨김 id → 공개 키 → `analyze`의 요청별 평균), `run.json`의 `repeats`(최대 반복 수; 같은 `run_id`에 반복을 이어 실행), `--repeat N`(기본 1, 1~`MAX_REPEATS`), 점수 구조 `scores[요청][팔][반복 문자열]`(`reveal_scores` → `scores.json` → `analyze`), 사람 시트 `repeat == 1` 규칙(`build_claim_sheet` → 사전 등록 4번째 문장), `repeats`(`analyze` → 팔별 반복 분포 보고).

**비용(호출 수 기준, 실측 단가)**: 모델 호출은 사용자가 final 실행을 할 때만 나간다(이 step은 0건·접속 0건). 요청 20 × 팔 3 × 반복 2 = 120건 실행: 팔 평균(Supervisor $0.0074·단일 $0.0138·off $0.0075)로 약 $1.15, 채점 120건 × $0.00536 ≈ $0.64(채점 상한 $1.5 이내), 합계 약 $1.8(`--budget-usd` final 기본 3.0 이내; 예산은 생성+채점을 합산한다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 실제 호출은 사용자가 실행한다, 동결된 기준은 결과를 본 뒤 바꾸지 않는다(이 step은 판정 임계값을 바꾸지 않고 반복 집계 방식을 정한다), 모델이 만든 값을 테스트 기대값으로 굳히지 않는다
- `/src/beautyads/eval/e2_scoring.py`(전체), `/src/beautyads/eval/e2e5_live.py`(전체), `/src/beautyads/eval/prereg.py`(`REQUIRED_SENTENCES`·`render_results_template`), `/docs/EVAL.md`(E2·E5 절, 읽기 전용)
- `/tests/test_e2_scoring.py`(전체: `record`·`population`·`blind` 헬퍼), `/tests/test_e2e5_live.py`(전체: `rig`·`result`·`entry`), `/tests/test_prereg.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/e2_scoring.py`, `src/beautyads/eval/e2e5_live.py`, `src/beautyads/eval/prereg.py`, `tests/test_e2_scoring.py`, `tests/test_e2e5_live.py`, `tests/test_prereg.py`

열람 금지 경로: `data/interim/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로 `data/interim/e2e5/`)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `src/beautyads/eval/e2_scoring.py`, `src/beautyads/eval/e2e5_live.py`, `src/beautyads/eval/prereg.py`, `tests/test_e2_scoring.py`, `tests/test_e2e5_live.py`, `tests/test_prereg.py`

E2·E5 실행·채점·집계에 반복(repeat)을 도입하고 사전 등록 문장을 갱신한다. **모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: `MAX_REPEATS`, `_scores_by_repeat`, `_request_groups`

**1. 기록·채점(`eval/e2_scoring.py`)**
- `ArmRecord.repeat: int = Field(default=1, ge=1)`(`extra="forbid"` 유지; 기본값이 있어 이 칸이 없는 기록도 읽힌다). `_records`의 중복 키는 `(item_id, arm, repeat)`다.
- `blind_items`: 정렬 키 `(item_id, arm, repeat)`, 숨김 id = `sha256(f"{seed}:{item_id}:{arm}:{repeat}")` 앞 12자(`repeat == 1`도 이 새 형식), 공개 키 항목에 `"repeat": row.repeat`를 더한다. 나머지(팔 이름·모델 이름 숨김, 화이트리스트, `random.Random(seed).shuffle`, `order_seed`, `BLIND_ID_COLLISION`)는 불변이다. 채점 항목은 반복마다 따로다(기획안이 있는 기록 하나당 한 항목).
- `reveal_scores`: 결과 구조를 `revealed[요청][팔][str(반복)] = {**row, **source}`로 한다. 같은 (요청, 팔, 반복)이 둘이면 `SCORING_KEY_INVALID`.
- `_scores_by_repeat(scores, item, arm) -> dict[int, dict]`: `scores.get(item, {}).get(arm)`을 읽는다. **`"status"` 키가 있는 딕셔너리(평면 구조)면 `{1: 그 값}`**, 키가 반복 번호(문자열 또는 정수)인 딕셔너리면 `{int(k): v}`, 그 밖은 `{}`다. `analyze`·`_check_identity`가 이 함수를 쓴다(기존 테스트의 평면 점수 합성이 그대로 통과한다).
- `_check_identity`: 색인 키를 `(item, arm, repeat)`로 하고 점수 항목의 `run_id`·`code_commit`·`evalset_hash`·`scoring_run_id` 검사는 반복별로 같은 규칙을 적용한다.
- `build_claim_sheet`: **`repeat == 1`인 기록만** 후보로 쓴다(반복 2 이상은 사람 판정 표본에서 제외). 행 단위(기획안의 근거 소재마다 한 행)·숨김 id 형식·`size=200` 상한 규칙은 불변이다.
- `_request_groups(rows, reqs, left, right) -> list[tuple[str, list[ArmRecord], list[ArmRecord]]]`: 요청 id 오름차순으로 두 팔 모두 **기록이 하나 이상** 있는 요청의 (id, 왼쪽 팔 기록들(반복 오름차순), 오른쪽 팔 기록들)을 돌려준다. 어느 팔이든 기록이 없으면 `not_run`이다.

**2. 집계(`analyze`): 요청 단위, 반복은 먼저 반복 단위로 처리한 뒤 평균**
- 팔의 요청 값 = 그 팔의 반복별 값의 평균(`fmean`). 반복별 값: `evidence_validity`는 기획안이 있으면 `evidence_validity(기록)`, 없으면 `WORST_EVIDENCE_VALIDITY`. `request_fit`·`distinctiveness`는 기획안이 없으면 `WORST_*`, 있으면 그 반복의 점수(`status == "scored"`; 아니면 **그 반복만 그 지표에서 뺀다**). 한 팔의 모든 반복이 빠지면 그 요청은 그 지표에서 제외(`excluded`)된다. 차이 = 왼쪽 팔 평균 − 오른쪽 팔 평균, **부트스트랩 입력은 요청별 차이 하나씩**이다(`_paired_summary`·`bootstrap_ci`·시드·10,000회 불변).
- `e2`·`e5`: `n`은 요청 수, `not_run`은 한 팔이라도 기록이 없는 요청 수다. `imputed_no_plan`은 팔별로 **기록(반복) 단위**로 센 기획안 없는 기록 수(비교 대상 요청 안)다. **`repeats`**(새 키, 최상위): 팔(`ARMS`)별 `{"records": 기록 수, "requests": 기록이 하나 이상인 요청 수, "per_request": {"1": 반복이 1개인 요청 수, "2": …}}`.
- **완전 사례(`e2_complete_case`·`e5_complete_case`)**: 요청마다 팔의 값 = **기획안이 있는(그리고 점수가 `scored`인) 반복만** 평균한다. 한 팔에 그런 반복이 하나도 없으면 그 요청은 제외(`excluded_no_plan`)한다. 키·구조는 step 21과 같다.
- **E5 토큰**: 요청마다 팔의 값 = 그 팔의 반복별 `input_tokens` 평균, `on_input_tokens`·`off_input_tokens` = 비교 대상 요청에 대한 합계, `token_reduction = 1 - on/off`(off가 0이면 `None`)다. `n`은 비교 대상 요청 수다. E5 근거 유효율은 위 규칙의 요약이다. `_descriptive`(비용·지연·호출 수·도구 호출 수)의 팔별 요약은 모든 기록, 팔 간 차이는 요청별 반복 평균의 차이다.
- `failure_rates`·`strata`·`claim_bias_check`: 기록(반복) 단위이며 구조 불변이다. 독스트링을 갱신한다.
- **불변식**: 모든 기록의 `repeat == 1`이면 결과의 숫자·키가 step 21까지와 같다(새 키 `repeats` 제외).

**3. 실행기(`eval/e2e5_live.py`)**
- `MAX_REPEATS = 5`. `--repeat N`(정수, 기본 1, 1~`MAX_REPEATS`): `run`과 `--dry-run`에서만 받고 다른 명령(`score`·`sheet`·`report`)에서 주거나 범위 밖이면 `ARGUMENT_ERROR`다.
- 실행 순서: `for repeat in 1..N: for item in items: for arm in ARMS_DEFAULT:`(**반복이 바깥**이라 예산이 끊겨도 반복 1이 먼저 완성된다). 재개 키 `seen = {(r.item_id, r.arm, r.repeat) for r in rows}`, `_load_records`의 중복 키도 `(item_id, arm, repeat)`다. `--repeat`를 지정하지 않으면 기존 순서·동작과 같다.
- 두 번째 이후 반복은 **새 호출**이다(호출 캐시·시드 재사용 없음: 모델 비결정성이 반복의 목적이다). 반복 사이 원장 증가분은 기존 `before = len(read_entries(...).entries)` 방식으로 기록마다 분리된다(요청이 순차이므로 섞이지 않는다). 예산 검사(생성+채점 지출 합산)·중단 코드는 불변이다.
- `_record(...)`가 `repeat`를 받아 기록에 싣는다. `run.json`에 `"repeats"`를 두고(생성 시 `args.repeat`), 기존 `run.json`이 있으면 `max(기존 값, args.repeat)`로 갱신해 저장한다(같은 `run_id`에 반복을 이어서 실행 가능). `--dry-run`의 `request_arm_count`·`generation_calls_assumed`·비용 추정은 반복 수를 곱하고 `repeats`를 출력에 싣는다.
- `_e5_supplement`: 짝 키를 `(요청, 반복)`으로 하고(같은 반복 번호의 supervisor·off 기록끼리) `plan_per_request` 항목에 `repeat`를 더한다. `_axis_adherence`는 기록 단위라 불변이다. `_report`는 `analyze` 결과의 새 키(`repeats`)를 그대로 출력한다. `score`·`sheet` 흐름은 새 `blind_items`·`build_claim_sheet`를 그대로 쓴다(`DEV_SCORE_MAX_ITEMS` 검사 불변).

**4. 사전 등록(`eval/prereg.py`)**
- **3번째 문장 갱신**(사전 등록 문서 생성 전이라 기존 문장 수정이 허용된다; 이유를 이 step이 기록한다): "반복 횟수는 요청당 팔마다 2회(요청 20건 × 2회, 같은 요청을 팔마다 2회 실행해 요청별로 평균한다), 쌍 비교 부트스트랩의 단위는 요청이며 10,000회(퍼센타일 95%), 시드는 코드 상수 값, 기준 판정은 CI가 0을 넘는지(하한 > 0)로 한다. 반복은 모델 비결정성의 영향을 줄이기 위한 것이며 판정 기준은 `docs/EVAL.md` 그대로다."
- **4번째 문장 갱신**: 기존 문구를 유지하고 "사람 claim 일치 판정은 반복 1의 기획안(요청 × 팔)만 대상으로 하며 근거 소재마다 한 행이고 표본이 200행을 넘으면 고정 시드로 뽑는다"를 더한다.
- **19번째 문장 갱신**: 기존 문구를 유지하고 "우리 요청은 전부 지원 범위 안이므로 범위 밖(`out_of_scope`) 분류도 실패로 센다"를 더한다.
- **끝에 20번째 문장 추가**(기존 19개의 순서 불변): 반복마다 따로 채점하며 팔 이름 숨김·순서 섞기·고정 시드를 유지하고 숨김 id에 반복 번호를 반영한다. 최저점 규칙은 반복 단위로 먼저 적용한 뒤 요청별로 평균한다. 한 팔의 반복이 일부만 없으면 있는 반복만 평균하고 어느 팔이든 반복이 하나도 없으면 실행되지 않은 항목으로 센다. E5 입력 토큰은 요청별 반복 평균이고 E5 (a)는 E2 Supervisor의 두 반복을 모두 재사용한다(같은 코드 커밋·세트 해시·채점 실행). E3와 격리는 반복하지 않는다.
- `render_results_template()`의 E2 행에 "요청당 반복 수(팔별 분포)"를 더한다(빈 칸 틀).

**테스트(합성 데이터·`tmp_path`, 모델·접속 없음)**
- `tests/test_e2_scoring.py`: (1) 위 "상수 단언 grep"의 갱신(숨김 id 형식에 반복 번호). (2) 새 `blind_items`: 같은 요청·팔의 반복 1·2가 서로 다른 숨김 id를 갖고 공개 키에 `repeat`가 있으며 팔 이름·모델 이름이 채점 입력에 없다. (3) `reveal_scores`의 3단 구조와 중복 시 `SCORING_KEY_INVALID`. (4) `_scores_by_repeat`: 평면 구조·반복 구조·빈 값. (5) 반복이 모두 1인 합성 입력에서 `analyze` 결과가 변경 전과 같다(숫자·키, 새 키 `repeats` 제외). (6) 반복 2 합성 입력에서 요청별 평균·차이·`n`·`excluded`·`not_run`이 손으로 센 값과 같다(부트스트랩은 `monkeypatch`로 고정). (7) 한 반복만 기획 실패인 요청은 그 반복이 최저점으로 들어간 평균이고, 한 팔의 모든 반복이 실패면 그 팔의 값이 최저점이다(주 판정); 완전 사례에서는 기획안이 있는 반복만 평균되고 모든 반복이 실패면 제외된다. (8) 한 팔의 반복이 일부만 있으면 있는 반복만 평균되고 반복이 0이면 `not_run`이다. (9) 한 반복의 채점이 `scored`가 아니면 그 반복만 그 지표에서 빠진다. (10) E5 토큰이 요청별 반복 평균의 합으로 계산되고 `token_reduction`이 손으로 센 값과 같다. (11) `repeats` 분포. (12) `build_claim_sheet`가 `repeat == 1` 기록만 쓴다(반복 2 기록의 근거 소재가 시트·키에 없다). (13) `ARM_RECORD_DUPLICATE`가 `(item, arm, repeat)` 중복에만 난다.
- `tests/test_e2e5_live.py`: (14) `--repeat 2`로 실행하면 가짜 `ask`가 요청·팔마다 2번 불리고 기록에 `repeat` 1·2가 있으며 실행 순서가 반복이 바깥이다(반복 1이 모든 요청·팔을 먼저). (15) 두 번째 반복이 첫 번째의 결과·시드를 재사용하지 않는다(가짜 `ask`가 반복마다 새 호출을 받고 같은 객체를 돌려주지 않는다). (16) 반복 사이 원장 증가분이 기록마다 분리된다(합성 원장). (17) 같은 `run_id`에 `--repeat 1`로 실행한 뒤 `--repeat 2`로 이어 실행하면 반복 1은 건너뛰고 반복 2만 실행하며 `run.json`의 `repeats`가 2다. (18) 예산이 반복 1 도중 소진되면 반복 2는 시작하지 않는다. (19) `--repeat 0`·`6`·`score --repeat 2`는 `ARGUMENT_ERROR`, `--dry-run`의 요청×팔×반복 수와 `repeats` 출력. (20) `score`가 반복마다 항목을 만들고 `scores.json`이 3단 구조이며 `report`가 `repeats`를 출력한다. (21) `_e5_supplement`가 같은 반복 번호끼리 짝짓는다. (22) `--repeat` 미지정 동작·기존 테스트 불변.
- `tests/test_prereg.py`: (23) `== 20`, 3·4·19번째 문장의 새 구절(`2회`·`요청`·`반복 1`·`out_of_scope` 포함)과 20번째 문장 존재, 위 해시 기대값 한 줄 갱신. (24) 결과 틀에 새 행이 빈 칸으로 있다.
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

- 판정 임계값(`MIN_E2_PAIRS`·`E5_MIN_TOKEN_REDUCTION`·`E5_MIN_VALIDITY_LOWER`·`CI_CONFIDENCE`·`BOOTSTRAP_RESAMPLES`·`SCORING_SEED`·`WORST_*`)과 `bootstrap_ci`·`evidence_validity`·`score_plans`의 동작, 판정 공식(`_e2_verdict`·`_e5_verdict`)을 바꾸지 마라. 이유: 동결된 기준이며 이 step은 반복 집계 방식만 정한다.
- 두 번째 반복이 첫 번째 반복의 모델 응답·호출 결과·시드를 재사용하게 하거나 반복 사이 원장 증가분을 합치지 마라. 이유: 모델 비결정성이 반복의 목적이고 입력 토큰·비용은 기록 단위로 분리되어야 한다.
- 사람 claim 시트의 후보에 반복 2 이상을 넣거나 시트 형식·숨김 id 형식·지침 문서를 바꾸지 마라. 이유: 사람 판정은 반복 1로 고정한다(조언 세션 결정).
- E3·격리 실행기와 `eval/e3_live.py`·`eval/isolation_live.py`·`eval/evalset*.py`·`Makefile`을 수정하거나 새 의존성을 추가하지 마라. 이유: 허용 범위 밖이며 E3·격리는 반복하지 않는다(필요하면 `blocked`로 보고).
- 기존 테스트의 단언을 약화하지 마라(위 "상수 단언 grep"에 적힌 형식·구조·문구와 위 세 곳의 해시 기대값 한 줄씩 갱신만 허용). 이유: 이미 통과한 step의 계약이다.
