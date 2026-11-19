# Step 21: failure-as-worst

## 설계 검토 기록

**배경(조언 세션 승인)**: 단일 팔이 도구 결과에서 근거를 못 얻어 기획안을 내지 못한 경우(req-dev-0006, `status="no_evidence"`)가 있다. 현재 `e2_scoring.analyze`는 기획안이 없는 쌍을 지표별로 **제외**하고(독스트링 "Missing plans/scores are excluded per metric, never imputed") 건수만 보고하며 사전 등록 문장에도 이 규칙이 없다. 실패가 잦은 팔의 살아남은 표본만 평균하면 그 팔에 유리해진다. 이 step은 기획안을 시도했으나 내지 못한 경우를 **최저점으로 포함**한 결과를 주 판정으로 하고, 현행 완전 사례 분석을 민감도로 병기하며, 기록이 없는 항목은 `not_run`으로 따로 세어 제외하고, 팔별 기획 실패율을 보고하고, 사전 등록 문장을 추가한다. **판정 임계값(`MIN_E2_PAIRS`·`E5_MIN_*`·CI 기준)과 E5 토큰 합계 계산은 바꾸지 않는다.**

**식별자 전수 대조(현재 코드, 모두 열어 확인)**: `eval/e2_scoring.py`(`ARMS = ("supervisor","single","off")`·`MIN_E2_PAIRS = 10`·`E5_MIN_TOKEN_REDUCTION`·`E5_MIN_VALIDITY_LOWER`·`MIN_STRATUM_N`·`ArmRecord`(`status: Literal["plan","no_evidence","limit","failed","out_of_scope"]`, `plan: dict | None`; `_record`가 `plan`이 없으면 `status`를 결과의 `kind`로 두므로 **`status != "plan"`이면 `plan is None`이다**)·`_Scores`(`request_fit`·`distinctiveness`: `StrictInt`, `ge=1, le=5`)·`evidence_validity(record) -> float`(`plan is None`이면 `ValueError("EVIDENCE_UNDEFINED")`)·`blind_items`(기획안 없는 기록은 채점 항목에서 빠진다 → 실패한 팔의 점수 항목이 없다)·`reveal_scores`(요청 → 팔 → `{"status": "scored"|…, "request_fit", "distinctiveness", …}`)·`_paired_summary(diffs, total)`(`{"mean_diff", "ci", "n", "excluded"}`)·`_pairs(index, reqs, left, right, *, plans=False)`·`_descriptive`·`analyze(records, *, scores, requests, claim_matches=None) -> dict`: 결과 키 `confidence`·`e2`(`metrics`·`n`·`excluded`·`excluded_no_plan`·`descriptive`·`note`)·`verdict_e2`·`e5`(`token_reduction`·`on_input_tokens`·`off_input_tokens`·`n`·`excluded`·`excluded_no_plan`·`evidence_validity`·`descriptive`)·`verdict_e5`·`strata`·`claim_bias_check`), `eval/e2e5_live.py`(읽기 전용: `analyze(_plain(rows), …)`가 결과를 표로 출력), `eval/prereg.py`(`REQUIRED_SENTENCES`·`render_results_template`). **이 step은 step 20이 끝난 뒤 실행되며 `REQUIRED_SENTENCES`는 18개다.**

