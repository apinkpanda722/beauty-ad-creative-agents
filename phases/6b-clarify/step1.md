# Step 1: clarify-core

## 설계 검토 기록

**배경(조언 세션 승인, 이슈 #55)**: E2 최종 실행에서 효능이 제품과 맞지 않는 요청 24회 중 Supervisor가 요청 효능을 살린 경우가 0회였고 17회는 근거 있는 다른 효능으로 조용히 바뀌었다(경고 없음). 사용자가 확정한 동작: ① 효능 지정 있음 + 근거 확인됨 → 바로 초안 ② 효능 지정 있음 + 근거 없음 → 임의로 바꾸지 않고 경고 후 마케터가 선택 ③ 효능 지정 없음 → 시스템이 고르지 않고 묻는다. 이 step은 **판정과 상태만**(코드, 모델 호출 추가 없음)이다. 되묻기 응답의 HTTP·SSE 표현은 step 2, 기획·평가 프롬프트는 step 3이다.

**식별자 전수 대조(현재 코드, 모두 열어 확인)**:
- `agents/supervisor.py`: `:145 class SupervisorState(TypedDict)`(키 11개 `sv_message`·`sv_decision`·`sv_brief`·`sv_handoff`·`sv_results`·`sv_index`·`sv_status`·`sv_steps`·`sv_trims`·`sv_tool_outputs`·`sv_spent`), `:171 initial_supervisor_state(message, limits)`, `:285 build_supervisor_graph(*, ctx, profile, feedback, decide_fn, research_fn, plan_eval_fn, spent_fn, limits, on_event, claims_fn, context_mode)`, 노드 `interpret`(`SupervisorDecision.model_validate(decide_fn(...))` → `boundary`/`category None`이면 `out_of_scope` → `ResearchBrief`를 `goal·category·claim·hook_type·angle·format·skin_concern`(+`output: "both"`)로 만듦), `research`(현재 `:395-425`에서 `intent == "plan"` 이고 `handoff["status"] == "ok"` 이고 `evidence_ids`가 있고 `claims_fn is not None`일 때만 `claims_fn(deepcopy(profile))` 호출, 상태 `"ok"|"failed"|"skipped"` 검증, `ok`면 `Claim`에서 `other`를 뺀 값만 순서 유지 중복 제거, 예외는 `([], "failed")`), `plan`, `run_request(*, message, ctx, profile, feedback, decide_fn, research_fn, plan_eval_fn, spent_fn, limits, on_event, claims_fn, context_mode)`와 그 결과 딕셔너리(`:560-625`: `kind`·`intent`·`brief`·`handoff`·`available_efficacy`·`available_efficacy_status`·`product_display`·`pattern_distribution`·`aggregates_label`·`aggregates_removed`·`plans`·`prompt_versions`·`limit_hit`·`limit_kinds`·`limit_detail`·`limits`·`incomplete`·`text`·`input_trims`·`steps`·`tool_outputs`·`event_errors`·`disclaimer`).
- `domain/supervisor.py`: `SupervisorDecision`(`claim: Claim | None`), `Intent`, `RequestLimits`, 기존 문구 상수(`OUT_OF_SCOPE_TEXT` 등), `trim_handoff`. `domain/labels.py`: `Claim`(`hydration`·`soothing`·`brightening`·`firming_elasticity`·`pore_sebum`·`acne_trouble`·`barrier`·`anti_aging`·`sun_protection`·`texture_finish`·`other`).
- `api/assembly.py`: `:277 def ask(message, ctx, profile, feedback, with_image, on_event=None, *, context_mode="on")` 안에서 `:346 claims_fn(profile)`(`own_product_url`이 없거나 공백이면 `([], "skipped")`, 그 밖에는 `Claim`(other 제외) 10개마다 `GraphEfficacySupport.efficacy_support`를 부르고 하나라도 `last_error`가 있으면 `([], "failed")`, 아니면 `supported`인 값들과 `"ok"`)와 `:483 run_request(...)` 호출(`context_mode`는 `**({"context_mode": context_mode} if context_mode != "on" else {})` 형태로 조건부 전달).
- `GraphEfficacySupport.efficacy_support`는 `supported`·`unknown`만 돌려준다(`agents/lookups.py:63`). 코드는 "약함"과 "없음"을 구분하지 못하며 둘 다 "근거가 확인되지 않음"이다.

**지금 코드와 이 step 요구의 충돌 지점(이미 확인함, 아래 "수정할 파일"에 갱신 허용을 넣었다)**:
- `tests/test_supervisor.py`의 `SupervisorState` 키 집합 정확 일치(`keys == {...11개...}`)와 `node_count == 5` 근처 단언, `test_claims_lookup_only_runs_once_for_plan_with_evidence`(`no_evidence` 사례가 `claims_fn` 호출 0회를 단언; 새 구조에서는 `decide` 직후 호출하므로 `plan`·`no_evidence` 둘 다 1회), `test_claims_status_is_safe_and_never_changes_evaluation_decisions`(`mode="ok"`에서 `decision_data()`의 `claim`이 `None`이라 새 규칙으로는 ③ 되묻기가 된다).
- `tests/test_domain_supervisor.py`의 `decision_data`(기본 `claim: None`)는 바꾸지 않는다(소비자가 많다). 새 테스트는 `decision_data(claim=...)`로 쓴다.
- `tests/test_api_assembly.py::test_assembled_claims_function_uses_only_existing_support_query`: `mode="ok"`는 새 규칙에서 ③ 되묻기(요청 효능 없음 + 확인 효능 있음)가 된다 → 그 테스트에서 `services.ask(..., claim_choice={"mode": "none"})`로 호출하게 갱신한다(이 step에서 `assembly.ask`가 `claim_choice`를 받는다). 단언(쿼리 목록·`available_efficacy`·`plans[0]["status"] == "done"`)은 그대로 둔다.
- `tests/test_supervisor_context_mode.py`와 그 밖의 테스트 중 `claims_fn`을 넘기지 않는 것은 **동작이 바뀌지 않아야 한다**(`claims_fn is None`이면 새 규칙을 전혀 적용하지 않는다).

**사전 결함(이미 확인함, 이 step과 무관)**: `tests/test_isolation_live.py`는 `NOW = datetime(2026, 11, 19, tzinfo=UTC)`(`:26`)로 기준일을 고정하는데 코드(`api/feedback.py:67 created_at=datetime.now(UTC)`, `eval/isolation_live.py:172·580`)는 실제 시계를 쓴다. 실행일이 2026-11-20(UTC)로 넘어가면서 피드백 생성일이 기준일보다 뒤가 되어 **변경 없는 main 코드에서도** 이 파일의 테스트 13건 이상이 `SETUP_INCOMPLETE`로 실패한다(`make verify` 실패). 그래서 이 step의 허용 목록에 이 파일을 **합성 시계 고정에 한해** 넣는다: 테스트 안에서 `datetime.now`를 쓰는 모듈(`beautyads.api.feedback`·`beautyads.eval.isolation_live`)의 시계를 `NOW`로 고정하는 방식(모듈 속성 교체)을 쓰고, `src/`는 바꾸지 않으며 기존 단언은 약화하지 않는다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: `tenant_id`는 세션에서만 나온다(요청 입력에 테넌트 칸을 두지 않는다), LangGraph 상태에는 dict·기본 타입만, 모델이 만든 값을 테스트 기대값으로 굳히지 않는다
- `/docs/ADR.md`(ADR-006·009), `/docs/PROMPT_CHANGELOG.md`(읽기 전용)
- `/src/beautyads/agents/supervisor.py`(전체), `/src/beautyads/domain/supervisor.py`, `/src/beautyads/domain/labels.py`(`Claim`), `/src/beautyads/domain/research.py`(`ResearchBrief`, 읽기 전용), `/src/beautyads/api/assembly.py`(`ask`·`claims_fn`·`run_request` 호출부)
- `/tests/test_supervisor.py`(전체), `/tests/test_domain_supervisor.py`, `/tests/test_supervisor_context_mode.py`, `/tests/test_api_assembly.py`(`test_assembled_claims_function_uses_only_existing_support_query`)

## 작업

**수정할 파일**: `src/beautyads/domain/supervisor.py`, `src/beautyads/agents/supervisor.py`, `src/beautyads/api/assembly.py`, `tests/test_domain_supervisor.py`, `tests/test_supervisor.py`, `tests/test_supervisor_context_mode.py`, `tests/test_api_assembly.py`, `tests/test_isolation_live.py`

열람 금지 경로: `data/interim/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `src/beautyads/domain/supervisor.py`, `src/beautyads/agents/supervisor.py`, `src/beautyads/api/assembly.py`, `tests/test_domain_supervisor.py`, `tests/test_supervisor.py`, `tests/test_supervisor_context_mode.py`, `tests/test_api_assembly.py`, `tests/test_isolation_live.py`

Supervisor가 `decide` 직후(같은 `interpret` 노드 안)에 요청 효능과 확인된 효능을 비교해 ①②③을 가르고, 되묻기 상태를 결과에 싣는다. **새 노드·새 모델 호출 없음. 테스트를 먼저 쓴다(TDD).**

새 식별자: `ClaimChoice`, `ClarifyReason`, `ClarifyOption`, `resolve_claim_policy`, `clarification_texts`, `CLARIFY_REQUESTED_TEXT`, `CLARIFY_REQUESTED_NO_CONFIRMED_TEXT`, `CLARIFY_UNSPECIFIED_TEXT`, `OPTION_KEEP_REQUESTED`, `OPTION_SELECT_CONFIRMED`, `OPTION_SELECT_ONE`, `OPTION_SELECT_MANY`, `OPTION_NONE`, `EFFICACY_NOTICE_TEXT`, `sv_efficacy`, `sv_claim_choice`, `sv_clarification`, `sv_efficacy_notice`

**1. 도메인(`domain/supervisor.py`, 표준 라이브러리·pydantic만)**
- 문구 상수(한 곳, 테스트가 문자열을 그대로 고정한다). **사용자가 확정한 문구**(바꾸지 않는다):
  - `CLARIFY_REQUESTED_TEXT = "요청하신 '{requested}' 효능은 이 제품의 성분·인증으로 근거가 확인되지 않았습니다. 확인된 효능은 {available}입니다. 어떻게 진행할까요?"`
  - `CLARIFY_UNSPECIFIED_TEXT = "효능을 지정하지 않으셨습니다. 이 제품에서 근거가 확인된 효능은 {available}입니다. 어떤 효능을 강조할까요?"`
  - `OPTION_KEEP_REQUESTED = "요청하신 '{requested}'로 진행 (효능을 단정하는 표현은 제한됩니다)"`, `OPTION_SELECT_CONFIRMED = "확인된 효능 중에서 선택"`, `OPTION_SELECT_ONE = "한 가지 효능 선택"`, `OPTION_SELECT_MANY = "여러 효능 선택"`, `OPTION_NONE = "효능 강조 없이 제품 홍보"`
  - `EFFICACY_NOTICE_TEXT = {"lookup_unconfirmed": "효능 근거를 확인하지 못해 효능 강조 없이 작성했습니다.", "none_confirmed": "이 제품에서 근거가 확인된 효능이 없어 효능 강조 없이 작성했습니다."}` — `lookup_unconfirmed` 문구는 사용자 확정, **`none_confirmed` 문구와 아래 `CLARIFY_REQUESTED_NO_CONFIRMED_TEXT`는 이 step에서 새로 정한 초안**이다(조언 세션 확인 대상, 문구만 바꾸면 되도록 상수 한 곳에 둔다).
  - `CLARIFY_REQUESTED_NO_CONFIRMED_TEXT = "요청하신 '{requested}' 효능은 이 제품의 성분·인증으로 근거가 확인되지 않았습니다. 이 제품에서 근거가 확인된 효능이 없습니다. 어떻게 진행할까요?"`
- `class ClarifyReason(StrEnum)`: `requested_not_confirmed`, `no_claim_requested`. `class ClarifyOption(StrEnum)`: `keep_requested`, `select_confirmed`, `select_one`, `select_many`, `none`.
- `class ClaimChoice(BaseModel)`(`extra="forbid"`): `mode: Literal["selected", "keep_requested", "none"]`, `claims: list[Claim] = []`, `requested_claim: Claim | None = None`. 검증(구조 오류는 `ValidationError`): `Claim.other`는 `claims`·`requested_claim` 어디에도 불가, `claims` 중복 불가, `selected`는 `claims`가 1개 이상, `keep_requested`는 `requested_claim`이 있어야 하고 `claims`가 비어 있어야 함, `none`은 `claims`가 비어 있어야 함. **테넌트·사용자·날짜 칸을 두지 않는다**(ADR-009).
- `resolve_claim_policy(*, requested: str | None, available: list[str], status: str, choice: dict | None) -> dict`: 순수 함수(모델 호출·입출력 없음). 입력 `requested`는 `Claim` 값 문자열이며 `"other"`는 `None`으로 본다(분류에 없는 효능은 "지정 없음"으로 취급, 이 처리는 이 함수 안에서만). `choice`는 `ClaimChoice.model_dump(mode="json")`이거나 `None`이다. 반환 딕셔너리 키는 정확히 `{"action", "claim", "claim_choice", "notice", "clarification"}`(JSON 기본 타입만):
  - `action`: `"proceed" | "clarify" | "invalid"`. `claim`: 리서치 `brief`에 넣을 효능(`str | None`). `claim_choice`: 기획·평가에 전달할 `ClaimChoice` 형태의 dict 또는 `{}`. `notice`: `None | "lookup_unconfirmed" | "none_confirmed"`. `clarification`: `{}` 또는 `{"reason", "requested_claim", "available_efficacy", "available_status", "options"}`(`options`는 `ClarifyOption` 값 문자열 목록).
  - 규칙(순서대로): (a) `status != "ok"`(조회 실패·건너뜀): `choice`는 무시, `action="proceed"`, `notice="lookup_unconfirmed"`, `claim=requested`, `claim_choice`는 `requested`가 있으면 `{"mode": "keep_requested", "claims": [], "requested_claim": requested}`, 없으면 `{"mode": "none", "claims": [], "requested_claim": None}`. (b) `status == "ok"`이고 `choice`가 있을 때: `selected`는 `claims`가 모두 `available`에 있어야 하며 아니면 `action="invalid"`(`claim=None`·`claim_choice={}`·`clarification={}`), 맞으면 `proceed`, `claim=claims[0]`, `claim_choice`는 입력 그대로. `keep_requested`는 `requested`(함수 인자, 호출자가 `choice.requested_claim`으로 덮어쓴 값)가 있어야 하며 없으면 `invalid`, 있으면 `proceed`, `claim=requested`. `none`은 `proceed`, `claim=None`, `claim_choice={"mode": "none", "claims": [], "requested_claim": None}`. (c) `status == "ok"`이고 `choice`가 없을 때: `requested`가 `available`에 있으면 ①: `proceed`, `claim=requested`, `claim_choice={"mode": "selected", "claims": [requested], "requested_claim": requested}`. `requested`가 있고 `available`에 없으면 ②: `clarify`, `reason=requested_not_confirmed`, `options`는 `available`이 있으면 `[keep_requested, select_confirmed, none]`, 비어 있으면 `[keep_requested, none]`. `requested`가 없고 `available`이 있으면 ③: `clarify`, `reason=no_claim_requested`, `options=[select_one, select_many, none]`. `requested`가 없고 `available`이 비면: `proceed`, `claim=None`, `claim_choice={"mode": "none", "claims": [], "requested_claim": None}`, `notice="none_confirmed"`.
  - `clarification.available_efficacy`는 `available` 그대로, `available_status`는 `"ok"`, `requested_claim`은 `requested`(③은 `None`).
- `clarification_texts(clarification: dict, display: Mapping[str, str]) -> dict`: `{"text": str, "options": [{"id": str, "label": str}]}`를 돌려주는 순수 함수. `display`는 `Claim` 값 → 표시 이름이며 도메인은 표시 이름을 모른다(호출하는 쪽, step 2의 `api`가 `analysis.prompts`에서 넘긴다). 목록은 `", "`로 잇는다. `reason`·`available_efficacy` 유무에 따라 위 세 문구를 고른다(②에서 확인 효능 0개면 `CLARIFY_REQUESTED_NO_CONFIRMED_TEXT`, 선택지 라벨은 `OPTION_*`에 `{requested}`를 표시 이름으로 채움). `display`에 없는 값은 값 문자열 그대로 쓴다.

**2. 감독자(`agents/supervisor.py`)**
- `SupervisorState`에 키 4개를 더한다: `sv_efficacy: dict`(`{"available": [...], "status": "..."}`), `sv_claim_choice: dict`, `sv_clarification: dict`, `sv_efficacy_notice: str | None`. 기존 키·`AgentState`·`ResearchState`·`PlanEvalState`의 키와 겹치지 않아야 한다(`sv_` 접두사 유지). `initial_supervisor_state(message, limits)`는 시그니처 그대로 두고 네 키의 빈 기본값(`{"available": [], "status": "skipped"}`, `{}`, `{}`, `None`)을 넣는다.
- `build_supervisor_graph(..., claim_choice=None)`·`run_request(..., claim_choice=None)`: 키워드 인자 하나를 더한다. 값이 있으면 `ClaimChoice.model_validate`로 읽고(실패하면 `ValueError("CLAIM_CHOICE_INVALID")`를 그래프 시작 전에 던진다; API는 step 2에서 이 경우를 이미 422로 걸러 낸다) `model_dump(mode="json")`한 dict를 클로저로 쓴다.
- `interpret` 노드(새 노드 없음): 기존 `decision` 검증·`out_of_scope` 분기 뒤, `ResearchBrief`를 만들기 **전에** 다음을 한다. **`claims_fn is not None`이고 `decision["intent"] == "plan"`일 때만** 적용하며 그 밖에는 지금 동작을 바이트 단위로 유지한다.
  1. 요청 효능 `requested`: `claim_choice`의 `requested_claim`이 있으면 그 값으로 `decision["claim"]`을 덮어쓴다(재 decide는 비결정적이므로 클라이언트가 확인한 값을 따른다). 없으면 `decision["claim"]`.
  2. `available, status`를 구한다: 기존 `research` 노드의 `claims_fn` 처리 블록(상태 검증 `ok|failed|skipped`, `ok`일 때만 `Claim`(other 제외) 순서 유지 중복 제거, 예외는 `([], "failed")`, 진단 문자열 비노출)을 **이 노드로 옮긴다**(복사하지 말고 한 곳의 헬퍼로). `state["sv_efficacy"]`에 저장한다.
  3. `resolve_claim_policy(requested=..., available=..., status=..., choice=...)`를 부른다. `invalid`면 `state["sv_status"]["kind"] = "claim_choice_invalid"`(실패 코드·`incomplete` 설정 없음)로 `END`. `clarify`면 `state["sv_clarification"]`에 저장하고 `kind = "needs_clarification"`로 `END`(리서치·기획 호출 0회). `proceed`면 `state["sv_claim_choice"]`·`state["sv_efficacy_notice"]`를 저장하고 `decision["claim"] = policy["claim"]`로 맞춘 뒤 기존 흐름(`state["sv_decision"] = decision`, `ResearchBrief`, `kind`)을 이어 간다. 결과의 `sv_decision`은 맞춘 값이다.
- `research` 노드: `claims_fn`을 **부르지 않는다**. `handoff["available_efficacy"]`·`["available_efficacy_status"]`는 이전과 같은 조건(`intent == "plan"`이고 `handoff["status"] == "ok"`이고 `evidence_ids`가 있고 `claims_fn is not None`)일 때만 `state["sv_efficacy"]`의 값을 쓰고, 그 밖에는 `[]`·`"skipped"`(기존과 같음).
- `run_request` 결과 딕셔너리에 키 3개를 더한다: `"clarification": state["sv_clarification"]`, `"efficacy_notice": state["sv_efficacy_notice"]`, `"claim_choice": state["sv_claim_choice"]`. 기존 키는 그대로. `kind`가 `needs_clarification`이면 `handoff`는 `{}`이므로 `available_efficacy`는 `state["sv_efficacy"]`에서 읽는다(결과의 `available_efficacy`·`available_efficacy_status`가 그 요청의 값이 되도록; `needs_clarification`·`claim_choice_invalid`일 때만 이 출처를 쓰고 그 밖에는 기존 출처를 유지). `text` 칸은 새 kind에서 `""`.
- `plan()` 노드와 기획·평가 입력은 **바꾸지 않는다**(step 3이 `claim_choice`를 입력에 싣는다).

**3. 조립(`api/assembly.py`, 통과 전달만)**: `ask(message, ctx, profile, feedback, with_image, on_event=None, *, context_mode="on", claim_choice=None)`에 키워드 인자를 더하고, `run_request(...)` 호출에 `**({"claim_choice": claim_choice} if claim_choice is not None else {})`(기존 `context_mode`와 같은 조건부 전달 형태)로 넘긴다. 그 밖의 조립 로직은 바꾸지 않는다.

**테스트(합성 데이터, 모델·접속 없음)**
- `tests/test_domain_supervisor.py`: (1) `resolve_claim_policy` 표 테스트: 위 규칙 (a)(b)(c)의 모든 가지(① 요청 효능이 목록 안, ② 목록 밖·확인 효능 있음/0개, ③ 지정 없음·확인 효능 있음, 지정 없음·0개, 조회 `failed`·`skipped`에서 요청 있음/없음, `choice` 세 mode의 정상·`invalid`, `requested == "other"`가 `None`으로 취급됨)을 손으로 쓴 기대 딕셔너리와 정확 일치로 단언한다. 반환 키 집합이 정확히 5개다. 검사한 사례 수가 0이면 실패한다. (2) `ClaimChoice` 검증: 위 구조 규칙 위반 각각이 `ValidationError`, `other`·중복·모드 불일치·테넌트 같은 추가 키 거절. (3) 문구 상수가 위 문자열과 정확히 같고(사용자 확정 문구 고정), `clarification_texts`가 ②(확인 효능 있음·0개)·③ 각각에서 표시 이름 매핑을 써서 기대 문장·선택지 id/라벨 목록과 같다.
- `tests/test_supervisor.py`: (4) ② ③ 되묻기 경로: 가짜 `decide`·`claims_fn`으로 `kind == "needs_clarification"`, `research_calls == []`, `plan_calls == []`, `clarification`이 기대 딕셔너리, `handoff == {}`, `available_efficacy`·`available_efficacy_status`가 요청의 값, 호출 순서에 `"research"`·`"plan"`이 없다. (5) ① 바로 진행(`claim`이 목록 안)과 `claims_fn=None`일 때 결과가 이전과 같다(`clarification == {}`, `efficacy_notice is None`, `claim_choice == {}`). (6) `choice`가 있는 재호출: `selected`가 확인 효능의 부분집합이면 진행하고 리서치 `brief["claim"]`이 `claims[0]`, 부분집합이 아니면 `kind == "claim_choice_invalid"`이고 리서치 0회, `keep_requested`는 `requested_claim`으로 `decision["claim"]`을 덮어써 리서치 `brief["claim"]`이 그 값, `none`은 `brief["claim"]`이 `None`. 재 decide가 다른 `claim`을 내도 `requested_claim`이 우선한다. (7) `failed`·`skipped`·예외: 되묻지 않고 진행하며 `efficacy_notice == "lookup_unconfirmed"`, `available_efficacy == []`, 진단 문자열이 결과에 없다. (8) `intent`가 `pattern`·`relation`·`boundary`이면 `claims_fn`을 부르지 않는다. (9) `claims_fn`이 `decide` 직후 한 번만 불리고 리서치 노드에서 불리지 않는다(`plan`·`no_evidence` 사례 모두 1회). (10) 기존 단언 갱신: `SupervisorState` 키 집합에 새 네 키만 더하고(정확 일치 유지), `test_claims_lookup_only_runs_once_for_plan_with_evidence`의 `no_evidence` 호출 횟수 기대를 `[profile]`로 바꾸며(결과의 `available_efficacy`는 `[]`·`"skipped"` 그대로), `test_claims_status_is_safe_and_never_changes_evaluation_decisions`의 `mode == "ok"` 호출은 `decision_data(claim="hydration")`로 요청 효능이 확인 효능 안에 있게 한다(① 경로). 나머지 단언은 약화하지 않는다.
- `tests/test_supervisor_context_mode.py`: 위 변경으로 깨지는 단언이 있으면(`claims_fn`을 쓰는 것에 한함) 새 키 하나만 더하는 갱신만 허용한다. 없으면 수정하지 않는다.
- `tests/test_api_assembly.py`: 위 충돌 지점대로 해당 테스트 한 개만 `claim_choice={"mode": "none"}`로 호출하게 갱신하고 `assembly.ask`가 `claim_choice`를 `run_request`에 넘기는 케이스 하나(가짜 `run_request`가 받은 인자 검사, `None`이면 인자 자체가 없음)를 더한다. 다른 테스트는 건드리지 않는다.
- 합성 문장·분류 값을 기대값으로 굳히지 않는다(닫힌 값·문구 상수·건수·구조만 검사).

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

- `SupervisorDecision`·`ResearchBrief`·`decide`의 스키마·프롬프트·`_SYSTEM`을 바꾸지 마라. `ClaimChoice`는 모델에 보내는 구조화 스펙이 아니라 요청 입력 모델이다. 이유: 구조화 스키마는 strict 가드(`tests/test_schema_guard.py`)와 사전 등록 동결 줄의 대상이다(FP-C15). 이 step에서는 해석 프롬프트 버전·해시가 변하지 않아야 한다.
- `agents/planning.py`·`agents/evaluation.py`·`agents/plan_eval.py`를 수정하거나 `plan()`에서 기획·평가 입력에 `claim_choice`를 싣지 마라. 이유: 입력·프롬프트 변경은 step 3의 몫이고 프롬프트 버전 단언(`tests/test_planning.py`·`tests/test_evaluation.py`)이 걸려 있다(FP-C11).
- `claims_fn is None`인 호출에는 새 규칙(되묻기·안내·`claim_choice`)을 적용하지 마라. 이유: `claims_fn`을 넘기지 않는 기존 테스트와 평가 경로의 결과를 바이트 단위로 보존해야 한다. 되묻기 경로(`needs_clarification`·`claim_choice_invalid`)는 리서치·기획 모델 호출이 0회임을 테스트가 호출 기록으로 단언해야 하며, 검사한 사례가 0건이면 실패다(B-FP-069).
- 요청 입력·`ClaimChoice`·상태·결과에 테넌트·사용자·오늘 날짜 칸을 만들지 마라. 사용자 확정 문구 상수(`CLARIFY_REQUESTED_TEXT`·`CLARIFY_UNSPECIFIED_TEXT`·`OPTION_*`·`lookup_unconfirmed` 문구)의 글자를 바꾸지 마라. 이유: 테넌트는 세션에서만 나온다(ADR-009). 문구는 사용자가 확정했다.
- `tests/test_isolation_live.py`는 시계 고정에 한해서만 고쳐라(`NOW`를 오늘 날짜로 바꾸거나 단언·기대값·건수를 바꾸지 마라). 이유: 사전 결함이 날짜에 따라 다시 깨지지 않게 고정하는 것이 목적이고 격리 검사의 판정 규칙은 건드리지 않는다.
- 기존 테스트의 단언을 약화하지 마라. 허용: `SupervisorState` 키 집합에 새 키 4개를 더하는 갱신(정확 일치 유지), 위에 적은 `claims_fn` 테스트 두 개와 `test_assembled_claims_function_uses_only_existing_support_query`의 호출·기대 갱신. 이유: 새 키·새 호출 위치가 만드는 정확 일치 충돌이다(FP-C11). 모델이 만든 문장·분류 값을 기대값으로 굳히지 않는다(FP-C03).
