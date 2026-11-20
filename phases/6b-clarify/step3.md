# Step 3: clarify-prompts

## 프롬프트 초안 (조언 세션 확인 대상, 확인 전에는 이 step을 실행하지 않는다)

### A. payload 키(`claim_choice`)

`plan()` 노드가 기획·평가 입력용 `handoff` 사본(`bounded`)에 `claim_choice`를 싣는다(트림 뒤, `context_mode`가 `on`이든 `off`이든). 값은 step 1의 `state["sv_claim_choice"]`이며 비어 있으면(`{}`; `claims_fn`이 없거나 `intent`가 plan이 아님) 키를 싣지 않는다. 기획 payload와 평가 payload의 **최상위**에 `"claim_choice"` 키를 **항상** 둔다(값이 없으면 `null`). 형태:

| mode | 의미 | `claims` | `requested_claim` | 기획이 하는 일 |
|---|---|---|---|---|
| `selected` | ① 요청 효능이 확인됨, 또는 ③/② 선택 뒤 마케터가 확인된 효능을 고름 | 확인된 효능 1개 이상(모두 `available_efficacy` 안) | 요청 효능 또는 `null` | `claims`를 소구 중심으로, `claimed_efficacy = claims` |
| `keep_requested` | ② 근거 없는 요청 효능을 그대로 살리기로 함(조회 실패·건너뜀일 때 요청 효능이 있어도 같은 mode) | `[]` | 요청 효능(`other`일 수 있음) | 요청 효능을 소구 방향으로, 단정 표현 금지, `claimed_efficacy`는 확인된 값만(보통 `[]`) |
| `none` | 효능 강조 없이 제품 홍보(선택 또는 확인 효능 0개 또는 조회 실패·요청 없음) | `[]` | `null` | 효능을 앞세우지 않고 제품 자체를 홍보, `claimed_efficacy = []` |

값이 `null`이면(`claims_fn` 없음, 또는 `intent`가 plan이 아님) `brief.claim`이 `available_efficacy` 안에 있으면 그 효능을 소구와 `claimed_efficacy`의 중심으로 하고, 그렇지 않으면 `available_efficacy` 안의 값만 `claimed_efficacy`에 넣는다(요청 효능을 다른 효능으로 바꾸지 않는다).

### B. 기획 `_SYSTEM`: 바꾸는 기존 문장(`agents/planning.py:29-31`)과 교체 문장

기존(지운다):
> "claimed_efficacy에는 입력의 available_efficacy(코드가 확인한 효능)에 있는 값만 넣는다. 확인된 효능이 목록에 없으면 주장하지 않고 빈 목록으로 둔다. 목록이 비어 있으면 빈 목록이다. "

교체(이 자리에 들어가는 새 문장들; `tests/test_planning.py`가 시스템 지시에서 확인하는 기존 낱말 `available_efficacy`·`확인된 효능`·`빈 목록`은 그대로 들어 있다):
> "claimed_efficacy에는 입력의 available_efficacy(코드가 확인한 효능)에 있는 값만 넣는다. 확인된 효능이 아닌 값은 어떤 경우에도 넣지 않고, 확인된 효능이 없으면 빈 목록이다. "
> "소구 방향과 claimed_efficacy는 따로 정한다. 소구 방향은 마케터가 정한 claim_choice를 따르고, claimed_efficacy는 코드가 확인한 효능만 담는다. "
> **(나) 분리 문장**: "요청한 효능이 확인된 효능이 아니어도 요청 효능을 근거 있는 다른 효능으로 바꾸지 않는다. 소구 방향은 요청 효능으로 두고, claimed_efficacy에만 확인된 값을 넣는다. "
> **(가-기획) keep_requested**: "claim_choice.mode가 keep_requested이면 마케터가 근거가 확인되지 않은 효능을 요청했다. 요청한 효능(claim_choice.requested_claim, 그 값이 other이면 brief.goal의 효능 표현)을 hook_text·copy_lines의 소구 방향으로 살린다. 단 그 효능이 제품에서 확인된 것처럼 단정하는 표현(효과가 입증됐다·확실하다·보장한다·치료한다 등)은 쓰지 않고 사용 장면과 느낌을 말하는 표현을 쓴다. claimed_efficacy에는 요청한 효능을 넣지 않고 available_efficacy 안의 값만 넣으며 없으면 빈 목록이다. 효능을 사실처럼 암시하는 표현도 쓰지 않는다. "
> **(다-복수) selected**: "claim_choice.mode가 selected이면 claims의 효능이 소구의 중심이다. claims가 여러 개이면 한 안에서 모두 다루되 첫 번째 효능을 앞세운다. claimed_efficacy에는 claims를 그대로 넣는다(모두 available_efficacy 안의 값이다). "
> **(다-없음) none**: "claim_choice.mode가 none이면 효능을 강조하지 않고 제품 자체(사용감·제형·사용 장면·브랜드)를 홍보한다. 입력과 그래프에서 확인되지 않은 사용감·제형·성분은 지어내지 않는다. 효능 이름을 앞세운 카피를 쓰지 않고 claimed_efficacy는 빈 목록이다. "
> "claim_choice가 null이면 위 규칙을 쓰지 않는다. brief.claim이 있고 그 값이 available_efficacy 안에 있으면 그 효능을 소구와 claimed_efficacy의 중심으로 하고, 그렇지 않으면 available_efficacy에 있는 값만 claimed_efficacy에 넣는다. "

