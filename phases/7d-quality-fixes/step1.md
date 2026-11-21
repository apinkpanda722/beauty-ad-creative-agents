# Step 1: design-quality

## 설계 검토 기록

**배경(P7 화면 확인에서 나온 서버 쪽 품질 문제, 7d)**: 시안 이미지를 사람이 보고 두 가지 문제가 확인됐다. (1) **프롬프트**: `agents/design_images.py`의 `image_prompt(plan)`은 `plan.image_brief` 뒤에 `IMAGE_NO_TEXT_CLAUSE`("단일 컷, 글자·로고·브랜드·제품명·라벨 금지, 제품은 무라벨 일반 병·튜브·패키지")만 붙인다. 그 결과 내용물이 없는 맹물 같은 투명 병이 나오고, 병을 코에 대는 구도가 나오고, 인물이 서양인으로 나오고, 기획안 장면과 이미지가 어긋났다(시안 4장 중 병 제품 2장이 문제, 튜브 2장은 정상이었으나 튜브를 얼굴에 직접 대는 구도가 있었다). (2) **합성**: `agents/design_compose.py`의 `_scrim`은 글자 영역(region)에만 막을 깐다. region은 이미지 가장자리에서 안쪽(위쪽·좌우 5% 여백)에 있어 **영역의 위·왼쪽·오른쪽 경계에서 막이 갑자기 시작해 각진 어두운 사각형**으로 보인다. 이 step은 둘을 고친다. 이 step은 서버(`agents/`)만 바꾸고 `web/`은 건드리지 않는다(화면은 7c).

**식별자 전수 대조(현재 코드, 모두 열어 확인)**:
- `agents/design_images.py`: `IMAGE_NO_TEXT_CLAUSE`(문자열 상수), `image_prompt(plan: Plan) -> str`(장면 `plan.image_brief`에서 `※`·`참고:`·`주의:`·`설명:`·`지시:`·`Note:` 줄, 괄호 `() [] （） <>`, 따옴표 안 문장, URL을 지우고 `scene = "\n".join(cleaned)[: 2000 - len(IMAGE_NO_TEXT_CLAUSE) - 1].rstrip()`, 반환 `(scene + "\n" if scene else "") + IMAGE_NO_TEXT_CLAUSE`, 길이 2000자 상한). **정지 선**: `agents/planning.py`의 `image_brief` 규칙(프롬프트 동결 줄, `tests/test_prereg.py`·`tests/test_freeze_guard.py`가 해시로 지킨다)은 **건드리지 않는다**. 이 step이 쓰는 파일은 동결 줄에 없다(`tests/test_freeze_guard.py`·`tests/test_prereg.py`에서 `design_images`·`design_compose` 참조 없음, 2026-11-21 `rg` 확인).
- `agents/design_compose.py`: 상수 `MARGIN_RATIO = 0.05`, `HEADLINE_HEIGHT_RATIO = 0.16`, `CTA_HEIGHT_RATIO = 0.06`, `PRODUCT_HEIGHT_RATIO = 0.045`, `MIN_CONTRAST_RATIO = 3.0`, `SCRIM_MAX_ALPHA = 0.5`, `SCRIM_STEP = 0.05`; `layout_regions(width, height)`(`headline`·`cta`·`product` 상자, 좌우 `margin`·위 `vertical_margin`); `_scrim(patch, *, alpha, color, edge)`(patch 행마다 `edge == "top"`이면 위 1 → 아래 0, 아니면 0 → 1로 줄어드는 마스크, **가로는 균일**); `_contrast_style(original, *, box, region, edge)`(region을 잘라 글자 상자 `box`의 대비를 재고 `SCRIM_STEP`씩 알파를 올려 `MIN_CONTRAST_RATIO`에 닿을 때까지 `_scrim`, 반환 `color, alpha, contrast, adjusted`); `_draw(image, *, original, text, region, filename, directory, max_lines, font_ratio, edge)`(`image.paste(patch, (left, top))`로 막을 붙이고 그림자·글자를 region 안에만 그림); `compose_design(...)`(요소별 `("headline", ..., "top")`, `("product", ..., "bottom")`, `("cta", ..., "bottom")`).
- **막의 경계 문제의 정확한 위치(코드 추론)**: 막은 region 안에서 `edge == "top"`일 때 **region 맨 위 행이 최대 강도**이므로 region의 위쪽 경계(이미지 가장자리보다 5% 안쪽)·왼쪽·오른쪽 경계에서 강도가 0에서 최대로 갑자기 바뀐다. 아래쪽(`edge == "bottom"`)은 반대로 region 아래·좌우 경계에서 갑자기 시작한다.
- 소비자 테스트: `tests/test_design_images.py`는 `IMAGE_NO_TEXT_CLAUSE`를 이름으로 불러 `prompt.endswith(IMAGE_NO_TEXT_CLAUSE)`(145·154·178행), `len(image_prompt(...)) == 2000`(58행), **정확 일치 `prompt == "SYNTH_VISUAL\n" + IMAGE_NO_TEXT_CLAUSE`(250행)·`image_prompt(plan(image_brief=brief)) == IMAGE_NO_TEXT_CLAUSE`(270행)·`== "SYNTH_VISUAL_AFTER\n" + IMAGE_NO_TEXT_CLAUSE`(281행)**와 문구 포함 단언(260행)을 한다. `tests/test_api_assembly.py` 137행은 `prompt.endswith(IMAGE_NO_TEXT_CLAUSE)`만 단언한다. `tests/test_design_compose.py`는 막을 region 안에서 독립 재구성한다(`test_scrim_uses_smallest_step_and_correct_edge_fade`, 548행: region 안의 행 기울기와 `inner_y`에서 원본과 같음을 단언)·`test_png_dimensions_safe_regions_and_original_pixels`(40행)는 `(0, 0)`·`(512, 512)`·`(margin + 1, margin + 1)` 픽셀이 원본과 같음을 단언한다.

