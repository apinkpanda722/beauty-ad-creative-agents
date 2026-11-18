# Step 6c: plan-eval-loop

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`agents`), CRITICAL 규칙(LangGraph 상태 dict·기본 타입, 하위 그래프 전용 상태, 되돌림은 상태 카운터, `recursion_limit`은 안전망, 판정은 코드)
- `/docs/PRD.md` — 핵심 기능 7·8(되돌림 최대 2회, 피드백 메모리)
- `/docs/ARCHITECTURE.md` — "컨텍스트 관리"(되돌림 시 전달), "멀티테넌트"
- `/docs/CONTRACTS.md` — "LangGraph" 절(`recursion_limit`은 슈퍼스텝 수)
- `/src/beautyads/agents/planning.py`, `/src/beautyads/agents/evaluation.py`, `/src/beautyads/agents/lookups.py`, `/src/beautyads/agents/research.py`, `/src/beautyads/agents/state.py`, `/src/beautyads/agents/design_images.py`, `/src/beautyads/domain/evaluation.py`, `/src/beautyads/domain/research.py`, `/src/beautyads/domain/tenant.py`, `/src/beautyads/store/tenant_repository.py`, `/src/beautyads/llm/image.py`, `/tests/test_research_agent.py`, `/tests/test_architecture.py` — step 4·5·5c·6a·6b 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/agents/plan_eval.py`(새 파일), `tests/test_plan_eval.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/agents/plan_eval.py`, `tests/test_plan_eval.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

기획과 평가를 잇는 **되돌림 하위 그래프**를 만든다. 평가가 기준 미달이면 기획으로 되돌린다(최대 2회, 상태 카운터). 되돌림에는 **코드 검사 실패 사유와 LLM 평가의 낮은 항목을 둘 다** 전달하고 이전 기획안 전문은 전달하지 않는다. 이 step은 모델·네트워크를 부르지 않는다(가짜 `plan`·`evaluate`·`image` 함수만). **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

**`agents/plan_eval.py`**: `run_plan_eval(*, brief: dict, handoff: dict, profile: dict, feedback: dict | None, plan_fn, evaluate_fn, image_fn=None, with_image: bool = False, max_reworks: int = 2) -> dict`(`plan_fn`·`evaluate_fn`은 주입된 함수: 6b의 `make_plan`·`evaluate_plan`을 감싼 것, `image_fn`은 6a의 `generate_image`+`save_design_image`를 감싼 것. 반환은 dict·기본 타입만).
- LangGraph 하위 그래프, **전용 상태 스키마**(`TypedDict`, dict·기본 타입만): `brief`, `handoff`, `profile`, `feedback`, `plan`, `report`, `rework_count`, `rework_payload`, `attempts`(시도별 요약 dict 목록: 시도 번호, 코드 검사 `passed`, 점수, 낮은 항목, 실패한 검사 코드 목록, 비용), `image`, `status`. **부모 상태(`agents/state.py`)·리서치 하위 그래프 상태(`agents/research.py`)와 키를 하나도 공유하지 않는다**(테스트가 키 집합 교차 0을 단언). 부모와는 `run_plan_eval`이 변환한다(입력은 dict, 출력은 결과 dict, 상태를 통째로 넘기지 않는다).
- 노드: `plan`(→ 기획안 1안, 구조화 실패면 `status="failed"`로 끝), `evaluate`(→ `EvaluationReport`), `route`(통과면 `done`, 미통과이고 `rework_count < max_reworks`면 `rework_count += 1` 하고 `plan`으로 되돌림, 그렇지 않으면 `needs_review`로 끝). **되돌림 횟수는 상태 카운터로 세고** `recursion_limit`은 안전망으로만 설정한다(실제 노드 수에 맞춘 상수, 카운터로 먼저 끝난다). 최대 2회는 `max_reworks` 인자로 받되 2를 넘으면 `ValueError`.
- `rework_payload`는 `{"check_issues": [{"code", "field", "detail"}…]}`(실패한 검사 항목과 사유, `fail` 심각도만, `unknown`은 포함하지 않는다)와 `{"low_items": [{"item", "score", "rationale"}…]}`(낮은 평가 항목)를 **둘 다** 담는다. 채점이 구조화 실패(`scoring_failed`)면 `low_items`는 비고 그 사실(`scoring_failed: true`)을 담는다. 이전 기획안의 본문·필드 값은 담지 않는다.
- 이미지: `with_image=True`이고 최종 상태가 `done`·`needs_review`일 때 **한 번만**(되돌림마다 만들지 않는다) `image_fn(plan)`을 부른다. 실패는 예외가 아니라 `image: {"ok": False, "code": ...}`로 남고 기획 결과는 유지된다. `with_image=False`(기본)면 `image_fn`을 부르지 않는다.
- 결과 dict: `{"status": "done"|"needs_review"|"failed", "plan", "report", "rework_count", "attempts", "image", "unknown_count", "unknown_codes", "result_counts", "evidence_counts", "disclaimer"}`. **`unknown_count`·`unknown_codes`는 `passed`와 분리된 별도 칸**이고(최종 평가 보고에서 복사), `disclaimer`는 `CLAIM_CHECK_DISCLAIMER` 그대로다. `result_counts`는 핸드오프의 값(리서치 도구 결과의 전체·표시 건수)을 복사하고, `evidence_counts`는 `{"in_plan": 기획안의 근거 ID 수, "in_pool": 핸드오프 근거 ID 수}`다(화면이 `domain.research.count_label`로 "N건 중 M건"을 만드는 데 쓴다. 이 step은 문구를 만들지 않는다).
- 피드백 메모리: `feedback`은 호출부가 `domain.tenant.summarize_feedback` 결과(dict)로 넘긴다. 이 모듈은 저장소를 부르지 않는다(주입만).

