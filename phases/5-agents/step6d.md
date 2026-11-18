# Step 6d: dev-compare

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`eval`은 모든 계층 import 가능, `fastapi`·`httpx` 제외), CRITICAL 규칙(사전 등록 파일을 결과 전에 커밋, 개발 반복은 luna·haiku 기본, 상한 검사, `temperature` 금지)
- `/docs/results/p5_dev_compare_preregistration.md` — 이 step이 구현하는 비교의 사전 등록 기준(읽기 전용. 결과를 본 뒤 바꾸지 않는다)
- `/docs/ARCHITECTURE.md` — "요청 처리 공통 장치"
- `/docs/EVAL.md`(동결, 읽기 전용)
- `/src/beautyads/agents/research.py`, `/src/beautyads/agents/planning.py`, `/src/beautyads/agents/evaluation.py`, `/src/beautyads/agents/lookups.py`, `/src/beautyads/agents/plan_eval.py`, `/src/beautyads/domain/evaluation.py`, `/src/beautyads/domain/research.py`, `/src/beautyads/llm/structured.py`, `/src/beautyads/llm/chat.py`, `/src/beautyads/obs/ledger.py`, `/src/beautyads/eval/live_agent.py`, `/src/beautyads/eval/cq_verify.py`(`cq_preflight`), `/Makefile`, `/tests/test_live_agent.py`, `/tests/test_architecture.py` — 이전 step 산출물과 live 진입점의 점검 방식

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/p5_compare.py`(새 파일), `Makefile`, `README.md`, `tests/test_p5_compare.py`(새 파일), `tests/test_compose.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/p5_compare.py`, `Makefile`(`live-compare` 타깃과 `.PHONY` 추가에 한함, `verify` 불변), `README.md`(live-compare 절 추가에 한함), `tests/test_p5_compare.py`, `tests/test_compose.py`(`Makefile` 타깃 목록을 단언한다면 `live-compare` 추가를 반영하는 갱신에 한함, 그 외 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

`docs/results/p5_dev_compare_preregistration.md`(이 step 전에 커밋된 사전 등록 파일)에 적힌 두 비교를 실행하는 **사용자 실행용 도구**를 만든다: (1) terra `reasoning_effort` 비교(`none`·`low`·`medium`), (2) sonnet 구조화 출력 (a) 대 (b) 비교. 이 step은 도구와 테스트만 만들고 **실행하지 않는다**(모델 호출은 사용자가 `make live-compare`로 한다). 입력·지표·판정 규칙·상한은 **사전 등록 파일이 정하고 이 step이 그대로 구현한다**: 파일을 읽어 숫자를 가져오지 않고(파싱하지 않고) 구현은 아래 상수로 두되, 상수가 사전 등록 파일의 값과 같다는 점검(`tests`가 파일 내용에서 값 줄을 찾아 비교)을 둔다. **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

**`eval/p5_compare.py`**(`eval` 계층): `main(argv=None, *, environ=None, out=None, ...) -> int`, 하위 명령 `inputs`·`terra`·`sonnet`(인자 `ARGS='inputs'` 형태). 공통:
- **사전 등록 검사(B-FP-043)**: 시작 전에 `docs/results/p5_dev_compare_preregistration.md`가 git에 **커밋돼 있고 작업 트리에서 수정되지 않았는지** 확인한다(`git log -1 -- <파일>`이 비어 있지 않고 `git status --porcelain -- <파일>`이 비어 있음. 점검 함수는 주입 가능). 아니면 `PREREGISTRATION_NOT_COMMITTED`를 출력하고 호출 없이 종료 코드 2.
- 사전 점검: `cq_preflight`와 같은 방식(컨테이너·키 이름만, 값 출력 금지)과 이미지 끄기: 이 비교는 이미지를 쓰지 않는다. 호출 전 **목적별 상한**을 `check_purpose_cap`으로 검사한다(목적 접두어 `compare-inputs` $0.02, `compare-terra` $0.12, `compare-sonnet` $0.10, 사전 등록 파일의 값과 같은 상수). 상한 이상이면 호출 없이 멈춘다.
- 결과: 실행마다 `data/interim/p5_compare/<날짜>-<하위 명령>.json`(gitignore)과 표 한 개를 출력한다. **결과 파일·터미널 출력·표**에는 키·값·모델 전문(기획안 전문 포함)이 없다: 지표와 입력·출력 해시, 토큰·비용만. **예외(중간 입력 산출물)**: 비교에 필요한 `inputs/`의 핸드오프 5개와 `plans/`의 기획안 15개는 `data/interim/` 아래 로컬 gitignore 파일로 둔다. `plans/` 파일에는 모델이 만든 `Plan` 필드만 담고 호출 인자·원응답 전문·키·`thought_signatures` 같은 부가 필드는 담지 않는다. 결과 파일에는 이 중간 산출물의 내용이 들어가지 않는다.
- **`inputs`**: dev workspace(사전 등록 파일의 `mixsoon` 세럼·`cosrx` 선세럼) 요청 5건(사전 등록 파일의 고정 브리프 5개)에 리서치 에이전트(luna, `reasoning_effort="none"`)를 한 번씩 돌려 `ResearchHandoff` 5개를 `data/interim/p5_compare/inputs/`에 저장하고 각 파일의 sha256을 출력한다(사용자가 사전 등록 파일에 해시를 추가 커밋한 뒤 `terra`를 실행한다). 장부 목적 `compare-inputs`. 이미 저장된 입력이 있으면 덮어쓰지 않고 거부한다.
- **`terra`**: 저장된 입력 5개 × `reasoning_effort` `none`·`low`·`medium` = 15호출(한 호출에 기획안 1안, 같은 프롬프트·같은 입력). 입력 파일의 sha256이 사전 등록 파일에 적힌 값과 같지 않으면 호출 없이 `INPUT_HASH_MISMATCH`로 멈춘다. 각 기획안에 `checks.run_checks`(6b의 조회 구현체)를 돌려 지표를 계산한다: **쓸 수 있는 기획안 수**(= `passed`이고 `evidence_ids`가 1개 이상이며 전부 핸드오프 풀 안인 건), 구조화 실패 수(재요청 뒤 실패), 보고용 호출당 비용·추론 토큰. 판정(사전 등록 파일의 B-1): 쓸 수 있는 기획안 수가 가장 많은 값 → 동률이면 구조화 실패가 적은 값 → 그래도 같으면 낮은 비용 값(`none` < `low` < `medium`). **모든 값이 3/5 미만이면 결정을 보류**하고 "보류"를 출력한다(자동 선택 없음). 기획안 5×3개는 `data/interim/p5_compare/plans/`에 저장하고 각 sha256을 출력한다. 장부 목적 `compare-terra`.
- **`sonnet`**: 위 기획안 중 **파일 해시 오름차순 앞 6건**(코드 검사 결과와 무관)을 `claude-sonnet-5-5`로 평가한다: 각 입력을 (a) `ToolCallStructured`와 (b) `NativeAnthropicStructured`로 1번씩 = 12호출(+재요청). 지표: 방식별 **첫 시도 구조화 실패율과 재요청 뒤 실패율**, 두 방식 점수 차이 절댓값 평균과 완전 일치 비율(보고용), 호출당 입력 토큰·비용(보고용), 캐시 읽기 토큰(같은 접두 연속 2호출에서 관찰, 보고용). 판정(사전 등록 파일의 B-2): **(b)의 재요청 뒤 구조화 실패율이 (a)보다 엄격히 낮을 때만** (b)를 기본으로 권고, 같거나 (a)가 낮으면 (a) 유지. 점수 차이 평균이 1.0(5점 척도)을 넘으면 판정과 별도로 "검토 표시". 장부 목적 `compare-sonnet`.
- 이 도구는 **판정 결과를 출력할 뿐 코드 상수(`PLANNING_REASONING_EFFORT`, 평가 기본 방식)를 바꾸지 않는다**(사용자 승인 뒤 별도 변경).
- `Makefile`에 `live-compare: uv run python -m beautyads.eval.p5_compare $(ARGS)`와 `.PHONY`를 추가한다(`verify`에는 넣지 않는다).

**반드시 있어야 하는 테스트**(가짜 함수·합성 값, 실제 호출 없음):
- 사전 등록 검사: 커밋 안 됨·수정됨이면 `PREREGISTRATION_NOT_COMMITTED`, 종료 코드 2, 모델 호출 없음(가짜가 불리지 않는다). 상한 상수가 사전 등록 파일의 값 줄과 같다(파일 내용에서 값을 찾아 비교, 못 찾으면 실패).
- 목적 상한: `compare-terra` 합계가 상한 이상이면 호출 없이 멈춘다. 접두어가 정확히 맞는 목적만 합산된다.
- `terra` 판정(순수 함수로 분리해 합성 입력으로 검증): 쓸 수 있는 기획안 수 최다 선택, 동률에서 구조화 실패가 적은 값, 그래도 같으면 낮은 비용 값(순서 `none` < `low` < `medium`), 모두 3/5 미만이면 "보류"이고 값을 고르지 않는다. 쓸 수 있는 기획안 수 정의(`passed`이고 `evidence_ids` 1개 이상이며 전부 풀 안)가 경계 케이스(근거 0개, 풀 밖 ID 하나, `passed`만 거짓)에서 맞다. 입력 해시 불일치는 호출 없이 `INPUT_HASH_MISMATCH`.
- `sonnet` 판정(순수 함수): (b)가 엄격히 낮을 때만 (b) 권고, 같으면 (a), (a)가 낮으면 (a). 첫 시도 실패율과 재요청 뒤 실패율을 따로 계산한다. 점수 차이 평균 1.0 초과 검토 표시. 파일 해시 오름차순 앞 6건 선택이 입력 순서에 무관하다.
- **결과 json·터미널 출력·표**에 합성 비밀·합성 기획안 문자열이 없다(합성 값을 넣어 확인). **`plans/` 파일에는 `Plan` 필드만 있고 합성 비밀·호출 인자·부가 필드가 없다.** `data/interim/`이 `.gitignore`에 포함돼 있다(`.gitignore` 줄 확인). `inputs`가 기존 입력을 덮어쓰지 않는다.
- `tests/test_architecture.py`가 통과한다(`eval`은 `fastapi`·`httpx`를 import하지 않는다).

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

- 사전 등록 파일이 커밋돼 있지 않거나 수정됐는데 호출하지 마라. 이유: 기대값·판정 규칙은 실행 전에 정해 커밋하고 결과를 본 뒤 바꾸지 않는다(AGENTS.md CRITICAL, B-FP-043).
- 판정 결과로 `PLANNING_REASONING_EFFORT`나 평가 기본 방식 상수를 이 도구에서 바꾸지 마라. 이유: 상수 변경은 결과 보고와 사용자 승인 뒤 별도 변경이다. 도구는 판정을 출력만 한다.
- 사전 등록 파일의 값을 파싱해 동작을 정하지 마라. 이유: 구현은 상수이고 파일과 같다는 점검만 둔다(파일이 바뀌면 점검이 실패해 드러난다. B-FP-044).
- 결과 파일·터미널 출력·표에 기획안 전문·모델 응답 전문·키를 남기지 마라(해시·지표·비용만). 이유: 결과가 보고서와 대화로 퍼질 수 있다. 중간 입력 산출물(`inputs/`·`plans/`)은 `data/interim` 아래 로컬 gitignore 파일로만 허용하고 `plans/`에는 `Plan` 필드만 담는다(AGENTS.md: `data/interim`은 커밋하지 않는다).
- `make live-compare`를 실행하거나 실제 서비스에 접속하는 테스트를 만들지 마라. 이유: 모델 호출은 사용자가 실행한다(AGENTS.md CRITICAL). 모든 호출 경로는 주입 함수로 테스트한다.
- test 브랜드(isntree·beauty_of_joseon) 입력을 쓰지 마라. 이유: 개발 비교는 dev workspace 입력만 쓰고 test 브랜드는 최종 평가·시연에만 쓴다(P5 결정).
