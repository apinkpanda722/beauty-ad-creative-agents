# Step 5: taxonomy-v1

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P3 `taxonomy-v1` 행, 변경 기록 #32, §8 결정 현황
- `/docs/TAXONOMY.md` — §5~§8의 "미확정 쟁점"과 §5의 `has_hook_segment` 쟁점
- `/docs/ADR.md` — 마지막 ADR의 형식
- `/src/beautyads/domain/labels.py` — `StructureFlags`, `PlatformFitFlags`, `CtaType`, `Claim`, `HookResult`, `FullResult`
- `/src/beautyads/analysis/models.py`, `/src/beautyads/analysis/prompts.py`, `/src/beautyads/analysis/axes.py` — 프롬프트 버전·입력(제목·캡션이 "참고"로 들어감)·출력 검증과 재요청
- `/src/beautyads/eval/sheets.py` — `parse_taxonomy`, `codebook_rows`, `label_columns`
- `/tests/test_pilot_sheet.py`, `/tests/test_analysis_full.py`, `/tests/test_domain.py`, `/tests/test_taxonomy_freeze.py` — 이 step이 바꾸는 단언과 깨면 안 되는 기존 테스트

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `docs/TAXONOMY.md`, `docs/ADR.md`, `src/beautyads/domain/labels.py`, `src/beautyads/analysis/models.py`, `src/beautyads/analysis/prompts.py`, `src/beautyads/eval/sheets.py`, `tests/test_taxonomy_freeze.py`, `tests/test_analysis_full.py`, `tests/test_pilot_sheet.py`, `tests/test_domain.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `docs/TAXONOMY.md`(§5~§8과 헤더의 버전 표기에 한함), `docs/ADR.md`(새 ADR 하나를 끝에 추가하는 것에 한함), `src/beautyads/domain/labels.py`(`## 확정된 결정`이 요구하는 변경에 한함), `src/beautyads/analysis/models.py`(`PROMPT_VERSIONS` 값 갱신에 한함), `src/beautyads/analysis/prompts.py`(`## 확정된 결정`이 요구하는 프롬프트 변경에 한함), `src/beautyads/eval/sheets.py`(코드북·시트가 새 축 구성을 따르게 하는 것에 한함), `tests/test_taxonomy_freeze.py`(축 확장에 한함), `tests/test_analysis_full.py`(`test_run_and_prompt_versions`의 `PROMPT_VERSIONS` 기대값 한 군데에 한함, 다른 단언 약화 금지), `tests/test_pilot_sheet.py`(`test_real_taxonomy_gives_every_tabled_value_a_definition`의 "미확정 쟁점" 단언 한 줄에 한함, 다른 단언 약화 금지), `tests/test_domain.py`(축을 제거하는 결정이 있을 때 그 필드를 가리키는 단언에 한함)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

소비자 테스트 점검 결과: `tests/test_analysis.py`·`tests/test_analyze_runner.py`·`tests/test_media_flow.py`는 `domain/labels.py`의 enum(`HookType` 등)과 `analysis/models.py`를 import한다. 이 step이 값·필드를 바꿔 이 테스트들의 단언이 깨지면(수정 허용 경로에 없다) 고치지 말고 `blocked`로 보고한다. `scripts/test_step_files.py`는 `docs/ADR.md`를 참조하지만 ADR을 끝에 추가하는 것은 영향이 없다.

> **이 step은 2026-11-19 사용자의 전체 v1 동결 승인 뒤에만 실행한다.** 아래 `## 확정된 결정`은 사용자가 11-18~19에 결정한 내용을 구현 세션이 붙여 넣은 뒤에 실행한다(초안 시점에는 비어 있다). 비어 있으면 코드를 쓰지 않고 `blocked`로 보고한다. reason에 "확정된 결정 절이 비어 있음"을 적는다.

