# Step 9h: no-band-product-line

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL 규칙(모델이 만든 문자열을 화면·이미지에 쓰지 않기, 새 Cypher는 계약에 없으면 금지: 이 step의 제품명 읽기는 예외로 명시된 고정 읽기 전용 질의 하나, 생성 시안은 로컬 전용, 외부 호출·다운로드는 사용자)
- `/docs/PROMPT_CHANGELOG.md`(읽기 전용, 이 step 뒤 구현 세션이 갱신한다), `/docs/results/2026-11-18-p5-live-agents.md`(읽기 전용), `/docs/CONTRACTS.md`(읽기 전용)
- `/src/beautyads/agents/design_compose.py`(전체: 상수·`layout_regions`·`_fit`·`_draw`·`compose_design`·`ComposedImage`), `/src/beautyads/agents/design_images.py`(읽기 전용), `/src/beautyads/api/assembly.py`(`image_fn`·`compose_design` 호출·작업 공간 루프의 `product_unit_price_query` 사용), `/src/beautyads/agents/supervisor.py`(`product_display` 결과 칸), `/src/beautyads/api/ask_view.py`(`show_plan`의 `product_display`·`image_reference`의 `composed` 통과), `/src/beautyads/obs/trace.py`(`TracePlan`·`build_trace`), `/src/beautyads/eval/agents_live.py`(요약이 `TracePlan` 덤프를 그대로 싣는 부분, **읽기 전용**), `/src/beautyads/graph/evidence_queries.py`(`product_unit_price_query`·`product_unit_price_parameters`의 형태), `/src/beautyads/domain/products.py`(`Product.name_ko`: 쇼핑몰 공식 한글 제품명, 그래프 `Product` 노드 속성), `/src/beautyads/domain/tenant.py`(`WorkspaceProfile`), `/config/workspaces.yaml`(`display_name`은 **작업 공간 이름**이지 제품명이 아니다), `/tests/test_design_compose.py`, `/tests/test_api_assembly.py`, `/tests/test_supervisor.py`, `/tests/test_ask_view.py`, `/tests/test_trace.py`, `/tests/test_agents_live.py`, `/tests/test_graph_evidence_queries.py`, `/tests/test_architecture.py` — step 6a·7b·7c·7d·9f·9g 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/agents/design_compose.py`, `src/beautyads/api/assembly.py`, `src/beautyads/agents/supervisor.py`, `src/beautyads/api/ask_view.py`, `src/beautyads/obs/trace.py`, `src/beautyads/graph/evidence_queries.py`, `tests/test_design_compose.py`, `tests/test_api_assembly.py`, `tests/test_supervisor.py`, `tests/test_ask_view.py`, `tests/test_trace.py`, `tests/test_agents_live.py`, `tests/test_graph_evidence_queries.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/agents/design_compose.py`(`BAND_RGBA` 제거, 새 상수와 순수 함수 추가, `layout_regions`에 `product` 영역 추가와 `cta` 영역 위치 조정, `_draw`·`compose_design`·`ComposedImage`의 띠 제거·그림자·대비 보정·CTA 옵션·제품명 줄 추가에 한함. 글자 정리 `_clean`·폰트 로딩 `_load_font`·`FontMissing`·`CTA_LABELS`·`cta_label`·줄바꿈 `_wrap`·말줄임 불변), `src/beautyads/api/assembly.py`(작업 공간 루프에서 제품명 조회 추가, `ask` 안에서 프로필 사본에 `product_name`을 넣는 것, `image_fn`의 `compose_design` 호출 인자를 `headline`·`product_line`으로 바꾸는 것, 합성 결과의 `contrast_adjusted`·`min_contrast`를 참조의 `composed` 칸에 옮기는 것, `cta_label` import 제거에 한함. 모델 호출 모양·상한·`IMAGE_CAP_REACHED`/`IMAGE_FAILED`/`compose_error` 경로·원본 저장 순서 불변), `src/beautyads/agents/supervisor.py`(결과 `product_display`에 `product_name` 키를 더하는 한 곳에 한함, 상태 키·흐름 불변), `src/beautyads/api/ask_view.py`(`show_plan`의 `product_display` 기본값에 `product_name` 키를 더하는 한 곳과 `image_reference`가 `composed`의 선택 칸 `contrast_adjusted`·`min_contrast`를 형식 검증 뒤 통과시키는 데 한함, 경로·base64를 싣지 않는 규칙·필수 칸 불변), `src/beautyads/obs/trace.py`(`TracePlan`에 선택 칸 `composed_contrast`를 더하고 `build_trace`가 기획안 `image.composed`에서 채우는 데 한함, 기존 칸·검증 불변), `src/beautyads/graph/evidence_queries.py`(새 함수 `product_name_query`·`product_name_parameters` 추가에 한함, 기존 질의·함수 불변), `tests/test_design_compose.py`(줄 단위로 명시한 갱신만 허용: `test_png_dimensions_safe_regions_and_original_pixels`의 `compose_design` 호출에 `with_cta=True`를 더하는 한 곳, 같은 함수의 CTA 상자 영역 단언 `inside(value.cta_box, (margin, 1024 - margin - int(1024 * compose.CTA_HEIGHT_RATIO), 1024 - margin, 1024 - margin))` 블록(`cta` 영역이 제품명 영역 위로 올라가므로)을 `compose.layout_regions(1024, 1024)["cta"]` 기준으로 바꾸는 한 곳과 "밴드 안 한 점이 어두워진다"를 확인하던 `!=` 단언을 띠가 없으므로 원본과 `==`로 바꾸는 한 줄, `test_minimum_font_ellipsizes_headline_and_single_line_cta`의 호출에 `with_cta=True`를 더하는 한 곳, `test_cta_ellipsis_and_centered_text_are_actually_drawn`의 호출에 `with_cta=True`를 더하는 한 곳과 `assert len(drawn) == 1 and drawn[0].endswith("…")` 한 줄을 그림자 그리기 호출을 허용하는 `assert drawn and set(drawn) == {drawn[0]} and drawn[0].endswith("…")`로 바꾸는 한 줄, `test_layout_regions_are_bounded_small_separate_edge_bands`의 `assert set(regions) == {"headline", "cta"}` 한 줄을 `product`를 포함하는 집합으로 바꾸는 한 줄, `test_compose_uses_image_height_fonts_and_preserves_entire_center`의 호출에 `with_cta=True`를 더하는 한 곳. 그 밖은 케이스 추가에 한함), `tests/test_api_assembly.py`(줄 단위: 이미지 합성 테스트의 가짜 `compose` 함수 시그니처 `def compose(value, *, headline, cta):`와 `assert cta == "지금 만나보기"` 두 줄을 `product_line` 인자 기준으로 바꾸는 한 곳, `assert result["product_display"] == {key: profile.get(key) for key in ("brand", "display_name")}`의 키 튜플에 `"product_name"`를 더하는 한 곳, 그 밖은 케이스 추가에 한함), `tests/test_supervisor.py`(`test_product_display_is_server_profile_only_and_no_handoff_distribution_is_empty`의 키 튜플에 `"product_name"`를 더하는 한 곳, 그 밖은 케이스 추가에 한함), `tests/test_ask_view.py`(`test_plan_has_fixed_image_disclaimer_and_separate_product_display`의 기본값 단언 `{"brand": None, "display_name": None}`에 `"product_name": None`을 더하는 한 줄, 그 밖은 케이스 추가에 한함), `tests/test_trace.py`·`tests/test_agents_live.py`(케이스 추가에 한함, 기존 단언 변경 0줄. 요약은 `TracePlan` 덤프를 그대로 싣고 기존 테스트가 같은 덤프와 비교하므로 새 칸이 자동으로 일치한다), `tests/test_graph_evidence_queries.py`(케이스 추가에 한함, 기존 단언 변경 0줄)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

9g 뒤 image 실행에서 사용자가 합성 이미지를 보고 지적한 세 가지를 고친다: (1) 글자가 검은 띠 안에 있을 필요가 없다, (2) 제품 정체성이 이미지에 없다, (3) "자세히 보기" CTA가 불필요하다. 제품 정체성은 **B안(코드가 브랜드·제품명을 이미지 하단 중앙에 한 줄로 작게 합성)**이 선택됐다. 이 step은 모델·실제 서비스를 부르지 않는다. **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.** 변경은 dev 개선 반복이고 이유·날짜는 구현 세션이 `docs/PROMPT_CHANGELOG.md`에 기록한다. **이미지 프롬프트(`image_prompt`·`IMAGE_NO_TEXT_CLAUSE`)는 바꾸지 않는다**(무라벨 일반 병 지시 그대로, 이미지 모델에 제품명·브랜드를 전달하지 않는다).

**1. 띠 제거와 가독성 보정(`agents/design_compose.py`, 순수 함수·결정적)**
- `BAND_RGBA`(반투명 검정 띠)를 **지우고** 띠를 그리지 않는다. 글자에는 은은한 **그림자**를 준다: 글자와 같은 모양을 `SHADOW_OFFSET_RATIO = 0.04`(글자 크기 대비 오프셋, 최소 1px)만큼 밀어 `GaussianBlur(radius = max(1, 글자 크기 * SHADOW_BLUR_RATIO))`, `SHADOW_BLUR_RATIO = 0.05`로 흐린 뒤 `SHADOW_ALPHA = 0.6`의 반대색으로 먼저 합성하고 글자를 그린다.
- **대비 보정 규칙**(글자 상자마다 독립, 상수·함수는 모듈 안): 글자가 놓일 상자(줄바꿈·크기 결정 뒤 측정된 글자 상자) 안 **원본 픽셀의 상대 휘도**(sRGB → 선형, `0.2126R+0.7152G+0.0722B`)를 구해 90번째 백분위수 `p_hi`와 10번째 백분위수 `p_lo`를 쓴다. 흰 글자의 대비 `c_white = 1.05 / (p_hi + 0.05)`, 어두운 글자(`DARK_TEXT = (17, 17, 17)`)의 대비 `c_dark = (p_lo + 0.05) / (L_dark + 0.05)`(`L_dark`는 `DARK_TEXT`의 상대 휘도). 상수 `MIN_CONTRAST_RATIO = 3.0`(WCAG AA 큰 글자 기준, 헤드라인은 큰 글자).
  1) `c_white >= MIN_CONTRAST_RATIO`면 **흰 글자, 보정 없음**(기존 단순 배경 `#7294b6`이 이 경우다).
  2) 아니고 `c_dark >= MIN_CONTRAST_RATIO`면 **어두운 글자(그림자는 밝은색), 보정 없음**(밝은 배경).
  3) 둘 다 못 미치면 둘 중 대비가 큰 쪽 글자색을 고르고 **그 영역에만 연한 그라데이션**(`SCRIM_MAX_ALPHA = 0.5`, 단계 `SCRIM_STEP = 0.05`)을 깐다: 흰 글자면 검정, 어두운 글자면 흰색 그라데이션, 영역의 바깥쪽 가장자리(헤드라인은 위, 제품명 줄·CTA는 아래)에서 `alpha`로 시작해 반대쪽으로 0까지 줄어든다(영역 전체 가로 폭, 영역 높이만큼만). `alpha`는 0.05 단위로 올려 **글자 상자 안 보정 뒤 대비가 `MIN_CONTRAST_RATIO` 이상이 되는 가장 작은 값**을 고르고, 없으면 `SCRIM_MAX_ALPHA`다(최선 시도). 보정 뒤 대비는 그라데이션을 반영한 같은 백분위수 방식으로 계산한다.
  이 상수들의 이유(변경 이유·날짜)는 코드 주석 한 줄과 `docs/PROMPT_CHANGELOG.md`에 남긴다(구현 세션이 기록).