**상수 단언 grep**: `tests/test_e2_scoring.py`에서 이 step이 값을 바꾸는 단언은 다음뿐이다.
- `:439-456 test_exclusions_are_per_metric_and_small_sample_undecidable`: `metrics["evidence_validity"]["n"] == 10`·`["excluded"] == 2`·`metrics["request_fit"]["n"] == 9`·`["excluded"] == 3`·`verdict_e2 == "undecidable"`·`result["e2"]["excluded_no_plan"] == 1`은 **완전 사례 분석의 값**이다. 이 단언들을 새 키 `e2_complete_case`(같은 키 이름)로 옮겨 값은 그대로 유지하고, 같은 합성 입력의 주(최저점 포함) 결과를 **손으로 센 값으로 새로 단언**한다(n·excluded·`not_run`·`imputed_no_plan`; 부트스트랩이 판정에 개입하면 `bootstrap_ci`를 `monkeypatch`로 고정한다, `:491-524`의 방식). 약화가 아니라 의미가 갈라진 두 분석을 각각 단언하는 것이다.
- `:422-436 test_e2_verdict_branches`·`:470-524` E5 테스트(`verdict_e5`·`token_reduction`): 합성 입력에 기획 실패가 없으므로 주 결과와 완전 사례 결과가 같아 **불변**이다.
- `tests/test_prereg.py`의 문장 수(`== 18`)는 `== 19`로 갱신한다. 결과 틀 테스트에 새 행의 빈 칸 단언을 더한다.
- `eval/e2e5_live.py`의 `_report`는 `analyze` 결과의 모든 키를 출력하므로 새 키가 자동으로 출력된다(수정하지 않는다; `tests/test_e2e5_live.py`의 보고 테스트가 키 전체의 정확 일치를 단언하는지 확인하고 그렇다면 `blocked`로 보고한다).

**새 칸 대응표**: `WORST_REQUEST_FIT`·`WORST_DISTINCTIVENESS`·`WORST_EVIDENCE_VALIDITY`(상수 → 주 판정의 최저점 → 사전 등록 문장), `e2`·`e5`의 `not_run`·`imputed_no_plan`(`analyze` → 보고), `failure_rates`(기록 상태 → 보고), `e2_complete_case`·`e5_complete_case`·`verdict_*_complete_case`·`verdicts_agree`(완전 사례 민감도 → 보고 → 두 판정이 다르면 그대로 적는 사전 등록 문장).

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건(합성 테스트만).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 동결된 기준은 결과를 본 뒤 바꾸지 않는다(이 step은 판정 임계값을 바꾸지 않고 결측 처리만 정한다), 모델이 만든 값을 테스트 기대값으로 굳히지 않는다
- `/src/beautyads/eval/e2_scoring.py`(전체), `/src/beautyads/eval/prereg.py`(`REQUIRED_SENTENCES`·`render_results_template`), `/src/beautyads/eval/e2e5_live.py`(`_report`·`_plain`, 읽기 전용)
- `/tests/test_e2_scoring.py`(전체: `record`·`population`·`request` 헬퍼, `:405-600`), `/tests/test_prereg.py`, `/tests/test_e2e5_live.py`(보고 테스트, 읽기 전용 확인용), `/docs/EVAL.md`(E2·E5 절, 읽기 전용: 판정 기준 숫자는 불변)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/e2_scoring.py`, `src/beautyads/eval/prereg.py`, `tests/test_e2_scoring.py`, `tests/test_prereg.py`

열람 금지 경로: `data/interim/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `src/beautyads/eval/e2_scoring.py`, `src/beautyads/eval/prereg.py`, `tests/test_e2_scoring.py`, `tests/test_prereg.py`

E2·E5 분석이 기획안을 내지 못한 시도를 최저점으로 포함하게 하고 민감도·실패율·`not_run`을 보고하며 사전 등록 문장을 추가한다. **모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: `WORST_REQUEST_FIT`, `WORST_DISTINCTIVENESS`, `WORST_EVIDENCE_VALIDITY`

**1. 상수와 의미(`eval/e2_scoring.py`)**
- `WORST_REQUEST_FIT = 1`, `WORST_DISTINCTIVENESS = 1`, `WORST_EVIDENCE_VALIDITY = 0.0`. 앞의 둘은 `_Scores`의 하한(`ge=1`)과 같다(테스트가 `_Scores`가 1을 받고 0을 거부함으로 고정한다).
- **시도한 기록**: 한 팔의 기록(`ArmRecord`)이 있으면 그 요청을 그 팔이 시도한 것이다. `plan is None`(상태 `no_evidence`·`failed`·`limit`·`out_of_scope` 전부)이면 **기획안을 내지 못한 실패**다. **기록이 없는 항목**은 실행되지 않은 것(`not_run`)이다.
- **짝 규칙**: 비교하는 두 팔(E2: supervisor·single, E5: supervisor·off) 모두 기록이 있는 요청이 비교 대상 쌍이다(`_pairs(index, reqs, left, right)`와 같다). 어느 한 팔이라도 기록이 없는 요청은 `not_run`으로 **제외하고** 건수를 보고한다.