**전체 v1 동결**: 나머지 축의 정의를 고정하고 프롬프트 버전을 올린다. 이 동결은 E1 2단계 라벨링 전이고 일괄 분석(`analyze-target`) 전이다. 시범(`@minimal`·`@default`) 결과는 v0 프롬프트의 것이므로 `@v1`과 섞지 않는다(`FINAL_RUN_TAG`가 이미 분리한다).

1. **TAXONOMY 미확정 쟁점 4건을 `## 확정된 결정`대로 문서에 반영하고 해당 "미확정 쟁점" 문구를 지운다**: (a) `has_hook_segment`(정의 확정 **또는** 축 제거), (b) `has_cta`와 `cta_type`의 연동(`has_cta` ⇔ `cta_type != none`이 확정되면 `FullResult`에 이 관계를 강제하는 검증을 둔다), (c) `claims`에 캡션 본문 문장을 인정할지(현재 분석 프롬프트는 제목·캡션을 "참고" 입력으로 넣는다 — 확정된 결정과 프롬프트의 입력 설명이 일치해야 한다), (d) 다중 CTA 선택 규칙. 문서 헤더의 버전을 `v1`로 바꾸고 동결 날짜를 적는다.
2. **코드가 문서를 따르게 한다**: 결정이 값 목록·필드를 바꾸면 `domain/labels.py`, `analysis/prompts.py`, `eval/sheets.py`를 함께 고친다(값은 문서가 정하고 코드가 따른다). 축을 제거하면 그 축을 가리키는 `StructureFlags`·프롬프트·코드북 열·테스트 단언이 한꺼번에 바뀌어야 한다(일부만 바꾸면 테스트가 깨진다).
3. **`PROMPT_VERSIONS`를 v1로 올린다**: `analysis/models.py`의 세 값(`content_type`·`hook`·`full`)을 새 버전 문자열로 바꾼다. `ANALYSIS_MODEL_ID`와 `FINAL_RUN_TAG`는 바꾸지 않는다. 프롬프트 본문이 바뀐 축은 버전도 바뀌어야 한다(본문이 바뀌지 않은 축의 버전을 올릴지는 `## 확정된 결정`을 따른다).
4. **기존 단언 두 개를 새 계약으로 바꾼다(그 줄만)**: `tests/test_analysis_full.py::test_run_and_prompt_versions`의 `PROMPT_VERSIONS` 기대값(코드 상수이며 모델이 만든 값이 아니다), `tests/test_pilot_sheet.py::test_real_taxonomy_gives_every_tabled_value_a_definition`의 `cta_type`·`claims` "미확정 쟁점" 단언(문서에서 쟁점이 해소되어 표시가 사라지므로, 문서에 표시가 **있으면** 모든 값 note에 보이고 **없으면** `정의:`로 시작하기만 하면 되는 형태로). 나머지 단언(`정의:` 접두, true/false 문구, `FINAL_RUN_TAG == "v1"`, 시범 태그와 겹치지 않음)은 그대로 둔다.
5. **`tests/test_taxonomy_freeze.py`를 모든 축으로 넓힌다**: `domain` 값 목록(모든 닫힌 값 축)과 `docs/TAXONOMY.md`의 값 집합이 같고, 불리언 열이 문서의 열과 같으며, 값마다 정의가 있고, 문서에 "미확정 쟁점"이 하나도 남아 있지 않고(결정이 모두 끝났다는 뜻), 문서 헤더가 v1 동결 날짜를 갖는지 검사한다. 값 목록은 테스트가 정하지 않고 문서·enum에서 읽는다.
6. **`docs/ADR.md` 끝에 ADR 하나를 추가한다**: 결정(전체 v1 동결, 날짜 2026-11-19, 네 쟁점의 결정 요약), 이유(2단계 라벨링과 일괄 분석이 같은 기준을 써야 한다), 트레이드오프(시범 v0 결과와 v1 결과가 달라 직접 비교하지 않는다).
7. **사전 등록 파일(`docs/results/e1_preregistration.md`)은 이 step이 고치지 않는다.** 구현 세션이 이 step 뒤에 전체 동결 날짜·프롬프트 버전 3개·`ANALYSIS_MODEL_ID`를 기록해 별도로 커밋한다. `analyze-target`(step 6)은 그 기록이 없으면 시작하지 않는다.

