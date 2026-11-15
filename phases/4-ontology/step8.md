# Step 8: layer1-graph

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조, 온톨로지 절, 데이터 흐름
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P4 절과 변경 기록 #36
- `/docs/COMPETENCY_QUESTIONS.md` — v1(2026-11-15 동결), 홉 정의와 한계
- `/docs/ARCHITECTURE.md` — 1층 노드·관계 표(Brand, Product, Category, Form, Ingredient, IngredientAlias, Efficacy, SkinConcern, SkinType, FunctionalCert, ClaimRule)
- `/docs/ADR.md` — ADR-012(후속 결정 5~7 포함), ADR-014
- `/src/beautyads/graph/`, `/src/beautyads/domain/sync.py`, `/src/beautyads/pipeline/sync.py`, `/src/beautyads/store/sync_source.py`, `/src/beautyads/store/product_repository.py`, `/src/beautyads/domain/claims.py`, `/src/beautyads/domain/products.py`, `/src/beautyads/domain/skin.py` — step 0~7 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/graph/layer1.py`(새 파일), `src/beautyads/graph/schema.py`, `src/beautyads/domain/layer1.py`(새 파일), `src/beautyads/store/layer1_source.py`(새 파일), `src/beautyads/pipeline/sync.py`, `config/ingredient_efficacy.yaml`(새 파일), `config/efficacy_concerns.yaml`(새 파일), `README.md`, `tests/test_graph_layer1.py`, `tests/test_layer1_source.py`, `tests/test_sync_pipeline.py`, `tests/test_graph_schema.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/graph/layer1.py`, `src/beautyads/graph/schema.py`(제약 추가에 한함, 기존 제약·테스트 단언 불변), `src/beautyads/domain/layer1.py`, `src/beautyads/store/layer1_source.py`, `src/beautyads/pipeline/sync.py`(`--layers` 옵션 추가에 한함, 기존 동작 불변), `config/ingredient_efficacy.yaml`, `config/efficacy_concerns.yaml`, `README.md`(sync 절 추가에 한함), `tests/test_graph_layer1.py`, `tests/test_layer1_source.py`, `tests/test_sync_pipeline.py`(케이스 추가에 한함, 단언 약화 금지), `tests/test_graph_schema.py`(케이스 추가에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

1층(제품 지식)을 PostgreSQL에서 Neo4j로 증분 MERGE로 적재한다(step 0과 같은 동기화 틀, `--layers 1`). **이 step 안에서는 실제 접속·실행을 하지 않는다.**

**선행 조건**: `config/ingredient_efficacy.yaml`(성분→효능 수기 표)이 아래 "확정된 표" 절에 승인본으로 붙어 있어야 한다. 이 표는 step 7 live 뒤 성분 빈도 보고를 받아 조언 세션이 상위 약 20개에 출처를 붙여 만든다. 절이 비어 있으면 `blocked`(reason에 "성분→효능 수기 표가 없다").

- **노드**: `Brand`, `Product`(이름, 영문명, 별칭, 용량·단위, 정가·판매가·`price_basis`, 단위당 정가, 가격 수집 시각, 출처 주소), `Category`(`mask_pack`·`serum_ampoule`·`sun_care`, 고정 목록), `Form`, `Ingredient`(표준명, 영문명, CAS), `IngredientAlias`, `Efficacy`(`domain.labels.Claim`의 값, `other` 제외 — 분류의 소구점 값과 같은 목록), `SkinConcern`·`SkinType`(`domain/skin.py`의 목록), `FunctionalCert`, `ClaimRule`(step 1 규칙).
- **관계**: `OWNS`, `IN_CATEGORY`, `HAS_FORM`, `CONTAINS`(표기 순서, 핵심 성분 여부, 출처), `ALIAS_OF`, `HAS_EFFICACY`, `ADDRESSES`, `SUITS`, `CERTIFIED_AS`, `APPLIES_TO`. **`미해결` 성분은 `Ingredient` 노드로 올리지 않는다**(`CONTAINS`는 표준명에 묶인 성분만, 미해결은 PostgreSQL에만 남는다). **제품의 성분 관계(`CONTAINS`)는 집합 교체(삭제 반영)로 적재한다**: 한 제품의 `CONTAINS`는 PostgreSQL의 그 제품 성분 집합과 정확히 같아야 하므로, 적재할 때 PostgreSQL에 더 이상 없는 관계(순서가 줄어 사라진 행, 표준명이 바뀐 행)를 그래프에서 삭제한다. 삭제된 행은 변경 시각으로 보이지 않으므로, 변경이 감지된 제품은 그 제품의 `CONTAINS` 전체를 다시 계산해 교체한다(MERGE 후 집합에 없는 관계 삭제). 이유: 재파싱이 짧아져 이전 행이 남는 결함이 P4에서 실제로 있었다(FP-C09).
- **`HAS_EFFICACY`의 출처(ADR-012 후속 결정)**: (a) 식약처 기능성 고시 성분(미백·주름 개선·자외선 차단), (b) 그 밖의 효능(진정·보습 등)은 `config/ingredient_efficacy.yaml`의 소규모 수기 표(**각 행에 출처 문헌·데이터베이스 필수**). 출처가 없는 행은 로더가 `INGREDIENT_EFFICACY_INVALID`로 거부하고 **관계를 만들지 않는다**. 관계 속성에 `source`를 둔다.
- **`ADDRESSES`(Efficacy→SkinConcern)**: `config/efficacy_concerns.yaml`에 ADR-012 후속 결정 6의 대응 초안이 들어 있다. **출처가 없는 초안이므로 행마다 `status`(`draft`·`confirmed`)와 `source`를 둔다. `status == confirmed`이고 `source`가 비어 있지 않은 행만 관계로 올리고, `draft` 행은 올리지 않으며 건수를 `draft_not_loaded`로 요약에 출력한다**(사용자 확인 또는 출처 부여 전에는 그래프에 없다). `SkinConcern`·`SkinType` 노드는 올린다.
- **`CERTIFIED_AS`**: `product_certs.status == certified`인 것만 만든다. **`unknown`(보고품목 `SPF`·`PA` null 등)은 관계를 만들지 않고** 커버리지 수(`certified`·`unknown`·제품 수)를 요약에 출력한다("인증 없음"으로 만들지 않는다).
- **`APPLIES_TO`**: `ClaimRule`을 효능·피부 고민·카테고리에 붙인다. `applies_to`의 `status`가 `advisor_approved`·`confirmed`인 항목만 관계로 올리고 `draft` 항목은 올리지 않으며 건수를 `draft_not_loaded`로 센다(`claim_rules.yaml`의 `applies_to`는 조언 세션이 승인했다). 규칙은 개별 제품이 아니라 효능·카테고리에 붙는다.
- 변경 판정은 step 0과 같다(PostgreSQL 변경 시각 기준, 겹쳐 읽기, 적재 뒤 워터마크 갱신, 레이어별 워터마크 이름). 모든 문장은 `MERGE`와 파라미터이고 제약은 `IF NOT EXISTS`다.

## 확정된 표

(비어 있음 — step 7 live 뒤 조언 세션이 `ingredient_efficacy.yaml` 본문(출처 필수)을 승인하면 여기에 붙인다. `efficacy_concerns.yaml`은 ADR-012 후속 결정 6의 초안 10행을 `status: draft`로 두고 시작한다.)

### 반드시 있어야 하는 테스트

- 적재 문장: `CREATE` 없음·`MERGE`·파라미터만, 같은 입력을 두 번 넣으면 문장·파라미터가 같다, 제약이 `IF NOT EXISTS`이고 기존 제약이 불변이다.
- `HAS_EFFICACY`: 출처가 없는 합성 행은 거부되고 관계가 만들어지지 않는다, 출처가 있는 행은 `source` 속성을 가진다, 표에 없는 성분·효능은 관계가 없다("근거 연결 없음"을 다른 값으로 채우지 않는다), `Efficacy` 값이 `Claim`의 닫힌 목록 밖이면 거부된다.
- `ADDRESSES`: `draft` 행은 올라가지 않고 `draft_not_loaded`로 센다, `confirmed`이면서 출처가 있는 행만 올라간다, `confirmed`인데 출처가 비어 있으면 `EFFICACY_CONCERN_INVALID`, 값이 `Claim`·`SkinConcern` 밖이면 거부된다.
- 한 제품의 성분 행 수가 줄어든 뒤 다시 적재하면 사라진 순서의 `CONTAINS`가 그래프에서도 삭제된다(제품당 `CONTAINS` 수가 PostgreSQL의 성분 수와 같다)
- `미해결` 성분이 `Ingredient` 노드·`CONTAINS`로 올라가지 않는다, 별칭이 표준명에 `ALIAS_OF`로 이어진다.
- `CERTIFIED_AS`: `unknown`은 관계가 없고 커버리지 수에 센다, `certified`만 관계가 된다.
- 증분: 워터마크보다 오래된 제품은 읽지 않는다, 적재 실패 시 워터마크가 오르지 않는다, 그래프 카운터를 판정에 쓰지 않는다.
- 실제 `config/ingredient_efficacy.yaml`·`efficacy_concerns.yaml`을 읽는 테스트 1개: 로더가 통과하고 모든 `confirmed` 행에 `source`가 비어 있지 않다(**행의 개수나 내용을 단언하지 않는다**).
- `tests/test_architecture.py`가 통과한다(`graph`는 `store`를 import하지 않는다, `neo4j`는 `graph`만).

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

- `make sync`를 실행하지 마라. 이유: 실제 Neo4j 접속은 사용자가 한다.
- 출처가 없는 성분→효능 연결을 만들거나 모델이 만든 연결을 쓰지 마라. 이유: ADR-012("출처 없는 연결은 만들지 않는다").
- `draft` 대응(`ADDRESSES`·`APPLIES_TO`)을 그래프에 올리지 마라. 이유: 출처 없는 초안이다(ADR-012 후속 결정 6). `advisor_approved`·`confirmed`만 올린다.
- `unknown`을 "인증 없음"으로 올리지 마라. 이유: 식약처 `SPF`·`PA`가 대부분 null이다(계약).
- `미해결` 성분을 `Ingredient`로 올리지 마라. 이유: 표준명에 묶인 것만 그래프에 둔다(ARCHITECTURE).
- 표 내용("확정된 표" 절)을 지어내지 마라. 이유: 출처가 있어야 하는 사실 관계다. 절이 비어 있으면 `blocked`.
- 규칙을 개별 제품에 붙이지 마라. 이유: 규칙 상속(ARCHITECTURE).
- 기존 `Protocol`·`graph/load.py`(step 0)의 동작을 바꾸지 마라. 이유: step 0 테스트가 계약이다.
