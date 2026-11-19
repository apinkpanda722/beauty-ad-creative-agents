# Step 20: e2e5-records

## 설계 검토 기록

**배경(조언 세션 승인)**: dev 스모크에서 두 가지가 드러났다. (1) E5 "끔"에서 요청당 입력 토큰 합계는 켬과 거의 같았다(기획 호출만 끔이 약 70% 많음; 리서치·평가 호출이 대부분이고 리서치 호출 수가 실행마다 3~4회로 달라 합계가 3~5천 흔들림). (2) req-dev-0002의 Supervisor 기획안이 사용자 지정 포맷(`ugc_style`)을 따르지 않았는데 brief·지배 축이 기록되지 않아 원인을 코드로 판정할 수 없다. 이 step은 **기록 보강**이다: 기록에 목적별 입력 토큰·호출 수와 Supervisor 팔의 brief 닫힌 값·지배 축을 남기고, 보고에 E5 보조 표와 지정 축 준수 표를 더하며, 사전 등록에 E5 문장을 추가한다. **판정 로직(`e2_scoring.analyze`)은 바꾸지 않는다.**

**식별자 전수 대조(현재 코드, 모두 열어 확인)**: `eval/e2e5_live.py`(`:81 class _RecordedArm(ArmRecord)`: `prereg_commit`·`prompt_versions` 두 칸을 더한 runner 전용 서브클래스, `:118 ledger_delta(path, before)`(키 `input_tokens`·`model_calls`·`spent_usd`), `:377 _json_write`, `:385 _load_records`, `:395 _plain(rows)`(= `r.model_dump(include=set(ArmRecord.model_fields))`, **runner 전용 칸은 `analyze`·`blind_items`로 넘어가지 않는다**), `:399 _record(item, arm, result, *, run_id, identity, set_hash, delta, latency)`, `:533`의 호출 `delta=ledger_delta(settings.ledger_path, before)`(`before = len(read_entries(...).entries)`), `:561 _report(rows, items, root, metadata, out)`), `eval/e2_scoring.py`(읽기 전용: `ArmRecord`는 `extra="forbid"`, 칸 `status: Literal["plan","no_evidence","limit","failed","out_of_scope"]`·`input_tokens`·`model_calls` 등), `agents/supervisor.py`(`run_request` 결과 딕셔너리: `"brief"`: `state["sv_brief"]`(= `ResearchBrief`의 `model_dump`: `goal`·`category`·`claim`·`hook_type`·`angle`·`format`·`skin_concern`·`output`·`max_tool_calls`), `"handoff"`: 안에 `"pattern_context"`), `domain/supervisor.py:162 pattern_context`(반환의 `"dominant_axes"`: 항목 `{"axis", "values", "share"}`의 리스트, `"weak_axes"`, `"distribution"`), `obs/ledger.py`(`LedgerEntry`: `purpose`·`input_tokens`; `read_entries(path).entries`), `eval/evalset.py`(`RequestItem.axes_used`: 요청 템플릿에 따라 `["category"]`·`["category","format"]`·`["hook_type"]`·`["angle"]`).

**상수 단언 grep**: `tests/test_e2e5_live.py:317-328 test_ledger_delta_and_axes_are_code_derived`가 `live.ledger_delta(path, 1) == {"input_tokens": 33, "model_calls": 3, ...}` **정확 일치**를 단언한다 → **`ledger_delta`는 바꾸지 않고** 새 함수를 따로 만든다. `result()` 헬퍼(`:45-54`)는 `"handoff": {"evidence_ids": [...], "pattern_context": {"distribution": [{"axis": "format"}]}}`이고 `brief`가 없다 → 새 칸은 모두 기본값이 있어 이 헬퍼 결과에서도 레코드가 만들어져야 한다. `entry(...)` 헬퍼(`:305`)로 합성 원장 항목을 만든다. `tests/test_prereg.py`의 문장 수 단언(`== 17`)은 `== 18`로 갱신한다. 결과 틀 테스트는 새 행도 빈 칸임을 단언하게 갱신한다.

