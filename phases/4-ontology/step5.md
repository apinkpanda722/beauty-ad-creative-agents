# Step 5: store-products

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조, 온톨로지 절, 데이터 흐름
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P4 절과 변경 기록 #36
- `/docs/COMPETENCY_QUESTIONS.md` — v1(2026-11-15 동결), 홉 정의와 한계
- `/docs/ARCHITECTURE.md` — 1층 노드·관계 표, 1층 구축 파이프라인(제품 하나가 레코드 하나)
- `/docs/ADR.md` — ADR-013
- `/src/beautyads/store/schema.py`, `/src/beautyads/store/repository.py`, `/src/beautyads/store/connection.py`, `/tests/test_store.py` — 마이그레이션 방식, 변경 시각, 연결 Protocol(**기존 동작을 바꾸지 않는다**)
- `/src/beautyads/domain/mfds.py`, `/src/beautyads/domain/mall.py`, `/src/beautyads/domain/labels.py`, `/src/beautyads/domain/skin.py` — step 1~3 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/products.py`(새 파일), `src/beautyads/store/schema.py`, `src/beautyads/store/product_repository.py`(새 파일), `tests/test_products_domain.py`(새 파일), `tests/test_product_store.py`(새 파일), `tests/test_store.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/products.py`, `src/beautyads/store/schema.py`(`MIGRATIONS`에 v4 추가에 한함, 기존 마이그레이션·`CHANGE_COLUMNS` 불변), `src/beautyads/store/product_repository.py`, `tests/test_products_domain.py`, `tests/test_product_store.py`, `tests/test_store.py`(마이그레이션 v4 케이스 추가에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

제품 레코드의 타입과 PostgreSQL 저장을 만든다(PostgreSQL이 원본, 그래프는 파생물). **이 step 안에서는 실제 DB에 접속하지 않는다.**

- **`domain/products.py`**(pydantic·표준 라이브러리만): `Product`(`brand`, `source_url`(정규화), `category`(`Category`에서 `other`를 뺀 값), `name_ko`, `name_en`(없을 수 있음), `aliases`(줄임말 별칭 목록 — **`derive_aliases(name_ko)`가 기계적으로 만든다**, 사용자가 채우지 않는다. `PROMOTES`가 쓴다), 용량 값·단위, 정가·판매가·`price_basis`, 가격 수집 시각, 제형, `skin_types`(`SkinType` 목록), 효능 문구·기능성 표기 원문 목록), `ProductIngredient`(제품, 순서, 원문, 표준명(없으면 `None`), 상태 `resolved`·`unresolved`), `ProductCert`(제품, 기능성 종류, 상태 `certified`·`unknown`, 근거 품목명, 근거 API), `ProductExtraction`(제품, 프롬프트 버전, 모델 출력 원문), 그리고 이 저장소를 읽고 쓰는 **새 Protocol `ProductRepository`**(기존 Protocol은 건드리지 않는다).
- **`derive_aliases(name_ko: str) -> list[str]`(순수 함수, 같은 입력은 같은 결과)**: 제품명에서 **용량·용기 표기를 떼고** 핵심 성분·제형 조합을 기계적으로 만든다. 규칙: (1) 토큰화(공백 기준, NFKC·소문자). (2) 제거: 용량 토큰(`\d+(\.\d+)?(ml|g|매|입|ea)`, `\d+\+\d+`), 용기 단어(`튜브`·`펌프`·`캡`·`리필`·`용기`·`파우치`·`데일리`·`픽`, 상수 `CONTAINER_WORDS`), SPF·PA 표기(`spf\d+\+?`·`pa\+*`). (3) 남은 토큰을 이은 것이 별칭 1이다. (4) 불용어(`STOPWORDS` 상수: 더·the·new·리뉴얼·어드밴스드·플러스·하이퍼·마일드·워터리·릴리프 등)를 더 뺀 것이 별칭 2다. (5) 제형 단어(`FORM_WORDS` 상수: 세럼·앰플·마스크·시트·팩·선크림·선세럼·선스틱·에센스·크림·젤·로션)가 있으면 **불용어를 뺀 첫 토큰 + 마지막 제형 단어**가 별칭 3이다(핵심 성분·제형 조합). (6) 중복을 지우고, 정규화한 길이가 3자 미만이거나 제형 단어 하나뿐이거나 브랜드 이름뿐인 것은 버린다. 영문명은 번역하지 않는다(제품명에 영문 토큰이 있으면 그대로 남는다).
- **마이그레이션 v4**(추가형, 두 번 실행해도 같다, `IF NOT EXISTS`): `products`(PK `(brand, source_url)`, 위 필드, `aliases` jsonb, `skin_types` jsonb, `updated_at`), `product_prices`(제품, 수집 시각, 정가, 판매가, `price_basis` — 가격 이력은 PostgreSQL에만 쌓는다), `product_ingredients`, `ingredient_standards`(표준명 캐시: 표준명, 영문명, CAS, 조회 시각), `product_certs`, `product_extractions`(모델 출력 원문과 프롬프트 버전 보존). 변경 시각 컬럼은 `products`·`product_ingredients`·`product_certs`에 있고, **값이 바뀐 때만 올린다**(소재 표와 같은 방식: `IS DISTINCT FROM` 비교).
- **`store/product_repository.py`**: `ProductRepository`의 구현(upsert, 이력 추가, 조회, 표준명 캐시 읽기·쓰기, 변경된 행 읽기(`updated_at` 기준, step 8의 증분 동기화가 쓴다)). 연결은 `SqlConnection` Protocol 뒤에서만 쓴다. 소재 표(`creatives`)·`analysis_jobs`·`CHANGE_COLUMNS`는 건드리지 않는다.

### 반드시 있어야 하는 테스트

(가짜 연결로만 테스트한다. 실제 DB 접속 금지.)
- 마이그레이션: v4가 두 번 실행해도 같은 문장 목록이고 기존 v1~v3 문장·`CHANGE_COLUMNS`가 불변이다, 모든 문장이 추가형(`IF NOT EXISTS`·`ADD COLUMN IF NOT EXISTS`)이다.
- 저장: 같은 입력을 두 번 upsert하면 `updated_at`이 두 번째에 오르지 않는다(변경 비교 문장 텍스트 검사 + 가짜 연결 호출 기록), 값이 바뀌면 오른다, 가격 이력이 쌓인다(같은 제품의 두 수집이 두 행), `aliases`·`skin_types`가 JSON 배열로 왕복된다, `미해결` 성분(`status=unresolved`, 표준명 `None`)이 원문과 함께 보존된다.
- `derive_aliases`: 합성 제품명에서 용량·용기·SPF 표기가 빠진다, 별칭 1~3이 규칙대로 나온다, 같은 입력은 같은 결과, 3자 미만·제형 단어뿐인 별칭은 버려진다, 제품명이 비어 있으면 빈 목록이다(실제 제품명을 기대값으로 굳히지 않고 합성 이름으로만 검사한다).
- 타입: `Product`의 `category`가 `other`를 거부한다, `aliases`가 비어 있어도 유효하다, `SkinType` 밖의 값이 거부된다, `price_basis`가 `list_price`·`sale_price_fallback` 밖이면 거부된다.
- 읽기: 변경된 행 읽기가 `updated_at > 기준`으로만 판정하고 그래프 카운터에 의존하지 않는다, 빈 결과는 오류가 아니다.
- 기존 `tests/test_store.py`가 그대로 통과하고 `tests/test_architecture.py`가 통과한다(`domain`은 pydantic·표준 라이브러리만).

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

- 실제 PostgreSQL에 접속하지 마라. 이유: 실제 DB는 사용자가 띄운 환경이고 SQL은 가짜로만 통과할 수 있다(첫 live에서 결함이 드러난다).
- 기존 마이그레이션 v1~v3·`creatives`·`analysis_jobs`·`CHANGE_COLUMNS`를 바꾸지 마라. 이유: 소재 분석 전체가 그 위에 있다.
- 기존 `CreativeRepository`·`AnalysisRepository` Protocol에 메서드를 추가하지 마라. 이유: 가짜 구현이 깨진다.
- 제품 레코드를 조각내지 마라(제품 하나가 레코드 하나). 이유: 성분 정보와 제품명이 갈라진다(ARCHITECTURE).
- 가격을 덮어써서 이력을 잃지 마라. 이유: 가격 이력은 PostgreSQL에 두고 그래프에는 최신 값만 올린다(ARCHITECTURE).
- 모델 출력 원문을 버리지 마라. 이유: 원문 보존이 규칙이다(ARCHITECTURE).