**2. 주 판정(최저점 포함, `analyze`의 기존 키가 이 값을 갖는다)**
- `evidence_validity`: 쌍마다 팔별 값 = 기획안이 있으면 `evidence_validity(기록)`, 없으면 `WORST_EVIDENCE_VALIDITY`. 차이 = 첫째 팔 − 둘째 팔. 모든 비교 대상 쌍이 들어간다.
- `request_fit`·`distinctiveness`(E2만): 팔별 값 = 기획안이 있으면 그 점수(`scores[요청][팔]`의 `status == "scored"`여야 한다), 없으면 `WORST_REQUEST_FIT`·`WORST_DISTINCTIVENESS`. **기획안이 있는데 채점 상태가 `scored`가 아닌 팔이 있는 쌍은 그 지표에서 제외**하고(채점 실패는 팔의 실패가 아니다) 건수를 `excluded`에 넣는다. 외부에서 읽은 점수는 기존처럼 `_Scores`로 검증해 쓴다.
- `e2`: `metrics`(위 값)·`n`(지표별 `n`의 최솟값)·`excluded`(`total - n`)·**`not_run`**(요청 수 − 비교 대상 쌍 수)·**`imputed_no_plan`**(`{"supervisor": 최저점으로 채운 쌍 수, "single": …}`)·`descriptive`·`note`는 기존과 같은 구조·의미(`descriptive`는 비교 대상 쌍 기준 불변)다. 기존 `excluded_no_plan` 키는 이 블록에서 제거하고 완전 사례 블록으로 옮긴다. `verdict_e2`는 이 주 결과로 기존 공식(`MIN_E2_PAIRS`·CI 하한 > 0 / 상한 < 0)으로 낸다.
- `e5`: 토큰 필드(`token_reduction`·`on_input_tokens`·`off_input_tokens`·`n`·`excluded`·`descriptive`)는 **바꾸지 않는다**(비교 대상 쌍의 합계, 실패한 기록의 토큰도 이미 포함). `evidence_validity`는 위 주 규칙의 요약, `imputed_no_plan`(`{"supervisor", "off"}`)·`not_run`을 더하고 `excluded_no_plan`은 완전 사례 블록으로 옮긴다. `verdict_e5`는 이 주 결과로 기존 공식으로 낸다.

**3. 민감도·실패율**
- `e2_complete_case`: 기존 계산 그대로(기획안이 있는 쌍만, 지표별 제외): `metrics`·`n`·`excluded`·`excluded_no_plan`·`verdict`. `verdict_e2_complete_case`도 함께 낸다. `e5_complete_case`: 같은 방식(`evidence_validity`·`excluded_no_plan`·`verdict`), `verdict_e5_complete_case`. `verdicts_agree`: `{"e2": bool, "e5": bool}`(주 판정과 완전 사례 판정이 같은지; 다르면 보고에 그대로 보이게 한다).
- `failure_rates`: 팔마다 `{"records": 기록 수, "no_plan": 기획안이 없는 기록 수, "rate": no_plan/records 또는 None, "by_status": {상태: 건수(plan 제외)}}`.
- 위 키 외의 기존 키(`confidence`·`strata`·`claim_bias_check`)는 불변이다. 독스트링을 새 규칙에 맞게 고친다("기획안이 없는 시도는 최저점으로 포함한다. 실행되지 않은 항목만 제외하고 보고한다").

**4. 사전 등록(`eval/prereg.py`)**
- `REQUIRED_SENTENCES` **끝에 19번째** 문장을 추가한다(기존 18개의 순서·문장 불변): (a) E2·E5의 주 판정은 기획안을 시도했으나 내지 못한 경우(근거 없음·실패·한도·범위 밖)를 최저점(요청 적합성 1점, 차별성 1점, 근거 유효율 0)으로 포함해 계산한다. (b) 실행되지 않은 항목(기록 없음)은 제외하고 건수를 보고한다. (c) 기획안이 있는 쌍만 쓰는 완전 사례 분석을 민감도로 함께 보고하며 두 판정이 다르면 그대로 적는다. (d) 팔별 기획 실패율을 보고한다. (e) 채점 실패로 점수가 없는 항목은 팔의 실패가 아니므로 그 지표에서 제외하고 건수를 적는다. `render_preregistration`의 번호 매김·인덱스 참조는 바꾸지 않는다.
- `render_results_template()`에 E2·E5 행으로 "팔별 기획 실패율"·"완전 사례 민감도 판정"·"실행되지 않은 항목 수"를 더한다(빈 칸 틀).