**새 칸 대응표**: `input_tokens_by_purpose`·`model_calls_by_purpose`(`ledger_purpose_totals` → `_RecordedArm` → `records.jsonl` → E5 보조 표·`e5_supplement.json`), `brief_axes`(Supervisor·off 팔 결과의 `brief`에서 닫힌 값 6개만 → 기록 → 지정 축 준수 표), `dominant_axes`(`pattern_context.dominant_axes` → 기록 → 준수 표의 충돌 열), 사전 등록 18번째 문장(→ 결과 문서의 E5 예상 결과).

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건. 원장 증가분 계산만이다. 재스모크는 사용자가 한다(기존 스모크 기록에는 새 칸이 없다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 실제 호출은 사용자가 실행한다, 모델이 만든 값을 테스트 기대값으로 굳히지 않는다, 키·응답 본문·요청 본문을 기록에 남기지 않는다
- `/src/beautyads/eval/e2e5_live.py`(전체), `/src/beautyads/eval/e2_scoring.py`(읽기 전용: `ArmRecord`·`analyze`), `/src/beautyads/eval/prereg.py`(`REQUIRED_SENTENCES`·`render_results_template`), `/src/beautyads/obs/ledger.py`(`read_entries`·`LedgerEntry`, 읽기 전용), `/src/beautyads/domain/supervisor.py`(`pattern_context`, 읽기 전용), `/src/beautyads/domain/research.py`(`ResearchBrief`, 읽기 전용)
- `/tests/test_e2e5_live.py`(전체: `rig`·`result`·`entry`·report 테스트 `:440-470`), `/tests/test_prereg.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/e2e5_live.py`, `src/beautyads/eval/prereg.py`, `tests/test_e2e5_live.py`, `tests/test_prereg.py`

열람 금지 경로: `data/interim/`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.
수정 허용 경로: `src/beautyads/eval/e2e5_live.py`, `src/beautyads/eval/prereg.py`, `tests/test_e2e5_live.py`, `tests/test_prereg.py`

E2·E5 실행 기록에 목적별 입력 토큰과 brief·지배 축을 남기고 보고에 보조 표를 더하며 사전 등록 문장을 추가한다. **모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: `ledger_purpose_totals`, `brief_axes`, `dominant_axes`, `input_tokens_by_purpose`, `model_calls_by_purpose`

**1. 기록(`eval/e2e5_live.py`)**
- `ledger_purpose_totals(path, before) -> dict`: `read_entries(path).entries[before:]`을 목적별로 묶어 `{"input_tokens_by_purpose": {목적: 입력 토큰 합}, "model_calls_by_purpose": {목적: 호출 수}}`를 돌려준다(`ledger_delta`와 같은 구간, 이미지 목적도 그대로 센다; 새 호출 없음). **`ledger_delta`는 그대로 둔다.**
- `_RecordedArm`에 칸을 더한다: `input_tokens_by_purpose: dict[str, int] = Field(default_factory=dict)`, `model_calls_by_purpose: dict[str, int] = Field(default_factory=dict)`, `brief_axes: dict[str, str | None] | None = None`, `dominant_axes: list[dict] | None = None`. 새 칸이 없는 옛 `records.jsonl`도 읽혀야 한다(`_load_records`).
- `_record(...)`가 새 인자(`by_purpose`)를 받아 위 두 목적별 칸을 채운다(호출부 `:533`에서 `ledger_purpose_totals(settings.ledger_path, before)`를 넘긴다). Supervisor·off 팔(`arm != "single"`)이면 결과의 `brief`에서 **닫힌 값 6개만**(`category`·`claim`·`hook_type`·`angle`·`format`·`skin_concern`) `brief_axes`로, `handoff.pattern_context.dominant_axes`에서 항목마다 `axis`·`values`·`share`만 `dominant_axes`로 기록한다. **`goal`(과제 문장)·요청 본문·정답·도구 결과 본문은 기록하지 않는다.** 단일 팔은 둘 다 `None`이다. 결과에 `brief`나 `pattern_context`가 없으면 `None`이다.
- `_plain`은 바꾸지 않는다(새 칸이 `analyze`·`blind_items`로 가지 않아야 한다).

**2. 보고(`_report`)**: 기존 출력은 그대로 두고 뒤에 두 표를 더하고 각각 JSON으로도 저장한다(`root / "e5_supplement.json"`, `root / "axis_adherence.json"`; 건수·합계·비율만, 본문 없음).
- **E5 보조 지표(참고용, 판정에 쓰지 않음)**: Supervisor와 off를 둘 다 가진 요청 중 두 기록 모두 `input_tokens_by_purpose`가 비어 있지 않은 쌍만 쓴다. 목적별로 켬·끔 입력 토큰 합계, 요청당 평균, 변화율 `1 - 켬/끔`(끔이 더 적으면 음수, 끔이 0이면 "해당 없음"), `plan` 목적의 요청 단위 값, 리서치(`research`) 호출 수 평균(`model_calls_by_purpose`)과 호출당 입력 토큰, 리서치 제외 합계(전체 − `research`), 사용한 쌍 수와 값이 없어 뺀 쌍 수를 낸다. 표 아래에 한 줄 주석: "리서치 호출 수 변동이 합계를 수천 토큰 흔들 수 있다. 판정은 요청당 입력 토큰 합계 기준 그대로다."
- **지정 축 준수(코드 판정, 참고용)**: Supervisor·off 기록 중 `brief_axes`가 있고 기획안이 있는 것에 대해 축 `format`·`hook_type`·`angle`마다 (a) `brief_axes[축]`이 지정됨(`None`이 아님)인 건수, (b) 그중 기획안의 같은 축 값이 같은 건수(준수), (c) 지정된 축이 `dominant_axes`의 같은 축에 있고 지정 값이 그 `values`에 들어 있는 건수(지배 값과 충돌), (d) 요청의 `axes_used`에 그 축이 있는데 `brief_axes[축]`이 `None`인 건수(해석 누락)를 팔(supervisor·off)별로 센다. 값이 없는 기록(옛 기록)은 `unavailable` 건수로 따로 센다. 모델 호출 없이 기록 값만으로 계산한다.

**3. 사전 등록(`eval/prereg.py`)**
- `REQUIRED_SENTENCES` **끝에 18번째** 문장을 추가한다(기존 17개의 순서·문장 불변): (a) E5 판정은 요청당 입력 토큰 합계가 켬이 끔보다 30% 이상 적고 근거 유효율 차이의 95% 신뢰구간 하한이 -0.05보다 크다는 `docs/EVAL.md` 기준 그대로이며 둘 중 하나라도 못 넘으면 넘지 못한 쪽을 그대로 적는다. (b) 목적별 입력 토큰(특히 기획 호출)을 요청 단위로 합산한 값은 참고용 보조 지표이며 판정에 쓰지 않는다. (c) 리서치 호출 수가 실행마다 달라 합계가 수천 토큰 흔들릴 수 있다. (d) 예상 결과: 리서치·평가 호출이 입력 토큰의 대부분이고 도구 결과가 작아 합계 기준 30% 감소를 달성하지 못할 가능성이 높으며 그 경우 결과는 토큰 기준 미달로 그대로 보고한다(dev 스모크 2건에서 기획 호출 입력은 끔이 켬보다 약 70% 많았으나 요청당 합계 차이는 거의 없었다는 dev 관찰). `render_preregistration`의 번호 매김·인덱스 참조는 바꾸지 않는다.
- `render_results_template()`의 E5 행에 "목적별 입력 토큰(기획 포함, 참고용)"을, E2 행에 "지정 축 준수(코드 판정, 참고용)"를 더한다(빈 칸 틀, 수치 없음).

**테스트(합성 데이터·`tmp_path`, 모델·접속 없음)**
- `tests/test_e2e5_live.py`: (1) `ledger_purpose_totals`가 합성 원장 항목(여러 목적·토큰)에서 목적별 합계·호출 수를 손으로 센 값과 같게 내고 `before` 이전 항목은 세지 않는다. (2) 기존 `ledger_delta` 정확 일치 테스트가 그대로 통과한다. (3) 기록이 새 칸을 채운다: 가짜 `ask`가 합성 원장 항목을 추가하고 `brief`·`pattern_context.dominant_axes`를 포함한 결과를 돌려주면 `records.jsonl`의 `input_tokens_by_purpose`·`brief_axes`(6개 닫힌 값만, `goal` 없음)·`dominant_axes`(`axis`·`values`·`share`만)가 기대와 같고, 단일 팔은 `brief_axes`·`dominant_axes`가 `None`이다. (4) 기존 `result()` 헬퍼 결과(brief 없음)에서도 레코드가 만들어지고 `brief_axes`가 `None`이다. (5) 옛 형식 `records.jsonl`(새 칸 없음)이 로드되고 보고가 `unavailable`로 처리한다. (6) `_plain(rows)`의 키가 `ArmRecord.model_fields`와 같다(새 칸이 `analyze`로 넘어가지 않음)와 `analyze` 결과(`verdict_e2`·`verdict_e5`·`e5.token_reduction`)가 새 칸 유무와 무관하게 같다. (7) E5 보조 표: 합성 기록(목적별 토큰이 켬/끔 다름)에서 목적별 합계·변화율·요청당 평균·`plan` 값·리서치 호출 수 평균·리서치 제외 합계가 손으로 센 값과 같고 끔이 0이면 "해당 없음", 값이 없는 쌍은 뺀 쌍 수에 들어가며 `e5_supplement.json`에 본문(brief의 `goal`·요청 문장)이 없다. (8) 지정 축 준수 표: 지정·준수·지배 충돌·해석 누락·`unavailable` 건수가 합성 기록에서 손으로 센 값과 같다(합성 값은 닫힌 분류 값). (9) 판정이 보조 표의 영향을 받지 않는다(같은 기록에서 목적별 값만 바꿔도 `verdict_e5`가 같다).
- `tests/test_prereg.py`: (10) `== 18`과 18번째 문장 존재(`30%`·`참고용`·`리서치`·`토큰 기준 미달`·`그대로` 포함), 기존 17개 불변. (11) 결과 틀에 새 두 행이 빈 칸으로 있다.
- 합성 문장·분류 값을 기대값으로 굳히지 않는다(형식·건수·계산값만 검사).

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

- `eval/e2_scoring.py`의 `analyze`·`ArmRecord`·판정 로직과 `ledger_delta`의 반환 형태를 바꾸지 마라. 이유: 판정 기준은 동결되어 있고 정확 일치 테스트가 있다. 보조 지표는 `e2e5_live`에서만 계산한다.
- 요청 본문·`goal`·정답·도구 결과 본문·키를 기록·표·JSON·로그·예외 메시지에 넣지 마라. 이유: 기록에는 닫힌 값과 수치만 남긴다(AGENTS.md).
- 보조 표나 준수 표의 값으로 판정을 바꾸거나 `REQUIRED_SENTENCES`의 기존 문장을 고치지 마라. 이유: 참고용이며 사전 등록 문장은 기존 항목을 고치지 않는다(B-FP-043).
- `eval/e3_live.py`·`eval/evalset*.py`·`agents/`·`domain/`·`Makefile`을 수정하거나 새 의존성을 추가하지 마라. 이유: 허용 범위 밖이다(필요하면 `blocked`로 보고).
- 기존 테스트의 단언을 약화하지 마라(문장 수 갱신과 새 행 단언 추가만 허용). 이유: 이미 통과한 step의 계약이다.
