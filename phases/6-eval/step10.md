# Step 10: prereg-template

## 설계 검토 기록

**식별자 전수 대조(bb0e64f)**: `eval/freeze_guard.py`(step 2: 줄 형식 상수 `REQUEST_HASH_LABEL`·`QUESTION_HASH_LABEL`·`frozen_values`·`parse_preregistration`·`PREREG_PATH`), `eval/evalset.py`(`request_set_hash`·`question_set_hash`·`validate_set`·`E1_UNMET_AXES`·`E1_RELIABLE_AXES`·`EVALSET_DIR`), `eval/single_agent.py`(`single_agent_system_prompt`·`SINGLE_AGENT_PROMPT_VERSION`), `eval/e2_scoring.py`(`E2_RUBRIC`·`E2_SCORING_PROMPT_VERSION`·`SCORING_SEED`·`BOOTSTRAP_RESAMPLES`·`E2_SCORE_PURPOSE_CAP`·`MIN_STRATUM_N`·`E5_MIN_TOKEN_REDUCTION`·`E5_MIN_VALIDITY_LOWER`), `eval/vector_baseline.py`·`eval/e3_live.py`(`TOP_K`·`MAX_DOC_CHARS`·`CORPUS_FIELDS`·`ANSWER_PROMPT_VERSION`·`EMBED_PURPOSE_CAP`), `domain/supervisor.py`(`MIN_DOMINANT_SHARE`·`THIN_POOL_MAX`·`RequestLimits`), `domain/evaluation.py:10 PASS_MIN_SCORE`, `agents/planning.py`·`agents/evaluation.py`(버전·`_SYSTEM`), `docs/results/p5_dev_compare_preregistration.md`(형식 선례, 읽기 전용), `docs/EVAL.md`(**수정 금지**).

**상수 단언 grep**: 이 step의 새 상수(`REQUIRED_SENTENCES` 등)를 단언하는 기존 테스트 없음. `docs/results/`의 사전 등록 파일을 읽는 기존 테스트(`tests/test_p5_compare.py:189`가 `compare.PREREG_PATH`를 읽는다)는 P5 파일만 대상이므로 P6 문서를 새로 만들어도 영향이 없다. **`docs/EVAL.md`는 바꾸지 않는다**(절차 세부는 `docs/results/p6_preregistration.md`에만 적는다).

**새 칸 대응표**: 사전 등록 문서 줄(이 step의 생성기가 코드 값으로 씀 → step 2의 `parse_preregistration`·`check_run`이 읽음), 필수 문장 목록 `REQUIRED_SENTENCES`(이 step → 사전 등록 문서 → 사람이 읽음; 테스트가 문서에 모두 있음을 단언), 결과 문서 틀(이 step → 11-30 결과 문서 작성 때 사용).

**시점(조언 세션 결정)**: 세트 확정(11-26) 직후 세트 해시 계산 → 프롬프트·상수 동결 → 사전 등록 문서 생성 → **사용자가 요청할 때** 커밋(같은 커밋). 이 step은 생성기와 틀만 만들고 사전 등록 문서 자체는 만들지 않는다(문서는 사용자가 11-26에 생성기를 돌려 만든다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 동결된 기준은 결과를 본 뒤 바꾸지 않는다, 결과를 내기 전에 사전 등록 파일을 커밋한다
- `/docs/EVAL.md`(읽기 전용, 기준 숫자 불변), `/docs/results/e1_preregistration.md`·`/docs/results/p5_dev_compare_preregistration.md`(읽기 전용: 사전 등록 문서 형식·정정 기록 방식), `/docs/results/2026-11-19-e1-scoring.md`(읽기 전용: 미충족 축 표시 방침), `/docs/PROMPT_CHANGELOG.md`(읽기 전용)
- `/src/beautyads/eval/freeze_guard.py`, `/src/beautyads/eval/evalset.py`, `/src/beautyads/eval/single_agent.py`, `/src/beautyads/eval/e2_scoring.py`, `/src/beautyads/eval/vector_baseline.py`, `/src/beautyads/eval/e3_live.py`(step 2·4·5·8 산출물), `/src/beautyads/domain/supervisor.py`, `/src/beautyads/domain/evaluation.py`
- `/tests/test_freeze_guard.py`(읽기 전용: 줄 형식 파서 사례), `/tests/test_p5_compare.py`(읽기 전용: 사전 등록 문서를 읽는 기존 테스트)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/prereg.py`(새 파일), `tests/test_prereg.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/prereg.py`, `tests/test_prereg.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로, 평가 정답을 읽는 채점 함수)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

