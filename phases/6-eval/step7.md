# Step 7: e2e5-live

## 설계 검토 기록

**식별자 전수 대조(bb0e64f)**: `api/assembly.py:115 assemble_full(...)`(`group="dev"` 기본, `:138` 허용 집합, `limits=_DEFAULT_LIMITS`, 비동기 컨텍스트)·`:276 ask`(step 6에서 `context_mode` 추가)·`:237 hydrate(ids)`·`:196-232 call_options·chat`·`:306-312 structured(model)`, `api/app.py:39-40`(`Assembly` 필드 `ask`·`hydrate`·`tenants`·`workspaces`·`price_bands`·`as_of`·`last_collected_at`), `api/ask.py:45-92`(`resolve_session`·`ToolContext` 구성·`feedback_for_prompt` 호출 — 러너가 **같은 구성**을 따라야 한다), `api/feedback.py:75 feedback_for_prompt(tenants, tenant_id, as_of)`, `eval/agents_live.py:409`(`assemble_full` 사용·`:420` dev 작업 공간 집합·`WORKSPACE_GROUP_INVALID`), `eval/cq_verify.py:365 cq_preflight`, `obs/ledger.py`(`read_entries`·`ledger_total`·`check_purpose_cap`), `eval/freeze_guard.py`·`eval/evalset.py`·`eval/e2_scoring.py`·`eval/single_agent.py`(step 2·4·5), `domain/supervisor.py:49 RequestLimits`·`cost_exceeded`.

**상수 단언 grep**: 이 step의 새 상수(`DEFAULT_BUDGET_USD`, 결과 디렉터리)를 단언하는 기존 테스트 없음. `RequestLimits` 기본값은 `RequestLimits()`로만 쓰고 숫자를 다시 적지 않는다(`tests/test_supervisor.py:35·63·78·279`가 `RequestLimits()`를 직접 만든다 — 칸 추가·기본값 변경 금지).

**새 칸 대응표**: `ArmRecord` 필드(이 step 러너가 씀 → step 5 `analyze`가 읽음), `code_commit`·`evalset_hash`(`freeze_guard.run_identity` → 기록 → `analyze`의 같은 실행 확인 → 결과 문서), `axes_used_observed`(러너가 `pattern_context.distribution`의 축과 도구 로그에서 코드로 추출 → 결과 문서 참고 표, 층화 기준 아님), `input_tokens`·`model_calls`(원장 증가분 → `ArmRecord`), 결과 파일 경로 `data/interim/e2e5/<run_id>/`(러너 → step 5 시트·채점).

**조언 세션 결정**: 실험 러너는 `/ask` HTTP가 아니라 `Assembly.ask`를 직접 부른다(그래서 `api/ask.py:45-92`와 같은 세션·`ToolContext`·피드백 구성을 따라야 하고 일치 테스트가 필요하다). 이미지는 끈다(`with_image=False`). E5 (a)는 E2 Supervisor 실행을 재사용하므로 러너의 팔은 `supervisor`(켬)·`single`·`off`(끔) 세 개다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 실제 API 호출은 사용자가 실행, 유료 호출 직전 공급사별 누적액 검사, `tenant_id`는 세션에서만, 상한은 `Settings` 한 곳, `make verify`는 키·네트워크 없이 통과
- `/docs/EVAL.md`(E2·E5), `/docs/ARCHITECTURE.md`(요청 흐름), `/.claude/skills/failure-patterns/SKILL.md`(FP-C13·C16, B-FP-040·051·069)
- `/src/beautyads/api/assembly.py`(전체), `/src/beautyads/api/ask.py`·`/src/beautyads/api/feedback.py`·`/src/beautyads/api/app.py`·`/src/beautyads/api/session.py`(읽기 전용), `/src/beautyads/eval/agents_live.py`(읽기 전용: 러너 구조·`--dry-run`·요약 선례), `/src/beautyads/eval/p5_compare.py`(읽기 전용: 목적별 상한·점검 메시지 선례), `/src/beautyads/eval/cq_verify.py`(`cq_preflight`)
- `/src/beautyads/eval/evalset.py`, `/src/beautyads/eval/freeze_guard.py`, `/src/beautyads/eval/e2_scoring.py`, `/src/beautyads/eval/single_agent.py`(step 2·4·5 산출물), `/src/beautyads/obs/ledger.py`, `/src/beautyads/settings.py`(`Settings`·`provider_caps_usd`·`ledger_path`)
- `/tests/test_agents_live.py`, `/tests/test_api_assembly.py`, `/tests/test_caps_guard.py`(읽기 전용: 가짜 조립·상한 리터럴 스캔 선례), `/Makefile`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/e2e5_live.py`(새 파일), `tests/test_e2e5_live.py`(새 파일), `Makefile`(`live-e2e5` 타깃 한 개 추가에 한함)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/e2e5_live.py`, `tests/test_e2e5_live.py`, `Makefile`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로, 평가 정답을 읽는 채점 함수)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