## 확정된 결정

(비어 있음 — 11-18~19에 사용자가 아래 네 가지를 결정한 뒤 구현 세션이 붙여 넣는다.)
1. `has_hook_segment`: 정의 확정(정의 문구) 또는 축 제거.
2. `has_cta` ⇔ `cta_type != none` 연동의 확정 여부와 강제 방식(스키마 검증 여부).
3. `claims`의 캡션 문장 인정 여부와 그 근거 문구(영상 자막·음성만인지, 캡션 본문 포함인지).
4. 다중 CTA 선택 규칙.
5. 프롬프트 버전 문자열 세 개와 본문이 바뀐 축.

### 반드시 있어야 하는 테스트

- `PROMPT_VERSIONS`의 세 값이 `domain`·프롬프트 본문 변경에 맞게 올라갔고 `FINAL_RUN_TAG`·`ANALYSIS_MODEL_ID`는 그대로다.
- 문서와 `domain`의 모든 축 값 집합이 같다(문서에서 값을 지운 합성 텍스트로는 실패), 문서에 "미확정 쟁점"이 남아 있으면 실패한다(합성 텍스트로 검사).
- `has_cta` ⇔ `cta_type != none`이 확정된 경우: 이 관계가 어긋난 합성 `FullResult`(`has_cta`가 true인데 `cta_type`이 `none`, 그 반대)는 검증에서 거부되고 일치하면 통과한다. 어긋난 출력은 기존 재요청·`INVALID_OUTPUT` 경로로 처리된다(모델 값을 고정하지 않고 가짜 모델 출력으로 검증).
- 축을 제거한 경우: 제거된 필드를 가진 합성 출력은 거부되고(`extra="forbid"`), 코드북·시트 열에서 그 열이 빠진다. 제거하지 않은 경우: 그대로다.
- 시트 코드북이 새 TAXONOMY에서 정의를 읽는다(문서와 코드북이 어긋나지 않음).
- 수정한 두 기존 단언 외의 단언을 약화하지 않았다(`git diff`로 삭제된 단언 줄이 위 두 곳뿐임을 확인).

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
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
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

- `## 확정된 결정` 밖의 값·정의를 임의로 바꾸지 마라. 이유: 정의 확정은 사용자의 결정이고 구현은 그 결정을 옮기기만 한다.
- `ANALYSIS_MODEL_ID`·`FINAL_RUN_TAG`를 바꾸지 마라. 이유: 모델 ID는 사전 등록에 동결 기록하고 `FINAL_RUN_TAG`는 시범 결과와 분리하는 기준이다.
- 테스트에 새 값 목록·정의 문구를 하드코딩하지 마라. 이유: 문서와 코드가 어긋난 것을 테스트가 알려야 한다(FP-C03).
- 위 두 기존 단언 외의 기존 단언을 약화하거나 삭제하지 마라(가드 테스트 포함). 이유: 이 step이 의도한 계약 변경은 그 두 곳뿐이다.
- 프롬프트 본문을 바꾸고 버전을 올리지 않는 것, 또는 본문을 바꾸지 않고 버전만 올리는 것을 하지 마라(결정에 명시된 경우 제외). 이유: 버전이 결과의 출처를 식별한다.
- `docs/results/`의 사전 등록 파일을 고치지 마라. 이유: 구현 세션이 별도로 기록·커밋한다.
- 모델을 호출하거나 시범을 다시 돌리지 마라. 이유: 분석은 `analyze-target`에서 사용자가 실행한다.
