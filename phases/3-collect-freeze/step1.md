# Step 1: taxonomy-partial

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — "P3 collect-freeze"의 `taxonomy-partial` 행과 변경 기록 #32
- `/docs/TAXONOMY.md` — §0 `content_type`, §10 `category`
- `/src/beautyads/domain/labels.py` — `ContentType`, `Category`
- `/src/beautyads/eval/sheets.py` — `parse_taxonomy`(표 첫 열의 백틱 값과 정의를 읽는 방식)
- `/tests/test_pilot_sheet.py`, `/tests/test_domain.py` — 이 step이 깨면 안 되는 기존 테스트
- `/docs/ADR.md` — 마지막 ADR의 형식

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `docs/TAXONOMY.md`, `docs/ADR.md`, `tests/test_taxonomy_freeze.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `docs/TAXONOMY.md`(§0 `content_type`과 §10 `category` 절에 한함), `docs/ADR.md`(새 ADR 하나를 끝에 추가하는 것에 한함), `tests/test_taxonomy_freeze.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

> **이 step은 사용자 승인(2026-11-13) 뒤에만 실행한다.** 아래 `## 확정된 정의` 절에 승인된 문구가 붙어 있다. 비어 있으면 코드를 쓰지 않고 `blocked`로 보고한다. reason에 "확정된 정의 절이 비어 있음"을 적는다.

E1 1단계 라벨링(사람이 `content_type`과 `category`를 함께 라벨링) 전에 **두 축의 정의만 부분 동결**한다. 나머지 축(`hook_type`·`angle`·`format`·`talent`·구조·플랫폼 적합성·`cta_type`·`claims`)은 전체 v1(step 5)까지 바뀔 수 있으므로 건드리지 않는다.

0. **`docs/TAXONOMY.md` §0 `content_type`의 표를 `## 확정된 정의`의 표로 바꾸고**(값 목록은 그대로) 표 아래에 판정 순서 줄과 §10에는 category 규칙 줄을 그대로 넣는다.
1. **`docs/TAXONOMY.md` §10 `category`를 표로 바꾼다.** 지금은 값만 나열한 한 줄이라 `eval.sheets.parse_taxonomy`가 정의를 읽지 못한다. §0과 같은 형식(`| 값 | 판정 기준 |`, 첫 열은 백틱 값)으로 `## 확정된 정의`의 문구를 옮긴다. 값 목록은 `domain/labels.py`의 `Category`와 같아야 한다(값을 늘리거나 줄이는 것은 승인본이 그렇게 말할 때만, 그 경우 이 step의 수정 허용 경로에 `src/beautyads/domain/labels.py`가 없으므로 `blocked`로 보고한다).
2. §0·§10 제목 바로 아래에 `> 부분 동결(2026-11-13): 이 절의 값과 정의는 E1 1단계 라벨링 전에 고정했고 v1 동결 전까지 바꾸지 않는다.` 한 줄을 넣는다.
3. **`docs/ADR.md` 끝에 ADR 하나를 추가한다**(번호는 마지막 ADR 다음, 형식은 기존과 같다): `## 확정된 정의`의 "ADR에 적을 내용" 네 항목(결정·이유·근거·트레이드오프, 날짜 2026-11-13)을 그대로 쓴다.
4. **`tests/test_taxonomy_freeze.py`**: 값 목록은 테스트가 정하지 않고 문서가 정한다. `eval.sheets.parse_taxonomy(TAXONOMY_PATH 내용)`로 `content_type`과 `category` 절의 값을 읽어 (a) `set(ContentType)`·`set(Category)`의 값 집합과 같고, (b) 값마다 비어 있지 않은 정의가 있고, (c) 두 절 모두 `other`를 가지며, (d) 두 절 제목 아래에 부분 동결 줄이 있음을 검사한다. 합성 문서로 파서 동작(값이 하나 빠진 문서는 실패)도 검사한다.

## 확정된 정의

사용자가 2026-11-13에 승인한 정의다(조언 세션 초안 `TAXONOMY_PARTIAL_FREEZE_DRAFT`을 그대로 옮김). 값 목록은 `domain`의 enum과 같고 **정의만 고정**한다. 아래 표의 값 순서는 문서 표 순서이며 enum 순서와 달라도 된다(테스트는 집합으로 비교한다). `docs/TAXONOMY.md` §0·§10에 표와 판정 순서·category 규칙을 그대로 옮긴다(§0 판정 순서 줄과 §10 규칙 줄에는 값 뒤에 괄호 설명을 붙이지 않는다 — 코드북 파서가 값 뒤 괄호를 정의로 읽는다).

### `content_type` 정의 (확정) (하나 선택, 다른 축보다 먼저 판정)

