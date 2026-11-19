# Step 24: fixed-axes-pattern

## 설계 검토 기록

**배경(사용자 확정·조언 세션 승인)**: dev 재스모크에서 사용자가 지정한 포맷(예: "일반인 후기형 포맷")을 Supervisor 기획안이 따르지 않았다. 기획 프롬프트(`agents/planning.py` `_SYSTEM`, 2026-11-18-3)는 `research.pattern_context.dominant_axes`에 있는 축에서 **지배 값과 다른 값**을 고르라고 하고, `pattern_context`는 brief를 보지 않아 사용자가 고정한 축도 똑같이 지배 축으로 판정한다(선케어 풀의 format 최빈 점유율 0.529 ≥ `MIN_DOMINANT_SHARE` 0.4). 이 step은 **brief에서 지정된 축을 `dominant_axes`·`weak_axes`에서 제외**한다(B안). 기획·평가 프롬프트 문구와 `MIN_DOMINANT_SHARE`·`THIN_POOL_MAX` 등 상수는 바꾸지 않는다. 지정 축이 없는 요청(P5 요청)의 동작은 바이트 단위로 같아야 한다.

**식별자 전수 대조(현재 코드, 모두 열어 확인)**: `domain/supervisor.py:162 pattern_context(tool_outputs, evidence_ids)`(닫힌 축 `closed = {"hook_type": …, "angle": …, "format": …}`, 축마다 관측 점유율이 `MIN_DOMINANT_SHARE` 이상이면 `dominant_axes.append({"axis", "values", "share"})` 아니면 `weak_axes.append(axis)`, 모든 관측 축은 `distribution`에 `{"axis","total","top_share","second_share","top_value"}`, 반환 키 `pool_size`·`pool_basis`·`thin_pool`·`min_dominant_share`·`thin_pool_max`·`dominant_axes`·`weak_axes`·`distribution`), `agents/supervisor.py:372`(`handoff["pattern_context"] = pattern_context(state["sv_tool_outputs"], handoff["evidence_ids"])`; `state["sv_brief"]`는 `ResearchBrief.model_dump`로 키 `hook_type`·`angle`·`format`이 있다), `domain/supervisor.py:252 pattern_alignment`(관찰 전용, **불변**), `agents/planning.py:23-25`·`agents/evaluation.py:38-41`(프롬프트 문구, **불변**; 평가 입력 `research.pattern_context`는 지배 축이 비면 구체성으로 판단한다고 되어 있다).

**상수 단언 grep(전수)**: `pattern_context`를 부르는 기존 테스트 — `tests/test_domain_supervisor.py:260-281`(경계 점유율·`weak_axes == ["angle"]`·`dominant_axes == [...]`), `:293-295`(`thin_pool` 경계)·`:299-336`(분포 순위, 모호·무효 출력 건너뜀: `context["distribution"] == context["dominant_axes"] == context["weak_axes"] == []`), `tests/test_supervisor.py:556-582`(`expected = pattern_context([output], f.handoff["evidence_ids"])`와 `result["handoff"]["pattern_context"] == expected` 정확 일치; 합성 `decision_data()`의 세 축이 모두 `None`이라 이 step 뒤에도 같은 딕셔너리여야 한다), `:620-633`(`monkeypatch`로 `supervisor.pattern_context`를 바꾼 호출 `changed(...)` — **새 인자가 생겨도 이 가짜가 받을 수 있어야 한다**: 가짜의 시그니처를 확인하고 필요하면 `**kwargs`를 받게 갱신), `tests/test_evaluation.py:227-247`(`pattern_context([], ["yt:a"])`와 평가 payload의 정확 일치), `tests/test_trace.py:439`. 모두 인자 두 개 호출이라 기본값 `()`이면 불변이다.

