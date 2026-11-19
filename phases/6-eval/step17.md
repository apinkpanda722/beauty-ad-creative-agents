# Step 17: dev-budget-cap

## 설계 검토 기록

**배경(조언 세션 요청)**: 사용자가 `e2e5_live run --mode dev --budget-usd 0.40`을 실행하자 `DEV_BUDGET_INVALID`로 멈췄다(`eval/e2e5_live.py:632`, `DEFAULT_BUDGET_USD["dev"] = 0.15` 초과 거부). 호출 전이라 비용 0이다. 조언 세션이 승인한 dev 스모크 예산은 0.40이다. 이 step은 dev 예산 상수를 0.40으로 바꾼다. 거부 기준은 "0.40 초과"이고 `DEV_BUDGET_INVALID` 오류 코드는 유지한다. 채점 항목 상한 `DEV_SCORE_MAX_ITEMS = 6`은 그대로다.

**식별자 전수 대조(현재 코드)**: `eval/e2e5_live.py`(`:75 DEFAULT_BUDGET_USD = {"dev": 0.15, "final": 3.0}`, `:628-633`: `--budget-usd` 미지정이면 `DEFAULT_BUDGET_USD[args.mode]`, 유한·양수 검사(`ARGUMENT_ERROR`), `args.mode == "dev" and args.budget_usd > DEFAULT_BUDGET_USD["dev"]`이면 `_Stopped("DEV_BUDGET_INVALID")`; `:464`·`:767-775`의 누적 지출(`previous_spend`)이 같은 `args.budget_usd`와 비교됨 — **`run`과 `score`의 지출이 한 예산에 합산된다**: 이 step은 이 동작을 바꾸지 않는다), `tests/test_e2e5_live.py`(`:294`·`:643`: `entry(cost=live.DEFAULT_BUDGET_USD["dev"])`로 예산 도달을 만든다, `:347-354 test_preflight_failure_and_dev_budget_rejection_are_call_free`: `str(live.DEFAULT_BUDGET_USD["dev"] + 0.01)`을 거부 단언, `:291 test_budget_stops_before_next_arm_and_resume_counts_previous_spend`, `:640 test_score_budget_includes_generation_spend`).

**상수 단언 grep(전수)**: `0.15`·`DEFAULT_BUDGET_USD`·`DEV_BUDGET_INVALID`를 `src/`·`tests/`·`docs/`·`Makefile`·`README.md`에서 찾은 결과 코드와 테스트의 사용처는 위 목록이 전부다. 테스트는 **상수 값을 직접 읽어** 쓰므로(`DEFAULT_BUDGET_USD["dev"]`) 값 변경에 자동으로 맞춰진다(리터럴 0.15를 단언하는 테스트는 없다). step 7 문서(`phases/6-eval/step7.md`의 `:38`·`:48`·`:62`)의 0.15 문구는 이 step 시작 전에 이미 0.40으로 갱신되어 있다(`phases/`는 읽기 전용이다).

**새 칸 대응표**: `DEFAULT_BUDGET_USD["dev"]`(상수 → `--budget-usd` 기본값과 dev 거부 기준 → 테스트의 경계값 단언), `DEV_BUDGET_INVALID`(`main` → 고정 오류 코드 불변).

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건(합성 테스트만).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 비용 상한 검사는 모든 유료 호출 직전에 유지한다, 실제 호출은 사용자가 실행한다
- `/src/beautyads/eval/e2e5_live.py`(`DEFAULT_BUDGET_USD`·`DEV_SCORE_MAX_ITEMS`·`main`의 예산 검사 `:620-640`·누적 지출 검사 `:455-500`·`:760-800`)
- `/tests/test_e2e5_live.py`(`rig` 픽스처와 위 테스트들)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/e2e5_live.py`, `tests/test_e2e5_live.py`

열람 금지 경로: `data/interim/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `src/beautyads/eval/e2e5_live.py`, `tests/test_e2e5_live.py`

dev 모드 예산 상수를 0.40으로 올리고 경계 테스트를 추가한다. **모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: (없음)

**1. 상수(`eval/e2e5_live.py`)**
- `DEFAULT_BUDGET_USD = {"dev": 0.40, "final": 3.0}`. 변경은 이 한 줄뿐이다.
- 거부 조건(`args.budget_usd > DEFAULT_BUDGET_USD["dev"]`)·오류 코드 `DEV_BUDGET_INVALID`·유한/양수 검사(`ARGUMENT_ERROR`)·`DEV_SCORE_MAX_ITEMS = 6`·`run`/`score` 지출 합산 로직·final 기본 3.0은 **바꾸지 않는다.** 0.40은 통과하고 0.41은 거부된다(`>`).

**테스트(합성 데이터, 모델·접속 없음)**
- `tests/test_e2e5_live.py` 새 테스트: (1) dev에서 `--budget-usd 0.40`은 `DEV_BUDGET_INVALID` 없이 통과한다(가짜 점검 단계까지 진행: 선행 실패 `DOCKER_DOWN` 등 점검 문제를 주입해 호출 0건으로 끝나는 방식 등 기존 `rig` 패턴을 따르고 거부 코드가 출력에 없음을 단언), `--budget-usd 0.41`은 `DEV_BUDGET_INVALID`로 호출 0건 거부된다. (2) `--budget-usd`를 생략하면 dev 기본값이 `DEFAULT_BUDGET_USD["dev"]`이고 그 값이 0.40이다(리터럴 대신 상수를 읽어 비교하되 경계 테스트(1)가 0.40·0.41 리터럴로 값을 고정한다). (3) final의 기본 예산과 `--budget-usd 3.0` 초과 허용 동작은 변경 전과 같다(final에는 dev 상한이 적용되지 않는다). (4) `DEV_SCORE_MAX_ITEMS`는 6이고 채점 항목 7건 이상은 거부된다(기존 테스트가 있으면 그대로 통과).
- 기존 테스트는 모두 그대로 통과해야 한다(`DEFAULT_BUDGET_USD["dev"]`를 직접 읽는 `:294`·`:352`·`:643` 포함, 값이 0.40으로 바뀌어도 의미가 같다).
- 합성 문장·분류 값을 기대값으로 굳히지 않는다.

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

- 위 한 줄 외의 소스를 바꾸거나 `run`/`score` 지출을 분리하는 등 예산 로직을 바꾸지 마라. 이유: 이 step은 상수만 바로잡는다(조언 세션 요청). 예산 합산 방식 변경은 별도 결정 사항이다.
- final 모드의 예산 기본값·상한(3.0)·가드(`check_run`)와 `DEV_SCORE_MAX_ITEMS`를 바꾸지 마라. 이유: 동결·사전 등록 대상 실행의 안전장치다.
- `eval/e3_live.py`·`eval/isolation_live.py`·`Makefile`·`phases/`를 수정하지 마라. 이유: 허용 범위 밖이다(필요하면 `blocked`로 보고).
- 기존 테스트의 단언을 약화하지 마라. 이유: 이미 통과한 step의 계약이다(경계값 0.40 통과·0.41 거부는 새 테스트로 추가한다).