**반드시 있어야 하는 테스트**(가짜 함수·합성 값, 모델 문장을 기대값으로 굳히지 않는다):
- 흐름: 첫 평가 통과면 `rework_count == 0`·`status="done"`. 첫 평가 미통과 뒤 통과면 `rework_count == 1`. 계속 미통과면 `rework_count == 2`에서 `needs_review`로 끝나고 `plan_fn`이 3번(첫 시도 + 되돌림 2회) 불린다. `max_reworks=3`은 `ValueError`.
- 되돌림 전달: 두 번째 `plan_fn` 호출 인자(`rework`)에 `check_issues`와 `low_items`가 **둘 다** 있고(`fail` 코드만 `check_issues`에, `unknown`은 없다), 이전 기획안의 합성 식별 문자열이 어디에도 없다. 채점 실패 시 `scoring_failed`가 전달된다.
- 상태: 하위 그래프 상태의 모든 값이 dict·기본 타입이다. 상태 스키마 키 집합과 부모 상태·리서치 하위 그래프 상태의 키 집합의 교차가 비어 있다. 횟수는 상태 카운터이고(`recursion_limit`에 의존하지 않는다: 매우 낮은 안전망에서도 카운터로 끝나는 케이스와, 안전망을 넘기는 합성 루프가 예외 없이 `needs_review`나 `failed`로 끝나는 케이스).
- 이미지: `with_image=False`(기본)에서 `image_fn`이 불리지 않는다. `with_image=True`에서 되돌림이 2번 있어도 `image_fn`이 **1번**만 불린다. `image_fn`이 실패를 돌려줘도 결과 `plan`·`report`가 유지되고 `image.ok`가 거짓이다. `plan_fn` 구조화 실패는 `status="failed"`이고 `image_fn`이 불리지 않는다.
- 결과: `unknown_count`·`unknown_codes`가 평가 보고에서 복사된 별도 칸이고 `passed`가 거짓이든 참이든 같은 값이다. `disclaimer`가 있다. `result_counts`·`evidence_counts`가 핸드오프에서 온 값이다.
- `tests/test_architecture.py`가 통과한다(`agents`는 허용 계층만).

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

- 되돌림에 이전 기획안 전문이나 필드 값을 넣지 마라. 이유: 되돌림에는 실패한 검사 항목과 낮은 평가 항목만 전달한다(ARCHITECTURE 컨텍스트 관리).
- 되돌림 횟수를 `recursion_limit`에 맡기지 마라. 이유: 횟수는 상태 카운터로 세고 `recursion_limit`은 안전망으로만 쓴다(AGENTS.md CRITICAL, CONTRACTS: `recursion_limit`은 슈퍼스텝 수라 기획 횟수가 아니다).
- `unknown_count`를 `passed`에 합치거나 결과에서 빼지 마라. 이유: "근거 연결 없음"은 사용자가 보는 결과와 보고에 눈에 띄게 별도로 노출한다(P5 결정).
- 하위 그래프 상태에 부모·리서치 상태 키를 쓰거나 pydantic 객체를 넣지 마라. 이유: 전용 상태 스키마와 dict·기본 타입 규칙(AGENTS.md CRITICAL).
- 되돌림마다 이미지를 생성하지 마라. 이유: 이미지 목적 상한이 있고(기본 $3.5) 이미지는 최종 기획안에 한 번만 만든다. 이미지 실패로 기획 결과를 버리지도 마라.
- 저장소·그래프·모델을 이 모듈에서 직접 부르지 마라. 이유: 함수 주입으로 테스트하고 조립은 step 7(`api`)이 한다.