`docs/results/p6_preregistration.md`를 **코드 값에서 생성하는 생성기**와 결과 문서 틀을 만든다. 모델·접속 없음. **이 step에서는 `docs/results/` 아래에 파일을 만들지 않는다**(테스트는 `tmp_path`에만 쓴다). **테스트를 먼저 쓴다.**

새 식별자: `REQUIRED_SENTENCES`, `render_preregistration`, `render_results_template`, `main`

**`render_preregistration(*, request_hash, question_hash, extra, embedding, isolation_hash, today) -> str`**
- 입력은 모두 인자다(해시는 호출자가 `evalset`으로 계산해 넘긴다). 반환은 사전 등록 문서 전문(마크다운). **`freeze_guard`의 줄 형식 상수를 import해 같은 형식**(`"{라벨}: {값}"`)으로 아래 줄을 쓴다: 세트 해시 요청·질문, `frozen_values()`의 모든 줄, `extra`의 줄(단일 에이전트 프롬프트 버전·sha256, 채점 프롬프트·루브릭 sha256, 임베딩 모델·`TOP_K`·`MAX_DOC_CHARS`·`ANSWER_PROMPT_VERSION`·`CORPUS_FIELDS`, 격리 요청 세트 해시). 문서는 같은 입력에서 항상 같다(결정적, 날짜 인자만 제외).
- **필수 문장(`REQUIRED_SENTENCES`, 문서에 그대로 들어가고 테스트가 전부 있음을 단언)** — 조언 세션이 승인한 내용:
  1. 기준 숫자는 `docs/EVAL.md` 그대로이고 이 문서는 절차 세부만 추가한다. **결과가 기준에 못 미쳐도 그대로 보고한다.**
  2. E2는 "한 에이전트 대 한 시스템" 비교다. 두 팔은 생성 모델(gpt-6.1-terra, reasoning_effort low), 도구 집합, 그래프, API 호출 재시도·구조화 교정 한도, 도구 호출 한도, 요청당 텍스트 비용 상한이 같다. Supervisor 팔은 요청 해석, 리서치 분리, 코드가 만드는 보조 값(pattern_context, available_efficacy, aggregates 검증), 루프 내 평가와 최대 2회 재작업 루프를 시스템으로서 함께 가진다. **단일 팔은 보조 값(pattern_context, available_efficacy)을 받지 않는다.** 차이는 시스템 구성 전체의 효과이며 결과 문서에도 그렇게 적는다.
  3. 반복 횟수는 요청당 팔마다 1회(요청 20건), 쌍 비교 부트스트랩 10,000회(퍼센타일 95%), 시드는 코드 상수 값, 기준 판정은 CI가 0을 넘는지(하한 > 0)로 한다.
  4. E2 채점은 Anthropic sonnet이고 팔 이름을 숨기고 순서를 섞고 시드를 고정하며 루프 내 평가와 다른 루브릭·프롬프트를 쓴다. 사람 "claim 일치" 판정 약 200건은 편향 점검용이며 주 판정이 아니다(1인 라벨링).
  5. E5 "끔"의 정의와 식별자 목록(우회: `trim_handoff`·`tool_result_payload` 이원화·원출력 비전달, 추가 전달: `sv_tool_outputs`를 `raw_tool_outputs` 필드로; 유지: `trim_message`·`_text_data`·`research_payload`·`MAX_ROWS` 표시; 불변: 상수·함수 정의), 입력 토큰은 요청 중 원장 증가분의 `input_tokens` 합이다. E5 (a)는 E2 Supervisor 실행을 재사용하며 같은 코드 커밋·같은 세트 해시·같은 채점 실행일 때만 유효하고 코드 커밋 해시와 사전 등록 커밋 해시를 결과 문서에 적는다. 이력 압축은 이 실험에 넣지 않는다.
  6. E3: 코퍼스 필드(`CORPUS_FIELDS`), top-k, 청크 방식(청크 분할 없음), 임베딩 모델과 선택 기준(dev 질문 hit@k 최고, 동률이면 저가)이 고정이다. 정답은 그래프 질의로 계산해 사람이 확인했다(그래프에 유리한 질문일 수 있다). 코퍼스에 test 브랜드 소재가 섞인다. 질문 40건과 단순 검색형 10건 부분집합을 따로 보고한다.
  7. 격리: 4경로·경로당 50건·합계 200건, 표식 문자열 검색을 코드가 판정, 노출 0건 기준, 정상 요청 응답률을 짝 지표로 보고한다. **경로 3은 "다른 테넌트의 thread_id 요청 거부 + 정상 요청 응답 확인"이며 대화 압축 요약 경로는 미구현이라 대상이 아니다.** 어디서도 대화 압축 격리를 검증했다고 쓰지 않는다. **재작업 경로(max_reworks=0)는 실행되지 않는다.** 요청당 `max_plans=1`, `max_reworks=0`. 0건은 관측값이지 증명이 아니며 시도한 요청 유형의 범위를 결과와 함께 적는다.
  8. 층화 보조 분석: 요청·질문의 `axes_used`(세트 확정 때 고정)로 충족 축만 쓰는 항목과 미충족 축(hook_type·angle·talent·has_proof_segment·is_vertical·has_text_overlay·cta_type·claims)을 쓰는 항목을 나눠 따로 보고한다. 결론 근거가 아니며 층의 건수가 작으면 판정 불가로 적는다. 문항은 빼지 않는다. 미충족 축과 claims는 "라벨 신뢰도 낮음(κ x.xx)"로 표시하고 κ 값은 E1 결과 문서에서 그대로 읽는다. 재검사 κ는 재현성 증거로 쓰지 않는다.
  9. 동결: 프롬프트 버전·상수·`_SYSTEM` sha256과 세트 해시가 위 줄과 같을 때만 test 실행(와 격리 최종 실행)이 코드로 허용된다. 동결 뒤 프롬프트·상수·세트를 바꾸지 않는다.
  10. E4는 선택이며 11-24까지 구현을 시작하지 못했으면 하지 않는다(11-28까지 나머지 실험이 끝나지 않아도 하지 않는다). 하지 않은 경우 결과 문서에 "미수행"과 이유를 적는다.
  11. 이미지 생성은 실험에서 끈다. 모든 사람 판정 수치에 "1인 라벨링"을 병기한다. 건수가 작으면 작다고 적는다. 기준을 못 넘긴 항목·판정 불가 항목도 같은 표에 넣는다. 정정은 기존 문장을 고치지 않고 정정 기록으로만 쌓는다.
  12. 비용 상한과 실행 순서: E3, E2, E5, 격리, E4(Anthropic 잔여 $1.5 이상일 때만). 호출 전 공급사별 누적액 검사는 유지한다.
  13. **변경 규칙**: 사전 등록 이후 `src/`·`config/`·`data/evalset/`를 수정하면 재등록(새 사전 등록 문서와 새 커밋)이 필요하다. 재등록 전에는 test와 격리 최종 실행이 코드로 막힌다.
  14. **커밋 절차**: 사전 등록 커밋은 확정 세트(`data/evalset/`의 요청·질문·정답 파일)와 이 문서를 **함께** 커밋한다(`data/evalset/`는 gitignore 대상이 아니며 최종 가드가 이 폴더의 작업 트리 변경을 차단한다).
