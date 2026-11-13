# Step 8: e1-scorer

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/EVAL.md` — E1 절(**동결된 판정 기준. 읽기만**: 사람 재검사 κ 0.7, 사람·모델 κ 0.6, 콘텐츠 유형 재현율 0.9)
- `/docs/results/e1_preregistration.md` — 사전 등록(비교 규칙·분모 규칙. 읽기 전용. 규칙이 없으면 `blocked`)
- `/docs/PHASES.md` — P3 `e1-scorer` 행과 `pilot-compare` 행
- `/src/beautyads/eval/pilot_compare.py` — `agreement`, 교집합·제외 규칙(이 모듈은 **추가에 한함**)
- `/src/beautyads/eval/e1_sampling.py`, `/src/beautyads/eval/e1_stage2.py` — 키 파일·시트 형식(1단계·2단계)
- `/src/beautyads/eval/sheets.py` — `label_columns`, 코드북 값
- `/src/beautyads/domain/labels.py`, `/src/beautyads/domain/jobs.py` — 결과 모델, `JobStatus`
- `/src/beautyads/pipeline/preflight.py` — `docker_running`·`tcp_reachable`
- `/README.md`, `/Makefile`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/e1_scorer.py`(새 파일), `src/beautyads/eval/pilot_compare.py`(추가에 한함), `Makefile`, `README.md`, `tests/test_e1_scorer.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/e1_scorer.py`, `src/beautyads/eval/pilot_compare.py`(공용 함수 추가에 한함, 기존 함수·동작·단언 불변), `Makefile`(`e1-score` 타깃과 `.PHONY` 추가에 한함, `verify` 불변), `README.md`(e1-score 절 추가에 한함), `tests/test_e1_scorer.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

소비자 테스트 점검 결과: `scripts/test_hooks.py`는 임시 디렉터리에 자기 `Makefile`을 만들어 쓰므로 영향이 없다. `tests/test_compose.py`·`tests/test_slice.py`·`tests/test_collect.py`·`tests/test_pilot.py`는 저장소 `Makefile`을 읽지만 `.PHONY`는 부분집합으로, 기존 타깃의 레시피 원문은 정확히, `verify` 레시피는 `live-`가 없음을 단언한다. 따라서 **새 타깃은 추가하되 기존 타깃의 레시피 원문·`verify` 레시피·그 뒤의 빈 줄 형식은 바꾸지 않는다.** `tests/test_architecture.py`는 새 모듈에 계층 규칙을 적용한다(통과해야 한다). 이 파일들은 수정하지 않는다. 깨지면 고치지 말고 `blocked`로 보고한다.

E1(소재 분석 정확도)의 채점기다(`make e1-score` → `uv run python -m beautyads.eval.e1_scorer`). **사람 라벨 파일이 없으면 시작하지 않는다.** 사용자가 직접 실행한다. `eval/`에 두고 SDK를 직접 import하지 않는다. 모델 결과는 DB의 `*@v1` 작업에서 읽는다(`store`의 함수). **이 step 안에서는 CLI를 실제 데이터로 실행하지 않는다. 테스트는 합성 데이터·가짜 저장소만 쓴다.**

### 입력

1. 1단계: 사람 라벨 `e1_stage1_sheet_labeled.csv`와 1단계 키 파일(`e1_stage1_key.json`). **멈춘 위치까지의 라벨만** 쓴다(`e1_stage2.stop_point` 재사용, 새로 구현하지 않는다).
2. 2단계: 사람 라벨 `e1_stage2_sheet_labeled.csv`(첫 라벨)와 7일 뒤 재라벨 `e1_stage2_sheet_relabeled.csv`, 2단계 키 파일.
3. 모델 결과: DB의 `content_type@v1`·`hook@v1`·`full@v1`을 키로 `get_job_results`로 읽는다.
- 라벨 파일이 없으면 `LABEL_FILE_MISSING`, 형식 오류는 `LABEL_FILE_INVALID`이고 **DB 접속 전에** 종료 코드 2다(라벨 검사가 먼저). 재라벨 파일이 없으면 재검사 κ만 `RELABEL_MISSING`으로 보고하고 나머지는 계산한다. 점검: `ENV_MISSING:POSTGRES_PASSWORD`, `DOCKER_DOWN`, `POSTGRES_UNREACHABLE`.

### 지표 (기준 숫자는 `docs/EVAL.md`에서 가져온 상수이고 **이 CLI는 기준을 바꾸지 않는다**)

- **콘텐츠 유형 재현율**(1단계, **모델 누락은 축별 κ가 아니라 이 재현율로 따로 판정한다**): 사람이 `product_creative`로 판정한 소재 중 모델도 `product_creative`로 본 비율(기준 0.9 이상). 사람×모델 **혼동 행렬**도 낸다. 모델 결과가 없는(작업이 `done`이 아닌) 소재는 재현율 분모에서 빼지 않고 "모델 결과 없음"으로 따로 세어 보고한다(분석이 안 된 소재가 재현율을 부풀리지 않게).
- **축별 일치율과 Cohen's κ**(2단계, 사람 대 모델): 닫힌 값 축과 불리언 열. **분모는 사람과 모델이 모두 `product_creative`로 본 교집합이다**(사전 등록 §5, `pilot-compare`와 같은 규칙, 제외 항목 규칙도 동일). **합격 판정(κ ≥ 0.6)도 이 교집합 값으로 한다.** 축마다 **커버리지 = 교집합 건수 ÷ 사람이 제품으로 본 건수**를 `n`과 함께 보고한다. 사전 등록 파일에 §5(교집합 규칙·커버리지)가 없으면 `blocked`로 보고한다. `agreement`(`pilot_compare`)를 재사용한다.
- **사람 재검사 κ**(2단계, 첫 라벨 대 7일 재라벨): 축별. 기준 0.7 미만이면 "정의 모호" 후보로 표시.
- **소구점(`claims`, 여럿 선택)**: 값(항목)별 정밀도·재현율(사람 대 모델), 사람 재검사도 같은 방식.
- κ를 정의할 수 없는 경우(한쪽이 한 값만 가짐, 기대 일치가 1)는 `KAPPA_UNDEFINED:<축>`이라고 보고하고 숫자를 지어내지 않는다. 표본이 비는 축은 `SCORE_EMPTY_SET:<축>`(0으로 쓰지 않음).
- **판정 표시**: 기준을 충족/미충족으로 표시하되 이것은 EVAL의 동결된 기준을 그대로 적용한 표시이며, 기준을 바꾸거나 완화하는 옵션을 만들지 않는다. `has_cta`·`has_hook_segment`처럼 v1 동결 전에 정의가 바뀐 축이 있었으면 사전 등록 파일의 기록을 따르며 코드에 예외를 하드코딩하지 않는다.
- 출력: 사람이 읽는 표(축, `n`, 일치율, κ, 기준 충족 여부)와 JSON 한 줄. 제목·캡션·라벨 원문은 출력하지 않는다. 종료 코드: 0 성공, 2 입력 문제, 3 일부 축 계산 불가.
- `Makefile`: `e1-score` 타깃을 `.PHONY`와 함께 추가한다. README에 입력 파일, 7일 재라벨 일정, 이유 코드 표를 쓴다.

### 반드시 있어야 하는 테스트

(합성 라벨 CSV·합성 키·가짜 저장소. 모델 라벨 값을 기대값으로 굳히지 않는다.)
- 라벨 파일이 없으면 `LABEL_FILE_MISSING`, 형식 오류는 `LABEL_FILE_INVALID`이고 **저장소 접속 함수가 불리지 않는다**(가짜로 감시). 재라벨 파일이 없으면 재검사 κ만 `RELABEL_MISSING`이고 나머지는 계산된다.
- 콘텐츠 유형 재현율: 합성 1단계(멈춘 위치 뒤의 라벨은 무시됨)에서 손계산 값과 같고, 혼동 행렬이 맞고, 모델 결과가 없는 소재가 분모에서 사라지지 않고 따로 세어진다.
- 교집합 규칙: 사람은 제품·모델은 비제품인 소재(누락)가 축별 κ의 분모에서 빠지고 커버리지 분자에 들어가지 않으며(커버리지 = 교집합 ÷ 사람 제품 수, 손계산 값), 누락은 콘텐츠 유형 재현율에만 반영된다. 합격 판정이 교집합 κ로 계산된다.
- Cohen's κ와 일치율이 작은 합성 입력의 손계산 값과 같다(기대값은 구현과 다른 방식으로 계산한 값), κ가 정의되지 않는 입력(한쪽이 모두 같은 값)에서 `KAPPA_UNDEFINED`이고 숫자를 내지 않는다, 빈 표본은 `SCORE_EMPTY_SET`.
- 재검사 κ: 첫 라벨과 재라벨의 합성 쌍에서 손계산 값과 같다.
- `claims`: 항목별 정밀도·재현율이 합성 집합 입력의 손계산 값과 같다(모델이 사람에게 없는 항목을 낸 경우, 빠뜨린 경우).
- 기준(0.7, 0.6, 0.9)은 상수 한 곳에 있고 경계값에서 충족 여부가 맞다. 기준을 바꾸는 옵션이 파서에 없다(옵션 목록 확인).
- 분모 규칙: 사전 등록 파일(tmp 합성)에 규칙이 없으면 시작하지 않는다.
- 출력에 합성 제목·캡션 감시 문자열이 없다. `pilot_compare`의 기존 테스트가 그대로 통과한다.
- `Makefile`: `verify` 레시피에 `e1-score`가 없고 타깃과 `.PHONY` 항목이 있다.

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

- `docs/EVAL.md`의 기준 숫자(κ 0.7·0.6, 재현율 0.9)를 바꾸거나 완화하는 옵션·코드를 만들지 마라. 이유: 동결된 판정 기준은 결과를 본 뒤 바꾸지 않는다(AGENTS.md).
- 라벨 검사보다 먼저 DB에서 모델 결과를 읽지 마라. 이유: 사람 라벨이 모델 결과보다 먼저여야 한다.
- 축별 합격 판정을 사람이 제품으로 본 소재 전체 분모로 계산하지 마라, 커버리지를 빼고 κ만 보고하지 마라. 이유: 사전 등록 §5 — 교집합 κ는 좁은 모집단의 값이므로 커버리지가 함께 있어야 읽힌다.
- 모델 결과가 없는 소재를 재현율 분모에서 조용히 빼지 마라. 이유: 분석이 안 된 소재가 빠지면 재현율이 부풀려진다(PHASES 변경 기록 #10, #29).
- κ를 정의할 수 없는데 0이나 1로 채우지 마라. 이유: 숫자를 지어내면 판정이 왜곡된다.
- 멈춘 위치 뒤의 1단계 라벨을 쓰지 마라. 이유: 표본이 편향된다.
- `pilot_compare.py`의 기존 함수·동작·단언을 바꾸지 마라(추가만). 이유: 시범 비교의 계약이다.
- 실제 `data/interim` 파일을 테스트에서 읽지 마라. 이유: 테스트는 합성 데이터만 쓴다.
