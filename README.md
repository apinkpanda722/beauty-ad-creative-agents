# beauty-ad-creative-agents

뷰티 광고 크리에이티브를 분석해 근거가 달린 기획안을 만드는 멀티에이전트 프로젝트.

## live-agent (P5 요청 뼈대)

사용자가 PostgreSQL 마이그레이션·Neo4j 제품 그래프와 서비스를 준비하고 실행한다.
`OPENAI_API_KEY`, `NEO4J_PASSWORD`, `POSTGRES_PASSWORD`를 기존 설정 방식으로
준비한다. 다음 명령은 개발·검증 과정에서 실행하지 않으며 `verify`에도 포함하지 않는다.

```bash
make live-agent ARGS='--tenant demo-a --message "기능성 인증에 연결된 제품을 알려줘" --max-usd 0.02'
```

`--tenant`와 `--message`는 필수다. 키 설정 여부(이름만), 컨테이너·포트·기존
마이그레이션을 점검하고 실패하면 `PREFLIGHT_FAILED <이유 코드>`와 종료 코드 2로
끝난다. 점검을 통과하면 앱 lifespan 안에서 체크포인터 풀을 열고 `setup()`한 뒤,
프로세스 안에서 `/chat` 한 건을 호출하고 자원을 닫는다. SSE 이벤트 종류·최종 답·
원장 비용 증가분을 출력한다. HTTP/SSE 실행 실패는 종료 코드 3이다.

모델은 `gpt-6-luna`, `reasoning_effort="none"`이며 조회 도구는
`lookup_certified_products` 하나다. 모델은 최대 두 번 호출한다.
`--max-usd`(기본 $0.02)는 **모델 한 호출**의 예상 비용 상한이다. 호출마다
UTF-8 입력 크기·가격표·출력 최대 1,024토큰으로 보수적으로 추정하고
초과하면 호출 전에 멈춘다. 공급사 누적액 상한도 기존 원장으로 검사한다.

데모 세션은 `X-Tenant-Id` 헤더이며 인증 기능은 아니다. 조립의 허용 목록과
thread 소유권을 그래프 실행 전에 검사한다. `/chat` 본문은 `message`와 선택
`thread_id`만 받는다. 새 thread는 `X-Thread-Id` 응답 헤더로 돌려준다.
`step`·`tool_start`·`token` 이벤트를 보내며, 예외는 코드만 담은 `error`로 닫는다.
`/healthz`는 의존 서비스를 조회하지 않는다. PostgreSQL 원본의 마지막 수집 시각을
프롬프트에 넣고, 수집 기록이 없으면 unknown으로 표시한다.
Supervisor·역할별 에이전트·화면 명령 생성은 이후 step의 범위다.

## sync: 피드백 패턴 (P5)

사용자가 PostgreSQL의 `tenant_feedback`과 Neo4j를 준비한 뒤 실행한다.

```bash
make sync ARGS='--layers 3'
make sync ARGS='--layers 3 --limit 50'
make sync ARGS='--layers 3 --full --verify'
```

`--layers 3`은 `(tenant_id, feedback_id)`로 Feedback을 MERGE하고,
`plan_id`·`decision`·UTC ISO 문자열 `created_at`을 기록한다.
`ABOUT`은 훅(Hook)과 효능(Efficacy)의 전체 집합으로 같은 트랜잭션에서
교체한다. 반려 사유 원문과 기획안 본문은 PostgreSQL에만 남긴다.
테넌트 ID나 훅·효능·승인/반려 값이 유효하지 않으면 해당 Feedback 전체를
쓰지 않고 `FEEDBACK_VALUE_INVALID`로 보고한다. 요약에는 `read`·`loaded`·
`rejected`·`errors`와 그래프 생성 수·워터마크가 나온다.

전용 워터마크는 `tenant_feedback_layer3_v1`이다. PostgreSQL `updated_at`을
기준으로 10분 겹쳐 읽고, 모든 적재와 선택적 검증 성공 뒤에만 읽은 행의
최대 변경 시각으로 갱신한다. 거부한 행도 읽은 수와 워터마크에 포함되며,
수정 후 다시 반영하려면 원본 `updated_at`도 갱신하거나 `--full`을 쓴다.
`--verify`는 같은 입력을 재적재해 속성과 `ABOUT` 집합이 같은지 확인한다.
`--sample`은 3층에서 사용할 수 없다. 모델 호출이나 다운로드는 없다.

## live-graph (P4)

PostgreSQL 원본에서 Creative와 분류 축(Hook·Angle·Format·Talent·CtaType)을
Neo4j로 증분 동기화한다. OrbStack을 켜고 `.env`에 `POSTGRES_PASSWORD`와
`NEO4J_PASSWORD`(8자 이상)를 준비한 뒤 사용자가 다음 명령을 실행한다.
수집·분석 결과가 PostgreSQL에 있어야 하며 모델 호출과 다운로드는 없다.

```bash
make db-up
# 컨테이너가 준비된 뒤 사용자가 실행한다.
make live-graph
# 전체 변경분 동기화와 선택적 읽기 상한·재구축
make sync
make sync ARGS='--limit 50'
make sync ARGS='--full'
```

Neo4j 주소 기본값은 `bolt://127.0.0.1:7688`이며 필요하면
`BEAUTYADS_NEO4J_URI`로 바꾼다. PostgreSQL 호스트 포트는 기본 5433이고
기존 `BEAUTYADS_POSTGRES_PORT`를 따른다. Neo4j 드라이버는 `6.4.1`이다.

`make live-graph`는 `--sample 50 --verify`로 **분석 완료(`*@v1`) 소재를 우선**
고른 50건을 두 번 적재한다(`--sample`은 `--limit`·`--full`과 함께 쓸 수
없고 워터마크를 올리지 않는다). 두 번째 `nodes_created`와
`relationships_created`가 0인지, 두 번의 Creative `count`가 같은지,
분류 값 노드가 닫힌 목록 안인지 `count`로 확인하고 요약의 `verification`에
출력한다. 요약의 `graph_check`는 표본 중 훅·전체 라벨이 있는 소재 수
(`labeled_in_sample`)와 그래프의 분류 축 관계 수(`axis_relationships`)다.
**표본에 분석 완료 소재가 없으면 `GRAPH_VERIFY_NO_LABELED_SAMPLE`, 라벨이 있는데
관계가 0이면 `GRAPH_VERIFY_NO_RELATIONSHIPS`로 실패한다**(검사한 것이 없는 것을
통과로 보지 않는다). 전체를 처음부터 적재하며 검증하려면
`make sync ARGS='--full --verify'`를 쓴다. 기본 동기화 요약에는 `read`, `nodes_created`,
`relationships_created`, `skipped_invalid`, `watermark`, `elapsed_s`가 나온다.
변경분이 없으면 정상 0건 요약이며 워터마크는 유지된다.

변경 판정은 소재와 최종 분석 작업의 PostgreSQL `updated_at`으로 한다.
워터마크보다 10분 앞에서 겹쳐 읽고, 모든 적재와 선택적 검증이 성공한 뒤에만
읽은 행의 최대 변경 시각으로 워터마크를 올린다. `--full`은 워터마크를
무시하고 처음부터 MERGE하며 그래프를 삭제하지 않는다. `properties_set`은
같은 값을 다시 써도 증가하므로 변경 판정에 쓰지 않는다.
라벨은 `FINAL_RUN_TAG`의 `content_type@v1`·`hook@v1`·`full@v1` 중
`done` 작업만 사용한다. 제품 소재에만 분류 축 관계를 만들고 목록 밖 값은
`skipped_invalid`로 센다. 기존 v1 훅 라벨은 묘사 필드가 없으므로,
훅 묘사는 원본 라벨에 `hook_description`이 있을 때만 관계에 기록한다.

**첫 볼륨 비밀번호 함정:** Neo4j 비밀번호는 데이터 볼륨을 처음 만들 때만
적용된다. 나중에 `.env`만 바꾸면 인증에 실패한다. 원래 비밀번호를 확인하고,
그래프를 원본에서 다시 만들기로 결정한 경우에만 사용자가 기존
`make graph-reset CONFIRM=yes`와 `make db-up`, `make sync ARGS='--full'`을
차례로 실행한다. `graph-reset`은 그래프 데이터를 삭제한다.
PostgreSQL도 비밀번호가 첫 볼륨에 적용되므로 기존 원본 볼륨의 비밀번호를
확인한다.

실패 출력은 `PREFLIGHT_FAILED <코드>`와 종료 코드 2, 정상 완료는 0이다.
점검이 실패하면 드라이버 생성과 저장소 접속을 하지 않는다. 키·비밀번호·URI의
인증 정보는 출력하지 않으며 두 Make 타깃은 `verify`에 포함하지 않는다.

| 이유 코드 | 의미와 조치 |
|---|---|
| `ENV_MISSING:NEO4J_PASSWORD` | 공백이 아닌 Neo4j 비밀번호를 설정한다. |
| `ENV_MISSING:POSTGRES_PASSWORD` | 공백이 아닌 PostgreSQL 비밀번호를 설정한다. |
| `INVALID_SETTING:NEO4J_PASSWORD` | Neo4j 비밀번호를 8자 이상으로 설정한다. |
| `DOCKER_DOWN` | OrbStack을 켜고 Docker 데몬 준비를 기다린다. |
| `POSTGRES_UNREACHABLE` | `make db-up`과 PostgreSQL 노출 포트를 확인한다. |
| `NEO4J_UNREACHABLE` | `make db-up`과 Neo4j 주소·노출 포트를 확인한다. |
| `NEO4J_AUTH_VOLUME_STALE` | 비밀번호는 데이터 볼륨을 처음 만들 때만 적용된다. 원래 값을 확인하거나 명시적으로 `make graph-reset`으로 재구축한다. |
| `NEO4J_CONSTRAINT_VIOLATION` | 원본 키와 기존 그래프의 유일 제약 위반 데이터를 확인한다. |
| `POSTGRES_AUTH_FAILED` / `POSTGRES_CONNECT_FAILED` | 원본 DB의 비밀번호·컨테이너·포트를 확인한다. |
| `GRAPH_VERIFY_FAILED` | 반복 적재의 생성 수·Creative 수·닫힌 목록 검증이 실패했다. 워터마크를 갱신하지 않는다. |
| `SYNC_FAILED` | 원본 스키마·데이터 형식·실행 환경을 확인하고 다시 실행한다. 워터마크 이전에 실패했다면 겹쳐 읽어 재적재한다. |

## sync: 1층 제품 지식 (P4)

사용자가 PostgreSQL의 제품 레코드와 Neo4j를 준비한 뒤 실행한다.

```bash
make sync ARGS='--layers 1'
make sync ARGS='--layers 1 --limit 50'
make sync ARGS='--layers 1 --full --verify'
```

`--layers 1`은 제품·성분·별칭·인증·표현 규칙과 효능·피부 분류를 MERGE한다.
옵션을 생략하거나 `--layers 2`를 지정하면 기존 Creative·분류 축 동기화가
실행된다. `--sample`은 기존 소재 확인 전용이며 1층과 함께 쓰면 거부한다.
제품 키는 `(brand, source_url)`, 성분 키는 `standard_name`이다. 가격·용량과
단위, 제품명·영문명·별칭·가격 수집 시각을 보존하고 `unit_list_price`는
용량당 정가다(`price_basis: sale_price_fallback`이면 판매가로 계산).
전성분의 핵심 성분 여부는 원본에 없어 `is_key`를 null로 전달한다.
**새 속성을 추가하는 step 뒤에는 `--full` 재동기화가 필요하다.** 증분 동기화는 PostgreSQL 변경 시각이 바뀐 소재·제품만 다시 읽으므로, 이미 적재된 노드에는 새 속성이 채워지지 않는다(예: `Creative.advertiser_name`은 `--layers` 없이 `make sync ARGS='--full'`로 기본 동기화를 한 번 다시 돌려야 CQ-09 분류가 나온다).

1층 워터마크는 `public_products_layer1_v1`로 기존 소재 워터마크와 분리한다.
제품·성분·인증의 `updated_at`과 재추출 기록의 `created_at` 중 최대값을
기준으로 10분 겹쳐 읽는다. 변경된 제품의 성분·인증은 같은 PostgreSQL
스냅샷에서 **전체 집합**을 읽는다. `CONTAINS`를 MERGE한 뒤 원본에 없는
순서·표준명 관계를 삭제하므로, 재파싱이 짧아지거나 표준명이 바뀌어도
이전 관계가 남지 않는다. 미해결 성분은 PostgreSQL에만 남긴다.
변경 시각이나 재추출 기록 없이 수동으로 행만 삭제했다면 `--full`로 반영한다.
모든 적재와 선택적 반복 검증이 성공한 뒤에만 원본 시각으로 워터마크를
갱신하며 그래프 생성 카운터는 변경 판정에 쓰지 않는다.