**설계 결정**:
1. **이미지 프롬프트**: 새 상수 `IMAGE_STYLE_CLAUSE`(아래 글자 그대로)와 조합 상수 `IMAGE_PROMPT_SUFFIX = IMAGE_STYLE_CLAUSE + " " + IMAGE_NO_TEXT_CLAUSE`를 더한다. `image_prompt`는 장면 뒤에 **`IMAGE_PROMPT_SUFFIX`**를 붙이고 장면 길이 상한을 `2000 - len(IMAGE_PROMPT_SUFFIX) - 1`로 계산한다(기존 `IMAGE_NO_TEXT_CLAUSE` 상수 값·괄호/주석/따옴표/URL 제거 로직·2000자 한도는 그대로). `IMAGE_NO_TEXT_CLAUSE`는 값이 바뀌지 않고 접미사의 **맨 끝**에 남는다(`endswith` 단언 유지).
   `IMAGE_STYLE_CLAUSE`(글자 그대로 고정, 줄바꿈 없는 한 문자열):
   `장면은 훅 문구를 가장 잘 보여 주는 하나의 순간으로 고르고 기본은 사용 장면이다(손등이나 볼에 제품을 바르는 손과 피부 클로즈업). 얼굴 전체를 정면으로 잡는 구도와 병이나 튜브를 코나 입에 대는 구도는 그리지 않는다. 용기가 나오면 내용물이 보여야 한다(맑은 물처럼 보이는 투명 액체 금지, 세럼은 약간 점성이 있는 연한 색 액체와 스포이트나 펌프 형태, 튜브는 닫힌 튜브). 제품을 얼굴에 직접 대거나 문지르지 말고 손가락 끝에 덜어 바르는 모습으로 그린다. 인물이 나오면 한국인 모델이다.`
   (이 문구의 괄호는 **장면 정리 단계가 아니라 접미사**라서 지워지지 않는다: `image_prompt`는 장면 문자열에만 정리를 적용한다.)
