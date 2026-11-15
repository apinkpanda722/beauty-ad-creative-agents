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

**수정할 파일**: `docs/TAXONOMY.md`, `docs/ADR.md`, `src/beautyads/domain/labels.py`, `src/beautyads/analysis/models.py`, `src/beautyads/analysis/prompts.py`, `src/beautyads/eval/sheets.py`, `tests/test_taxonomy_freeze.py`, `tests/test_analysis_full.py`, `tests/test_pilot_sheet.py`, `tests/test_domain.py`, `tests/test_analysis.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `docs/TAXONOMY.md`(§1~§8과 헤더·초안 표시의 v1 동결 표기에 한함, §1~§4는 확정된 결정 6번 (a)~(d)의 문구에 한함), `docs/ADR.md`(새 ADR 하나를 끝에 추가하는 것에 한함), `src/beautyads/domain/labels.py`(`## 확정된 결정`이 요구하는 변경에 한함), `src/beautyads/analysis/models.py`(`PROMPT_VERSIONS` 값 갱신에 한함), `src/beautyads/analysis/prompts.py`(`## 확정된 결정`이 요구하는 프롬프트 변경에 한함), `src/beautyads/eval/sheets.py`(코드북·시트가 새 축 구성을 따르게 하는 것에 한함), `tests/test_taxonomy_freeze.py`(축 확장에 한함), `tests/test_analysis_full.py`(`test_run_and_prompt_versions`의 `PROMPT_VERSIONS` 기대값 한 군데와, 모든 enum을 순회해 `cta_type`을 바꾸는 테스트의 입력 구성에서 `structure.has_cta`를 `cta_type`과 일치시키는 것에 한함, 다른 단언 약화 금지), `tests/test_pilot_sheet.py`(`test_real_taxonomy_gives_every_tabled_value_a_definition`의 "미확정 쟁점" 단언 한 줄과 `test_label_columns_and_codebook_follow_domain`의 열 개수 기대값(축 제거로 17에서 16으로)에 한함, 다른 단언 약화 금지), `tests/test_domain.py`(축을 제거하는 결정이 있을 때 그 필드를 가리키는 단언과, 모든 enum을 순회해 `cta_type`을 바꾸는 테스트의 입력 구성에서 `structure.has_cta`를 `cta_type`과 일치시키는 것에 한함), `tests/test_analysis.py`(프롬프트 버전 hook-v0을 기대하는 단언의 기대값 갱신에 한함, 다른 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

소비자 테스트 점검 결과: `tests/test_analysis.py`·`tests/test_analyze_runner.py`·`tests/test_media_flow.py`는 `domain/labels.py`의 enum(`HookType` 등)과 `analysis/models.py`를 import한다. 이 step이 값·필드를 바꿔 이 테스트들의 단언이 깨지면(수정 허용 경로에 없다) 고치지 말고 `blocked`로 보고한다. `scripts/test_step_files.py`는 `docs/ADR.md`를 참조하지만 ADR을 끝에 추가하는 것은 영향이 없다.

> **이 step은 사용자의 전체 v1 동결 승인(2026-11-13) 뒤에만 실행한다.** 승인은 예정일(11-19)보다 앞당겨졌다(E1 1단계가 11-13에 끝나 2단계 라벨링·7일 재라벨 일정에 여유를 만들기 위함이며 사전 등록 위반이 아니다). 아래 확정된 결정 절에 승인된 내용이 붙어 있다. 비어 있으면 코드를 쓰지 않고 `blocked`로 보고한다. reason에 "확정된 결정 절이 비어 있음"을 적는다.

**전체 v1 동결**: 나머지 축의 정의를 고정하고 프롬프트 버전을 올린다. 이 동결은 E1 2단계 라벨링 전이고 일괄 분석(`analyze-target`) 전이다. 시범(`@minimal`·`@default`) 결과는 v0 프롬프트의 것이므로 `@v1`과 섞지 않는다(`FINAL_RUN_TAG`가 이미 분리한다).