- `ComposedImage`에 **기본값이 있는 새 필드**를 끝에 더한다(기존 필드·순서 불변): `headline_contrast: float | None = None`(보정 뒤 대비), `headline_scrim: float = 0.0`, `headline_color: str | None = None`(`"white"`|`"dark"`), `product_box`·`product_size`·`product_text`(그려진 제품명 줄, 없으면 `None`), `product_contrast`·`product_scrim`·`product_color`, `cta_contrast`·`cta_scrim`·`cta_color`(CTA를 그렸을 때만).

**1-1. 대비 보정 기록(조용히 넘어가지 않는다)**: `ComposedImage`에 기본값이 있는 칸을 더 둔다: `contrast_adjusted: bool = False`(**어느 글자 요소든 기본(흰 글자·보정 없음)에서 벗어났으면 참**: 어두운 글자로 바꿨거나 그라데이션을 깔았다)와 `min_contrast: float | None = None`(**그려진 글자 요소의 최종(보정 뒤) 대비 중 최솟값**, 그린 요소가 없으면 `None`). 체커보드처럼 대비를 만들 수 없는 배경은 최선 시도로 처리하되 `contrast_adjusted`가 참이고 `min_contrast`가 `MIN_CONTRAST_RATIO`보다 낮게 그대로 남아야 한다(사용자 화면·trace에서 보인다).
- 전달: `api/assembly.py`의 `image_fn`이 합성 결과(`compose_design` 반환)의 `contrast_adjusted`(`bool`)·`min_contrast`(유한한 `float`, 소수 3자리로 반올림)를 **있을 때만** 참조 `composed` 칸에 `"contrast_adjusted"`·`"min_contrast"`로 옮긴다(결과 객체가 이 속성이 없으면 — 예: 기존 테스트의 가짜 합성기 — 키를 넣지 않고 오류도 내지 않는다). `api/ask_view.py`의 `image_reference`는 `composed`의 이 두 선택 칸을 형식 검증(`bool`, 음이 아닌 유한한 숫자) 뒤 통과시키고 검증에 실패하면 그 칸만 뺀다(`mime`·`size`·`sha256` 검증과 경로·base64 금지 불변). 따라서 `show_plan` 데이터의 `image.composed`에 실린다. `obs/trace.py`: `TracePlan.composed_contrast: TraceComposedContrast | None = None`(`TraceComposedContrast(contrast_adjusted: bool, min_contrast: float | None)`)를 더하고 `build_trace`가 `plans[i].image.composed`에서 형식을 검증해 채운다(없으면 `None`). `eval/agents_live.py` 요약은 `TracePlan` 덤프를 그대로 싣는 기존 코드라 새 칸이 자동으로 포함된다(코드 변경 없음).

