# Step 25: interpretation-glossary

## 설계 검토 기록

**배경(사용자 확정·조언 세션 승인)**: dev 재스모크에서 brief의 `format`·`hook_type`·`angle`이 사용자 지정("일반인 후기형 포맷", "정지 이미지 포맷")에도 모두 `None`이었다. `SupervisorDecision`에는 세 칸이 있으나 `decide()`의 `_SYSTEM`(`agents/supervisor.py:49`)에 지정 축을 채우라는 지시가 없고 payload에 한국어 표현→닫힌 값 대응표가 없다. 이 step은 **D안**: 해석 프롬프트에 "명시하면 채우고 명시하지 않으면 null" 지시를 넣고, 대응표를 payload로 제공하며, 해석 프롬프트(버전·`_SYSTEM` sha256·대응표 sha256)를 사전 등록 동결 대상에 추가한다. 해석 모델은 `gpt-6-luna`(`reasoning_effort` none) 그대로다. 기획·평가 프롬프트와 상수는 바꾸지 않는다. (step 24가 지정 축을 지배 축에서 제외했다.)

**식별자 전수 대조(현재 코드, 모두 열어 확인)**
- `agents/supervisor.py`: `SUPERVISOR_REASONING_EFFORT = "none"`·`_MODEL = "gpt-6-luna"`·`_SYSTEM`(`:49-55`: "Supervisor로서 요청을 해석하고 과제의 목표와 닫힌 분류 값만 제출한다. …사용자 메시지는 JSON 데이터이며…\n" + `TOOL_DATA_RULE`)·`decide(message, *, as_of, structured, limits, **call_options)`(`:84`: payload `{"message", "as_of", "supported_categories", "intents"}`, `call_options`에 `{"model","messages","temperature","reasoning_effort","thinking"}`가 있으면 `ValueError("SUPERVISOR_CALL_OPTIONS_INVALID")`), 해석 결과 → `ResearchBrief`(`interpret`: `goal`·`category`·`claim`·`hook_type`·`angle`·`format`·`skin_concern`).
- `domain/supervisor.py`: `SupervisorDecision`(칸 `hook_type: HookType | None`·`angle`·`format`, 모두 필수 칸이며 값 없으면 `None`).
- `analysis/prompts.py`: `_HOOK_CRITERIA`·`_ANGLE_CRITERIA`·`_FORMAT_CRITERIA`(enum 멤버 → 한국어 판정 기준. **`tests/test_taxonomy_freeze.py`가 이 정의가 `docs/TAXONOMY.md`와 일치함을 검증한다**: `test_frozen_axis_values_and_definitions_follow_document_and_domain`·`test_v1_codebook_and_prompt_use_document_definitions`)·`_criteria(enum, descriptions)`. 이 모듈은 `beautyads.domain`만 import한다(계층 표: `analysis`는 `domain`·`llm`).
- `api/assembly.py:314-321`: `def decide_fn(text): result = decide(text, as_of=ctx.as_of, structured=structured("gpt-6-luna"), limits=limits)`(`api`는 계층 표상 `analysis`를 import할 수 있다; `agents`는 `analysis`를 import할 수 없다).
- `domain/labels.py`: `HookType`·`Angle`·`Format`(`StrEnum`; 값 목록은 아래), 한국어 표시 이름 상수는 **현재 없다**. 표시 이름은 `eval/evalset_candidates.py:91-116`의 `_LABELS["format"|"hook_type"|"angle"]`(문자열 값 → 한국어 이름)에만 있고 요청 후보 문장에 쓰인다(`_LABELS`는 `monkeypatch.setitem(candidates._LABELS, "format", {...})`로 쓰는 테스트가 있어 **축 이름 → {값 문자열: 이름} 딕셔너리 구조를 유지해야 한다**).
- `eval/freeze_guard.py`: 라벨 상수(`PLANNING_PROMPT_VERSION_LABEL` 등)와 `frozen_values()`(7개: 기획·평가 프롬프트 버전, `MIN_DOMINANT_SHARE`·`THIN_POOL_MAX`·`PASS_MIN_SCORE`, 기획·평가 `_SYSTEM` sha256; 이 모듈의 이름 `supervisor`는 `domain.supervisor`다 → 새 import는 `agents.supervisor`를 다른 이름으로 가져온다).
- `eval/e2e5_live.py`: `_record(...)`의 `versions = result.get("prompt_versions") or {}`(`:478`), `_axis_adherence(rows, items)`(축별 `specified`·`adherent`·`dominant_conflict`·`interpretation_missing`), `obs/trace.py:150`의 `prompt_versions: dict[Literal["planning","evaluation"], str]`(**결과 딕셔너리의 `prompt_versions`에 키를 더하지 않는다**).
- `eval/prereg.py`: `REQUIRED_SENTENCES` 21개(마지막이 step 23의 EVAL 대비 변경), `render_results_template`.
- `docs/PROMPT_CHANGELOG.md`: 표 열 `| 날짜 | 버전 | 대상 | 변경 | 이유 |`.