2. **합성 막 확장**: 막의 **세로 기울기 모양은 region 안에서 지금과 같게 두고**(그래서 글자 상자의 대비 측정값과 `SCRIM_*`·`MIN_CONTRAST_RATIO` 규칙이 불변) region 밖으로 **경계 없이 이어 붙인다**: `headline`은 이미지 위 가장자리(`y = 0`)와 좌우 끝(`x = 0`·`width`)까지, `product`는 아래 가장자리(`y = height`)와 좌우 끝까지, `cta`는 좌우 끝까지만(세로는 region 그대로: CTA는 기본 꺼짐(`with_cta=False`)이고 위아래 이웃 막과 겹치지 않게 한다). 확장한 영역의 세로 강도: `edge == "top"`이면 region 위쪽 위의 행은 **강도 1(최대)**, region 안은 지금처럼 1 → 0, region 아래는 0; `edge == "bottom"`이면 region 위는 0, region 안은 0 → 1, region 아래쪽 행은 **강도 1**. 가로는 계속 균일하므로 좌우 경계에서도 계단이 없다. 구현: 새 함수 `scrim_region(region, size, element) -> (left, top, right, bottom)`로 확장 상자를 만들고 `_scrim`이 `inner`(확장 patch 안에서 region의 위·아래 행)를 받아 위 규칙으로 마스크를 만든다. `_contrast_style`은 **확장 patch로 막을 만들되 글자 상자 대비는 같은 위치(region 안)에서 측정**해 반환한다. `_draw`는 확장 patch를 **확장 상자의 왼쪽 위**에 붙이고 그림자·글자는 region 안에 그대로 그린다.
3. **보정 후 대비를 최종 합성 이미지 기준으로 다시 측정**한다: `compose_design`이 모든 요소의 **막을 붙인 뒤 글자를 그리기 전**의 중간 이미지에서 각 요소의 글자 상자 대비를 다시 재서 `*_contrast`·`min_contrast` 기록에 쓴다(`contrast_adjusted`·`min_contrast`의 의미와 필드는 불변, 값이 단지 최종 중간 이미지 기준이 된다). 막이 없는 요소(보정 불필요)는 지금처럼 원본 측정값이다.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `IMAGE_STYLE_CLAUSE`·`IMAGE_PROMPT_SUFFIX` | `agents/design_images.py` | `image_prompt`, `tests/test_design_images.py`, `api/assembly.py`(`image_prompt` 호출, 코드 변경 없음) |
| `scrim_region`, 확장 `_scrim`(`inner` 인자) | `agents/design_compose.py` | `_contrast_style`·`_draw`·`compose_design`, `tests/test_design_compose.py` |
| 프롬프트·합성 변경 기록 | `docs/PROMPT_CHANGELOG.md`(행 추가) | 사람(조언 세션), 상세 페이지 "부딪힌 문제" 원천 |

**기존 단언과의 충돌 점검(`rg`·읽기로 확인)**:
- `tests/test_design_images.py` 250·270·281행의 **정확 일치 기대값**은 접미사가 `IMAGE_NO_TEXT_CLAUSE`에서 `IMAGE_PROMPT_SUFFIX`로 바뀌므로 `IMAGE_PROMPT_SUFFIX`로 **갱신만** 한다(`==` 유지, 부분 문자열로 바꾸지 않음). 58행 `len == 2000`·145·154·178행 `endswith(IMAGE_NO_TEXT_CLAUSE)`·260행 문구 포함은 그대로 통과해야 한다.
- `tests/test_design_compose.py`의 막 재구성 테스트는 region 안의 기울기·글자 상자 대비를 단언하므로 그대로 통과해야 한다(region 안 모양 불변). `test_png_dimensions_safe_regions_and_original_pixels`의 `(0, 0)`·`(margin + 1, margin + 1)` 픽셀 동일 단언은 **그 합성 입력에서 막이 적용되지 않으면**(대비가 충분하면 막 없음) 그대로 통과한다. 막이 적용되는 경우 위·좌우 가장자리 픽셀이 어두워지는 것이 **의도된 변경**이므로, 그런 단언이 실패하면 단언을 지우지 말고 "막 확장 영역 밖(중앙 25~75%, `compose_uses_image_height_fonts_and_preserves_entire_center`가 지키는 영역)은 원본과 같다"로 **옮기고** 막 확장 영역의 새 불변식(아래 테스트)을 더한다. `tests/test_api_assembly.py` 137행은 불변.
- 동결 가드: 이 step이 건드리는 모듈은 동결 줄·해시 대상이 아니다. `tests/test_prereg.py`·`tests/test_freeze_guard.py`는 건드리지 않는다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`(CRITICAL: 동결 기준을 바꾸지 않는다, 모델 호출 규칙), `/docs/PROMPT_CHANGELOG.md`(형식과 기존 이미지·합성 행: 9e·9g·9h), `/docs/ARCHITECTURE.md`
- `/src/beautyads/agents/design_images.py`, `/src/beautyads/agents/design_compose.py`, `/src/beautyads/agents/planning.py`(`image_brief` 규칙은 읽기 전용)
- `/tests/test_design_images.py`, `/tests/test_design_compose.py`(합성 입력 생성 함수 `synthetic_background`·`pixels`·`measured_contrast`·`fonts` 픽스처), `/tests/test_api_assembly.py`(137행 부근), `/tests/test_freeze_guard.py`·`/tests/test_prereg.py`(읽기 전용: 동결 대상 확인)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/agents/design_images.py`, `src/beautyads/agents/design_compose.py`, `docs/PROMPT_CHANGELOG.md`, `tests/test_design_images.py`, `tests/test_design_compose.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `src/beautyads/agents/design_images.py`, `src/beautyads/agents/design_compose.py`, `docs/PROMPT_CHANGELOG.md`, `tests/test_design_images.py`, `tests/test_design_compose.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** 위 "설계 결정" 1~3을 구현한다. `agents/planning.py`·`api/assembly.py`·`web/`은 수정하지 않는다.