**2. CTA는 기본으로 넣지 않는다**: `compose_design(image_bytes, *, headline, cta="", product_line="", with_cta=False, font_dir=...)`. **`with_cta`가 거짓이면 `cta`를 무시한다**(CTA 영역을 그리지 않고 `cta_box`가 `None`). CTA 합성 코드·`CTA_LABELS`·`cta_label`은 **지우지 않는다**(`with_cta=True`로 다시 켤 수 있다). `CtaType`은 기획안 데이터로만 보여 준다(`show_plan` 데이터의 `plan.cta_type`: 이미 기획안 칸이 그대로 실린다).

**3. 제품명 한 줄(B안)**
- 순수 함수 `product_line(brand: str | None, product_name: str | None) -> str`(`design_compose.py`): 형식 **`"{brand}  {제품명}"`**(두 칸 공백). 글자 출처는 **프로필 `brand` 값과 쇼핑몰 공식 한글 제품명뿐이다**(모델이 만든 문자열은 받지 않는다). 브랜드는 **영문 발음을 한글로 옮긴 표기를 만들지 않고 프로필 `brand` 값 그대로** 쓴다(밑줄 `_`만 공백으로 바꾼다: `beauty_of_joseon` → `beauty of joseon`). 제품명은 **용량 표기를 제외**한다: `\d+(?:\.\d+)?\s*(?:ml|mL|g|kg|l|L|매|입|ea|개)` 토큰과 그 앞뒤의 쉼표·괄호·공백을 제거한다(예: `... 세럼 50ml` → `... 세럼`). `_clean`(제어 문자·URL 제거, 공백 정리)을 거치고 전체를 `MAX_PRODUCT_LINE_CHARS = 60`자로 자른다. **둘 중 하나라도 값이 있으면 있는 것만** 쓰고(브랜드만/제품명만) **둘 다 없거나 정리 뒤 비면 빈 문자열**(줄 생략)이다. 문자열이 아닌 입력(`None` 포함)은 값 없음으로 본다.
- 레이아웃: `layout_regions`에 `"product"` 영역을 더한다: 아래 여백 위로 `PRODUCT_HEIGHT_RATIO = 0.045` 높이의 가운데 정렬 영역. **`cta` 영역은 그 위로 올린다**(영역끼리 겹치지 않고 `headline` 영역은 그대로이며, 모든 영역은 이미지 경계·여백 안, `cta`·`product`는 높이 75% 아래에서 시작). 글자 크기는 `PRODUCT_FONT_RATIO = 0.03`(이미지 높이의 약 3%, **헤드라인보다 작게**: `PRODUCT_FONT_RATIO < HEADLINE_FONT_RATIO`), **SemiBold**(`_SEMIBOLD`), **한 줄**, 영역 안에 안 들어가면 `MIN_FONT_PX`까지 줄이고 그래도 넘으면 말줄임(`_fit` 기존 규칙 재사용). 띠 없이 헤드라인과 **같은 그림자·대비 보정 규칙**을 쓴다. **헤드라인은 상단, 제품명 줄은 하단, 중앙 25~75%는 계속 비운다**.

