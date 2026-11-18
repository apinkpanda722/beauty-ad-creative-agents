# Step 5b: certified-by-claim

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`graph`는 `domain`만, `agents`는 `graph` 가능), CRITICAL 규칙(에이전트에게 Cypher 금지, 고수준 도구)
- `/docs/COMPETENCY_QUESTIONS.md` — v1(동결, 읽기 전용)의 CQ-03·10·11과 "CQ-03·10·11의 인증 연결 규칙과 커버리지"(연결되지 않은 제품은 "인증 없음"이 아니라 unknown)
- `/docs/ARCHITECTURE.md` — "도구 설계 규칙"
- `/src/beautyads/graph/queries.py`(동결, 읽기 전용: `QUESTIONS["CQ-03"]`, `_CERT_CLAIMS`), `/src/beautyads/graph/evidence_queries.py`, `/src/beautyads/agents/tools.py`, `/src/beautyads/domain/evidence.py`, `/src/beautyads/domain/tools.py`, `/src/beautyads/eval/evidence_check.py`, `/tests/test_graph_evidence_queries.py`, `/tests/test_agent_tools.py`, `/tests/test_evidence_check.py`, `/tests/test_architecture.py` — step 2·5a 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/graph/evidence_queries.py`, `src/beautyads/agents/tools.py`, `src/beautyads/domain/evidence.py`, `src/beautyads/eval/evidence_check.py`, `tests/test_graph_evidence_queries.py`, `tests/test_agent_tools.py`, `tests/test_evidence_check.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/graph/evidence_queries.py`(질의 1개와 입력 검증 추가에 한함, 기존 질의·함수 불변), `src/beautyads/agents/tools.py`(도구 1개와 입력 모델 추가에 한함, 기존 도구의 이름·입력·설명·동작과 `ToolSpec`의 기존 필드 불변), `src/beautyads/domain/evidence.py`(닫힌 값 추가에 한함, 기존 값 불변), `src/beautyads/eval/evidence_check.py`(점검 항목 추가에 한함, 기존 점검과 종료 코드 불변), `tests/test_graph_evidence_queries.py`(케이스 추가에 한함, 단언 약화 금지), `tests/test_agent_tools.py`(케이스 추가에 한함, 단언 약화 금지), `tests/test_evidence_check.py`(케이스 추가에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

첫 `make live-agent`에서 보인 한계: 동결 CQ-03 도구(`lookup_certified_products`)는 입력이 없어 미백(`brightening`)만 조회하고, 주름 개선(`anti_aging`)·자외선 차단(`sun_protection`) 인증 제품은 물을 수 없다. 인증 종류를 입력으로 받는 **새 도구 1개**를 만든다. 동결 질의(`graph/queries.py`)와 기존 도구는 고치지 않는다. 이 step은 모델을 호출하지 않는다. **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

**`domain/evidence.py`**: `CertificationKind`(StrEnum `brightening`·`anti_aging`·`sun_protection`, `graph/queries.py`의 `_CERT_CLAIMS` 키와 같은 값. 값 목록을 `_CERT_CLAIMS`에서 읽지 않고(`domain`은 `graph`를 import하지 않는다) 같은 값을 정의하고, 두 목록이 같다는 테스트를 둔다).

**`graph/evidence_queries.py`**: `certified_by_kind_query() -> str`(고정 Cypher, 값은 `$cert` 파라미터). `QUESTIONS["CQ-03"]`와 **같은 패턴·같은 조건**(`MATCH (p:Product)-[:CERTIFIED_AS]->(f:FunctionalCert)`와 `WHERE f.value = $cert`)이고 CQ-03이 반환하는 열(`product`, `certification`)을 같은 값으로 돌려주며 읽기 쉬운 열 두 개를 더한다(`brand` = `p.brand`, `product_name` = `p.name_ko`). `ORDER BY p.brand, p.source_url`로 순서를 고정한다. 입력 검증 함수가 `cert`를 `CertificationKind` 값으로 제한한다.

**`agents/tools.py`**: 도구 `certified_products_by_kind`(종류 `lookup`)를 **추가**한다. 입력 `certification`(`CertificationKind`, 칸 설명에 "brightening=미백, anti_aging=주름 개선, sun_protection=자외선 차단"). 출력은 기존 도구와 같은 `ToolResult`(`rows`의 `product`·`certification`·`brand`·`product_name`, `top_rows` 앞 5개, `row_count`, 근거 ID 칸은 소재가 아니라 제품이라 비어 있다, 행이 0이면 `no_evidence`). `summary`에 "식약처 보고 품목과 연결된 제품만 해당한다. 연결되지 않은 제품은 인증 없음이 아니라 알 수 없음이다."를 항상 붙인다. 도구 `description`의 "쓰지 않는 때:"에 **동결 CQ-03 도구와의 관계**를 적는다: `lookup_certified_products`(입력 없음, 미백만)와 `certification="brightening"`은 같은 제품 집합을 돌려준다(새 도구는 열이 두 개 더 있다). 미백만 필요하면 어느 쪽을 써도 되고, 다른 인증 종류가 필요하면 이 도구를 쓴다. 이 도구는 인증이 없다는 사실을 돌려주지 않는다(연결 커버리지가 제한적이라 빈 결과는 "인증 없음"이 아니다). 기존 도구 규칙(`tenant`·`user`·`date`·`today`·`time` 칸 금지, `extra="forbid"`, 칸마다 `description`, 정렬된 고정 순서, 테넌트 fail-closed)을 따른다.

**`eval/evidence_check.py`**: 읽기 전용 점검 항목 추가: 세 인증 종류 각각에 대해 새 질의의 `(product, certification)` 집합이 `QUESTIONS["CQ-03"]`의 Cypher를 같은 `cert` 파라미터로 돌린 결과와 같은지 확인한다. 다르면 기존 점검과 같은 종료 코드 3과 차이 개수를 출력한다. 종류별 건수를 함께 출력한다. 기존 점검 동작은 바꾸지 않는다.

**반드시 있어야 하는 테스트**(가짜 `GraphReader`·합성 행만, 값·건수를 실제 그래프에서 굳히지 않는다):
- 회귀(동결 질의와의 일치, 오프라인): `certified_by_kind_query()`에 `QUESTIONS["CQ-03"]`의 `MATCH` 한 줄과 `WHERE` 조건이 공백 정규화 뒤 그대로 들어 있고, CQ-03의 반환 열 이름이 모두 새 질의의 반환 열에 있다. `CertificationKind` 값 집합이 `_CERT_CLAIMS` 키 집합과 같다. 기존 도구들의 이름·입력 필드·`QUESTIONS` 본문이 이 step 전후로 같다(도구의 `question_id`가 가리키는 본문과 실행하는 `cypher`가 같음을 단언).
- 도구: 닫힌 값 밖 `certification`은 `INPUT_INVALID`이고 그래프가 불리지 않는다. 합성 행에서 `ToolResult.top_rows`가 5개로 잘리고 `row_count`가 전체다. 빈 결과는 `no_evidence=True`, 그래프 오류는 `GRAPH_UNAVAILABLE`이고 둘이 섞이지 않는다. `summary`에 "인증 없음이 아니라 알 수 없음"이 있다. `description`의 "쓰지 않는 때:"에 `lookup_certified_products`와 `brightening`이 같은 집합이라는 설명이 있다.
- 질의: 읽기 전용(`CREATE`·`MERGE`·`SET`·`DELETE` 없음), 파라미터만 쓰고 문장에 입력이 끼지 않는다.
- `evidence_check`: 세 집합이 같으면 종료 코드 0, 다르면 3과 차이 개수, 출력에 키·비밀 없음(가짜 그래프). 기존 `tests/test_evidence_check.py` 단언은 그대로 통과한다.
- `tests/test_architecture.py`가 통과한다.

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

- `graph/queries.py`의 동결 질의(CQ-03·CQ-10)나 기존 도구를 고치지 마라. 이유: CQ v1이 동결돼 있다. 새 질의는 `graph/evidence_queries.py`에 따로 둔다.
- 빈 결과를 "인증 없음"으로 표기하지 마라. 이유: 식약처 품목과 연결되지 않은 제품은 인증이 없는 것이 아니라 `unknown`이다(COMPETENCY_QUESTIONS 한계).
- 모델 입력(`certification`)을 Cypher 문자열에 끼우지 마라. 이유: 값은 `$cert` 파라미터이고 닫힌 값만 받는다(AGENTS.md: 에이전트에게 Cypher를 쓰게 하지 않는다).
- 테스트 기대값에 실제 그래프 건수(13·11·16 등)를 굳히지 마라. 이유: 값은 데이터 갱신마다 달라진다(B-FP-061). 구조·관계·동일성만 단언하고 건수는 live 점검 출력으로만 본다.