E2(단일 대 Supervisor)와 E5(켬 대 끔)를 **같은 요청 세트로 돌리는 실행기**를 만든다. 이 step의 코드는 실제 서비스에 접속하지만 **이 step 안에서는 접속·실행하지 않는다**(테스트는 가짜 조립·가짜 `ask`·가짜 단일 팔만 쓴다). **테스트를 먼저 쓴다.**

새 식별자: `ARMS_DEFAULT`, `DEFAULT_BUDGET_USD`, `DEV_SCORE_MAX_ITEMS`, `RESULT_ROOT`, `tool_context`, `build_single_arm`, `run_arm`, `ledger_delta`, `observed_axes`, `main`

**CLI**: `uv run python -m beautyads.eval.e2e5_live <run|score|sheet|report> [--mode dev|final] [--arms supervisor,single,off] [--limit N] [--budget-usd X] [--dry-run] [--run-id ID]`. `Makefile`에 `live-e2e5`(`uv run python -m beautyads.eval.e2e5_live $(ARGS)`) 한 개를 추가한다.
- `--mode dev`(기본): `group="dev"` 작업 공간과 dev 요청만. `check_run(mode="dev", groups=…)`가 test 작업 공간·test split을 `WORKSPACE_GROUP_INVALID`로 거부한다. 채점 모델은 mode와 무관하게 `claude-sonnet-5-5`다(step 5의 `score_plans`가 다른 모델을 `SCORING_MODEL_INVALID`로 거부한다; 이 step은 `e2_scoring.py`를 고치지 않는다). dev 스모크는 요청 3건 × 팔 2개 = 채점 항목 **최대 6건**(`DEV_SCORE_MAX_ITEMS`), `--budget-usd`는 dev에서 **0.40 초과를 거부**한다.
- `--mode final`: test 작업 공간과 test split(요청 20건)만. **모델 호출·접속 전에** `check_run(mode="final", groups={"test"}, extra=…)`를 통과해야 하고(`extra`에 단일 에이전트 프롬프트 sha256·채점 루브릭 sha256과 같은 이 실행기가 가진 추가 동결 값), 실패하면 고정 코드(`PREREG_NOT_COMMITTED`·`EVALSET_HASH_MISMATCH`·`FROZEN_VALUE_MISMATCH`)를 출력하고 가짜 `chat` 호출 0건으로 끝난다. 통과하면 `RunIdentity`(코드 커밋·사전 등록 커밋·세트 해시)를 기록에 싣는다.
- 요청 파일은 final에서 `data/evalset/requests.jsonl` 고정이다. dev에서는 `--requests PATH`로 후보 파일을 줄 수 있다(final은 이 옵션을 거부).
- `--dry-run`: 접속·모델 호출 없이 요청 수×팔 수, 채점 항목 수와 호출 수, "호출 수 기준 비용 추정(가정, 미실측)"만 출력한다. 스모크 실행은 이 출력을 사용자에게 보고하고 승인받은 뒤에만 한다.
- 시작 점검(`cq_preflight` 방식과 키·원장 경로 확인)이 실패하면 이유 코드를 출력하고 시작하지 않는다(B-FP-051).

