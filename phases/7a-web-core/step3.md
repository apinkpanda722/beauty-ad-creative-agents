# Step 3: view-contract

## 설계 검토 기록

**배경(P7 설계 승인 d, 승인 Q6·Q8)**: 화면은 (1) 코드가 센 값과 모델 작성값을 **따로** 보여 주고(P5 결정 50), (2) 요청 비용 한 줄을 보여 주고(Q8), (3) 같은 내용을 두 번 그리지 않아야 한다. 지금은 `aggregates`가 `token` 텍스트 안에 `AGGREGATES_LABEL` → `key: value` → `aggregates_removed: ...` 줄로 섞여 나가고(`api/ask_view.py` 235~245행), 같은 `token` 텍스트에 기획안 본문(제목·훅·장면·카피)과 도구별 건수 줄도 들어 있어 화면의 기획안 카드·건수 표시와 겹친다. 요청 비용은 Supervisor 결과의 `limits.text_spent_usd`에 있지만 화면으로 나가지 않는다.

**이 step의 변경(서버 계약 추가, 기존 형식 유지)**:
1. 새 화면 명령 `show_aggregates`: `{"label": AGGREGATES_LABEL, "verified_counts": [{"tool","row_count","shown_count","count_label"}...], "model_written": [{"name","value"}...], "removed": ["키 이름"...]}`. `verified_counts`는 도구가 센 건수(`handoff.result_counts`, 코드 계산 값), `model_written`은 `verify_aggregates`를 통과한 **모델 작성값**(통과해도 모델이 쓴 문장이므로 `label`이 "모델 작성값, 검증되지 않음"이다), `removed`는 도구 출력에 없어 빠진 키 이름이다. 지금 `token` 텍스트를 만드는 같은 조건(`aggregates` 또는 `aggregates_removed`가 있음)일 때 낸다.
2. 새 화면 명령 `show_cost`: `{"label": "텍스트 모델 비용(이미지 제외)", "text_spent_usd": float, "max_text_cost_usd": float}`. 결과에 `limits.text_spent_usd`·`limits.max_text_cost_usd`가 둘 다 유한한 숫자(bool 아님)일 때만 낸다.
3. `View`에 선택 필드 `display_text: str | None = None`을 더한다: **화면에 구조화 명령이 따로 있는 내용(기획안 본문 줄, 도구별 건수 줄, aggregates 줄)을 뺀 메시지 텍스트**(고정 문구·"기획안입니다."/"리서치 결과입니다."·리서치 결론·한도 도달 문구)다. `answer_text`는 **그대로** 둔다(터미널 `chat_client`와 기존 테스트가 쓴다). `/ask`는 `display_text`가 `None`이 아니고 `answer_text`와 다를 때만 마지막 `token` 이벤트 본문에 `"display_text"` 키를 **더한다**(`{"text": ..., "display_text": ...}`). 같거나 `None`이면 본문은 지금과 같다(되묻기·효능 안내 `token` 본문 `{"text": ...}` 불변).
4. **근거 카드 분석 속성(P7 승인 추가, 화면 절반)**: step 2가 `hydrate`에 붙인 여섯 키(`hook_type`·`angle`·`format`·`talent`·`cta_type`·`claims`)를 카드에 싣는다. `_CARD_FIELDS`에 이 여섯 키를 **뒤에** 더한다(기존 여덟 키와 순서 불변). 카드 한 장은 이제 `_CARD_FIELDS` 전체를 키로 갖고, `hydrate`가 값을 주지 않은 키는 `None`이다(`by_id[eid].get(key)`). **라벨이 없는 소재는 오류가 아니다**: 값은 `None`(`claims`는 `[]` 또는 `None`)이고 카드는 그대로 나간다.
- 새 명령은 기존 명령 **뒤에** 붙인다(기존 명령의 순서·내용 불변). 되묻기·효능 조회 불가·선택 오류 경로(`needs_clarification`·`efficacy_unavailable`·`claim_choice_invalid`)는 **ui_commands가 계속 빈 목록**이다(초기 `return` 경로 불변).

