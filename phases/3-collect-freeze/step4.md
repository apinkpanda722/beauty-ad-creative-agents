# Step 4: cost-recalc

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P3 `cost-recalc` 행과 §8 결정 6번
- `/docs/COST_ESTIMATE.md` — "보정"과 "확정 계획" 절(thought 토큰, 공급사별 상한). **이 파일은 고치지 않는다(읽기만)**
- `/src/beautyads/obs/ledger.py` — `LedgerEntry`, `read_entries`, `provider_total`
- `/src/beautyads/eval/pilot_run.py` — 시범 `purpose` 이름 규칙(`pilot-<태그>`, `pilot-<태그>-retry`)
- `/README.md`, `/Makefile`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/cost_recalc.py`(새 파일), `Makefile`, `README.md`, `tests/test_cost_recalc.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/cost_recalc.py`, `Makefile`(`cost-recalc` 타깃과 `.PHONY` 추가에 한함, `verify` 불변), `README.md`(cost-recalc 절 추가에 한함), `tests/test_cost_recalc.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

소비자 테스트 점검 결과: `scripts/test_hooks.py`는 임시 디렉터리에 자기 `Makefile`을 만들어 쓰므로 영향이 없다. `tests/test_compose.py`·`tests/test_slice.py`·`tests/test_collect.py`·`tests/test_pilot.py`는 저장소 `Makefile`을 읽지만 `.PHONY`는 부분집합으로, 기존 타깃의 레시피 원문은 정확히, `verify` 레시피는 `live-`가 없음을 단언한다. 따라서 **새 타깃은 추가하되 기존 타깃의 레시피 원문·`verify` 레시피·그 뒤의 빈 줄 형식은 바꾸지 않는다.** `tests/test_architecture.py`는 새 모듈에 계층 규칙을 적용한다(통과해야 한다). 이 파일들은 수정하지 않는다. 깨지면 고치지 말고 `blocked`로 보고한다.

비용 원장(`data/manifest/costs.jsonl`)으로 소재 분석 비용을 다시 계산하는 읽기 전용 CLI다(`make cost-recalc` → `uv run python -m beautyads.eval.cost_recalc`). **네트워크·DB·모델·`.env`를 쓰지 않고 원장을 읽기만 한다.** `eval/`에 둔다. 이 step 뒤에 사용자가 `thinking_level`과 Gemini 상한을 정한다.

### 입력과 계산

- 원장은 `obs.ledger.read_entries`로 읽는다(`--ledger`, 기본 설정의 원장 경로). 읽을 수 없거나 항목이 깨졌으면 `LEDGER_UNREADABLE`, 파싱 못 한 줄 수는 보고한다.
- **실행 묶음**: `purpose`가 `pilot-<태그>` 또는 `pilot-<태그>-retry`인 항목을 태그별로 묶는다(`minimal`, `default`). 다른 purpose(`live-slice-hook` 등)는 "기타"로 따로 합계만 낸다. `provider`는 `gemini`만 본다.
- 태그별로 호출 수, 비용 합계, 호출당 입력·출력·thought 토큰의 평균·p50·p90·최댓값, 호출당 비용의 평균·p50·p90·최댓값을 낸다(`cached_tokens`가 있으면 따로 보인다). `cost_source`가 `response_cost`가 아닌 항목 수를 보고한다(있으면 비용이 추정치임을 표시).
- **호출 종류별 비용은 원장에서 구분할 수 없다**(`purpose`에 축이 들어 있지 않다). 그래서 이 CLI는 종류별 환산을 하지 않고, 호출당 비용 분포와 `--pilot-items`(시범 항목 수, 기본 20)로 **소재당 호출 수 = 호출 수 ÷ 항목 수**와 **소재당 비용(측정값)** 을 낸다. 시범의 제품 소재 비율이 그 값에 섞여 있다는 사실을 출력에 적는다.
- **전체 분석 견적**: `--items N`(필수, 분석할 소재 수)로 태그별 견적을 낸다. 세 시나리오를 **가정으로 표시**한다: (낮음) 시범의 소재당 비용 × N × 0.5, (기준) 시범의 소재당 비용 × N, (높음) 호출당 비용 p90 × 시범의 소재당 호출 수 × N × 1.25. 각 시나리오의 계수(0.5, 1.25)는 코드 상수이고 출력에 "가정(미실측)"이라고 적는다. **모든 숫자에 "측정값(시범 20건, 실측 N호출)" 또는 "가정"을 붙인다.**
- **상한 비교**: 현재 Gemini 누적(`provider_total`), 상한($12, `settings`의 값)과 상한을 올릴 경우의 후보(`--candidate-cap`, 기본 14)에 대해 시나리오별 `누적 + 견적`이 상한 안인지 보고한다. 이것은 **결정이 아니라 보고**이고 상한이나 `thinking_level`을 이 CLI가 바꾸지 않는다.
- `minimal` 대비 `default`의 호출당 비용 비율과 소재당 비용 비율도 낸다(thought 토큰 차이가 큰지 보기 위해).
- **호출 종류가 `purpose`에 들어 있는 항목**(`analyze-target-content_type`·`-hook`·`-full`, step 6 이후 원장)이 있으면 종류별 호출 수·토큰·비용을 따로 집계해 출력한다(이 step 시점의 원장에는 없으므로 없으면 "종류별 측정 없음"이라고 적는다). 같은 CLI를 첫 배치 뒤에 다시 돌려 전체 견적을 재계산할 수 있게 한다.
- 출력: 사람이 읽는 표와 JSON 한 줄. 마지막 줄에 "시범 표본이 작다(20건, 소재 길이·제품 비율에 따라 크게 달라질 수 있음)"와 "정확한 종류별 비용은 `analyze-target`의 첫 실행에서 측정한다"를 적는다. `docs/COST_ESTIMATE.md`를 고치지 않는다(사용자가 결정한 뒤 갱신).
- 종료 코드: 0 성공, 2 입력 문제(`LEDGER_UNREADABLE`, `--items` 누락·0 이하), 3 시범 항목(해당 태그의 호출)이 없음(`COST_NO_PILOT_ENTRIES`).