(마지막 문장은 `claims_fn`이 없는 경로·`context_mode`의 이전 동작을 보존하되, 요청 효능이 확인된 효능이면 그것을 중심으로 삼게 한다. 조언 세션 확정 문장: 문장 4 끝 "효능을 사실처럼 암시하는 표현도 쓰지 않는다.", 문장 6의 "입력과 그래프에서 확인되지 않은 사용감·제형·성분은 지어내지 않는다.", 문장 7의 `brief.claim` 규칙.) 나머지 `_SYSTEM`(`image_brief`·`hook_text`·`rework`·데이터 규칙·`TOOL_DATA_RULE`·`PARTIAL_RESULT_RULE`)은 글자 그대로 둔다. `PLANNING_PROMPT_VERSION`: `"2026-11-18-3"` → **`"2026-11-20-1"`**.

### C. 평가 `_SYSTEM`: 추가 문장(`agents/evaluation.py`, `"rationale은 한국어 200자 이내로 쓴다. "` 바로 앞에 삽입; 기존 문장·`_CRITERIA`는 글자 그대로)

> "입력의 claim_choice는 마케터가 정한 효능 방향이다(mode는 selected·keep_requested·none, null이면 없음). 요청 적합성은 brief와 claim_choice에 비추어 판단한다. "
> **(가-평가) keep_requested**: "claim_choice.mode가 keep_requested이면 plan.claimed_efficacy가 비어 있어도 감점하지 않는다. claimed_efficacy는 코드가 확인한 효능만 담기 때문이다. 대신 요청한 효능(claim_choice.requested_claim, other이면 brief.goal의 효능 표현)이 hook_text·copy_lines·scenes의 소구 방향에 반영됐는지로 요청 적합성을 판단한다. 효능을 단정하는 표현이 있으면 rationale에 사실만 한 문장으로 적는다(규칙 위반 판정은 코드가 한다). "
> "claim_choice.mode가 selected이면 claims의 효능이 소구에 반영됐는지, none이면 효능을 앞세우지 않고 제품 자체가 중심인지로 요청 적합성을 판단한다. 이 두 경우도 claimed_efficacy가 비어 있음 자체는 감점 사유가 아니다(selected는 claimed_efficacy에 claims가 들어 있어야 한다). "
> "claim_choice가 null이면 이전처럼 brief 기준으로 판단한다. "

`EVALUATION_PROMPT_VERSION`: `"2026-11-18-2"` → **`"2026-11-20-1"`**. 평가 payload의 `criteria`(`differentiation`·`fit`)·`plan` 키 목록은 바뀌지 않는다.

### D. 도메인 수정(요청 효능이 `Claim.other`인 경우 ②로 처리, 조언 세션 결정)