**4. 데이터 흐름(제품명 출처)**: 작업 공간 `display_name`(`config/workspaces.yaml`)은 **"믹순 개발 작업 공간"** 같은 작업 공간 이름이라 이미지에 쓸 수 없다. 쇼핑몰 공식 한글 제품명은 그래프 `Product` 노드의 `name_ko` 속성이다(P4 적재). 이 step은 그 값을 읽는 **새 고정 읽기 전용 Cypher 하나**를 예외로 허용한다(효능 조회 등 다른 새 Cypher는 여전히 금지).
- `graph/evidence_queries.py`: `product_name_query() -> str`(`MATCH (p:Product) WHERE p.brand = $brand AND p.source_url = $url RETURN p.name_ko AS product_name`, 읽기 전용·고정·`$` 파라미터만)와 `product_name_parameters(*, brand, url) -> dict`(`product_unit_price_parameters`와 같은 입력 검증: 빈 문자열·문자열 아님이면 `ValueError("PRODUCT_NAME_INPUT_INVALID")`).
- `api/assembly.py`: 작업 공간 시드 루프에서 가격대 조회 옆에 `product_name_query()`를 실행해 첫 행의 `product_name`(비어 있지 않은 문자열)을 `product_names[tenant_id]`에 둔다(없거나 조회가 실패하면 넣지 않고 예외를 올리지 않는다, 진단 값 미노출). `ask` 안에서 **프로필 사본**에 `"product_name": product_names.get(tenant_id)`를 더해 `run_request`와 `image_fn`에 쓴다(`Assembly`의 필드·`workspaces` 값은 바꾸지 않는다). `image_fn`은 `compose_design(outcome.image_bytes, headline=plan["hook_text"], product_line=product_line(profile["brand"], profile.get("product_name")))`를 부른다(`cta`를 넘기지 않는다, `cta_label` import 제거). 합성 실패 처리(`compose_error`)·원본 저장 순서는 그대로다.
- `agents/supervisor.py`: 결과 `product_display`가 **`{"brand", "display_name", "product_name"}`**를 프로필에서 그대로 싣는다(`display_name`은 화면 UI용 작업 공간 이름, `product_name`은 쇼핑몰 공식 제품명, 값이 없으면 `None`). `api/ask_view.py`: `show_plan`의 `product_display` 기본값이 `{"brand": None, "display_name": None, "product_name": None}`이다(기획안 안의 모델이 쓴 `product_display`는 계속 무시한다).