- `render_results_template() -> str`: `docs/results/`의 결과 문서 틀(실험별 표: 건수·기준일·조건·커밋 해시 두 개(사전 등록 커밋은 확정 세트와 문서를 함께 커밋한 것)·모델 ID·판정 코드·기준 미달 항목, E2 구성 한계 문장, 층화 보조 표, 한계 절)을 빈 값으로 돌려준다. 수치를 채우지 않는다.
- `main(argv=None, *, out=sys.stdout) -> int`: `python -m beautyads.eval.prereg [--print|--write PATH|--results-template]`. `--write`는 대상 경로가 이미 있으면 **덮어쓰지 않고** 고정 코드 `PREREG_FILE_EXISTS`로 끝낸다(사전 등록은 기존 파일을 고치지 않고 쌓는다, B-FP-043). 확정 세트를 읽어 `validate_set(final=True)`를 통과하지 못하면 해시를 계산하지 않고 고정 코드로 끝낸다. 쓴 뒤 "사전 등록 커밋은 `data/evalset/`와 이 문서를 함께 커밋한다"는 안내 한 줄을 출력한다(커밋은 사용자가 요청할 때만 한다).

**테스트(`tests/test_prereg.py`)**: `tmp_path`·합성 값만. (1) `render_preregistration` 출력에 `REQUIRED_SENTENCES`(14개, 13번 변경 규칙·14번 커밋 절차 포함)가 전부 있고 개수 0은 실패, (2) **왕복**: 출력을 `freeze_guard.parse_preregistration`이 읽어 만든 값이 입력(`frozen_values()`·`extra`·해시)과 같고, `check_run(mode="final")`의 가짜 `committed_fn`·합성 세트와 함께 통과한다, (3) 같은 입력에서 같은 출력, (4) `--write`가 기존 파일을 덮어쓰지 않음, (5) 틀이 수치 칸을 비워 둠, (6) 이 모듈이 `docs/EVAL.md`·`docs/results/`를 쓰지 않음(경로 문자열 단언 없이 `tmp_path`만 쓰는 호출로 검사), (7) 문서에 "1인 라벨링"·"그대로 보고한다"·"대화 압축" 한계 문장이 있음. 합성 문장을 모델 결과처럼 굳히지 않는다.

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

