# Step 27: review-fixes

## 설계 검토 기록

**배경(코드 리뷰 `/code-review medium 50`, 조언 세션 승인)**: PR #50 리뷰 지적 중 코드로 확인된 4건을 고친다. (#1) 비용 상한·일일 한도로 멈출 때 중단된 팔의 placeholder `failed` 기록이 `records.jsonl`에 남아 재개 때 완료로 건너뛰어지고 최저점으로 집계된다. (#2) `parse_preregistration`이 동결 라벨이 아닌 줄의 중복까지 `FROZEN_VALUE_MISMATCH`로 거부해 사전 등록 후 정정 기록 등이 final 가드를 막을 수 있다. (#3) `check_run` final 모드가 `groups`를 검증하지 않는다. (#7) `score_answer`의 `evidence_hit_rate`가 중복 id를 그대로 세 부풀 수 있다. **사전 등록 문장 24개·문장 해시 고정 테스트 세 곳·동결 값은 건드리지 않는다.**

**식별자 전수 대조(현재 코드, 모두 열어 확인)**
- `eval/e2e5_live.py`: `_run_batch(args, items, identity, set_hash, root, rows, *, settings, assemble, single_builder, chat_fn, structured_factory, environ, env_file, out, prior_score_spend)`(`:521`; `previous_spend = fsum(r.spent_usd for r in rows) + prior_score_spend`(`:543`); 팔마다 `before = len(read_entries(...).entries)`, `result, stopped = {"kind": "failed"}, None`; `run_arm` 예외 처리: `CostCapExceeded` → `stopped = "COST_CAP_REACHED"`, `LlmCallError`의 `ErrorKind.DAILY_LIMIT`/`CREDITS_DEPLETED` → `stopped = "DAILY_LIMIT"`, 그 밖 `Exception` → `result = {"kind": "failed"}`; `stopped = stopped or watch.stopped`; **그 뒤 `_record(...)`로 만든 행을 `records.jsonl`에 항상 append한다**; `if stopped:`는 append 뒤에 `STOPPED …`를 출력하고 `return 2`), 재개 키 `seen = {(r.item_id, r.arm, r.repeat) for r in rows}`, `main`의 메타 `run.json`(`mode`·`identity`·`evalset_hash`·`item_ids`·`scoring_spent_usd`·`repeats`, `_json_write(metadata_path, metadata)`는 run 시작 때 `:1014` 부근, `scoring_spent_usd` 갱신 `:1063-1066`), `run` 호출부의 `prior_score_spend=metadata["scoring_spent_usd"]`(`:1031`)와 `score`의 `previous_spend = fsum(r.spent_usd for r in rows) + metadata["scoring_spent_usd"]`(`:1036-1038`), `ledger_delta(path, before)`(`spent_usd` 포함, 불변).
- `eval/freeze_guard.py`: `parse_preregistration(text)`(`:96-105`: 줄마다 첫 `:`로 라벨·값을 나누고 **같은 라벨이 두 번 나오면 `FreezeError("FROZEN_VALUE_MISMATCH")`**), `check_run`(`:127-`: `mode == "dev"`면 `"test" in groups`일 때만 `WORKSPACE_GROUP_INVALID`; `mode != "final"`이면 `WORKSPACE_GROUP_INVALID`; **final에서는 `groups`를 읽지 않는다**; `values = parse_preregistration(text)`(`:177`); 점검 라벨 = `REQUEST_HASH_LABEL`·`QUESTION_HASH_LABEL`·`frozen_values()`의 키·`extra`의 키), 호출자: `e2e5_live.main`(`groups={"test"}`)·`e3_live.main`(`groups={split}`, final이면 `{"test"}`)·`isolation_live`(`groups={"isolation"}`).
- `eval/e3_live.py:220 score_answer`: `evidence = answer.evidence_ids`; `evidence_hit_rate = sum(id_ in truth.evidence_ids for id_ in evidence) / len(evidence)`(정답 증거가 없으면 `None`, 제출이 비면 0.0).