`config/ingredient_efficacy.yaml`의 `links`만 `HAS_EFFICACY`로 적재하며
`basis`·`source_ref`·`conditional`을 관계에 기록한다. `unmatched`와
`not_linked_for_now`는 연결하지 않고 동명 요약 필드에 개수만 출력한다.
표에 없는 성분은 **근거 연결 없음**이며, `conditional: true`는 고시 함량
조건과 기능성 심사(보고)가 필요하다는 뜻이다. 성분 함유만으로 효능이나
제품 인증이 인정되는 것은 아니다.

`config/efficacy_concerns.yaml`의 `confirmed`·`taxonomy_definition`·출처가
있는 행만 `ADDRESSES`로 올린다. 이는 효능의 실증 주장이 아닌 프로젝트
분류 체계다. `claim_rules.yaml`의 규칙은 `advisor_approved`·`confirmed`
범위만 효능·피부 고민·카테고리에 연결한다. 두 대응의 draft 합계는
`draft_not_loaded`다. 인증은 `certified`만 연결하고 `unknown`은 연결하지
않는다. 요약 `certification`에는 읽은 제품 수(`products`), 인증 상태별
행 수(`certified`·`unknown`), 제품 단위 커버리지
(`certified_products`·`unknown_products`)가 나온다.

표 전체는 적재 전에 검증한다. 형식이나 필수 출처가 잘못되면
`INGREDIENT_EFFICACY_INVALID`·`EFFICACY_CONCERN_INVALID`로 중단하며,
`--verify`는 같은 입력을 재적재해 두 번째 생성 수가 0인지 확인한다.
이 명령은 모델·출처 API 호출이나 이미지 다운로드를 하지 않는다.

## sync: 2층 소재와 제품 연결 (P4)

Step 9부터 명시적인 `--layers 2`는 기존 Creative·분류 축 동기화에
`PROMOTES`·`CLAIMS`·`MENTIONS`를 추가한다. 사용자가 1층 제품 적재와
step 7의 `ingredient-matches@v1` 대조를 마친 뒤 실행한다.

```bash
make sync ARGS='--layers 2 --full --verify'
make sync ARGS='--layers 2'
make sync ARGS='--layers 2 --sample-pairs 20 --seed 20261115'
```

`--layers` 생략 및 `--sample 50 --verify`는 기존 소재·분류 축 확인 동작을
유지한다. `--sample-pairs`(기본 20, 0이면 생략)와 `--seed`(기본 20261115)는
제품 연결 정밀도를 사람이 확인할 표본을 정한다. 제목·캡션은 각각 앞
120자, 제품 이름·제품 URL·일치 문자열·`basis`·`confidence`와 함께 요약의
`sample_pairs`에 나온다. 같은 입력·시드는 입력 순서와 무관하게 같은 쌍을
고른다. `matched_text`는 정규화 비교에서 일치한 제품명·별칭의 저장 표기다.

`PROMOTES`는 `content_type@v1`이 `done`인 제품 소재에만 만든다.
NFKC·대소문자 무시·공백 제거 뒤 같은 브랜드의 한글 제품명 전체 또는
영문명·별칭이 제목·캡션에 포함되어야 한다. 영문명·별칭은 정규화 길이
3자 이상만 쓴다. 최장 일치 제품이 둘이면 `ambiguous`로 보류한다.
제품명 일부만으로는 연결하지 않는다. `basis`는 `title`·`caption`,
`confidence`는 한글 제품명 전체면 `name_full`, 영문명·별칭이면 `alias`다.
동일 제품 안에서 길이가 같으면 전체 이름, 제목 순으로 근거를 고른다.

`CLAIMS`는 `done`인 `full@v1`의 유효한 `claims` 값에서 `other`를 제외한다.
주장 원문 속성은 없다. `MENTIONS`는 같은 `full@v1`의 성분 원문과
`done`인 `ingredient-matches@v1`의 `raw_name`이 정확히 같고 표준명이 하나로
묶인 경우에만 `IngredientAlias`로 잇고 `ALIAS_OF`로 `Ingredient`에 잇는다.
`raw_name` 관계 속성에 원문을 보존하며 나머지는 `unresolved`로 센다.
시범 `@minimal`·`@default`·v0 라벨은 읽지 않는다. 모델 재분석은 하지 않는다.

2층 워터마크는 `public_links_layer2_v1`이다. 소재·v1 분석 작업과 같은
브랜드 제품의 PostgreSQL 변경 시각 중 최대값을 10분 겹쳐 읽는다.
제품명·별칭이 바뀌거나 새 제품이 생겨도 그 브랜드 소재를 재계산한다.
해당 소재 키의 이전 `PROMOTES` 삭제와 새 관계의 MERGE는 한 트랜잭션이다.
`CLAIMS`·`MENTIONS`도 해당 소재에서 사라진 할당을 제거한다. 변경 시각 없이
수동 삭제한 원본은 `--full`로 반영한다. 모든 적재와 반복 검증이 성공한
뒤에만 워터마크를 저장한다. `--verify`는 재생성 카운터 대신 관계·속성·대상
집합의 동일성을 검사한다(`PROMOTES`는 반복 시에도 삭제 후 다시 만들어진다).

요약의 `promotes`, `product_creatives`, `coverage`, `ambiguous`, `claims`,
`mentions`, `unresolved`는 이번에 실제 적재한 소재 집합을 기준으로 집계하며
`coverage_scope: applied_batch`으로 표시한다. `read`와 생성 카운터도
이번 변경분 적재 수다. 표본 쌍은 이 집합에서 실제 연결한 소재만 대상으로
고른다. 전체 커버리지와 전 소재의 정밀도 표본을 확인하려면 `--limit` 없이
`--full --verify`를 사용한다. `config/brand_split.yaml`에 따라 `dev`·`test`와
출처별로 같은 수를 보고하며 규칙 선택에는 dev 입력만 전달한다.
test 결과로 별칭 길이나 후보 선택 규칙을 바꾸지 않는다.

제품이 없는 브랜드는 `no_product_info_brands`(제품 정보 없음)에 나열하고
`product_creatives` 분모에서 제외한다. `all_product_creatives`는 제외 전
제품 소재 수다. 토리든·넘버즈인은 공식몰 제품 정보가 없어 이 한계에 해당한다.
`candidates_by_source`는 제목·캡션이 비어 있지 않은 제품 소재 수다.
TikTok은 두 필드가 비어 있어 후보에 포함되지 않으며 제품에 억지로 잇지
않는다. TikTok은 CQ-09와 분포 용도이고 제품 연결 질문의 답은
YouTube·Instagram에 한정된다. YouTube·Instagram의 test 대상 중 미연결이
있으면 요약 마지막 `recommendation`에서 영상 제품 식별의 별도 추출을
제안한다. 이 제안은 유료 모델 비용이 드는 후속 작업이며 실행하지 않는다.

- 하네스 사용법: [scripts/README.md](scripts/README.md)
- 요구사항·설계·결정 기록: [docs/](docs/)

## 구성도

아래 그림은 `docs/ARCHITECTURE.md`의 글과 `AGENTS.md` 계층 경계 표, `tests/test_architecture.py`의 `LAYER_IMPORTS`에 적힌 구성만 옮긴 것이다. 구현이 바뀌면 같이 고친다.

### 1. 전체 구성

```mermaid
flowchart LR
  subgraph SRC[출처]
    YT[YouTube Data API]
    IG[Instagram Business Discovery]
    TT[TikTok Commercial Content API]
    MFDS[식약처 공공 API]
    MALL[공식몰 상세 페이지]
  end

  subgraph OFF[오프라인 파이프라인]
    AD[출처 어댑터 · 공통 소재 형식]
    SEL[콘텐츠 유형 선별 · 제품 소재만 통과]
    AN[소재 분석 에이전트 · Gemini · 훅 3초 + 전체 두 번 호출]
    VAL[스키마 검증 · 1회 재요청 후 보류]
    SYNC[증분 동기화 · 바뀐 행만 MERGE]
  end

  subgraph STORE[저장소]
    PG[(PostgreSQL · 원본 소재 · 지표 이력 · 모델 출력 원문 · 작업 상태 · 체크포인터)]
    NEO[(Neo4j · 온톨로지 1층 제품 지식 + 2층 광고 관찰)]
  end

  subgraph ON[온라인 에이전트]
    WEB[웹 화면]
    API[FastAPI · SSE 단계 이벤트]
    SUP[Supervisor · 요청 유형 판정 · 과제 지시서]
    RES[리서치 · 그래프 도구 4종]
    PLAN[기획 · OpenAI]
    EVAL[평가 · Anthropic · 코드 검사 + LLM 채점]
  end

  LLM[LLM 호출 래퍼 · LiteLLM SDK · 재시도 · 대기 · 비용 집계 · 공급사별 누적액 검사]
  LF[Langfuse · 요청별 trace · 에이전트별 호출 수·비용·지연]

  YT --> AD
  IG --> AD
  TT --> AD
  MFDS -- 1층 제품 지식 --> PG
  MALL -- 1층 제품 지식 --> PG
  AD --> PG
  PG --> SEL --> AN --> VAL --> PG
  PG --> SYNC --> NEO

  WEB <--> API
  API --> SUP --> RES
  RES --> NEO
  SUP --> PLAN --> EVAL
  EVAL -- 미달 시 사유와 함께 최대 2회 --> PLAN
  EVAL --> API
  API -- 승인·반려 사유 --> NEO

  AN --- LLM
  PLAN --- LLM
  EVAL --- LLM
  SUP --- LLM
  RES --- LLM
  ON -. trace .-> LF
  ON -. 체크포인터 .-> PG
```

### 2. 요청 한 번의 흐름 (온라인)

```mermaid
sequenceDiagram
  participant U as 사용자
  participant A as API · SSE
  participant S as Supervisor
  participant R as 리서치
  participant G as Neo4j
  participant P as 기획
  participant E as 평가

  U->>A: 요청
  A->>S: 요청 + 작업 공간(tenant_id는 세션에서)
  S->>S: 유형 판정 (패턴·관계·기획·범위 밖)
  S->>R: 과제 지시서 (목표 · 조건 · 산출 형식)
  R->>G: 고수준 도구 호출 (조회·집계·비교)
  G-->>R: 근거 소재 · 집계 값
  R-->>S: 구조화 요약 (근거 소재 ID · 확신 수준 · 못 푼 것)
  alt 근거가 기준 건수 미만
    S-->>A: 근거 없음으로 종료
  else 기획 요청
    S->>P: 과제 지시서 + 근거 소재 ID 목록
    P-->>E: 기획안 (주장마다 근거 소재 ID)
    E->>E: 코드 검사 (근거 ID 존재 · 분류 값 유효 · 금지 표현)
    E->>E: LLM 채점 (차별성 · 요청 적합성)
    alt 미달 (최대 2회)
      E-->>P: 사유와 함께 되돌림
    else 통과 또는 미달 표시
      E-->>A: 기획안 + 점수
    end
  end
  A-->>U: 응답 + 근거 카드 + 그래프 조각
  U->>A: 승인·반려 사유
  A->>G: 피드백 저장
```

### 3. 계층 의존 방향 (코드 구조)

```mermaid
flowchart TB
  EVAL[eval · 평가셋 · 실험 · 채점]
  ASM[api · pipeline · 조립]
  AGENTS[agents · supervisor · research · planning · evaluation]
  ANALYSIS[analysis]
  CHECKS[checks]
  GRAPH[graph]
  LLM[llm]
  STORE[store]
  SOURCES[sources]
  OBS[obs]
  DOMAIN[domain · 표준 라이브러리와 pydantic만]

  EVAL --> ASM
  EVAL -.->|다른 모든 계층도 import 가능| AGENTS
  ASM --> AGENTS
  ASM --> ANALYSIS
  ASM --> SOURCES
  ASM --> STORE
  AGENTS --> CHECKS
  AGENTS --> GRAPH
  AGENTS --> LLM
  AGENTS --> STORE
  AGENTS --> OBS
  ANALYSIS --> LLM
  LLM --> OBS
  OBS --> DOMAIN
  LLM --> DOMAIN
  CHECKS --> DOMAIN
  GRAPH --> DOMAIN
  STORE --> DOMAIN
  SOURCES --> DOMAIN
  ANALYSIS --> DOMAIN
  AGENTS --> DOMAIN
```

