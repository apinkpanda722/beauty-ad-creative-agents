# Step 5: web-chat

## 설계 검토 기록

**배경(P7 설계 승인 Q1~Q5, Q9)**: 대화 화면의 뼈대다. 작업 공간 선택, 요청 입력, 단계 진행 표시, 되묻기 선택 카드, 효능 조회 불가 안내, 오류·다시 시도까지 만든다. 근거 카드·기획안 카드·aggregates·분포·피드백·시안은 step 6, 그래프는 step 7이다(이 step은 화면 명령을 상태에 **저장만** 하고 그리는 자리 `CommandSlot`만 둔다).

**사용자가 확정한 화면 동작(P7 승인, 글자 그대로 따른다)**:
- Q1 효능 조회 불가(`efficacy_unavailable`): 서버 문구(`text`)를 안내 카드로 보여 주고 **선택지 없이** 새 요청만 허용한다. 시연 영상에는 쓰지 않는다.
- Q2 확인된 효능 0개(`reason == "no_efficacy_confirmed"`): 서버가 준 선택지 `none`("효능 강조 없이 진행")·`cancel`("중단") 두 개.
- Q3 "중단"(`cancel`): **서버 요청 없이** 카드를 닫고 한 줄 안내("중단했습니다. 새 요청을 입력하세요.").
- Q4 근거 없음(`no_evidence`): 서버 문구를 그대로(`token`의 `display_text ?? text`), 근거·기획안 카드 없음(서버가 명령을 내지 않는다).
- Q5 중간 오류·한도: 이미 받은 화면 명령(근거 카드 등)은 유지하고 오류 코드와 "다시 시도" 버튼을 보인다. 한도 도달 문구는 서버 텍스트다(오류가 아니라 정상 종료 `token`).
- Q9 작업 공간: 서버는 시작할 때 정한 그룹(`dev` 또는 `test`) 하나만 연다. 화면에 "작업 공간은 서버를 시작할 때 정한 그룹 하나만 보입니다. 바꾸려면 서버를 다시 시작하세요."를 적는다.

**서버 계약(코드로 확인한 사실)**:
- 이벤트와 순서: `api/ask.py`와 `docs/ARCHITECTURE.md`(step 3이 적은 이벤트 절). 단계 이벤트 순서는 `tests/test_supervisor.py`의 `test_events_arrive_at_stage_boundaries_including_tools_reworks_image`가 고정했다: `step(supervisor,end,ok)` → `step(research,end,*)` → `tool_start`들 → 기획안마다 [`step(planning,start,running)` → `step(evaluation,end,*)` → `step(rework,end,done)`×되돌림 → `step(image,end,ok|failed)`] → `step(supervisor,done,<kind>)`. **supervisor·research는 시작 이벤트가 없다**(끝날 때만 온다).
- 종료 형태 네 가지: ① 정상 `ui_command`들 → `token{text, display_text?}`, ② `needs_clarification` → `token{text}`(`text`는 clarification의 `text`와 같다), ③ `efficacy_unavailable` → `token{text}`, ④ `error{code, detail?, error_code?}`. HTTP 오류는 200이 아니다(400·403·422, 본문 `{"detail": "코드"}`; 422는 `detail`이 목록일 수 있다).
- `needs_clarification` 본문(`api/ask_view.py`): `reason`(`requested_not_confirmed` | `no_claim_requested` | `no_efficacy_confirmed`), `requested_claim`, `requested_label`, `available: [{claim, label}]`, `text`, `options: [{id, label}]`, 선택지 id는 `keep_requested`·`select_confirmed`·`select_one`·`select_many`·`none`·`cancel`(`domain/supervisor.py` `ClarifyOption`).
- 선택 후 재요청 본문(`ClaimChoice`, `domain/supervisor.py`): **같은 `message`·같은 `thread_id`** + `claim_choice`. 검증 규칙: `selected`는 `claims` 비어 있으면 안 됨, `keep_requested`는 `requested_claim` 필수, `selected`가 아니면 `claims`가 비어야 함, `claims`에 `other`·중복 불가, 확인된 효능 밖이면 서버가 `CLAIM_CHOICE_INVALID`로 거절. `eval/clarify_demo.py`가 쓰는 본문 모양: ②의 확인된 효능 선택은 `{"mode":"selected","claims":[...],"requested_claim":<요청 효능>}`, ③은 `{"mode":"selected","claims":[...],"requested_claim":null}`, `none`은 `{"mode":"none","claims":[],"requested_claim":<요청 효능 또는 null>}`, `keep_requested`는 `{"mode":"keep_requested","claims":[],"requested_claim":<요청 효능>}`.
- 서버 오류 코드(코드에서 확인): `TENANT_CONTEXT_MISSING`·`TENANT_NOT_ALLOWED`·`TENANT_MISMATCH`(`api/session.py`), `WORKSPACE_MISSING`·`IMAGE_DISABLED`·`ASK_INPUT_INVALID`(`api/ask.py`), `AGENT_INTERNAL_ERROR`·`CLAIM_CHOICE_INVALID`(SSE `error`).
- `GET /workspaces`(step 2): `{"workspaces": [{"tenant_id","display_name","brand","product_name"}], "image_enabled": bool}`.