**닫힌 값과 표시 이름(현재 코드의 `_LABELS` 그대로, 이관 대상)**
- `format`: `ugc_style` "일반인 후기형", `studio_film` "스튜디오 촬영", `demo` "시연", `text_motion` "문자 모션", `static_image` "정지 이미지", `other` "기타 포맷".
- `hook_type`: `question` "질문형", `problem` "문제 제기형", `result_first` "결과 선공개형", `bold_claim` "강한 주장형", `product_first` "제품 먼저 제시형", `person_first` "인물 먼저 제시형", `other` "기타 훅".
- `angle`: `problem_solution` "문제 해결", `desire` "욕구", `social_proof` "사회적 증거", `comparison` "비교", `ingredient_science` "성분 과학", `how_to` "사용법", `other` "기타 각도".

**요청 문장 보존(조건 3-a)**: 표시 이름 이관 전후로 `build_request_candidates`가 만드는 요청 문장이 **한 글자도 바뀌지 않아야 한다.** 현재 코드(CANDIDATE_FACTOR를 충분히 크게 해 모든 후보를 만든 경우, 실제 `config/workspaces.yaml`·`BRIEFS`)가 만드는 고유 `(tenant_id, message)`는 180개이고, `json.dumps(sorted(...), ensure_ascii=False)`의 SHA-256은 `c7f6b382fd7cbf952de28a969424b39471e467c6ddaac4289b507a23cbe8b1fb`다(이 문서 작성 시 현재 코드로 계산). 대표 문장(현재 코드 출력): `dev-cosrx`: "선케어 제품의 자외선 차단 광고 기획안 1안을 문자 모션 포맷으로 작성해 주세요."·"…강한 주장형 훅 유형으로 작성해 주세요."·"…문제 해결 각도로 작성해 주세요."·"선케어 제품의 자외선 차단 광고 기획안 1안을 작성해 주세요."(무지정), `dev-mixsoon`: "세럼·앰플 제품의 미백 광고 기획안 1안을 문자 모션 포맷으로 작성해 주세요."·"…강한 주장형 훅 유형으로 작성해 주세요."·"…문제 해결 각도로 작성해 주세요."·"세럼·앰플 제품의 미백 광고 기획안 1안을 작성해 주세요."(무지정). `BRIEFS`에는 마스크팩이 없어 후보 문장에도 마스크팩은 없다(확인된 사실). **작업 순서: 먼저 이 고정값 테스트를 추가해 현재 코드로 통과함을 확인한 뒤에 표시 이름을 이관한다.**