1. **TAXONOMY 미확정 쟁점 4건을 `## 확정된 결정`대로 문서에 반영하고 해당 "미확정 쟁점" 문구를 지운다**: (a) `has_hook_segment`(정의 확정 **또는** 축 제거), (b) `has_cta`와 `cta_type`의 연동(`has_cta` ⇔ `cta_type != none`이 확정되면 `FullResult`에 이 관계를 강제하는 검증을 둔다), (c) `claims`에 캡션 본문 문장을 인정할지(현재 분석 프롬프트는 제목·캡션을 "참고" 입력으로 넣는다 — 확정된 결정과 프롬프트의 입력 설명이 일치해야 한다), (d) 다중 CTA 선택 규칙. 문서 헤더의 버전을 `v1`로 바꾸고 동결 날짜를 적는다.
2. **코드가 문서를 따르게 한다**: 결정이 값 목록·필드를 바꾸면 `domain/labels.py`, `analysis/prompts.py`, `eval/sheets.py`를 함께 고친다(값은 문서가 정하고 코드가 따른다). 축을 제거하면 그 축을 가리키는 `StructureFlags`·프롬프트·코드북 열·테스트 단언이 한꺼번에 바뀌어야 한다(일부만 바꾸면 테스트가 깨진다).
3. **`PROMPT_VERSIONS`를 v1로 올린다**: `analysis/models.py`의 세 값(`content_type`·`hook`·`full`)을 새 버전 문자열로 바꾼다. `ANALYSIS_MODEL_ID`와 `FINAL_RUN_TAG`는 바꾸지 않는다. 프롬프트 본문이 바뀐 축은 버전도 바뀌어야 한다(본문이 바뀌지 않은 축의 버전을 올릴지는 `## 확정된 결정`을 따른다).
4. **기존 단언 두 개를 새 계약으로 바꾼다(그 줄만)**: `tests/test_analysis_full.py::test_run_and_prompt_versions`의 `PROMPT_VERSIONS` 기대값(코드 상수이며 모델이 만든 값이 아니다), `tests/test_pilot_sheet.py::test_real_taxonomy_gives_every_tabled_value_a_definition`의 `cta_type`·`claims` "미확정 쟁점" 단언(문서에서 쟁점이 해소되어 표시가 사라지므로, 문서에 표시가 **있으면** 모든 값 note에 보이고 **없으면** `정의:`로 시작하기만 하면 되는 형태로). 나머지 단언(`정의:` 접두, true/false 문구, `FINAL_RUN_TAG == "v1"`, 시범 태그와 겹치지 않음)은 그대로 둔다.
5. **`tests/test_taxonomy_freeze.py`를 모든 축으로 넓힌다**: `domain` 값 목록(모든 닫힌 값 축)과 `docs/TAXONOMY.md`의 값 집합이 같고, 불리언 열이 문서의 열과 같으며, 정의 표가 있는 축은 표의 값마다 정의가 있고(`angle`·`format`의 `other`처럼 표에서 정의 칸이 비어 있는 값과, 값 목록만 있고 표가 없는 `talent`의 정의 없는 값은 허용하되 `ordinary_person`은 확정된 결정 6번 (c)의 정의가 있어야 한다), 문서에 "미확정 쟁점"이 하나도 남아 있지 않고(결정이 모두 끝났다는 뜻), 문서 헤더가 v1 동결 날짜를 갖는지 검사한다. 값 목록은 테스트가 정하지 않고 문서·enum에서 읽는다.
6. **`docs/ADR.md` 끝에 ADR 하나를 추가한다**: 결정(전체 v1 동결, 날짜 2026-11-13, 확정된 결정 1~6번의 요약), 이유(2단계 라벨링과 일괄 분석이 같은 기준을 써야 한다; 동결을 예정일 11-19보다 앞당긴 사유: E1 1단계가 11-13에 끝나 2단계 라벨링·7일 재라벨 일정에 여유를 만든다), 트레이드오프(시범 v0 결과와 v1 결과가 달라 직접 비교하지 않는다, 시범 사람 라벨은 옛 규칙(마지막 CTA 등)이므로 E1 판정에 시범을 쓰지 않는다).
7. **사전 등록 파일(`docs/results/e1_preregistration.md`)은 이 step이 고치지 않는다.** 구현 세션이 이 step 뒤에 전체 동결 날짜·프롬프트 버전 3개·`ANALYSIS_MODEL_ID`를 기록해 별도로 커밋한다. `analyze-target`(step 6)은 그 기록이 없으면 시작하지 않는다.

