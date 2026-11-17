# Step 3: mall-source

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조, 온톨로지 절, 데이터 흐름
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P4 절과 변경 기록 #36
- `/docs/COMPETENCY_QUESTIONS.md` — v1(2026-11-15 동결), 홉 정의와 한계
- `/docs/CONTRACTS.md` — 브랜드 공식몰 상세페이지 절 전체와 **"공식몰 재실측 (2026-11-15)"**(전성분 구조 차이, 고도몰, 단종 404, robots.txt)
- `/docs/ADR.md` — ADR-013
- `/tests/fixtures/contracts/mall_*.html`, `/tests/fixtures/contracts/mall_robots_*.txt` — **픽스처는 이 파일들에서만 만든다**(2026-11-15 저장, 필요한 부분만 남긴 최소본)
- `/config/product_candidates.yaml`, `/config/sources.yaml` — 대표 단품 후보(임시), 브랜드 목록
- `/src/beautyads/sources/youtube.py`, `/src/beautyads/sources/media.py` — 어댑터 구조, 다운로드 방식

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/sources/mall.py`(새 파일), `src/beautyads/domain/mall.py`(새 파일), `config/malls.yaml`(새 파일), `tests/test_mall.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/sources/mall.py`, `src/beautyads/domain/mall.py`, `config/malls.yaml`, `tests/test_mall.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

브랜드 공식몰 상세페이지에서 **가격과 전성분 텍스트, 상세 이미지 주소**를 읽는 어댑터다. 이미지를 모델로 읽는 일은 `analysis`(step 6)가 한다 — `sources`는 `llm`을 import하지 못한다. **이 step 안에서는 실제 페이지를 요청하지 않는다.** 응답 원본은 이미 저장돼 있다(공식몰 재실측 2026-11-15). 원본이 없으면 `blocked`다.

- **robots.txt와 간격**: 요청 전에 호스트의 robots.txt를 읽는다(표준 라이브러리 `urllib.robotparser`로 파싱, 요청은 `httpx`). 해당 경로가 막혀 있으면 요청하지 않고 `MALL_ROBOTS_DISALLOWED`를 돌려준다. `Crawl-delay`가 있으면 그 값을(달바 10초, 달바 robots에는 `*` 그룹이 없고 이름 지정 봇에만 있으나 우리는 10초를 지킨다), 없으면 `config/malls.yaml`의 기본 간격(기본 6초)을 호스트별 최소 간격으로 지킨다(대기 함수·시계 주입). **robots.txt가 CRLF 줄바꿈이어도 읽혀야 한다.** User-Agent는 일반 클라이언트 이름(개인 정보·이메일 금지)이고 `config/malls.yaml`에서 읽는다. 이용약관은 영리 목적 복제·배포 금지 조항만 있다(ADR-013): **사실 정보(가격·전성분·효능 표기)만 읽고 이미지는 저장·재배포하지 않는다.**
- **제외 몰**: `config/malls.yaml`에 `excluded: true`인 몰(토리든: AI 크롤러 차단, 넘버즈인: 접근 401)은 요청하지 않고 `MALL_EXCLUDED`를 돌려준다. 이 두 브랜드는 제품 정보를 받지 못해 `PROMOTES` 커버리지에서 빠진다(`docs/ARCHITECTURE.md`).
- **가격**: 카페24는 메타 태그 `product:price:amount`(정가), `product:sale_price:amount`(판매가), `product:price:currency`. 메타가 없는 고도몰은 JSON-LD `offers.price`(문자열 `"29900.00"`)·hidden input `set_goods_price`·`set_goods_fixedPrice`에서 읽는다. **정가가 없거나 `0.00`이면 판매가를 쓰고 `price_basis`(`list_price`·`sale_price_fallback`)에 어느 쪽인지 남긴다.** 정가와 판매가가 같은 상품도 있다. **가격은 이미지에서 뽑지 않는다.**
- **단종·실패 판정**: HTTP 상태를 먼저 본다. **404는 단종 후보(`MALL_PRODUCT_GONE`)로, 200이어도 가격 메타(또는 JSON-LD 가격)가 없으면 `MALL_PRODUCT_GONE`이다**(단종 표현이 두 형태로 관측됐다, 2026-11-12 HTTP 200·2026-11-15 HTTP 404). 그 밖의 비200은 `MALL_HTTP_<상태>`(일시 오류와 단종을 같은 코드로 합치지 않는다, 5xx·연결 실패는 재시도 대상이다 — FP-C05). 응답은 gzip일 수 있으니 클라이언트가 풀게 한다. 한글이 든 주소는 퍼센트 인코딩해 요청한다(이미 인코딩된 주소를 이중 인코딩하지 않는다).
- **전성분 텍스트 우선, 판정은 "값 칸이 비어 있지 않은가"**: 라벨("화장품법에 따라 기재해야 하는 모든 성분"·"모든 성분"·"전성분")이 HTML에 **있다는 것만으로 텍스트가 있다고 판정하지 않는다**(이즈앤트리는 행이 있지만 `<td>`가 비어 있다). 두 구조를 읽는다: (1) `<table>`의 `th`(라벨)와 `td`(값), (2) `div.info-row` 안 `div.info-label`(라벨)과 `div.info-content`(값, 아누아는 `ingredients` 클래스). 값이 비어 있지 않을 때만 `ingredients_text`를 돌려주고 비어 있으면 `None`이다. `None`이면 상세 이미지 주소 목록(`id="prdDetail"` 안 `img`의 `ec-data-src`, 페이지 순서 보존, 상대 경로는 절대 주소로)을 돌려준다. 표준 라이브러리 `html.parser`만 쓴다.
- **이미지 내려받기 함수(`download_detail_image`)**: 메모리 바이트로만 돌려주고 **디스크에 쓰지 않는다**, 최대 크기(`max_bytes`, 필수 인자)를 넘으면 `MALL_IMAGE_TOO_LARGE`, timeout 있음. 이 함수는 step 7의 실행기가 부른다.
- 세트 상품("1+1" 등)은 어댑터가 판정하지 않는다(대표 단품 선정은 사용자 확인).

