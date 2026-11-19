# Step 28: evaluation-model

## 설계 검토 기록

**배경(사용자 결정, 조언 세션 승인)**: 최종 E2·E5의 Supervisor 팔과 끔 팔은 루프 내 평가를 정식 구성인 `claude-sonnet-5-5`로 돌린다. 현재 `e2e5_live`는 `assemble` 호출에 `evaluation_model`을 지정하지 않아 `api/assembly.py`의 기본값 `claude-haiku-5-5`가 쓰인다(스모크용). dev 모드는 haiku를 유지한다. 이 평가 모델을 사전 등록 동결 줄과 문장 25번째에 기록한다. **이 step이 사전 등록 전 마지막 코드 변경이다. `data/evalset/`·동결 프롬프트·상수·기존 문장 24개는 건드리지 않는다.**

**식별자 전수 대조(현재 코드, 모두 열어 확인)**
- `api/assembly.py`: `assemble_full(..., evaluation_model="claude-haiku-5-5", trace_path=None)`(`:129` 기본값), `if evaluation_model not in {"claude-haiku-5-5", "claude-sonnet-5-5"}: raise ValueError("EVALUATION_MODEL_INVALID")`(`:137`), `evaluate_fn`이 `structured(evaluation_model)`·`evaluate_plan(..., model=evaluation_model)`로 쓴다(`:368-376`). **이 파일은 수정하지 않는다**(sonnet은 이미 허용).
- `eval/e2e5_live.py`: `_SCORING_MODEL = "claude-sonnet-5-5"`(`:82`), `_extra_frozen()`(`:107-113`, 키 `동결 단일 에이전트 프롬프트 sha256`·`동결 E2 채점 루브릭 sha256`), `assemble` 호출은 두 곳이다. **`_run_batch` 안의 `assembly = await assemble(settings=..., group="dev" if args.mode == "dev" else "test", limits=limits, environ=..., env_file=..., models={...})`(`:552`)가 Supervisor·끔 팔의 평가를 실행하는 유일한 호출이다**(한 `assembly`를 두 팔이 공유). `:1090`은 `sheet()` 안의 `assemble(settings=..., group=split, limits=RequestLimits(), ...)`로 `assembly.hydrate`만 쓰며 평가를 실행하지 않으므로 **바꾸지 않는다.** `_record(item, arm, result, *, run_id, identity, set_hash, delta, by_purpose, latency, repeat=1)`(`:461`)는 `versions = dict(result.get("prompt_versions") or {})`에서 시작해 `arm != "single"`이면 `versions["supervisor"] = SUPERVISOR_PROMPT_VERSION`, `arm == "single"`이면 `versions = {"single": ...}`로 `prompt_versions`를 만들고, `_run_batch`의 호출부(`:615`)가 유일한 실호출부다. `_RecordedArm.prompt_versions: dict[str, str]`.
- `eval/isolation_live.py:525`의 `assemble(group="isolation", limits=RequestLimits(max_plans=1, max_reworks=0), ...)`는 `evaluation_model`을 지정하지 않아 haiku다. **이 step은 수정하지 않는다**(25번째 문장이 격리는 haiku라고 적는다. 격리는 표식 노출만 보므로 해석에 영향이 없다).
- `eval/prereg.py`: `REQUIRED_SENTENCES`(`:221`부터 튜플, 현재 24개), 렌더링은 `*(f"{i}. {sentence}\n" for i, sentence in enumerate(REQUIRED_SENTENCES, 1))`(`:460`), `main`이 `extra={**e2e5_live._extra_frozen(), **e3_live.extra_frozen(embedding)}`(`:646`)로 동결 줄을 만든다(그래서 `_extra_frozen()`에 키를 추가하면 렌더링과 `check_run` 비교에 자동 반영된다). 동결 줄·문장 렌더링에서 `:`가 든 줄은 `parse_preregistration`이 라벨로 읽는다(새 문장에 `:`를 넣지 않는다).
- `eval/freeze_guard.py`: 수정하지 않는다. `check_run`은 `extra` 키를 점검 라벨과 `strict_labels`에 자동 포함한다(step 27).

**문장 대 코드 대조**: 25번째 문장이 말하는 모델은 코드와 일치한다 — 기획 `structured("gpt-6.1-terra")`(`api/assembly.py:361-363`, `reasoning_effort low`는 `docs`·기존 문장 2번의 서술), Supervisor의 요청 해석·리서치는 `gpt-6-luna`(이 문장은 사전 등록 문서의 설명이며 코드 변경 대상이 아니다. 새 단언은 평가 모델만 코드로 검사한다), 루프 내 평가는 `evaluation_model`(이 step), 격리는 기본 haiku(`isolation_live.py:525`가 지정 안 함). 기존 문장 2번 "두 팔은 생성 모델(gpt-6.1-terra, reasoning_effort low) ... 이 같다"는 **수정하지 않고** 25번째 문장이 해석을 덧붙인다.