| 값 | 판정 기준 |
|---|---|
| `event_place` | 매장·팝업·플래그십 스토어·행사·협업 공간 안내가 중심이다. 영상에 제품이 나오거나 모델이 제품을 써 보는 장면이 있어도 중심이 장소·행사면 이 값이다. 가장 먼저 확인한다 |
| `product_creative` | 특정 제품 또는 제품 세트가 광고 대상이고, 그 제품이 영상에 **한 번이라도** 나온다(알아보기 어려울 만큼 스치듯 나와도 같다). 제목·캡션이 그 제품이나 세트를 광고 대상으로 적고 있어야 한다 |
| `brand_campaign` | 영상에 제품이 한 번도 나오지 않거나, 제품이 나와도 제목·캡션이 브랜드 이름·캠페인·협업만 적고 특정 제품을 광고 대상으로 적지 않는다 |
| `other` | 공지, 채용, 일상 등 위 어느 것도 아니다 |

판정 순서: `event_place` 확인 → 특정 제품을 제목·캡션이 광고 대상으로 적고 영상에 제품이 나오는가(`product_creative`) → 아니면 `brand_campaign` → 그 밖은 `other`.

### `category` 정의 (확정) (하나 선택. `content_type`이 `product_creative`가 아니면 `other`)

| 값 | 판정 기준 |
|---|---|
| `mask_pack` | 마스크팩(시트 마스크, 워시오프 팩, 슬리핑 팩)이 광고 대상이다 |
| `serum_ampoule` | 세럼, 앰플, 에센스(기능성 성분을 농축한 액상 제품)가 광고 대상이다. 에센스는 이 값에 포함한다 |
| `sun_care` | 자외선 차단 제품이 광고 대상이다(선크림, 선스틱, 선파우더, 선세럼 등 SPF·PA 표기가 있는 제품). 선세럼처럼 두 값에 걸치면 `sun_care`가 우선한다 |
| `other` | 위에 해당하지 않는 모든 제품이다: 클렌저, 토너·토너패드, 크림·아이크림, 오일, 뷰티 디바이스, 여러 라인이 섞인 세트 등. 지배적인 한 제품이 없는 세트도 `other`다 |

`category`가 `other`인 소재는 수집은 하되 전체 축 분석(`hook`·`full`)에서 뺀다.

### ADR에 적을 내용 (step 1이 쓴다)
- 결정: `content_type`·`category` 두 축의 값과 정의를 2026-11-13에 부분 동결한다.
- 이유: E1 1단계 라벨링(사람이 두 축을 함께 라벨링) 중에 정의가 바뀌면 사람 라벨의 기준이 달라진다.
- 근거: 시범 20건 사람 라벨링과 라벨 점검(2026-11-13). `content_type`의 `product_creative`와 `brand_campaign` 경계 규칙은 라벨링 중 정했고, 시범 비교 결과 일부를 본 뒤 라벨 점검에 반영했다(결과 문서에 한계로 기록).
- 트레이드오프: 나머지 축(`hook_type`·`angle`·`format`·`talent`·구조·플랫폼 적합성·`cta_type`·`claims`)은 전체 v1(2026-11-19)까지 바뀔 수 있다.


### 반드시 있어야 하는 테스트

- 문서의 `content_type`·`category` 값 집합이 `domain`의 enum 값 집합과 같다(문서에서 값을 하나 지운 합성 텍스트로는 실패한다).
- 값마다 정의가 비어 있지 않다(빈 정의 합성 텍스트로는 실패한다).
- 두 절에 부분 동결 줄이 있다.
- 값 목록·정의 문구를 테스트 코드에 문자열 리터럴로 굳히지 않는다(문서와 enum에서 읽는다).
- 기존 테스트가 모두 통과한다. 특히 `tests/test_pilot_sheet.py`의 코드북 테스트와 `tests/test_domain.py`는 이 step이 §10을 표로 바꿔도 깨지지 않아야 한다(깨지면 고치지 말고 `blocked`로 보고한다).

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

- `content_type`·`category` 밖의 축 절을 고치지 마라. 이유: 나머지 축은 시범 라벨링 결과와 미확정 쟁점(`has_hook_segment`, `has_cta`, `claims`)을 본 뒤 step 5에서 한꺼번에 동결한다.
- `domain/labels.py`의 enum 값이나 `PROMPT_VERSIONS`를 바꾸지 마라. 이유: 값 변경은 프롬프트·시트·코드북이 함께 바뀌어야 해서 이 step의 범위가 아니다.
- 테스트에 값 목록이나 정의 문구를 하드코딩하지 마라. 이유: 문서와 코드가 어긋났을 때 테스트가 그 사실을 알려야 하는데 테스트가 값을 굳히면 둘이 같이 틀려도 통과한다(FP-C03).
- `docs/results/`의 사전 등록 파일을 만들거나 고치지 마라. 이유: 사전 등록은 구현 세션이 별도로 커밋한다(읽기 전용).