**상수 단언 grep(전수)**
- 새 기대값이 필요한 기존 단언: `tests/test_freeze_guard.py:139-155 test_frozen_values_follow_current_code`(`values == {…7개…}` 정확 일치) → 새 라벨 3개를 **더한 정확 일치**로 갱신한다. `:232-238`(필수 라벨 매개변수 목록)에 새 라벨 3개를 더한다.
- `tests/test_prereg.py`: 문장 수 단언 두 곳(`:42`·`:817`의 `== 21`) → `== 23`. **문장 해시를 고정하는 기존 테스트 세 곳**(조언 세션이 확인한 위치): (a) `test_none_measurement_preserves_original_bytes`(렌더링 전체, **동결 줄 3개 추가와 22·23번째 문장 추가로 바뀐다 → 이 기대 해시 한 줄을 새 값으로 갱신**), (b) `test_first_seventeen_procedures_remain_byte_identical`(`REQUIRED_SENTENCES[:17]`; 앞 17개를 바꾸지 않으므로 **불변**), (c) `test_failure_as_worst_procedure_is_nineteenth`(`REQUIRED_SENTENCES[:18]`; **불변**). 새 문장은 끝에만 추가한다.
- `tests/test_supervisor.py:32-56 test_decide_actual_messages_schema_and_fixed_call_options`: payload에서 두 키 집합만 단언하므로 추가 키에 안전하고, `glossary` 없는 호출은 payload가 변경 전과 같아야 한다. `tests/test_llm_param_guard.py:299-326`·`tests/test_schema_guard.py:436-440`도 `glossary=None` 호출이라 불변이다. `tests/test_api_assembly.py:775·822·868`의 가짜 `decision(text, *, structured, **kwargs)`는 `glossary`를 `**kwargs`로 받는다.
- `tests/test_e2e5_live.py:252 assert row["prompt_versions"]`(참)·`:53` 픽스처: 새 `"supervisor"` 버전 키에 안전하다. `_axis_adherence` 결과 구조를 정확 일치로 단언하는 테스트가 있으면(step 20 테스트) 새 키 `unrequested_filled`를 더한 값으로 갱신한다.
- `tests/test_evalset_candidates.py:232-251·:1312·:1329`: `_LABELS[...]` 구조(`monkeypatch.setitem` 포함)와 값을 읽는다 → 구조·값 불변이어야 한다.