**테스트 해시 고정·개수 단언 전수 목록(`tests/test_prereg.py`, 열어 확인)**
- 불변: `test_first_seventeen_procedures_remain_byte_identical`(`:130`, `REQUIRED_SENTENCES[:17]`), `test_failure_as_worst_procedure_is_nineteenth`(`:137`, `[:18]`, 해시 `:160-162`), `test_first_twenty_three_procedures_remain_byte_identical`(`:916`, `[:23]`). 새 문장은 끝에 붙으므로 이 해시들은 그대로다.
- **갱신**: `test_none_measurement_preserves_original_bytes`(`:562-568`)의 렌더링 전체 sha256 — 동결 줄(평가 모델)과 25번째 문장이 렌더링에 더해져 바이트가 바뀐다. 새 해시를 구현 뒤 실제 렌더링에서 계산해 고정하고 "이 step에서 동결 줄과 25번째 문장 추가로 갱신" 주석을 단다.
- **갱신**: 문장 수 단언 `:42`(`== 24` → `25`)와 `:817`(`len(sentences) == 24` → `25`).
- **추가**: `REQUIRED_SENTENCES[:24]`를 `json.dumps(..., ensure_ascii=False)`의 sha256으로 고정하는 테스트(기존 `:916` 패턴). 25번째 문장 단언 테스트(`:891-913` 패턴: 핵심 구절 포함, `f"25. {sentence}\n"`이 렌더링에 있음).
- **확인**: 고정 길이 언패킹·슬라이스 `REQUIRED_SENTENCES[21:23]`(`:860`)·`[23]`(`:891`)·`[20]`·`[15]`·`[16]`·`[17]`·`[18]`·`[14]`는 인덱스가 그대로라 불변이다. `:336`·`:347`은 모든 문장이 출력에 있는지만 본다(불변). 동결 줄 레이블 단언(`:870-885` 해석 라벨)은 별도로 새 라벨 단언을 추가한다. `tests/test_freeze_guard.py`·`tests/test_e3_live.py`·`tests/test_isolation_live.py`는 `_extra_frozen()`을 쓰지 않는다(grep 확인).
- `tests/test_e2e5_live.py`: `rig`의 가짜 `assemble(**kw)`(`:83`)가 `state.assemblies.append(kw)`로 호출 인자를 모은다(새 단언에 쓴다). `test_record_supervisor_version_does_not_mutate_results`(`:1472-1495`)는 `_record`를 새 인자 없이 호출하므로 `prompt_versions`가 기존과 같아야 한다(**새 인자의 기본값 `None`이면 키를 넣지 않는다**).

`tests/test_e3_live.py`는 `prereg.validate_dev_measurement`만 쓰므로 영향이 없다(소비자 테스트 경고 확인).

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건(합성 테스트만).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 동결된 기준은 결과를 본 뒤 바꾸지 않는다, 결과를 내기 전에 사전 등록 파일을 커밋한다
- `/src/beautyads/eval/e2e5_live.py`(`_SCORING_MODEL`·`_extra_frozen`·`_record`·`_run_batch`의 `assemble` 호출), `/src/beautyads/eval/prereg.py`(`REQUIRED_SENTENCES`·렌더링·`main`), `/src/beautyads/api/assembly.py`(`:120-140`·`:355-380`, 읽기 전용), `/src/beautyads/eval/isolation_live.py`(`:520-535`, 읽기 전용)
- `/tests/test_e2e5_live.py`(`rig`·`:1472-1495`), `/tests/test_prereg.py`(전체, 위 해시 고정 위치)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/e2e5_live.py`, `src/beautyads/eval/prereg.py`, `tests/test_e2e5_live.py`, `tests/test_prereg.py`

열람 금지 경로: `data/interim/`, `data/evalset/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로 `data/interim/e2e5/`)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `src/beautyads/eval/e2e5_live.py`, `src/beautyads/eval/prereg.py`, `tests/test_e2e5_live.py`, `tests/test_prereg.py`

**모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: `_EVALUATION_MODEL`, `evaluation_model`(`_record`의 키워드 인자), `"동결 Supervisor 루프 내 평가 모델"`

**1. final에서 평가 모델 지정(`eval/e2e5_live.py`)**
- 모듈 상수 `_EVALUATION_MODEL = "claude-sonnet-5-5"`를 `_SCORING_MODEL` 바로 아래에 둔다.
- `_run_batch`의 `assemble(...)` 호출(`:552`)에 `evaluation_model="claude-haiku-5-5" if args.mode == "dev" else _EVALUATION_MODEL`을 추가한다(다른 인자 불변). `sheet()`의 호출(`:1090`)과 그 밖의 코드는 바꾸지 않는다.
- `_record`에 키워드 인자 `evaluation_model=None`을 추가한다. 값이 `None`이 아니고 `arm != "single"`이면 `versions["evaluation_model"] = evaluation_model`을 넣는다(단일 팔과 `None`이면 넣지 않아 기존 기록·테스트가 그대로다). `_run_batch`의 `_record(...)` 호출(`:615`)에 같은 `evaluation_model` 값을 넘긴다(`assemble`에 준 값과 같은 변수 하나를 쓴다).
- `_extra_frozen()`에 `"동결 Supervisor 루프 내 평가 모델": _EVALUATION_MODEL`을 기존 두 키 뒤에 추가한다.