화살표는 "import할 수 있다"는 방향이다. 출처는 `AGENTS.md`의 계층 경계 표와 `tests/test_architecture.py`의 `LAYER_IMPORTS`이며 정확한 허용표는 테스트가 기준이다. `api`와 `pipeline`은 `domain`부터 `agents`까지 모든 계층을 직접 import할 수 있고(그림은 중복을 줄여 일부 화살표를 생략했다), 서로를 import하지 않는다. `eval`은 `api`·`pipeline`을 포함한 다른 모든 계층을 import할 수 있고 다른 계층은 `eval`을 import하지 않는다. `settings`(루트 모듈, `.env`를 읽는 유일한 함수)는 `obs`·`llm`·`sources`·`store`·`graph`·`api`·`pipeline`·`eval`이 import할 수 있어(`LAYER_IMPORTS` 기준) 그림에서 뺐다. 외부 SDK는 `litellm`은 `llm`, `neo4j`는 `graph`, `httpx`는 `sources`, `langfuse`는 `obs`, `fastapi`는 `api`, `psycopg`는 `store`와 `api`, `langgraph`는 `agents`와 `api`에서만 쓴다.

## E1 라벨링 시트 (P3)

두 명령은 사용자가 직접 실행한다. `config/e1_sampling.yaml`과 사전 등록
`docs/results/e1_preregistration.md`의 sha256을 각 단계의 키 파일과 시트 안내문
메타데이터에 기록한다. 설정을 바꾸면 기존 1단계 키로 2단계를 만들 수 없다.
모델 분석 결과·지표·게시 시각은 선정에 쓰지 않는다.

```bash
# 수집과 test 분할 확정, content_type·category 부분 동결 뒤 실행한다.
# PostgreSQL만 사용한다. POSTGRES_PASSWORD 설정과 Docker·DB 준비가 필요하다.
make e1-stage1
# 기본 폴더를 바꾸려면 data/interim 아래를 지정한다.
uv run python -m beautyads.eval.e1_sampling --out-dir data/interim/e1
```

기본 폴더 `data/interim/e1`에 `e1_stage1_sheet.csv`,
`e1_stage1_codebook.csv`, `e1_stage1_instructions.md`, `e1_stage1_key.json`을
만든다. test 브랜드의 명시적으로 분석 가능한 YouTube·Instagram 소재에서
출처×브랜드 층을 번갈아 뽑는다. 중복 키는 YouTube의
`(source, account, title, caption)`, Instagram의 `(source, account, caption)`이다.
문자열 완전 일치로 묶어 그룹당 시드 무작위 대표 1건을 남기며,
키 필드가 하나라도 비었거나 공백뿐이면 각각 남긴다. DB 행은 변경하지 않는다.
요약에는 출처·브랜드별 프레임 건수, 중복 제거 전후·출처별 제외 건수,
`shortfall`(전체 부족분과 균등 할당 대비 층별 부족분), 산출물 경로가 나온다.
다른 층에서 보충되면 전체 부족분은 0이어도 층별 부족분이 있을 수 있다.

시트를 위에서부터 **건너뛰지 않고** `content_type`·`category`를 함께 라벨링한다.
사람이 `product_creative`로 판정한 건이 50건 이상이면서 100건 이상 라벨링한
첫 행에서 멈춘다. 최대 200건이며, 뒤의 빈 행은 그대로 둬도 된다.
사람 라벨은 `data/interim/e1/e1_stage1_sheet_labeled.csv`에 저장한다.
**키 파일은 라벨링 뒤에만 연다.** CSV에는 영상 주소·제목·캡션과 라벨 칸만
있고, Instagram은 만료되는 media_url 대신 permalink를 쓴다.

```bash
# 나머지 축의 전체 v1 동결 뒤, 1단계 라벨을 저장한 다음 직접 실행한다.
make e1-stage2
uv run python -m beautyads.eval.e1_stage2 \
  --labels data/interim/e1/e1_stage1_sheet_labeled.csv \
  --key data/interim/e1/e1_stage1_key.json --out-dir data/interim/e1
```

2단계는 DB·네트워크에 접속하지 않는다. 두 정지 조건을 처음 만족한 행까지만
사용하고 이후 라벨 건수는 `unused_count`로 보고한다. 그 범위의 사람 제품
라벨을 출처×사람 카테고리로 층화해 50건을 뽑는다. 제품이 부족해도 가능한
건수로 계속하며 종료 코드는 0이다. `e1_stage2_sheet.csv`,
`e1_stage2_codebook.csv`, `e1_stage2_instructions.md`, `e1_stage2_key.json`을
만든다. 2단계 키에만 1단계 사람 라벨과 1단계 키 sha256을 남긴다.
2단계 시트에는 content_type·category·ingredients가 없으며 `claims`는 쉼표로
구분해 여럿 선택한다.

첫 라벨을 `e1_stage2_sheet_labeled.csv`에 저장하고, **7일 뒤** 원래의 빈
`e1_stage2_sheet.csv`를 복사해 같은 항목·순서를 다시 라벨링한다.
첫 라벨과 키를 가린 채 `e1_stage2_sheet_retest.csv`에 저장한다.
기존 산출물은 어느 단계도 덮어쓰지 않는다. 재생성이 필요하면 기존 라벨을
보존할지 검토한 뒤 사용자가 해당 단계의 네 산출물을 직접 치워야 한다.
두 Make 타깃은 `verify`에 포함하지 않는다.

| 이유 코드 | 의미와 조치 |
|---|---|
| `PREREGISTRATION_MISSING` | 사전 등록 파일이 없거나 읽을 수 없다. 등록된 파일을 준비한다. |
| `E1_CONFIG_INVALID` | 설정 파일 누락·키 누락·알 수 없는 키·형식·범위 오류다. 등록한 설정을 확인한다. |
| `E1_SPLIT_FILE_INVALID` | 1단계의 브랜드 분할 파일 존재·형식을 확인한다. |
| `ENV_MISSING:POSTGRES_PASSWORD` | 1단계 실행에 필요한 공백이 아닌 설정을 준비한다. |
| `DOCKER_DOWN` / `POSTGRES_UNREACHABLE` | Docker·DB와 노출 포트(기본 5433, `BEAUTYADS_POSTGRES_PORT`)를 확인한다. |
| `POSTGRES_AUTH_FAILED` / `POSTGRES_CONNECT_FAILED` | 비밀번호·DB 준비 상태를 확인한다. |
| `E1_FRAME_EMPTY` | test 브랜드에 해당하는 분석 가능한 두 출처 소재가 없다. |
| `OUTPUT_NOT_IGNORED` | 출력은 `data/interim` 아래만 허용한다. 경로·심볼릭 링크 이탈을 확인한다. |
| `E1_OUTPUT_EXISTS` | 해당 단계 산출물이 이미 있다. 기존 파일을 덮어쓰지 않고 중단한다. |
| `E1_OUTPUT_WRITE_FAILED` | 출력 폴더의 쓰기 권한·여유 공간을 확인한다. |
| `LABEL_FILE_MISSING` | 1단계 사람 라벨 파일이 없다. `--labels` 경로를 확인한다. |
| `LABEL_FILE_INVALID` | 열·코드북 값·항목 번호·연속 라벨링 순서·키 형식 또는 등록·설정 해시가 잘못됐다. |
| `E1_PRODUCT_SHORTFALL <k>` | 정지 범위의 제품 소재가 목표보다 k건 부족하다. 가능한 제품으로 계속한다. |

오류는 `PREFLIGHT_FAILED <코드>`와 종료 코드 2다. 정상 생성과 제품 부족은 0이다.

## live-slice (P1)

YouTube 소재 수집 → 첫 3초 훅 분석 → PostgreSQL 저장을 확인한다.
OrbStack을 켜고 `.env`에 `YOUTUBE_API_KEY`, `GEMINI_API_KEY`,
`POSTGRES_PASSWORD`를 설정한다. `make db-up`은 Neo4j도 올리므로
`NEO4J_PASSWORD`(8자 이상)도 필요하다. 이 CLI는 Neo4j를 사용하지 않는다.

```bash
make db-up
# 컨테이너 준비까지 수 초 기다린 뒤 실행한다.
make live-slice
```

기본 수집 상한은 1건이다. 아래 모듈 명령에 `--count`로 1~5건을 지정할 수 있다.
환경 점검만 하려면 다음을 실행한다(모델 호출·DB 접속 없음).

```bash
uv run python -m beautyads.pipeline.slice --preflight-only
```

정상 출력은 소재별 JSON 한 줄과 마지막 요약 한 줄이다. 아래는 값 없이 필드
이름만 표시한 출력 형식이다.

```text
event, source, source_id, url, status, hook_type, error_code
event, collected, analyzed, stopped, gemini_total_usd
```

`analyzed`는 분석 상태별 건수이며, 중단 시 남은 작업은 `pending`으로 보존한다.
분석 1건 비용은 약 $0.006 추정이며 실제 비용은 `data/manifest/costs.jsonl`에
기록한다. 기본 Gemini 누적 상한은 $12다. 키·DSN·API 요청 쿼리와 영상 파일
경로는 출력하지 않으며 영상 파일은 다운로드하지 않는다.

점검 실패는 `PREFLIGHT_FAILED <코드>`와 종료 코드 2, 한도 등 실행 중단은
`STOPPED <사유>`와 종료 코드 3, 정상 완료·점검 통과는 종료 코드 0이다.

| 이유 코드 | 조치 |
|---|---|
| `ENV_MISSING:YOUTUBE_API_KEY` | `.env`에 해당 이름의 공백이 아닌 값을 설정한다. |
| `ENV_MISSING:GEMINI_API_KEY` | `.env`에 해당 이름의 공백이 아닌 값을 설정한다. |
| `ENV_MISSING:POSTGRES_PASSWORD` | `.env`에 해당 이름의 공백이 아닌 값을 설정한다. |
| `DOCKER_DOWN` | OrbStack을 켜고 Docker 데몬이 준비될 때까지 기다린다. |
| `POSTGRES_UNREACHABLE` | `make db-up` 뒤 잠시 기다렸다가 다시 시도한다. 기본 포트는 5433이며 `BEAUTYADS_POSTGRES_PORT`를 쓰면 실제 노출 포트와 맞춘다. |
| `COST_CAP:gemini` | 원장 누적액과 비용 상한 설정을 확인한 뒤 예산을 결정한다. |
| `LEDGER_NOT_WRITABLE` | 원장 경로와 부모 디렉터리의 쓰기 권한·여유 공간을 확인한다. |
| `POSTGRES_AUTH_FAILED` | PostgreSQL 비밀번호는 데이터 볼륨을 처음 만들 때만 적용된다. P1은 데이터가 없으니 `.env`의 `POSTGRES_PASSWORD`를 원래 값으로 되돌리거나 볼륨을 직접 삭제한다(삭제 타깃은 만들지 않았다). |
| `POSTGRES_CONNECT_FAILED` | PostgreSQL 비밀번호는 데이터 볼륨을 처음 만들 때만 적용된다. P1은 데이터가 없으니 `.env`의 `POSTGRES_PASSWORD`를 원래 값으로 되돌리거나 볼륨을 직접 삭제한다(삭제 타깃은 만들지 않았다). 컨테이너 상태와 포트도 확인한다. |
| `DAILY_LIMIT` / `RATE_LIMITED` | 한도가 회복된 뒤 다시 실행한다. 대기 작업은 보존된다. |
| `YOUTUBE_KEY_INVALID` / `YOUTUBE_QUOTA` | YouTube 키 설정 또는 할당량을 확인한 뒤 다시 실행한다. |

## live-collect (P2)

YouTube·Instagram의 메타데이터만 수집해 PostgreSQL에 저장한다. 영상 파일을
다운로드하거나 모델을 호출하지 않으므로 모델 비용은 없다. OrbStack을 켜고
`.env`에 `YOUTUBE_API_KEY`, `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID`,
`POSTGRES_PASSWORD`를 설정한다. **`INSTAGRAM_USER_ID`는 호출 주체인 내 Instagram
사용자 ID이며, 사용자가 `.env`에 값을 추가해야 한다.** `make db-up`에는
`NEO4J_PASSWORD`(8자 이상)도 필요하다. 수집기는 Neo4j를 사용하지 않는다.
Instagram 기본 URL은 `https://graph.facebook.com/v21.0`이며 필요할 때만
`BEAUTYADS_INSTAGRAM_BASE_URL`로 바꾼다.