**상수 단언 grep(전수, 값이 달라지는 기존 테스트)**
- `tests/test_e2e5_live.py:274-288 test_batch_stops_on_provider_limits`: 한도로 멈춘 뒤 `len(records.jsonl 줄) == 1`을 단언한다 → **의도된 동작 변경으로 `== 0`(또는 파일 없음)이 되고**, `run.json`의 `interrupted_spent_usd`가 그 시도의 원장 증가분과 같음을 새로 단언한다. 같은 테스트의 `len(rig.calls) == 1`·`"STOPPED" in output`·`code != 0`은 유지한다. `:583-595`(`watch.stopped == "DAILY_LIMIT"`)·`:688-693`(`"DAILY_LIMIT" in output`)은 영향이 없는지 확인한다. `:385 monkeypatch.setattr(live, "_run_batch", batch)`의 가짜는 새 인자를 받을 수 있어야 한다(시그니처 확인 후 필요하면 `**kwargs`). `:1207`(`STOPPED BUDGET_REACHED`)은 팔 시작 전 검사라 불변이다.
- `tests/test_freeze_guard.py:171-190 test_parse_lines_and_reject_duplicates`·`test_empty_values_do_not_hide_duplicate_labels`: **`parse_preregistration(text)`를 인자 없이 부르는 기본 동작(모든 중복 거부)은 그대로**라 불변이다. `tests/test_prereg.py`의 `parse_preregistration` 호출(`:189`·`:235`·`:319`·`:618`·`:644`·`:877`)도 기본 호출이라 불변이다.
- `tests/test_freeze_guard.py`·`tests/test_prereg.py:204`·`tests/test_e3_live.py:379`·`tests/test_isolation_live.py`의 `check_run(mode="final", groups=…)` 호출은 모두 `{"test"}` 또는 `{"isolation"}`이다(전수 확인하고 다른 값을 넘기는 곳이 있으면 `blocked`로 보고).
- `tests/test_e3_live.py:482 test_evidence_ratio_counts_submitted_ids_and_count_tolerance`: `evidence_ids=["youtube:a", "youtube:a", "wrong"]`에서 `evidence_hit_rate == pytest.approx(2 / 3)`를 단언한다(중복 포함) → 새 정의에서는 중복 제거 제출 id `["youtube:a", "wrong"]`에서 1건이 정답 증거라 **`1 / 2`로 갱신**한다(테스트 이름·의도는 "제출된 id 기준, 중복은 한 번만"으로 맞춘다). `count` 허용 오차 단언은 유지한다. `:440-442`의 다른 `evidence_hit_rate` 단언(`2 / 3` 등)이 중복 없는 입력이면 불변이다(전수 확인).

**새 칸 대응표**: `run.json["interrupted_spent_usd"]`(중단된 시도의 원장 증가분 → `run`·`score`의 `previous_spend` → 예산 검사; 키가 없으면 0.0), `parse_preregistration(text, *, strict_labels=None)`의 `strict_labels`(`check_run`이 점검 라벨 집합 전달 → 그 라벨의 중복만 거부).

**옛 run 처리(보고 사항)**: 이 step 이전의 `records.jsonl`에서 중단으로 남은 `failed` 기록은 일반 실패(`failed`) 기록과 **구별할 수 없다**(상태·필드가 같다). 그래서 옛 기록은 이전처럼 완료된 시도로 읽는다(재개 때 건너뜀). 옛 dev 스모크 run은 폐기하고, final 실행은 이 step 이후 새 `--run-id`로 시작한다는 것을 사용자 안내로 남긴다. `run.json`에 `interrupted_spent_usd`가 없으면 0.0으로 읽는다.

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건(합성 테스트만).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 모델 호출 직전 누적액 검사, 한도 429는 재시도하지 않고 배치를 멈춰 남은 항목을 대기 상태로 둔다(중단된 항목은 완료로 기록하지 않는다), 동결된 기준은 결과를 본 뒤 바꾸지 않는다
- `/src/beautyads/eval/e2e5_live.py`(`_run_batch`·`main`의 run/score 구간·`ledger_delta`), `/src/beautyads/eval/freeze_guard.py`(전체), `/src/beautyads/eval/e3_live.py`(`score_answer`)
- `/tests/test_e2e5_live.py`(`rig`·`:274-290`·`:370-400`·`:580-700`·`:1190-1210`), `/tests/test_freeze_guard.py`(전체), `/tests/test_e3_live.py`(`:440-495`), `/tests/test_prereg.py`(`check_run` 사용부, 읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/e2e5_live.py`, `src/beautyads/eval/freeze_guard.py`, `src/beautyads/eval/e3_live.py`, `tests/test_e2e5_live.py`, `tests/test_freeze_guard.py`, `tests/test_e3_live.py`

열람 금지 경로: `data/interim/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로 `data/interim/e2e5/`)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `src/beautyads/eval/e2e5_live.py`, `src/beautyads/eval/freeze_guard.py`, `src/beautyads/eval/e3_live.py`, `tests/test_e2e5_live.py`, `tests/test_freeze_guard.py`, `tests/test_e3_live.py`

