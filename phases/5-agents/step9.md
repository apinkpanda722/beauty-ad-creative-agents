# Step 9: agents-live-target

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL 규칙(실제 API 호출은 사용자가 실행, 공급사별 누적액·상한 Gemini $12·OpenAI $10·Anthropic $8, 개발 반복 기본 모델 `gpt-6-luna`·`claude-haiku-5-5`, `reasoning_effort` 명시, 테넌트는 세션에서만, 비밀 값 금지)
- `/docs/ARCHITECTURE.md` — "요청 처리 공통 장치", "멀티테넌트"
- `/docs/results/p5_dev_compare_preregistration.md` — §8(실측 비용·평가 점수 분포)
- `/src/beautyads/eval/live_agent.py`(`preflight`·`container_running`·`migrations_ready`·`_positive_usd`·CLI 오류 출력 방식), `/src/beautyads/api/assembly.py`, `/src/beautyads/api/chat_client.py`(`run_ask_once`·`AskOutcome`), `/src/beautyads/api/app.py`(`create_app`), `/src/beautyads/domain/supervisor.py`(`RequestLimits`), `/src/beautyads/obs/trace.py`, `/src/beautyads/obs/ledger.py`, `/src/beautyads/sources/workspaces.py`, `/config/workspaces.yaml`, `/Makefile`, `/tests/test_live_agent.py`, `/tests/test_api_assembly.py`, `/tests/test_trace.py`, `/tests/test_architecture.py` — step 1·7a~7d·8a 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/agents_live.py`(새 파일), `Makefile`, `tests/test_agents_live.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/agents_live.py`, `Makefile`(`live-agents` 타깃과 그 `.PHONY` 줄 추가에 한함. `verify` 타깃과 기존 타깃·기존 `.PHONY` 줄 불변. 기존 줄 첫 줄에 이름을 덧붙이지 않고 `live-agent`처럼 별도 `.PHONY: live-agents` 줄을 둔다), `tests/test_agents_live.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

P5의 끝에서 **사용자가 실행하는** live 도구 `make live-agents`를 만든다. dev 작업 공간 2개에 요청 5종을 보내 Supervisor·리서치·기획·평가 전체 경로를 돌리고, 결과 요약(구조화 실패 종류별 횟수, 되돌림 점수 경로, `unknown_count`, 한도, 비용)을 낸다. **이 step은 도구 코드와 가짜 의존성 테스트만 만들고 모델·서비스를 부르거나 `make live-agents`를 실행하지 않는다.** **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