**새 칸·상수 대응표(만드는 파일 → 읽는 파일)**
| 칸·상수 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `product_name_query`·`product_name_parameters` | `graph/evidence_queries.py` | `api/assembly.py`, `tests/test_graph_evidence_queries.py` |
| `product_names`(작업 공간 ID → 제품명) | `api/assembly.py`(시드 루프) | `api/assembly.py`(`ask`의 프로필 사본) |
| 프로필 사본 `product_name` | `api/assembly.py`(`ask`) | `agents/supervisor.py`(`product_display`), `api/assembly.py`(`image_fn`) |
| `product_display.product_name` | `agents/supervisor.py` | `api/ask_view.py`(`show_plan`), 테스트 |
| `product_line` 함수 | `agents/design_compose.py` | `api/assembly.py`(`image_fn`), `tests/test_design_compose.py` |
| `compose_design`의 `product_line`·`with_cta` 인자와 `ComposedImage` 새 필드 | `agents/design_compose.py` | `api/assembly.py`(`product_line`만), 테스트 |
| `layout_regions()["product"]`·`PRODUCT_FONT_RATIO`·`PRODUCT_HEIGHT_RATIO`·`MAX_PRODUCT_LINE_CHARS` | `agents/design_compose.py` | `compose_design`(같은 파일), `tests/test_design_compose.py` |
| `MIN_CONTRAST_RATIO`·`SCRIM_MAX_ALPHA`·`SCRIM_STEP`·`SHADOW_*`·`DARK_TEXT` | `agents/design_compose.py` | `compose_design`(같은 파일), `tests/test_design_compose.py` |
| `ComposedImage.contrast_adjusted`·`min_contrast` | `agents/design_compose.py` | `api/assembly.py`(`image_fn`), `tests/test_design_compose.py` |
| 참조 `composed.contrast_adjusted`·`composed.min_contrast` | `api/assembly.py`(`image_fn`) | `api/ask_view.py`(`image_reference`), `obs/trace.py`(`build_trace`), `tests/test_api_assembly.py`·`tests/test_ask_view.py` |
| `show_plan` 데이터 `image.composed` 두 칸 | `api/ask_view.py` | 화면(사용자), `tests/test_ask_view.py` |
| `TracePlan.composed_contrast` | `obs/trace.py` | `eval/agents_live.py`(요약이 덤프를 그대로 싣는다), `tests/test_trace.py`·`tests/test_agents_live.py` |