## 확정된 결정

사용자가 조언 세션의 권고를 전부 승인했다(2026-11-13). 동결 날짜는 모든 곳(TAXONOMY 헤더, ADR, 사전 등록 §6)에서 **2026-11-13**이다.

1. **`has_hook_segment`: 축을 제거한다.** `StructureFlags`(`domain/labels.py`), 분석 프롬프트, 코드북·시트 열(`eval/sheets.py`가 `label_columns()`로 따라가게), 관련 테스트 단언에서 한꺼번에 뺀다. `docs/TAXONOMY.md` §5의 `has_hook_segment` 행과 그 설명 문장, "미확정 쟁점"을 지운다(`hook_type`은 그대로다). 다른 소비자 테스트(`tests/test_analysis.py`·`tests/test_analyze_runner.py`·`tests/test_media_flow.py` 등 수정 허용 경로 밖)가 깨지면 고치지 말고 `blocked`로 보고한다(위 소비자 테스트 점검 결과 규칙 그대로).
2. **`has_cta` ⇔ `cta_type != none`을 확정한다.** `FullResult`에 스키마 검증(`model_validator`)으로 강제한다. `structure.has_cta`가 true인데 `cta_type`이 `none`이거나 `has_cta`가 false인데 `cta_type`이 `none`이 아니면 검증이 실패하고, 이 실패는 기존 스키마 검증 실패 경로(1회 재요청 뒤 `INVALID_OUTPUT`)로 처리된다(새 경로를 만들지 않는다). 문서의 `has_cta` 행에서 "미확정 쟁점"과 "조언 세션이 정한 임의 규칙" 문구를 지우고 규칙만 남긴다.
3. **`claims`: 영상 자막·음성에 더해 캡션 본문 문장에 명시된 효능도 인정한다. 해시태그만 있는 경우는 제외한다.** `docs/TAXONOMY.md` §8의 "자막이나 음성으로 **명시된** 효능만 붙인다" 문장을 이 규칙으로 고치고 "미확정 쟁점"을 지운다. 분석 프롬프트의 입력 설명(제목·캡션이 "참고" 입력)을 이 규칙과 일치시킨다(캡션 본문 문장에 명시된 효능을 인정하고 해시태그만 있으면 붙이지 않는다고 프롬프트에 쓴다).
4. **다중 CTA: 고정 우선순위 `shop_now` > `event` > `learn_more` > `store_mention` > `follow_engage` 순으로 가장 앞선 것을 고른다.** `docs/TAXONOMY.md` §7의 "여러 개가 나오면 영상에서 가장 마지막에 요구하는 것" 문장과 "미확정 쟁점"을 지우고 이 우선순위를 적는다. 프롬프트에도 같은 우선순위를 쓴다(§7 표의 행 순서는 바꾸지 않는다).
5. **프롬프트 버전: `content_type`·`hook`·`full` 세 값을 모두 v1로 올린다**(`analysis/models.py`의 `PROMPT_VERSIONS`를 `content-type-v1`·`hook-v1`·`full-v1`로). `ANALYSIS_MODEL_ID`와 `FINAL_RUN_TAG`는 바꾸지 않는다. (`hook`·`content_type`의 프롬프트 본문이 이번에 바뀌지 않았어도 사용자 결정으로 세 값을 모두 올린다.)
6. **추가 문서 정리(값 목록 변경 없음, `docs/TAXONOMY.md` §1~§4의 해당 문구에 한함)**
   - (a) **format 우선순위를 표 순서로 적는다**: §3 표 행을 `static_image` > `text_motion` > `ugc_style` > `demo` > `studio_film` > `other` 순으로 다시 늘어놓고, 표 아래에 "둘 이상 해당하면 표의 위쪽 값을 우선한다" 문장을 쓴다(§1의 같은 문장 형식).
   - (b) **angle과 format의 독립 문구를 §2 끝에 한 줄 추가한다**: "`how_to`는 메시지 전략, `demo`는 제작 형식이라 함께 붙을 수 있다."
   - (c) **`talent`의 `ordinary_person`을 정의한다**: "이름·소속이 표시되지 않은 출연자(전문 광고 모델 포함)". §4의 해당 불릿과 기존 문장("없으면 `ordinary_person`으로 둔다")이 이 정의와 어긋나지 않게 한다.
   - (d) **`hook_type`에 `title_card` 값을 추가하지 않는다.** §1의 "타이틀·로고 화면으로 시작하는 영상을 어디에 넣을지는 미정이다…" 문장을 "타이틀·로고로 시작하는 영상은 `other`로 둔다(`title_card` 값은 추가하지 않는다)"로 바꾼다.
   - **분석 프롬프트에도 format 우선순위(위 순서)와 `ordinary_person` 정의가 반영되게 한다**(`prompts.py`, 허용 범위 안). 프롬프트의 값 목록 설명이 enum 정의 순서가 아니라 이 우선순위를 따르게 하려면 프롬프트 문장에 우선순위를 명시한다(enum 값 순서는 바꾸지 않는다).