먼저 `--dry-run`으로 호출 수·예상 소요 시간을 확인한다. 이 모드는 키 없이
실행할 수 있으며 HTTP·DB 접속과 Docker 점검을 하지 않는다.

```bash
uv run python -m beautyads.pipeline.collect --dry-run
make db-up
# 컨테이너가 준비된 뒤 사용자가 실행한다(권장: 11-15~16).
make live-collect
```

기본값은 두 출처 모두, 계정당 최대 150건이다. `--max-per-account` 범위는
1~1000이며 YouTube는 영상 수, Instagram은 게시물 수다. 호출 수 추정은
YouTube 채널당 `1 + 2 × ceil(N / 50)`, Instagram 계정당 `ceil(N / 100)`이다.
호출당 시간은 가정(미실측)이며 YouTube 쿼터 사용량은 미확인(Cloud 콘솔에서
확인)이다. Instagram은 호출당 앱 사용량 0.5%를 적용하지만 첫 live에서 과소추정으로 드러났다(13계정·약 26호출에 80% 도달, 어느 지표가 올랐는지는 미확인).
예를 들어 22계정 × 2쪽은 44호출이고 0.5% 가정으로는 약 22%지만 실제로는 그보다 훨씬 빨리 찼다.
사용량 창은 롤링이라 멈춘 뒤 약 1시간 기다렸다가 `--skip-recent-hours`로 이어 받는다.
오류·중단으로 끝난 계정은 저장하지 않으므로 이어 받을 때 다시 수집된다. 수집기는 수집기는 사용량 80% 이상이면 Instagram을 멈춘다.

```bash
uv run python -m beautyads.pipeline.collect --sources youtube --max-per-account 100
# 최근 24시간 안에 수집된 계정을 건너뛴다(기본 0은 끄기).
uv run python -m beautyads.pipeline.collect --skip-recent-hours 24
# 실패한 YouTube handle 또는 Instagram username만 다시 수집한다.
uv run python -m beautyads.pipeline.collect --accounts @torriden,torriden_official
```

계정 하나가 끝날 때마다 업서트하므로 중간에 끊겨도 앞 계정의 결과는 남고,
다시 실행해도 같은 소재가 중복되지 않는다. 계정별 오류는 다음 계정으로
넘어가고, 인증·한도 중단은 해당 출처만 멈춘다. 일시적인 읽기 요청 실패와
HTTP 500·502·503·504는 최대 3회 시도하며 400대는 재시도하지 않는다.

진행 중에는 계정별 JSON 한 줄(`event=account`)에 `source`, `brand`, `account`,
`fetched`, `analyzable_true`, `analyzable_false`, `analyzable_null`, `error`,
`skipped`를 출력한다. 마지막 `event=summary`의 `by_source_brand`는 저장소 전체의
출처·브랜드별 분석 가능 분포이며, `split_analyzable_true`는
`config/brand_split.yaml`에 따른 dev·test 합계다. 분할에 없는 브랜드와 브랜드가
없는 소재는 `unassigned`에 따로 센다. `stopped`는 출처별 중단 이유,
`elapsed_s`는 총 소요 초다. 키·토큰·요청 URL 쿼리·임시 영상 주소는 출력하지 않는다.

| 이유 코드 | 의미와 조치 |
|---|---|
| `ENV_MISSING:YOUTUBE_API_KEY` | YouTube를 선택했다면 해당 키를 설정한다. |
| `ENV_MISSING:INSTAGRAM_ACCESS_TOKEN` / `ENV_MISSING:INSTAGRAM_USER_ID` | Instagram을 선택했다면 토큰과 호출 주체 ID를 설정한다. |
| `ENV_MISSING:POSTGRES_PASSWORD` | PostgreSQL 비밀번호를 설정한다. |
| `DOCKER_DOWN` / `POSTGRES_UNREACHABLE` | OrbStack과 `make db-up`, 노출 포트(기본 5433)를 확인한다. |
| `POSTGRES_AUTH_FAILED` / `POSTGRES_CONNECT_FAILED` | 비밀번호·컨테이너·포트를 확인한다. 비밀번호는 볼륨 최초 생성 시 적용되므로 기존 볼륨이면 원래 값을 확인한다. |
| `YOUTUBE_KEY_INVALID` / `YOUTUBE_QUOTA` | YouTube만 중단한다. 키나 Cloud 콘솔 할당량을 확인한 뒤 재개한다. |
| `INSTAGRAM_TOKEN_INVALID` | Instagram만 중단한다. 토큰을 갱신한 뒤 재개한다. |
| `INSTAGRAM_USAGE_HIGH` / `INSTAGRAM_RATE_LIMITED` | Instagram만 중단한다. 사용량 창이 회복된 뒤 재개한다. |
| `CHANNEL_NOT_FOUND` / `CHANNEL_MISMATCH` / `INSTAGRAM_ACCOUNT_NOT_FOUND` | 해당 계정 설정을 확인한다. 다른 계정은 계속 수집한다. |
| `YOUTUBE_HTTP_*` / `YOUTUBE_REQUEST_FAILED` / `INSTAGRAM_ERROR_*` / `INSTAGRAM_REQUEST_FAILED` / `*_INVALID_RESPONSE` | 해당 계정의 요청·응답 오류다. 나머지 계정 수집 후 재실행한다. |
| `COLLECTION_ACCOUNT_FAILED` | 해당 계정의 수집 또는 저장이 실패했다. 저장소 상태와 계정 설정을 확인해 재실행한다. |
| `SPLIT_VOLUME_INSUFFICIENT` | 전체 저장소 기준 `volume_violations`를 확인한다. 자동 재분할은 하지 않는다. |

점검 실패는 `PREFLIGHT_FAILED <코드>`와 종료 코드 2, 출처 중단이 있으면
종료 코드 3, 그 밖에는 0이다. 수집량 미달만 있으면 종료 코드는 0이다.

**live 순서: `make live-collect` → 수집량 확인(`SPLIT_VOLUME_INSUFFICIENT` 유무)
→ 필요하면 라벨링 전에 1회 재분할 → 그 뒤에 `make live-pilot`.**
수집량이 모자라면 추가 수집을 검토하고, 라벨링 시작 전에 한해 이유를 적어
다음 명령으로 1회 재분할할 수 있다.

```bash
uv run python -m beautyads.sources.split --resplit --reason "수집량 확인 후 재분할 사유" --path config/brand_split.yaml
```

분할이 바뀌면 시범 20건도 바뀌므로 `make live-pilot`은 분할 확정 뒤에 실행한다
(P2 step 13에서 제공).

## live-pilot (P2)

**live 순서: `make live-collect` → 수집량 확인 → 필요 시 라벨링 전에 1회
재분할 → 그 뒤에 `make live-pilot`.** 수집을 완료하고
`config/brand_split.yaml`의 dev·test 수집량 기준을 충족해야 한다.
시범 실행기는 저장소의 `collection_stats()`로 이를 다시 검사하며 우회 옵션은 없다.
분할이 바뀌면 시범 20건도 바뀌므로 분할을 확정한 뒤 시작한다.

OrbStack을 켜고 `.env`에 `GEMINI_API_KEY`, `POSTGRES_PASSWORD`,
`INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID`를 설정한다. 시작 점검에서는
대상 출처를 아직 모르므로 Instagram 두 설정도 확인한다. `make db-up`에는
`NEO4J_PASSWORD`(8자 이상)도 필요하다. 시범은 PostgreSQL만 사용한다.

먼저 `--dry-run`으로 계획 호출 수와 영상 입력 토큰 추정을 확인한다.
이 모드는 키 없이 실행하며 Docker 점검·네트워크 호출·DB 접속·모델 호출을 하지 않는다.
금액은 추정하지 않는다. 비용은 원장에 기록되며 시범 뒤 `cost-recalc`가 계산한다.

```bash
uv run python -m beautyads.eval.pilot_run --dry-run
make db-up
# 컨테이너가 준비되고 수집량·분할을 확인한 뒤 사용자가 실행한다.
make live-pilot
# 개수·선정 seed·구간 상한·출력 폴더를 바꾸는 예
uv run python -m beautyads.eval.pilot_run --n 20 --seed 20261112 --content-type-window-s 60 --full-window-s 60 --out-dir data/interim/pilot
```

기본값은 dev 브랜드의 분석 가능한 YouTube·Instagram 소재 20건,
seed `20261112`, 콘텐츠 유형·전체 분석 구간 각각 최대 60초다. `--n`은
1~40이며 지표나 분석 결과를 선정에 쓰지 않는다. 같은 선정 소재를
`thinking_level=minimal` → `default` 순으로 분석한다. **두 실행이므로
단일 실행보다 계획 호출 수가 두 배다.** 제품 소재는 콘텐츠 유형·첫 3초 훅·전체
세 축을 분석하고 스키마 검증 실패 시 축당 한 번 재요청한다. `--dry-run`의 입력
추정은 영상만 계산하며 프롬프트·캡션·출력·thought 토큰은 제외한다.
실제 Gemini 비용에는 thought 토큰도 포함되므로 원장으로 확인한다.
누적 상한 기본값은 Gemini $12, OpenAI $10, Anthropic $8이다.
시범은 Gemini를 호출하며 첫 실행이 한도로 중단되면 두 번째 실행을 시작하지 않는다.

**재시도와 코드북 재생성(시트·키는 건드리지 않는다)**

```bash
# 코드북·안내만 다시 쓴다(API·DB·키 파일 접근 없음). 값 정의·우선순위는 docs/TAXONOMY.md에서 읽는다.
uv run python -m beautyads.eval.pilot_docs
# default 실행에서 Instagram 주소 재조회가 중단돼(MEDIA_REFRESH_STOPPED) 또는 못 찾아(MEDIA_URL_MISSING)
# 실패한 content_type만 다시 분석한다. 시트와 pilot_key.json은 그대로 두고 결과를
# pilot_key_supplement.json(같은 item_id)에 쓴다. 완료된 작업은 건드리지 않는다.
uv run python -m beautyads.eval.pilot_run --retry-missing
```

Instagram 주소 재조회가 사용량 한도로 도중에 멈추면 못 찾은 소재는
`MEDIA_REFRESH_STOPPED`(재시도 대상)로 기록하고, 재조회가 끝까지 돌았는데도 없으면
`MEDIA_URL_MISSING`으로 확정한다. 키가 사라진 게시물(`MEDIA_URL_GONE`)과는 다르다.
`--retry-missing`은 호출 전 점검과 비용 상한 검사를 시범과 똑같이 한다.
재시도 출력에는 `REFRESH_SCAN` 줄이 계정마다 붙는다. 스캔한 쪽수(`pages`), 못 찾은 게시물 수(`remaining`),
마지막 앱 사용량 세 지표(`usage`), 중단 코드(`stopped`)이며, 사용량이 높아 멈춘 시점을 보여 준다.

출력은 실행 태그별 상태 분포, 이번 실행의 `gemini_cost_usd`, 분할 파일의
`split_sha256`, 네 파일의 경로다. 기본 출력 폴더 `data/interim/pilot` 아래에
`pilot_sheet.csv`, `pilot_codebook.csv`, `pilot_instructions.md`, `pilot_key.json`을 쓴다.
`--out-dir`은 `data/interim` 아래만 허용하고 경로 이탈·심볼릭 링크 이탈도 거부한다.
시범 명령은 키 파일을 읽거나 모델 라벨을 출력하지 않는다.

11-17~18에는 **시트의 영상 링크·제목·캡션으로 먼저 라벨링**하고,
값 선택과 비제품 소재의 빈칸 규칙은 코드북·`pilot_instructions.md`를 참고한다.
**키 파일(pilot_key.json)은 라벨링을 마치기 전에 열지 마세요.**
키 파일은 라벨링 뒤에 열어 두 실행 결과와 비교한다.