**`eval/agents_live.py`**(`eval` 계층, `api`·`obs`·`sources`·`agents` import 가능. `httpx`·`fastapi`를 직접 import하지 않는다: 호출은 `api.chat_client.run_ask_once`): `main(argv=None, *, out=None, check=None, run=None, settings=None, assemble=None, clock=None) -> int`.
- **인자**: `--config {dev,official,image}`(필수), `--dry-run`(호출·비용 없이 계획만 출력), `--reset-baseline`(예산 기준점을 새로 만든다), `--only <시나리오 id>`(선택, 반복 가능), 그 밖의 인자 없음. **작업 공간은 dev 그룹 고정**이다(`assemble_full`의 `group="dev"`), test 그룹 테넌트를 쓰는 인자·경로가 없다(test 브랜드는 최종 평가 전까지 쓰지 않는다).
- **구성**: `dev` = 평가 모델 `claude-haiku-5-5`·이미지 끔·시나리오 전부. `official` = 평가 모델 `claude-sonnet-5-5`·이미지 끔·기획 시나리오(`plan` 종류)만. `image` = 평가 모델 `claude-sonnet-5-5`·이미지 켬(`with_image_enabled=True`, 요청 `with_image=True`)·첫 기획 시나리오 하나만. 모델 값은 `assemble_full`에 **명시**해 넘긴다(기본값에 기대지 않는다).
- **시나리오**(모듈 상수 목록, 각 `id`·`tenant_id`(dev 그룹 값)·`kind`(`pattern`·`relation`·`plan`·`boundary`)·`message`(사람이 쓴 짧은 한국어 요청): 패턴 질의 1(dev-mixsoon·세럼), 관계 질의 1(dev-mixsoon), 기획 요청 2(dev-mixsoon 세럼·dev-cosrx 선케어, 안 1개를 요청하는 문장), 범위 밖 1(dev-mixsoon, 지원하지 않는 카테고리를 묻는 문장). 시나리오 id는 중복 없고 모든 `tenant_id`가 `config/workspaces.yaml`의 dev 그룹이며 `message`는 1~2,000자다.
- **예산(승인된 값)**: 세션 전체 상한 $1.0 = OpenAI $0.5 + Anthropic $0.4 + 이미지 $0.1. 상수 `RUN_CAPS = {"openai": 0.5, "anthropic": 0.4, "image": 0.1}`. 기준점 파일 `data/interim/agents_live/baseline.json`(`created_at`·`provider_totals`(openai·anthropic)·`image_total`)을 **처음 실행할 때 만들고 이후 실행은 재사용**한다(`--reset-baseline`일 때만 새로 만든다). 사용 누적액 = 원장(`settings.ledger_path`)의 현재 합계 − 기준점(`obs.ledger.provider_total`·`purpose_total("image")`; **다른 비용이 섞이면 더 일찍 멈추는 보수적 방향이다**). **각 요청 직전**에 어느 공급사든 누적액이 상한 이상이면 남은 시나리오를 `pending`으로 두고 `STOPPED BUDGET_REACHED`를 출력해 멈춘다. 요청마다 `RequestLimits(max_text_cost_usd=min(0.30, 남은 OpenAI+Anthropic 상한))`를 `assemble_full(limits=…)`로 넘긴다. 기존 공급사별 누적 상한 검사는 래퍼가 그대로 한다.
- **실행**: 시나리오마다 `create_app(partial(assemble_full, …))`+`run_ask_once(app, tenant_id=…, message=…, with_image=…)`(각 요청이 새 조립을 시작하고 닫는다). `preflight`(Docker·마이그레이션, `live_agent`의 것을 재사용)가 실패하면 `PREFLIGHT_FAILED <코드>`를 출력하고 종료 코드 2. 설정 오류는 `PREFLIGHT_FAILED <코드>:<이름>`(값 미노출). 한 요청의 실패(HTTP 오류·`error` 이벤트·예외)는 기록하고 **다음 시나리오로 넘어간다**(일일 한도 429 계열 오류 코드는 재시도하지 않고 배치를 멈춘다).
- **요약(JSON, 표준 출력 한 줄 + `data/interim/agents_live/<run_id>.json` 파일)**: `run_id`, `config`, 시나리오별 `{id, tenant_id, kind, status_code, event_names, error_code, trace_id, plans: [{status, rework_count, unknown_count, efficacy_status, attempts: [{attempt, passed, scores(정수 값만), failed_check_codes}]}], limit_hit, limit_kinds, cost_by_provider, duration_ms}`(8a trace에서 읽는다: 실행 시작 시각 이후 `read_traces`, 테넌트·시작 순서로 대응), 전체 `structured`(모델별 `calls`·`failed_after_retry`·`first_attempt_failures` 종류별 합과 **총 호출 수가 20 미만이면 `"sample_too_small": true`**), `budget`({`used`, `caps`, `remaining`}), `pending`(남은 시나리오 id). **모델이 만든 문장·메시지 원문·키·DSN은 요약에 넣지 않는다**(시나리오는 id로만).
- 종료 코드: 모두 완료 0, 일부 요청 실패 3, 예산 도달·preflight 실패·인자 오류 2.

**`Makefile`**: `live-agents:` 타깃(`uv run python -m beautyads.eval.agents_live $(ARGS)`)과 별도 `.PHONY: live-agents` 줄을 `live-agent` 타깃 근처에 추가한다. `verify` 타깃에는 넣지 않는다.

**반드시 있어야 하는 테스트**(가짜 `check`·`run`·`assemble`·합성 원장·`tmp_path`, 실제 서비스 접속·키 없음):
- 시나리오: id 중복 없음, 모든 `tenant_id`가 실제 `config/workspaces.yaml`의 **dev 그룹**(개수·값을 `== N`으로 단언하지 않고 그룹 불변식만), `kind`가 허용 값 집합 안, 메시지 길이 1~2,000, `plan` 종류가 하나 이상, `boundary` 종류가 하나 이상. 구성별 시나리오 선택: `dev`는 전부, `official`은 `plan`만, `image`는 `plan` 하나(값이 아니라 종류·부분집합 관계로 단언). 알 수 없는 `--config`·알 수 없는 `--only`는 인자 오류 2.
- **FP-C14(전달 확인)**: 가짜 `assemble`이 받은 인자를 직접 검사한다: `group`이 `"dev"`, 평가 모델이 구성에 맞는 값(`dev`→haiku, `official`·`image`→sonnet), `with_image_enabled`가 `image` 구성에서만 참, `limits.max_text_cost_usd`가 `min(0.30, 남은 예산)`. 가짜 `run`이 받은 `with_image`가 `image` 구성에서만 참이고 `tenant_id`가 시나리오 값이다.
- 예산: 기준점 파일이 처음엔 만들어지고 두 번째 실행은 **그대로 재사용**된다(합성 원장), `--reset-baseline`만 다시 만든다. 사용 누적액이 상한 이상이면 요청 전에 멈추고 `STOPPED BUDGET_REACHED`·남은 시나리오가 `pending`·`run`이 더 불리지 않는다. 한 공급사만 넘어도 멈춘다. 남은 상한이 0.30보다 작으면 `max_text_cost_usd`가 그 값이다. 이미지 누적액 상한도 적용된다.
- 실패 처리: 한 요청의 `error` 이벤트·예외가 기록되고 다음 시나리오가 실행된다(종료 코드 3). 한도(429 계열) 오류 코드면 배치가 멈추고 남은 것이 `pending`이다. `preflight` 실패는 종료 코드 2이고 `run`이 불리지 않는다.
- `--dry-run`: `run`·`assemble`·원장 읽기가 불리지 않고(호출 0) 계획(구성·시나리오·예산 상한)만 출력된다.
- 요약: 합성 trace 파일(8a 형식)에서 시나리오별 `plans`·`attempts`의 점수 경로·`unknown_count`·`limit_kinds`가 구조화 칸 그대로 나온다, 구조화 실패 종류 합과 `sample_too_small`(호출 수 19 → 참, 20 → 거짓: 경계), 파일이 `data/interim/agents_live/<run_id>.json`에 쓰인다(`tmp_path`로 교체). **합성 비밀 문자열을 메시지·trace·오류 메시지에 넣어도 표준 출력과 요약 파일에 없다**. 요약에 메시지 원문이 없다.
- `Makefile`: `live-agents` 타깃 줄과 별도 `.PHONY` 줄이 있고 `verify` 본문에 `live-`가 없다(기존 `tests/test_cq_verify.py`·`tests/test_evidence_check.py` 단언이 그대로 통과한다).
- `tests/test_architecture.py` 통과(`eval`이 `httpx`·`fastapi`를 직접 import하지 않는다).

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

- `make live-agents`나 `uv run python -m beautyads.eval.agents_live`를 실행하거나 모델·서비스에 접속하지 마라. 이유: 실제 호출과 비용은 사용자가 실행한다(AGENTS.md CRITICAL). 모든 의존성은 주입해 테스트한다.
- test 그룹 작업 공간(`test-isntree`·`test-bojoseon`)을 시나리오·인자·기본값에 넣지 마라. 이유: test 브랜드는 최종 평가 전까지 쓰지 않는다(P5 결정). 도구는 dev 그룹 고정이다.
- 예산 상한·기준점 로직을 건너뛰거나 상한을 상수 밖에서 바꾸는 인자를 만들지 마라. 이유: 세션 상한 $1.0(OpenAI $0.5·Anthropic $0.4·이미지 $0.1)은 승인된 값이고 기준점은 재사용된다.
- 요약에 메시지 원문·모델 문장·키·DSN을 넣거나 정확도를 단언하는 테스트를 쓰지 마라. 이유: 모델이 만든 값을 기대값으로 굳히지 않고 비밀 값은 어디에도 남기지 않는다(AGENTS.md CRITICAL). 형식·코드가 하는 일만 검사한다.
- `Makefile`의 `verify`·기존 타깃·기존 `.PHONY` 줄을 바꾸거나 `data/manifest/costs.jsonl`·`data/interim/`의 파일 내용을 읽거나 수정하지 마라. 이유: verify는 키·네트워크 없이 통과해야 하고 원장은 사용자의 실행 기록이다. 도구가 런타임에 `data/interim/agents_live/`에 쓰는 것은 대상이 아니다.
- `httpx`·`fastapi`를 직접 import하거나 `api` 계층 코드를 바꾸지 마라. 이유: 호출은 `run_ask_once`가 한다(AGENTS.md 계층 경계). 같은 값(시나리오·구성·상한 목록)을 본문과 테스트에 적을 때 표현을 맞춘다(7d 교훈).
