# Step 5: clarify-demo

## 설계 검토 기록

**배경(사용자 확정, 이슈 #55)**: step 1~4가 효능 되묻기 흐름(①②③, 효능 0개 되묻기, 조회 실패·제품 미등록 차단)을 API까지 만들었다. 이 step은 사용자가 **직접 눈으로** 인수 점검하는 개발용 도구 `make demo-clarify`와 기록(결과 문서 5절·`TROUBLESHOOTING_LOG`)을 만든다. 선택 카드 UI는 P7이다. 도구 출력은 JSON이 아니라 **읽을 수 있는 한국어**(요청, 기대, 시스템 응답, 되묻기 문구와 선택지, 선택 뒤 기획안 요약)다. 실제 호출 실행(`make demo-clarify`, 모델 호출 있음)은 **사용자가 한다.** 이 step 안에서는 `--dry-run`(모델·네트워크·DB 없음)만 실행할 수 있다.

**사용자 확정 시나리오 9개(요청 문장은 글자 그대로)**:

| # | 구분 | 작업 공간 | 요청 문장 | 조회 | 기대(코드가 판정하는 것) |
|---|---|---|---|---|---|
| 1 | 효능 맞음 | `dev-mixsoon` | "보습을 내세운 세럼 광고 기획안 1안을 만들어 주세요." | 실제 | 되묻기 없이 기획안, `claimed_efficacy`가 확인된 효능의 부분집합 |
| 2 | 효능 맞음 | `dev-mixsoon` | "피부 장벽 강화를 내세운 세럼 광고 기획안 1안을 만들어 주세요." | 실제 | 같음 |
| 3 | 효능 맞음 | `dev-cosrx` | "자외선 차단을 내세운 선케어 광고 기획안 1안을 만들어 주세요." | 실제 | 같음 |
| 4 | 근거 없음 ② | `dev-mixsoon` | "진정 효과를 내세운 세럼 광고 기획안 1안을 만들어 주세요." | 실제 | `needs_clarification`(`requested_not_confirmed`), 선택지 `keep_requested`·`select_confirmed`·`none`, 첫 호출은 리서치·기획 0회 |
| 5 | 근거 없음 ② | `dev-cosrx` | "모공과 피지 관리를 내세운 선케어 광고 기획안 1안을 만들어 주세요." | 실제 | 같음 |
| 6 | 지정 없음 ③ | `dev-mixsoon` | "이 세럼의 광고 기획안 1안을 만들어 주세요." | 실제 | `needs_clarification`(`no_claim_requested`), 선택지 `select_one`·`select_many`·`none` |
| 7 | 지정 없음 ③ | `dev-cosrx` | "이 선세럼 제품의 광고 기획안 1안을 만들어 주세요." | 실제 | 같음 |
| 8 | 조회 실패 | `dev-mixsoon` | 1번과 같은 문장 | **가짜 `claims_fn`이 `failed`** | `efficacy_unavailable`(`failed`), 기획안 없음, 리서치·기획 호출 0회, trace에 작업 공간·제품·상태가 남음 |
| 9 | 확인 효능 0개 | `dev-mixsoon` | 9a "이 세럼의 광고 기획안 1안을 만들어 주세요." / 9b "진정 효과를 내세운 세럼 광고 기획안 1안을 만들어 주세요." | **가짜 `claims_fn`이 `ok`+빈 목록** | 9a는 `needs_clarification`(`no_efficacy_confirmed`, 선택지 `none`·`cancel`), 9b는 `requested_not_confirmed` ②이고 선택지가 `keep_requested`·`none` 두 개뿐(`select_confirmed` 없음) |

- 확인된 효능의 실측값(2026-11-20, 읽기 전용 질의, 모델 호출 없음): `dev-mixsoon`(히알레배 포어 버블 세럼 70ml) = 보습·미백·피부 장벽·주름 개선(안티에이징), `dev-cosrx`(울트라 라이트 인비저블 선세럼 50ml) = 보습·미백·주름 개선(안티에이징)·자외선 차단. 도구의 `--dry-run`은 이 값을 가짜 `claims_fn`의 기본값으로 쓰며 출력에 "측정값(2026-11-20), 실제 조회 아님"을 표시한다.
- **선택 후 분기(②③ 전체)**: ②(4·5·9b)는 `keep_requested`(`requested_claim`=요청 효능)·`selected`(확인된 효능 중 첫 효능)·`none`. 9b는 `keep_requested`·`none`만. ③(6·7)은 한 개 선택(`selected` 1개)·여러 개 선택(`selected` 2개)·`none`. 9a는 `none`(선택하면 기획안)과 `cancel`(화면에서 취소하며 서버 요청이 없음을 출력으로 설명만 한다). 각 선택은 원래 `message`와 같은 `thread_id`에 `claim_choice`를 얹은 재요청이다.
- **시나리오 8·9는 모델을 쓰지 않는다**: 가짜 `decide`(요청 문장 → 닫힌 값 결정 표)·가짜 `claims_fn`·가짜 리서치·가짜 기획을 `run_request`에 넣어 실제 정책·API·뷰 코드를 그대로 지나가게 한다. `--dry-run`은 1~7번도 같은 가짜 구성으로 돌린다. live(사용자 실행)에서 1~7번만 실제 조립(`assemble_full`)·실제 모델을 쓴다.

**비용(호출 수 기준, 가정이며 실측은 첫 실행의 원장으로 다시 계산한다, FP-C06)**: live는 1~7번뿐이다. 전체 실행 15회(1~3번 3회 + ②③ 분기 재요청 12회)와 `decide`만 부르는 되묻기 첫 호출 4회. 개발 구성(평가 haiku)은 요청당 약 $0.0105 → 약 $0.17. **세션 상한은 OpenAI+Anthropic 합계 $0.40이며 도달하면 남은 시나리오를 대기로 두고 멈춘다**(원장 증가분으로 계산). 단가는 2026-11-20 원장의 목적별 호출당 평균(`decide` $0.00008, 리서치 $0.00037, 기획 $0.0042, 평가 haiku $0.00082)에서 구한 가정이다.

**식별자 전수 대조(현재 코드, 모두 열어 확인)**:
- `eval/agents_live.py`(읽기 전용 참고): `RUN_CAPS`, `_CONFIGS = {"dev": ("claude-haiku-5-5", False), "official": (..., False), "image": (..., True)}`, `_preflight(*, with_image)`(내부에서 `live_agent.preflight()`와 `ANTHROPIC_API_KEY` 확인), `_totals(settings)`(`provider_total(settings.ledger_path, "openai"|"anthropic")`), `_request(...)`·`main(...)`의 흐름: `create_app(partial(assemble_full, settings=settings, group="dev", evaluation_model=model, with_image_enabled=False, limits=limits))` → `run_ask_once(app, tenant_id=..., message=..., with_image=False)` → `outcome.events`·`outcome.ui_commands`(`show_plan`) 읽기, `load_workspaces(Path("config/workspaces.yaml"))`로 `group == "dev"` 검사, 출력은 `data/interim/agents_live/`(gitignore).
- `api/chat_client.py`: `run_ask_once(app, *, tenant_id, message, with_image=False, thread_id=None) -> AskOutcome`(`events`·`ui_commands`·`final_text`·`status_code`), 본문 `{"message", "with_image"[, "thread_id"]}`. **`claim_choice` 인자가 없다.**
- `api/app.py`: `Assembly(graph, tenants, allowed_tenants, as_of, last_collected_at, chat, tool_runner, close, workspaces, price_bands, ask, hydrate, design_dir, image_enabled)`, `create_app(assemble)`. 가짜 조립은 `tests/test_api_ask.py`의 `services(ask=...)`·`AskTenants`처럼 만든다.
- `agents/supervisor.py`: `run_request(*, message, ctx, profile, feedback, decide_fn, research_fn, plan_eval_fn, spent_fn, limits, on_event, claims_fn, context_mode, claim_choice)`와 결과 키(`kind`·`clarification`·`efficacy_unavailable`·`claim_choice`·`plans`·`product_display`·`available_efficacy`·`available_efficacy_status` 등). `obs/trace.py`: `build_trace(...)`·`append_trace(path, record)`·`read_traces(path)`·`TraceRecord.efficacy_unavailable`(step 4).
- `analysis/prompts.py`: `CLAIM_DISPLAY_NAMES`(효능 표시 이름). `domain/supervisor.py`: 문구 상수와 `clarification_texts`.
- 기존 Makefile 소비자 테스트는 타깃별 줄을 읽기만 한다(`tests/test_agents_live.py:598-601` 등 `live-agents`·`.PHONY: live-agents`). 새 타깃은 `live-agents`처럼 **별도 `.PHONY: demo-clarify` 블록**으로 더하고 기존 `.PHONY` 줄·`verify` 레시피는 건드리지 않는다. `verify`에 `demo-clarify`를 넣지 않는다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 실제 API 호출은 사용자가 실행한다, `make verify`는 키·네트워크 없이 통과해야 한다, 유료 모델 호출 직전 공급사별 누적액 검사, 키·요청 본문을 기록에 남기지 않는다
- `/docs/results/2026-11-20-p6-final.md`(5절), `/docs/TROUBLESHOOTING_LOG.md`(마지막 항목 형식)
- `/src/beautyads/eval/agents_live.py`(전체, 읽기 전용), `/src/beautyads/eval/live_agent.py`(`preflight`, 읽기 전용), `/src/beautyads/api/chat_client.py`, `/src/beautyads/api/app.py`, `/src/beautyads/api/ask_view.py`, `/src/beautyads/agents/supervisor.py`(`run_request`), `/src/beautyads/domain/supervisor.py`, `/src/beautyads/obs/trace.py`, `/src/beautyads/analysis/prompts.py`(`CLAIM_DISPLAY_NAMES`), `/config/workspaces.yaml`(읽기 전용), `/Makefile`
- `/tests/test_agents_live.py`(구조 참고, 읽기 전용), `/tests/test_api_chat_client.py`, `/tests/test_api_ask.py`(`services`·가짜 조립 참고)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/clarify_demo.py`(새 파일), `src/beautyads/api/chat_client.py`, `Makefile`, `tests/test_clarify_demo.py`(새 파일), `tests/test_api_chat_client.py`, `docs/results/2026-11-20-p6-final.md`, `docs/TROUBLESHOOTING_LOG.md`

열람 금지 경로: `data/interim/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `src/beautyads/eval/clarify_demo.py`, `src/beautyads/api/chat_client.py`, `Makefile`, `tests/test_clarify_demo.py`, `tests/test_api_chat_client.py`, `docs/results/2026-11-20-p6-final.md`, `docs/TROUBLESHOOTING_LOG.md`

새 식별자: `clarify_demo`(모듈), `make demo-clarify`, `SCENARIOS`(위 9개 표), `run_ask_once(..., claim_choice=None)`. **테스트를 먼저 쓴다(TDD).**

**1. `api/chat_client.py`**: `run_ask_once`에 키워드 인자 `claim_choice=None`을 더한다. 값이 있을 때만 요청 본문에 `"claim_choice"`로 넣는다(없으면 본문이 지금과 같다). 반환 `AskOutcome`·다른 인자 불변.

**2. 도구(`eval/clarify_demo.py`)**
- CLI: `python -m beautyads.eval.clarify_demo [--config {dev,official}] [--dry-run] [--only ID ...]`. 기본 `--config dev`(평가 haiku; `official`은 평가 sonnet). 알 수 없는 인자·알 수 없는 `--only` ID는 `ARGUMENT_ERROR`(종료 코드 2, 인자 값을 출력하지 않음; `agents_live`의 `_Parser` 방식). `--only` ID는 `1`~`7`, `8`, `9a`, `9b`.
- `SCENARIOS`: 위 표의 9개(9a·9b 포함 10개 행)를 닫힌 데이터로 정의한다(`id`, `tenant_id`, `message`, `lookup`: `"real" | "fake_failed" | "fake_empty"`, 기대 `kind`/`reason`/선택지 id 목록, `branches`: `claim_choice` 본문 목록). 모든 `tenant_id`는 `config/workspaces.yaml`에서 `group == "dev"`여야 하고 아니면 실행하지 않는다(`PREFLIGHT_FAILED WORKSPACE_GROUP_INVALID`).
- **dry-run**: 모델·네트워크·DB·`.env` 없이 동작한다(설정·키 함수를 부르지 않는다). 가짜 `Assembly`(`ask`가 `run_request`에 가짜 `decide`·`claims_fn`·리서치·기획을 넣어 호출)로 `create_app` → `run_ask_once` 경로를 그대로 통과시켜 SSE·`build_view`를 실제 코드로 거친다. 가짜 기획은 `claim_choice`(`handoff["claim_choice"]`)에 따라 `claimed_efficacy`를 `selected`면 `claims`, 그 밖에는 `[]`로 돌려준다(프롬프트 동작의 시늉이며 출력에 "가짜 기획(dry-run)"이라고 표시한다). 가짜 `claims_fn`은 시나리오의 `lookup`과 작업 공간에 따라 위 실측 효능 목록, `("[]", "failed")`, `([], "ok")`를 돌려준다. 시작할 때 계획(시나리오 수, 전체 실행·되묻기 첫 호출 건수, 개발 구성 예상 비용 약 $0.17·상한 $0.40, "단가는 2026-11-20 원장 평균 가정, 실측 아님")을 한국어로 출력한다.
- **live**(사용자가 `ARGS` 없이 또는 `--config`로 실행): 시작 전 환경 점검(`agents_live`의 `_preflight`와 같은 점검; 실패하면 `PREFLIGHT_FAILED <코드>`를 출력하고 시작하지 않는다, B-FP-051). 1~7번은 `agents_live`와 같은 방식으로 실제 조립(`assemble_full`, `group="dev"`, 평가 모델은 구성에서)을 쓰고, 8·9번은 dry-run과 같은 가짜 구성을 쓴다(모델 호출 없음). **세션 상한: 시작 시점 원장 합계(OpenAI+Anthropic)를 기준으로 증가분이 $0.40에 닿으면 남은 시나리오를 `pending`으로 두고 `STOPPED BUDGET_REACHED`로 종료 코드 2**(호출 직전 검사). 일일 한도·크레딧 오류(`DAILY_LIMIT`·`RATE_LIMIT`·`HTTP_429`·`CREDITS_DEPLETED`)는 재시도하지 않고 멈춘다(`agents_live`의 `_STOP_CODES`와 같은 규칙). 한 시나리오의 실패는 기록하고 다음으로 넘어간다.
- **읽기 출력(한국어, 시나리오마다)**: 제목(`[번호/전체] 구분 · 작업 공간 · 제품명`), `요청:`, `기대:`(위 표의 코드 판정 기대), `시스템 응답:`(`기획안` / `되묻기 ②` / `되묻기 ③` / `효능 근거 조회 실패로 중단` / `제품 미등록으로 중단` 중 하나와, 되묻기면 안내 문구 `text`와 번호 붙은 선택지 라벨, 중단이면 오류 문구), 분기마다 `선택: <선택지 라벨> → 재요청`, `기획안 요약:`(제목·훅 문구·카피 줄·`claimed_efficacy`의 한글 이름·`efficacy_status`·`unknown_count`; **터미널에만 출력하고 요약 JSON에는 저장하지 않는다**), `확인 포인트:`(소구 방향·`claimed_efficacy` 값·단정 표현 없음), `단정 의심 표현(참고, 코드 판정 아님):`(훅·카피에서 `입증`·`확실`·`보장`·`치료`·`100%`·`완벽`이 있으면 그 낱말을 표시), `코드 판정:`(`일치`/`불일치` + 불일치 이유 코드; 기대 `kind`·`reason`·선택지 id 집합·되묻기 첫 호출의 리서치·기획 호출 0회(`steps`에 `research`·`planning` 단계가 없음)·`claimed_efficacy ⊆ available_efficacy`·`keep_requested`에서 `claimed_efficacy`에 요청 효능이 없음). **모델이 만든 문장은 `코드 판정`의 기대값으로 쓰지 않는다**(닫힌 값·호출 기록·구조만). 8번은 trace 파일(`data/interim/clarify_demo/traces.jsonl`)을 읽어 `tenant_id`·`reason`·`brand`·`product_name`이 남았는지 출력하고 요청 본문이 없음을 확인한다(가짜 조립의 `ask`가 `build_trace`·`append_trace`로 직접 남긴다).
- 요약 JSON은 `data/interim/clarify_demo/<run_id>.json`에 쓴다(gitignore 경로): 시나리오 ID·`kind`·`reason`·선택지 id·분기 `claim_choice` 본문·`claimed_efficacy`·`efficacy_status`·코드 판정·공급사별 비용 증가분·`pending`만(요청 본문·모델 문장·키 없음). 종료 코드: 모두 일치 0, 인자·환경 오류·예산 중단 2, 시나리오 실패 또는 불일치 3.

**3. `Makefile`**: `live-agents` 블록 모양 그대로 `.PHONY: demo-clarify` / `demo-clarify:` / `\tuv run python -m beautyads.eval.clarify_demo $(ARGS)`를 파일 끝에 더한다. 기존 줄·`verify` 레시피는 바꾸지 않는다.

**4. 문서**
- `docs/results/2026-11-20-p6-final.md` 5절 끝에 두 줄을 더한다(기존 문장은 고치지 않는다): "실험 실행기(`live-agents`·`e2e5`)는 되묻기를 처리하지 않는다. 효능을 지정하지 않은 요청은 `needs_clarification`으로, 효능 근거 조회 실패·제품 미등록은 `efficacy_unavailable`로 끝나므로 이 코드로 실험을 다시 돌리려면 실행기가 `claim_choice`를 넘기도록 따로 바꿔야 한다(최종 실험은 끝났고 재실행하지 않는다)." 그리고 "효능 근거 없이 작성한 기획안은 신뢰할 수 없다는 사용자 결정에 따라 조회 실패·제품 미등록·확인 효능 0개에서는 기획을 진행하지 않거나 되묻는다(이슈 #55)."
- `docs/TROUBLESHOOTING_LOG.md` 끝에 세 항목을 더한다(기존 항목 형식, **문제/원인/해결/근거**): (a) `tests/test_isolation_live.py`의 `NOW = 2026-11-19` 고정 시계와 코드의 `datetime.now(UTC)` 불일치로 UTC 날짜가 넘어가면 변경 없는 main에서도 13건 이상 실패(해결: autouse 시계 고정 픽스처, 근거: step 1), (b) 프롬프트·버전을 바꾸는 step이 `tests/test_prereg.py::test_none_measurement_preserves_original_bytes`(렌더링 전체 해시, 동결 줄 포함)를 깬 것을 허용 목록에 넣지 못해 blocked(근거: step 3), (c) 효능 조회 `failed`·`skipped`를 "효능 없이 진행"으로 둔 초기 설계가 근거 없는 기획안을 만들 수 있어 사용자가 차단·되묻기로 바꿈(근거: step 4). 사실만 쓰고 추측을 적지 않는다.

**테스트(합성 데이터, 모델·네트워크·DB·`.env` 없음, `tmp_path`)**
- `tests/test_clarify_demo.py`: (1) `SCENARIOS` 정합: ID 집합이 정확히 `{"1","2","3","4","5","6","7","8","9a","9b"}`, 요청 문장이 위 표와 글자 그대로 같음, 모든 `tenant_id`가 `config/workspaces.yaml`의 `group == "dev"`, `lookup` 값이 닫힌 목록 안, 기대 `reason`·선택지 id가 도메인의 `ClarifyReason`·`ClarifyOption` 값 안. 검사한 시나리오 수가 0이면 실패(B-FP-069). (2) `--dry-run`: 종료 코드 0, `assemble_full`·`load_settings`·`get_setting`이 불리지 않음(가짜로 바꿔 호출 시 실패), 출력에 시나리오 10개의 제목과 `요청:`·`기대:`·`코드 판정: 일치`가 있고 `불일치`가 없으며, 되묻기 시나리오(4·5·6·7·9a·9b)의 분기 재요청이 모두 출력에 나옴(②는 `keep_requested`·`selected`·`none`, 9b는 두 개, ③은 한 개·여러 개·`none`). (3) 출력의 안내 문구가 `domain/supervisor.py` 상수(`CLARIFY_REQUESTED_TEXT` 등)에서 만든 문장이다(출력 문자열을 테스트가 따로 하드코딩하지 않고 `clarification_texts`로 만든 기대와 비교). 8번 출력에 `EFFICACY_UNAVAILABLE_TEXT["failed"]`가 있고 리서치·기획 호출 횟수가 0이다. (4) dry-run이 보낸 요청 본문(가짜 앱이 받은 JSON)을 검사: 첫 호출에는 `claim_choice`가 없고 재요청에만 `{"mode", "claims", "requested_claim"}`이 있으며 `cancel`은 서버로 보내지 않는다. (5) live 경로를 가짜 주입(`assemble`·`run`·`settings`·`check`·원장 합계 함수)으로 검증: 1~7번이 주입한 `run`으로 불리고 8·9번은 주입한 조립을 쓰지 않으며(가짜 구성), 시작 전 환경 점검 실패 시 `PREFLIGHT_FAILED`와 종료 코드 2로 시작하지 않음, 원장 증가분이 상한 $0.40에 닿으면 남은 시나리오가 `pending`이고 `STOPPED BUDGET_REACHED`·종료 코드 2, `STOPPED`류 코드(`DAILY_LIMIT` 등)에서 재시도 없이 멈춤, 한 시나리오 실패가 다음 시나리오를 막지 않음. (6) 요약 JSON에 요청 본문·모델 문장(기획안 제목·훅·카피)·키 모양 문자열이 없다(합성 비밀 문자열을 가짜 응답에 넣고 요약에서 부재를 확인). (7) 인자 오류(알 수 없는 인자·`--only` ID·`--config`)가 `ARGUMENT_ERROR`·종료 코드 2이고 인자 값이 출력에 없다. (8) Makefile에 `demo-clarify` 타깃이 기대한 한 줄 레시피로 있고 `verify` 레시피에는 `demo-`가 없다.
- `tests/test_api_chat_client.py`: (9) `run_ask_once`에 `claim_choice`를 주면 요청 본문에 있고, 안 주면 본문이 지금과 같다(가짜 앱이 받은 JSON 직접 검사).
- 합성 문장·분류 값을 기대값으로 굳히지 않는다.

## Acceptance Criteria

```bash
make verify   # lint + test 통과
uv run python -m beautyads.eval.clarify_demo --dry-run   # 모델·네트워크 없이 시나리오 10개를 읽을 수 있는 한국어로 출력하고 종료 코드 0
```

## 검증 절차

1. 위 AC 커맨드를 실행한다. 두 번째 명령(`--dry-run`)은 이 step 안에서 실행해도 된다(모델·네트워크·DB·`.env` 없음). 출력이 한국어로 읽히는지(시나리오 제목, 요청, 기대, 시스템 응답, 선택지 번호, 코드 판정) 직접 확인하고 최종 응답의 `summary`에 출력 앞부분 한두 줄의 형태를 적는다(B-FP-075). **live 실행(모델 호출)은 하지 않는다.**
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

- `make demo-clarify`·`make live-agents`·`make live-evidence`를 실행하지 마라. 이 도구를 `--dry-run` 없이 실행하지 마라. 유료 모델·Neo4j·PostgreSQL에 접속하는 테스트를 만들지 마라. 이유: 실제 호출은 사용자가 실행한다(AGENTS.md CRITICAL, A-FP-040). `--dry-run`과 가짜 주입 테스트만 허용한다. 테스트는 키·네트워크 없이 통과해야 한다.
- 도구가 `claims_fn`·정책·뷰 로직을 따로 구현하지 마라(가짜 구성은 `run_request`·`create_app`·`build_view`의 실제 코드를 지나가게 하고 입력만 가짜로 바꾼다). 이유: 가짜 구현이 실제 코드와 다른 가정을 공유하면 인수 점검이 아무것도 증명하지 못한다(B-FP-020).
- 모델이 만든 문장(기획안 제목·훅·카피)을 요약 JSON·테스트 기대값에 넣지 마라. `코드 판정`은 닫힌 값·호출 기록·구조만 쓴다. 이유: 모델 출력의 값을 기대값으로 굳히지 않는다(FP-C03). 기획안 요약은 터미널 출력에만 둔다.
- 세션 상한($0.40)을 설정 상수로 깎거나 `min(...)`으로 우회하지 말고, 호출 직전에 원장 증가분으로 검사하라. 일일 한도·크레딧 오류는 재시도하지 마라. 공급사 상한 딕셔너리 리터럴(`gemini`·`openai`·`anthropic` 세 키)을 새로 만들지 마라(`tests/test_caps_guard.py`가 막는다; 이 도구의 세션 상한은 단일 숫자 상수 하나). 이유: 상한·재시도 규칙은 AGENTS.md CRITICAL이며 시스템 장애를 시나리오 실패로 기록하지 않는다(FP-C07, FP-C16).
- `eval/agents_live.py`·`eval/e2e5_live.py`·`.claude/`·`scripts/`를 수정하지 마라(참고·재사용만, 필요하면 `blocked`). 기존 테스트의 단언을 약화하지 마라. 이유: 이 step은 새 도구를 더하는 것이며 기존 실행기는 되묻기를 처리하지 않는다는 한계를 문서에만 기록한다.