| 이유 코드 | 의미와 조치 |
|---|---|
| `ENV_MISSING:GEMINI_API_KEY` / `ENV_MISSING:POSTGRES_PASSWORD` | 해당 이름의 공백이 아닌 값을 설정한다. |
| `ENV_MISSING:INSTAGRAM_ACCESS_TOKEN` / `ENV_MISSING:INSTAGRAM_USER_ID` | 토큰과 호출 주체 ID를 설정한다. |
| `DOCKER_DOWN` / `POSTGRES_UNREACHABLE` | OrbStack·`make db-up`과 포트(기본 5433, `BEAUTYADS_POSTGRES_PORT`)를 확인한다. |
| `POSTGRES_AUTH_FAILED` / `POSTGRES_CONNECT_FAILED` | 비밀번호·컨테이너·포트를 확인한다. 비밀번호는 볼륨 최초 생성 시 적용되므로 기존 볼륨의 원래 값을 확인한다. |
| `COST_CAP:gemini` | 원장 누적액과 예산을 확인한다. 상한에 도달하면 호출하지 않는다. |
| `LEDGER_NOT_WRITABLE` | 원장과 부모 디렉터리의 쓰기 권한·여유 공간을 확인한다. |
| `PILOT_SPLIT_FILE_INVALID` | `config/brand_split.yaml`의 존재·형식을 확인한다. |
| `PILOT_SPLIT_NOT_VERIFIED` | 수집량 기준 미달이다. 수집 결과를 확인하고 추가 수집 또는 허용된 1회 재분할 후 실행한다. |
| `PILOT_NO_COLLECTION` | dev에 분석 가능한 YouTube·Instagram 소재가 없다. 수집 결과를 확인한다. |
| `PILOT_SHORTFALL <k>` | 목표보다 k건 부족하다. 가능한 소재로 계속 실행한다. |
| `OUTPUT_NOT_IGNORED` | 출력 폴더를 `data/interim` 아래로 지정한다. |
| `DAILY_LIMIT` / `RATE_LIMITED` | 한도 회복 뒤 재실행한다. 남은 작업은 pending으로 유지한다. |
| `INVALID_SETTING:<이름>` | 해당 설정의 형식·범위를 확인한다. 값은 출력하지 않는다. |

점검·수집량·옵션 오류는 종료 코드 2, 실행 중 한도 중단은 3,
정상 완료와 `--dry-run`은 0이다. 분석 도중 소재별 실패나 한도로 일부 결과가 비어도
선정 소재의 블라인드 시트는 생성하고 누락 결과는 키 파일에 빈 값으로 남긴다.

## pilot-compare (P3)

**키 파일은 라벨링을 마친 뒤에만 연다(시범 라벨링은 끝났다).**
사람 라벨의 열·값을 먼저 검사한 뒤 모델 키와 같은 폴더의
`pilot_key_supplement.json`(있을 때만)을 읽는다. 보충 결과는 같은 항목의
해당 실행만 덮어쓴다. 파일을 수정하거나 DB·네트워크·모델을 호출하지 않는다.

```bash
make pilot-compare
# 기본 사람 라벨: data/interim/pilot/pilot_sheet_labeled.csv
# 기본 모델 키: data/interim/pilot/pilot_key.json
uv run python -m beautyads.eval.pilot_compare --labels <라벨.csv> --key <키.json>
```

한 실행이라도 콘텐츠 유형 작업이 완료되지 않았거나, 모델이 제품으로 본
항목의 훅·전체 작업이 미완료이면 두 실행·모든 축에서 함께 제외한다.
제외 목록에는 항목 번호·실행 태그·작업·이유 코드만 표시한다.
`content_type`은 비제외 항목 전체의 사람×모델 혼동 행렬과 참고 일치율을
낸다. 나머지 축은 사람과 해당 실행이 모두 제품으로 본 교집합에서 비교한다.
두 모델끼리 비교할 때는 사람·두 실행이 모두 제품인 항목만 쓴다.

표와 마지막 JSON 한 줄에 축·실행별 분모(`n`)·교집합 크기·일치율을 표시한다.
빈 불리언 라벨은 해당 축의 분모에서 빠지며 `claims` 빈칸은 빈 집합이다.
소구점은 순서와 중복을 무시하고 집합이 정확히 같을 때 일치로 센다.
교집합이나 유효 값 쌍이 비면 해당 일치율은 비워 두고 다른 축은 계속 계산한다.
`has_cta`·`has_hook_segment`에는 `note: 정의 미확정, 참고용`을 붙인다.
라벨 원문·제목·캡션은 출력하지 않는다. 혼동 행렬의 행·열에는 코드북 값만 쓴다.

| 이유 코드 | 의미와 조치 |
|---|---|
| `LABEL_FILE_MISSING` | 사람 라벨 파일이 없다. `--labels` 경로를 확인한다. 키는 읽지 않는다. |
| `LABEL_FILE_INVALID` | 열·값·항목 번호가 잘못됐다. 형식·값 오류일 때는 키를 읽지 않으며, 키에 없는 항목 번호는 키를 읽은 뒤 검사한다. |
| `PILOT_KEY_MISSING` | 모델 키가 없다. `--key` 경로를 확인한다. |
| `PILOT_KEY_INVALID` | 모델 키 또는 보충 파일의 형식을 확인한다. |
| `COMPARE_EMPTY_SET:<축>` | 해당 비교에 유효한 값 쌍이 없다. 0%로 해석하지 않는다. 다른 축의 결과는 함께 출력한다. |

종료 코드는 정상 비교 0, 입력 문제 2, 빈 비교가 하나라도 있으면 3이다.
`pilot-compare`는 수동 타깃이며 `make verify`에는 포함하지 않는다.

## cost-recalc (P3)

Gemini 비용 원장을 읽어 시범 `minimal`·`default` 실행의 비용과 전체 분석
시나리오를 보고한다. 네트워크·DB·모델·`.env`를 사용하지 않으며, 원장·설정·
`docs/COST_ESTIMATE.md`를 수정하지 않는다. 기본 원장 경로와 현재 상한은
`settings`에서 읽는다(기본 `data/manifest/costs.jsonl`, Gemini $12).
환경 변수의 설정값은 적용하지만 `.env` 파일은 읽지 않는다.

```bash
# --items는 필수이므로 Make 타깃에 CLI 인수를 전달한다.
make cost-recalc ARGS='--items 1500'
# 모듈을 직접 실행할 수도 있다.
uv run python -m beautyads.eval.cost_recalc --items 1500
uv run python -m beautyads.eval.cost_recalc --ledger <합성또는실제원장.jsonl> \
  --items 1500 --pilot-items 20 --hook-input-max 1000 \
  --product-shares 0.25,0.5,0.75 --candidate-cap 14
```

`make cost-recalc`는 인수 없이 실행하면 `--items` 누락으로 종료 코드 2를
반환한다. 소재 수를 지정할 때는 `ARGS` 또는 위의 직접 실행 명령을 사용한다.
수동 타깃이며 `make verify`에는 포함하지 않는다.

`pilot-<태그>-retry`는 같은 태그에 합산하고 다른 공급사는 제외한다.
기타 purpose는 합계만 별도로 표시한다. 태그별 호출 수·비용 합계와 호출당
입력·출력·thought·cached 토큰 및 비용의 평균·p50·p90·최댓값을 출력한다.
백분위는 정렬 후 `(n-1)×q` 위치에서 선형 보간한다.
`response_cost` 외 항목 수를 표시하고 있으면 비용이 추정치임을 알린다.
원장 비용에는 이미 thought 비용이 포함되므로 토큰 비용을 다시 더하지 않는다.

원장의 시범 purpose에는 호출 종류가 없다. 입력 토큰이 `--hook-input-max`
이하이면 **짧은 호출(hook으로 보임)**, 나머지는 **구간 호출(content_type·full로
보임)**이라는 가정으로 나눈다. 기본 경계 1000토큰은 시범 관찰에 맞춘 가정이며
종류별 측정값이 아니다. `p=(호출 수−시범 항목 수)/2`와 짧은 호출 수가 다르면
`COST_KIND_SPLIT_MISMATCH`와 함께 분리를 신뢰할 수 없다고 표시하고 계산은
계속한다. 재시도가 포함되므로 p와 시범 제품 비율은 왜곡될 수 있는 참고값이다.

전체 소재 수 `N`은 content_type 호출 수의 상한이다. 제품 비율 `s`는 기본
0.25·0.5·0.75의 **가정(미실측)**이며 시범의 제품 비율을 적용하지 않는다.
견적은 `N×c_구간 + N×s×(c_구간+c_짧음)`이다. content_type과 full의 평균 비용이
같다는 가정이며, 높은 쪽 열은 구간 평균만 p90으로 대체하고 짧은 호출은 평균을
유지한다. 이 열은 총비용 분포의 통계적 p90이 아니다. 필요한 묶음이 비면
0으로 간주하지 않고 계산 불가로 표시한다.

현재 누적+각 견적이 현재 상한과 후보 상한(기본 $14) 미만인지 출력한다.
래퍼와 동일하게 상한에 정확히 닿으면 밖으로 표시한다. default/minimal의
호출당·시범 소재당 비용 비율도 보고하며 소재당 비율을 전체 견적에 쓰지 않는다.
상한과 `thinking_level`은 이 결과를 보고 사용자가 결정한다.

첫 배치 이후 같은 CLI를 다시 실행하면 `analyze-target-content_type`·`-hook`·
`-full`의 종류별 호출·토큰·비용을 측정값으로 따로 표시한다(없으면
"종류별 측정 없음"). 세 종류가 모두 있으면 각각의 측정 단가로 별도 시나리오를
계산한다. 이때도 제품 비율은 가정이며 원장에 서로 다른 실행 설정이 섞였을 수
있다. 종류별 측정값은 기타 합계에도 포함되므로 합계를 중복해서 더하지 않는다.

표 뒤에 JSON 한 줄, 마지막 줄에 작은 표본의 한계와 첫 `analyze-target`에서
정확한 종류별 비용을 측정한다는 안내를 출력한다. JSON 숫자의 `basis`는 해당
객체와 하위 항목에 적용되고 하위 `basis`가 있으면 그 표시를 따른다.

| 이유 코드 | 의미 |
|---|---|
| `LEDGER_UNREADABLE` | 원장이 없거나 읽을 수 없거나 깨진 항목이 있다. 파싱 못 한 줄 수를 보고하며 견적을 내지 않는다. |
| `COST_INPUT_INVALID` | 소재 수·시범 항목 수가 양수가 아니거나 비율이 [0,1] 밖인 등 입력값이 잘못됐다. |
| `COST_NO_PILOT_ENTRIES` | minimal·default 중 해당 태그의 Gemini 시범 호출이 없다. 누락 태그를 표시한다. |
| `COST_KIND_SPLIT_MISMATCH:<태그>` | 호출 수로 역산한 제품 소재 수와 짧은 호출 수가 맞지 않는다. 경고이며 견적은 계속 낸다. |

종료 코드는 성공 0, 입력 문제 2(`--items` 누락 포함), 시범 태그 누락 3이다.

## live-analyze (P3)

수집된 소재를 전체 v1 분류로 분석한다. 먼저 OrbStack을 켜고 `make db-up`으로
DB를 준비하고 수집을 마친다. `.env`에는 `GEMINI_API_KEY`·`POSTGRES_PASSWORD`,
Instagram을 포함하면 `INSTAGRAM_ACCESS_TOKEN`·`INSTAGRAM_USER_ID`가 필요하다.
TikTok을 포함할 때만 `TIKTOK_CLIENT_KEY`·`TIKTOK_CLIENT_SECRET`도 점검한다.
`docs/results/e1_preregistration.md`에 현재 분석 모델 ID·프롬프트 버전 세 값과
`전체 v1 동결: YYYY-MM-DD` 형식의 실제 날짜를 기록해야 시작한다.
사전 등록 갱신은 분류 v1 승인 뒤 분석 전에 완료한다.

```bash
# DB·네트워크·모델 없이 계획만 확인
make live-analyze ARGS='--dry-run --items 1500'
# E1 시트를 만든 뒤 표본을 먼저 분석한다(두 단계 키의 합집합).
make live-analyze ARGS='--only-keys-file data/interim/e1/e1_stage1_key.json --only-keys-file data/interim/e1/e1_stage2_key.json'
# 이어서 옵션 없이 전체를 돌린다. 이미 done인 작업은 다시 호출하지 않는다.
make live-analyze
# 사용량 회복 뒤 재시도 가능한 실패만 다시 처리
make live-analyze ARGS='--retry-failed'
make cost-recalc ARGS='--items 1500'
```

키 경로는 실제 E1 시트 출력 폴더에 맞춘다. E1 시트를 만든 뒤
`--only-keys-file`로 표본을 먼저 분석하고, 이어서 옵션 없이 전체를 돌린다.
사용자가 2단계 라벨링을 하는 동안 E1 모델 결과를 먼저 확보할 수 있다.
키 파일에서는 `source`·`source_id`만 사용하고 키 값·브랜드·URL·사람 라벨은
출력하지 않는다. 여러 키 파일은 합집합이며 `--sources`와는 교집합이다.
`--brands`·`--limit`와 함께 지정할 수 없다. DB에 없거나 분석 불가능한 키는
`KEY_NOT_ANALYZABLE <건수>`로 보고하고 건너뛴다.

