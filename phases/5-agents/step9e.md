# Step 9e: weak-contrast-image-prompt

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL 규칙(판정할 수 있는 것은 코드가, 외부 텍스트는 데이터, 모델이 만든 문장을 기대값으로 굳히지 않기, 생성 시안은 로컬 전용)
- `/docs/PROMPT_CHANGELOG.md`(읽기 전용, 이 step 뒤 구현 세션이 갱신한다), `/docs/ARCHITECTURE.md` — "그라운딩 원칙"·생성 시안 로컬 전용 규칙
- `/docs/EVAL.md`(동결된 판정 기준, **읽기 전용**)
- `/src/beautyads/agents/planning.py`(`_SYSTEM`·`research_payload`·`PLANNING_PROMPT_VERSION`), `/src/beautyads/agents/evaluation.py`(`_CRITERIA`·`_SYSTEM`·`EVALUATION_PROMPT_VERSION`), `/src/beautyads/agents/design_images.py`(`image_prompt`), `/src/beautyads/domain/supervisor.py`(`pattern_alignment` 축 판별과 상수), `/src/beautyads/agents/supervisor.py`(`research` 노드·결과 조립), `/src/beautyads/api/ask_view.py`(`show_plan`), `/tests/test_planning.py`, `/tests/test_evaluation.py`, `/tests/test_design_images.py`, `/tests/test_domain_supervisor.py`, `/tests/test_supervisor.py`, `/tests/test_ask_view.py`, `/tests/test_architecture.py` — step 6a·6b·7a·7c·9c 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/supervisor.py`, `src/beautyads/agents/supervisor.py`, `src/beautyads/agents/research.py`, `src/beautyads/agents/planning.py`, `src/beautyads/agents/evaluation.py`, `src/beautyads/agents/design_images.py`, `src/beautyads/api/ask_view.py`, `src/beautyads/obs/trace.py`, `src/beautyads/eval/agents_live.py`, `tests/test_api_assembly.py`, `tests/test_research_agent.py`, `tests/test_trace.py`, `tests/test_agents_live.py`, `tests/test_domain_supervisor.py`, `tests/test_supervisor.py`, `tests/test_planning.py`, `tests/test_evaluation.py`, `tests/test_design_images.py`, `tests/test_ask_view.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/supervisor.py`(`pattern_context` 순수 함수·상수·고지 문구 상수 추가에 한함, `pattern_alignment` 동작 불변), `src/beautyads/agents/supervisor.py`(리서치 뒤 핸드오프에 `pattern_context`와 얇은 풀 노트를 더하고 결과에 `product_display`·`pattern_distribution` 두 칸을 더하는 데 한함, 상태 키·흐름·한도 불변), `src/beautyads/agents/research.py`(`_SYSTEM`에 도구 우선순위 지시 한 문장 추가에 한함, 그 밖의 코드·상태 키·상태 판정 불변), `src/beautyads/obs/trace.py`(`pattern_distribution` 칸 추가와 `build_trace`·`summarize_by_tenant`의 연결에 한함), `src/beautyads/eval/agents_live.py`(요약에 `pattern_distribution`을 싣는 합산·연결에 한함), `src/beautyads/agents/planning.py`(`_SYSTEM` 개정·`research_payload`에 `pattern_context` 키 추가·`PLANNING_PROMPT_VERSION` 갱신에 한함, 스키마·호출 모양 불변), `src/beautyads/agents/evaluation.py`(`_SYSTEM` 개정·`_CRITERIA`의 `fit` 단계 설명 개정·`EVALUATION_PROMPT_VERSION` 갱신에 한함, `_CRITERIA` 키 집합·점수 스키마·검사 순서 불변), `src/beautyads/agents/design_images.py`(`image_prompt`와 `IMAGE_NO_TEXT_CLAUSE` 상수 추가에 한함), `src/beautyads/api/ask_view.py`(`show_plan`에 고지 칸과 `product_display` 칸 추가에 한함), `tests/test_planning.py`(132행 근처 `payload["research"]` 키 집합 단언에 `pattern_context`를 더하는 한 곳, 205행 `PLANNING_PROMPT_VERSION == "2026-11-18-1"` 단언을 `"2026-11-18-2"`로 바꾸는 한 줄, 케이스 추가에 한함), `tests/test_design_images.py`(`test_prompt_includes_only_plan_text`가 `hook_text`를 기대하는 부분을 "`hook_text`는 이미지 프롬프트에 들어가지 않고 `image_brief`·`scenes`는 들어간다"로 바꾸는 한 곳과 케이스 추가에 한함), `tests/test_evaluation.py`(223행 `EVALUATION_PROMPT_VERSION == "2026-11-18-1"` 단언을 `"2026-11-18-2"`로 바꾸는 한 줄과 케이스 추가에 한함), `tests/test_api_assembly.py`·`tests/test_research_agent.py`·`tests/test_trace.py`·`tests/test_agents_live.py`·`tests/test_domain_supervisor.py`·`tests/test_supervisor.py`·`tests/test_ask_view.py`(케이스 추가에 한함, 기존 단언 변경 0줄. 이 파일들의 합성 버전 문자열은 상수가 아니므로 바꾸지 않는다)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

live 결과(차별성 점수 정체, 소재 풀 7건 규모, 이미지에 메타 문구·부정확한 라벨 글자)를 반영해 **강제 대비를 완화**하고 **이미지 프롬프트·고지**를 고친다. 변경은 dev 브랜드 개선 반복이고 변경 이유·날짜는 구현 세션이 `docs/PROMPT_CHANGELOG.md`에 기록한다. 이 step은 모델·실제 서비스를 부르지 않는다. **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

**1. 코드가 계산하는 `pattern_context`(`domain/supervisor.py`, 순수 함수)**: `pattern_context(tool_outputs: list[dict], evidence_ids: list[str]) -> dict`. 축 판별과 지배 값 계산은 9c의 `pattern_alignment`와 **같은 규칙**을 쓴다(한 도구 출력의 모든 `value`를 포함하는 닫힌 값 집합이 정확히 하나일 때만 그 축, 같은 축 출력은 `creatives` 합산, 지배 = `creatives` 최대 값들). 반환(모두 숫자·닫힌 값): `{"pool_size": int | None, "pool_basis": "axis_total" | "evidence_ids", "thin_pool": bool, "min_dominant_share": MIN_DOMINANT_SHARE, "thin_pool_max": THIN_POOL_MAX, "dominant_axes": [{"axis": 축, "values": [지배 값…], "share": float}], "weak_axes": [축…]}`. `pool_size` = 비교 도구 출력의 `total` 최대값(`pool_basis: "axis_total"`), 비교 출력이 없으면 `len(set(evidence_ids))`(`"evidence_ids"`). `thin_pool` = `pool_size < THIN_POOL_MAX`. `dominant_axes` = 점유율(`지배 값의 합산 creatives / 합산 total`)이 `MIN_DOMINANT_SHARE` **이상**인 축, `weak_axes` = 비교는 했으나 기준 미만인 축. **상수는 잠정값이다**: `MIN_DOMINANT_SHARE = 0.4`, `THIN_POOL_MAX = 10`(주석에 "잠정값, 사용자 승인 전. 이유·날짜는 docs/PROMPT_CHANGELOG.md"). 입력을 바꾸지 않는다. **분포 기록(임계값을 데이터로 정하기 위한 계측)**: 반환에 `distribution: [{"axis": 축, "total": int | None, "top_share": float | None, "second_share": float | None, "top_value": 값 | None}]`를 더한다(비교한 모든 축, 기준 이상 여부와 무관). `top_share`는 `creatives` 1위 값의 점유율, `second_share`는 2위 값의 점유율(값이 하나뿐이면 `None`), 동률은 같은 점유율을 모두 1위로 본다. 이 분포는 판정에 쓰지 않는다. **Supervisor 결과 최상위의 `pattern_distribution`**(`agents/supervisor.py`가 `pattern_context.distribution`에서 `top_value`를 뺀 `[{"axis", "total", "top_share", "second_share"}]`로 만든다, 핸드오프를 쓰지 못한 요청은 빈 목록)이 trace·`agents_live` 요약의 원천이다.

**1-1. 리서치 도구 우선순위(`agents/research.py`)**: `_SYSTEM`에 한 문장을 더한다: "패턴·경쟁 소재 근거에는 카테고리 단위 도구(`compare_axis_by_category`, `top_vs_bottom_axis`)를 먼저 쓰고, 제품 연결 도구(`lookup_*`류)는 제품을 특정한 질문에만 쓴다." 그 밖은 바꾸지 않는다(코드·상태 키 불변). 풀 크기가 어떻게 달라지는지는 다음 live에서 분포로 본다.

**2. 핸드오프에 주입(`agents/supervisor.py`)**: `research` 노드가 핸드오프 검증과 `aggregates` 검증을 마친 뒤 `sv_handoff`에 `pattern_context`를 더하고, `thin_pool`이 참이면 **코드가 만든 고정 문장**을 `basis_notes` 끝에 중복 없이 덧붙인다(`THIN_POOL_NOTE = "근거 소재가 {n}건으로 얇아 차별성 판단에 한계가 있다"`, `{n}`은 `pool_size`, 모델이 쓰지 않는다). 이 값은 `trim_handoff`·`plan_eval_fn`에 그대로 전달되고 결과 `handoff`에도 실린다. `pattern_alignment` 보고 지표(9c)는 그대로 둔다(판정 미사용).

**3. 프롬프트(`agents/planning.py`·`agents/evaluation.py`)**
- `research_payload`의 키 목록에 `pattern_context`를 더한다(기획·평가가 같은 함수를 쓰므로 **평가자 입력에도 근거 풀 크기가 전달된다**).
- 기획 `_SYSTEM`: 9c의 "지배 패턴과 뚜렷이 다른 조합"을 다음으로 바꾼다(의미를 지켜 다듬는다): "`research.pattern_context.dominant_axes`에 있는 축(점유율이 기준 이상)에서만 그 지배 값과 다른 값을 고른다. 나머지 축(`weak_axes`)은 근거에 맞게 고른다. `pattern_context.thin_pool`이 참이면 차별성을 단정하지 않는다(한계는 코드가 `basis_notes`에 적었다)." (ii)~(v)(`own_product_url`·확인된 효능만·`low_items` 지침·데이터 규칙 대상 구분)는 그대로 둔다. **`image_brief`는 장면 묘사만 쓴다**(지시·설명·괄호 주석을 쓰지 않고, 이미지 안에 어떤 글자·로고·브랜드·제품명·라벨 문구도 넣지 않으며 제품은 무라벨 일반 제품(병·튜브·패키지의 형태만)으로 묘사한다)는 문장을 더한다. **한국어 광고 카피 지침**을 더한다(긍정형 원칙 중심): `hook_text`·`copy_lines`는 **소비자의 실제 상황이나 고민에서 출발해 짧은 구어체로** 쓰고, 이미지 위에 올릴 광고 문구인 `hook_text`는 **한 문장**이다. 피할 것은 번역투·설명조 한 가지 줄이다(특정 문장 형태를 금지 예시로 나열하지 않는다). `PLANNING_PROMPT_VERSION = "2026-11-18-2"`.
- 평가 `_SYSTEM`: "`research.pattern_context`는 근거 풀 크기와 지배 축이다. `thin_pool`이 참이면 차별성 판단의 한계를 `rationale`에 한 문장으로 적고 근거가 얇다는 이유만으로 극단 점수(1·5)를 주지 않는다. 지배 축이 없으면(`dominant_axes`가 비면) 차별성은 훅·각도·포맷의 근거 연결과 구체성으로 판단한다"를 더하고 **`rationale`은 한국어 200자 이내로 쓴다**는 문장을 더한다(스키마 상한과 같은 값을 지시문에 명시). `_CRITERIA`의 키 집합·점수 스키마는 그대로이고 **`fit`의 점수 단계 설명에 "한국어 광고 카피로서 자연스러운가"(번역투·설명조면 감점, 소비자의 실제 상황에서 출발한 짧은 구어체면 가점)를 포함한다**. `EVALUATION_PROMPT_VERSION = "2026-11-18-2"`.

**4. 이미지 프롬프트(`agents/design_images.py`)**: `image_prompt(plan)`은 **장면 묘사만** 쓴다: `image_brief`와 `scenes`를 쓰고 `hook_text`(화면 글자로 렌더링되는 카피)는 넣지 않는다. 각 문장에서 **메타 문구를 제거**한다: 괄호 주석(`(...)`·`[...]`·`（...）`·`<...>`) 전체, `※`·`참고:`·`주의:`·`설명:`·`지시:`·`Note:`로 시작하는 줄, 그리고 이어진 URL(기존 규칙). 제거 뒤 빈 줄은 버리고 2000자 상한은 유지한다. 순수 텍스트 함수라 모델·네트워크를 부르지 않는다.

**5. 고지·제품 표시 칸(`domain/supervisor.py`·`agents/supervisor.py`·`api/ask_view.py`)**: 제품명·브랜드명은 이미지에 넣지 않고 **화면 데이터의 별도 칸**으로만 준다: Supervisor 결과에 `product_display: {"brand", "display_name"}`(`run_request`가 받은 작업 공간 프로필의 값, 모델을 거치지 않음)를 더하고 `show_plan`이 그대로 싣는다(프로필이 비면 두 값 모두 `None`). 고지는 상수 `DESIGN_IMAGE_DISCLAIMER = "생성 시안은 참고용이며 라벨 글자가 부정확할 수 있다"`(코드가 넣는 고정 문장). `show_plan` 화면 명령 데이터에 `design_disclaimer` 칸을 더한다: 기획안에 이미지 참조(`image`)가 있을 때 이 상수, 없으면 `None`. 모델 출력으로 바뀌지 않는다.

**반드시 있어야 하는 테스트**(합성 값·가짜 호출. 모델 문장·점수를 기대값으로 굳히지 않는다):
- **`pattern_context`(순수 함수)**: 합성 `tool_outputs`로 점유율이 기준 이상인 축만 `dominant_axes`, 기준 미만은 `weak_axes`(경계: 점유율이 정확히 `MIN_DOMINANT_SHARE`이면 `dominant`), `pool_size`가 `total` 최대, 비교 출력이 없으면 `evidence_ids` 개수와 `pool_basis`, `thin_pool` 경계(`THIN_POOL_MAX` 미만만 참: 9 → 참, 10 → 거짓), 축 판별 불가 출력은 건너뜀, 입력 불변, JSON 직렬화. 값이 9c `pattern_alignment`의 축·지배 판정과 같은 합성 입력에서 일치한다.
- **분포·기록**: `distribution`이 합성 `tool_outputs`(1위 0.5·2위 0.3, 동률, 값 하나, 합계 0)에서 정확한 `top_share`·`second_share`·`total`을 내고(값이 하나면 `second_share None`, 합계 0이면 `None`) 판정 결과(`dominant_axes`)에 영향을 주지 않는다. Supervisor 결과와 trace의 `pattern_distribution`(축별 `axis`·`total`·`top_share`·`second_share`, 값 이름 없음)·`agents_live` 요약이 그 값을 그대로 싣는다(합성 비밀을 `top_value`에 넣어도 trace·요약에 없다: 닫힌 값 집합 밖 문자열은 기록하지 않는다). 리서치 `_SYSTEM`에 `compare_axis_by_category`·`top_vs_bottom_axis`·`제품을 특정한` 구절이 있다(호출 인자 직접 검사).
- **주입·전달 확인(FP-C14)**: 가짜 단계 함수로 Supervisor를 돌려 `plan_eval_fn`이 받은 핸드오프에 `pattern_context`가 있고 `thin_pool`이 참이면 `basis_notes` 끝에 `THIN_POOL_NOTE` 형식(개수 포함)이 **정확히 한 번** 있다(두 번 돌려도 중복 없음). 가짜 `structured`가 받은 기획·평가 `messages`를 직접 열어 사용자 메시지 JSON의 `research.pattern_context`가 있고(키 집합에 `pattern_context`), 기획 시스템 메시지에 `dominant_axes`·`thin_pool`·"장면 묘사"·`own_product_url` 구절이, 평가 시스템 메시지에 `thin_pool`·`200자` 구절이, 평가 `criteria.fit` 값에 "한국어 광고 카피" 구절이 있고, 기획 시스템 메시지에 한국어 카피 지침 구절(`실제 상황`·`구어체`·`한 문장`)과 "무라벨"·"글자" 구절이 있다. **9c의 `pattern_alignment`·`final_passed` 흐름은 그대로**이고 `pattern_context`를 바꿔도 `status`·`rework_count`는 같다(보고 지표 불변). 버전 상수가 `"2026-11-18-2"`다.
- **이미지 프롬프트**: 메타 문구가 든 합성 `image_brief`(괄호 주석, `※` 줄, `지시:` 줄, URL)와 `hook_text`가 든 계획으로 `image_prompt`를 부르면 결과에 메타 문구·`hook_text`·URL이 **없고** 장면 묘사 본문은 있다. 가짜 `generate_image`(조립 경유 또는 `image_fn`)가 받은 **호출 인자의 `prompt`를 직접 열어** 같은 단언을 하고 `IMAGE_NO_TEXT_CLAUSE`가 끝에 있음을 단언한다(`image_brief=None`이어도 있다). 2000자 상한과 `image_brief=None` 처리는 유지된다.
- **고지·제품 표시**: `show_plan`에 `design_disclaimer`가 이미지가 있을 때 상수와 같고 없을 때 `None`이며, `product_display`가 프로필의 `brand`·`display_name`과 같고(프로필이 비면 `None`), 데이터가 `json.dumps`를 통과한다. 기존 `ask_view` 단언은 그대로 통과한다.
- 기존 `tests/test_architecture.py`·`tests/test_schema_guard.py`·`tests/test_llm_param_guard.py`가 그대로 통과한다.

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

- `pattern_context`나 얇은 풀 노트를 `passed`·되돌림·`status`·라우팅에 쓰거나 모델이 쓰게 하지 마라. 이유: 근거 풀 한계는 코드가 숫자로 계산해 문장으로 남기고, 판정에는 영향이 없다(승인된 조건, 9c 보고 지표와 같은 원칙).
- 상수 `MIN_DOMINANT_SHARE`·`THIN_POOL_MAX`를 확정 값처럼 문서·테스트에 단정하지 마라. 이유: 잠정값이고 사용자 승인 전이다. 테스트는 상수를 import해 경계(상수 값 이상/미만)를 지켜야 하고 값 자체를 `== 0.4`로 굳히지 않는다(B-FP-061).
- 프롬프트 구절을 모델 출력 기대값으로 굳히거나 점수·문장을 단언하지 마라. 이유: 정확도는 평가에서 잰다(AGENTS.md CRITICAL). 테스트는 입력 전달(호출 인자)과 코드가 하는 일만 검사한다.
- `image_prompt`에서 메타 문구 제거를 모델·네트워크에 맡기거나 `hook_text`를 다시 넣지 마라. 이유: 이미지 모델이 지시·카피를 글자로 그려 넣는 문제를 막는 결정론 처리다. 생성 이미지·base64·경로는 어떤 결과에도 넣지 않는다(6a 규칙).
- `docs/EVAL.md`의 동결된 판정 기준이나 점수 스키마·`PASS_MIN_SCORE`를 바꾸지 마라. 이유: 개선 반복은 입력·프롬프트 한정이고 최종 평가 전에 동결한다(AGENTS.md CRITICAL).
- 고지 문구를 모델이 만들게 하거나 이미지가 없을 때 칸을 생략하지 마라. 이유: 코드가 넣는 고정 문장이고 칸은 항상 있다(값은 `None`).
- 이미지 프롬프트에 글자·카피·브랜드·제품명을 넣거나 `IMAGE_NO_TEXT_CLAUSE`를 빼지 마라. 이유: 이미지 모델이 글자를 깨뜨려 그린다(live 관측). 글자는 코드가 합성하고(step 9f) 제품명은 화면 데이터 칸으로만 준다.