**시연 요청 문장(P7 승인 확정, 입력창 채우기용 예시 칩. 모델 출력이 아니라 입력 문장이다)**:

| 작업 공간 | 칩 | 문장 |
|---|---|---|
| `test-isntree` | 정상 | 보습을 내세운 세럼 광고 기획안 1안을 만들어 주세요. |
| `test-isntree` | 되묻기 ② | 진정 효과를 내세운 세럼 광고 기획안 1안을 만들어 주세요. |
| `test-isntree` | 되묻기 ③ | 이 세럼의 광고 기획안 1안을 만들어 주세요. |
| `test-bojoseon` | 정상 | 자외선 차단을 내세운 선케어 광고 기획안 1안을 만들어 주세요. |
| `test-bojoseon` | 되묻기 ② | 모공과 피지 관리를 내세운 선케어 광고 기획안 1안을 만들어 주세요. |
| `test-bojoseon` | 되묻기 ③ | 이 선세럼 제품의 광고 기획안 1안을 만들어 주세요. |
| `dev-mixsoon` | 정상 | 보습을 내세운 세럼 광고 기획안 1안을 만들어 주세요. |
| `dev-mixsoon` | 되묻기 ② | 진정 효과를 내세운 세럼 광고 기획안 1안을 만들어 주세요. |
| `dev-mixsoon` | 되묻기 ③ | 이 세럼의 광고 기획안 1안을 만들어 주세요. |
| `dev-cosrx` | 정상 | 자외선 차단을 내세운 선케어 광고 기획안 1안을 만들어 주세요. |
| `dev-cosrx` | 되묻기 ② | 모공과 피지 관리를 내세운 선케어 광고 기획안 1안을 만들어 주세요. |
| `dev-cosrx` | 되묻기 ③ | 이 선세럼 제품의 광고 기획안 1안을 만들어 주세요. |

(`test-bojoseon`은 인삼선세럼이라 되묻기 ③ 문장을 "이 선세럼 제품의 …"로 확정했다. 이 문장의 test B 해석은 live 리허설 전에는 확인되지 않았다. 칩은 입력창을 채울 뿐 자동으로 보내지 않는다. 시연 문장의 근거 소재가 충분한지는 live 리허설 전에는 모른다. 이 step은 칩의 문장을 서버 응답의 기대값으로 쓰지 않는다.)