- `resolve_claim_policy`: `requested == Claim.other`를 `None`으로 보던 줄을 지운다. `requested == "other"`는 "요청 효능이 있으나 근거를 확인할 수 없음"으로 다룬다(`available`에 `other`는 절대 없으므로 조회 `ok`이고 `choice`가 없으면 ②로 간다; 선택지는 ②와 같고, `requested_claim`은 `"other"`).
- `ClaimChoice`: `requested_claim == Claim.other`를 허용한다(`claims`에는 계속 `other` 불가). 그래야 `keep_requested`·`requested_claim: "other"` 선택을 표현할 수 있다.
- 문구(`domain/supervisor.py` 상수, 테스트로 고정): 효능 이름 자리에 일반 표현을 쓴다.
  - `CLARIFY_REQUESTED_GENERIC_TEXT = "요청하신 효능은 이 제품의 성분·인증으로 근거가 확인되지 않았습니다. 확인된 효능은 {available}입니다. 어떻게 진행할까요?"`
  - `CLARIFY_REQUESTED_GENERIC_NO_CONFIRMED_TEXT = "요청하신 효능은 이 제품의 성분·인증으로 근거가 확인되지 않았습니다. 이 제품에서 근거가 확인된 효능이 없습니다. 어떻게 진행할까요?"`
  - `OPTION_KEEP_REQUESTED_GENERIC = "요청하신 효능으로 진행 (효능을 단정하는 표현은 제한됩니다)"`
  - `clarification_texts`는 `requested_claim == "other"`일 때 위 세 상수를 쓴다(`display`에 `other`가 없어도 원문 `other`를 문장에 넣지 않는다).
- `api/ask_view.py`: SSE `needs_clarification`의 `requested_label`은 `requested_claim == "other"`이면 `None`(표시 이름 `other`를 노출하지 않는다).

## 설계 검토 기록