**진행 이벤트 계약(코드로 확인, 문서화만)**: 화면의 단계 표시줄은 `tests/test_supervisor.py:296` `test_events_arrive_at_stage_boundaries_including_tools_reworks_image`가 고정한 순서를 따른다: `step(supervisor,end,ok)` → `step(research,end,<상태>)` → `tool_start`(리서치 종료 뒤 도구 호출 순서대로 일괄) → 기획안마다 [`step(planning,start,running)` → `step(evaluation,end,<상태>)` → `step(rework,end,done)` 되돌림 횟수만큼 → `step(image,end,ok|failed)` 이미지가 있으면] → `step(supervisor,done,<kind>)`. **supervisor·research는 시작 이벤트가 없다**(끝날 때만 온다). 이 사실을 `docs/ARCHITECTURE.md`의 "스트리밍 이벤트와 화면 명령" 절에 표로 적는다(아래 문서 항목).

**식별자 전수 대조(현재 코드, 모두 열어 확인)**:
- `api/ask_view.py`: `View(answer_text, ui_commands, clarification=None, error_code=None, efficacy_unavailable=None)`(데이터클래스, 두 인자 생성 호환 테스트 `test_view_two_argument_constructor_is_compatible`), `build_view(result, *, plan_ids, hydrate) -> View`, `_counts(counts)`(건수 + `count_label`), `AGGREGATES_LABEL`(`domain/supervisor.py`), `json_copy`.
- `api/ask.py`: 마지막 경로 `for command in outcome.ui_commands: yield encode_event("ui_command", command)` 뒤 `yield encode_event("token", {"text": outcome.answer_text})`, `outcome`은 `work()`가 돌려준 `build_view` 결과(`answer_text`, `ui_commands`, `clarification`, `error_code`, `efficacy_unavailable`). 되묻기·효능 안내 경로의 `token`은 별도 줄이다(불변).
- `agents/supervisor.py`(읽기 전용): 결과 `limits = {"text_spent_usd": state["sv_spent"], "max_text_cost_usd": limits.max_text_cost_usd}`, `aggregates_label`, `aggregates_removed`, `handoff.aggregates`(`verify_aggregates` 통과분만 남음).
- `api/chat_client.py`: `run_ask_once`의 `final_text`는 `token` 본문의 `text`만 이어 붙인다(불변, `display_text`를 읽지 않는다).
- `api/sse.py`: `EventName`은 불변이다(새 이벤트 이름 없음. 새 것은 `ui_command`의 `kind`다).

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `View.display_text` | `api/ask_view.py` | `api/ask.py`(마지막 `token`), 웹 `lib/reducer.ts`(step 5) |
| `ui_command` `show_aggregates`·`show_cost` | `api/ask_view.py` | `api/ask.py`(기존 `ui_command` 전송 루프를 그대로 지나감, 코드 변경 없음), 웹 `lib/types.ts`·컴포넌트(step 4~6) |
| 진행 이벤트 표 | `docs/ARCHITECTURE.md` | 웹 단계 표시줄(step 5) |
| 카드의 여섯 키 내보내기 | `api/ask_view.py`(`_CARD_FIELDS`) | 웹 `EvidenceCards`(step 6), `tests/test_web_contract.py`(step 6에서 키 대조) |