리뷰 지적 4건을 고친다. **모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: `interrupted_spent_usd`, `strict_labels`

**1. 중단된 팔은 기록하지 않는다(`eval/e2e5_live.py`, #1)**
- `_run_batch`가 `metadata`(딕셔너리)와 `metadata_path`를 받게 한다(호출부 `main`에서 `run.json`의 값을 그대로 넘긴다). `previous_spend = fsum(r.spent_usd for r in rows) + prior_score_spend + metadata.get("interrupted_spent_usd", 0.0)`다(**한 번만 합산**: 이 값은 현재 배치의 `ledger_total - baseline` 증가분과 겹치지 않는다. 중단 시점에는 현재 배치가 곧바로 끝나므로 이중 계산이 없다).
- `stopped`가 참인 시도(`COST_CAP_REACHED`·`DAILY_LIMIT`·`watch.stopped`)는 **`records.jsonl`에 행을 추가하지 않는다.** 대신 그 시도의 원장 증가분(`ledger_delta(...)["spent_usd"]`)을 `metadata["interrupted_spent_usd"]`에 더해 `run.json`에 저장하고(`_json_write(metadata_path, metadata)`) 기존처럼 `STOPPED …`를 출력하고 `return 2`한다. 일반 실패(`failed`, `stopped`가 아닌 예외)는 이전처럼 기록한다. `REQUEST_FAILED …` 출력·종료 코드 3도 불변이다.
- 재개하면 중단된 (item, arm, repeat)는 기록이 없으므로 `seen`에 없어 **처음부터 다시 실행**된다.
- `score`의 `previous_spend`(`:1036-1038`)에도 `metadata.get("interrupted_spent_usd", 0.0)`를 더한다. 새 `run.json`을 만들 때는 `"interrupted_spent_usd": 0.0`을 넣고, 키가 없는 옛 `run.json`은 `.get(..., 0.0)`으로 읽는다(저장 형식 호환). `dry-run`·`report`·`sheet` 흐름은 불변이다.

**2. 중복 라벨 완화(`eval/freeze_guard.py`, #2)**
- `parse_preregistration(text, *, strict_labels=None)`: `strict_labels`가 `None`이면 **현재 동작 그대로**(모든 중복 거부)다. 집합이 주어지면 그 집합에 속한 라벨이 두 번 나올 때만 `FreezeError("FROZEN_VALUE_MISMATCH")`를 던지고, 그 밖의 라벨의 중복 줄은 **첫 번째 값을 유지하고 나머지는 무시한다**(예외 없음).
- `check_run`은 `values = parse_preregistration(text, strict_labels={REQUEST_HASH_LABEL, QUESTION_HASH_LABEL, *frozen_values(), *(extra or {})})`로 부른다(동결·해시·`extra` 라벨의 중복은 계속 거부한다). 나머지 점검 순서·오류 코드는 불변이다.

**3. final의 `groups` 검증(`eval/freeze_guard.py`, #3)**
- `check_run`의 `mode == "final"` 분기에서 `groups`가 비어 있거나 `{"test", "isolation"}` 밖의 값을 포함하면 `FreezeError("WORKSPACE_GROUP_INVALID")`(예: `{"dev"}`·`{"test", "dev"}`·`set()`)다. 위치는 `mode != "final"` 검사 바로 뒤, 사전 등록 읽기 앞이다(기존 호출자는 모두 유효한 groups라 순서 영향이 없다). `dev` 모드 동작은 불변이다.

**4. 중복 증거 id(`eval/e3_live.py`, #7)**: `score_answer`가 제출 증거 id를 `list(dict.fromkeys(answer.evidence_ids))`로 중복 제거한 뒤 같은 계산(`정답 증거에 있는 수 / 제출한 고유 id 수`)을 한다. 정답 증거가 없으면 `None`, 제출이 비면 0.0인 기존 규칙·`correct` 판정·반환 키는 불변이다.

**테스트(합성 데이터·`tmp_path`, 모델·접속 없음)**
- `tests/test_e2e5_live.py`: (1) 위 "상수 단언 grep"의 갱신(한도 중단 시 기록 0행, `interrupted_spent_usd`가 원장 증가분과 같음; `COST_CAP_REACHED`·`DAILY_LIMIT` 둘 다). (2) 재개: 중단된 팔이 처음부터 다시 실행되고 기록이 한 번만 생긴다(가짜 `ask` 호출 횟수·`records.jsonl`). (3) **예산에 한 번만 합산**: 중단 지출 S와 예산 B를 정해(예: S가 B의 대부분) 재개한 배치가 `previous_spend`에 S를 정확히 한 번 반영한다(이중 계산이면 즉시 `BUDGET_REACHED`가 되고, 한 번 계산이면 남은 예산만큼 실행됨을 합성 팔 비용으로 확인). (4) `score`의 예산 검사가 `interrupted_spent_usd`를 포함한다(그 값만으로 예산에 닿으면 `BUDGET_REACHED`). (5) `interrupted_spent_usd`가 없는 옛 `run.json`이 읽히고 0.0으로 취급되며 이어서 실행 가능하다. (6) 일반 실패(`stopped`가 아닌 예외)는 여전히 `failed`로 기록되고 다음 팔로 넘어간다(종료 코드 3). (7) 옛 형식 `records.jsonl`(중단 `failed` 포함)은 그대로 읽히고 그 항목은 완료로 취급된다.
- `tests/test_freeze_guard.py`: (8) 기본 호출은 모든 중복을 거부한다(기존 테스트). (9) `strict_labels` 집합이 주어지면 집합 밖 라벨의 중복은 첫 값을 유지하며 통과하고 집합 안 라벨(동결·해시·`extra`)의 중복은 `FROZEN_VALUE_MISMATCH`다. (10) **`check_run` 통합**: 사전 등록 문서에 비동결 라벨의 중복 줄(예: `날짜: …`가 두 번)이 있어도 통과하고, 동결 라벨·해시 라벨·`extra` 라벨 각각의 중복 줄은 `FROZEN_VALUE_MISMATCH`다(매개변수화). (11) final에서 `groups`가 `set()`·`{"dev"}`·`{"test","dev"}`이면 `WORKSPACE_GROUP_INVALID`이고(사전 등록 읽기·git 호출 이전: 가짜 git 호출 0건), `{"test"}`·`{"isolation"}`·`{"test","isolation"}`은 통과한다. (12) dev 모드 동작 불변.
- `tests/test_e3_live.py`: (13) `evidence_ids=["a","a","wrong"]` → 1/2(위 갱신), 모두 고유한 경우 값 불변, 전부 같은 id 반복(`["c1","c1","c1","x"]`, 정답 `["c1"]`)은 1/2, 제출이 비면 0.0, 정답 증거가 없으면 `None`.
- 합성 문장·분류 값을 기대값으로 굳히지 않는다(형식·건수·코드·계산값만 검사).

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

- 사전 등록 문장(`REQUIRED_SENTENCES` 24개)·문장 해시 고정 테스트·동결 값(`frozen_values()`의 값)·판정 로직·판정 임계값을 바꾸지 마라. 이유: 이 step은 리뷰 지적 4건만 고친다.
- 한도로 멈춘 시도를 `failed`가 아닌 다른 상태로 `records.jsonl`에 남기거나 중단 지출을 예산에서 빼거나 두 번 더하지 마라. 이유: 중단된 항목은 완료로 기록하지 않고 지출은 한 번만 합산한다(AGENTS.md).
- `parse_preregistration`의 기본 호출(인자 없음) 동작과 동결·해시·`extra` 라벨 중복 거부를 약화하지 마라. 이유: 완화는 점검 대상이 아닌 라벨의 줄에만 적용한다.
- `eval/e2_scoring.py`·`eval/prereg.py`·`eval/vector_baseline.py`·`eval/isolation_live.py`·`llm/`·`agents/`·`api/`를 수정하거나 새 의존성을 추가하지 마라. 이유: 허용 범위 밖이다(필요하면 `blocked`로 보고).
- 기존 테스트의 단언을 약화하지 마라(위 "상수 단언 grep"에 적힌 한도 중단 기록 수·`evidence_hit_rate` 기대값 갱신과 가짜 시그니처 호환만 허용). 이유: 이미 통과한 step의 계약이며 변경은 의도된 동작 변경에만 한정한다.
