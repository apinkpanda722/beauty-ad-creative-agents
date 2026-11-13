# Step 3: pilot-compare

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P3 `pilot-compare` 행(입력·제외·교집합 규칙)과 `e1-scorer` 행(이 모듈의 일치율 함수를 재사용한다)
- `/docs/results/e1_preregistration.md` — 사전 등록의 비교 규칙 절(읽기 전용. 이 step의 규칙과 어긋나면 `blocked`)
- `/src/beautyads/eval/sheets.py` — `label_columns`, `_label_axes`(평탄화 규칙), `read_key_items`, `write_key_supplement`, `SheetError`
- `/src/beautyads/eval/pilot_run.py` — 재시도 보충 파일(`pilot_key_supplement.json`) 형식, `AXES`, `RUN_TAGS`
- `/src/beautyads/domain/labels.py`, `/src/beautyads/domain/jobs.py` — `ContentTypeResult`·`HookResult`·`FullResult`, `JobStatus`
- `/README.md`, `/Makefile`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/pilot_compare.py`(새 파일), `Makefile`, `README.md`, `tests/test_pilot_compare.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/pilot_compare.py`, `Makefile`(`pilot-compare` 타깃과 `.PHONY` 추가에 한함, `verify` 불변), `README.md`(pilot-compare 절 추가에 한함), `tests/test_pilot_compare.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

소비자 테스트 점검 결과: `scripts/test_hooks.py`는 임시 디렉터리에 자기 `Makefile`을 만들어 쓰므로 영향이 없다. `tests/test_compose.py`·`tests/test_slice.py`·`tests/test_collect.py`·`tests/test_pilot.py`는 저장소 `Makefile`을 읽지만 `.PHONY`는 부분집합으로, 기존 타깃의 레시피 원문은 정확히, `verify` 레시피는 `live-`가 없음을 단언한다. 따라서 **새 타깃은 추가하되 기존 타깃의 레시피 원문·`verify` 레시피·그 뒤의 빈 줄 형식은 바꾸지 않는다.** `tests/test_architecture.py`는 새 모듈에 계층 규칙을 적용한다(통과해야 한다). 이 파일들은 수정하지 않는다. 깨지면 고치지 말고 `blocked`로 보고한다.

시범 20건의 두 실행(`minimal`·`default`)을 사람 라벨과 비교하는 작은 CLI다. `eval/`에 둔다. DB·네트워크·모델을 쓰지 않는다(파일만 읽는다). **이 step 안에서는 CLI를 실제 파일로 실행하지 않는다. 테스트는 합성 라벨·합성 키 파일만 쓴다.**

### 입력

- **사람 라벨**: 기본 `data/interim/pilot/pilot_sheet_labeled.csv`(상수 `DEFAULT_LABELS`, `--labels`로 변경). 열은 시트와 같다(`item_id`, `link`, `text`, `label_columns()`). 파일이 없으면 `LABEL_FILE_MISSING`, 열 이름이 다르거나 값이 코드북 밖(`domain` enum 값 밖, 불리언 열이 `true`/`false`/빈 값이 아님, `claims`가 닫힌 목록 밖)이면 `LABEL_FILE_INVALID`이고 **키 파일을 읽기 전에** 종료 코드 2로 끝난다(라벨의 형식·값 검사가 먼저다). **그 검사를 통과한 뒤에** 키 파일을 읽고, 그 다음에 `item_id`가 키 파일에 없는 행이 있으면 같은 `LABEL_FILE_INVALID`(종료 코드 2)로 끝난다(`item_id` 포함 여부는 키 파일을 읽어야 알 수 있으므로 이 검사만 키를 읽은 뒤에 한다). 원본 빈 시트와 백업 파일은 읽지 않는다.
- **모델 결과**: 기본 `data/interim/pilot/pilot_key.json`(`--key`)과 같은 폴더의 `pilot_key_supplement.json`(있으면). 보충 파일의 항목은 **같은 `item_id`의 해당 `run_tag` 실행만** 덮어쓴다(다른 실행·다른 항목은 건드리지 않는다). 키 파일이 없으면 `PILOT_KEY_MISSING`(`eval.sheets.SheetError` 재사용).
- 각 실행의 결과는 `runs[<태그>][content_type|hook|full]` = `{status, labels, error_code, ...}` 또는 `null`이다. 열은 `label_columns()`의 평탄화 규칙에 따라 **그 열을 만드는 작업의 `labels`에서** 찾는다(`ContentTypeResult` 열은 `content_type` 작업, `HookResult` 열은 `hook` 작업, `FullResult` 열은 `full` 작업, 구조·플랫폼 적합성의 중첩은 열 이름으로 펼친다).

### 제외 규칙(항목 단위, 모든 축에서 함께 제외)