### 반드시 있어야 하는 테스트

(합성 원장 JSONL을 tmp 경로에 만든다. 실제 원장을 읽지 않는다.)
- 태그별 묶음: `pilot-minimal`·`pilot-default`·`pilot-default-retry`·기타 purpose를 섞은 합성 원장에서 호출 수·합계가 손계산 값과 같고 retry는 해당 태그에 합산된다, 다른 `provider` 항목은 제외된다.
- 분포: 작은 합성 입력의 평균·p50·p90·최댓값이 손계산 값과 같다(기대값을 구현과 같은 공식으로 만들지 않는다).
- 견적: `--items`와 `--pilot-items`에서 세 시나리오 값이 손계산 값과 같고 출력의 모든 숫자에 "측정값" 또는 "가정" 표시가 붙는다.
- 상한 비교: 누적+견적이 상한 안/밖인 합성 케이스에서 보고가 맞다. 이 CLI가 설정·상한 값을 바꾸는 코드를 갖지 않는다.
- 오류: 원장이 없거나 깨진 줄이 있으면 `LEDGER_UNREADABLE`(깨진 줄 수 보고), `--items` 누락은 오류 종료, 시범 항목이 없으면 `COST_NO_PILOT_ENTRIES`와 종료 코드 3.
- 이 CLI가 네트워크·DB 접속 함수를 부르지 않는다(import 목록 또는 가짜로 확인).
- `Makefile`: `verify` 레시피에 `cost-recalc`가 없고 타깃과 `.PHONY` 항목이 있다.

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

- `docs/COST_ESTIMATE.md`, `config/`의 상한 값, 설정의 `thinking_level`을 이 CLI로 바꾸지 마라. 이유: 상한과 `thinking_level`은 사용자가 이 결과를 보고 결정한다(PHASES §8 결정 6번).
- 호출 종류(`content_type`·`hook`·`full`)별 비용을 원장에서 추정해 사실처럼 출력하지 마라. 이유: 원장의 `purpose`에 축이 없어 구분할 수 없다. 추정은 "가정"으로 표시한 시나리오로만 낸다(FP-C06: 문서의 추정값을 계획의 근거로 쓰지 않는다).
- 시범 한 번의 소재당 비용을 1,500건(또는 N건)에 곱한 값을 하나의 숫자로 단정하지 마라. 이유: 시범은 20건이고 제품 비율·영상 길이에 따라 달라진다. 범위와 가정 표시를 함께 낸다.
- 원장 파일을 쓰거나 고치지 마라(읽기만). 이유: 원장은 상한 검사의 원본이다.
- 실제 원장(`data/manifest/costs.jsonl`)을 테스트에서 읽지 마라. 이유: 테스트는 합성 데이터만 쓴다.