기본 출처는 `youtube,instagram`이며 `--sources tiktok` 또는
`--sources youtube,instagram,tiktok`으로 TikTok을 포함할 수 있다.
`--sources youtube`로 YouTube만, `--brands 브랜드1,브랜드2`로 브랜드를,
`--limit N`으로 대상 소재 수를 제한할 수 있다. `--batch-size`는 기본 100(1~500),
`--concurrency`는 기본 1(1~4), `--thinking-level`은 기본 `minimal`이다.
`--content-type-window-s`·`--full-window-s`는 각각 기본 60초이고 훅은 3초다.
`--items N`은 `--dry-run`에서만 사용하며 기본 호출 수 N~3N을 계산한다
(스키마 재요청·전송 재시도 제외). 비용은 원장에 기록되며 `cost-recalc` 결과를 따른다.
상한·thinking 수준 변경은 비용 결과를 확인한 사용자 결정에 따른다.

TikTok은 분석 직전에 브랜드별로 한 번 재조회해 영상 주소를 얻고 기존
Instagram 플랜과 합성한다. `--tiktok-max-pages` 기본값은 **20**이며 1 이상이어야
한다. **수집 때 쓴 `--max-pages`보다 작게 주지 말 것**(이번 수집은 20쪽).
재조회 결과의 중단 사유를 그대로 사용하며 쪽 수 부족을 별도로 추정하지 않는다.
중단돼 못 찾은 소재는 `missing`으로 확정하지 않고 `MEDIA_REFRESH_STOPPED`로
기록한다. 다운로드에서 주소를 사용할 수 없으면 해당 ID 하나로 1회 재조회한다.
토큰의 7200초 만료·재발급은 `TokenProvider`가 처리한다. 영상 주소·토큰은
DB·로그·출력에 남기지 않고 영상은 메모리 처리·업로드 후 분석이 끝나면 삭제한다.
TikTok은 그래프·에이전트 데이터용이며 E1 정확도 표본에는 포함하지 않는다.

비용을 제한하려면 `--per-brand-limit N`(1~500)을 쓴다. 출처·브랜드 필터를 적용한
`analyzable == true` 소재에서 **시드 20261114, 분석 가능 소재를 브랜드별로
`source_id` 정렬 후 섞어 앞에서 N건(최신순 아님)**을 고른다. 브랜드마다
`random.Random(f"{seed}:{brand}")`로 독립적으로 섞으며 브랜드가 없으면 한 묶음이다.
대상이 N건 이하면 전부 선택한다. 같은 소재 집합·시드에서는 입력 순서와 무관하게
같은 표본이고, N을 늘리면 기존 표본이 앞부분에 포함된다. 선택한 소재만 대기열에
넣고 처리하므로 같은 옵션으로 재개해도 이미 `done`인 작업은 다시 호출하지 않는다.
`--brands`와 함께 쓸 수 있지만 `--only-keys-file`·`--limit`와 함께 쓰면
`PER_BRAND_CONFLICT`(종료 코드 2)다.

```bash
make live-analyze ARGS='--sources tiktok --per-brand-limit 40 --tiktok-max-pages 20'
make live-analyze ARGS='--sources tiktok --per-brand-limit 40 --dry-run'
```

결과 문서에는 위 시드·N·선택 규칙과 요약 `sampling.selected_total`을 옮긴다.
`sampling`에는 시드·N·선택 합계·규칙만 출력하며 브랜드별 선택 건수는 출력하지
않는다. `--dry-run`도 시드·N·규칙을 표시하되 DB를 읽지 않으므로 선택 합계는
미계산(`null`)이다. 실제 선택 합계는 실행 마지막 요약에서 확인한다.

작업은 `content_type@v1`·`hook@v1`·`full@v1`만 읽고 쓴다. 재실행하면
DB의 `pending` 작업부터 이어가며 시범 `@minimal`·`@default`는 건드리지 않는다.
`--retry-failed`는 `RETRYABLE_ERROR_CODES`에 있는 `failed`만 실행 시작에 한 번
되돌린다(`MEDIA_REFRESH_STOPPED` 포함). `MEDIA_URL_MISSING`·`INVALID_OUTPUT`·
`MEDIA_URL_GONE`이나 `held` 작업은 되돌리지 않는다.

Instagram은 배치 분석 직전에 계정을 재조회하고 서명 URL로 받은 영상은
메모리에서만 처리하며 업로드한 파일은 분석 뒤 삭제한다. 앱 사용량 중단은
부재로 확정하지 않고 못 찾은 소재를 `MEDIA_REFRESH_STOPPED`로 기록한다.
중단 뒤 자동 반복하지 않으므로 **시간을 두고 `--retry-failed`로 다시 실행한다**.
계정별 재조회 횟수와 마지막 앱 사용량은 마지막 요약에서 확인한다.
같은 계정의 소재가 같은 배치에 몰리는 순서는 보장하지 않는다.
일일 한도·비용 상한에 닿으면 남은 작업을 `pending`으로 보존한다.

매 배치 JSON 한 줄(`event: batch`)과 마지막 `summary`에 상태 분포·오류 코드·
대기 건수·비용·경과 시간을 출력한다. 출처·category별 완료 수는
`content_type@v1`의 `done` 기준이다. 실패율은 `(failed + held) / (done + failed + held)`로
전체 축의 작업을 세며, 처리된 작업이 없으면 null이다. `full@v1`의 enum 축별
`other` 비율은 값이 있는 완료 작업을 분모로 하고, `claims`는 목록에 `other`가
포함된 작업을 한 번 센다. 분모가 없으면 null이다.

원장의 `purpose`는 `analyze-target-content_type`·`analyze-target-hook`·
`analyze-target-full`로 나눈다. 마지막 요약의 `cost_by_axis`에는 이번 실행 시작
이후 추가된 해당 Gemini 항목만 집계해 종류별 호출 수·입력/출력/thought/cached
토큰 평균·비용 합계·`response_cost`가 아닌 항목 수를 표시한다.
**첫 배치 뒤 요약의 종류별 비용으로 전체 견적을 다시 계산한다**(`make cost-recalc`).
비용 상한은 누적 원장 전체에 적용한다.

| 이유 코드 | 의미와 조치 |
|---|---|
| `ENV_MISSING:<이름>` | 필요한 `.env` 키 이름을 확인한다. 값은 출력하지 않는다. |
| `DOCKER_DOWN` | OrbStack을 켠다. |
| `POSTGRES_UNREACHABLE` | `make db-up`과 PostgreSQL 포트(기본 5433)를 확인한다. |
| `POSTGRES_AUTH_FAILED` / `POSTGRES_CONNECT_FAILED` | DB 인증·연결 설정을 확인한다. 기존 볼륨의 비밀번호는 `.env` 변경만으로 바뀌지 않는다. |
| `LEDGER_NOT_WRITABLE` | 비용 원장과 부모 폴더의 쓰기 권한을 확인한다. |
| `COST_CAP:gemini` | 누적 상한에 닿았다. 비용 결과를 보고 사용자가 상한을 결정한다. |
| `PREREGISTRATION_NOT_UPDATED` | 사전 등록 파일의 모델·프롬프트 버전·전체 v1 동결 날짜를 갱신한다. 우회 옵션은 없다. |
| `ONLY_KEYS_CONFLICT` | 키 파일 옵션에서 `--brands`·`--limit`를 뺀다. |
| `PER_BRAND_CONFLICT` | `--per-brand-limit`에서 `--only-keys-file`·`--limit`를 뺀다. |
| `ONLY_KEYS_FILE_MISSING` | 키 파일 경로를 확인한다. |
| `ONLY_KEYS_FILE_INVALID` | JSON의 items 매핑·알려진 source·비어 있지 않은 source_id 문자열을 확인한다. |
| `KEY_NOT_ANALYZABLE <건수>` | DB에 없거나 분석 불가능한 키 수다. 나머지는 계속 처리한다. |
| `MEDIA_REFRESH_STOPPED` / `INSTAGRAM_USAGE_HIGH` | 자동 반복하지 않는다. 시간을 두고 `--retry-failed`로 재실행한다. |
| `DAILY_LIMIT` / `RATE_LIMITED` | 한도 회복 뒤 재실행한다. |
| `INVALID_SETTING:<이름>` | 설정 형식과 범위를 확인한다. |

점검 실패는 `PREFLIGHT_FAILED <코드>`와 종료 코드 2, 중단은 `STOPPED <사유>`와
종료 코드 3이다. 대기열 소진·처리 0건으로 반복 종료·계획 출력은 종료 코드 0이다.
`live-analyze`는 사용자 수동 실행용이며 `make verify`에는 포함하지 않는다.

## live-tiktok (P3)

TikTok Commercial Content API의 EU 게재 광고를 브랜드별로 수집해 PostgreSQL에
저장한다. OrbStack을 켜고 `make db-up`으로 DB를 준비한다. `.env`에는
`TIKTOK_CLIENT_KEY`·`TIKTOK_CLIENT_SECRET`·`POSTGRES_PASSWORD`가 필요하다.
TikTok 키는 승인된 연구용 클라이언트의 **My research**에서 확인한다.
`config/retailers.yaml`은 사용자 확인을 기다리는 판매처 시드 초안이므로
실제 실행 전에 목록을 확인한다. 실행기가 시드를 수정하지는 않는다.

```bash
# 키·네트워크·DB 없이 광고 조회 호출 수 범위만 확인
make live-tiktok ARGS='--dry-run'
# 어댑터의 첫 실서비스 실행은 반드시 작게 시작한다.
make live-tiktok ARGS='--brands mixsoon --max-pages 1'
# 모듈 직접 실행 및 여러 브랜드 선택
uv run python -m beautyads.pipeline.collect_tiktok --brands mixsoon,dalba --max-pages 2
```

`--brands` 기본값은 `config/sources.yaml`의 전체 브랜드다. `--max-pages`는
브랜드당 쪽 수 상한으로 기본 **1**, 허용 범위는 1~50이다. 한 쪽은 최대 10건이며
`has_more == false`이면 상한 전에 종료한다. `--dry-run`은 의존성 생성과 환경·DB
접속 점검도 생략하고 `ESTIMATE` 한 줄을 출력한다. 광고 조회 호출 수는 선택한
브랜드 수~브랜드 수×쪽 수 범위이며, 토큰 발급·어댑터의 토큰 갱신 재조회는 별도다.
호출당 시간은 가정(미실측)이다.

브랜드가 끝날 때마다 JSON 한 줄(`event: brand`)에 브랜드·고유 수집 수(`fetched`)·
집행 주체 분포(`executor`)·오류(`error`)·저장 수(`stored`)를 출력한다. 분류기의
`brand_direct`·`retailer`·`unknown` 값을 그대로 쓰며 숫자 이름·목록 밖은
`unknown`(불명)이다. 마지막 `summary`에는 브랜드별 수집·저장 수, 집행 주체 분포,
오류·중단 코드, 판매처 시드 경로·중복 제거한 항목 수, 총 수집 소요 초를 표시한다.
수집 수와 집행 주체 분포에는 실패한 브랜드에서 받은 부분 결과도 포함되지만,
그 브랜드는 **한 건도 저장하지 않는다**. 브랜드 간에도 같은 `ad.id`는 실행당
한 번만 저장하므로 수집 수와 저장 수는 다를 수 있다. 재실행하면 처음 쪽부터
받고 기존 저장소의 upsert로 갱신한다. 중단 전에 완료한 브랜드는 보존한다.

토큰 유효 기간은 **7200초**이고 리프레시 토큰은 없다. 기존 `TokenProvider`가
만료 직전에 재발급하며 어댑터는 만료된 토큰 응답에 한 번만 갱신 조회한다.
실행기는 인증 오류·400대 응답을 추가 재시도하지 않는다. 토큰 발급 실패,
잘못된 토큰·요청, 429는 다음 브랜드를 호출하지 않고 멈춘다.
영상 주소는 저장·출력하지 않는다. 서명 URL은 만료되므로 분석 직전
`tiktok-plans`가 재조회한다. 키·토큰·인증 헤더·응답 진단 본문도 출력하지 않는다.