한 실행이라도 아래에 걸리면 그 항목을 **모든 축·두 실행 모두에서 제외**하고 제외 목록(항목 번호·실행 태그·실패한 작업·`error_code`)을 보고한다(축마다 모집단이 달라져 두 실행 비교가 깨지는 것을 막는다). **제외는 아래 (a)·(b)뿐이다** (2026-11-13 정정: 처음 규칙이 파이프라인 동작과 달랐다):
(a) 그 실행에 **존재하는 작업**(`content_type`·`hook`·`full`)의 `status`가 `done`이 아니다(`failed`·`held`·`pending`). `content_type` 작업이 없거나 `null`이어도 제외한다.
(b) 모델이 `product_creative`이고 category가 `other`가 아닌 항목(`analysis.axes.is_product_target`와 같은 조건)인데 `hook` 또는 `full` 작업이 없다.
**모델이 `product_creative`로 보고 category를 `other`로 본 항목은 제외하지 않는다**(분석 파이프라인이 `hook`·`full`을 만들지 않는 것이 정상이다). 모델이 제품이 아니라고 본 항목도 `hook`·`full`이 없는 것이 정상이다. 분석 대상 조건은 코드 한 곳(`_is_analysis_target`)에 두고, 파이프라인의 `is_product_target`와 모든 (`content_type`, `category`) 조합에서 같은 결과를 내는지 테스트로 확인한다.

### 비교 규칙 (사전 등록에 적힌 규칙, 코드 상수로 한 곳에 둔다)

- **`content_type` 축은 혼동 행렬로만 보고한다**: 행 = 사람 값, 열 = 모델 값, 실행별. 제외되지 않은 모든 항목이 대상이다(교집합 규칙을 적용하지 않는다). 단순 일치율은 참고로 한 줄 덧붙인다.
- **나머지 모든 축**(`category`, `hook_type`, `angle`, `format`, `talent`, 구조·플랫폼 불리언, `cta_type`, `claims`)은 **사람과 모델이 모두 `product_creative`로 판정한 교집합 항목에서만** 비교한다. 교집합은 **실행마다 따로** 구한다. 단, `hook`·`full`에서 나오는 축은 교집합 항목 중 모델이 분석한 항목(`is_product_target`)만 비교하고, 모델이 `product_creative`+category `other`로 본 항목은 "모델이 분석하지 않음"(사유 `category_other로 분석 제외`)으로 따로 세어 보고한다(축마다 `분석 제외` 건수, `사람 제품 수`, 커버리지 = 비교에 쓰인 건수 ÷ 사람이 제품으로 본 건수, 목록 `NOT_ANALYZED <항목> <실행> <사유>`). `category` 축은 `content_type` 작업에서 나오므로 이 항목들을 포함해 비교한다(사람 기준 지원 3종이었다면 category 불일치로 드러난다). 사람이 `product_creative`가 아닌 항목은 나머지 열이 비어 있으므로(시트 안내) 비교에서 빠진다. 모델이 `product_creative`가 아니면 `full` 분석이 없으므로 역시 빠진다.
- 축별 지표: 단순 일치율(같은 값이면 일치, `claims`는 집합이 정확히 같을 때), **분모(`n`)와 교집합 크기를 함께** 낸다. 실행 간(`minimal` 대 `default`) 모델끼리의 일치율도 같은 교집합 규칙(양쪽 실행과 사람이 모두 제품)으로 낸다. 일치율 계산은 **재사용 가능한 순수 함수 `agreement(pairs) -> AgreementResult`**로 만든다(`e1-scorer`가 재사용한다. 모델 값을 고정하지 않고 값 쌍을 받는다).
- **교집합이 비는 축**은 0%로 쓰지 않고 `COMPARE_EMPTY_SET:<축>`을 보고하고 종료 코드 3이다(모든 축이 비면 종료 코드 3, 일부만 비면 그 축만 보고하고 나머지는 계산하며 종료 코드 3).
- **정의 미확정 표시**: `has_cta`(라벨링 도중 정의가 고쳐짐), `has_hook_segment`(`product_first`와 정의 충돌)는 결과 줄에 `note: 정의 미확정, 참고용`을 붙인다. 이 두 열 이름은 상수 하나로 둔다.
- 출력: 사람이 읽는 표(축, 실행, `n`, 일치율)와 JSON 한 줄. 라벨·모델 라벨 원문 텍스트나 `text`(제목·캡션)는 출력하지 않는다. 종료 코드: 0 성공, 2 입력 문제, 3 비교 불가.
- `Makefile`: `pilot-compare` 타깃(`uv run python -m beautyads.eval.pilot_compare`)을 `.PHONY`와 함께 추가한다. README에 사용법(`--labels`, `--key`), 이유 코드 표, "키 파일은 라벨링을 마친 뒤에만 연다(시범 라벨링은 끝났다)"를 쓴다.

### 반드시 있어야 하는 테스트