**설계 결정**:
- 상태는 순수 reducer(`web/lib/reducer.ts`)에 둔다. 한 번의 요청 = 한 **턴**. 턴 상태: `running` | `done` | `needs_choice` | `unavailable` | `error` | `stopped`. 턴은 `message`, `claimChoice`, 받은 단계 이벤트 목록, `tool_start` 목록, 화면 명령 목록(저장만), 표시 텍스트(`display_text ?? text`; 되묻기·효능 안내 턴은 카드가 `text`를 그리므로 `token`을 텍스트로 중복 표시하지 않는다), `clarification`·`unavailable`·`error`를 가진다.
- **스트림이 끝 신호(`token`·`error`·`needs_clarification`·`efficacy_unavailable` 중 하나) 없이 끝나면 성공이 아니라 클라이언트 오류 `STREAM_ENDED_EARLY`다**(FP-C05: 중단을 완료로 확정하지 않는다).
- 단계 표시줄은 순수 함수 `deriveStages(stepEvents, turnStatus)`로 만든다: 요청 해석(`supervisor` end) → 리서치(`research` end) → 기획(`planning` start) → 평가(`evaluation` end, 되돌림 `rework` 횟수 배지) → 시안(`image` end, 이벤트가 있을 때만) → 완료(`supervisor` done). 시작 이벤트가 없는 단계는 **앞 단계가 끝나는 순간부터 다음 단계가 진행 중**으로 본다. 상태가 `failed`인 이벤트는 실패 표시. 기획안이 여러 개면 기획·평가 이벤트가 반복되므로 횟수를 센다.
- 되묻기 카드는 서버가 준 `text`와 `options[].label`을 **그대로** 보여 준다(문구의 단일 출처는 서버 `clarification_texts`, 웹에서 다시 쓰거나 번역하지 않는다). 선택지 id별 동작: `keep_requested`/`none`은 바로 재요청, `select_confirmed`/`select_one`은 `available` 효능 칩 **하나** 선택 후 재요청, `select_many`는 칩 **하나 이상** 선택 후 재요청, `cancel`은 서버 요청 없이 턴을 `stopped`로 닫는다. 칩은 `available[].label`(서버 표시 이름)만 쓴다.
- 재요청은 새 턴이고 `message`는 원래 요청과 같으며 선택한 선택지 라벨을 "선택: ○○"로 보여 준다. "다시 시도"도 같은 `message`·`claimChoice`·`thread_id`의 새 턴이다.
- `thread_id`는 첫 응답의 `X-Thread-Id`를 작업 공간이 바뀔 때까지 재사용한다. 작업 공간을 바꾸면 대화를 비우고 진행 중 요청을 `AbortController`로 취소한다.
- 한국어 입력: **IME 조합 중(`isComposing`)의 Enter는 전송하지 않는다**. Enter 전송, Shift+Enter 줄바꿈, 입력은 2000자 상한(`AskRequest.message` 최대 2000), 실행 중 입력·전송 비활성.
- 시안 이미지 체크박스는 `image_enabled`가 true일 때만 보이고 기본 켬(P7 승인 Q8: 시연 구성은 시안 포함). false이면 `with_image`를 보내지 않는다.
- 테넌트는 작업 공간 목록에서만 고른다(사용자가 문자열로 입력하지 않는다). `localStorage`는 쓰지 않는다.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `Turn`·`State`·액션 | `web/lib/reducer.ts` | `web/components/*`, step 6·7 |
| `deriveStages` | `web/lib/stages.ts` | `StepBar.tsx` |
| `buildChoice`·`validateChoice` | `web/lib/claim.ts` | `ClarifyCard.tsx` |
| 예시 문장 | `web/lib/examples.ts` | `Chat.tsx` |
| `getWorkspaces`·`Workspace` 타입 | `web/lib/api.ts`·`web/lib/types.ts`(**추가만**) | `WorkspacePicker.tsx`, `app/page.tsx` |
| 저장된 화면 명령 | `reducer.ts` | `CommandSlot.tsx`(자리, step 6이 채움) |

