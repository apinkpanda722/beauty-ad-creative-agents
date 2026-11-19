# Step 5: e2-scoring

## 설계 검토 기록

**식별자 전수 대조(bb0e64f)**: `agents/evaluation.py:14 EVALUATION_PROMPT_VERSION`·`:33 _SYSTEM`·`:51 evaluate_plan`(루프 내 평가의 척도 문구는 읽기 전용, **E2 채점 루브릭은 이것과 다른 문장**), `llm/structured.py`(`StructuredSpec`·`StructuredGenerator.generate`), `obs/ledger.py`(`check_purpose_cap`·`purpose_total`·`read_entries`), `domain/plan.py`(`Plan`·`CheckCode.EVIDENCE_NOT_FOUND`·`EVIDENCE_NOT_IN_HANDOFF`·`CheckIssue.field`), `checks/plan_checks.py`(`_evidence_issues`가 `evidence_ids[i]` 꼴 `field`를 만든다), `eval/evalset.py`(step 2: `stratum`·`E1_UNMET_AXES`·`RequestItem`), `eval/single_agent.py`(step 4: 결과 dict 키), `eval/sheets.py`(사람 시트·설명 문서 선례, 읽기 전용), `tests/test_schema_guard.py`(`GUARDED_MODULES`·`test_no_new_structured_spec_module_without_a_guard`), `tests/test_llm_param_guard.py:259 test_evaluation_single_auto_tool_shape`(sonnet 구조화 모양, 읽기 전용).

**상수 단언 grep**: 새 상수(`BOOTSTRAP_RESAMPLES`, `SCORING_SEED`, `E2_SCORE_PURPOSE_CAP`, `MIN_STRATUM_N`, `E5_MIN_TOKEN_REDUCTION`, `E5_MIN_VALIDITY_LOWER`)를 단언하는 기존 테스트 없음. EVAL.md 동결 숫자(0.30·-0.05·95%)는 이름 있는 상수로 두고 테스트는 상수를 import해 경계값 위아래로 검사한다(`== 0.3`처럼 값을 굳히는 새 단언 금지, B-FP-061).

**새 칸 대응표**: `arm_hidden_id`·`order_seed`(이 step 채점기 → 결과 해제 단계·사람 시트 키), `claim_match`·`claim_match_note`(이 step 시트 생성 → 사용자 기입 → 이 step의 `load_claim_matches`·편향 점검 집계), `ArmRecord`(이 step 정의 → step 7 러너가 씀 → 이 step 분석이 읽음), `E2_SCORING_PROMPT_VERSION`·루브릭 sha256(이 step → step 10 사전 등록 동결 값), 결과 문서 항목(근거 유효율·점수·비용·지연·호출 수 → 결과 문서 §E2·§E5).