(합성 라벨 CSV와 합성 키 JSON을 tmp 경로에 만들어 쓴다. 실제 `data/interim` 파일을 읽지 않는다. 모델 라벨 값을 기대값으로 굳히지 않는다. 합성 키의 값은 테스트가 정한 임의의 enum 값이다.)
- 라벨 파일이 없으면 `LABEL_FILE_MISSING`, 열 이름·값 형식 오류는 `LABEL_FILE_INVALID`이고 **키 파일 읽기 함수가 불리지 않는다**(가짜로 감시). 형식·값이 올바르면 키 파일을 읽고, 라벨의 `item_id`가 키 파일에 없으면 `LABEL_FILE_INVALID`(이때는 키 읽기 함수가 불린다), 키 파일이 없으면 `PILOT_KEY_MISSING`.
- 제외: ① 존재하는 작업(`content_type`·`hook`·`full`)이 `failed`·`held`·`pending`이거나 `content_type`이 없으면 그 항목이 두 실행 모두에서, 모든 축에서 빠진다. ② 모델이 `product_creative`이고 category가 `other`가 아닌데 `hook`/`full`이 없으면 제외. ③ 모델이 제품이 아니면 `hook`/`full`이 `null`이어도 제외되지 않는다. ④ **모델이 `product_creative`+category `other`로 본 항목은 제외되지 않고**, `content_type`·`category` 비교에 들어가며 `hook`·`full` 계열 축에서는 "모델이 분석하지 않음"으로 따로 세어진다(축별 `분석 제외` 건수·사유·커버리지가 손계산 값과 같다, 두 실행 비교 `minimal_vs_default`도 같은 방식). ⑤ 존재하지만 `done`이 아닌 `hook`은 모델이 category `other`로 본 항목이어도 제외한다. ⑥ `_is_analysis_target`이 파이프라인의 `is_product_target`과 모든 조합에서 같다. 제외 목록에 항목 번호·태그·작업이 정확히 나온다.
- 보충 파일: 같은 `item_id`·`run_tag`의 실패가 보충 결과로 `done`이 되면 제외에서 풀린다, 다른 실행·다른 항목은 그대로다, 보충 파일이 없어도 동작한다.
- 교집합: 사람은 제품·모델은 비제품인 항목, 사람은 비제품·모델은 제품인 항목이 나머지 축에서 빠지고 `n`·교집합 크기가 손계산 값과 같다. 교집합은 실행마다 따로 계산되어 두 실행의 `n`이 다를 수 있다.
- `content_type` 혼동 행렬이 합성 입력의 손계산 값과 같고 교집합 규칙이 적용되지 않는다(모든 비제외 항목 포함).
- `agreement()`: 값 쌍 목록에서 일치율을 내고, 빈 입력에서는 결과가 아니라 실패(예외 또는 명시적 빈 집합 결과)이며 0%를 반환하지 않는다. `claims`는 집합 일치다.
- 교집합이 빈 축은 `COMPARE_EMPTY_SET:<축>`과 종료 코드 3, 나머지 축은 계산된다.
- `has_cta`·`has_hook_segment` 결과에 정의 미확정 note가 붙고 다른 열에는 붙지 않는다.
- 출력에 합성 `text`(제목·캡션) 감시 문자열이 없다.
- `Makefile`: `verify` 레시피에 `pilot-compare`가 없고 타깃과 `.PHONY` 항목이 있다.

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

- 실제 `data/interim/pilot` 파일을 열거나 테스트에서 읽지 마라(CLI 코드가 런타임에 읽는 것은 사용자 실행이다). 이유: 열람 금지 경로이고 테스트는 합성 데이터만 쓴다.
- 라벨의 형식·값 검사보다 먼저 키 파일을 읽지 마라(`item_id`가 키 파일에 있는지의 검사만 키를 읽은 뒤에 한다). 이유: 라벨 파일이 없는데 모델 라벨을 먼저 보는 흐름이 되면 블라인드 규칙의 취지(사람 라벨이 모델 결과보다 먼저)에 어긋난다.
- 모델이 `product_creative`+category `other`로 본 항목을 "실패"로 제외하지 마라(분석 제외로 따로 센다). 이유: 파이프라인이 그 항목의 `hook`·`full`을 만들지 않는 것이 정상이다(2026-11-13 정정).
- 교집합 규칙 밖의 항목(사람이나 모델이 제품이 아닌 항목)을 나머지 축 비교에 넣지 마라, 빈 교집합을 0%로 보고하지 마라. 이유: 사전 등록 규칙이고 비제품 항목의 빈 열이 불일치로 세어지거나 빈 집합이 0%로 읽히면 일치율이 왜곡된다(FP-C03의 "빈 집합" 방지).
- `content_type` 축에 교집합 규칙을 적용하지 마라. 이유: 선별 정확도(혼동 행렬)는 모든 항목을 보아야 한다.
- 한 실행이라도 실패한 항목을 축별로 달리 처리하지 마라(항목 단위 제외). 이유: 두 실행 비교의 모집단이 축마다 달라진다.
- 시범 시트·키 파일·보충 파일을 쓰거나 고치지 마라(읽기만). 이유: 사용자 라벨링이 끝난 산출물이다.
- 모델이 고른 값(라벨 원문)이나 제목·캡션을 출력·로그에 남기지 마라. 이유: 결과는 일치율과 건수만이다. 정확도의 최종 판정은 E1(`e1-scorer`)에서 한다.