**배경(조언 세션 승인, 이슈 #55)**: step 1·2가 되묻기 판정과 API를 만들었다. 이 step은 마케터의 선택(`claim_choice`)을 **기획·평가가 실제로 받아 쓰게** 한다. 지금 기획 `_SYSTEM`의 "available_efficacy 값만 / 없으면 빈 목록" 제한이 요청 효능을 덮어 근거 있는 다른 효능으로 바꾸거나 비우는 원인이다(조용한 교체 0→17회 관찰). 새 프롬프트는 소구 방향과 `claimed_efficacy`를 분리한다. 프롬프트 변경이므로 사전 등록 동결 줄(`동결 기획 프롬프트 버전`·`동결 기획 _SYSTEM sha256`·`동결 평가 프롬프트 버전`·`동결 평가 _SYSTEM sha256`)과 달라진다. 이는 정상이다(`docs/results/p6_preregistration.md`는 읽기 전용, 수정하지 않는다; 최종 실험은 끝났고 재실행하지 않는다).

**식별자 전수 대조(현재 코드, 모두 열어 확인)**:
- `agents/planning.py`: `PLANNING_PROMPT_VERSION = "2026-11-18-3"`(`:17`), `_SYSTEM`(`:19-59`, 효능 문장 `:29-31`), `make_plan(*, brief, handoff, profile, feedback, rework, structured, purpose, **call_options)`: payload 키 `brief`·`research`(= `research_payload(handoff)`)·`available_efficacy`(handoff에서 `Claim`(other 제외) 값만)·`profile`·`feedback`·`rework`, 있으면 `raw_tool_outputs`. `research_payload`는 알려진 핸드오프 키만 고른다(`claim_choice`가 `research` 안으로 새지 않는다).
- `agents/evaluation.py`: `EVALUATION_PROMPT_VERSION = "2026-11-18-2"`(`:14`), `_CRITERIA`(`differentiation`·`fit`), `_SYSTEM`, `evaluate_plan(*, plan, brief, handoff, rules, evidence_index, support, certs, structured, model, purpose, **call_options)`: payload 키 `plan`(11개 칸)·`brief`·`research`·`criteria`.
- `agents/plan_eval.py`: `pe_handoff`를 기획과 평가 양쪽에 그대로 넘긴다(`:152-153`, `:191-192`) → `plan_fn`·`evaluate_fn` 시그니처를 바꾸지 않고 `handoff["claim_choice"]`로 전달한다.
- `agents/supervisor.py`: `plan()` 노드(`:500-508` 부근): `context_mode == "off"`이면 `bounded = deepcopy(state["sv_handoff"])` + `raw_tool_outputs`, 아니면 `bounded, trims = trim_handoff(...)`. 여기에 트림 뒤 `claim_choice`를 싣는다. `state["sv_claim_choice"]`는 step 1이 만든 칸이다.
- `domain/supervisor.py`(step 1 산출물): `ClaimChoice`, `resolve_claim_policy`, `clarification_texts`, `CLARIFY_*`·`OPTION_*`. `api/ask_view.py`(step 2 산출물)의 `_CLAIM_DISPLAY`와 `requested_label`.

**기존 단언 충돌 점검(이미 열어 확인함)**:
- 프롬프트 버전 상수 단언: `tests/test_planning.py:206`, `:293`(`== "2026-11-18-3"`), `tests/test_evaluation.py:223`(`== "2026-11-18-2"`). 새 값으로 갱신한다(정확 일치 유지).
- `tests/test_planning.py:252-284`: `phrase in system["content"]` 목록(`단일 컷`·`콜라주`·`장면 묘사`·`무라벨`·`글자`·`available_efficacy`·`확인된 효능`·`빈 목록`·`지배 패턴`·`own_product_url`·`low_items`)은 **약화하지 않는다** → 교체 문장이 이 낱말을 모두 유지해야 한다(위 초안 B가 유지함). payload 키 집합 정확 일치(`:132` 부근 `research` 키 집합, 최상위 키 집합 단언)가 있으면 새 최상위 키 `claim_choice` 하나만 더하는 갱신을 허용한다.
- `tests/test_evaluation.py`: 최상위 payload 키·`criteria`·`plan` 키 집합 단언(`:100-114`, `:209-221`)은 최상위 `claim_choice` 하나만 더하는 갱신을 허용한다(`criteria`·`plan` 키 집합은 그대로).
- `tests/test_supervisor_context_mode.py:162`: 기획 호출 최상위 payload 키 집합을 정확 일치로 단언한다(`brief`·`research`·`available_efficacy`·`profile`·`feedback`·`rework` 등) → 새 최상위 키 `claim_choice` 하나만 더하는 갱신을 허용한다(`context_mode` `on`·`off` 모두, 부분 비교로 바꾸지 않음). 같은 테스트의 `messages == [{system}, {user: json.dumps(expected)}]` 정확 일치(`:156` 부근)는 `expected`에 `"claim_choice": None`(이 사례는 `claims_fn`이 없음) 하나를 더해 갱신한다. 같은 파일에서 `claims_fn`을 넘기지 않는 사례의 `handoff`·결과는 바이트 단위로 그대로여야 한다.
- 요청 효능 `other` 규칙 변경과 충돌하는 기존 테스트(이미 확인함): `tests/test_domain_supervisor.py:791-794`(`requested_claim: "other"`를 거절하던 사례 → 이제 유효, `claims: ["other"]`는 계속 거절), `tests/test_supervisor.py:946`(`requested` 매개변수의 `"other"`가 `None`으로 취급되던 기대 → ②), `:1049`(`keep_requested`·`requested_claim: "other"`가 거절되던 기대 → 유효), `tests/test_api_ask.py:632`(`claims: ["other"]`는 계속 422; `requested_claim: "other"`가 422 사례에 있으면 제거하고 유효 사례로 이동), `tests/test_ask_view.py`(`requested_label`이 `other`일 때 `None`). 각각 **"other 규칙 변경에 따른 기대 갱신에 한함, 나머지 단언 약화 금지"**다.

**새 칸 대응표**: `claim_choice`(`state["sv_claim_choice"]` → `plan()`의 `bounded["claim_choice"]` → `plan_eval` → `make_plan` payload 최상위 `claim_choice` / `evaluate_plan` payload 최상위 `claim_choice`), 새 상수 3개(`domain/supervisor.py` → `clarification_texts`), 두 프롬프트 버전(`planning.py`·`evaluation.py` → `supervisor.py`의 결과 `prompt_versions` → trace).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 모델 호출에 `temperature`를 지정하지 않는다, `reasoning_effort`를 명시하고 원장에 기록한다(기존 값 유지), 모델이 만든 문장을 테스트 기대값으로 굳히지 않는다
- `/docs/PROMPT_CHANGELOG.md`(표 형식 확인), `/docs/ADR.md`
- `/src/beautyads/agents/planning.py`, `/src/beautyads/agents/evaluation.py`, `/src/beautyads/agents/plan_eval.py`(읽기 전용), `/src/beautyads/agents/supervisor.py`(`plan()` 노드), `/src/beautyads/domain/supervisor.py`, `/src/beautyads/api/ask_view.py`
- `/tests/test_planning.py`(전체), `/tests/test_evaluation.py`(전체), `/tests/test_domain_supervisor.py`, `/tests/test_supervisor.py`, `/tests/test_api_ask.py`, `/tests/test_ask_view.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/agents/planning.py`, `src/beautyads/agents/evaluation.py`, `src/beautyads/agents/supervisor.py`, `src/beautyads/domain/supervisor.py`, `src/beautyads/api/ask_view.py`, `docs/PROMPT_CHANGELOG.md`, `tests/test_planning.py`, `tests/test_evaluation.py`, `tests/test_domain_supervisor.py`, `tests/test_supervisor.py`, `tests/test_api_ask.py`, `tests/test_ask_view.py`, `tests/test_supervisor_context_mode.py`, `tests/test_prereg.py`

열람 금지 경로: `data/interim/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `src/beautyads/agents/planning.py`, `src/beautyads/agents/evaluation.py`, `src/beautyads/agents/supervisor.py`, `src/beautyads/domain/supervisor.py`, `src/beautyads/api/ask_view.py`, `docs/PROMPT_CHANGELOG.md`, `tests/test_planning.py`, `tests/test_evaluation.py`, `tests/test_domain_supervisor.py`, `tests/test_supervisor.py`, `tests/test_api_ask.py`, `tests/test_ask_view.py`, `tests/test_supervisor_context_mode.py`, `tests/test_prereg.py`

위 "프롬프트 초안" A~D를 **조언 세션이 확인한 문장 그대로** 구현한다(확인 중 문장이 바뀌면 이 파일의 초안이 먼저 바뀐다). **모델 호출 없음, 테스트를 먼저 쓴다(TDD).**

**1. 감독자(`agents/supervisor.py`)**: `plan()`에서 `bounded`를 만든 뒤(트림 뒤, `context_mode` 두 경우 모두) `state["sv_claim_choice"]`가 비어 있지 않으면 `bounded["claim_choice"] = deepcopy(state["sv_claim_choice"])`를 한다. 그 밖의 변경은 없다(트림 목록·결과 키 불변).

**2. 기획(`agents/planning.py`)**: 초안 B대로 `_SYSTEM`의 효능 문장을 교체하고 `PLANNING_PROMPT_VERSION = "2026-11-20-1"`. `make_plan`의 payload 최상위에 `"claim_choice": handoff.get("claim_choice") or None`을 더한다(값이 있으면 `{"mode", "claims", "requested_claim"}` 세 키만 담은 사본; 그 밖의 키는 걸러 낸다). `research_payload`·`available_efficacy` 계산은 바꾸지 않는다. 다른 `_SYSTEM` 문장은 글자 그대로다.

**3. 평가(`agents/evaluation.py`)**: 초안 C대로 `_SYSTEM`에 문장을 삽입하고 `EVALUATION_PROMPT_VERSION = "2026-11-20-1"`. `evaluate_plan`의 payload 최상위에 같은 방식으로 `"claim_choice"`를 더한다. `_CRITERIA`·`plan` 키 목록·코드 검사(`run_checks_on_dict`)·`efficacy_status`는 바꾸지 않는다.

**4. 도메인·뷰(초안 D)**: `domain/supervisor.py`의 `resolve_claim_policy`·`ClaimChoice`·`clarification_texts`와 새 문구 상수 3개, `api/ask_view.py`의 `requested_label`.

**4b. 사전 등록 렌더링 해시(`tests/test_prereg.py`)**: `test_none_measurement_preserves_original_bytes`(`:567`)는 `prereg.render_preregistration(**render_inputs, dev_measurement=None)` 전체 바이트의 SHA-256을 정확 일치로 고정한다. 이 렌더링에는 동결 줄(`동결 기획 프롬프트 버전`·`동결 기획 _SYSTEM sha256`·`동결 평가 프롬프트 버전`·`동결 평가 _SYSTEM sha256`)이 현재 코드값으로 들어가므로 이 step의 프롬프트·버전 변경으로 해시가 바뀐다(이미 확인함: 전체 테스트에서 이 한 개만 실패). **그 기대 해시 문자열 한 줄만** 새 렌더러 출력의 해시로 갱신하고(`uv run python`으로 합성 입력 `render_inputs`에서 계산; 코멘트 한 줄 "2026-11-20 6b-clarify step 3: 프롬프트 동결 줄 변경으로 갱신" 추가), 그 테스트의 나머지 단언(`None`이면 인자 생략과 같고 "E3 dev 측정 근거"가 없다)은 그대로 둔다. 의도된 변경에 따른 값 갱신이지 단언의 약화가 아니다. 같은 파일의 다른 해시 단언(`:132`, `:161`, `:918`, `:925`)은 바뀌지 않아야 한다(바뀌면 `blocked`).

**5. 문서(`docs/PROMPT_CHANGELOG.md`)**: 표 끝에 두 줄을 더한다(`2026-11-20 | 기획 2026-11-20-1 | agents/planning.py | …`, `2026-11-20 | 평가 2026-11-20-1 | agents/evaluation.py | …`): 변경(소구 방향과 `claimed_efficacy` 분리, `claim_choice` 입력, `keep_requested`에서 단정 표현 제한과 `claimed_efficacy` 빈 목록 무감점)과 이유(E2 최종 실행에서 요청 효능이 조용히 근거 있는 다른 효능으로 바뀌거나 비워짐; 되묻기 흐름 추가)를 적는다. 한 줄에 "사전 등록 동결 줄과 달라져 final 가드가 막히는 것은 정상이며 실험은 재실행하지 않는다"를 적는다. 기존 줄은 고치지 않는다.

**테스트(합성 데이터, 모델·접속 없음)**
- `tests/test_supervisor_context_mode.py`: (9b) 위 키 집합 갱신(정확 일치 유지)과 `claim_choice`가 `on`·`off` 모두에서 같은 값으로 전달됨.
- `tests/test_planning.py`: (1a) `claim_choice`가 `null`이고 `brief.claim`이 `available_efficacy` 안일 때 기획 입력(가짜 `structured`가 받은 `messages`의 user JSON)에 `brief.claim`과 `available_efficacy`가 함께 실려 있고 시스템 지시에 위 `null` 규칙 낱말(`brief.claim`·`중심`)이 있다(FP-C14). (1b) 새 `_SYSTEM` 고정: `PLANNING_PROMPT_VERSION == "2026-11-20-1"`와, 확정 문장 세 곳의 핵심 구절(`사실처럼 암시`, `지어내지 않는다`, `brief.claim이 있고`)이 시스템 지시에 있다. (1) 실제 `make_plan` 호출 인자(`messages`)의 시스템 지시에 위 초안 문장의 핵심 낱말이 있다(`claim_choice`·`keep_requested`·`selected`·`none`·`단정`·`소구 방향`·`claimed_efficacy`·`available_efficacy`·`확인된 효능`·`빈 목록`; **초안 문장 전체가 아니라 핵심 낱말**로 검사해 문장 다듬기에 깨지지 않게 한다) 그리고 기존 `phrase in system["content"]` 목록이 그대로 통과한다. (2) mode 세 가지와 `None`에서 payload 최상위 `claim_choice`가 정확히 `{"mode", "claims", "requested_claim"}` 키의 사본이거나 `None`이다(가짜 `structured`가 받은 `user` 메시지를 직접 검사, FP-C14). 핸드오프의 다른 키가 `claim_choice` 안으로 새지 않는다. (3) `research` 페이로드 키 집합이 그대로다(`claim_choice`가 `research` 안에 없다). (4) 버전 상수 두 곳을 새 값으로 갱신(정확 일치). (5) 입력 `handoff`가 변하지 않는다.
- `tests/test_evaluation.py`: (5b) 세 mode(`selected`·`keep_requested`·`none`)와 `null`마다 평가 payload 최상위 `claim_choice`가 정확히 `{"mode", "claims", "requested_claim"}` 키이거나 `None`이다(가짜 `structured`가 받은 user JSON 직접 검사), 기획 payload도 같은 방식으로 세 mode를 검사한다(`tests/test_planning.py`). 평가 `_SYSTEM` 고정: `EVALUATION_PROMPT_VERSION == "2026-11-20-1"`와 핵심 구절(`감점하지 않는다`). (6)(1)과 같은 방식의 평가 시스템 지시 낱말(`claim_choice`·`keep_requested`·`감점하지 않는다`·`요청 적합성`)과 payload 최상위 `claim_choice` 검사, 기존 키 집합 단언은 `claim_choice` 하나만 더하는 갱신. (7) 버전 상수 갱신. (8) 코드 검사 결과(`check_report`)와 `efficacy_status`가 `claim_choice` 유무와 무관하게 같다.
- `tests/test_supervisor.py`: (9) `claims_fn`이 있고 진행하는 경우 `plan_calls[*]["handoff"]["claim_choice"]`가 `state["sv_claim_choice"]`와 같고(`context_mode` `on`·`off` 둘 다), `claims_fn=None`이면 `claim_choice` 키가 없다. 트림 목록이 이전과 같다. (10) other 규칙 변경: `requested == "other"`·조회 `ok`·선택 없음이면 `needs_clarification`(②)이고 리서치 0회, `keep_requested`·`requested_claim: "other"` 재호출은 진행하며 리서치 `brief["claim"] == "other"`, 조회 실패·건너뜀에서는 이전처럼 진행하고 `claim_choice.mode == "keep_requested"`다.
- `tests/test_domain_supervisor.py`: (11) 정책 표에 `other` 가지(② 확인 효능 있음·0개, `keep_requested` 유효, 조회 실패) 추가, `ClaimChoice`가 `requested_claim: "other"`를 받고 `claims: ["other"]`는 거절. (12) 새 문구 상수 3개를 문자열 정확 일치로 고정하고 `clarification_texts`가 `other`일 때 원문 `other`를 문장에 넣지 않으며 선택지 라벨이 `OPTION_KEEP_REQUESTED_GENERIC`이다.
- `tests/test_api_ask.py`·`tests/test_ask_view.py`: (13) `requested_claim: "other"`는 422가 아니고 가짜 `ask`가 그대로 받는다(`claims`에 `other`는 계속 422). `requested_label`은 `other`일 때 `None`이다.
- 합성 문장·분류 값을 기대값으로 굳히지 않는다(닫힌 값·상수·구조·핵심 낱말만 검사).

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

- 초안 B·C·D 밖의 `_SYSTEM` 문장(`image_brief`·`hook_text`·`rework`·데이터 규칙·`TOOL_DATA_RULE`·`PARTIAL_RESULT_RULE`)과 `_CRITERIA`·`Plan` 스키마·`EvaluationScores` 스키마를 바꾸지 마라. 이유: 구조화 스키마는 strict 가드 대상이고(FP-C15) 이 phase가 바꾸는 것은 효능 방향 입력과 그 해석 문장뿐이다. 이 step 뒤에도 `Plan.claimed_efficacy`의 분류 값·코드 검사(`EFFICACY_UNKNOWN`)는 그대로 근거 없는 값을 막아야 한다.
- 모델 호출 인자에 `temperature`를 넣거나 `reasoning_effort` 값을 바꾸지 마라(`PLANNING_REASONING_EFFORT`·평가의 `reasoning_effort=None` 유지). 이유: AGENTS.md CRITICAL, 호출 래퍼 가드(`tests/test_llm_param_guard.py`)가 이 조합을 검사한다(FP-C13).
- 기획·평가가 `claim_choice`를 실제 입력으로 받는다는 테스트를 가짜 `structured`의 반환값이 아니라 **호출 인자(`messages`의 user JSON)** 로 단언하라. 이유: 반환값만 보면 입력에 안 들어가도 통과한다(FP-C14). 시스템 지시 문장은 전체 일치가 아니라 핵심 낱말로 검사해 모델이 만든 문장을 굳히지 않는다(FP-C03).
- `docs/results/p6_preregistration.md`·`docs/EVAL.md`·`tests/test_freeze_guard.py`·`src/beautyads/eval/`를 수정하지 마라. `tests/test_prereg.py`는 아래 해시 한 줄 갱신 외에는 수정하지 마라. 이유: 사전 등록 동결 줄과 달라지는 것은 정상이며 동결값은 결과를 본 뒤 바꾸지 않는다. 가드 테스트(`test_freeze_guard.py`)는 현재 코드값을 동적으로 읽어 영향이 없다(이미 확인함).
- 기존 테스트의 단언을 약화하지 마라. 허용: `tests/test_prereg.py:567` 기대 해시 한 줄 갱신(위 4b), 버전 상수 정확 일치 갱신, 최상위 payload 키 집합에 `claim_choice` 하나를 더하는 갱신, 위 `other` 규칙 변경에 따른 기대 갱신. 이유: 새 키·새 규칙이 만드는 정확 일치 충돌이다(FP-C11, B-FP-071). 경계: `tests/test_planning.py`의 기존 `phrase in system["content"]` 목록은 그대로 통과해야 한다.
