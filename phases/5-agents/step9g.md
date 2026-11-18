# Step 9g: single-cut-layout-efficacy

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL 규칙(판정할 수 있는 것은 코드가, 모델이 만든 목록을 근거로 쓰지 않기, 생성 시안은 로컬 전용, 외부 호출은 래퍼 하나, 새 Cypher는 계약에 없으면 금지)
- `/docs/PROMPT_CHANGELOG.md`(읽기 전용, 이 step 뒤 구현 세션이 갱신한다), `/docs/results/2026-11-18-p5-live-agents.md`(읽기 전용)
- `/docs/ARCHITECTURE.md` — 그라운딩 원칙·생성 시안 로컬 전용 규칙
- `/src/beautyads/agents/design_images.py`(`image_prompt`·`IMAGE_NO_TEXT_CLAUSE`), `/src/beautyads/agents/design_compose.py`(레이아웃 상수·`_fit`·`compose_design`), `/src/beautyads/agents/planning.py`(`_SYSTEM`·`make_plan` payload·`PLANNING_PROMPT_VERSION`), `/src/beautyads/agents/supervisor.py`(`run_request`·`build_supervisor_graph`의 `research` 노드), `/src/beautyads/agents/lookups.py`(`GraphEfficacySupport`·`product_support_query` 재사용), `/src/beautyads/graph/evidence_queries.py`(`product_support_query`·`product_support_parameters`, **읽기 전용**: 새 Cypher를 만들지 않는다), `/src/beautyads/api/assembly.py`(`ask` 래퍼·`GraphEfficacySupport` 조립), `/src/beautyads/domain/labels.py`(`Claim`), `/src/beautyads/domain/lookups.py`(`SupportStatus`), `/tests/test_design_images.py`, `/tests/test_design_compose.py`, `/tests/test_planning.py`, `/tests/test_supervisor.py`, `/tests/test_api_assembly.py`, `/tests/test_architecture.py` — step 6a·6b·7a·7d·9e·9f 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/agents/design_images.py`, `src/beautyads/agents/design_compose.py`, `src/beautyads/agents/planning.py`, `src/beautyads/agents/supervisor.py`, `src/beautyads/api/assembly.py`, `tests/test_design_images.py`, `tests/test_design_compose.py`, `tests/test_planning.py`, `tests/test_supervisor.py`, `tests/test_api_assembly.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/agents/design_images.py`(`image_prompt`와 `IMAGE_NO_TEXT_CLAUSE` 문구에 한함, `save_design_image`·`save_composed_design`·`SavedImage` 불변), `src/beautyads/agents/design_compose.py`(레이아웃 상수 값 변경, 새 상수 `HEADLINE_FONT_RATIO`·`CTA_FONT_RATIO`·`BAND_AREA_MAX_RATIO`와 순수 함수 `layout_regions` 추가, `_fit`의 시작 글자 크기 계산 인자 추가, `compose_design`의 영역 계산이 `layout_regions`를 쓰도록 바꾸는 데 한함. 글자 정리·폰트 로딩·CTA 문구·`ComposedImage` 필드·`FontMissing` 불변), `src/beautyads/agents/planning.py`(`_SYSTEM` 개정·`make_plan` payload에 최상위 `available_efficacy` 칸 추가·`PLANNING_PROMPT_VERSION` 갱신에 한함, 스키마·호출 모양·`research_payload` 키 목록 불변), `src/beautyads/agents/supervisor.py`(`run_request`·`build_supervisor_graph`에 선택 인자 `claims_fn=None` 추가, `research` 노드 안에서 `plan` 의도일 때만 `claims_fn`을 호출해 핸드오프에 `available_efficacy`를 더하고 결과 최상위에 `available_efficacy`·`available_efficacy_status` 두 칸을 더하는 데 한함. 상태 키 집합·노드 구성·흐름·한도 불변), `src/beautyads/api/assembly.py`(`ask` 래퍼 안에서 `claims_fn`을 정의해 `run_request` 호출에 넘기는 데 한함, 모델 호출 모양·상한·이미지 경로 불변), `tests/test_design_images.py`(두 줄만 갱신 허용: `test_prompt_includes_only_plan_text`의 `for text in [value.image_brief, *value.scenes]:` 줄을 `image_brief`만 프롬프트에 들어가고 `scenes`는 들어가지 않는다는 단언으로 바꾸는 한 곳, `test_prompt_removes_meta_copy_and_always_ends_with_no_text_clause`의 `assert "빛나는 표면" in prompt` 줄을 `not in`으로 바꾸는 한 줄, 그 밖은 케이스 추가에 한함), `tests/test_design_compose.py`(새 레이아웃 값에서 파생되는 기대값 갱신만 허용, 함수 단위로 명시: `test_png_dimensions_safe_regions_and_original_pixels`의 영역 리터럴 `0.28`·`0.12`와 `margin + int(1024 * 0.28)` 표현, `test_wraps_and_shrinks_with_at_most_three_lines`의 `<= 3`과 상자 튜플 `(51, 51, 973, 337)`, `test_minimum_font_ellipsizes_headline_and_single_line_cta`의 `<= 3`과 상자 튜플 `(5, 5, 95, 291)`·`(5, 897, 95, 1019)`, `test_short_headline_keeps_starting_font_and_is_centered`의 시작 글자 크기 공식 `int(int(1024 * compose.HEADLINE_HEIGHT_RATIO) * 0.75)`. 이 갱신은 상수 import 표현으로 바꿔 값 자체를 굳히지 않는다. 그 밖은 케이스 추가에 한함), `tests/test_planning.py`(`PLANNING_PROMPT_VERSION == "2026-11-18-2"` 단언 한 줄을 `"2026-11-18-3"`으로 바꾸는 한 곳과 케이스 추가에 한함. 기존 `확인된 효능`·`빈 목록` 구절 단언은 새 문장이 그대로 포함하므로 변경 0줄), `tests/test_supervisor.py`(케이스 추가에 한함, 기존 단언 변경 0줄. `run_request`의 새 인자가 선택이라 기존 호출은 그대로다), `tests/test_api_assembly.py`(`test_fp_c14_assembled_image_call_is_scene_only_and_carries_context`의 `assert "투명한 물결" in prompt` 한 줄을 `scenes`가 프롬프트에 없다는 `not in` 단언으로 바꾸고 `image_brief`가 있는 매개변수에서 `"햇빛 속 병"`·`"물방울"`이 프롬프트에 있다는 단언을 추가하는 한 곳, 그 밖은 케이스 추가에 한함)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

생성 시안 확인(9e·9f 뒤 image 실행)에서 드러난 세 가지를 고친다: (1) 이미지가 3×3 스토리보드 콜라주였고 "글자 없음" 지시를 무시한 한글 자막이 그려졌다, (2) 합성 헤드라인 띠가 크고 중앙을 가린다, (3) `efficacy_status`가 비어 효능 근거 경로가 live로 검증되지 않았다. 이 step은 모델·실제 서비스를 부르지 않는다. **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.** 변경은 dev 브랜드 개선 반복이고 변경 이유·날짜는 구현 세션이 `docs/PROMPT_CHANGELOG.md`에 기록한다.

**원인 점검(오프라인, 합성 plan)**: 현재 `image_prompt`는 `image_brief`와 `scenes`를 합친다. `scenes`는 **영상의 여러 장면**을 한 줄씩 적은 목록이라 이미지 모델이 여러 컷(콜라주·스토리보드)으로 그리고, `image_brief`·`scenes` 안의 따옴표 문장(카피 문장)이 자막으로 그려진다. `hook_text`·`copy_lines`는 이미 프롬프트에 없다(`copy_lines`는 처음부터 쓰지 않는다).

**1. 이미지 단일 컷(`agents/design_images.py`·`agents/planning.py`)**
- `image_prompt(plan)`: **`image_brief`만** 쓴다(`scenes`·`hook_text`·`copy_lines`는 어떤 경우에도 넣지 않는다). 기존 메타 문구 제거 규칙(괄호 주석, `※`·`참고:`·`주의:`·`설명:`·`지시:`·`Note:` 줄, URL)은 유지하고 **따옴표로 감싼 문장 전체를 따옴표째 제거**한다(`"…"`, `“…”`, `‘…’`, `'…'`, `「…」`, `『…』`, 중첩 포함, 줄이 비면 버림). `image_brief`가 없거나 모두 지워지면 장면 부분 없이 고정 지시만 남는다. 2000자 상한은 고정 지시를 보존하며 유지한다.
- `IMAGE_NO_TEXT_CLAUSE`(상수 이름 유지, 문구 개정): "하나의 구도로 단일 컷만 그린다(콜라주·그리드·스토리보드·여러 컷 금지). 이미지에는 글자·자막·카피·로고·브랜드·제품명·라벨 문구를 넣지 않는다. 제품은 무라벨 일반 병·튜브·패키지의 형태로만 묘사한다." 프롬프트는 항상 이 문구로 끝난다.
- 기획 `_SYSTEM`: `image_brief`는 **하나의 핵심 장면(단일 컷) 묘사**만 쓴다는 문장으로 바꾼다(여러 장면·콜라주·자막·문구·따옴표 문장을 쓰지 않는다. 기존의 "지시·설명·괄호 주석 금지", "이미지 안 글자·로고·브랜드·제품명·라벨 금지·무라벨 일반 제품" 문장과 `장면 묘사`·`무라벨`·`글자` 구절은 유지한다). `scenes`는 영상 장면 목록으로 그대로 쓰되 이미지에는 쓰이지 않는다.

**2. 합성 레이아웃(`agents/design_compose.py`)**: 헤드라인은 작게·최대 2줄·상단 띠 면적 20% 이하, CTA는 더 작은 하단 소형 띠, 상단·하단에만 배치해 중앙 피사체를 가리지 않는다.
- 상수 값/추가: `HEADLINE_FONT_RATIO = 0.055`(이미지 높이 대비 시작 글자 크기, 5~6%), `CTA_FONT_RATIO = 0.035`, `HEADLINE_HEIGHT_RATIO = 0.16`(헤드라인 영역 높이), `CTA_HEIGHT_RATIO = 0.06`, `MAX_HEADLINE_LINES = 2`, `BAND_AREA_MAX_RATIO = 0.20`, `MARGIN_RATIO`·`MIN_FONT_PX`·`BAND_RGBA`·`TEXT_COLOR`·`MAX_HEADLINE_CHARS`는 그대로.
- 순수 함수 `layout_regions(width: int, height: int) -> dict[str, tuple[int, int, int, int]]`: `{"headline": (l, t, r, b), "cta": (l, t, r, b)}`. 여백은 기존 `MARGIN_RATIO` 규칙, 헤드라인 영역은 위 여백부터 `HEADLINE_HEIGHT_RATIO`, CTA 영역은 아래 여백 위로 `CTA_HEIGHT_RATIO`(이미지 경계 안으로 자른다). `compose_design`은 이 함수의 영역을 쓴다.
- `_fit`: 시작 글자 크기를 영역이 아니라 **이미지 높이 × 해당 비율**(`int(height * FONT_RATIO)`, 최소 `MIN_FONT_PX`)에서 시작하고 기존처럼 2px씩 줄여 영역 안에 줄 수·너비·높이가 들어가는 첫 크기를 쓴다(최소 크기에서도 넘으면 기존 말줄임 규칙). 헤드라인은 `MAX_HEADLINE_LINES`, CTA는 1줄.

**3. 효능 근거 입력(`agents/supervisor.py`·`api/assembly.py`·`agents/planning.py`)**: 모델이 목록을 만들지 않고 **코드가 우리 제품의 확인된 효능을 조회해 채운다**(새 Cypher 없음: 기존 `GraphEfficacySupport`가 `product_support_query()`로 읽는다).
- `api/assembly.py`: `ask` 래퍼 안에 `claims_fn(profile: dict) -> tuple[list[str], str]`를 정의한다: `profile["own_product_url"]`이 비면 `([], "skipped")`. 아니면 `Claim` 값(`other` 제외)을 `Claim` 정의 순서대로 `GraphEfficacySupport(graph_connection).efficacy_support(own_product_url, claim)`로 조회해 `SupportStatus.supported`인 `claim.value`만 모은다. 조회 중 `last_error`(`GRAPH_UNAVAILABLE`)가 한 번이라도 있으면 **빈 목록과 상태 `"failed"`**를, 없으면 모은 목록과 `"ok"`를 돌려준다. `run_request(..., claims_fn=claims_fn)`로 넘긴다. 읽기 전용 질의만 쓴다.
- `agents/supervisor.py`: `run_request`·`build_supervisor_graph`에 선택 인자 `claims_fn=None`. `research` 노드가 `pattern_context`를 주입한 뒤, **의도가 `plan`일 때만** `claims_fn(profile)`을 부른다(그 밖의 의도·`claims_fn=None`이면 호출하지 않고 `([], "skipped")`). 반환 목록은 `Claim` 닫힌 값(`other` 제외)만 남기고 중복을 제거하며 순서를 유지하고, 예외는 삼켜 `([], "failed")`로 둔다(진단 값 미노출). 결과를 `sv_handoff["available_efficacy"]`(핸드오프 키)에 넣고, 결과 최상위에 `available_efficacy`(목록)·`available_efficacy_status`(`"ok"|"failed"|"skipped"`)를 싣는다. **상태 키 집합·노드 구성·흐름은 바뀌지 않는다**(`sv_handoff`에 키만 더한다).
- `agents/planning.py`: `make_plan`의 사용자 메시지 payload에 **최상위 `available_efficacy`**(핸드오프의 값 중 `Claim` 닫힌 값만, 없으면 `[]`)를 더한다(`research_payload`의 키 목록은 바꾸지 않는다: 평가 입력은 그대로). `_SYSTEM`의 효능 지시를 바꾼다: "`claimed_efficacy`에는 입력의 `available_efficacy`(코드가 확인한 효능)에 있는 값만 넣는다. 확인된 효능이 목록에 없으면 주장하지 않고 빈 목록으로 둔다. 목록이 비어 있으면 빈 목록이다." (`확인된 효능`·`빈 목록` 구절을 포함한다.) `PLANNING_PROMPT_VERSION = "2026-11-18-3"`.
- 검사는 기존대로 한다(`evaluation`의 `efficacy_status`는 계획의 `claimed_efficacy`를 그대로 조회하므로 목록에 있는 값은 `supported`로 나온다). 확인된 효능이 하나도 없으면 빈 목록을 그대로 전달한다(지어내지 않는다).

**새 칸 대응표(만드는 파일 → 읽는 파일)**
| 칸·상수 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `claims_fn` 인자 | `api/assembly.py` | `agents/supervisor.py` |
| 핸드오프 `available_efficacy` | `agents/supervisor.py`(`research` 노드) | `agents/planning.py`(`make_plan`), 테스트 |
| 결과 `available_efficacy`·`available_efficacy_status` | `agents/supervisor.py` | 테스트(화면·trace는 이 step에서 읽지 않는다) |
| payload 최상위 `available_efficacy` | `agents/planning.py` | 모델 입력(가짜 `structured`가 받은 `messages`를 테스트가 직접 연다) |
| `IMAGE_NO_TEXT_CLAUSE` | `agents/design_images.py` | `image_prompt`(같은 파일), 테스트(상수 import) |
| `HEADLINE_FONT_RATIO`·`CTA_FONT_RATIO`·`BAND_AREA_MAX_RATIO`·`layout_regions` | `agents/design_compose.py` | `compose_design`(같은 파일), `tests/test_design_compose.py` |
| `PLANNING_PROMPT_VERSION` | `agents/planning.py` | Supervisor 결과 `prompt_versions`(코드 변경 없음, 상수 import), `tests/test_planning.py:206` 단언 |

**반드시 있어야 하는 테스트**(합성 값·가짜 호출. 모델 문장·점수를 기대값으로 굳히지 않는다)
- **이미지 프롬프트(`tests/test_design_images.py`)**: 합성 plan(`image_brief`에 따옴표 문장 `"SYNTH_QUOTE_A"`·`“SYNTH_QUOTE_B”`·`「SYNTH_QUOTE_C」`와 괄호 주석, `scenes`에 `SYNTH_SCENE_X`·`hook_text`에 `SYNTH_HOOK`·`copy_lines`에 `SYNTH_COPY`)으로 `image_prompt`를 부르면 `SYNTH_QUOTE_*`·`SYNTH_SCENE_X`·`SYNTH_HOOK`·`SYNTH_COPY`·괄호 주석이 **없고** `image_brief`의 장면 본문은 있으며 프롬프트가 `IMAGE_NO_TEXT_CLAUSE`로 끝난다. `IMAGE_NO_TEXT_CLAUSE`에 `콜라주`·`스토리보드`·`여러 컷`·`단일 컷`·`자막`·`무라벨` 구절이 모두 있다(상수 문자열 포함 검사). `image_brief=None`·전부 따옴표인 `image_brief`면 프롬프트가 고정 지시뿐이다. 2000자 상한과 고정 지시 보존. **호출 인자 직접 검사(FP-C14)**: `tests/test_api_assembly.py`의 조립 경유 테스트가 가짜 `generate_image`가 받은 `prompt`에서 `scenes`의 문구·`COPY_SENTINEL`·메타 문구가 없고 `image_brief`의 장면 문구가 있으며 고정 지시로 끝남을 단언한다(위 허용된 한 줄 갱신과 추가 단언).
- **기획 프롬프트 전달(`tests/test_planning.py`)**: 가짜 `structured`가 받은 시스템 메시지에 `단일 컷`·`콜라주`·`장면 묘사`·`무라벨`·`글자`·`available_efficacy`·`확인된 효능`·`빈 목록` 구절이 있고 기존 구절(지배 패턴·`own_product_url`·`low_items` 등)이 그대로 있으며, 사용자 메시지 JSON의 최상위 `available_efficacy`가 핸드오프 값과 같다(`Claim` 닫힌 값 밖의 값과 `other`는 빠지고, 핸드오프에 없으면 `[]`). `PLANNING_PROMPT_VERSION`이 `2026-11-18-3`이고 `payload["research"]` 키 집합·`reasoning_effort`·모델·스키마는 이전과 같다.
- **효능 조회(Supervisor, `tests/test_supervisor.py`)**: 가짜 `claims_fn`이 `plan` 의도에서만 한 번 불리고(`pattern`·`relation`·`out_of_scope`·`no_evidence`에서는 불리지 않음) 받은 `profile`이 `run_request`의 `profile`과 같다. 반환 `["hydration", "bogus", "other", "hydration", "soothing"]`이 `["hydration", "soothing"]`으로 정리되어 `plan_eval_fn`이 받은 핸드오프의 `available_efficacy`와 결과 최상위 `available_efficacy`가 같고 `available_efficacy_status == "ok"`이다. `claims_fn`이 예외를 던지면 `[]`·`"failed"`이고 요청은 끝까지 진행되며 **예외 메시지가 결과에 없다**. `claims_fn=None`이면 `[]`·`"skipped"`이다. **`claims_fn`의 결과를 바꿔도 `status`·`rework_count`·`attempts`가 같다**(판정 영향 없음). 상태 키 집합 단언(`SupervisorState` 키)은 그대로 통과한다.
- **효능 조회(조립, `tests/test_api_assembly.py`)**: 가짜 그래프가 `product_support_query()` 질의에 `hydration`만 `{"ingredient_count": 1, "supporting_count": 1}`로 돌려주면(`product_support_parameters`의 `claim` 값으로 구분) 조립이 만든 `claims_fn`이 `["hydration"]`·`"ok"`를 돌려주고, **질의가 전부 `product_support_query()`이며 `other`는 조회하지 않고 새 Cypher가 없다**(가짜가 받은 질의 문자열 직접 검사). 그래프가 예외를 던지면 `([], "failed")`, `own_product_url`이 비면 `([], "skipped")`이고 그래프 질의가 없다. 조립 경유 `ask` 결과의 `available_efficacy`가 위 목록과 같다. 기존 `test_hydrate_uses_seven_columns_and_bound_keys_and_json_dates`의 질의 개수 단언은 그대로 통과한다.
- **합성 레이아웃(`tests/test_design_compose.py`)**: `layout_regions`가 영역 두 개를 이미지 경계와 여백 안에 돌려주고(여러 크기: 1024×1024·512×1024·2048×64·8×256) **헤드라인 띠 면적(영역 너비×높이)이 이미지 면적의 `BAND_AREA_MAX_RATIO` 이하**, CTA 띠가 헤드라인 띠보다 작으며 두 영역이 겹치지 않는다. `0.05 <= HEADLINE_FONT_RATIO <= 0.06`이고 `CTA_FONT_RATIO < HEADLINE_FONT_RATIO`이며 줄 수는 **`len(value.lines) <= compose.MAX_HEADLINE_LINES`와 `compose.MAX_HEADLINE_LINES <= 2`**로 단언한다(값 자체를 `== 2`로 굳히지 않는다). 짧은 헤드라인의 `headline_size`가 `max(MIN_FONT_PX, int(height * HEADLINE_FONT_RATIO))`이고 CTA 글자 크기가 헤드라인보다 작다. 긴 헤드라인은 줄 수가 상한 이하로 줄바꿈·축소되고 상자가 영역 안에 있다. **중앙 영역**(높이 25%~75%)에는 합성 상자가 들어가지 않고 중앙 픽셀이 원본과 같다(1024×1024·512×1024). 갱신된 기존 단언(허용 목록의 함수 4개)이 새 상수 import 표현으로 통과한다.
- 기존 `tests/test_architecture.py`·`tests/test_schema_guard.py`·`tests/test_llm_param_guard.py`가 그대로 통과하고(`planning.py`의 스키마·호출 모양 불변), `agents/supervisor.py`가 `neo4j`·`fastapi`·`psycopg`를 import하지 않는다.

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

- `scenes`·`hook_text`·`copy_lines`·따옴표 문장을 이미지 프롬프트에 다시 넣거나 `IMAGE_NO_TEXT_CLAUSE`에서 단일 컷·콜라주 금지·자막 금지 구절을 빼지 마라. 이유: `scenes`가 영상의 여러 장면이라 이미지 모델이 콜라주로 그리고 따옴표 문장이 자막으로 그려졌다(live 관측). 카피 글자는 코드가 합성한다(9f).
- 모델이 효능 목록을 만들게 하거나 조회 실패를 확인된 것으로 처리하지 마라. 이유: 판정할 수 있는 것은 코드가 한다(AGENTS.md CRITICAL). 확인된 효능이 없으면 빈 목록이고 실패는 `failed`·빈 목록이다. 새 Cypher를 만들지 말고 기존 `product_support_query()`만 쓴다.
- `available_efficacy`를 `passed`·되돌림·`status`·라우팅에 쓰거나 평가 입력(`research_payload` 키 목록)에 넣지 마라. 이유: 기획 입력용이고 검사는 기존대로 `claimed_efficacy`를 조회한다(승인된 조건). 평가 입력 키 집합 단언을 바꾸지 않는다.
- 허용 목록 밖의 기존 단언을 바꾸거나 새 레이아웃 값을 테스트에 `== 0.055`처럼 굳히지 마라. 이유: 값은 조정 대상이고(B-FP-061) 기대값 갱신은 함수·줄 단위로 허용한 곳뿐이다. 상수는 import해 경계로 검사한다.
- `SupervisorState`의 키·노드 구성·한도·`pattern_context`·`pattern_alignment` 동작을 바꾸거나 `compose_design`의 글자 정리·폰트 로딩·CTA 문구·`ComposedImage` 필드를 바꾸지 마라. 이유: 9a~9f에서 검증한 계약이다. 새 칸은 핸드오프 키와 결과 칸 추가만 한다.
- 폰트를 내려받거나 `data/design/` 파일을 커밋하지 말고 실제 모델·서비스를 부르지 마라. 이유: 다운로드와 실제 호출은 사용자가 한다(AGENTS.md CRITICAL). 폰트가 필요한 케이스는 기존대로 명시적 skip이다.