**조언 세션 결정**: E2 채점은 Anthropic sonnet, **팔 이름 숨김, 순서 섞기, 고정 시드, 루프 내 평가와 다른 루브릭·프롬프트**. 사람 "claim 일치" 판정 약 200건은 편향 점검용이다(주 판정이 아니다). 요청당 팔마다 1회(n=20), 부트스트랩 10,000회, 시드 고정. E5 (a)는 E2 Supervisor 실행을 재사용하되 **같은 코드 커밋·같은 세트 해시·같은 채점 실행**일 때만이다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 판정할 수 있는 것은 코드가, LLM 채점은 차별성·요청 적합성에만, 유료 호출 직전 공급사별 누적액 검사, `temperature` 지정 금지, 모델이 만든 문장을 테스트 기대값으로 굳히지 않는다
- `/docs/EVAL.md`(E2·E5 판정 기준과 한계, 읽기 전용), `/docs/results/p5_dev_compare_preregistration.md`(읽기 전용: 절차 문장 형식 선례), `/docs/results/2026-11-19-e1-scoring.md`(미충족 축 표시 방침)
- `/src/beautyads/agents/evaluation.py`(루프 내 평가 척도 문구와 스펙 구성, 읽기 전용), `/src/beautyads/llm/structured.py`, `/src/beautyads/obs/ledger.py`, `/src/beautyads/domain/plan.py`, `/src/beautyads/checks/plan_checks.py`
- `/src/beautyads/eval/evalset.py`, `/src/beautyads/eval/freeze_guard.py`, `/src/beautyads/eval/single_agent.py`(step 2·4 산출물), `/src/beautyads/eval/sheets.py`(읽기 전용), `/tests/test_schema_guard.py`, `/tests/test_llm_param_guard.py`(읽기 전용), `/tests/test_evaluation.py`(가짜 `structured` 방식 선례, 읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/e2_scoring.py`(새 파일), `tests/test_e2_scoring.py`(새 파일), `tests/test_schema_guard.py`(`GUARDED_MODULES`에 `eval/e2_scoring.py` 한 개 추가와 새 테스트 함수 추가에 한함, 기존 단언 약화 금지)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/e2_scoring.py`, `tests/test_e2_scoring.py`, `tests/test_schema_guard.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로, 평가 정답을 읽는 채점 함수)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

E2·E5의 **채점기, 사람 판정 시트, 통계(쌍 비교 부트스트랩)**를 `eval/e2_scoring.py`에 만든다. 실행기(step 7)가 쓰는 결과 형식 `ArmRecord`도 여기에 정의한다. **이 step 안에서는 모델을 부르지 않는다. 테스트를 먼저 쓴다.**

새 식별자: `ARMS`, `ArmRecord`, `E2_SCORING_PROMPT_VERSION`, `E2_RUBRIC`, `E2_SCORE_PURPOSE_CAP`, `SCORING_SEED`, `BOOTSTRAP_RESAMPLES`, `MIN_STRATUM_N`, `E5_MIN_TOKEN_REDUCTION`, `E5_MIN_VALIDITY_LOWER`, `blind_items`, `score_plans`, `reveal_scores`, `bootstrap_ci`, `evidence_validity`, `build_claim_sheet`, `load_claim_matches`, `analyze`, `RunIdentityMismatch`

**결과 형식 `ArmRecord`(pydantic, `extra="forbid"`)**: `run_id`, `item_id`(요청 id), `arm`(`ARMS = ("supervisor","single","off")`: Supervisor 켬·단일·Supervisor 끔), `tenant_id`, `status`(`plan`|`no_evidence`|`limit`|`failed`|`out_of_scope`), `plan: dict | None`(최종 기획안), `check_report: dict | None`(최종 시도 코드 검사 보고), `evidence_pool: list[str]`, `spent_usd: float`, `input_tokens: int`(원장 증가분 합), `model_calls: int`(원장 항목 수), `latency_s: float`, `tool_calls: int`, `limit_hit: bool`, `code_commit: str`, `evalset_hash: str`, `axes_used_observed: list[str]`(참고용, 층화 기준 아님).

**채점(조언 세션 결정, 사전 등록에 적는 절차)**
- `E2_RUBRIC`: 두 항목 `request_fit`(요청이 정한 카테고리·효능·제약을 지켰는가)과 `distinctiveness`(일반적인 광고 문구와 달리 구체적 차별점이 있는가), 1~5점. **루프 내 평가(`agents/evaluation.py`의 `_CRITERIA`·`_SYSTEM`)와 다른 문장·다른 척도 설명**으로 쓴다(테스트: 두 문자열 사이에 20자 이상 같은 부분 문자열 없음). `E2_SCORING_PROMPT_VERSION = "2026-11-19-1"`, 루브릭+시스템 프롬프트의 sha256은 step 10 사전 등록의 동결 값이다.
- `blind_items(records, *, requests, seed=SCORING_SEED) -> (items, key)`: 채점 입력은 **요청 문장 + 기획안의 텍스트 필드**(`title`·`hook_text`·`scenes`·`copy_lines`·`image_brief`·`hook_type`·`angle`·`format`·`claimed_efficacy`)만이다. 팔 이름·모델 이름·점수·코드 검사 결과·근거 ID·비용·지연은 넣지 않는다. 항목마다 익명 `arm_hidden_id`(예: `sha256(f"{seed}:{item_id}:{arm}")` 앞 12자리)를 붙이고, 순서는 `random.Random(seed)`로 섞는다(`SCORING_SEED = 20261126`). `key`(익명 ID→팔·요청)는 **채점 호출과 별도 경로**에 둔다.
- `score_plans(items, *, structured, ledger_path, purpose="e2-score")`: 항목마다 `check_purpose_cap(ledger_path, "e2-score", E2_SCORE_PURPOSE_CAP)`를 호출 **직전**에 검사하고(`E2_SCORE_PURPOSE_CAP = 1.5`), 닿으면 남은 항목을 `SCORING_CAP_REACHED`로 표시하고 멈춘다. `StructuredSpec("e2_scores", …)`(스키마: 정수 `request_fit`·`distinctiveness` 1~5, 문자열 `rationale` 200자 이내; OpenAI strict 검증기를 통과하는 모양, `agents/evaluation.py`의 스펙 구성 방식을 따른다), `reasoning_effort`는 지정하지 않고(`None`) `temperature`도 지정하지 않는다. 구조화 실패는 그 항목만 `SCORE_FAILED`로 기록하고 다음으로 넘어간다. `structured`는 주입되며 모델 ID는 `claude-sonnet-5-5`다(호출 옵션·키는 주입 래퍼가 합친다).
- `reveal_scores(scores, key) -> dict`: 채점이 끝난 뒤에만 팔을 되돌린다.

**통계**
- `bootstrap_ci(diffs, *, seed=SCORING_SEED, resamples=BOOTSTRAP_RESAMPLES, confidence=0.95)`: 요청 단위 쌍 차이의 평균에 대한 퍼센타일 신뢰구간(`random.Random(seed)`로 복원추출, `BOOTSTRAP_RESAMPLES = 10_000`, 표준 라이브러리만). 같은 입력·시드면 같은 결과. 빈 입력은 `ValueError("BOOTSTRAP_EMPTY")`.
- `evidence_validity(record) -> float`: 최종 기획안의 `evidence_ids` 중 `check_report` 이슈 코드 `EVIDENCE_NOT_FOUND`·`EVIDENCE_NOT_IN_HANDOFF`의 `field`(`evidence_ids[i]`)로 걸리지 않은 비율. 근거 ID가 비면 0.0(근거 없음은 유효하지 않다). 기획안이 없는 기록은 이 값이 정의되지 않으며 쌍에서 제외하고 제외 건수를 센다.
- `analyze(records, *, scores, requests, claim_matches=None) -> dict`: (1) **같은 실행 확인**: 모든 기록의 `code_commit`·`evalset_hash`가 같아야 하고 아니면 `RunIdentityMismatch`(E5 (a) 재사용 조건). (2) **E2**: `supervisor`와 `single`의 요청 쌍에서 `evidence_validity`·`request_fit`·`distinctiveness`의 차이(supervisor − single)와 95% CI, 쌍 수·제외 수. 판정 `verdict_e2`: 세 지표 중 CI 하한이 0보다 큰 것이 있고 상한이 0보다 작은 것이 없으면 `"supervisor_better"`, 상한이 0보다 작은 것만 있으면 `"single_better"`, 둘 다 있으면 `"mixed"`, 둘 다 없으면 `"no_difference_found"`("품질 차이를 확인하지 못했다"), 쌍이 10 미만이면 `"undecidable"`. 비용·지연(p50·p95, nearest-rank)·모델 호출 수·도구 호출 수는 팔별 평균과 차이 CI를 **서술용**으로만 낸다(판정 없음, "늘어난 비용·지연·호출 수를 대가로 그대로 적는다"). (3) **E5**: `supervisor`(켬)와 `off`(끔)의 요청 쌍에서 `입력 토큰 절감률 = 1 − Σ input_tokens(켬) / Σ input_tokens(끔)`과 `evidence_validity` 차이(켬 − 끔) 95% CI. 판정 `verdict_e5`: 절감률 ≥ `E5_MIN_TOKEN_REDUCTION`(0.30)이고 CI 하한 > `E5_MIN_VALIDITY_LOWER`(-0.05)면 `"cost_reduced_evidence_kept"`, 아니면 넘지 못한 쪽을 적은 `"not_met:<tokens|evidence|both>"`. (4) **층화 보조 분석**: 요청의 `stratum(axes_used)`(평가셋 항목의 **미리 정해진** `axes_used`, 관측값 아님)로 `reliable`/`unreliable` 두 층의 팔별 `evidence_validity` 평균과 건수를 따로 내고, 층의 요청 수가 `MIN_STRATUM_N`(5) 미만이면 그 층을 `"undecidable"`로 표시한다. 결론 근거가 아니라 표시용이며 `claims` 관련 항목은 "라벨 신뢰도 낮음"을 붙인다(κ 값은 결과 문서에서 읽고 이 코드에 적지 않는다). `claim_matches`가 있으면 팔별 `match`·`partial`·`no_match` 건수를 **편향 점검**으로 따로 싣는다(판정에 쓰지 않는다).

**사람 판정 시트(`build_claim_sheet(records, *, evidence_texts, seed, size=200, out_dir)`)**: 최종 기획안의 (기획안, 근거 소재 ID) 쌍을 모아 시드 고정으로 섞어 최대 `size`건을 뽑는다(`random.Random(seed)`). 파일 두 개를 **다른 경로**에 쓴다: `claim_sheet.csv`(열 `item_id`·`claim`·`evidence_text`·`claim_match`·`claim_match_note`; `item_id`는 익명, 팔·모델·점수·비용 없음)와 `claim_sheet_key.json`(익명 ID→팔·요청·근거 ID). `claim`은 기획안의 닫힌 값으로 코드가 만든 문장("훅 유형 {hook_type}·각도 {angle}·포맷 {format}, 효능 {claimed_efficacy}")이고 모델 자유 문장이 아니다. `evidence_text`는 호출한 쪽이 넘긴 소재 텍스트(제목·브랜드, 링크 제외)다. 설명 문서 `claim_sheet_instructions.md`를 함께 쓴다: **칸의 뜻, 칸별 기준, 예시 1개, 기록 방법**을 담는다 — `claim_match`는 `match`(근거 소재가 그 훅·각도·포맷 선택을 뒷받침), `partial`(일부만), `no_match`(무관·반대) 중 하나이고 빈 칸은 금지다. 판단이 모호하면 `partial`을 고르고 `claim_match_note`에 사유를 적는다. 예시 1개(합성 문장: claim "훅 유형 question·각도 problem·포맷 demo", evidence_text "건조한 피부 고민을 묻는 세럼 영상 제목" → `match`)와 기록 방법(CSV의 `claim_match`·`claim_match_note` 두 칸만 채우고 다른 칸은 고치지 않는다, 시트와 키 파일은 따로 보관)을 포함한다. 사람 판정은 1인 라벨링이며 결과에 "1인 라벨링"을 병기한다. `load_claim_matches(sheet_path, key_path)`는 값이 `match`·`partial`·`no_match`가 아니거나 빈 칸이면 고정 코드로 거부한다.

**`tests/test_schema_guard.py`**: `GUARDED_MODULES`에 `"eval/e2_scoring.py"`를 더하고 새 테스트 함수(이 모듈의 `StructuredSpec`이 strict 검증기를 통과, 검사한 스펙 수 0은 실패)를 추가한다. 기존 단언은 약화하지 않는다.

**테스트(`tests/test_e2_scoring.py`, 합성 데이터)**: 가짜 `structured`가 받은 `messages`를 직접 열어 (1) 팔 이름·모델 이름·점수·비용·코드 검사 결과·근거 ID 문자열이 입력에 없음(합성 `SENTINEL_ARM_…`), (2) 같은 시드에서 순서·익명 ID가 같고 다른 시드에서 달라짐, (3) 구조화 호출에 `reasoning_effort`·`temperature`가 없음, (4) 상한 직전 검사와 닿았을 때 멈춤·표시, (5) 항목 실패가 다음으로 넘어감, `bootstrap_ci`의 결정성·구간이 평균을 포함·분산 0 입력, `analyze`의 각 판정 분기(`supervisor_better`·`single_better`·`mixed`·`no_difference_found`·`undecidable`, E5 두 조건의 경계 위아래·`not_met` 분기), `RunIdentityMismatch`, 층 `MIN_STRATUM_N` 미만의 `undecidable`, 시트에 팔 이름이 없고 열이 정확히 5개이며 설명 문서에 네 항목이 있음, `load_claim_matches` 거부 사례, 제외 건수 집계. 기대값은 합성 입력에서 계산한 형식·분기이며 모델이 만든 점수를 굳히지 않는다.

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

- 채점 입력이나 호출 인자에 팔 이름·점수·코드 검사 결과·근거 ID·비용·지연을 넣거나 `key`를 같은 경로에 쓰지 마라. 이유: 팔 이름 숨김이 이 채점의 편향 방지 장치다(조언 세션 결정, B-FP-042).
- 루프 내 평가(`agents/evaluation.py`)의 척도 문구·프롬프트를 재사용하거나 그 파일을 고치지 마라. 이유: 시스템 안의 평가 루프와 채점은 달라야 자기 채점이 되지 않는다(조언 세션 결정). 동결 평가 프롬프트는 불변이다.
- EVAL.md의 숫자(0.30·-0.05·95%)를 바꾸거나 판정 분기를 결과가 마음에 들게 조정하지 마라. 이유: 기준은 동결돼 있고 못 넘은 결과도 그대로 보고한다(docs/EVAL.md 원칙, B-FP-043).
- 사람 판정 시트에 모델 자유 문장을 `claim`으로 쓰거나 판정 결과로 근거 유효율 주 지표를 대체하지 마라. 이유: 사람 판정은 편향 점검용이다. 주 지표의 존재 여부는 코드가 판정한다(AGENTS.md CRITICAL).
- 모델이 만든 점수·문장을 테스트 기대값으로 굳히지 마라. 이유: 정확도는 평가에서 재고 테스트는 형식과 코드가 하는 일만 검사한다(FP-C03).