**2. `docs/PROMPT_CHANGELOG.md`**: 표 끝에 행을 **추가**한다(기존 행은 고치지 않는다): `2026-11-21 | — | agents/design_images.py(이미지 프롬프트, 코드)` — 장면 뒤 접미사에 `IMAGE_STYLE_CLAUSE` 추가(사용 장면 기본, 얼굴 정면·병을 코나 입에 대는 구도 금지, 내용물이 보이는 용기, 제품을 얼굴에 직접 대지 않고 손가락 끝에 덜어 바르기, 한국인 모델), 이유: 화면 확인에서 맹물 같은 투명 병·병을 코에 대는 구도·서양인·기획안 장면과 어긋난 이미지가 나옴(4장 중 병 2장), 동결 줄(`planning.py`의 `image_brief` 규칙)이 아니라서 사전 등록 문서는 건드리지 않는다. 한 행 더: `2026-11-21 | — | agents/design_compose.py(합성, 코드)` — 막을 이미지 가장자리까지 확장(`scrim_region`), region 안 기울기·`MIN_CONTRAST_RATIO`·`SCRIM_*` 불변, 이유: region 경계에서 막이 갑자기 시작해 각진 어두운 사각형으로 보임.

**테스트(합성 데이터, 모델·네트워크·폰트 다운로드 없음 — `tests/test_design_compose.py`의 기존 `fonts` 픽스처 사용)**
- `tests/test_design_images.py`(케이스 추가 + 위 세 정확 일치 기대값 갱신): (1) **`IMAGE_STYLE_CLAUSE`가 위 문구와 글자 그대로 같다**(테스트에 그 문자열을 그대로 적는다), (2) `IMAGE_PROMPT_SUFFIX == IMAGE_STYLE_CLAUSE + " " + IMAGE_NO_TEXT_CLAUSE`이고 `IMAGE_NO_TEXT_CLAUSE` 값은 불변(기존 문구 단언 유지), (3) `image_prompt`의 끝이 `IMAGE_PROMPT_SUFFIX`이고 길이가 2000을 넘지 않으며 장면이 길어도 접미사가 잘리지 않는다(`image_brief="가" * 3000` → 길이 2000, 끝이 접미사), (4) 접미사의 괄호 문구가 장면 정리로 지워지지 않는다(접미사의 `(손등이나 볼에 제품을 …)`가 결과에 남음), (5) 장면의 괄호·주석·따옴표·URL 제거는 기존과 같다(기존 테스트 유지), (6) `image_brief=None`이면 접미사만 반환.
- `tests/test_design_compose.py`(케이스 추가, 기존 단언 약화 금지): 막이 필요한 **균일한 밝은 합성 이미지**(예: 전체 RGB 240, 헤드라인 흰 글자 대비 부족)로 `compose_design`을 호출해 (7) **위쪽 가장자리 행(`y = 0`)이 원본보다 어둡다**(막이 이미지 가장자리까지 이어짐), (8) **region 경계에서 계단이 없다**: 글자가 없는 같은 행(예: `y = margin + 1`, 글자 상자 밖)에서 `x = region_left - 1`과 `x = region_left`의 픽셀 차이가 1 이하, 오른쪽 경계도 같고, 위쪽 경계에서 `y = region_top - 1`과 `y = region_top`(같은 `x`)의 차이가 1 이하, (9) 막의 세로 기울기가 region 아래 경계에서 0으로 이어진다(`y = region_bottom + 1` 픽셀이 원본과 같음), (10) 하단 `product`도 같은 방식으로 아래 가장자리 행이 어둡고 좌우 경계 계단이 없다, (11) 막 확장 영역 **밖**(세로 25~75% 중앙)은 원본과 같다(기존 `preserves_entire_center` 유지), (12) `contrast_adjusted`·`min_contrast`가 이전과 같은 필드·의미로 기록되고 `min_contrast >= MIN_CONTRAST_RATIO`(막이 닿을 수 있는 입력에서)·값이 **최종 중간 이미지에서 독립적으로 재측정한 값과 같다**, (13) 같은 입력은 같은 PNG 바이트(결정성), (14) `SCRIM_MAX_ALPHA`·`SCRIM_STEP`·`MIN_CONTRAST_RATIO` 상수 값이 불변.
- 모델이 만든 문장·그림을 기대값으로 굳히지 않는다(합성 문자열과 합성 픽셀만).

