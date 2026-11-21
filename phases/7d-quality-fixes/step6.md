# Step 6: langfuse-stage-inputs

## 설계 검토 기록

**배경(사용자 live 확인과 조언 세션 설계 누락 정정, 2026-11-21)**: Langfuse trace의 새 span 구조와 `ask`의 입력·출력은 확인됐고, 키·토큰 검색(`sk-`·`Bearer`·`AIza`)도 나오지 않았다. 그런데 **`research` span의 Input이 `null`**이다. 7d 브리프가 입력을 채울 곳을 `ask`와 `supervisor`로만 적고 `research`·`planning`·`evaluation`·`image`는 output만 적었던 **설계 누락**이다. 이 step은 **모든 단계 span의 입력**을 채운다. 단계 span의 **output 키와 이미 채운 `ask`·`supervisor`의 입출력은 바꾸지 않는다**. 키 이름은 기존과 같은 한국어 라벨 체계를 따른다.

**실제로 각 에이전트가 받은 값(코드를 열어 확인한 위치)**:
- **research 입력** = Supervisor가 넘긴 과제 지시서: `agents/supervisor.py`가 결과에 싣는 `result["brief"]`(`domain/research.py` `ResearchBrief`: `goal`, `category`, `claim`, `hook_type`, `angle`, `format`, `skin_concern`, `output`(`patterns`|`examples`|`both`), `max_tool_calls`). 연구 에이전트는 이 `brief`를 입력으로 받는다(`agents/research.py`의 `run_research(brief, ...)`).
- **planning #k 입력** = `agents/planning.py` `make_plan(*, brief, handoff, profile, feedback, rework, structured, purpose="plan", **call_options)`의 `payload`: `brief`, `research`(`research_payload(handoff)`), `available_efficacy`(코드가 확인한 효능 목록), `claim_choice`(`mode`·`claims`·`requested_claim`), `profile`, `feedback`, `rework`(`check_issues`·`low_items`, 재작업일 때만), `raw_tool_outputs`. **결과에 남는 값만** 쓴다: `result["brief"]`, `result["claim_choice"]`, `result["available_efficacy"]`(`agents/supervisor.py` 640~644행에서 만든 결과 키), `result["handoff"]["evidence_ids"]`(근거 소재 수), 그리고 재작업이면 **같은 기획안의 바로 앞 시도** `attempts[k-1]`의 `failed_check_codes`·`low_items`(`agents/plan_eval.py`의 시도 dict 키 `attempt`, `checks_passed`, `final_passed`, `scores`, `low_items`, `failed_check_codes`)가 다음 시도의 `rework` 입력이 된다. `profile`·`feedback`·`raw_tool_outputs`는 **싣지 않는다**(`profile`에는 `forbidden_terms`가 있고 `feedback`·`raw_tool_outputs`는 크다. 4,000자 상한 이전에 허용 키만 고르는 원칙).
- **evaluation #k 입력** = `agents/evaluation.py` `evaluate_plan(*, plan, brief, handoff, rules, ..., purpose="evaluate")`의 평가 대상 `plan`과 **코드 검사 결과**(`run_checks_on_dict` 결과). 결과에 남는 값: 마지막 시도에서만 기획안 본문(`result["plans"][i]["plan"]`), 모든 시도의 `checks_passed`·`failed_check_codes`, 마지막 시도에서 기획안 단위의 `unknown_count`·`efficacy_status`.
- **image 입력** = `result["plans"][i]["plan"]["image_brief"]`와, **실제 이미지 모델에 보낸 최종 이미지 프롬프트 문자열**(`api/assembly.py`의 `image_fn`이 `image_prompt(Plan.model_validate(plan))`로 만든 `prompt`, 7d step 3이 `Capture("image-plan", prompt, …)`로 이미 수집한다). 수집분은 `RequestIO.captures`에 있고 목적이 `image`로 시작한다.
- **"소구 방향" 해석(조언 세션 지시문의 표현)**: `agents/planning.py` 시스템 지시(32행)는 "소구 방향은 마케터가 정한 `claim_choice`를 따른다"고 정의한다. 그래서 `claim_choice`를 **`효능 선택`**(= 소구 방향)으로 싣고, `brief`의 `claim`(요청 효능)과 `angle`(소구)도 라벨을 달리해 함께 싣는다(없는 값을 지어내지 않고 결과에 있는 값만).

