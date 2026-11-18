# Step 9b: cap-config-follow

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL 규칙(공급사별 누적액 호출 직전 검사, 상한 Gemini $12·OpenAI $10·Anthropic $8은 **설정 기본값**이고 승인된 환경변수 `BEAUTYADS_CAP_<공급사>_USD`로 올릴 수 있다, 키·비밀 금지, 실제 서비스 접속 금지)
- `/docs/PHASES.md` — 변경 기록 #40(`BEAUTYADS_CAP_GEMINI_USD`는 20.5로 승인)·#52(step 9 예산)
- `/docs/ARCHITECTURE.md` — "요청 처리 공통 장치"의 비용 상한 항목
- `/src/beautyads/settings.py`(`Settings`·`load_settings`의 상한 읽기), `/src/beautyads/api/assembly.py`(`_HARD_CAPS`·`caps`·`purpose_caps`·`image_fn`), `/src/beautyads/eval/live_agent.py`(`HARD_CAPS`), `/src/beautyads/eval/p5_compare.py`(`HARD_CAPS`), `/src/beautyads/obs/ledger.py`(`CostCapExceeded`·`check_cap`·`check_purpose_cap`), `/src/beautyads/llm/image.py`, `/src/beautyads/agents/supervisor.py`(`_limit`·결과 `limit_kinds`), `/src/beautyads/obs/trace.py`, `/src/beautyads/eval/agents_live.py`, `/tests/test_api_assembly.py`, `/tests/test_supervisor.py`, `/tests/test_trace.py`, `/tests/test_agents_live.py`, `/tests/test_p5_compare.py`, `/tests/test_settings.py`, `/tests/test_architecture.py` — step 7a·7d·8a·9 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/api/assembly.py`, `src/beautyads/eval/live_agent.py`, `src/beautyads/eval/p5_compare.py`, `src/beautyads/agents/supervisor.py`, `src/beautyads/obs/trace.py`, `src/beautyads/eval/agents_live.py`, `tests/test_caps_guard.py`(새 파일), `tests/test_api_assembly.py`, `tests/test_supervisor.py`, `tests/test_trace.py`, `tests/test_agents_live.py`, `tests/test_p5_compare.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/api/assembly.py`(`_HARD_CAPS` 제거·`caps`·`purpose_caps`를 설정값 그대로 사용·`image_fn` 반환에 `cap` 추가에 한함, 다른 동작·모델 호출 모양 불변), `src/beautyads/eval/live_agent.py`·`src/beautyads/eval/p5_compare.py`(`HARD_CAPS`로 설정을 깎는 `min` 제거에 한함: 상한은 `settings.provider_caps_usd`를 복사해 쓴다), `src/beautyads/agents/supervisor.py`(`limit_detail` 추가에 한함, `limit_kinds`·기존 결과 키·흐름 불변), `src/beautyads/obs/trace.py`(`limit_detail` 필드 추가에 한함), `src/beautyads/eval/agents_live.py`(요약에 `limit_detail`을 싣는 데 한함), `tests/test_caps_guard.py`, `tests/test_api_assembly.py`(케이스 추가에 한함. 단 487행의 `image` 결과 정확 일치 단언 한 줄은 `cap` 칸을 포함하도록 갱신 허용: 값은 `"provider:gemini"`), `tests/test_supervisor.py`·`tests/test_trace.py`·`tests/test_agents_live.py`(케이스 추가에 한함, 기존 단언 변경 0줄), `tests/test_p5_compare.py`(700행 `kw["caps"] == compare.HARD_CAPS`를 `kw["caps"] == Settings().provider_caps_usd`로 바꾸는 한 줄에 한함. `HARD_CAPS` 제거로 생기는 변경이다)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

live 결과에서 드러난 **상한 우회 결함**을 고친다. `api/assembly.py`의 `min(_HARD_CAPS, 설정값)`은 설정 상한을 낮추기만 하고 올릴 수 없어, 승인된 `BEAUTYADS_CAP_GEMINI_USD=20.5`를 붙여도 장부 Gemini $16.66이 하드코딩 $12에 막혀 이미지가 생성되지 않았다(`limit_kinds ["image"]`, 이미지 사용액 0.0). 이 step은 모델·실제 서비스를 부르지 않는다. **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

**1. 상한은 설정값 한 곳에서만 온다**: `Settings.provider_caps_usd`(기본 Gemini $12·OpenAI $10·Anthropic $8, 환경변수로 조정)와 `Settings.purpose_caps_usd`(이미지 기본 3.5)가 유일한 출처다.
- `api/assembly.py`: `_HARD_CAPS`와 `min(...)`을 지우고 `caps = dict(settings.provider_caps_usd)`, `purpose_caps = dict(settings.purpose_caps_usd)`(복사본)를 쓴다. 리터럴 `3.5`도 지운다.
- `eval/live_agent.py`·`eval/p5_compare.py`: 같은 패턴(`HARD_CAPS`와 `min`)을 같은 방식으로 고친다(`HARD_CAPS` 상수를 지운다).
- `agents/*.py`(supervisor·research·planning·evaluation)의 `"caps": {"gemini": 12.0, ...}` 리터럴은 호출 옵션이 없을 때의 대체값이고 조립이 항상 설정값으로 덮어쓴다. **이 step은 이 대체값을 지우지 않고** 가드 테스트(아래)가 값이 `Settings` 기본값과 같음만 지킨다(`agents`는 `settings`를 import하지 못하는 계층 규칙 때문).

**2. 상한이 어느 것이었는지 남긴다**: `CostCapExceeded.provider`는 `"gemini"`(공급사) 또는 `"purpose:image"`(목적)다.
- `image_fn`은 `CostCapExceeded`를 만나면 `{"ok": False, "code": "IMAGE_CAP_REACHED", "cap": "provider:<이름>" | "purpose:image"}`를 돌려준다(공급사 이름은 `[a-z_]{1,32}`만 허용, 아니면 `provider:unknown`). 다른 예외·실패 반환(`IMAGE_FAILED`)은 그대로다.
- `agents/supervisor.py`: 결과에 `limit_detail: list[{"kind": str, "cap": str}]`(종류 오름차순)를 더한다. `kind`가 `image`면 `cap`은 이미지 결과의 `cap`(형식 `^(provider|purpose):[a-z_]{1,32}$` 밖이면 `"unknown"`), `text`는 `"request:text"`, `steps`는 `"request:steps"`, `plans`는 `"request:plans"`다. `limit_kinds`·`limit_hit` 동작은 바뀌지 않는다.
- `obs/trace.py`: `TraceRecord.limit_detail: list[TraceLimitDetail(kind, cap)]`(토큰 정규식 통과만)를 더하고 `build_trace`가 `result["limit_detail"]`에서 만든다(없으면 빈 목록). `eval/agents_live.py` 요약의 시나리오 항목에도 `limit_detail`을 싣는다(trace 값 그대로).

**반드시 있어야 하는 테스트**(합성 값, 모델·서비스 접속 없음):
- **설정이 조립을 따라간다(`tests/test_caps_guard.py`, 새 가드)**: 가짜 `connect_fn`·`graph_fn`·`saver_fn`·가짜 `models`(chat·structured·image)로 `assemble_full`을 만들고 **설정 상한을 올린 `Settings`(Gemini 20.5·OpenAI 20·Anthropic 16·이미지 목적 5.0)와 낮춘 `Settings`(Gemini 5·OpenAI 1·Anthropic 1·이미지 1.0)** 각각에서 가짜 chat·structured 생성기·image가 받은 `caps`·`purpose_caps`가 설정값과 같다(복사본이라 호출 쪽 변경이 설정을 바꾸지 않음도 확인). **장부 Gemini 16.66(합성 원장)에서 실제 `obs.ledger.check_cap`에 조립이 넘긴 `caps`를 넣으면 20.5에서는 통과하고 기본 12에서는 `CostCapExceeded`다**(오프라인으로 FP 재현). 이미지 목적도 같은 방식(`check_purpose_cap`).
- **하드코딩 상한 스캔(AST, 같은 파일)**: `src/beautyads` 모든 `.py`에서 (A) `caps`·`CAPS` 이름을 인자로 하는 `min(` 호출이 없다(설정 상한 깎기 금지, 검사한 파일 수 0이면 실패). (B) `"gemini"`·`"openai"`·`"anthropic"` 키를 가진 숫자 리터럴 딕셔너리는 `settings.py`와 `agents/` 아래 모듈만 허용하고(허용 목록은 테스트 안 상수로 명시) 그 값은 `Settings().provider_caps_usd`와 같다. 새 위반이 생기면 실패한다.
- **상한 종류 구분**: 가짜 이미지 호출이 `CostCapExceeded("gemini", 16.66, 12.0)`를 올리면 `image_fn` 반환이 `cap == "provider:gemini"`, `CostCapExceeded("purpose:image", 3.6, 3.5)`면 `"purpose:image"`, 알 수 없는 문자열은 `"provider:unknown"`이다(`IMAGE_CAP_REACHED` 코드와 `ok False`는 유지, `IMAGE_FAILED` 경로 불변). Supervisor 결과의 `limit_detail`이 `[{"kind": "image", "cap": ...}]`이고 텍스트 상한이면 `"request:text"`이며 `limit_kinds`는 기존 값 그대로다(둘 다 닿으면 둘 다 있다). trace의 `limit_detail`과 `agents_live` 요약이 그 값을 그대로 싣는다. `cap` 형식 밖 문자열은 `"unknown"`이 되고 합성 비밀 문자열을 `cap`에 넣어도 trace·요약에 없다.
- 기존 `tests/test_settings.py`·`tests/test_cost_recalc.py`의 설정 기본값 단언과 `tests/test_p5_compare.py`·`tests/test_live_agent.py`의 나머지 단언은 그대로 통과한다.

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

- `min(하드코딩 상한, 설정값)`처럼 설정 상한을 깎거나 새 하드코딩 상한을 `api`·`eval`·`pipeline` 계층에 만들지 마라. 이유: 상한은 `Settings` 한 곳이 출처이고 승인된 환경변수로만 바뀐다. 우회하면 승인된 설정이 조용히 무시된다(P5 step 9 live 결과: Gemini 20.5가 $12에 막힘).
- `agents/*.py`의 대체값 리터럴을 지우거나 `settings`를 import하지 마라. 이유: `agents`는 `settings`를 import하지 못한다(계층 경계). 값이 `Settings` 기본값과 같음은 가드 테스트가 지킨다.
- `image_fn`이 상한 오류를 삼키며 종류 정보를 버리게 두지 마라. 이유: 공급사 상한과 목적 상한은 대응이 다르다. `cap`이 `limit_detail`·trace·요약에 남아야 한다.
- `limit_kinds`·`limit_hit`의 기존 값과 `IMAGE_FAILED` 경로, 모델 호출 모양을 바꾸지 마라. 이유: 7a·7d에서 검증한 계약이다. 상세 정보는 새 칸에 추가만 한다.
- 가드를 구현 상수만 읽어 통과하게 쓰지 마라. 이유: 설정을 바꿨을 때 조립이 따라가는지를 가짜 호출이 받은 인자와 실제 `check_cap`으로 확인해야 FP가 재현된다(FP-C13 방식).
- `data/manifest/costs.jsonl`을 수정하거나 환경변수·키를 코드·테스트에 쓰지 마라. 이유: 장부는 사용자의 실행 기록이고 테스트는 합성 원장 파일(`tmp_path`)만 쓴다(AGENTS.md CRITICAL).