## Acceptance Criteria

```bash
make verify   # lint + pytest + pnpm lint·typecheck·test 통과
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - AGENTS.md CRITICAL 규칙을 위반하지 않았는가?
3. 결과를 최종 응답(JSON)으로 보고한다. `phases/` 아래 파일은 수정하지 않고 git commit도 하지 않는다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약(설치한 패키지 버전 포함, 승인 목록에서 조정한 것은 이유까지)"`
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

- `agents/planning.py`·`agents/evaluation.py`·`agents/supervisor.py`(프롬프트·동결 줄·해시·`image_brief` 규칙)와 `docs/results/`·`docs/EVAL.md`의 동결 기준·`tests/test_prereg.py`·`tests/test_freeze_guard.py`를 수정하지 마라. 이유: 동결 값은 결과를 본 뒤 바꾸지 않는다(AGENTS.md CRITICAL). 이미지 프롬프트 보완은 동결 줄이 아닌 `design_images.py`의 새 상수로만 한다.
- `IMAGE_NO_TEXT_CLAUSE`의 값, 장면 정리 로직(괄호·주석·따옴표·URL 제거), 2000자 한도, "글자·로고·브랜드·제품명·라벨 금지" 지시를 바꾸거나 약화하지 마라. 이유: 이미지에 글자가 찍히는 문제를 이미 고친 규칙이다(PROMPT_CHANGELOG 9e·9g·9h). 새 문구는 그 앞에 더하기만 한다.
- `MIN_CONTRAST_RATIO`·`SCRIM_MAX_ALPHA`·`SCRIM_STEP`·`MARGIN_RATIO` 등 합성 상수 값과 `contrast_adjusted`·`min_contrast`의 기록 규칙을 바꾸지 마라. 막의 region 안 기울기 모양을 바꾸지 마라. 이유: 대비 보정 규칙은 승인된 값이고(P5 결정 57), 기존 막 재구성 테스트가 region 안 모양을 단언한다.
- 기존 테스트 단언을 약화·삭제하지 마라(위 "기존 단언과의 충돌 점검"의 정확 일치 기대값 갱신과, 막 확장으로 달라지는 가장자리 픽셀 단언을 "중앙 보존 + 새 불변식"으로 옮기는 것만 허용). 이유: 가드를 약화하면 회귀를 못 잡는다.
- 이미지 모델을 호출하거나 `data/design/`의 파일을 읽지 마라. 이미지 품질 확인은 사용자가 화면에서 같은 요청을 여러 번 해서 한다. 이유: 실제 호출은 사용자가 실행하고(A-FP-040) 사람이 보는 산출물의 확인은 사람이 한다(B-FP-075).