**기존 단언과의 충돌 점검**: `web/tests/api.test.ts`·`sse.test.ts`(step 4)는 건드리지 않고 `api.ts`·`types.ts`는 **함수·타입 추가만** 한다(`tests/test_web_contract.py`가 타입 이름 드리프트를 검사하므로 서버에 없는 이벤트·명령 이름을 더하지 않는다). `web/app/page.tsx`는 step 4의 자리 표시 화면을 교체하므로 `web/tests/smoke.test.tsx`가 새 화면에 맞게 통과하도록 **그 테스트의 렌더 대상 단언만** 새 화면(작업 공간 목록을 불러오는 중 문구 또는 제목)에 맞게 갱신한다(테스트 삭제·약화 금지).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`(스트리밍 이벤트와 화면 명령), `/docs/PRD.md`(시연과 포트폴리오 산출물)
- `/src/beautyads/api/ask.py`, `/src/beautyads/api/ask_view.py`(`needs_clarification`·`efficacy_unavailable` 본문), `/src/beautyads/api/graph_routes.py`(`/workspaces` 응답), `/src/beautyads/domain/supervisor.py`(`ClaimChoice`, `ClarifyOption`, `clarification_texts`), `/src/beautyads/eval/clarify_demo.py`(`_choice`·`_scenario`: 선택 분기 본문 모양, 읽기 전용)
- `/tests/test_supervisor.py`(296행 단계 이벤트 순서), `/tests/test_api_ask.py`(되묻기·효능 안내 SSE 형태: 668행·788행 근처)
- `/web/lib/types.ts`, `/web/lib/sse.ts`, `/web/lib/api.ts`, `/web/app/page.tsx`, `/web/tests/`(step 4 산출물)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `web/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1. `web/lib/`**: `reducer.ts`(위 상태·액션: 작업 공간 선택, 요청 시작, 스트림 이벤트 수신, 스트림 종료, 요청 실패, 선택 제출, 중단, 다시 시도), `stages.ts`(`deriveStages`), `claim.ts`(`buildChoice(optionId, clarification, selectedClaims): ClaimChoice | null`은 `cancel`이면 `null`, `validateChoice`는 서버 `ClaimChoice` 규칙과 같은 검증), `examples.ts`(위 표), `api.ts`에 `getWorkspaces()`(`GET /api/workspaces`, 헤더 없음)·타입에 `Workspace`·`WorkspacesResponse` 추가. 에러 코드의 한국어 설명 표(위 "서버 오류 코드" + `STREAM_ENDED_EARLY` "응답이 중간에 끊겼습니다")는 화면에 **원 코드를 함께** 보인다.

**2. `web/components/`**: `WorkspacePicker.tsx`(작업 공간 선택, `display_name`·`brand`·`product_name` 표시, Q9 안내문), `Chat.tsx`(입력·칩·이미지 체크박스·전송·턴 목록), `StepBar.tsx`, `ClarifyCard.tsx`, `Notice.tsx`(효능 조회 불가 안내·오류·중단 안내), `CommandSlot.tsx`(저장된 화면 명령을 그릴 자리: 이 step에서는 아무것도 그리지 않는다), 턴 하나를 그리는 컴포넌트. `web/app/page.tsx`는 작업 공간 목록을 불러와(`getWorkspaces`) 실패하면 "API 서버에 연결하지 못했습니다. 서버가 실행 중인지 확인하세요."를 보이고, 성공하면 선택기와 대화 화면을 그린다. 접근성: 입력·버튼에 레이블, 진행 영역은 `aria-live="polite"`.