- `docs/EVAL.md`를 고치거나 기준 숫자(0.30·-0.05·95%·AUC 0.6·노출 0건)를 문서 생성기가 바꾸게 하지 마라. 이유: 동결 기준이다. 절차 세부만 `docs/results/p6_preregistration.md`에 적는다(조언 세션 결정).
- 이 step에서 `docs/results/p6_preregistration.md`를 만들거나 기존 사전 등록 파일을 덮어쓰지 마라. 이유: 문서는 세트 확정 직후(11-26) 사용자가 생성해 커밋한다. 사전 등록은 고치지 않고 쌓는다(B-FP-043).
- 필수 문장에서 "그대로 보고한다"·"단일 팔은 보조 값을 받지 않는다"·"대화 압축 요약 경로는 미구현"·"재작업 경로는 실행되지 않는다"를 빼거나 약화하지 마라. 이유: 조언 세션이 한계 기재로 승인한 문장이다. 대화 압축 격리를 검증했다고 어디에도 쓰지 않는다.
- κ 숫자를 코드·문서 생성기에 적거나 재검사 κ를 재현성 증거로 쓰는 문장을 넣지 마라. 이유: κ는 E1 결과 문서에서 그대로 읽고 재검사 κ는 기억 효과를 포함한다(조언 세션 방침).
- 해시·동결 값을 코드가 아니라 손으로 쓴 리터럴로 문서에 넣지 마라. 이유: 문서의 줄은 `frozen_values()`·세트 해시 함수에서 나와야 가드가 코드와 문서를 대조할 수 있다(step 2 가드).