**반드시 있어야 하는 테스트**(합성 이미지·가짜 폰트(Pillow 기본 폰트 주입)·합성 프로필·가짜 그래프. 모델 문장을 기대값으로 굳히지 않고 상수는 import해 경계로 단언한다)
- **띠 제거·그림자(`tests/test_design_compose.py`)**: `BAND_RGBA`가 모듈에 없다(`not hasattr`). 기존 단순 배경(`#7294b6`)에서 `headline_scrim == 0.0`·`headline_color == "white"`이고 영역 안 글자 상자 밖의 픽셀(예: `(margin + 1, margin + 1)`)이 **원본과 같다**(띠·그라데이션 없음). 글자 상자 주변에 그림자로 원본과 다른(어두워진) 픽셀이 있다(그림자 존재).
- **대비 보장**: 합성 배경 `흰색(255)`·`거의 흰색(240)`은 `headline_color == "dark"`·`headline_scrim == 0.0`이고 `headline_contrast >= MIN_CONTRAST_RATIO`, `어두운 회색(20)`·`중간 회색(128)`은 `"white"`·보정 없음·대비 이상, **`[200, 255]` 구간 시드 고정 노이즈**(`random.Random(0)`)는 대비 이상, **`[60, 160]` 구간 시드 고정 노이즈**(복잡한 배경)는 `headline_scrim > 0`이고 `<= SCRIM_MAX_ALPHA`이며 보정 뒤 `headline_contrast >= MIN_CONTRAST_RATIO`이고 보정 전 대비보다 낮아지지 않는다. **체커보드(흰/검정 8px)** 는 보정 뒤 대비가 보정 전보다 낮아지지 않고(최선 시도) 상자가 영역 안이며 중앙이 비어 있다(대비 보장은 단언하지 않는다). 각 경우에 `headline_box`가 이미지·`layout_regions()["headline"]` 안이고 이미지 중앙 영역(높이 25~75%)의 픽셀이 원본과 같다(같은 결과를 1024×1024와 512×1024에서). 같은 입력이면 PNG 바이트가 같다(결정적).
- **대비 보정 기록**: `ComposedImage`에서 기존 단순 배경(`#7294b6`)은 `contrast_adjusted is False`, 흰·거의 흰·`[200, 255]` 노이즈(어두운 글자)와 `[60, 160]` 노이즈(그라데이션)는 `contrast_adjusted is True`, 어두운 회색(20)·중간 회색(128)은 `False`이고 모든 경우 `min_contrast`가 그려진 요소의 최종 대비 중 최솟값(`headline_contrast`·`product_contrast`와 일치)이다. **체커보드는 `contrast_adjusted is True`이고 `min_contrast < MIN_CONTRAST_RATIO`가 그대로 남는다**(숨기지 않음), 글자를 그리지 않으면 `min_contrast is None`이고 `contrast_adjusted is False`다. 전달: 조립 경유 테스트가 합성 결과(`SimpleNamespace(png_bytes=..., contrast_adjusted=True, min_contrast=2.345678)`)에서 참조 `composed`에 `contrast_adjusted is True`·`min_contrast == 2.346`이 실리고, 속성이 없는 가짜 합성기(기존 테스트 형태)에서는 두 키가 없고 합성이 성공한다. `image_reference`가 두 칸을 통과시키고(`bool`·음이 아닌 유한 `float`), 형식 밖(문자열 `contrast_adjusted`·`NaN`·음수·`True` 아닌 정수)은 그 칸만 빠지며 `mime`·`size`·`sha256`·경로 금지는 그대로이고 입력 객체를 바꾸지 않는다. `show_plan` 데이터 `image.composed`에 두 칸이 있다. `trace`: 합성 결과에서 `record.plans[i].composed_contrast`가 채워지고 `composed`가 없거나 형식 밖이면 `None`이며 합성 비밀 문자열이 들어간 값은 기록되지 않는다. `agents_live` 요약의 기획안 항목에 `composed_contrast`가 trace 값 그대로 있다(`TracePlan` 덤프).
- **CTA 기본 끔**: `with_cta` 기본에서 `cta="자세히 보기"`를 줘도 `cta_box is None`이고 `with_cta=True`면 이전처럼 그려진다(`cta_box` 영역 안). `cta_label`·`CTA_LABELS`(키 집합 == `set(CtaType)`)는 그대로 있다. `show_plan` 데이터(`tests/test_ask_view.py`의 기존 합성 결과에 `cta_type`이 있으면 그 값 단언 추가, 없으면 합성)의 `data["plan"]["cta_type"]`이 기획안 값 그대로다.
- **제품명 줄(`product_line`·합성)**: `product_line("beauty_of_joseon", "인삼선세럼 SPF50+ 50ml")`가 밑줄이 공백이 되고 용량이 빠진 `"beauty of joseon  인삼선세럼 SPF50+"` 형태이며(정확한 문자열은 합성 값으로 단언), 용량 토큰(`50ml`·`30 g`·`2매`·`(100mL)`)이 모두 빠진다. 브랜드만/제품명만/둘 다 없음(`None`·빈 문자열·공백)에서 각각 브랜드만·제품명만·`""`이고 문자열이 아닌 입력도 `""`이며 예외가 없다. 제어 문자·URL이 제거되고 `MAX_PRODUCT_LINE_CHARS`로 잘린다. **한글 발음 표기를 만드는 변환이 없다**(영문 브랜드 입력이 그대로 출력에 들어간다). 합성: 줄이 있으면 `product_box`가 `layout_regions()["product"]` 안이고 `product_size == max(MIN_FONT_PX, int(height * PRODUCT_FONT_RATIO))`(짧은 줄)이며 `product_size < headline_size`, `0.025 <= PRODUCT_FONT_RATIO <= 0.035`, 가로 가운데 정렬(±1px), 한 줄(줄바꿈 없음), 긴 줄은 크기 축소 뒤 말줄임이다. 줄이 비면 `product_box is None`이고 이미지가 영향을 받지 않는다(헤드라인도 없으면 입력과 픽셀이 같다). **헤드라인 영역·`cta` 영역·`product` 영역이 서로 겹치지 않고** 모두 경계·여백 안이며 `cta`·`product` 영역이 높이 75% 아래에 있다(여러 크기). 합성이 실패하지 않는다(폰트 로딩·그림자·보정은 예외 없이).
- **출처(모델 문자열 미유입)**: `tests/test_api_assembly.py`의 조립 경유 테스트에서 가짜 `compose_design`이 받은 인자를 직접 연다: `product_line` 인자가 `product_line(profile["brand"], 가짜 그래프가 돌려준 제품명)`과 같고, **plan의 `title`·`hook_text`·`scenes`·`copy_lines`·`image_brief`에 넣은 합성 문장(`MODEL_SENTINEL_…`)이 `product_line` 인자에 없으며** `cta` 인자를 넘기지 않고 `headline`은 `plan["hook_text"]`다. 가짜 그래프가 제품명 질의에 행을 안 주거나 예외를 던지면 `product_line`이 브랜드만이고 요청이 성공하며 `product_display["product_name"]`이 `None`이다. 제품명 질의가 `product_name_query()`와 `product_name_parameters(brand=..., url=...)`로만 실행됐다(가짜가 받은 질의 문자열·파라미터 직접 검사, 다른 새 Cypher 없음). 조립 결과의 `product_display`가 `{"brand", "display_name", "product_name"}` 세 칸이고 `product_name`이 그래프 값(합성)이다(`display_name`은 작업 공간 이름 그대로).
- **질의(`tests/test_graph_evidence_queries.py`)**: `product_name_query()`가 읽기 전용(쓰기 키워드 없음)·고정·`$brand`·`$url` 파라미터만 쓰고 `p.name_ko AS product_name`만 돌려주며 입력이 질의 문장에 끼지 않는다. `product_name_parameters`가 빈 문자열·문자열 아님·`None`에서 `ValueError("PRODUCT_NAME_INPUT_INVALID")`를 올리고 정상 입력에서 `{"brand", "url"}`을 돌려준다. 기존 질의 본문 불변.
- **표시 칸**: `tests/test_supervisor.py`의 `product_display`가 세 칸(`product_name` 없으면 `None`)이고 모델 출력이 아닌 프로필 값이다. `tests/test_ask_view.py`의 `show_plan` `product_display` 기본값이 세 칸 `None`이고 기획안 안의 모델이 쓴 `product_display`는 무시된다.
- 기존 `tests/test_architecture.py`·`tests/test_schema_guard.py`·`tests/test_llm_param_guard.py`가 그대로 통과하고 `design_compose.py`는 Pillow·표준 라이브러리만 import한다(`graph`·`api` import 없음).

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