**3. 테스트(`web/tests/`, 가짜 `fetch`와 가짜 SSE 스트림만, 합성 문장만)**
- `reducer.test.ts`: (1) 정상 흐름 이벤트열(위 순서)이 단계·도구·화면 명령·표시 텍스트로 쌓임, `display_text`가 있으면 그것이 우선. (2) `needs_clarification` 뒤 `token`이 와도 텍스트가 중복 표시되지 않음. (3) **끝 신호 없이 스트림이 끝나면 `error`/`STREAM_ENDED_EARLY`**. (4) `error` 이벤트가 와도 이미 받은 화면 명령이 유지됨. (5) 작업 공간 변경 시 대화 초기화. (6) 재요청·다시 시도가 같은 `message`·`threadId`의 새 턴.
- `stages.test.ts`: `tests/test_supervisor.py`의 이벤트열(되돌림 2회·시안 있음, 기획안 3개)에서 단계 상태·되돌림 배지·시안 단계·완료, 실패 상태 이벤트의 표시, 이벤트가 없는 초기 상태(요청 해석 진행 중).
- `claim.test.ts`: 선택지 id별 `ClaimChoice` 본문 **정확 일치**(위 모양: ②의 `selected`는 `requested_claim`을 요청 효능으로, ③은 `null`), `cancel`은 `null`, 칩을 고르지 않은 `select_one`·`select_many`는 검증 실패, 서버 검증 규칙 위반(`other`·중복·`keep_requested`인데 `requested_claim` 없음) 거부.
- 컴포넌트 테스트(RTL): (7) `ClarifyCard`가 서버 `text`·`options[].label`을 그대로 그리고 `available` 밖 효능 칩이 없음, `select_many`는 하나 이상 고르기 전에는 제출 비활성, **`cancel` 선택은 `fetch`를 한 번도 부르지 않고** "중단했습니다. 새 요청을 입력하세요."를 보임, 선택 제출은 `POST /api/ask` 본문에 같은 `message`·`thread_id`와 위 `claim_choice`가 있음(가짜 `fetch`가 받은 본문 직접 검사). (8) 효능 조회 불가 카드에는 선택지가 없고 입력창이 활성. (9) 오류 카드가 코드와 "다시 시도"를 보이고 누르면 같은 본문으로 재요청. (10) IME 조합 중 Enter는 전송하지 않고 조합이 끝난 Enter는 전송, Shift+Enter는 줄바꿈, 2000자 초과 입력 불가. (11) `image_enabled: false`이면 체크박스가 없고 본문에 `with_image`가 없다(true이면 기본 켬). (12) 작업 공간 선택 후에만 입력이 활성이고 칩 클릭은 입력창만 채움(`fetch` 호출 없음).
- 서버가 만든 문장·분류 값을 기대값으로 굳히지 않는다(합성 문자열을 쓴다).

## Acceptance Criteria

```bash
make verify   # ruff + pytest + pnpm lint·typecheck·test 통과
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

- 서버가 준 되묻기 문구·선택지 라벨·오류 문구를 웹에서 다시 쓰거나 번역하지 마라(오류 코드의 한국어 설명은 원 코드와 함께 보이는 보조 설명만). 이유: 문구의 단일 출처는 서버(`clarification_texts`, `EFFICACY_UNAVAILABLE_TEXT`)이고, 두 곳에 두면 서로 달라진다.
- `cancel`에서 요청을 보내지 마라. 끝 신호 없이 끝난 스트림을 성공으로 처리하지 마라. 이유: 중단은 서버 요청이 없다는 사용자 결정(Q3)이다. 중단·끊김을 완료로 확정하면 안 된다(FP-C05).
- 한국어 IME 조합 중 Enter로 전송하지 마라. 이유: 한글 입력에서 조합이 끝나기 전 전송하면 마지막 글자가 중복·누락된다.
- 사용자가 테넌트 문자열을 입력하게 하거나 `localStorage`·URL 쿼리로 테넌트를 받지 마라. 이유: `tenant_id`는 서버가 준 작업 공간 목록에서만 나온다(ADR-009, AGENTS.md CRITICAL).
- `src/`·`tests/`(파이썬)·`Makefile`·`web/lib/sse.ts`의 파싱 규칙·step 4의 기존 테스트 단언을 약화하거나 바꾸지 마라. 서버(`make serve`)와 `pnpm dev`를 서버 연결 상태로 실행하지 마라. 이유: 서버 계약 변경은 step 2·3의 범위이고 서버 실행은 사용자가 한다(A-FP-040). 테스트는 가짜 `fetch`만 쓴다.