**조립과 호출**
- `assemble_full(group=…, limits=RequestLimits())`로 `Assembly`를 얻어 `assembly.ask(message, ctx, profile, feedback, False[, context_mode="off"])`를 **직접** 부른다. 팔 `supervisor`는 `context_mode`를 넘기지 않고(켬 = P5 동작), `off` 팔만 `context_mode="off"`를 넘긴다. `ctx`는 `tool_context(assembly, tenant_id)`가 `api/ask.py:45-92`와 같은 식(`tenant_id`·`as_of`·`last_collected_at`·`price_band`)으로 만들고, 피드백은 `feedback_for_prompt(assembly.tenants, tenant_id, assembly.as_of)`다. 일치 테스트: 같은 합성 `Assembly`에서 `tool_context`가 만든 `ToolContext`가 `api/ask.py`의 구성식으로 만든 기대값과 같다.
- 팔 `single`: `build_single_arm(...)`이 `assemble_full`과 **같은 래퍼·같은 상한 출처**(`Settings.provider_caps_usd`·`settings.ledger_path`)로 `chat`·`structured("gpt-6.1-terra")`·`runner`·코드 검사 구성요소(`load_claim_rules`·`GraphEvidenceIndex`·`GraphEfficacySupport`·`GraphCertLookup`)를 만들어 `run_single_agent`를 부른다(`assembly.py`의 해당 조립을 읽고 같은 방식으로 쓰되 상한 딕셔너리·`min(…)` 리터럴을 만들지 않는다, FP-C16). 래퍼 상한 검사는 모든 유료 호출 직전에 유지된다.
- 요청마다 순서는 `supervisor` → `single` → `off`(선택한 팔만), 요청 사이는 순차다. 한 요청의 실패는 `ArmRecord(status="failed")`로 기록하고 다음으로 넘어간다. 공급사 일일 한도·`CostCapExceeded`·`BUDGET_REACHED`는 배치를 멈추고 남은 항목을 미실행으로 둔다(재시도는 503·연결 실패·시간 초과만, 429 일일 한도는 재시도 안 함, AGENTS.md).
- 요청당 텍스트 비용 상한은 `RequestLimits()` 기본(`max_text_cost_usd`)이다. 전체 예산 `--budget-usd`(기본 `DEFAULT_BUDGET_USD`: dev 0.40·final 3.0, 모드별 상수; dev는 0.40 초과 값을 거부)를 **요청 시작 직전**에 `ledger_total` 증가분으로 검사해 넘으면 멈춘다.
- **기록(`ledger_delta`)**: 요청 시작 전 원장 항목 수를 기억하고 끝난 뒤 새 항목(`read_entries`)에서 `input_tokens` 합·항목 수(= `model_calls`)·텍스트 비용(`image` 목적 제외)을 모은다(요청이 순차이므로 증가분이 그 요청의 것이다). 지연은 `time.monotonic`. `ArmRecord`(step 5)로 `data/interim/e2e5/<run_id>/records.jsonl`(`RESULT_ROOT`)에 한 줄씩 덧붙이고, 이미 있는 (`item_id`, `arm`)은 다시 하지 않는다(재개). 기록에 `code_commit`·`evalset_hash`·`prompt_versions`(Supervisor 결과의 `prompt_versions`와 단일 팔 `prompt_version`)를 싣는다. 키·API 응답 본문·예외 문장은 기록하지 않는다.
- `axes_used_observed`: Supervisor 팔 결과의 `handoff["pattern_context"]["distribution"]`에서 `axis` 값을 모으고 도구 로그의 축 입력이 있으면 더해 코드로 만든다(참고 표시용, 모델 아님).

**하위 명령**
- `score`: 기록을 읽어 `e2_scoring.blind_items`→`score_plans`(주입 `structured`, 상한 직전 검사)로 채점하고 `reveal_scores` 결과를 `scores.json`에 쓴다. 채점은 한 번의 실행에서 모든 팔을 함께 한다(E5 재사용 조건: 같은 채점 실행). 채점 모델은 mode와 무관하게 sonnet이며(`score_plans`의 고정 모델), dev에서는 채점 항목이 `DEV_SCORE_MAX_ITEMS`(6)를 넘으면 거부한다.
- `sheet`: `build_claim_sheet`로 사람 판정 시트·설명·키를 만든다. 근거 소재 텍스트는 `assembly.hydrate(ids)` 카드의 제목·브랜드만 쓰고 링크는 넣지 않는다.
- `report`: `load_claim_matches`(있으면)와 `analyze` 결과를 표로 출력한다(건수·조건·"1인 라벨링" 병기, 기준 미달도 그대로, `verdict_*` 값과 `RunIdentity` 두 커밋 해시, E2 구성 한계 문장 "한 에이전트 대 한 시스템").