### 반드시 있어야 하는 테스트

(가짜 `get`은 `tests/fixtures/contracts/mall_*` 원본에서 만든 본문이다.)
- 가격: `mall_cafe24_*` 원본에서 정가·판매가·통화가 읽힌다(값의 형식과 정가 ≥ 판매가 같은 불변식만 단언하고 실제 금액을 굳히지 않는다), `mall_godomall_product.html`에서 JSON-LD 문자열 가격이 숫자로 바뀌고 정가가 `0.00`이면 `price_basis=sale_price_fallback`, 이미지에서 가격을 뽑는 경로가 없다.
- 전성분: `mall_cafe24_text_div.html`(div 구조)에서 `ingredients_text`가 나온다(비어 있지 않음만 단언), **`mall_cafe24_table_empty.html`(라벨은 있고 값 칸이 비어 있음)은 `None`이다**, 이미지뿐인 `mall_cafe24_image_only.html`은 `None`과 이미지 주소 목록(페이지 순서 보존), 고도몰 원본은 `None`, 이미지 주소가 상대 경로여도 절대 주소가 된다.
- 단종: `mall_discontinued_404.html`을 404로 돌려주면 `MALL_PRODUCT_GONE`, 같은 본문을 200으로 돌려줘도 가격이 없으면 `MALL_PRODUCT_GONE`, 500은 `MALL_HTTP_500`(재시도 대상으로 표시되고 단종으로 확정하지 않는다), 연결 실패는 재시도 대상이다.
- robots: `mall_robots_mixsoon.txt`는 상품 경로를 막지 않고 `/admin/`·`/order/` 등은 막는다(요청 없이 `MALL_ROBOTS_DISALLOWED`), `mall_robots_dalba.txt`(CRLF)에서 `Crawl-delay: 10`이 읽히고 같은 호스트 두 요청 사이에 대기 함수가 10초 이상으로 불린다, 호스트가 다르면 간격이 독립이다, robots.txt를 못 읽으면(5xx·연결 실패) 요청하지 않고 `MALL_ROBOTS_UNREADABLE`. 막힌 경로는 요청이 **한 번도** 나가지 않는다.
- 제외 몰: `excluded: true`는 요청 없이 `MALL_EXCLUDED`.
- 이미지 내려받기: 최대 크기 초과→`MALL_IMAGE_TOO_LARGE`, 파일을 쓰지 않는다(`tmp_path`에 새 파일이 없음), gzip 본문·한글 주소가 처리된다.
- 비밀·개인 정보: User-Agent에 이메일·이름이 없다(감시 값 주입).

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

- 실제 공식몰을 요청하거나 이미지를 내려받지 마라. 테스트는 가짜 `get`·저장된 원본만 쓴다. 이유: 실제 호출·다운로드는 사용자가 실행하고 robots.txt·간격 의무가 있다.
- 이미지를 디스크에 저장하거나 재배포하지 마라. 이유: 이용약관(영리 목적 복제·배포 금지)과 AGENTS.md CRITICAL(공식몰 이미지는 저장·재배포하지 않는다).
- 라벨 키워드의 존재로 텍스트 전성분이 있다고 판정하지 마라. 이유: 이즈앤트리는 라벨 행이 있지만 값이 비어 있다(2026-11-15 실측).
- 단종을 HTTP 200이라고 가정하거나 404를 일시 오류로 읽지 마라. 이유: 같은 단종 상품이 날짜에 따라 200·404로 관측됐다.
- `robots.txt`를 무시하거나 `Crawl-delay`를 줄이지 마라(달바 10초). 이유: AGENTS.md CRITICAL.
- 가격을 이미지에서 추출하지 마라. 이유: 행사 문구가 뽑혔다(계약).
- 몰 구조를 추측해 `<table>`만 읽는 코드를 쓰지 마라. 이유: 아누아는 `div.info-row` 구조다.
- `sources`에서 `llm`·`analysis`를 import하지 마라. 이유: 계층 경계(`httpx`는 `sources`만, 모델 호출은 `llm`만).
- 토리든·넘버즈인을 요청하지 마라. 이유: 제외 확정(ADR-013).