**설계 결정 (`obs/langfuse_io.py`의 `stage_io(io)`를 확장)**: 반환 형식 `{스팬 이름: {"input"?: ..., "output"?: ...}}`은 그대로다. 아래 입력을 **더하기만** 한다(output 키·supervisor 항목 불변). **허용 키만 골라** 만들고 결과에 없는 키는 건너뛴다(`[]` 직접 접근 금지). 모든 문자열은 sink가 이미 `clip(redact(...))`를 적용한다(4,000자 상한, `(생략됨)`, 키·토큰·Bearer·JWT·base64 가림은 step 3 그대로).
- `research` input = `{"목표": brief.goal, "카테고리": brief.category, "효능": brief.claim, "훅 유형": brief.hook_type, "소구": brief.angle, "형식": brief.format, "피부 고민": brief.skin_concern, "산출 형식": brief.output}`(값이 없는 칸은 빼고, `brief`가 없으면 input 없음).
- `planning #k` input = `{"소구": brief.angle, "요청 효능": brief.claim, "효능 선택": {mode, claims, requested_claim}, "확인된 효능": result.available_efficacy, "근거 소재 수": len(handoff.evidence_ids), "재작업": {"코드 검사 실패": 앞 시도.failed_check_codes, "재검토 항목": 앞 시도.low_items}}`. **`재작업` 칸은 같은 기획안의 두 번째 이후 시도에서만** 넣고 첫 시도에는 없다(실제 입력에 `rework`가 없다). 시도 번호 `k`는 기존 `stage_io`가 쓰는 **모든 기획안의 시도를 이어 센 번호**(`planning #1, #2, …`)와 같다.
- `evaluation #k` input = `{"기획안": 기획안 요약(마지막 시도에서만, 기존 `_plan_summary`), "코드 검사": {"통과": attempt.checks_passed, "실패 코드": attempt.failed_check_codes}, "근거 연결 없음": plan.unknown_count, "효능 상태": plan.efficacy_status}`(**마지막 시도에서만** 기획안·근거 연결 없음·효능 상태를 넣는다: 앞선 시도의 기획안 본문과 기획안 단위 값은 보관하지 않으므로 추측하지 않는다).
- `image` / `image #k` input: 기존 값(문자열 `image_brief`)을 **딕셔너리로 바꾼다**: `{"장면 묘사": image_brief, "이미지 프롬프트": k번째 이미지 수집분의 input 문자열}`. 수집분이 없으면(이미지 비활성·실패·수집 꺼짐) `{"장면 묘사": image_brief}`만. (이 변경은 지시문이 요구한 "image_brief와 최종 이미지 프롬프트"를 만족하기 위한 것이며, 기존 테스트의 기대값 갱신이 필요하다.)
- 끄는 방법·비활성 동작은 step 3 그대로다: `io is None`이거나 `settings.capture_io`가 거짓이면 `stage_io`는 호출되지 않고 batch는 이 step 이전과 **같다**(코드 경로 불변). JSONL `TraceRecord`에는 저장하지 않는다. `rationale`·모델이 쓴 문장·보관하지 않은 이전 시도의 본문은 넣지 않는다.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| 단계 span `input`(research·planning #k·evaluation #k·image) | `obs/langfuse_io.py`(`stage_io`) | `obs/langfuse_sink.py`(`build_timeline`이 span 이름으로 `stage_values`를 붙임, 코드 변경 없음), `tests/test_langfuse_io.py`, `tests/test_langfuse_sink.py`, Langfuse 화면(사용자) |
| 이미지 최종 프롬프트(입력) | `api/assembly.py`(7d step 3이 수집, 코드 변경 없음) | `obs/langfuse_io.py`(`stage_io`가 `io.captures`에서 읽음) |

**기존 단언과의 충돌 점검(`rg -n "stage_io" tests`와 읽기로 확인)**: `tests/test_langfuse_io.py`의 `test_allowlisted_projections_and_final_attempt_only`(약 156~210행)가 **정확 일치**를 단언한다 → 새 `input`이 생기는 항목의 **기대값만 갱신**한다(`==` 유지, 부분 비교로 바꾸지 않음): `stages["research"] == {"output": {...}}`는 `{"input": {...}, "output": {...}}`로, `stages["planning #2"] == stages["planning #3"] == {"output": summary}`는 시도별 `input`이 달라지므로 각각 `{"input": ..., "output": summary}`로 따로 단언, `stages["image"] == {"input": "합성 장면"}`는 `{"input": {"장면 묘사": "합성 장면"}}`(수집분 없는 합성 입력)로, `evaluation #k`의 `{"output": {...}}`는 `{"input": {...}, "output": {...}}`로. `stages["supervisor"]`는 **불변**이다. `test_missing_result_fields_are_skipped`의 `stage_io(io) == {}`(결과·브리프·핸드오프가 없으면 빈 딕셔너리)는 **그대로 통과해야 한다**(입력도 값이 없으면 만들지 않는다). 합성 입력의 비밀 값 검사(`"SYNTHETIC_NOT_ALLOWED"`·`"rationale"`·`"unknown"`이 직렬화에 없음)는 불변. `tests/test_langfuse_sink.py`·`tests/test_api_assembly.py`의 기존 단언은 불변이어야 한다(`io=None`이면 batch 동일, 수집기 꺼짐 경로 동일). **해시 시드·집합·딕셔너리 순회 순서에 기대는 새 단언을 만들지 않는다**(리스트와 명시적 순서로 단언, 7b step 4가 같은 원인으로 blocked됐다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`(CRITICAL: 비밀 값·키를 trace·로그에 남기지 않는다), `/docs/ADR.md`(ADR-016)
- `/src/beautyads/obs/langfuse_io.py`(`stage_io`·`_plan_summary`·`_select`·`_mapping`·`_rows`), `/src/beautyads/obs/langfuse_sink.py`(`build_timeline`의 `stage_values`·`captures` 사용 부분, 읽기 전용)
- `/src/beautyads/agents/supervisor.py`(결과 키: `brief`·`handoff`·`claim_choice`·`available_efficacy`·`plans`, 읽기 전용), `/src/beautyads/agents/planning.py`(`make_plan`의 `payload`와 `rework`, 읽기 전용), `/src/beautyads/agents/evaluation.py`(`evaluate_plan`의 `payload`, 읽기 전용), `/src/beautyads/agents/plan_eval.py`(시도 dict의 키, 읽기 전용), `/src/beautyads/agents/research.py`(`run_research`의 brief, 읽기 전용), `/src/beautyads/domain/research.py`(`ResearchBrief`)
- `/src/beautyads/api/assembly.py`(이미지 호출 수집부 `_capture(captures, "image-plan", prompt, …)`, 읽기 전용)
- `/tests/test_langfuse_io.py`(`synthetic_io`와 `stage_io` 단언 전체), `/tests/test_langfuse_sink.py`(`io`가 있을 때 입력·출력 부착 테스트)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/obs/langfuse_io.py`, `tests/test_langfuse_io.py`, `tests/test_langfuse_sink.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `src/beautyads/obs/langfuse_io.py`, `tests/test_langfuse_io.py`, `tests/test_langfuse_sink.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1. `obs/langfuse_io.py`**: 위 "설계 결정"대로 `stage_io`에 입력을 더한다. 각 입력을 만드는 작은 순수 함수를 둬도 된다(같은 파일 안). `Capture`·`RequestIO`·`redact`·`clip`·`match_captures`·`trace_input`·`trace_output`의 시그니처와 동작은 바꾸지 않는다. `obs/langfuse_sink.py`·`api/assembly.py`는 수정하지 않는다(span 이름으로 `stage_values`를 붙이는 기존 코드가 `input` 키를 이미 다룬다. 그렇지 않다면 `blocked`로 보고한다).

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `tests/test_langfuse_io.py`(위 기대값 갱신 + 케이스 추가): (1) `research` input이 `brief`의 `goal`·`category`·`claim`·`hook_type`·`angle`·`format`·`skin_concern`·`output`을 한국어 라벨로 담고 값이 없는 칸은 없다, `brief`가 없으면 `research`에 input이 없다. (2) `planning #k` input: 첫 시도에는 `재작업`이 **없고** 같은 기획안의 두 번째 시도에는 **앞 시도의** `failed_check_codes`·`low_items`가 `재작업`으로 들어간다(다른 기획안의 첫 시도에는 다시 없다), `효능 선택`이 `mode`·`claims`·`requested_claim`만(합성 `unknown` 칸이 없다), `확인된 효능`·`근거 소재 수`가 결과 값에서 온다, `profile`·`feedback`·`forbidden_terms`가 어디에도 없다. (3) `evaluation #k` input: 모든 시도에 `코드 검사`(`통과`·`실패 코드`)가 있고 **마지막 시도에만** `기획안`·`근거 연결 없음`·`효능 상태`가 있다(앞선 시도의 본문을 추측해 채우지 않음). (4) `image`/`image #k` input이 `{"장면 묘사": ..., "이미지 프롬프트": ...}`이고 k번째 이미지 수집분(`purpose`가 `image`로 시작)의 input을 쓴다, 수집분이 없으면 `장면 묘사`만, 일반 모델 호출 수집분(`supervisor`·`research`·`plan`·`evaluate` 목적)은 섞이지 않는다. (5) 합성 비밀·`rationale`·알 수 없는 키가 모든 입력 직렬화에 없다(기존 단언 유지·확장). (6) `supervisor` 항목·모든 `output` 키와 값이 이 step 이전과 **같다**. (7) 결과가 비어 있으면 `stage_io(io) == {}`.
- `tests/test_langfuse_sink.py`(케이스 추가, 기존 단언 불변): (8) `io`가 있고 `capture_io`일 때 합성 기록의 `research`·`planning #1`·`evaluation #1`·`image` span 본문에 `input`이 붙고 모든 문자열이 4,000자 이하이며 합성 비밀이 batch 어디에도 없다, (9) `io=None`이거나 `capture_io`가 거짓이면 span에 `input`이 없다(batch가 이 step 이전과 같다, 기존 단언 유지).
- 합성 값만 쓴다(모델 출력 값을 기대값으로 굳히지 않는다). **집합·딕셔너리 순회 순서·해시 시드에 의존하는 단언을 만들지 마라.**

## Acceptance Criteria

```bash
make verify   # lint + pytest + pnpm lint·typecheck·test 통과
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

- `llm/`·`agents/`·`obs/trace.py`·`obs/ledger.py`·`obs/langfuse_sink.py`·`api/assembly.py`·`settings.py`를 수정하지 마라. 로컬 JSONL `TraceRecord`에 입력·출력·메시지를 넣지 마라. 이유: 입력은 결과·수집분에서 `stage_io`가 만들어 sink로 직접 넘기는 기존 방식(step 3) 그대로이고, JSONL의 "메시지·모델 문장·키 없음" 규칙과 동결 호출 경로는 불변이다.
- 에이전트가 받지 않은 값을 지어내거나 추측해 채우지 마라(앞선 시도의 기획안 본문, 이전 시도의 `rationale`, `profile`·`feedback`·`raw_tool_outputs`·`forbidden_terms` 포함). 결과에 없는 키는 건너뛴다(`[]` 직접 접근 금지). 이유: 보관하지 않은 데이터는 지어내지 않고(FP-C03, AGENTS.md), `profile`·`feedback`에는 테넌트 전용 값이 있다(ADR-009).
- 단계 span의 `output` 키·값, `supervisor`·`ask`의 입출력, 라벨 체계(기존 한국어 키)를 바꾸지 마라. 이유: 이미 live로 확인된 화면이다(승인 지시: 이미 채운 입출력은 바꾸지 않는다).
- API 키·`.env` 값·인증 헤더·토큰·base64 이미지를 입력에 싣거나 로그·예외·반환에 남기지 마라(`redact`는 sink가 모든 문자열에 이미 적용한다. 이 step이 그 적용을 우회하는 경로를 만들지 마라). 이유: 비밀 값은 어디에도 남기지 않는다(AGENTS.md CRITICAL, B-FP-072).
- `make obs-up`·`make obs-check`·`uv run python -m beautyads.obs.langfuse_check`·`docker compose --profile obs up`을 실행하지 마라. 기존 단언을 약화·삭제하지 마라(위 "기존 단언과의 충돌 점검"의 기대값 갱신만 허용, `==` 유지). 이유: 실제 서비스 접속은 사용자가 하고(A-FP-040), 가드를 약화하면 회귀를 못 잡는다.