**기존 단언과의 충돌 점검(`rg`·`step_file_checks`로 확인한 소비자)**: `tests/test_ask_view.py`는 `result()`에 `limits` 키가 없어 `show_cost`가 나오지 않지만 `aggregates`가 있어 `show_aggregates`가 **새로 나온다** → `command(view, kind)` 형태로 종류를 골라 읽는 단언은 영향이 없고, `view.ui_commands == [...]` 정확 일치 단언이 있으면(예: 모델 UI 무시 테스트) 새 명령을 포함하도록 **기대값에 새 항목만 더하는 갱신**을 허용한다. `tests/test_api_ask.py`의 이벤트 순서 단언(`[name for name, _ in events] == ["step","tool_start","tool_start","step","token"]` 등)과 `ui_command` 개수·집합 단언도 같은 방식(새 `ui_command` 항목만 더함, 부분 비교로 바꾸지 않음)으로만 갱신한다. `tests/test_api_chat_client.py`·`tests/test_agents_live.py`·`tests/test_clarify_demo.py`·`tests/test_isolation_live.py`는 `ui_commands`를 `kind`로 걸러 읽으므로 영향이 없다(깨지면 수정하지 말고 `blocked`로 보고한다). `tests/test_api_assembly.py`는 `build_view`를 세 곳(73·1036·1275행 부근)에서 부르고 `show_plan`만 골라 읽으며, 1109행 부근은 `json.dumps(view.ui_commands)`에 비공개 문자열이 없음을 단언한다 → 새 명령이 그 단언을 깨면 단언을 약화하지 말고 `blocked`로 보고한다(이 파일은 수정 허용 목록에 없다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`("스트리밍 이벤트와 화면 명령"), `/docs/ADR.md`(ADR-011), `/docs/PHASES.md`(결정 표 50번: aggregates 분리 표시 요구)
- `/src/beautyads/api/ask_view.py`, `/src/beautyads/api/ask.py`, `/src/beautyads/api/sse.py`, `/src/beautyads/api/chat_client.py`
- `/src/beautyads/domain/supervisor.py`(`AGGREGATES_LABEL`, `verify_aggregates`), `/src/beautyads/agents/supervisor.py`(결과 조립부와 `_step` 호출 지점, 읽기 전용)
- `/tests/test_ask_view.py`, `/tests/test_api_ask.py`, `/tests/test_supervisor.py`(296행 이벤트 순서 테스트), `/tests/test_api_chat_client.py`, `/tests/test_clarify_demo.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/api/ask_view.py`, `src/beautyads/api/ask.py`, `docs/ARCHITECTURE.md`, `tests/test_ask_view.py`, `tests/test_api_ask.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `src/beautyads/api/ask_view.py`, `src/beautyads/api/ask.py`, `docs/ARCHITECTURE.md`, `tests/test_ask_view.py`, `tests/test_api_ask.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1. `api/ask_view.py`**: `_CARD_FIELDS`에 위 여섯 키를 **뒤에** 더한다. `View`에 `display_text: str | None = None`을 **맨 뒤에** 더한다. `build_view`의 주 경로(초기 `return` 경로 이후)에서 위 1~3 항목대로 `show_aggregates`·`show_cost` 명령과 `display_text`를 만든다. `display_text`는 `answer_text`를 만드는 같은 부품 중 "메시지 부분"만 이어 붙인다(기획안 본문 줄·`도구: 건수` 줄·aggregates 줄은 넣지 않는다). 기존 `answer_text` 조립은 바꾸지 않는다. 새 명령 본문도 `json_copy`를 거친다(`allow_nan=False`).

**2. `api/ask.py`**: 마지막 `token` 이벤트만 위 규칙대로 `display_text`를 조건부로 더한다. 다른 줄은 바꾸지 않는다.

**3. `docs/ARCHITECTURE.md`**: "스트리밍 이벤트와 화면 명령" 절에 (a) 실제로 나가는 이벤트 이름 전체(`step`·`tool_start`·`token`·`ui_command`·`error`·`needs_clarification`·`efficacy_unavailable`)와 종료 순서, (b) 위 진행 이벤트 순서 표(supervisor·research는 시작 이벤트 없음), (c) 새 명령 `show_aggregates`·`show_cost`와 `token`의 선택 키 `display_text`를 **추가**한다. 기존 문장은 고치지 않는다("네 종류" 표현이 사실과 달라지면 그 한 줄만 바로잡는다).

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `tests/test_ask_view.py`(케이스 추가에 한함): (1) `aggregates`·`aggregates_removed`가 있는 결과에서 `show_aggregates`의 `label == AGGREGATES_LABEL`, `model_written`이 살아남은 키만, `removed`가 제거된 키만, `verified_counts`가 `_counts` 결과와 같음, **`model_written`에 `removed` 키가 없고 `verified_counts`에 `model_written` 값이 없음**(분리 불변식). (2) `aggregates`도 `removed`도 없으면 명령이 없다. (3) `limits`가 유효하면 `show_cost`, 값이 `NaN`·`inf`·문자열·bool이면 명령이 없다. (4) `answer_text`는 기존과 바이트까지 같다(기존 단언 유지). (5) `display_text`: `plan` 결과에서 기획안 제목·훅·장면·카피 줄과 건수·aggregates 줄이 **없고** "기획안입니다."가 있다. `research` 결과에서 결론은 있고 aggregates 줄은 없다. 고정 문구 종류(`out_of_scope`·`no_evidence`·`limit_hit`)에서는 `answer_text`의 해당 문구가 `display_text`에 있다. 되묻기·`efficacy_unavailable`·`claim_choice_invalid` 경로는 `display_text is None`이고 `ui_commands == []`.
- `tests/test_ask_view.py`(카드 키, 케이스 추가 + 기대값 갱신): (9) `hydrate`가 여섯 키를 주면 카드가 그대로 담고, **주지 않은 가짜(기존 `hydrate` 헬퍼: 키 없음)이면 여섯 키가 `None`**이며 카드 키 집합이 정확히 `_CARD_FIELDS`와 같다. 기존 카드 단언(`view_count == 7`, `"thumbnail" not in card`)은 그대로 통과한다.
- `tests/test_api_ask.py`(케이스 추가에 한함): `create_app` 경로에서 (6) 정상 결과의 마지막 `token` 본문에 `display_text`가 있고 `text`는 `answer_text`와 같다, (7) 되묻기·효능 안내 `token` 본문은 정확히 `{"text": ...}`이다, (8) `ui_command` 이벤트에 `show_aggregates`·`show_cost`가 기존 명령 뒤에 온다.
- 합성 문장·분류 값을 기대값으로 굳히지 않는다(고정 문구 상수는 `domain/supervisor.py`에서 import해 비교한다).

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
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약(설치한 패키지 버전 포함, 승인 목록에서 조정한 것은 이유까지)"`
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

- `answer_text`의 조립·문구·순서를 바꾸지 마라. 이유: 터미널 `chat_client`(`final_text`)와 기존 테스트가 이 텍스트를 쓰고, 새 형식은 **추가**로만 낸다(승인 Q6: 기존 형식 유지).
- `sse.py`의 `EventName`에 새 이벤트 이름을 더하지 마라. 이유: 새 정보는 `ui_command`의 `kind`로 나가야 웹의 이벤트 분기와 기존 소비자(`parse_sse` 사용 코드)가 깨지지 않는다.
- aggregates의 값을 검증하거나 다시 계산하지 마라(`verify_aggregates`·`numbers_in_results`는 읽기만). `model_written` 값을 "검증됨"으로 표시하는 문구를 만들지 마라. 이유: 통과분도 모델이 쓴 값이다. 분리 표시는 출처 구분이고 신뢰 표시가 아니다(P5 결정 50, AGENTS.md "판정할 수 있는 것은 checks가 코드로 판정한다").
- 되묻기·효능 조회 불가·선택 오류 경로의 `ui_commands`를 비어 있지 않게 만들지 마라. 이유: `tests/test_ask_view.py`가 `ui_commands == []`로 고정한 계약이다.
- 이미지 비용을 `show_cost`에 합산하거나 `ledger_total`을 새로 읽지 마라(`limits.text_spent_usd`만 쓴다). 이유: 요청 상한은 텍스트 모델 비용 기준이고 이미지는 별도 상한이다(P5 결정 51, `RequestLimits` 주석). 라벨에 "이미지 제외"를 명시한다.