**TikTok은 E1 표본에서 제외된다(그래프·에이전트 데이터).** 모델 정확도는
YouTube·Instagram 소재로만 측정하며 TikTok 소재 분석 정확도는 미측정이다.
`live-tiktok`은 사용자가 직접 실행하는 별도 타깃이며 `make verify`에 포함되지 않는다.

| 이유 코드 | 의미와 조치 |
|---|---|
| `ENV_MISSING:TIKTOK_CLIENT_KEY` / `ENV_MISSING:TIKTOK_CLIENT_SECRET` / `ENV_MISSING:POSTGRES_PASSWORD` | 해당 설정에 공백이 아닌 값을 준비한다. 값은 출력하지 않는다. |
| `DOCKER_DOWN` | OrbStack을 켠다. |
| `POSTGRES_UNREACHABLE` | `make db-up`과 포트(`BEAUTYADS_POSTGRES_PORT`, 기본 5433)를 확인한다. |
| `POSTGRES_AUTH_FAILED` / `POSTGRES_CONNECT_FAILED` | DB 인증·연결 설정을 확인한다. DSN은 출력하지 않는다. |
| `TIKTOK_CONFIG_UNREADABLE` / `TIKTOK_CONFIG_INVALID` | `config/sources.yaml`의 읽기 권한·TikTok 설정 형식을 확인한다. |
| `RETAILERS_CONFIG_UNREADABLE` / `RETAILERS_CONFIG_INVALID` | 판매처 시드 경로·문자열 목록 형식을 확인한다. |
| `TIKTOK_BRANDS_INVALID` | `--brands`를 설정에 등록된 브랜드 이름으로 지정한다. |
| `TIKTOK_TOKEN_INVALID` | My research의 승인된 연구용 자격 증명을 확인한 뒤 재실행한다. |
| `TIKTOK_INVALID_PARAMS` | 국가·검색·날짜 설정을 확인한다. 자동 반복하지 않는다. |
| `TIKTOK_HTTP_429` | 한도 회복 뒤 재실행한다. 호출 한도는 아직 미확인이다. |
| `TIKTOK_HTTP_<상태>` / `TIKTOK_REQUEST_FAILED` / `TIKTOK_INVALID_RESPONSE` | 해당 브랜드는 저장하지 않는다. 서비스 상태·응답 계약을 확인한다. 토큰 발급 단계에서 발생하면 전체를 중단한다. |
| `COLLECTION_BRAND_FAILED` | 예상하지 못한 브랜드 처리 실패다. 진단 원문은 출력하지 않으며 해당 브랜드를 저장하지 않는다. |

점검 실패는 `PREFLIGHT_FAILED <코드>`와 종료 코드 2, 중단 또는 브랜드 오류는
종료 코드 3, 성공과 `--dry-run`은 0이다. 옵션 오류도 2다.

## e1-score (P3)

사람 라벨링을 모두 마친 뒤 **사용자가 직접** 실행한다. 기본 입력 폴더는
`data/interim/e1`이며 다음 다섯 파일이 필요하다.

| 입력 | 파일 |
|---|---|
| 1단계 사람 라벨 | `e1_stage1_sheet_labeled.csv` |
| 1단계 키 | `e1_stage1_key.json` |
| 2단계 첫 라벨 | `e1_stage2_sheet_labeled.csv` |
| 2단계 재검사 라벨 | `e1_stage2_sheet_retest.csv` |
| 2단계 키 | `e1_stage2_key.json` |

2단계 첫 라벨을 끝낸 **7일 뒤**, 원래의 빈 2단계 시트를 복사하고 첫 라벨과
키를 가린 채 같은 항목·순서를 다시 라벨링해 재검사 파일에 저장한다.
세 라벨 파일 중 하나라도 없으면 어떤 파일도 열거나 DB에 접속하지 않는다.
세 CSV의 열·값 검사를 모두 마친 다음 키와 등록 규칙을 검사하고,
`POSTGRES_PASSWORD`·Docker·PostgreSQL(기본 포트 5433)을 점검한다.
저장소의 `content_type@v1`·`hook@v1`·`full@v1` 작업만 읽으며 파일·DB를 수정하거나
모델을 호출하지 않는다. `make verify`에는 포함되지 않는다.

```bash
make e1-score
# 경로가 다를 때 (나머지 기본 경로도 개별 옵션으로 바꿀 수 있다)
make e1-score ARGS='--stage1-labels <1단계.csv> --stage2-labels <첫라벨.csv> --retest-labels <재검사.csv> --stage1-key <1단계.json> --stage2-key <2단계.json>'
```

1단계 범위는 `e1_stage2.stop_point`와 등록된 `config/e1_sampling.yaml`을 그대로
사용한다. 정지 범위 밖 라벨은 사용하지 않는다. 현재 §7 정정의
`use_all_labeled: true`에서는 상한까지 라벨링한 전부가 정지 범위다.
콘텐츠 유형 재현율은 사람이 제품으로 본 소재 전체가 분모다. `done`인 콘텐츠
유형 결과가 없으면 `model_missing`으로 혼동 행렬과 건수를 따로 내며 분모에 남긴다.
훅·전체 작업 실패는 축별 비교에서 항목 전체를 제외하되 콘텐츠 유형 재현율을
바꾸지 않는다. 축별 일치율·κ·합격 판정은 §5의 사람·모델 제품 교집합에서만
계산하고 축마다 `n`, 사람 제품 수, 교집합 크기, 커버리지(`n ÷ 사람 제품 수`),
분석 제외 건수를 표시한다. 모델 category가 `other`이면 category 비교에는
포함하고 훅·전체 축에서만 분석 제외로 센다. 빈 불리언은 해당 축에서만 빠진다.

재검사는 모델과 무관하게 2단계 시트 전체의 유효한 첫 라벨·재라벨 쌍으로
계산한다. 2단계 시트에는 content_type·category가 없으므로 두 축의 재검사 κ를
만들지 않는다. claims는 두 비교 모두 기존 `claim_scores`의 항목별 정밀도·재현율과
micro 값을 사용한다. 집합 일치율이나 claims κ를 내지 않는다.
`docs/EVAL.md`의 동결 기준(사람 재검사 κ 0.7, 사람·모델 κ 0.6, 콘텐츠 유형 재현율
0.9)을 그대로 표시하며 변경 옵션은 없다. 재검사 κ 미달은 "정의 모호 후보"로
표시한다. 현재 활성 축은 §6에서 동결한 v1 스키마를 따르며 시범 비교의 과거
미확정 표시를 적용하지 않는다.

결과는 사람이 읽는 표와 마지막 JSON 한 줄이다. 제목·캡션·개별 라벨 원문은
출력하지 않는다. 입력·준비 오류에는 이유 코드만 출력하며 부분 점수를 내지 않는다.
계산할 수 없는 축은 숫자를 채우지 않고 다른 결과와 함께 이유를 표시한다.
종료 코드는 완료 0(기준 미달 포함), 입력 문제 2, 일부 지표 계산 불가 3이다.

| 이유 코드 | 의미와 조치 |
|---|---|
| `NOT_READY:<파일 이름>` | 세 라벨 파일 중 해당 파일이 없다. 재검사까지 완료한 뒤 실행한다. |
| `LABEL_FILE_INVALID` | CSV 열·값·순서·CTA 동치, 키의 형식·항목·1단계 범위·사람 라벨 연결을 확인한다. DB 접속 전 중단한다. |
| `PREREGISTRATION_RULE_MISSING` | 사전 등록 §5의 교집합·합격 판정·커버리지 분모 규칙이 없거나 읽을 수 없다. 등록 기록을 확인한다. |
| `PREREGISTRATION_DEFINITIONS_MISSING` | §6의 전체 v1 동결 기록이 없다. 등록 기록을 확인한다. |
| `E1_CONFIG_INVALID` | 등록한 표집 설정의 형식·범위를 확인한다. |
| `ENV_MISSING:POSTGRES_PASSWORD` | 공백이 아닌 PostgreSQL 설정을 준비한다. |
| `DOCKER_DOWN` / `POSTGRES_UNREACHABLE` | Docker·DB와 `BEAUTYADS_POSTGRES_PORT`를 확인한다. |
| `POSTGRES_AUTH_FAILED` / `POSTGRES_CONNECT_FAILED` | DB 인증·연결 준비를 확인한다. |
| `MODEL_READ_FAILED` / `MODEL_RESULT_INVALID` | 저장 결과 조회 실패 또는 완료 작업의 라벨 형식 오류다. 점수는 출력하지 않는다. |
| `KAPPA_UNDEFINED:<축>` | 한쪽이 단일 값이거나 기대 일치가 1이라 κ를 정의할 수 없다. 판정은 비워 둔다. |
| `SCORE_EMPTY_SET:<축>` | 유효 비교 쌍 또는 재현율의 사람 제품 분모가 없다. 0으로 해석하지 않는다. |

## live-tiktok-analyze (P3)

TikTok 검색 결과는 실행마다 달라서 수집한 광고를 나중에 다시 찾을 수 없다. 이 명령은 **브랜드마다 수집한 직후 같은
응답에서 시드 고정 표본을 골라 바로 분석**한다. 영상 주소는 메모리에서만 쓰고 저장·출력하지 않는다.

```bash
make live-tiktok-analyze ARGS="--brands anua --per-brand-limit 20"   # 한 브랜드로 먼저 확인
make live-tiktok-analyze ARGS="--per-brand-limit 20"                 # 전체 14곳
```

- 선택 규칙: 분석 가능 소재를 브랜드별로 `source_id` 정렬 후 시드 20261114로 섞어 앞에서 N건(최신순 아님).
  이미 분석이 끝난 소재는 브랜드당 목표 N건에 포함하고, 실패한 소재는 건드리지 않는다.
- 소재는 광고 id로 기존 저장분과 병합한다(멱등). `--retry-failed` 재조회는 TikTok에 쓰지 않는다.
- 정지: 토큰·요청 오류는 전체 정지, 브랜드 하나의 서버 오류는 그 브랜드만 건너뜀, 일일 한도·크레딧 소진·비용 상한은 정지(남은 소재는 대기).
- 환경 점검은 `live-analyze`와 같다(TikTok 키, Gemini 키, 사전 등록, 비용 상한).

## live-products (P4)

대표 단품(`config/product_candidates.yaml`)의 공식몰 가격·전성분과 식약처 표준명·
기능성 보고/심사품목을 대조해 PostgreSQL에 저장한다. **사용자가 직접 실행한다.**
이 step에서는 `--scan`을 포함한 실제 호출을 실행하지 않는다.

실행 순서는 **`--scan` → 이미지 수·예상 비용 보고 → 사용자 승인 → 실행**이다.
스캔 결과를 보고한 뒤 멈추고 사용자 지시를 기다린다. 식약처 일일 한도는
미확인이므로 모든 모드에서 `--max-mfds-requests N`을 명시한다.

```bash
# 키·네트워크·DB 없이 ESTIMATE 한 줄만 출력
make live-products ARGS='--dry-run --products 1,2 --max-mfds-requests 20'
# 먼저 공식몰 HTTP만 사용해 가격·텍스트 전성분 여부·상세 이미지 수 확인
make live-products ARGS='--scan --products 1,2 --max-mfds-requests 20'
# 위 결과를 보고하고 멈춘 뒤, 사용자 승인 후 작게 실행
BEAUTYADS_CAP_GEMINI_USD=14 make live-products ARGS='--products 1,2 --max-mfds-requests 20 --thinking-level minimal'
```

`BEAUTYADS_CAP_GEMINI_USD=14`는 **2026-11-15 이 live에 한해 승인된 한도**다.
코드와 Makefile에 고정하지 않으며 사용자가 실행 환경에서 설정한다. 한도는
이번 실행의 예산이 아니라 `data/manifest/costs.jsonl`의 Gemini 누적액에 적용한다.
`.env`의 `DATA_GO_KR_SERVICE_KEY`·`GEMINI_API_KEY`·`POSTGRES_PASSWORD`를 준비하고,
실행에는 OrbStack과 `make db-up`도 필요하다. 값·토큰·이미지 바이트는 출력하지 않는다.
`--scan`도 키 이름·누적액을 먼저 점검하지만 Docker·DB 점검/접속은 생략하며,
모델·식약처·이미지 다운로드를 호출하지 않는다. 공식몰의 robots.txt와 호스트별
요청 간격은 기존 어댑터를 따른다. 제외 몰은 요청하지 않는다.