**2. 25번째 문장(`eval/prereg.py`)**: `REQUIRED_SENTENCES` 튜플 끝에 아래 문장을 **그대로**(한 글자도 바꾸지 말고, `:`를 넣지 말고) 추가한다. 기존 24개는 수정하지 않는다.

> 문장 2의 "생성 모델이 같다"는 기획 생성 모델(gpt-6.1-terra, reasoning_effort low)과 도구 집합·한도를 뜻한다. Supervisor의 요청 해석·리서치는 gpt-6-luna, 루프 내 평가는 claude-sonnet-5-5(최종 실행)이고 단일 팔의 도구 루프와 기획은 gpt-6.1-terra(reasoning_effort low) 하나다. 격리 실험은 표식 노출만 보므로 루프 내 평가 모델은 claude-haiku-5-5를 쓴다(결과 해석에 영향 없음).

(문장 안의 따옴표는 파이썬 문자열 이스케이프에 맞게 쓴다. 문장에 줄바꿈을 넣지 않는다.)

**테스트(합성 데이터·`tmp_path`, 모델·접속 없음)**
- `tests/test_e2e5_live.py`: (1) final 모드 실행에서 가짜 `assemble`이 받은 kwargs의 `evaluation_model == "claude-sonnet-5-5"`이고, dev 모드에서는 `"claude-haiku-5-5"`다(`rig`의 `state.assemblies`로 확인). (2) 같은 실행에서 `assemble` 호출이 한 번이라 Supervisor 팔과 끔 팔이 같은 `assembly`(같은 평가 모델)를 쓴다는 것을 두 팔이 모두 기록되는 실행으로 확인하고, 두 팔 기록의 `prompt_versions["evaluation_model"]`이 같다. (3) 단일 팔 기록의 `prompt_versions`에는 `evaluation_model` 키가 없다. (4) `_record`를 `evaluation_model` 없이 부르면 `prompt_versions`가 기존과 같다(기존 `:1472` 테스트 유지). (5) `_extra_frozen()`에 새 키가 있고 값이 `claude-sonnet-5-5`다. (6) `sheet` 흐름(`assemble`에 `evaluation_model`을 주지 않음)이 불변이다.
- `tests/test_prereg.py`: 위 "해시 고정·개수 단언 전수 목록"의 갱신·추가를 모두 한다. 추가로 (7) 렌더링한 사전 등록에서 `guard.parse_preregistration(rendered)["동결 Supervisor 루프 내 평가 모델"] == "claude-sonnet-5-5"`이고 `check_run`이 정상 문서에서 통과하며, 그 줄의 값을 바꾸거나 줄을 지운 문서에서는 `FROZEN_VALUE_MISMATCH`다(기존 `check_run` 테스트 패턴 사용).
- 합성 문장·분류 값을 기대값으로 굳히지 않는다(형식·코드·상수 값만 검사).

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

- 기존 사전 등록 문장 24개(`REQUIRED_SENTENCES[:24]`)·`frozen_values()`의 값·판정 로직·판정 임계값·동결 프롬프트(기획·평가·해석)를 바꾸지 마라. 이유: 이 step은 평가 모델 지정과 25번째 문장·동결 줄 추가만 한다.
- `data/evalset/`를 열거나 수정하지 마라. 이유: 확정 세트이며 세트 해시가 사전 등록에 들어간다.
- `api/assembly.py`·`eval/freeze_guard.py`·`eval/isolation_live.py`·`eval/e2_scoring.py`·`eval/e3_live.py`·`llm/`·`agents/`를 수정하거나 새 의존성을 추가하지 마라. 이유: 허용 범위 밖이다(필요하면 `blocked`로 보고).
- `:1090`(`sheet()`)의 `assemble` 호출과 dev 모드의 평가 모델(haiku)을 바꾸지 마라. 이유: 평가가 일어나지 않는 호출이고 dev는 스모크용이다.
- `run.json` 메타데이터에 평가 모델을 추가하거나 재개 불일치 검사를 만들지 마라. 이유: 코드 상수가 바뀌면 `code_commit`이 달라져 기존 `RUN_IDENTITY_MISMATCH`가 이미 막는다.
- 25번째 문장에 `:`를 넣거나 문구를 바꾸지 마라. 이유: `:`가 든 줄은 `parse_preregistration`이 라벨로 읽고 문구는 승인된 그대로다.
- 기존 테스트의 단언을 약화하지 마라(위 목록의 문장 수 `24→25`와 렌더링 전체 해시 갱신만 허용). 이유: 이미 통과한 step의 계약이며 변경은 의도된 동작 변경에만 한정한다.