**테스트(합성 데이터, 모델·접속 없음)**
- `tests/test_e2_scoring.py`: (1) 위 "상수 단언 grep"의 갱신(완전 사례 단언을 `e2_complete_case`로 옮기고 주 결과를 손으로 센 값으로 단언). (2) 한 팔의 기획 실패가 주 결과에서 최저점으로 들어간다: 실패 쌍의 차이가 정확히 (`WORST_*` − 상대 팔 값)이다(세 지표). (3) 양쪽 팔이 모두 실패한 쌍은 차이 0으로 들어간다. (4) 기록이 없는 항목은 `not_run`으로 제외·집계되고 주 결과의 `n`에 들어가지 않는다. (5) 기획안이 있는데 채점이 `scored`가 아닌 팔이 있는 쌍은 `request_fit`·`distinctiveness`에서만 제외되고 `evidence_validity`에는 들어간다. (6) 상태별(`no_evidence`·`failed`·`limit`·`out_of_scope`) 실패가 모두 같은 규칙으로 취급되고 `failure_rates`의 `by_status`가 맞다. (7) 편향 시연: 한 팔이 일부 요청에서 기획 실패하고 남은 요청에서 상대보다 높은 점수를 받는 합성 입력에서 완전 사례 판정은 그 팔을 낫다고, 주 판정은 그렇지 않다고 나오며 `verdicts_agree["e2"]`가 `False`다(부트스트랩은 `monkeypatch`로 결정적으로). (8) **E5 토큰 합계 불변**: 같은 기록에서 한 팔을 실패로 바꿔도 `e5`의 `token_reduction`·`on_input_tokens`·`off_input_tokens`가 변경 전 계산과 같다(실패 여부와 무관). (9) 실패가 없는 합성 입력에서 주 결과와 완전 사례 결과가 같고 `verdicts_agree`가 모두 `True`다. (10) 상수 `WORST_*` 값과 `_Scores` 하한 일치.
- `tests/test_prereg.py`: (11) `== 19`와 19번째 문장 존재(`최저점`·`실행되지 않은`·`민감도`·`실패율`·`채점 실패` 포함), 기존 18개 불변. (12) 결과 틀에 새 행이 빈 칸으로 있다.
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

- 판정 임계값(`MIN_E2_PAIRS`·`E5_MIN_TOKEN_REDUCTION`·`E5_MIN_VALIDITY_LOWER`·`CI_CONFIDENCE`·`BOOTSTRAP_RESAMPLES`·`SCORING_SEED`)과 E5 토큰 합계·감소율 계산, `blind_items`·`score_plans`·`reveal_scores`·`bootstrap_ci`·`evidence_validity`의 동작을 바꾸지 마라. 이유: 동결된 기준이며 이 step은 결측 처리 규칙만 정한다.
- 기획안이 없는 시도를 제외하는 기존 동작을 주 판정으로 되돌리거나, 채점 실패를 최저점으로 처리하거나, 기록이 없는 항목을 최저점으로 채우지 마라. 이유: 최저점은 시도했으나 기획안을 내지 못한 경우에만 쓴다(사전 등록 규칙).
- `eval/e2e5_live.py`·`eval/e3_live.py`·`eval/evalset*.py`·`Makefile`을 수정하거나 새 의존성을 추가하지 마라. 이유: 허용 범위 밖이다(필요하면 `blocked`로 보고).
- `REQUIRED_SENTENCES`의 기존 문장을 고치거나 기존 테스트의 단언을 약화하지 마라(위 "상수 단언 grep"에 적힌 의미가 갈라진 단언의 이동·새 단언 추가만 허용). 이유: 사전 등록 문장은 기존 항목을 고치지 않고(B-FP-043) 이미 통과한 step의 계약이다.
