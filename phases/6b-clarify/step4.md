# Step 4: efficacy-outcomes

## 설계 검토 기록

**배경(사용자 확정, 이슈 #55)**: step 1이 만든 규칙은 효능 조회가 `failed`·`skipped`이거나 확인된 효능이 0개일 때 "효능 강조 없이 진행 + 경고"였다. 사용자가 이를 뒤집었다: **효능 근거 없이 작성된 기획안은 신뢰할 수 없다.** 확정 동작:
- (a) 조회 `failed`(그래프·DB 오류) → 기획을 진행하지 않는다. (b) 조회 `skipped`(작업 공간에 제품 미등록) → 진행하지 않는다.
- (c) 조회 성공·확인된 효능 0개: 요청 효능이 없으면 되묻는다(선택지 "효능 강조 없이 진행"과 "중단"). 요청 효능이 있으면 기존 ②를 유지한다(선택지는 요청 효능으로 진행과 효능 강조 없이이며 "확인된 효능 중 선택"은 뺀다 — step 1이 이미 이렇게 만들었다).
- (d) 확인된 효능 1개 이상이면 ①②③은 그대로다. **`claims_fn`이 없는 조립(테스트·기존 경로)은 새 규칙을 전혀 적용하지 않는다(불변).**
- "관리자에게 알림"은 데모 범위에서 **추적 기록(trace)** 으로만 남긴다(작업 공간·제품·실패 상태, 요청 본문 제외; 이메일·알림 연동 없음).
- 이전 step 1의 `efficacy_notice` 문구("효능 근거를 확인하지 못해 효능 강조 없이 작성했습니다.", `none_confirmed` 문구)는 **더 이상 쓰지 않는다**(코드·테스트에서 정리).

이 step은 step 1·2의 판정표·API를 고치는 일이다. 모델 호출 없음. 새 결과 종류(`kind == "efficacy_unavailable"`)는 `interpret`에서 `decide` 직후 낸다(리서치·기획 호출 0회, `PlanRecord` 저장 없음).

**사용자 확정 문구(도메인 상수 한 곳, 테스트가 문자열을 그대로 고정)**:
- `EFFICACY_UNAVAILABLE_TEXT = {"failed": "이 제품의 효능 근거를 조회하지 못해 기획을 진행할 수 없습니다. 관리자에게 이 문제를 알려 주세요.", "no_product": "이 작업 공간에 제품 정보가 없어 효능 근거를 확인할 수 없습니다. 관리자에게 제품 등록을 요청해 주세요."}`
- `CLARIFY_NO_CONFIRMED_TEXT = "이 제품에서 근거가 확인된 효능이 없습니다. 효능을 강조하지 않고 제품 자체를 홍보하는 방향으로 진행할까요?"`
- `OPTION_PROCEED_WITHOUT_EFFICACY = "효능 강조 없이 진행"`, `OPTION_CANCEL = "중단"`

**식별자 전수 대조(현재 코드, 모두 열어 확인)**:
- `domain/supervisor.py`(step 1·3 산출물): 문구 상수(`CLARIFY_REQUESTED_TEXT`·`CLARIFY_REQUESTED_NO_CONFIRMED_TEXT`·`CLARIFY_REQUESTED_GENERIC_*`·`CLARIFY_UNSPECIFIED_TEXT`·`OPTION_*`), **`EFFICACY_NOTICE_TEXT`(제거 대상, `:40`)**, `ClarifyReason`(`requested_not_confirmed`·`no_claim_requested`), `ClarifyOption`(`keep_requested`·`select_confirmed`·`select_one`·`select_many`·`none`), `ClaimChoice`, `resolve_claim_policy`(반환 키 `{"action", "claim", "claim_choice", "notice", "clarification"}`; `status != "ok"`이면 `notice="lookup_unconfirmed"`로 진행, `ok`이고 `available`이 비고 요청이 없으면 `notice="none_confirmed"`로 진행), `clarification_texts(clarification, display)`.
- `agents/supervisor.py`: `SupervisorState`의 `sv_efficacy_notice`(`:163`, 제거 대상), `initial_supervisor_state`(`:205`), `interpret` 노드의 정책 처리(`:369-393`: `invalid`→`claim_choice_invalid`, `clarify`→`needs_clarification`, 그 밖에 `sv_claim_choice`·`sv_efficacy_notice`·`decision["claim"]` 설정), `run_request` 결과의 `"efficacy_notice"`(`:629`)와 `available_efficacy`·`available_efficacy_status`(`kind in {"needs_clarification", "claim_choice_invalid"}`일 때 `sv_efficacy`에서 읽음)와 `"text"`(같은 두 kind에서 `""`), `_lookup_efficacy(claims_fn, profile)`(상태 `ok|failed|skipped`, 예외·잘못된 상태는 `failed`).
- `api/ask_view.py`: `EFFICACY_NOTICE_TEXT` import(`:18`)와 `notice` 첫 줄 추가(`:139`; 제거 대상), `View(answer_text, ui_commands, clarification, error_code)`, `needs_clarification` 분기, `_CLAIM_DISPLAY`.
- `api/ask.py`: `events()`가 `outcome.error_code` → `outcome.clarification` → `ui_command`들 → `token` 순서로 낸다(`:171-178`). `api/sse.py`: `EventName`.
- `obs/trace.py`: `TraceRecord.kind` Literal(`needs_clarification`·`claim_choice_invalid` 포함), `build_trace(...)`가 `result.get("kind")`를 싣는다. **새 `kind`가 `Literal`에 없으면 `assembly.ask`의 `except Exception: pass`가 trace를 조용히 버린다.** `tenant_id`는 이미 trace의 칸이다(작업 공간).
- `api/assembly.py`: 변경 없음(`claims_fn`은 `own_product_url`이 없거나 공백이면 `([], "skipped")`, 질의 오류가 하나라도 있으면 `([], "failed")`, 아니면 `(확인된 효능, "ok")`).

**새 규칙에 따라 갱신해야 하는 기존 테스트(이미 `grep`으로 확인함)**:
- `tests/test_domain_supervisor.py`: `notice` 값을 쓰는 정책 표 사례(`:574` `none_confirmed`, `:739`·`:756`·`:777` `lookup_unconfirmed`), `EFFICACY_NOTICE_TEXT` 문자열 고정(`:897`), 정책 반환 키 집합(정확히 5개 단언).
- `tests/test_supervisor.py`: `SupervisorState` 키 집합(`:356`에 `sv_efficacy_notice`), `efficacy_notice` 단언(`:951`·`:973`·`:992`·`:1035`·`:1094`·`:1113`·`:1141`), `failed`·`skipped`·예외 사례(`:1094` 부근: 되묻지 않고 진행하던 기대 → `efficacy_unavailable`), 효능 0개 사례(`:1113` 부근), `test_claims_status_is_safe_and_never_changes_evaluation_decisions`(`mode`가 `failed`·`skipped`·`exception`이면 기획 결과가 없어짐).
- `tests/test_ask_view.py`: `EFFICACY_NOTICE_TEXT` import(`:15`)와 `test_efficacy_notice_is_first_line_and_preserves_existing_view`(`:483-493`, 삭제 후 새 동작 테스트로 대체).
- `tests/test_api_assembly.py::test_assembled_claims_function_uses_only_existing_support_query`: `mode`가 `failed`·`partial_failure`·`empty`·`missing`이면 새 규칙에서 `result["kind"] == "efficacy_unavailable"`이고 `result["plans"]`가 비어 있어 `result["plans"][0]["status"] == "done"`과 기획 payload 단언이 깨진다. `ok` 모드는 그대로(`claim_choice={"mode": "none"}` 호출 유지). 지원 질의 목록·`available_efficacy`·`available_efficacy_status` 단언은 그대로 유지하고, 비-`ok` 모드에서는 `plan` 호출이 한 번도 없음(`rig.calls`에 `plan` 없음)을 새로 단언한다.
- `tests/test_trace.py`·`tests/test_api_ask.py`: `kind` 목록·이벤트 이름 단언에 새 값 하나씩 더한다.

**새 칸 대응표**:
- 정책 반환 키(정확히 5개): `{"action", "claim", "claim_choice", "clarification", "unavailable"}`(`notice` 제거, `unavailable` 추가). `action`은 `"proceed" | "clarify" | "invalid" | "unavailable"`. `unavailable`: `{}` 또는 `{"reason": "failed" | "no_product"}`.
- 상태 `sv_efficacy_unavailable`(`interpret` → 결과 `efficacy_unavailable` → `build_view` → SSE `efficacy_unavailable` 본문 `{"reason", "text"}` → trace `efficacy_unavailable`).
- `ClarifyReason.no_efficacy_confirmed`, `ClarifyOption.cancel`(표시용 선택지 id; **서버가 받는 `claim_choice`에는 `cancel`이 없다**. 사용자가 "중단"을 고르면 화면이 취소하고 서버 요청은 없다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: `tenant_id`는 세션에서만 나온다(요청·결과 입력에 테넌트 칸 금지), 키·응답 본문을 trace에 남기지 않는다, 모델이 만든 값을 테스트 기대값으로 굳히지 않는다
- `/docs/ADR.md`(ADR-009), `/docs/TROUBLESHOOTING_LOG.md`(읽기 전용)
- `/src/beautyads/domain/supervisor.py`, `/src/beautyads/agents/supervisor.py`(`interpret`·`run_request`·`_lookup_efficacy`), `/src/beautyads/api/ask.py`, `/src/beautyads/api/ask_view.py`, `/src/beautyads/api/sse.py`, `/src/beautyads/obs/trace.py`, `/src/beautyads/api/assembly.py`(읽기 전용)
- `/tests/test_domain_supervisor.py`, `/tests/test_supervisor.py`, `/tests/test_ask_view.py`, `/tests/test_api_ask.py`, `/tests/test_trace.py`, `/tests/test_api_assembly.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/supervisor.py`, `src/beautyads/agents/supervisor.py`, `src/beautyads/api/ask.py`, `src/beautyads/api/ask_view.py`, `src/beautyads/api/sse.py`, `src/beautyads/obs/trace.py`, `tests/test_domain_supervisor.py`, `tests/test_supervisor.py`, `tests/test_ask_view.py`, `tests/test_api_ask.py`, `tests/test_trace.py`, `tests/test_api_assembly.py`

열람 금지 경로: `data/interim/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `src/beautyads/domain/supervisor.py`, `src/beautyads/agents/supervisor.py`, `src/beautyads/api/ask.py`, `src/beautyads/api/ask_view.py`, `src/beautyads/api/sse.py`, `src/beautyads/obs/trace.py`, `tests/test_domain_supervisor.py`, `tests/test_supervisor.py`, `tests/test_ask_view.py`, `tests/test_api_ask.py`, `tests/test_trace.py`, `tests/test_api_assembly.py`

새 식별자: `EFFICACY_UNAVAILABLE_TEXT`, `CLARIFY_NO_CONFIRMED_TEXT`, `OPTION_PROCEED_WITHOUT_EFFICACY`, `OPTION_CANCEL`, `ClarifyReason.no_efficacy_confirmed`, `ClarifyOption.cancel`, `sv_efficacy_unavailable`, `efficacy_unavailable`(결과 키·`kind`·SSE 이벤트·trace 칸), `TraceEfficacyUnavailable`. 제거 식별자: `EFFICACY_NOTICE_TEXT`, `sv_efficacy_notice`, 결과 키 `efficacy_notice`, 정책 반환 키 `notice`, 문구 `lookup_unconfirmed`·`none_confirmed`. **테스트를 먼저 쓴다(TDD).**

**1. 도메인(`domain/supervisor.py`)**
- 위 "사용자 확정 문구" 상수 4개를 추가하고 `EFFICACY_NOTICE_TEXT`를 지운다. `ClarifyReason`에 `no_efficacy_confirmed`, `ClarifyOption`에 `cancel`을 더한다.
- `resolve_claim_policy`: 반환 키를 위 대응표의 5개로 바꾸고 규칙을 다음으로 바꾼다.
  - `status`가 `"failed"`이면 `action="unavailable"`, `unavailable={"reason": "failed"}`. `"skipped"`이면 `unavailable={"reason": "no_product"}`. 그 밖의 `ok`가 아닌 값도 `failed`로 본다. 이때 `choice`·`requested`는 무시한다(`claim=None`, `claim_choice={}`, `clarification={}`).
  - `status == "ok"`이고 `available`이 비어 있고 `requested`가 없고 `choice`가 없으면 `action="clarify"`, `clarification = {"reason": "no_efficacy_confirmed", "requested_claim": None, "available_efficacy": [], "available_status": "ok", "options": ["none", "cancel"]}`.
  - 그 밖의 `ok` 규칙(①②③, `choice`의 `selected`·`keep_requested`·`none`, `requested == "other"`는 ②, 확인 효능 0개+요청 있음은 `[keep_requested, none]`)은 **그대로**다. `choice`의 `mode == "none"`이면 확인 효능 0개에서도 진행한다(`claim_choice`는 `{"mode": "none", "claims": [], "requested_claim": None}`). `notice`는 어떤 경우에도 반환하지 않는다.
- `clarification_texts`: `reason == no_efficacy_confirmed`이면 `CLARIFY_NO_CONFIRMED_TEXT`를 쓰고, 이때 선택지 라벨은 `none` → `OPTION_PROCEED_WITHOUT_EFFICACY`, `cancel` → `OPTION_CANCEL`이다(다른 reason의 `none` 라벨은 기존 `OPTION_NONE` 그대로). `cancel` 라벨은 reason과 무관하게 `OPTION_CANCEL`이다.

**2. 감독자(`agents/supervisor.py`)**
- `SupervisorState`·`initial_supervisor_state`: `sv_efficacy_notice`를 `sv_efficacy_unavailable: dict`(기본 `{}`)로 바꾼다.
- `interpret`: `policy["action"] == "unavailable"`이면 `state["sv_efficacy_unavailable"] = policy["unavailable"]`, `state["sv_status"]["kind"] = "efficacy_unavailable"`(실패 코드·`incomplete` 설정 없음)로 `END`(리서치·기획 호출 0회, 새 노드 없음). `notice` 대입 줄은 지운다. 그 밖은 지금 그대로다. **`claims_fn is None`이면 새 규칙을 적용하지 않는다(지금 구조 그대로).**
- `run_request` 결과: `"efficacy_notice"`를 지우고 `"efficacy_unavailable": state["sv_efficacy_unavailable"]`를 더한다. `kind == "efficacy_unavailable"`일 때도 `available_efficacy`·`available_efficacy_status`는 `sv_efficacy`에서 읽고(`kind in {"needs_clarification", "claim_choice_invalid", "efficacy_unavailable"}`), `text`는 `""`다.

**3. API·뷰**
- `api/sse.py`: `EventName`에 `"efficacy_unavailable"`을 더한다.
- `api/ask_view.py`: `EFFICACY_NOTICE_TEXT` import와 `notice` 첫 줄 추가 코드를 지운다. `View`에 `efficacy_unavailable: dict | None = None`을 더한다. `kind == "efficacy_unavailable"`이면 `reason = result["efficacy_unavailable"].get("reason")`(`EFFICACY_UNAVAILABLE_TEXT`에 없으면 `"failed"`)로 `text = EFFICACY_UNAVAILABLE_TEXT[reason]`를 만들어 `View(answer_text=text, ui_commands=[], efficacy_unavailable={"reason": reason, "text": text})`를 돌려준다(근거 카드·계획·분포 명령 없음).
- `api/ask.py`: `events()`에서 `outcome.efficacy_unavailable`이 있으면 `encode_event("efficacy_unavailable", outcome.efficacy_unavailable)` 다음 `token`(`answer_text`)을 낸다(`ui_command` 없음). 다른 분기·순서는 그대로다. `work()`는 `plans`가 없으므로 `PlanRecord`를 저장하지 않는다(지금 코드 그대로).

**4. 추적 기록(`obs/trace.py`)**: `TraceRecord.kind`의 `Literal`에 `"efficacy_unavailable"`을 더한다. `TraceEfficacyUnavailable`(`reason: Literal["failed", "no_product"]`, `brand: str | None`, `product_name: str | None`, 문자열은 길이 200 이하, 닫힌 모델)을 만들고 `TraceRecord.efficacy_unavailable: TraceEfficacyUnavailable | None = None`을 더한다. `build_trace`는 `result.get("kind") == "efficacy_unavailable"`일 때만 `reason`을 `result["efficacy_unavailable"]["reason"]`에서, `brand`·`product_name`을 `result["product_display"]`에서 채운다. **작업 공간은 기존 `tenant_id` 칸이 맡는다. 요청 본문·`goal`·진단 문자열·예외 메시지는 trace에 넣지 않는다.** 다른 칸·검증은 바꾸지 않는다.

**테스트(합성 데이터, 모델·접속 없음)**
- `tests/test_domain_supervisor.py`: (1) 정책 표 갱신: `failed`·`skipped`·잘못된 상태 → `unavailable`(`reason`이 `failed`/`no_product`/`failed`, `choice`가 있어도 무시), `ok`+`[]`+요청 없음+`choice` 없음 → `clarify`(`no_efficacy_confirmed`, 옵션 `["none", "cancel"]`), `ok`+`[]`+요청 없음+`choice` `none` → 진행, `ok`+`[]`+요청 있음(`other` 포함) → ②(`[keep_requested, none]`), `ok`+`[]`+`choice` `selected` → `invalid`, 기존 ①②③ 사례는 그대로. 반환 키 집합이 정확히 5개다. 사례 수가 0이면 실패한다(B-FP-069). (2) 문구 상수 4개 문자열 정확 일치 고정과 `EFFICACY_NOTICE_TEXT`가 모듈에 없음. (3) `clarification_texts`가 `no_efficacy_confirmed`에서 기대 문장과 선택지 `[{"id": "none", "label": "효능 강조 없이 진행"}, {"id": "cancel", "label": "중단"}]`를 낸다.
- `tests/test_supervisor.py`: (4) `failed`·`skipped`·예외·잘못된 상태 각각 `kind == "efficacy_unavailable"`, `efficacy_unavailable == {"reason": ...}`(예외·잘못된 상태·`failed`는 `failed`, `skipped`는 `no_product`), `research_calls == []`, `plan_calls == []`, 진단 문자열 비노출, 같은 요청에 `claim_choice`를 줘도 여전히 `efficacy_unavailable`. (5) 효능 0개+요청 없음 → `needs_clarification`(`reason == "no_efficacy_confirmed"`)이고 호출 0회, 같은 상황에서 `claim_choice={"mode": "none"}` 재호출은 진행하고 리서치 `brief["claim"]`이 `None`. (6) `claims_fn=None`이면 이전과 같다(`efficacy_unavailable == {}`). (7) 기존 단언 갱신: `SupervisorState` 키 집합(`sv_efficacy_notice` → `sv_efficacy_unavailable`, 정확 일치 유지), `efficacy_notice` 단언을 지우거나 `efficacy_unavailable == {}`로 바꾸기, 위 "갱신해야 하는 기존 테스트"의 `failed`·`skipped`·0개·`mode` 사례의 기대를 새 규칙으로 바꾸기. 단언을 느슨하게 만들지 않는다.
- `tests/test_ask_view.py`: (8) `efficacy_unavailable`의 `failed`·`no_product`·알 수 없는 `reason` 각각 `answer_text`가 `EFFICACY_UNAVAILABLE_TEXT`의 문자열과 같고 `ui_commands == []`다. (9) `needs_clarification`의 `no_efficacy_confirmed`가 기대 `text`와 선택지를 낸다. (10) 기존 `efficacy_notice` 테스트를 지우고 `efficacy_notice`가 결과에 있어도 출력에 영향이 없음(무시)을 확인한다.
- `tests/test_api_ask.py`: (11) 가짜 `ask`가 `kind: "efficacy_unavailable"` 결과를 돌려주면 이벤트가 `efficacy_unavailable`(본문 키가 정확히 `{"reason", "text"}`) 다음 `token`이고 `ui_command`가 없고 `PlanRecord`가 저장되지 않는다. (12) `create_app` 진입점을 거치는 경로로도 (11)이 동작한다(B-FP-070). (13) `needs_clarification`의 `no_efficacy_confirmed` 본문 `options`가 `none`·`cancel`이다. 기존 이벤트 이름 단언은 새 이름 하나만 더하는 갱신이다.
- `tests/test_trace.py`: (14) `kind` 매개변수에 `efficacy_unavailable`을 더한다. `build_trace`가 이 `kind`에서 `efficacy_unavailable`(`reason`·`brand`·`product_name`)을 채우고, 다른 `kind`에서는 `None`이며, 합성 비밀 문자열(요청 본문·`goal`)이 직렬화 결과에 없다. 기존 `kind` 단언은 약화하지 않는다.
- `tests/test_api_assembly.py`: (15) 위 "갱신해야 하는 기존 테스트"대로 `failed`·`partial_failure`·`empty`·`missing` 모드의 기대를 `kind == "efficacy_unavailable"`(`reason`: `failed`/`failed`/`no_product`/`no_product`)로 바꾸고 `plan` 호출이 없음을 단언한다. `ok` 모드와 지원 질의 단언은 그대로다. 같은 호출이 trace를 남기는지(`TraceRecord`가 만들어짐; 새 `kind`가 `Literal`에 있음)를 한 사례로 확인한다.
- 합성 문장·분류 값을 기대값으로 굳히지 않는다(문구 상수·닫힌 값·구조만 검사).

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

- 효능 조회 `failed`·`skipped`를 "확인된 효능 없음"으로 합치지 마라. 이유: 조회가 멈춘 것을 "없음"으로 확정하면 근거 없는 기획안이 신뢰할 수 있는 것처럼 나간다(FP-C05). 두 상태는 `unavailable`의 서로 다른 `reason`(`failed`·`no_product`)이며 둘 다 리서치·기획 모델 호출이 0회임을 테스트가 호출 기록으로 단언한다(B-FP-069: 검사한 사례 0건이면 실패).
- `claims_fn is None`인 호출과 확인된 효능이 1개 이상인 경로(①②③·`claim_choice` 검증)의 동작을 바꾸지 마라. 이유: 확정 동작 (d)와 step 1·2·3의 기존 테스트를 그대로 지켜야 한다. 기획·평가 프롬프트·`planning.py`·`evaluation.py`는 수정하지 않는다(프롬프트 버전 단언 FP-C11).
- 문구 상수 4개와 `EFFICACY_UNAVAILABLE_TEXT`·`CLARIFY_NO_CONFIRMED_TEXT`·`OPTION_PROCEED_WITHOUT_EFFICACY`·`OPTION_CANCEL`의 글자를 바꾸거나 서버가 받는 `claim_choice`에 `cancel`을 더하지 마라. 이유: 문구는 사용자가 확정했고 "중단"은 화면에서 취소하며 서버 요청이 없다(`ClaimChoice`·`AskRequest` 스키마 불변).
- trace에 요청 본문·`goal`·진단 문자열·예외 메시지·키를 남기거나 이메일·알림 연동을 만들지 마라. `obs/trace.py`에서 `kind`·새 칸 말고 다른 칸·검증을 바꾸지 마라. 이유: 관리자 보고는 데모 범위에서 trace 기록뿐이다(AGENTS.md 비밀 값 규칙). 새 `kind`를 `Literal`에 빠뜨리면 trace가 조용히 버려진다.
- 기존 테스트의 단언을 약화하지 마라. 허용: 위 "갱신해야 하는 기존 테스트" 목록의 기대 갱신(정책 표·`notice`·`efficacy_notice`·상태 키 집합·`kind` 목록·이벤트 이름 단언), `efficacy_notice` 전용 테스트 삭제와 새 동작 테스트로의 대체. 이유: 정책 반환 키·상태 키·결과 키·이벤트 이름이 바뀌어 정확 일치 단언과 충돌한다(FP-C11, B-FP-071).
