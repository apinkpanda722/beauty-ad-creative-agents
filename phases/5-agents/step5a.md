# Step 5a: evidence-tools

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`graph`는 `domain`·`settings`만, `agents`는 `graph` 가능, `eval`은 전부), CRITICAL 규칙(에이전트에게 Cypher 금지, 고수준 도구, 비밀 값)
- `/docs/ARCHITECTURE.md` — "도구 설계 규칙", "2층: 광고 관찰", "지표 정규화"
- `/docs/EVAL.md` — "지표 정규화"(동결, 읽기 전용: 같은 채널 안 조회수 백분위, 게시 14일 이상, 상위·하위 25%)
- `/docs/COMPETENCY_QUESTIONS.md` — v1(동결, 읽기 전용)과 "PROMOTES 연결 범위 측정"
- `/src/beautyads/graph/queries.py`(동결 질의, 읽기 전용), `/src/beautyads/graph/load.py`, `/src/beautyads/graph/layer2.py`, `/src/beautyads/agents/tools.py`, `/src/beautyads/domain/tools.py`, `/src/beautyads/domain/labels.py`, `/src/beautyads/eval/cq_verify.py`(`_percentiles`와 `cq_preflight`), `/tests/test_agent_tools.py`, `/tests/test_graph_queries.py`, `/tests/test_cq_verify.py`, `/tests/test_architecture.py` — 기존 도구 15개와 정규화 방식

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/evidence.py`(새 파일), `src/beautyads/graph/evidence_queries.py`(새 파일), `src/beautyads/agents/tools.py`, `src/beautyads/domain/tools.py`, `src/beautyads/eval/evidence_check.py`(새 파일), `Makefile`, `README.md`, `tests/test_domain_evidence.py`(새 파일), `tests/test_graph_evidence_queries.py`(새 파일), `tests/test_agent_tools.py`, `tests/test_evidence_check.py`(새 파일), `tests/test_compose.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/evidence.py`, `src/beautyads/graph/evidence_queries.py`, `src/beautyads/agents/tools.py`(도구 3개와 그 입력 모델 추가에 한함. 기존 15개 도구의 이름·입력·설명·동작과 `ToolSpec`의 기존 필드는 불변, 새 필드를 더하면 기본값을 둔다), `src/beautyads/domain/tools.py`(추가에 한함, 기존 값 불변), `src/beautyads/eval/evidence_check.py`, `Makefile`(`live-evidence` 타깃과 `.PHONY` 추가에 한함), `README.md`(live-evidence 절 추가에 한함), `tests/test_domain_evidence.py`, `tests/test_graph_evidence_queries.py`, `tests/test_agent_tools.py`(케이스 추가에 한함, 단언 약화 금지), `tests/test_evidence_check.py`, `tests/test_compose.py`(`Makefile` 타깃 목록을 단언한다면 `live-evidence` 추가를 반영하는 갱신에 한함, 그 외 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

동결 CQ 질의(PROMOTES 경유, 연결 범위 5.1%)에 막혀 있는 근거 소재 확보 범위를 넓히는 **새 도구 3개**를 만든다. 동결 질의(`graph/queries.py`)와 기존 15개 도구는 **고치지 않는다**. 새 질의는 `Creative.category`(분석 모델이 붙인 카테고리 라벨)로 직접 소재를 찾는 고정 Cypher다(2026-11-17 읽기 전용 조회: hook 라벨과 조회수가 있는 YouTube·Instagram 소재 1,043건, 같은 조건에서 CQ-06이 읽는 PROMOTES 연결 소재는 100건). 이 step은 모델을 호출하지 않는다. **이 step 안에서는 실제 접속·실행을 하지 않는다.**

**`domain/evidence.py`**(표준 라이브러리·pydantic만): `EvidenceAxis`(StrEnum `hook_type`·`angle`·`format`·`claim`), `CategoryBasis`(StrEnum `creative_label`·`product_link`), `EvidenceSource`(`youtube`·`instagram`·`tiktok`), `MIN_BAND_N = 10`, 순수 함수 `split_top_bottom(rows, *, mature_before) -> BandResult`. `rows`는 `{creative_id, source, channel_brand, views, published_at, value}`의 목록이다. **정규화는 `docs/EVAL.md`와 `eval/cq_verify.py`의 `_percentiles`와 같다**: `views`가 없는 행은 제외하고 개수를 센다(`excluded_missing_views`), 게시 시각이 `mature_before` 이하인 소재만 쓰고, `(source, channel_brand)` 그룹 안에서 조회수를 정렬해 선형 보간으로 25%·75% 경계를 구하며 경계 이상은 `top`, 이하는 `bottom`, 나머지는 `middle`이다. 결과는 축 값별 `n_top`·`n_bottom`, 전체 `top_total`·`bottom_total`, `excluded_missing_views`, 값별 대표 소재 ID(조회수 내림차순, ID 오름차순으로 동률 해소, 최대 3개)와 `note`(고정 문장 "기술적 비교이며 인과를 뜻하지 않는다. 조회수에는 광고비 효과가 섞여 있다.")이다. `min(top_total, bottom_total) < MIN_BAND_N`이면 `low_n=True`이고 `BandResult`가 "표본 부족(n<10): 상위 n=…, 하위 n=…"을 요약 문장으로 만든다.

**`graph/evidence_queries.py`**(`graph` 계층, `domain`만 import): 고정 Cypher 상수와 파라미터 검증. 축 이름은 닫힌 표로 관계·노드 라벨에 대응한다(`hook_type`→`USES_HOOK`·`Hook`, `angle`→`HAS_ANGLE`·`Angle`, `format`→`HAS_FORMAT`·`Format`, `claim`→`CLAIMS`·`Efficacy`). Cypher는 라벨·관계 이름을 파라미터로 받을 수 없으므로 **닫힌 표의 상수만으로 문장을 조립**하고(사용자·모델 입력을 문장에 끼우지 않는다) 모든 값은 `$` 파라미터다. 함수:
- `axis_rows_query(axis, basis) -> str`: 한 카테고리의 소재 행(`category`, `source`, `channel_brand`, `creative_id`(= `c.source + ':' + c.source_id`), `views`, `published_at`, `value`)을 돌려준다. `basis=creative_label`이면 `c.category = $category`(그리고 `c.content_type = 'product_creative'`)로, `basis=product_link`이면 PROMOTES 경로로 소재를 고른다. **`axis=hook_type`·`basis=product_link`의 `MATCH`·`WHERE`·`RETURN` 본문은 `QUESTIONS["CQ-06"]`의 질의와 같은 모양(같은 패턴·같은 조건·같은 반환 열 이름)이어야 한다**: 공백을 정규화한 뒤 CQ-06 질의의 `MATCH` 한 줄이 새 질의에 그대로 들어 있고, CQ-06이 반환하는 열(`category`, `source`, `channel_brand`, `creative_id`, `views`, `hook`)을 모두 같은 값으로 돌려준다(`value`는 `hook`과 같은 값이므로 별칭 `hook`도 함께 반환한다). `WHERE`의 출처·성숙 조건(`c.latest_view_count IS NOT NULL AND c.source IN $sources AND datetime(c.published_at) <= datetime($mature_before)`)도 같다.
- `axis_count_query(axis, basis)`: 축 값별 소재 수와 값별 `creative_id` 목록(조회수 내림차순 앞 3개, 동률은 ID 오름차순)과 전체 소재 수를 돌려준다.
- `example_query(basis)`: `category`와 선택 조건(`hook_type`·`angle`·`format`·`claim` 각각 선택, 값이 `NULL`이면 조건 없음)으로 소재 목록(`creative_id`, `brand`, `source`, `url`, `views`, `published_at`, 그 소재의 `hook_type`·`angle`·`format`)을 조회수 내림차순·ID 오름차순으로 `LIMIT $limit`(상한 20)만큼 돌려준다.
- `evidence_parameters(...)`: 입력(`category`는 `other` 제외 3종, `source`, 축, 기준, 닫힌 값)을 검증해 파라미터 dict를 만든다. 날짜(`mature_before`)는 서버가 준 `as_of`에서 `question_parameters`와 같은 방식(게시 14일 이상)으로 만든다. 모델 입력으로 받지 않는다.

**`agents/tools.py`**에 도구 3개를 **추가**한다(기존 15개·`QUESTIONS` 본문·기존 입력 스키마는 불변): 
| 이름 | 종류 | 입력(닫힌 값) | 하는 일 |
|---|---|---|---|
| `compare_axis_by_category` | compare | `category`, `source`(`youtube`·`instagram`·`tiktok`), `axis`, `category_basis`(기본 `creative_label`) | 축 값별 소재 수와 대표 근거 ID |
| `top_vs_bottom_axis` | compare | `category`, `source`(`youtube`·`instagram`만, TikTok은 조회수가 없다), `axis`, `category_basis` | `axis_rows_query` 결과를 `split_top_bottom`으로 가른 상위 25% 대 하위 25%의 축 값 분포 |
| `find_example_creatives` | lookup | `category`, `source`(선택), `hook_type`·`angle`·`format`·`claim`(각각 선택), `category_basis`, `limit`(1~20) | 조건에 맞는 소재 목록(근거 ID 포함) |
- 출력은 기존 도구와 같은 `ToolResult`이다(`top_rows` 앞 5개, `row_count`, `evidence_ids`(별도 칸), `no_evidence`). **모든 새 도구 결과의 `summary`에 `category_basis`를 적는다**: `creative_label`이면 "모델 라벨 기준(E1 채점 전)", `product_link`이면 "제품 연결 기준(연결된 소재만)". `top_vs_bottom_axis`의 `summary`에는 상위·하위 표본 수 `n`과 "기술적 비교이며 인과를 뜻하지 않는다"를 항상 쓰고, `low_n`이면 "표본 부족(n<10): 상위 n=…, 하위 n=…"을 쓴다. 이 도구 3개는 `PROMOTES` 도구 집합에 넣지 않는다(연결 주석은 `product_link`일 때만 붙인다).
- 도구 `description`의 "쓰지 않는 때:"에 **`category_basis`의 기본값(`creative_label`)과 뜻**을 분명히 적는다: `creative_label`은 분석 모델이 소재에 붙인 `category`(E1 채점 전이라 정확도는 미확정)로 근거 소재가 많고, `product_link`는 `PROMOTES`로 공식몰 제품에 연결된 소재만이라 정확하지만 적다. 제품 단위 주장(성분 연결)이 필요하면 `product_link`를 쓰고 기본값에 의존하지 않는다.
- 새 도구 이름·입력은 기존 규칙(`tenant`·`user`·`date`·`today`·`time` 칸 금지, `extra="forbid"`, 칸마다 `description`, 정렬된 고정 순서, 테넌트 fail-closed)을 그대로 따른다. 기존 도구 테스트(`tests/test_agent_tools.py`)의 일반 단언(이름 정렬·중복 없음·설명 문구)이 새 도구에도 적용된다.

**`eval/evidence_check.py`와 `make live-evidence`**(읽기 전용 라이브 점검, 모델 호출 없음, 비용 0): `eval/cq_verify.py`의 `cq_preflight`와 같은 사전 점검(컨테이너·키 이름 없이 Neo4j 접속 정보 확인) 뒤, 카테고리 3종 각각에 대해 (1) `axis_rows_query(hook_type, product_link)`의 결과 `(creative_id, hook)` 집합이 `QUESTIONS["CQ-06"]` 결과(같은 `as_of`, 같은 출처, 같은 카테고리)와 **같은지**, (2) `creative_label` 결과의 건수와 `product_link` 결과와의 교집합·차집합 건수를 출력한다(포함 관계를 단언하지 않는다: 두 카테고리 값의 출처가 달라 다를 수 있다). (1)이 다르면 비영(非零) 종료 코드 3과 차이 개수를 출력하고 멈춘다. 출력에 키·비밀이 없다. `Makefile`에 `live-evidence: uv run python -m beautyads.eval.evidence_check $(ARGS)`를 추가한다(`verify`에는 넣지 않는다).

**반드시 있어야 하는 테스트**(가짜 `GraphReader`·합성 행만, 값·건수를 모델이나 실제 그래프에서 굳히지 않는다):
- **회귀(동결 질의와의 일치, 오프라인)**: (a) `axis_rows_query("hook_type", "product_link")`에 `QUESTIONS["CQ-06"]`의 `MATCH` 한 줄과 조건 문구가 공백 정규화 뒤 그대로 들어 있고, CQ-06이 반환하는 열 이름 집합이 모두 새 질의의 반환 열에 있다. (b) 기존 15개 도구의 이름·종류·입력 필드 이름과 `QUESTIONS`의 모든 질의 본문이 이 step 전후로 같다(이 step 전의 값을 테스트에 박지 않고, 도구의 `question_id`가 가리키는 `QUESTIONS` 본문과 도구가 실행하는 `cypher`가 같음을 단언한다). (c) `split_top_bottom`이 같은 합성 입력에서 `eval/cq_verify._percentiles`와 같은 `top`·`bottom` 소재 집합을 낸다(`tests`가 두 함수를 모두 import한다).
- `split_top_bottom`: 조회수 없는 행 제외와 개수, 성숙 기준(게시 14일 미만 제외), 그룹 안 보간 경계(합성 값에서 손계산과 같음), 경계값 동률 처리(경계 이상은 `top`, 이하는 `bottom`), 대표 소재 최대 3개와 동률 정렬(ID 오름차순), `low_n` 경계(9는 참, 10은 거짓), 행이 0개면 예외 없이 빈 결과·`low_n=True`.
- 질의: 모든 문장이 `CREATE`·`MERGE`·`SET`·`DELETE`를 포함하지 않는 읽기 전용이고 파라미터만 쓰며, 문장 안에 모델 입력 문자열이 끼지 않는다(모든 축·기준 조합을 돌려 `$` 파라미터 이름 집합이 입력 집합과 같다). 닫힌 값 밖 입력은 `evidence_parameters`가 거부한다.
- 도구: 결과 `summary`에 `category_basis` 문구가 있다(`creative_label`이면 "모델 라벨 기준(E1 채점 전)"). `top_vs_bottom_axis`는 `n`과 "인과를 뜻하지 않는다"가 항상 있고 `low_n`일 때만 "표본 부족"이 있다. `description`의 "쓰지 않는 때:"에 `creative_label`·`product_link`가 모두 설명돼 있다. TikTok `source`는 `top_vs_bottom_axis`에서 `INPUT_INVALID`다. 빈 결과는 `no_evidence=True`, 그래프 오류는 `GRAPH_UNAVAILABLE`이고 둘이 섞이지 않는다. `evidence_ids`가 `EVIDENCE_ID_PATTERN`에 맞고 중복 없는 정렬 목록이다.
- `evidence_check`: 사전 점검 실패 시 호출 없이 이유 코드 종료, 두 집합이 같으면 종료 코드 0, 다르면 3과 차이 개수 출력, 출력에 키·비밀이 없다(가짜 그래프).
- `tests/test_architecture.py`가 통과한다(`graph`는 `domain`만 import, `agents`는 `graph` import 가능, `eval`은 `fastapi`·`httpx`를 import하지 않는다).

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

- `graph/queries.py`의 동결 질의나 기존 15개 도구를 고치지 마라. 이유: CQ v1이 동결돼 있다. 새 질의는 `graph/evidence_queries.py`에 따로 둔다.
- 모델 입력(카테고리·축 값·조건)을 Cypher 문자열에 끼우지 마라. 이유: 닫힌 표의 상수로만 문장을 조립하고 값은 `$` 파라미터다(AGENTS.md: 에이전트에게 Cypher를 쓰게 하지 않는다).
- `creative_label` 결과를 `product_link` 결과와 같은 근거 수준으로 표기하지 마라. 이유: `Creative.category`는 분석 모델 라벨이고 E1 채점 전이다. 모든 결과에 기준을 밝힌다(2026-11-17 판단).
- 백분위 정규화를 새로 정의하지 마라. 이유: `docs/EVAL.md`(동결)와 `cq_verify._percentiles`를 따른다(B-FP-044: 같은 판정에 규칙이 둘이면 안 된다). 두 함수가 같은 집합을 내는지 테스트로 묶는다.
- TikTok에 상위·하위를 적용하지 마라. 이유: TikTok은 조회수가 없고 도달 구간이다(ARCHITECTURE 지표 정규화).
- 테스트 기대값에 실제 그래프 건수(1,043·100 등)나 모델이 만든 값을 굳히지 마라. 이유: 값은 실행 시점마다 달라진다(FP-C03, B-FP-061). 합성 행과 구조·관계만 단언한다.