- 이미지 프롬프트에 제품명·브랜드를 넣거나 `image_prompt`·`IMAGE_NO_TEXT_CLAUSE`를 바꾸지 마라. 이유: 이미지 모델이 글자를 깨뜨린다(live 관측). 제품명·브랜드는 코드가 폰트로 합성하고 이미지 모델에는 무라벨 일반 병만 요청한다(조언 세션 결정).
- 제품명 줄에 모델이 만든 문자열(기획안의 title·hook_text·scenes·copy_lines·image_brief·핸드오프)이나 작업 공간 `display_name`(작업 공간 이름)을 쓰거나 브랜드의 한글 발음 표기를 만들지 마라. 이유: 글자 출처는 프로필 `brand` 값과 쇼핑몰 공식 한글 제품명(`Product.name_ko`)뿐이다(조언 세션 결정). 모델 문자열이 이미지에 들어가면 안 된다.
- `product_name_query` 외의 새 Cypher를 만들거나 `product_unit_price_query`·기존 질의를 바꾸지 마라. 이유: 새 질의는 이 하나만 예외로 승인된다(읽기 전용 고정 질의). 효능 조회·분포 등 다른 읽기는 기존 질의만 쓴다(AGENTS.md CRITICAL).
- CTA 합성 코드·`CTA_LABELS`·`cta_label`을 지우거나 `compose_design`의 `with_cta` 기본값을 참으로 두지 마라. 이유: 기본은 끄되 나중에 다시 켤 수 있게 남기는 결정이다. 기본에서 `cta`를 넘겨도 그리지 않는다.
- 허용 목록 밖의 기존 단언을 바꾸거나 새 상수 값을 테스트에 `== 0.03`처럼 굳히지 마라. 이유: 값은 조정 대상이고(B-FP-061) 기대값 갱신은 함수·줄 단위로 허용한 곳뿐이다. 상수는 import해 경계(`0.025 <= … <= 0.035` 등)로 검사한다.
- `ComposedImage`의 기존 필드·순서·`compose_design`의 기존 인자 이름을 바꾸거나 `design_compose.py`에서 `graph`·`api`·모델 SDK를 import하지 마라. 이유: 9f에서 검증한 계약이고 합성은 순수 함수여야 한다(계층·테스트 용이성). 새 필드와 인자는 기본값이 있는 추가만 한다.