**새 칸 대응표**: `fixed_axes`(brief의 `hook_type`·`angle`·`format` 중 값이 있는 축 → `pattern_context(..., fixed_axes=)` → 지배·약한 축 제외 → 기획·평가 입력의 `pattern_context`), 반환 키 `fixed_axes`(지정 축이 있을 때만 존재).

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건(합성 테스트만).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 동결된 기준은 결과를 본 뒤 바꾸지 않는다(이 step은 기획·평가 프롬프트·상수를 바꾸지 않는다), 모델이 만든 값을 테스트 기대값으로 굳히지 않는다
- `/src/beautyads/domain/supervisor.py`(`pattern_context`·`pattern_alignment`), `/src/beautyads/agents/supervisor.py`(`:360-380` 호출부와 `sv_brief`), `/src/beautyads/agents/planning.py`·`/src/beautyads/agents/evaluation.py`(읽기 전용)
- `/tests/test_domain_supervisor.py`, `/tests/test_supervisor.py`(`:556-633`), `/tests/test_evaluation.py`(읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/supervisor.py`, `src/beautyads/agents/supervisor.py`, `tests/test_domain_supervisor.py`, `tests/test_supervisor.py`

열람 금지 경로: `data/interim/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `src/beautyads/domain/supervisor.py`, `src/beautyads/agents/supervisor.py`, `tests/test_domain_supervisor.py`, `tests/test_supervisor.py`

`pattern_context`가 brief에서 지정된 축을 지배 축에서 제외하게 한다. **모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: `fixed_axes`

**1. `domain/supervisor.py`**
- 시그니처 `pattern_context(tool_outputs: list[dict], evidence_ids: list[str], *, fixed_axes=()) -> dict`. `fixed_axes`는 축 이름(`"hook_type"`·`"angle"`·`"format"`)의 반복 가능한 값이다. 이 셋 밖의 이름이 있으면 `ValueError("PATTERN_FIXED_AXES_INVALID")`다(값 없는 오류 문구).
- 관측된 축(`counts[axis]`가 비어 있지 않은 축)이 `fixed_axes`에 있으면 **`dominant_axes`에도 `weak_axes`에도 넣지 않는다.** `distribution`(관찰)에는 기존대로 넣는다. 그 밖의 계산(풀 크기·`thin_pool`·다른 축의 지배 판정·`MIN_DOMINANT_SHARE`)은 불변이다.
- `fixed_axes`가 비어 있지 않으면 반환 딕셔너리에 키 `"fixed_axes"`(정렬된 축 이름 리스트, 중복 제거; **관측 여부와 무관하게 받은 축 전부**)를 더한다. **비어 있으면 키를 만들지 않아 반환값이 변경 전과 완전히 같다.**
- `pattern_alignment`·상수·`THIN_POOL_NOTE` 등은 건드리지 않는다.

**2. `agents/supervisor.py` 호출부(`:372`)**
- `fixed = tuple(axis for axis in ("hook_type", "angle", "format") if state["sv_brief"].get(axis))`를 만들어 `pattern_context(state["sv_tool_outputs"], handoff["evidence_ids"], fixed_axes=fixed)`로 부른다(지정이 없으면 `()`라 호출 결과 불변). 그 밖의 흐름(`THIN_POOL_NOTE`·`available_efficacy`·계획 호출)은 불변이다.

**테스트(합성 데이터, 모델·접속 없음)**
- `tests/test_domain_supervisor.py`: (1) 인자 두 개 호출 결과가 변경 전과 같다(기존 `:260-336` 테스트가 단언 변경 없이 통과, 반환 딕셔너리에 `fixed_axes` 키 없음). (2) 지배 축(점유율 ≥ `MIN_DOMINANT_SHARE`)인 `format`을 `fixed_axes=("format",)`로 주면 `dominant_axes`에서 빠지고 `weak_axes`에도 없으며 `distribution`에는 남고 `fixed_axes == ["format"]`이다. (3) 약한 축(기준 미달)을 지정해도 `weak_axes`에서 빠진다. (4) 지정하지 않은 다른 축의 지배·약한 판정은 지정 여부와 무관하게 같다(같은 입력에서 `fixed_axes`만 달리한 결과 비교). (5) 관측되지 않은 축을 지정해도 `fixed_axes`에 들어가고 오류가 없다. (6) 알 수 없는 축 이름은 `PATTERN_FIXED_AXES_INVALID`이고 입력(`tool_outputs`)이 바뀌지 않는다(기존 테스트의 deepcopy 비교 방식). (7) 중복·순서 다른 입력이 같은 정렬 리스트를 낸다. (8) `fixed_axes`를 준 결과도 `json.dumps(..., allow_nan=False)`가 된다.
- `tests/test_supervisor.py`: (9) brief에 `format`이 있는 합성 결정(`decision_data(format="ugc_style")`)으로 `run_request`를 돌리면 기획 호출이 받은 `handoff["pattern_context"]`에서 `format`이 `dominant_axes`·`weak_axes`에 없고 `fixed_axes == ["format"]`이며, 결과의 `handoff["pattern_context"]`도 같다(`format`이 지배 축이 되는 합성 도구 출력 사용). (10) 세 축이 모두 `None`인 결정에서는 `handoff["pattern_context"]`가 `pattern_context([output], ids)`와 정확히 같다(기존 `:556-582` 테스트 유지). (11) `:620-633`의 가짜 `pattern_context`가 새 키워드 인자를 받는다(필요하면 가짜의 시그니처만 갱신, 단언은 유지).
- 합성 문장·분류 값·모델 출력을 기대값으로 굳히지 않는다(형식·집합·동일성만 검사).

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

- `agents/planning.py`·`agents/evaluation.py`의 프롬프트(`_SYSTEM`·`_CRITERIA`)·버전, `MIN_DOMINANT_SHARE`·`THIN_POOL_MAX`·`pattern_alignment`·`THIN_POOL_NOTE`를 바꾸지 마라. 이유: 기획·평가 프롬프트와 상수는 동결 대상이다. 이 step은 지배 축 판정의 입력만 바꾼다.
- 지정 축이 없을 때 `pattern_context`의 반환 키·값을 하나라도 바꾸지 마라(`fixed_axes` 키는 지정이 있을 때만 존재). 이유: 지정 축이 없는 P5 요청의 동작과 기존 정확 일치 단언을 보존해야 한다.
- `agents/supervisor.py`의 `decide`·`_SYSTEM`을 수정하지 마라. 이유: 해석 프롬프트는 다음 step(25)의 범위다.
- 허용 파일 밖(`api/`·`eval/`·`analysis/`·`docs/`)을 수정하거나 새 의존성을 추가하지 마라. 이유: 허용 범위 밖이다(필요하면 `blocked`로 보고).
- 기존 테스트의 단언을 약화하지 마라(`:620-633` 가짜의 시그니처 갱신만 허용). 이유: 이미 통과한 step의 계약이다.
