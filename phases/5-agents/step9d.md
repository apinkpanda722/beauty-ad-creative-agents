# Step 9d: structured-failure-detail

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL 규칙(키·입력 값·모델 응답 전문을 로그·trace·문서에 남기지 않는다, 모델이 만든 값을 기대값으로 굳히지 않는다, 외부 SDK 호출 모양)
- `/docs/results/p5_dev_compare_preregistration.md` — §8(구조화 실패 실측: sonnet (a) 첫 시도 실패 3/6, 읽기 전용)
- `/.claude/skills/failure-patterns/SKILL.md` — FP-C14·FP-C15(읽기 전용)
- `/src/beautyads/llm/structured.py`(`StructuredStats`·`_StructuredBase.generate`·`_validate`·재요청 메시지), `/src/beautyads/domain/evaluation.py`(`EvaluationScores`: `rationale` 최대 200자·점수 `strict` 1~5), `/src/beautyads/domain/plan.py`, `/src/beautyads/domain/research.py`, `/src/beautyads/api/assembly.py`(구조화 통계 합산), `/src/beautyads/obs/trace.py`, `/src/beautyads/eval/agents_live.py`, `/tests/test_llm_structured.py`, `/tests/test_trace.py`, `/tests/test_api_assembly.py`, `/tests/test_agents_live.py`, `/tests/test_research_agent.py`, `/tests/test_architecture.py` — step 0·0b·8a·9 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/llm/structured.py`, `src/beautyads/api/assembly.py`, `src/beautyads/obs/trace.py`, `src/beautyads/eval/agents_live.py`, `tests/test_structured_failure_detail.py`(새 파일), `tests/test_llm_structured.py`, `tests/test_trace.py`, `tests/test_api_assembly.py`, `tests/test_agents_live.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/llm/structured.py`(`StructuredStats`에 첫 시도 실패 상세 칸 추가·검증 오류 위치·종류 추출·재요청 메시지에 상세 덧붙임에 한함. 호출 모양·재시도 횟수·성공 경로 불변), `src/beautyads/api/assembly.py`(trace용 구조화 통계 합산에 새 칸을 더하는 데 한함), `src/beautyads/obs/trace.py`(`TraceStructured`에 칸 추가와 `summarize_by_tenant`의 구조화 합산에 새 칸을 더하는 데 한함), `src/beautyads/eval/agents_live.py`(요약 합산에 칸 추가에 한함), `tests/test_structured_failure_detail.py`, `tests/test_llm_structured.py`·`tests/test_trace.py`·`tests/test_api_assembly.py`·`tests/test_agents_live.py`(케이스 추가에 한함, 기존 단언 변경 0줄)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

소넷 평가의 첫 시도 `SCHEMA_VIOLATION`(이번 세션 4/4, 그래서 평가가 항상 2회 호출되어 비용·지연이 2배)의 **원인을 규명할 수 있게** 검증 오류의 **필드 경로와 오류 종류**를 집계한다. 가설(길이 제한이 있는 `rationale`을 모델이 초과)은 **확인 전에 단정하지 않는다**: 이 step은 오프라인 재현과 계측만 하고 프롬프트·스키마는 바꾸지 않는다. 이 step은 모델·실제 서비스를 부르지 않는다. **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

**`llm/structured.py`**
- `StructuredStats.first_attempt_failure_details: dict[str, int]`(기본 빈 dict)를 추가하고 `merge`가 합산한다(원본 불변). 키 형식 `"<스펙 이름>|<필드 경로>|<오류 종류>"`: 필드 경로는 pydantic `ValidationError.errors()`의 `loc`를 `.`로 잇고 정수 인덱스는 `*`로 바꾼다(없으면 `-`), 오류 종류는 같은 오류의 `type`(예: `string_too_long`, `int_type`, `less_than_equal`, `missing`, `extra_forbidden`). 한 번의 검증 실패에서 오류가 여러 개면 각각 센다(최대 5개). **`input`·`ctx`·`msg`·값은 쓰지 않는다**(`errors(include_url=False, include_context=False, include_input=False)` 형태로 위치·종류만 꺼낸다). pydantic 오류가 아닌 검증 예외는 `"<스펙 이름>|-|exception:<예외 클래스 이름>"`, 객체가 아닌 값은 `"<스펙 이름>|-|not_object"`, 파싱 실패는 `"<스펙 이름>|-|parse_failed"`, 도구 미호출은 `"<스펙 이름>|-|tool_not_called"`. 키는 `[A-Za-z0-9_.*:|-]`만 남기고 120자로 자른다(형식 밖 문자는 `_`).
- 기록 시점은 기존 `first_attempt_failures`와 같다: 첫 시도가 실패하고 `generate`가 끝났을 때(재시도로 성공했든 최종 실패든) 첫 시도의 상세만 센다.
- **재요청 메시지**에 상세를 덧붙인다: `Previous submission failed: SCHEMA_VIOLATION (rationale: string_too_long). Correct it and submit again.`(경로·종류만, 최대 3개, 값 없음). 이전 형식과 호환되는 접두(`Previous submission failed: <코드>.`)는 상세가 없을 때 그대로다. 호출 모양·재시도 횟수(1회)·성공 경로는 바뀌지 않는다. 검증기 결과는 `_parse`의 반환을 확장하거나 `generate` 안의 지역 값으로 전달하고 **인스턴스 공유 상태에 의존하지 않는다**(스레드 안전).

**소비자(추가에 한함)**: `api/assembly.py`가 요청 안 구조화 통계를 합칠 때 새 칸도 합산해 `obs.trace.TraceStructured.first_attempt_failure_details: dict[DetailKey, Count]`(키 정규식 `^[A-Za-z0-9_.*:|-]{1,120}$`, 값 정수)에 싣는다. `trace.summarize_by_tenant`와 `eval/agents_live.py` 요약의 `structured`도 같은 칸을 종류별 합으로 싣는다(모델 이름별, 호출 수가 20 미만이면 `sample_too_small` 규칙은 그대로).

**반드시 있어야 하는 테스트**(합성 응답·가짜 호출, 모델 문장·값을 기대값으로 굳히지 않는다):
- **오프라인 재현(가설의 가능성 확인, `tests/test_structured_failure_detail.py`)**: 실제 `EvaluationScores` 검증기로 만든 `StructuredSpec`(이름 `evaluation_scores`)에 가짜 호출이 (1) 201자 이상 `rationale`과 유효한 점수를 첫 시도로, 유효한 응답을 둘째 시도로 돌려주면 `ok True`·`attempts 2`·상세 키에 `evaluation_scores|rationale|string_too_long`이 1이다, (2) 범위 밖 점수는 `differentiation|…|less_than_equal`(또는 `greater_than_equal`), (3) 문자열 점수는 strict라 `…|int_type`, (4) 필수 칸 누락은 `missing`, (5) 알 수 없는 칸은 `extra_forbidden`, (6) JSON 아닌 응답은 `parse_failed`, (7) 도구 미호출은 `tool_not_called`. 이 케이스는 **계측이 오류 위치·종류를 정확히 분리하는지**를 보이는 것이고 실제 모델의 실패 원인을 단정하지 않는다(테스트 이름·주석에 명시).
- **값 미노출**: 합성 비밀 문자열(`SYNTHETIC-SECRET-…`)을 오류를 일으킨 값·필드 이름 대신 값 쪽에 넣어도 상세 키·재요청 메시지·trace·요약에 없다. 키 정규식 밖 문자가 `_`로 바뀌고 120자로 잘린다. 오류가 6개 이상이어도 5개만 센다.
- **재요청 메시지 전달 확인(FP-C14)**: 가짜 호출이 받은 둘째 시도 `messages`를 직접 열어 마지막 사용자 메시지에 `Previous submission failed: SCHEMA_VIOLATION (rationale: string_too_long)` 형태가 있고 값이 없으며, 상세가 없는 실패(`parse_failed`)는 이전 형식 그대로다.
- **합산·기록**: `merge`가 상세를 합산하고 원본을 바꾸지 않는다. 조립 경유 trace에 모델별 `first_attempt_failure_details`가 있고 `summarize_by_tenant`·`agents_live` 요약이 합산한다. 기존 `tests/test_llm_structured.py`·`tests/test_research_agent.py`의 단언은 그대로 통과한다.

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

- 프롬프트·스키마·점수 기준을 이 step에서 바꾸거나 `rationale` 초과를 원인으로 단정하는 문구·분기를 만들지 마라. 이유: 가설은 확인 전에 단정하지 않는다(조언 세션 지시). 이 step은 계측과 오프라인 재현뿐이고 수정은 다음 step이 계측 결과에 따라 한다.
- 검증 오류의 `input`·`ctx`·`msg`·값·원문을 stats·재요청 메시지·trace·요약에 남기지 마라. 이유: 모델 출력은 외부 텍스트이고 값에 비밀이나 입력 원문이 섞일 수 있다(AGENTS.md CRITICAL). 필드 경로와 오류 종류만 남긴다.
- 재시도 횟수·호출 모양·성공 경로·`StructuredResult` 형식을 바꾸지 마라. 이유: 구조화 통계와 호출 가드가 이 계약에 의존한다(FP-C13·FP-C15, 6e). 새 칸은 기본값이 있는 추가만 한다.
- 생성기 인스턴스에 요청 간 공유되는 가변 상태로 상세를 전달하지 마라. 이유: 요청이 스레드에서 병렬로 돌 수 있다. 지역 값이나 반환 확장으로 전달한다.
- 오프라인 재현 테스트가 실제 모델의 실패 원인을 증명하는 것처럼 쓰지 마라. 이유: 합성 응답은 계측의 정확성만 보인다. 실제 원인은 사용자가 다시 실행한 trace의 상세 집계로 확인한다.
- `data/manifest/costs.jsonl`·`data/interim/`의 파일을 읽거나 수정하지 마라. 이유: 장부와 실행 결과는 사용자의 기록이다. 테스트는 합성 데이터와 `tmp_path`만 쓴다.