7. **TAXONOMY 헤더와 초안 표시**: 문서 제목을 `# 소재 분류 목록 (v1, 2026-11-13 동결)`로 바꾸고 상태 문장("초안…시범을 거쳐…")을 "v1 동결(2026-11-13). 동결 뒤의 변경은 ADR에 남긴다."로 바꾼다. §5~§8의 `> 아래 정의는 시범 라벨링을 위한 **초안**이다…` 인용문은 `> v1 동결(2026-11-13): 이 절의 값과 정의는 E2 이후 변경 시 ADR에 남긴다.` 한 줄로 바꾼다(문서에 "미확정 쟁점"과 "초안" 표시가 남지 않게 한다. `content_type`·`category` 절의 부분 동결 줄은 그대로 둔다). **ADR의 트레이드오프에 반드시 적는다**: 시범 20건의 사람 라벨은 옛 규칙(마지막 CTA 등)으로 달았으므로 v1 결과와 직접 비교하지 않고, E1 판정에는 시범을 쓰지 않는다.

### 반드시 있어야 하는 테스트

- `PROMPT_VERSIONS`의 세 값이 `domain`·프롬프트 본문 변경에 맞게 올라갔고 `FINAL_RUN_TAG`·`ANALYSIS_MODEL_ID`는 그대로다.
- 문서와 `domain`의 모든 축 값 집합이 같다(문서에서 값을 지운 합성 텍스트로는 실패), 문서에 "미확정 쟁점"이 남아 있으면 실패한다(합성 텍스트로 검사).
- `has_cta` ⇔ `cta_type != none`이 확정된 경우: 이 관계가 어긋난 합성 `FullResult`(`has_cta`가 true인데 `cta_type`이 `none`, 그 반대)는 검증에서 거부되고 일치하면 통과한다. 어긋난 출력은 기존 재요청·`INVALID_OUTPUT` 경로로 처리된다(모델 값을 고정하지 않고 가짜 모델 출력으로 검증).
- 축을 제거한 경우: 제거된 필드를 가진 합성 출력은 거부되고(`extra="forbid"`), 코드북·시트 열에서 그 열이 빠진다. 제거하지 않은 경우: 그대로다.
- 시트 코드북이 새 TAXONOMY에서 정의를 읽는다(문서와 코드북이 어긋나지 않음).
- 코드북·시트 열 개수와 열 이름이 `domain`에서 `has_hook_segment`가 빠진 구성과 같다(`test_label_columns_and_codebook_follow_domain`의 기대값은 17에서 16으로 바꾼다).
- 모든 enum을 순회하는 기존 테스트들은 `cta_type`을 바꿀 때 `has_cta`를 함께 맞춰(`none`이면 false, 아니면 true) 새 검증과 충돌하지 않는다. 이 조정은 입력 구성에 한하고 단언은 약화하지 않는다.
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