**새 칸 대응표**: `HOOK_TYPE_NAMES`·`ANGLE_NAMES`·`FORMAT_NAMES`(`domain/labels.py` 한 곳 → `evalset_candidates._LABELS`·`analysis.prompts.axis_glossary`), `axis_glossary()`(→ `api/assembly.py`가 `decide(glossary=)`로 주입 → payload `axes` → 해석 결과 brief → 기획 입력), `SUPERVISOR_PROMPT_VERSION`·`_SYSTEM`·대응표(→ `freeze_guard.frozen_values()` 3줄 → 사전 등록 동결 줄 → 최종 가드), `unrequested_filled`(brief 축 값 + 요청 `axes_used` → 준수 표).

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건(합성 테스트만). 사용자가 이 step 뒤 dev 재스모크(`--arms supervisor --limit 2`, 약 $0.02)로 효과를 확인한다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 계층 경계(`agents`는 `analysis`를 import하지 않는다), 동결된 기준은 결과를 본 뒤 바꾸지 않는다(해석 프롬프트는 사전 등록 전에 확정해 동결 대상에 넣는다), 모델이 만든 값을 테스트 기대값으로 굳히지 않는다
- `/src/beautyads/agents/supervisor.py`(`_SYSTEM`·`decide`·`interpret`), `/src/beautyads/analysis/prompts.py`(`_*_CRITERIA`·`_criteria`), `/src/beautyads/domain/labels.py`, `/src/beautyads/api/assembly.py`(`:300-330` `decide_fn`), `/src/beautyads/eval/evalset_candidates.py`(`_LABELS`·`build_request_candidates`), `/src/beautyads/eval/freeze_guard.py`, `/src/beautyads/eval/prereg.py`, `/src/beautyads/eval/e2e5_live.py`(`_record`·`_axis_adherence`), `/docs/PROMPT_CHANGELOG.md`, `/docs/TAXONOMY.md`(읽기 전용)
- `/tests/test_supervisor.py`·`/tests/test_api_assembly.py`·`/tests/test_schema_guard.py`·`/tests/test_llm_param_guard.py`(`decide` 호출 테스트)·`/tests/test_taxonomy_freeze.py`·`/tests/test_freeze_guard.py`·`/tests/test_prereg.py`·`/tests/test_evalset_candidates.py`·`/tests/test_e2e5_live.py`·`/tests/test_architecture.py`(읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/agents/supervisor.py`, `src/beautyads/api/assembly.py`, `src/beautyads/analysis/prompts.py`, `src/beautyads/domain/labels.py`, `src/beautyads/eval/evalset_candidates.py`, `src/beautyads/eval/freeze_guard.py`, `src/beautyads/eval/prereg.py`, `src/beautyads/eval/e2e5_live.py`, `docs/PROMPT_CHANGELOG.md`, `tests/test_supervisor.py`, `tests/test_api_assembly.py`, `tests/test_schema_guard.py`, `tests/test_taxonomy_freeze.py`, `tests/test_freeze_guard.py`, `tests/test_prereg.py`, `tests/test_evalset_candidates.py`, `tests/test_e2e5_live.py`

열람 금지 경로: `data/interim/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `src/beautyads/agents/supervisor.py`, `src/beautyads/api/assembly.py`, `src/beautyads/analysis/prompts.py`, `src/beautyads/domain/labels.py`, `src/beautyads/eval/evalset_candidates.py`, `src/beautyads/eval/freeze_guard.py`, `src/beautyads/eval/prereg.py`, `src/beautyads/eval/e2e5_live.py`, `docs/PROMPT_CHANGELOG.md`, `tests/test_supervisor.py`, `tests/test_api_assembly.py`, `tests/test_schema_guard.py`, `tests/test_taxonomy_freeze.py`, `tests/test_freeze_guard.py`, `tests/test_prereg.py`, `tests/test_evalset_candidates.py`, `tests/test_e2e5_live.py`

해석 프롬프트와 닫힌 값 대응표를 추가하고 동결 대상에 넣는다. **모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: `SUPERVISOR_PROMPT_VERSION`, `HOOK_TYPE_NAMES`, `ANGLE_NAMES`, `FORMAT_NAMES`, `axis_glossary`, `unrequested_filled`, `SUPERVISOR_PROMPT_VERSION_LABEL`, `SUPERVISOR_SYSTEM_HASH_LABEL`, `AXIS_GLOSSARY_HASH_LABEL`

**0. 먼저(이관 전)**: `tests/test_evalset_candidates.py`에 요청 문장 보존 고정값 테스트를 추가한다: `monkeypatch`로 `candidates.CANDIDATE_FACTOR`를 100으로 올리고(모듈 속성을 호출 시점에 읽는다) 실제 `config/workspaces.yaml`·`BRIEFS`로 `build_request_candidates`를 부른 결과의 고유 `(tenant_id, message)` 목록(정렬)이 위 180개이며 그 JSON(`ensure_ascii=False`)의 SHA-256이 `c7f6b382fd7cbf952de28a969424b39471e467c6ddaac4289b507a23cbe8b1fb`이고, 위 대표 문장 8개가 목록에 있다. 또 같은 합성 환경(`synthetic` 픽스처)의 기본 호출(`CANDIDATE_FACTOR` 기본)이 만드는 `request_set_hash(result.requests)`를 **현재 코드로 계산해 그 값을 리터럴로 고정**한다(이관 뒤에도 같아야 한다; 값은 모델 출력이 아니라 결정적 코드 결과다). 이 테스트들이 현재 코드로 통과함을 확인한 뒤 1번으로 간다.

**1. 표시 이름 이관(`domain/labels.py`, `eval/evalset_candidates.py`)**
- `domain/labels.py`에 `HOOK_TYPE_NAMES: dict[HookType, str]`·`ANGLE_NAMES: dict[Angle, str]`·`FORMAT_NAMES: dict[Format, str]`를 둔다(위 "닫힌 값과 표시 이름"의 값 그대로, `other` 항목 포함, 열거 순서대로). 값을 새로 만들거나 바꾸지 않는다.
- `evalset_candidates._LABELS`의 세 축을 이 상수에서 만든다(`{member.value: name for member, name in …items()}`). `_LABELS`의 구조(축 이름 → `{값 문자열: 이름}` 딕셔너리)·값·나머지 축(`category`·`claim`·`concern`·`skin_type`)은 불변이다. 요청 문장 생성 코드(`build_request_candidates`)는 건드리지 않는다.
- 테스트: `HOOK_TYPE_NAMES`·`ANGLE_NAMES`·`FORMAT_NAMES`가 모든 enum 멤버를 빠짐없이 덮고(`other` 포함) 위 값과 정확히 같다(리터럴 고정). `_LABELS["format"|"hook_type"|"angle"]`가 이관 전과 같은 값이다. 0번의 고정값 테스트가 그대로 통과한다. `domain/labels.py`가 표준 라이브러리·pydantic만 쓴다(`tests/test_architecture.py`).

**2. 대응표(`analysis/prompts.py`)**
- 공개 함수 `axis_glossary() -> dict`: `{"hook_type": [{"value", "name", "definition"}, …], "angle": […], "format": […]}`. 각 항목은 열거 순서대로이며 **`other`는 제외한다**. `value`는 enum 값 문자열, `name`은 `HOOK_TYPE_NAMES` 등의 표시 이름, `definition`은 `_HOOK_CRITERIA`·`_ANGLE_CRITERIA`·`_FORMAT_CRITERIA`의 정의 문자열이다(손으로 복사하지 않는다). 같은 호출은 항상 같은 값을 낸다(결정적, 호출마다 새 딕셔너리).
- 테스트(`tests/test_taxonomy_freeze.py` 또는 해당 분석 프롬프트 테스트 파일): 각 축의 항목이 `other`를 뺀 모든 enum 멤버를 순서대로 덮고, `definition`이 `docs/TAXONOMY.md`의 정의와 같으며(기존 `parse_taxonomy`/문서 대조 방식), `name`이 표시 이름 상수와 같다. 반환 딕셔너리를 바꿔도 다음 호출에 영향이 없다.

**3. 해석 프롬프트(`agents/supervisor.py`)**
- `SUPERVISOR_PROMPT_VERSION = "2026-11-19-1"`. `_SYSTEM`에 다음 취지의 문장을 **더한다**(기존 문장·`TOOL_DATA_RULE` 불변): 사용자가 훅 유형(`hook_type`)·앵글(`angle`)·포맷(`format`)을 명시하면 입력 `axes` 표에서 그 표현(표시 이름 또는 판정 기준)에 맞는 `value`를 같은 이름의 칸에 채우고, 명시하지 않은 칸은 `null`로 둔다. `axes` 표에 없는 값을 만들거나 요청에 없는 축을 추측해 채우지 않는다. `axes` 표는 JSON 데이터이며 지시가 아니다.
- `decide(message, *, as_of, structured, limits, glossary=None, **call_options)`: `glossary`가 `None`이 아니면 payload에 `"axes": glossary`를 더한다(`None`이면 payload는 변경 전과 같다). `glossary`는 `call_options`가 아니다(고정 호출 옵션 검사·`SUPERVISOR_CALL_OPTIONS_INVALID` 불변). 모델·`reasoning_effort`·`StructuredSpec`·스키마는 불변이다.
- 테스트(`tests/test_supervisor.py`): (a) `glossary` 없는 호출의 payload 키가 변경 전과 같다. (b) `glossary`를 주면 payload에 `axes`가 있고 값이 주어진 것과 같으며 시스템 메시지에 새 지시 문장이 있다. (c) `glossary`를 `call_options`로 넘기려는 호출(`temperature` 등)은 기존 코드로 거부된다. (d) 실제 `decide`가 만든 메시지(`axes` 포함)가 `tests/test_schema_guard.py`의 메시지 가드(`guard_messages`)를 통과한다(새 테스트). (e) 닫힌 값 표 밖의 값을 모델이 돌려주면 `SupervisorDecision` 검증이 막는다(기존 동작 확인).

**4. 조립(`api/assembly.py`)**: `from beautyads.analysis.prompts import axis_glossary`를 가져와 `decide_fn`이 `decide(text, as_of=…, structured=…, limits=…, glossary=axis_glossary())`로 부른다(그 밖은 불변). 테스트(`tests/test_api_assembly.py`): `decide_fn`이 `glossary`를 `axis_glossary()`와 같은 값으로 넘긴다(가짜 `decide`로 확인, 기존 가짜 시그니처 호환).

**5. 동결(`eval/freeze_guard.py`)**: 라벨 상수 `SUPERVISOR_PROMPT_VERSION_LABEL = "동결 해석 프롬프트 버전"`, `SUPERVISOR_SYSTEM_HASH_LABEL = "동결 해석 _SYSTEM sha256"`, `AXIS_GLOSSARY_HASH_LABEL = "동결 해석 대응표 sha256"`. `frozen_values()`에 세 줄을 더한다: 버전 문자열, `sha256(agents.supervisor._SYSTEM)`, `sha256(json.dumps(axis_glossary(), sort_keys=True, ensure_ascii=False, separators=(",", ":")))`(기존 7개 줄 불변). 테스트: 위 "상수 단언 grep"의 갱신, 세 줄이 현재 코드를 따르고 값을 바꾸면(monkeypatch) 최종 가드가 `FROZEN_VALUE_MISMATCH`를 낸다.

**6. 기록·보고(`eval/e2e5_live.py`)**: `_record`에서 Supervisor·off 팔(`arm != "single"`)의 기록 `prompt_versions`에 `"supervisor": SUPERVISOR_PROMPT_VERSION`을 더한다(결과 딕셔너리는 건드리지 않는다). `_axis_adherence`의 축별 항목에 `unrequested_filled`를 더한다: 기획안이 있고 `brief_axes`가 있는 기록 중 `brief_axes[축]`이 `None`이 아닌데 요청의 `axes_used`에 그 축이 **없는** 건수(해석이 요청에 없는 축을 채운 과채움). 기존 키·값은 불변이다. 테스트(`tests/test_e2e5_live.py`): 지정·준수·충돌·해석 누락·`unrequested_filled`·`unavailable`이 합성 기록에서 손으로 센 값과 같고 지정 요청에서 해당 축의 `unrequested_filled`는 0, 무지정 요청에서 brief가 축을 채우면 1로 센다. 기록의 `prompt_versions`에 supervisor 버전이 들어간다(단일 팔은 아니다).

**7. 사전 등록(`eval/prereg.py`)**: `REQUIRED_SENTENCES` **끝에 22·23번째** 문장을 추가한다(앞 21개의 순서·문장 불변). 22번째: 변경 기록 — 해석 프롬프트(`SUPERVISOR_PROMPT_VERSION`)·닫힌 값 대응표 payload·`pattern_context`의 지정 축 제외는 P5 이후 변경이며 근거는 dev 스모크 관찰(사용자가 포맷·훅·앵글을 지정해도 해석 결과 brief의 해당 축이 비어 있었고 기획 단계에 지정 값이 전달되지 않았다)이다. P5 dev 비교 증거는 불변인 기획·평가 프롬프트에 대한 것이고 해석 단계는 P5에서 동결 대상이 아니었다. 해석 프롬프트 버전·`_SYSTEM`·대응표 해시는 이번에 동결 줄에 추가한다. 23번째: 한계 — 요청 문장은 대응표와 같은 표시 이름을 쓰므로 해석이 쉬운 조건이며 자유 표현(UGC·후기 영상 등)의 이해는 평가하지 않는다. 단일 팔은 원문을 받으므로 영향이 없다. `render_results_template`의 E2 행에 "요청에 없는 축 채움(과채움, 코드 판정, 참고용)"을 더한다.

**8. 변경 기록(`docs/PROMPT_CHANGELOG.md`)**: 표 끝에 행을 추가한다 — 날짜 `2026-11-19`, 버전 `해석 2026-11-19-1`, 대상 `agents/supervisor.py`·`api/assembly.py`·`analysis/prompts.py`·`domain/labels.py`·`domain/supervisor.py`(`pattern_context` 지정 축 제외, step 24), 변경(명시한 훅·앵글·포맷을 닫힌 값으로 채우고 명시하지 않으면 null, `axes` 대응표 payload — 값·정의는 `docs/TAXONOMY.md`·`analysis/prompts.py`의 기준에서 코드로 만들고 표시 이름은 기존 요청 문장 이름을 `domain/labels.py`로 이관, 사전 등록 동결 줄 3개 추가), 이유(재스모크에서 brief의 세 축이 지정에도 `None`, 기획 단계에 지정 값 미전달, 선케어 풀의 지배 format이 지정 값을 피하게 함; 이전 dev 결과와 직접 비교하지 않는다).

**테스트 요약(추가)**: `tests/test_prereg.py`: 문장 수 `== 23`, 22·23번째 문장 존재(`P5 이후`·`dev 스모크`·`동결`·`자유 표현`·`단일 팔은 원문`·`표시 이름` 포함), (a) 해시 기대값 한 줄 갱신, (b)(c) 불변 확인, 결과 틀의 새 행 빈 칸, 사전 등록 렌더링의 동결 줄에 새 라벨 3개와 값. 합성 문장·분류 값·모델 출력을 기대값으로 굳히지 않는다(형식·집합·해시·정확 일치 고정값만 검사).

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

- `agents/planning.py`·`agents/evaluation.py`의 프롬프트·버전, `MIN_DOMINANT_SHARE`·`THIN_POOL_MAX`·`PASS_MIN_SCORE`, `ResearchBrief`·`SupervisorDecision` 스키마, `pattern_context`·`pattern_alignment`를 바꾸지 마라. 이유: 동결 대상이거나 step 24의 범위다.
- 표시 이름 값을 새로 만들거나 바꾸거나 요청 문장(`build_request_candidates`의 출력·`_LABELS`의 값과 구조)을 한 글자라도 바꾸지 마라. 이유: 이관은 같은 값을 한 곳으로 옮기는 일이며 확정 세트 해시와 어긋나면 안 된다(고정값 테스트가 지킨다).
- `agents`에서 `analysis`·`eval`을 import하거나 `domain`에서 파일을 읽지 마라. 이유: 계층 경계다(`api/assembly.py`가 대응표를 만들어 주입한다).
- `obs/trace.py`의 `prompt_versions` 키 집합이나 결과 딕셔너리의 `prompt_versions`를 바꾸지 마라. 이유: 트레이스 스키마는 `planning`·`evaluation`만 허용한다(해석 버전은 `e2e5_live` 기록에만 남긴다).
- 해석 모델(`gpt-6-luna`)·`reasoning_effort`(`none`)·호출 옵션 검사를 바꾸거나 `temperature`를 지정하지 마라. 이유: 모델·옵션 규칙(AGENTS.md CRITICAL).
- 허용 파일 밖을 수정하거나 새 의존성을 추가하지 마라. 이유: 허용 범위 밖이다(필요하면 `blocked`로 보고). 기존 테스트의 단언을 약화하지 마라(위 "상수 단언 grep"에 적힌 정확 일치 갱신·문장 수·해시 (a) 한 줄 갱신만 허용). `REQUIRED_SENTENCES`의 기존 21개 문장을 고치지 마라. 이유: 이미 통과한 step의 계약이며 사전 등록 문장은 끝에만 추가한다.