`--products`는 후보 파일의 **1부터 시작하는 순번**, 제품명, `브랜드:제품명`,
또는 상세페이지 URL을 쉼표로 구분한다. 순번은 후보 파일의 목록 순서 기준이다.
생략하면 전체 후보를 처리한다. `--thinking-level` 기본값은 `minimal`이다.
`--top-n`은 별도 성분 빈도 표의 최대 행 수이며 기본 50이다.

스캔의 두 상수는 각각 **가정(미실측)**이다. 이미지당 조각 수 4(관측 1건 기반)와
조각당 $0.0009(2026-11-15 합성 이미지 실측 참고)를 곱한다. 실제 이미지 높이와
전성분 출력 길이를 재지 않은 견적이며 판정 기준으로 쓰지 않는다.
**전성분을 찾으면 멈추므로 상한 추정**이다. 텍스트 전성분이 있는 페이지도
이미지 수를 표시하지만 실제 실행은 이미지를 내려받거나 모델을 부르지 않는다.
`--dry-run`의 후보 수×호출 종류는 기본 조회만 세며, 성분 조회·쪽 넘김·robots·
이미지·재요청은 별도다. 식약처 총 HTTP 요청·재시도는 지정한 N을 넘지 않는다.
호출당 시간·비용은 가정(미실측)이다.

제품 별칭은 `derive_aliases`가 같은 브랜드의 `config/brand_product_pool.yaml`
이름 목록만 받아 만든다. 풀을 읽을 수 없거나 해당 브랜드 목록이 없으면
`BRAND_POOL_UNREADABLE`로 시작하지 않는다. 선택적인 추가·제외는
`config/product_aliases.yaml`의 `aliases` 목록에서 제품별 `brand`·`name_ko`·
`extra`·`drop`으로 지정한다. 성분 별칭은 `config/ingredient_aliases.yaml`의
`aliases` 목록에 `alias`·`standard_name`·`source`를 모두 적는다.
이 두 파일은 머리 주석만 있는 상태로 제공하며, 없거나 비어 있으면 추가 0개다.
성분 별칭은 사용자·조언 세션이 출처를 확인해 채우고, 출처가 없으면 `ALIAS_INVALID`다.

성분은 표준명 캐시를 먼저 읽고 **정확 일치**만 연결한다. 괄호 속 수치 함량은
비교할 때만 분리하며 성분 원문·순서·반복은 보존한다. 목록 밖 표기는 `unresolved`
(`미해결`)로 남긴다. 불완전한 식약처 조회는 `pending`으로 남겨 재실행 대상으로
삼으며 미해결로 확정하지 않는다. 제품명 인증 대조는 공백 제거 후 정확 일치이고,
취하 품목은 제외한다. 업체명으로 브랜드를 판정하지 않으며 SPF·PA가 null이면
자외선 차단은 `unknown`이다. 공식몰의 기능성 문구 자체를 인증으로 쓰지 않는다.
광고의 `full@v1.ingredients`도 같은 사전으로 대조하고, 원래 라벨은 유지한 채
`ingredient-matches@v1` 작업에 원문·표준명·상태를 저장한다.

마지막 JSON `summary`에는 제품 상태·성분 묶임 비율·미해결/대기 수·인증 연결
커버리지(인증 종류별 수도 별도)·별칭 수·오류/보류 코드와 이번 실행 원장의
`purpose=product-detail` 모델 호출 수·비용을 표시한다. 별도의
`ingredient_frequency`에는 **표준명·제품 건수만** 내림차순으로 출력한다.
같은 제품에 같은 성분이 반복돼도 빈도는 한 번 센다. 이 표를 조언 세션에
전달해 상위 약 20개 성분→효능 수기 표에 출처를 붙인다.

제품별 대기·실패·보류 상태와 추출 원문은 `data/interim/products/records.json`에
보존한다(이미지는 저장하지 않는다). 재실행은 선택한 후보를 다시 조회하고,
기존 표준명 캐시와 저장소 upsert를 사용한다. 성분·제품 하나의 실패는 다음
항목을 막지 않는다. 402·인증·일일 한도·요청 수/비용 상한은 즉시 중단하며 현재와
남은 제품은 대기로 남긴다. `STOPPED <코드>`를 확인하고 원인을 해소한 뒤 재실행한다. 식약처 오류로 멈추면 `STOPPED <코드> provider_code=… http_status=… provider_message=…`(마스킹·한 줄·200자 이하)가 출력되고 요약과 기록의 `stopped_detail`에도 남는다. 제품이 `PRODUCT_DETAIL_FAILED`·`PRODUCT_DETAIL_HELD`이면 기록의 `issues`에 이미지·조각별 오류 코드가 남는다.

점검 실패는 `PREFLIGHT_FAILED <코드>`와 종료 코드 2다. 이유 코드는
`ENV_MISSING:<이름>`·`DOCKER_DOWN`·`POSTGRES_UNREACHABLE`·`COST_CAP:gemini`·
`POSTGRES_AUTH_FAILED`·`POSTGRES_CONNECT_FAILED`·`BRAND_POOL_UNREADABLE`·
`ALIAS_INVALID` 등이다. 키 누락·비용 상한·Docker 실패 뒤에는 다음 접속 점검도
진행하지 않는다. 성공/계획/스캔 완료는 0, 시스템 중단 또는 제품 오류·보류·대기가
있으면 3이다. `live-products`는 `make verify`에 포함하지 않는다.


## 역량 질문 확인 (`live-cq`)

사용자가 `make sync`로 그래프를 준비한 뒤 `make live-cq`를 실행한다.
모델 호출 없이 Neo4j를 읽기만 하며 비용은 0이다. `make verify`에는 포함하지 않는다.
CQ-07을 제외한 동결 v1 질문을 고정 Cypher로 실행하고 질문별 JSON 한 줄과 요약을 출력한다.
각 줄에는 홉 수, 성공/오류 코드, 결과 행 수, 답에 사용된 Creative 중 제품에 연결된 수 /
질문 범위의 제품 소재 수(`PROMOTES` 커버리지), 문서의 한계 원문과 답을 표시한다.
0행은 데이터 부족으로 따로 집계하며 홉 설계 실패와 합치지 않는다.

CQ-09는 `config/advertiser_classes.yaml`을 정규화해 TikTok 광고주를 분류한다.
분류 파일 오류는 CQ-09만 막으며 다른 질문은 계속한다. 두 비교 집단 중 하나라도
30건 미만이면 “표본 부족으로 방향만 제시”라고 표시한다. 광고주 이름을 반영하려면
기존 일반 소재 동기화를 `make sync ARGS='--full'`로 다시 실행한다.
CQ-03·10·11은 제품 인증 연결의 certified/unknown/제품 수를 함께 출력한다.
CQ-06은 조회수 없는 소재 수를 별도로 출력하고 출처/브랜드별 14일 이상 소재의
백분위를 사용한다. 현재 그래프에는 원 채널 ID가 없어 브랜드를 대용하므로
엄밀한 채널 내 비교는 P5 이후 보완해야 한다.
CQ-12는 Feedback이 없으면 `SKIPPED_SYNTHETIC_ONLY`이고 임시 데이터를 쓰지 않는다.
Feedback이 있어도 세션 테넌트가 없는 CLI는 `CQ_CONTEXT_MISSING`으로 거부한다.
CQ-13·14·16은 공개 제품 각각을 기준 제품으로 표시한 쌍을 출력한다. 특정 작업 공간의
“우리 제품” 해석에는 P5 브랜드 프로필이 필요하다. 핵심 성분 unknown은 추정하지 않는다.
CQ-16은 서버 컨텍스트의 가격 범위로 조회하고, 범위가 없으면 기준 제품과 정확히 같은
단위당 정가만 조회한다. 임의의 가격대 허용 폭을 판정 기준으로 만들지 않는다.

점검 실패는 `PREFLIGHT_FAILED`와 종료 코드 2다. 이유는
`ENV_MISSING:NEO4J_PASSWORD`, `DOCKER_DOWN`, `NEO4J_UNREACHABLE`, `GRAPH_EMPTY`이며,
빈 그래프는 먼저 `make sync`로 준비한다. 질문 오류는 다음 질문을 막지 않고 종료 코드 3으로
보고한다. 성공(0행 및 합성 전용 건너뜀 포함)은 종료 코드 0이다.

## 영상에서 제품 식별 (`product-id@v1`)

텍스트로 제품에 연결하지 못한 YouTube·Instagram 최종 제품 소재에 한해,
같은 브랜드의 PostgreSQL 제품 후보 안에서만 영상으로 식별한다. TikTok과 이미
완료된 작업은 제외한다. v1 분류 축·E1은 변경하지 않는다. 영상은 앞 60초·fps 1이
기본이며 Instagram은 기존 재조회·메모리 다운로드·Files 업로드 경로를 사용하고
처리 직후 삭제한다. 결과는 별도 분석 작업에 원문·프롬프트 버전·시도 횟수와 함께
저장하며 다음 `make sync ARGS="--layers 2"`에서 `basis=video`, `confidence=model`로
연결한다. 텍스트로 이미 연결된 소재는 텍스트 판정을 유지한다.

아래 명령은 사용자가 실행한다. 개발·검증 중에는 실제 호출하지 않는다.

```bash
make live-product-identify ARGS="--dry-run --sample 50 --seed 20261115"
make live-product-identify ARGS="--sample 50 --seed 20261115 --sample-pairs 20 --thinking-level minimal --window-max-s 60"
```

`--dry-run`은 대상 수와 영상 길이×약 91토큰/초 비용을 **가정(미실측)**으로
표시하고 영상 다운로드·모델 호출·작업 저장을 하지 않는다. 같은 모델의 원장 실측
비용/입력 토큰이 있으면 출력·추론을 포함한 유효 단가로 사용하고, 없으면 입력
$0.75/M을 가정한다. 후보 글자·출력·추론·재요청에 따라 실제 비용은 달라지며
추정치는 판정 기준으로 쓰지 않는다.

`--sample N`은 고정 시드로 N건만 처리하고 멈춘다. `--max-videos`는 추가 상한이다.
요약에는 대상·처리·완료·보류·실패·대기, 새로 연결된 소재 수, 복수 제품 소재 수,
근거별 연결 수, 원장 비용과 정밀도 확인용 무작위 20쌍(제목·캡션 앞 120자,
YouTube 영상 주소 또는 Instagram permalink, 제품 이름)이 나온다. 사람이 표본을
확인하고 **전체 실행 비용을 승인한 뒤에만** `--sample`을 빼고 `--approve-cost`를
지정한다. 시작 전 Gemini 키·Docker·PostgreSQL·Gemini 누적액을 점검하며 상한은
$12다. 일일 한도·크레딧 소진·인증·비용 상한에 걸리면 남은 작업은 대기로 두고
멈춘다. 원인을 해결한 뒤 같은 명령으로 재개하면 완료 작업은 제외된다.

## 근거 도구 읽기 전용 점검 (`live-evidence`)

그래프를 준비한 뒤 **사용자가 직접** `make live-evidence`를 실행한다.
Neo4j 접속 설정·Docker·접속 가능 여부를 기존 `live-cq`와 같은 사전 점검으로
확인한다. 모델 호출과 쓰기 작업은 없고 비용은 0이며 `make verify`에 포함하지 않는다.

지원 카테고리 3종에 대해 같은 서버 기준일·출처(YouTube·Instagram)로 새 훅 질의의
`product_link` 결과와 동결 CQ-06의 `(creative_id, hook)` 집합이 같은지 확인한다.
다르면 차이 개수를 출력하고 즉시 종료 코드 3으로 멈춘다. 같으면 `creative_label`과
`product_link`의 결과 건수, 소재 ID 교집합과 양쪽 차집합 개수를 출력한다.
두 기준의 카테고리 출처가 다르므로 포함 관계를 가정하지 않는다.

새 도구의 `category_basis` 기본값 `creative_label`은 **모델 라벨 기준(E1 채점 전)**이다.
`product_link`는 **제품 연결 기준(연결된 소재만)**이며 제품 단위 성분 주장이 필요하면
명시적으로 선택한다. 상위·하위 비교는 출처·브랜드를 채널 대용으로 쓰고 게시 14일
이상 소재의 조회수 백분위를 따른다. TikTok에는 적용하지 않으며 기술적 비교는 인과를
뜻하지 않는다. 표본이 한쪽이라도 10건 미만이면 표본 부족을 표시한다.

성공은 종료 코드 0, 사전 점검·접속 오류는 이유 코드와 종료 코드 2다.
설정 값·인증 정보·개별 소재 원문은 출력하지 않는다.
