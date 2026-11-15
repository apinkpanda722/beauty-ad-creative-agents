# Step 9: layer2-links

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조, 온톨로지 절, 데이터 흐름
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P4 절과 변경 기록 #36
- `/docs/COMPETENCY_QUESTIONS.md` — v1(2026-11-15 동결), 홉 정의와 한계
- `/docs/ARCHITECTURE.md` — 2층 관계 표와 **"`PROMOTES` 판정 규칙(2026-11-15 승인)"·"`PROMOTES` 한계"**
- `/docs/TAXONOMY.md` — `claims` 축(값만 저장, 원문 문장은 저장하지 않는다), `ingredients` 원문
- `/config/brand_split.yaml`, `/src/beautyads/sources/split.py` — dev/test 브랜드 분할(규칙은 dev에서 다듬고 test에서 커버리지만 보고한다)
- `/src/beautyads/domain/labels.py`(`FullResult`에는 제품 식별 필드가 없다), `/src/beautyads/graph/`, `/src/beautyads/pipeline/sync.py`, `/src/beautyads/store/layer1_source.py`, `/src/beautyads/store/product_repository.py`, `/src/beautyads/domain/products.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/links.py`(새 파일), `src/beautyads/graph/layer2.py`(새 파일), `src/beautyads/store/links_source.py`(새 파일), `src/beautyads/pipeline/sync.py`, `README.md`, `tests/test_links_domain.py`, `tests/test_graph_layer2.py`, `tests/test_links_source.py`, `tests/test_sync_pipeline.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/links.py`, `src/beautyads/graph/layer2.py`, `src/beautyads/store/links_source.py`, `src/beautyads/pipeline/sync.py`(`--layers` 옵션에 2 추가에 한함, 기존 동작 불변), `README.md`(sync 절 추가에 한함), `tests/test_links_domain.py`, `tests/test_graph_layer2.py`, `tests/test_links_source.py`, `tests/test_sync_pipeline.py`(케이스 추가에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

2층(소재)을 1층에 잇는 관계 `PROMOTES`·`CLAIMS`·`MENTIONS`를 만든다(`--layers 2`). **이 step 안에서는 실제 접속·실행을 하지 않는다. 분석(모델 호출)을 다시 하지 않는다 — v1 라벨과 소재 제목·캡션만 쓴다.**

- **`PROMOTES`(소재→제품)의 판정 규칙(`domain/links.py`의 순수 함수 `match_product(creative, products)`, 2026-11-15 승인)**: v1 분석 결과(`FullResult`)에는 제품 식별 필드가 없으므로 판정 근거는 **소재의 제목·캡션 문자열과 같은 브랜드 제품의 이름·별칭**뿐이다. 정규화(NFKC·대소문자 무시·공백 제거) 뒤 **같은 브랜드 제품의 이름 전체(`name_ko`) 또는 그 제품의 영문명(`name_en`)·줄임말 별칭(`aliases`)이 제목·캡션에 들어 있으면** 후보다. 별칭이 너무 짧아 오연결을 낼 수 있으므로 정규화한 별칭의 길이가 `MIN_ALIAS_LEN`(상수, 기본 3자) 미만이면 쓰지 않는다. 후보 제품이 하나면 `PROMOTES`, 후보가 여럿이면 **가장 긴 일치 문자열**의 제품을 고르고, 가장 긴 일치가 같은 길이인 서로 다른 제품이 둘 이상이면 **만들지 않는다**(`ambiguous`로 센다). 후보가 없으면 만들지 않고 브랜드까지만 잇는다. 관계 속성: `basis`(`title`·`caption`), `confidence`(`name_full`·`alias`), `matched_text`. `content_type != product_creative`인 소재는 만들지 않는다. 다른 브랜드 제품에는 잇지 않는다.
- **TikTok 소재**: 제목·캡션 필드가 비어 있으므로(2026-11-15 확인) 이 규칙으로는 연결되지 않는다. **TikTok은 CQ-09와 분포 용도로만 쓰고 제품 연결(`PROMOTES`) 질문은 YouTube·Instagram에서만 답이 나온다.** 억지로 연결하지 않는다. 요약에서 출처별 후보 소재 수(제목·캡션이 비어 있지 않은 소재 수)를 따로 내고, **YouTube·Instagram의 test 커버리지가 부족하면 별도 추출(영상에서 제품 식별)을 사용자에게 제안하는 문장을 요약 끝에 출력한다**(제안만 하고 실행하지 않는다, 비용이 든다).
- **제품 정보가 없는 브랜드**: 토리든·넘버즈인은 공식몰에서 제품 정보를 받지 못해(ADR-013) 제품이 없으므로 `PROMOTES` 커버리지에서 빠진다. 요약에 "제품 정보 없음" 브랜드 목록을 낸다.
- **dev/test**: 규칙(별칭 길이, 후보 선택)의 조정은 **dev 브랜드의 결과로만** 정한다. test 브랜드는 **커버리지(제품 소재 중 `PROMOTES`가 이어진 비율, `ambiguous` 수)를 보고만** 하고 그 결과를 보고 규칙을 바꾸지 않는다. 요약을 dev·test로 나눠 낸다(`config/brand_split.yaml`에서 읽는다).
- **정밀도 확인용 무작위 20쌍(`--sample-pairs 20`, 기본 20)**: 이어진 `PROMOTES` 중 시드 고정(`--seed`, 기본 상수)으로 무작위 20쌍을 뽑아 **소재 제목·캡션(앞 120자)과 연결된 제품 이름·일치한 문자열·`basis`·`confidence`**를 출력한다(사용자가 정밀도를 확인한다). 같은 시드는 같은 20쌍이다. 20쌍보다 적으면 있는 만큼 낸다.
- **`CLAIMS`(소재→효능)**: `full@v1`의 `claims` 값(`Claim`)에서 `other`를 뺀 것을 `Efficacy`에 잇는다. v1 라벨은 값만 저장하므로 **"주장 원문" 속성은 없다**(`docs/ARCHITECTURE.md`에 정정돼 있다). `full@v1`이 `done`인 소재만.
- **`MENTIONS`(소재→성분 표기)**: `full@v1`의 `ingredients` 원문 각각을 step 7의 대조 결과로 `IngredientAlias`·`Ingredient`에 잇고 속성에 표기 원문을 둔다. 묶이지 않은 표기(`미해결`)는 관계를 만들지 않고 `unresolved` 수로 센다.
- **커버리지 보고**: 요약에 `PROMOTES`가 연결된 제품 소재 수·전체 제품 소재 수·`ambiguous` 수·`CLAIMS`·`MENTIONS` 수·`unresolved` 수를 낸다(2층 질문의 답 크기를 해석하기 위한 값이고 `cq-verify`가 같은 수를 답과 함께 보고한다).
- 변경 판정·MERGE·파라미터·워터마크는 step 0과 같다. 소재나 제품이 바뀌면 `PROMOTES`가 다시 계산되므로 **관계를 다시 맞출 때 이전 `PROMOTES`가 남지 않게** 해당 소재의 `PROMOTES`를 같은 트랜잭션에서 지우고 다시 만든다(이 삭제는 소재 단위 `PROMOTES`에 한정한다).

### 반드시 있어야 하는 테스트

- `match_product`: 같은 브랜드 제품 이름이 제목에 있으면 연결, 캡션에만 있으면 `basis=caption`, 영문명·별칭으로 연결되면 `confidence=alias`, 공백·대소문자·전각 변형이 같은 결과, 이름 일부만 있으면 연결 없음, 다른 브랜드 제품과는 연결되지 않는다, 길이가 다른 두 후보에서 긴 쪽을 고른다, 같은 길이 후보 둘이면 `ambiguous`로 연결 없음, `MIN_ALIAS_LEN` 미만 별칭은 쓰이지 않는다, 빈 제목·캡션은 연결 없음, `product_creative`가 아닌 소재는 연결 없음. (제품 이름·캡션은 합성 문자열이다.)
- dev/test: 요약이 dev·test로 나뉘고 test 결과가 규칙 선택에 쓰이지 않는다(규칙 선택 함수가 dev 입력만 받는 시그니처를 검사한다), 제품 정보 없는 브랜드가 목록에 나온다.
- 무작위 20쌍: 같은 시드는 같은 쌍을 낸다, 쌍 수가 min(20, 연결 수)이고 각 쌍에 제목·캡션과 제품 이름이 있다, 시드를 바꾸면 달라질 수 있다(고정 개수·순서를 단언하지 않고 집합 포함 관계만).
- TikTok 합성 소재(제목·캡션 빈 문자열)는 연결되지 않고 요약의 "후보 소재 수"에서 빠진다.
- `CLAIMS`: `other`는 빠진다, `full@v1`이 아닌 라벨(`@minimal`·`@default`·v0)은 읽지 않는다, 같은 입력을 두 번 넣으면 같은 문장·파라미터다.
- `MENTIONS`: 묶인 표기만 관계가 되고 `미해결`은 `unresolved`로 센다, 표기 원문이 속성에 남는다.
- 재계산: 소재가 바뀌어 `PROMOTES` 대상이 달라지면 이전 `PROMOTES`가 남지 않는다, 삭제가 다른 소재의 관계를 건드리지 않는다(문장이 소재 키로 한정됨).
- 커버리지 요약의 수가 합성 입력의 손계산 값과 같다, 빈 입력은 0건 요약.
- `CREATE`가 없고 값이 문자열에 끼지 않는다, `tests/test_architecture.py`가 통과한다.

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
- 모델을 호출해 제품을 식별하거나 v1 프롬프트·라벨을 다시 만들지 마라. 이유: 분류 v1은 동결됐고 재분석은 비용이 든다(ADR-018).
- test 브랜드의 결과를 보고 규칙(별칭 길이·후보 선택)을 바꾸지 마라. 이유: 규칙은 dev에서 다듬고 test는 커버리지 보고만 한다(승인 2026-11-15).
- 후보가 모호할 때 임의로 하나를 고르지 마라. 이유: 판정하지 못하면 만들지 않는다(ARCHITECTURE). 억지로 붙이면 CQ-04·05·13·14·15·16이 오염된다.
- 제목·캡션의 부분 일치(제품 이름의 일부)로 연결하지 마라. 이유: 오연결은 답을 조용히 틀리게 만든다.
- TikTok 소재를 다른 근거(광고주 이름 등)로 제품에 연결하지 마라. 이유: 승인된 규칙은 제목·캡션 문자열뿐이다.
- `CLAIMS`에 존재하지 않는 "주장 원문"을 만들어 채우지 마라. 이유: v1 라벨은 값만 저장한다.
- 다른 소재의 `PROMOTES`를 지우는 문장을 만들지 마라. 이유: 삭제는 해당 소재로 한정한다.