**테스트(`tests/test_e2e5_live.py`, 가짜 `assemble_full`·가짜 `ask`·가짜 단일 팔·`tmp_path`)**
- 가드 소비(모든 final 경로): 사전 등록 미커밋·해시 불일치·동결 값 불일치에서 가짜 `ask`·`chat`·`structured` 호출 0건이고 고정 코드를 출력한다. dev 모드에서 test 작업 공간·test split은 호출 0건으로 거부된다. final이 `--requests` 옵션을 거부한다.
- 팔: `off`만 `ask`에 `context_mode="off"`를 넘기고 `supervisor`는 키워드를 넘기지 않는다. 요청마다 가짜 `ask`가 받은 `with_image`가 `False`다. `single` 팔이 `assemble_full`과 같은 상한 출처를 쓴다(AST로 상한 리터럴·`min(` 호출 없음, `tests/test_caps_guard.py` 통과).
- **같은 상한 출처(조언 세션 조건 1, 값 비교 테스트)**: 단일 팔이 쓴 도구 호출 한도가 `ResearchBrief.model_fields["max_tool_calls"].default`와 같고 Supervisor 팔의 리서치가 받은 brief의 `max_tool_calls`와도 같으며, 단일 팔의 텍스트 비용 상한(`limits.max_text_cost_usd`)이 `assemble_full`에 넘긴 `RequestLimits`의 값과 같음을 **같은 출처에서 읽은 값끼리 비교**해 단언한다(리터럴 6·0.30을 테스트에 적지 않는다). 한쪽만 바꾸면 이 테스트가 실패해야 한다.
- 기록·재개: 같은 `run_id`를 다시 돌리면 이미 있는 (`item_id`,`arm`)을 건너뛴다. 한 요청 실패가 다음 요청을 막지 않는다. `CostCapExceeded`·예산 도달은 배치를 멈춘다. `ledger_delta`가 합성 원장 항목에서 `input_tokens`·항목 수·텍스트 비용(이미지 제외)을 정확히 센다.
- 채점 모델: `score`가 dev·final 모두 `claude-sonnet-5-5` 모델의 주입 `structured`만 쓰고(haiku 모델이면 `SCORING_MODEL_INVALID`), dev에서 항목 7건 이상 또는 `--budget-usd` 0.40 초과는 호출 0건으로 거부된다. `--dry-run`이 채점 호출 수를 출력한다.
- `--dry-run`·점검 실패에서 모델 호출 0건. 기록·출력에 합성 키·본문 문자열(`SENTINEL_…`)이 없다.
- 합성 문장·분류 값을 기대값으로 굳히지 않는다(형식과 호출 횟수만).

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

- `api/ask.py`·`api/assembly.py`·`agents/*`를 고치거나 `/ask` HTTP 경로로 `context_mode`를 넘기지 마라. 이유: 허용 목록 밖이다. 러너는 `Assembly.ask`를 직접 부르고 `/ask` 동작은 P5와 같아야 한다(조언 세션 결정 7).
- test 작업 공간·test split을 `check_run(mode="final")` 통과 전에 건드리거나 dev 모드에서 허용하지 마라. 이유: 사전 등록 커밋과 세트 해시가 일치할 때만 test를 쓴다(코드로 강제, AGENTS.md·docs/EVAL.md 원칙).
- 상한·원장 경로·키 리터럴을 만들거나 `min(caps)`로 깎지 마라. 이유: 상한 출처는 `Settings` 한 곳이다(FP-C16). 단일 팔 조립도 `assemble_full`과 같은 출처를 쓴다.
- 이미지를 켜거나(`with_image=True`) 요청·정답·점수를 보고 요청 세트·프롬프트·상수를 바꾸는 코드를 만들지 마라. 이유: 이미지는 실험에서 끈다(조언 세션 결정). 세트·프롬프트는 동결 뒤 불변이다(docs/EVAL.md).
- `make live-e2e5`로 실제 호출을 하거나 `data/interim/e2e5/`에 실제 결과를 쓰는 테스트를 만들지 마라. 이유: 실제 호출은 사용자가 비용 보고 뒤 승인하고 실행한다(AGENTS.md). 테스트는 가짜와 `tmp_path`만 쓴다.
