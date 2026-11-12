# phase 계획 (v3, 승인됨 2026-11-12)

상태: **승인됨**(2026-11-12, 사용자가 조언 세션 화면에서 직접 확정). 원래 조언 세션 검토(v0~v3)와 사용자 결정을 반영했다. 일정 재계획 지점은 P1 끝(11-14)과 P2 끝(11-17)이다. 변경은 이 문서를 고치고 변경 이유를 아래 "계획 변경 기록"에 적는다. 수치(예상 소요·비용)는 추정이며 측정값이 아니다.

## 0. 계획 변경 기록 (v0 → v3)

| # | 변경 | 출처 |
|---|---|---|
| 1 | dev/test 브랜드 분할 step을 P2 `pilot-sheet` 앞(P2 step 1)에 추가. 시범 20건은 dev 브랜드만, E1 표본은 test 브랜드만. 평가셋도 dev/test | 조언 세션 |
| 2 | P1을 수집→분석→저장까지로 축소. graph-sync는 P4 첫 step, 에이전트·API 뼈대는 P5 첫 step으로 이동 | 조언 세션 제안, 사용자 확정 |
| 3 | P1 step 2를 원장·상한(obs)과 LiteLLM 래퍼(llm)로 분리. compose와 store도 분리해 step마다 한 레이어 | 조언 세션 + 하네스 원칙 1 |
| 4 | 비용 원장 경로를 settings 기본값 + 주입 가능으로 하고 테스트는 tmp 경로만 | 조언 세션 |
| 5 | live마다 docs-only 결과 PR(`docs/results/<날짜>-<phase>-live.md`, TROUBLESHOOTING, 필요 시 FP 추가) | 조언 세션 |
| 6 | 블라인드 시트: 모델 라벨과 지표 숨김, 항목 순서 시드 셔플, 키 파일 분리, 생성기와 채점기를 다른 step에 | 조언 세션 |
| 7 | batch-runner: 동시성 기본값 낮게·설정 가능, 429를 분당·일일로 구분 | 조언 세션 |
| 8 | E1 표본 틀 확정(별도 100건 방식), 줄이는 순서 확정, TikTok 집행 주체는 규칙으로 | 사용자 결정(조언 세션 화면에서 전달) |
| 9 | 시범은 YouTube·Instagram만. TikTok 어댑터는 P2 마지막 step으로 옮기고 밀리면 P3로 | 조언 세션 일정 참고 |

**v1 → v2**

| # | 변경 | 출처 |
|---|---|---|
| 10 | **E1 층화 구멍 수정**: 1단계 100건은 모델 출력과 무관한 기준(출처×브랜드)으로 뽑고, 사람이 콘텐츠 유형과 카테고리를 함께 라벨링. 2단계 제품 소재 50건은 **사람 라벨**의 출처×카테고리로 뽑음. 모델이 `other`로 보낸 소재가 빠져 재현율이 부풀려지는 것을 막음 | 조언 세션(원래) |
| 11 | N 공식 폐기. 시드 셔플 순서대로 라벨링하다 사람이 제품 소재로 판정한 건이 50건 이상이 되면 멈춤. 최소 100건, 상한 200건을 사전 등록 | 조언 세션(원래) |
| 12 | P3 순서: `e1-sampling`을 `analyze-target` 앞으로. 사용자가 라벨링하는 동안 전체 분석이 돈다 | 조언 세션(원래) |
| 13 | P1 llm 래퍼는 Gemini만. `reasoning_effort`·temperature·스트리밍 비용 등 OpenAI·Anthropic 전용 처리는 P5 새 step `llm-chat-models`로 | 조언 세션(원래) |
| 14 | P1 step 0을 `architecture-guard`와 `settings-domain`으로 분리(가드 검사 대상 정의 포함), P1은 9 step | 조언 세션(원래) |
| 15 | dev:test 5:9에 제약 추가(양쪽에 카테고리 3개·YouTube·Instagram, test가 E1·E4 수집량을 채울 것, 라벨링 전 1회 재분할 허용) | 조언 세션(원래) |
| 16 | 평가셋: EVAL 숫자(요청 20, 질문 30 + 단순 검색형 10)를 test로, dev는 요청 10·질문 10 추가. 모델이 후보를 뽑고 사용자가 고르고 고침 | 조언 세션(원래) 권고, 사용자 결정 필요 |
| 17 | P4 step 0·P5 step 1 뒤에 짧은 live 확인(`make live-graph`, `make live-agent`) | 조언 세션(원래) |
| 18 | 사용자 시간 표에 날짜별 예상 소요 시간 추가(추정) | 조언 세션(원래) |
| 20 | **사전 실측 2차 반영**(원본 8건, 포크 조언 세션 실측, 원본 대조 완료): 영상 입력 토큰 ≈ 91/초(길이에 비례), `thinking_level` 설정, Gemini Files 실패 형태, TikTok 쪽 넘김·쪽 간 중복, Instagram URL 만료, 식약처 선케어 SPF·PA 대부분 null, YouTube 마지막 쪽·숨김 통계 | 포크 조언 세션 |
| 21 | **분석 비용 견적 상향 가능성**(상한 $12 유지 확정, 아래 §8): 1,500건 $9.3(minimal)~$12.8(기본 thinking), 상세페이지 $1.2 별도 → **Gemini 상한 $12는 기본 thinking이면 닿는다.** P1에 `duration_s`·분석 구간 상한(60초)·`thinking_level` 필수 인자(기본 minimal), P2 시범에서 minimal·기본 비교. 상한 결정은 사용자 | 포크 조언 세션 |
| 19 | TikTok 집행 주체 규칙(§P2 step 9)은 처음에 포크 조언 세션의 답이었으나 이후 **사용자가 확정**했다(§8) | 정정 |
| 22 | **분류 동결을 둘로 나눔**: 11-18 `content_type`·`category`만 부분 동결(시범 결과 반영, 사용자 승인), 11-19 나머지 축 전체 v1 동결. 두 날짜를 사전 등록 파일에 기록. 분석 일괄 실행은 전체 v1 동결 뒤 | 조언 세션 v2.1 |
| 23 | **`pilot-compare`·`cost-recalc`를 `analyze-target` 앞으로**, 둘 뒤에 사용자 결정 지점(thinking_level·Gemini 상한)을 두고 그 뒤에 일괄 분석 | 조언 세션 v2.1 |
| 24 | **TikTok은 E1 표본 출처에서 기본 제외**(밀릴 때만이 아님). 시트에는 YouTube 영상 주소·Instagram `permalink`만 쓰고 만료되는 `media_url`은 넣지 않음. 결과 문서에 "E1은 YouTube·Instagram 한정"을 한계로 기록 | 조언 세션 v2.1 |
| 25 | P2 시범의 성분은 **원문 그대로 저장**, 표준명 대조·폐기는 P4로(의존성 역전 해소). E1 판정 축에서 `ingredients` 제외 권고 | 조언 세션 v2.1 |
| 26 | E1 절차 3(타사 모델 라벨): 기본 "미수행, 결과 문서에 한계로 기록"으로 확정, P6에서 텍스트·캡션 축만 재검토 가능 | 조언 세션 v2.1, 사용자 확정 |
| 27 | E3 벡터 비교 구성(임베딩 모델, 벡터 저장소)을 남은 미확인과 P5 전 실측 대상에 추가 | 조언 세션 v2.1 |
| 28 | **수집 실행기를 P2로**: `collect-runner`(재개 가능한 전체 수집, 지표 이력 누적, `make live-collect`)를 P2 `instagram-source` 바로 뒤 step으로. 사용자가 11-15~16에 수집을 돌린다. P2가 밀리면 `batch-runner`·TikTok이 먼저 줄고 `collect-runner`는 남긴다 | 조언 세션 v3 검토 |
| 29 | **E1 표본 프레임 = 분석 가능한 소재**: 소재마다 `analyzable`을 저장(`domain` 공통 소재 형식, P1 step 1), `e1-sampling`은 `analyzable == true`에서만 추출, 제외 비율을 결과 문서에 한계로 기록 | 조언 세션 v3 검토 |
| 30 | `ingredients` E1 판정 축 제외는 **사용자 확정 전까지 권고 상태**. 확정되면 `e1_preregistration.md`에 기록 | 조언 세션 v3 검토 |

## 1. 전제와 일정

오늘 11-12, 마감 12-02. **Codex 실행은 직렬이다**(`execute.py`가 phase마다 `feature/{phase}` 브랜치를 쓴다). 병렬로 가는 것은 사용자 시간과 사용자가 돌리는 live뿐이다. 임계 경로는 E1이고 **11-20 첫 라벨링은 고정**이다. 앞이 밀리면 시범 날짜가 아니라 P2 범위를 줄인다.

| 날짜 | phase | 끝났을 때 있어야 하는 것 | 사용자 시간 |
|---|---|---|---|
| 11-12~14 | **P1 collect-analyze-core** | YouTube 1건 → 분석 → 저장(CLI 확인) | `make live-slice` 1회 |
| 11-14~17 | **P2 sources-pilot** | brand-split, Instagram, **전체 수집 실행기(11-15~16 `make live-collect`)**, 영상 파일 경로, 전체 분류 분석, 배치, 블라인드 시트, TikTok | **11-17~18 시범 20건 라벨링** |
| 11-17~20 | **P3 collect-freeze** | `content_type`·`category` 부분 동결(11-18), E1 1단계 시트, 시범 비교·비용 재계산, 전체 v1 동결(11-19), 일괄 분석 시작 | 아래 사용자 시간 표 |
| 11-20~24 | **P4 ontology** | graph-sync, 역량 질문 동결, 1층, 2층 연결 | 11-20 역량 질문 최종 검토 |
| 11-24~27 | **P5 agents** | 에이전트·API 뼈대, 도구, 에이전트 4종, 코드 검사, Langfuse(선택) | **11-26까지 평가셋(아래 §8)** |
| 11-27~30 | **P6 eval-runners** | E2·E3·격리·E5, 결과 문서 | **11-27 E1 재라벨링(축 50건)** |
| 11-30~12-02 | **P7 web-demo** | 화면, k3d, 시연 | 시연 녹화, 원고 |

**사용자 시간 (모두 추정, 측정 전)**

| 날짜 | 할 일 | 예상 소요 |
|---|---|---|
| 11-14 | `make live-slice` 실행·결과 확인 | 30분 |
| 11-15~16 | `make live-collect` 실행·결과 확인 | 30분 |
| 11-17~18 | 시범 20건 라벨링(소재당 약 5분) | 1.5~2시간 |
| 11-18 | `content_type`·`category` 부분 동결 검토·승인(시범 결과 기준) | 30분 |
| 11-18~19 | **E1 1단계**: YouTube·Instagram test 브랜드 100~200건에 콘텐츠 유형·카테고리 라벨링(소재당 약 1분) | 2~3.5시간 |
| 11-19 | 시범 비교·비용 재계산 보고 확인 → **thinking_level·Gemini 상한 결정**(15~30분), 나머지 축 포함 **전체 v1 동결 승인**(30~60분) | 45~90분 |
| 11-19~20 | **E1 2단계**: 제품 소재 50건에 나머지 축 라벨링(소재당 약 4~5분) | 3.5~4시간 |
| 11-20 | 역량 질문 최종 검토 | 1시간 |
| 11-23 | 공식몰 대표 단품 목록 확인 | 30분 |
| ~11-26 | 평가셋: 요청 30(test 20+dev 10)·질문 50(test 40+dev 10)을 모델 후보에서 고르고 고치고, 정답은 그래프 질의 결과를 확인 | 3~4시간 |
| 11-27 | **E1 재라벨링**(축 50건, 첫 라벨 가림) | 3~4시간 |
| 12-01~02 | 시연 녹화·상세 페이지 원고 | 3시간 |

11-17~20에 약 8~10시간이 몰린다. **고정 사슬**: 전체 수집 완료(11-16, P2 `collect-runner`) → 부분 동결 승인(11-18) → 1단계 시트 → 1단계 라벨링(11-18~19) → 전체 v1 동결(11-19) → 2단계 시트 생성 → 2단계 라벨링(11-20 완료) → 7일 뒤 재라벨링(11-27). 어느 고리든 하루 밀리면 재라벨링이 11-28로 밀리고 결과 문서 마감이 위험해진다. **E1 표본은 처음부터 YouTube·Instagram만 쓴다**(TikTok은 안정적인 보기 링크가 원본에 없고 영상은 분석 후 삭제하는 규칙과 충돌하며 EU 게재분이라 언어·시장이 다르다). 그래프·에이전트 데이터로는 TikTok을 쓴다. P2가 압박을 받으면 **TikTok이 아니라 batch-runner 범위(분당 한도 세부·동시성 튜닝)부터 줄인다**.

재계획 지점: **P1 끝(11-14)과 P2 끝(11-17)** 에 실측 소요로 일정을 다시 쓴다. 하루 이상 밀리면 확정된 순서대로 뺀다: **이력 압축 → E4 → 이미지 시안 → 분포 차트 → E5.** E1·E2·E3·격리 검사·웹 시연은 지킨다. P1을 11-14에 끝내고 여유가 있으면 `--steps`로 끊어 가며 P1b(그래프 적재와 에이전트 한 줄)를 잇는 선택지가 있다(§3).

## 2. 공통 설계 규칙

- phase = PR 1개, step은 8개 안팎, **step 하나는 레이어 하나**. 수정은 새 phase가 아니라 다음 phase의 step으로 넣는다.
- 실제 호출 live 타깃은 phase마다 이름 하나(`live-slice`, `live-pilot`, `live-collect`, `live-analyze`, `live-cq`, `live-agents`). verify에 넣지 않고, 시작 전 환경 점검을 하며 실패하면 이유 코드를 출력하고 시작하지 않는다(B-FP-051).
- **live 뒤에는 docs-only 결과 PR**: `docs/results/<날짜>-<phase>-live.md`, `TROUBLESHOOTING_LOG` 갱신, 수정 커밋이 있었던 실패는 failure-patterns FP로 추가. 수치는 결과 문서에서만 가져간다.
- `make verify`는 서비스 없이 통과하므로 SQL·Cypher·드라이버 설정의 결함은 첫 live에서 드러난다. 수정은 다음 phase의 첫 step(`live-fixes`)에 넣는다.
- 라벨 키 파일이 `data/interim/`에 놓이므로 **P2부터 모든 step의 열람 금지 경로에 `data/interim/`를 넣는다**(블라인드 보호).
- 패키지 설치: step이 `uv add`로 지시한 패키지만 허용하고 그 밖의 설치·의존성 추가는 금지하며, 해석된 버전을 완료 보고(`summary`)에 적는다. (AGENTS.md CRITICAL을 이에 맞게 고쳤다. 사용자 결정, 2026-11-12)
- `execute.py --steps N`으로 phase를 끊어 리뷰한다(P2는 TikTok 앞에서 한 번 끊어 시범 live를 먼저 돌린다).

## 3. phase 상세

### P1 collect-analyze-core (9 step, 목표 11-14)

분류 축은 `hook_type` 하나만 쓴다. 공통 금지(모든 P1 step): 실제 `.env` 열람 금지(공통 블록), 모델이 고른 값을 단언하지 않음(FP-C03).

| step | 이름 | 내용 | 수정 허용 경로 | step별 금지사항 후보 (FP) |
|---|---|---|---|---|
| 0 | `architecture-guard` | **`tests/test_architecture.py`**: AGENTS.md의 내부 계층 표와 외부 SDK 표를 AST로 강제. **검사 대상 = `src/beautyads` 아래 `.py`(`__init__.py` 포함) 1개 이상**이고 0개면 실패한다. 위반 모듈을 tmp 디렉터리에 만들어 실제로 잡히는지(허용 import는 통과, 금지 계층·SDK는 실패) 확인하는 자체 테스트 | `tests/test_architecture.py` | 가드가 비어 있어도 통과하게 두지 않는다(B-FP-069). 표를 바꾸는 step은 AGENTS.md와 이 테스트의 상수를 함께 고친다. 위반 검출 확인용 모듈은 tmp에만 만들고 `src/`에 두지 않는다 |
| 1 | `settings-domain` | `settings.py`(`.env`를 읽는 유일한 함수, 빈 값이 기본값을 덮지 않음, 원장 경로 기본값 `data/manifest/costs.jsonl`+주입 가능), `domain`(공통 소재 형식 — `analyzable`(`bool | None`, **None·키 없음은 미판정이며 분석 가능으로 보지 않는다**: YouTube는 수집 시 true, Instagram은 `media_type == "VIDEO"`이고 그 시점에 `media_url`이 반환됐으면 true, 아니면 false), `duration_s`(없을 수 있음)와 선택 통계(좋아요·댓글이 없으면 `null`이고 0이 아님), 닫힌 값 `hook_type`, 저장소·조회 Protocol). 설정값: **분석 구간 상한 60초**, **영상 길이 컷 기본 600초(수집 시점의 `analyzable` 판정에 한 곳에서 반영)**, 분석 `thinking_level` 기본 `minimal`(`ThinkingLevel`에 `default` = `thinking_level`을 보내지 않는 서버 기본 비교군 포함). `AnalysisRepository.record_analysis`에 `prompt_version`. `uv add pydantic` | `pyproject.toml`, `uv.lock`, `src/beautyads/settings.py`, `src/beautyads/domain/**`, `tests/test_settings.py`, `tests/test_domain*.py` | 기본값 있는 환경 변수는 한 함수로만 읽는다(B-FP-030). 설정 테스트는 임시 `.env`만 쓴다(A-FP-056). `domain`에서 pydantic 외 import 금지. 모델이 고른 값을 단언하지 않는다(FP-C03). `analyzable`이 None·없음일 때를 다루는 테스트(표본 추출·분석 대상 선별이 true만 통과시키는지)를 둔다 |
| 2 | `compose` | `deploy/docker-compose.yml`(postgres:17.11 호스트 5433, neo4j:2026.10.1-community, 이미지 태그 고정, 볼륨·컨테이너 이름이 B와 겹치지 않음), 비밀번호는 `.env` 변수 참조, `Makefile`의 `db-up`·`db-down`·`graph-reset` 타깃. `uv add pyyaml` | `deploy/**`, `Makefile`, `.env.example`, `tests/test_compose.py`, `pyproject.toml`, `uv.lock` | `latest` 태그·평문 비밀번호 금지. B 스택 포트(5432·3000·7474·7687 기본값)와 겹치는 호스트 포트 금지. compose 파일을 실행하지 않는다 |
| 3 | `store` | `store/` 스키마(소재, 지표 이력과 최신값, 모델 출력 원문, 분석 작업 상태 4종, 동기화 시각, **변경 시각 컬럼**), 멱등 마이그레이션, 연결은 Protocol 뒤. `uv add psycopg` | `src/beautyads/store/**`, `tests/test_store*.py`, `pyproject.toml`, `uv.lock` | 중복 제거 키 = (출처, 원본 ID) = 출력 키(A-FP-033). 마이그레이션은 두 번 실행해도 같다. 가짜 연결로만 테스트, 실제 DB 접속 금지. `model_outputs.prompt_version` 보존. "바뀐 행" 판정 열은 상수 `CHANGE_COLUMNS`(내용 열 7개 + 최신 지표 값 3개, 수집 시각 열 제외). `connect` 오류를 `POSTGRES_AUTH_FAILED`·`POSTGRES_CONNECT_FAILED`로 변환 |
| 4 | `obs-ledger` | `obs/`: 원장 한 줄 기록(공급사, 응답이 알려 준 실제 모델, 입력·출력·thought·캐시 토큰, 비용, 실행 유형, 비용 출처), 공급사별 누적액 검사(Gemini $12·OpenAI $10·Anthropic $8, 설정으로 주입), 손상 줄 처리 | `src/beautyads/obs/**`, `src/beautyads/settings.py`(원장·상한 설정 추가에 한함), `tests/test_ledger*.py`, `tests/test_settings.py`(해당 케이스 추가에 한함, 단언 약화 금지) | **테스트는 실제 `data/manifest/costs.jsonl`에 쓰지 않는다**(예외 경로라 작업 트리와 원장이 오염됨). 원장에 키·본문·헤더를 남기지 않는다. 필드는 이름으로 읽고 없으면 0 |
| 5 | `llm-wrapper` | `llm/`(LiteLLM SDK `==1.103.3`) **Gemini Interactions만**(YouTube 주소 입력, 구조화 출력, 구간 지정). 공통 부분: 재시도는 503·연결 실패·시간 초과만, 429를 본문·`retry-after`로 일일·분당 구분, **`thinking_level`을 필수 인자**로 받아 `generation_config`로 전달(기본 `minimal`, `thinking_budget`은 400이라 쓰지 않음), 호출 직전 공급사 상한 검사와 원장 기록 호출, Gemini 답 추출(`type == "model_output"`, 울타리 허용). **OpenAI·Anthropic 전용 처리(`reasoning_effort`·temperature·스트리밍 비용·도구 호출)는 P5 `llm-chat-models`로 미룬다** | `src/beautyads/llm/**`, `tests/test_llm*.py`, `pyproject.toml`, `uv.lock` | 일일 한도 429를 재시도하지 않는다(실측에서 한도를 소진함). 답의 위치를 `[0]`·`[-1]`로 찾지 않는다(FP-C02). 오류는 예외 문자열·객체·배열 형태를 모두 받는다(FP-C01). 전송 후 실패를 재시도해 이중 과금하지 않는다(A-FP-035). 채팅 모델 인자는 이 step에서 만들지 않는다. `thinking_level` 기본값을 `minimal` 이외로 하드코딩하지 않는다(thought는 출력 단가로 청구, 1,500건 비용이 $12.8까지 오름). `llm/__init__.py` 맨 앞에서 `LITELLM_LOCAL_MODEL_COST_MAP=True`를 설정해 가격표를 로컬로 고정(원격 조회 방지). `thinking_level="default"`이면 키를 보내지 않음 |
| 6 | `youtube-source` | `sources/youtube`와 `sources.yaml` 로더(채널 ID로만 조회, uploads 목록, 영상 상세), 공통 소재 형식 변환, 문자열 통계 변환. `uv add httpx` | `src/beautyads/sources/**`, `tests/test_youtube*.py`, `tests/test_sources_config.py`, `pyproject.toml`, `uv.lock` | `items` 키가 없을 수 있다. `statistics` 키가 빠질 수 있고 값은 문자열이다. 마지막 쪽에 `nextPageToken`이 없을 수 있다(FP-C01). 채널 이름 검색 금지(TROUBLESHOOTING 2026-11-11). 픽스처는 `youtube_*.json`에서만 만든다. **업로드 목록 마지막 쪽에는 `nextPageToken` 키가 없다**(8개 채널 모두). `likeCount`(1.9%)·`commentCount` 없는 영상이 있어 `null`로 저장하고 0으로 바꾸지 않는다. `quotaExceeded` 형태는 미실측이라 HTTP 상태를 먼저 보고 `error.errors[0].reason`을 읽는다. 목록 조회에 상한 설정(채널당). **영상 길이 컷은 수집 시점에 `analyzable=False`로 판정**(길이 0·`PT0S`, 컷 초과, 라이브·예정도 False, 길이 불명은 None) |
| 7 | `analysis-hook` | `analysis/`: 구조화 출력 요청(`response_format`+`Api-Revision`), 첫 3초 구간, 스키마 검증, 목록 밖이면 1회 재요청 후 보류, 모델 호출은 `llm` 래퍼만. **모델 호출 전의 값싼 선별**: `duration_s`가 길이 컷을 넘으면 제외하고, 분석 구간은 `end_offset` 최대 60초로 제한(14분 영상 전체 79,435토큰 대 60초 5,461토큰) | `src/beautyads/analysis/**`, `tests/test_analysis*.py` | 모델이 고른 `hook_type` 값을 기대값으로 쓰지 않는다. 형식·재요청·보류만 검사한다(FP-C03). 소재 하나의 실패는 기록하고 넘어간다(A-FP-030). 분석 쪽 `TOO_LONG` 선별은 방어용이고 길이 컷의 기준은 수집 시점 `analyzable`이다. `HOOK_PROMPT_VERSION`을 `model_outputs.prompt_version`에 기록 |
| 8 | `slice-live-target` | `pipeline/slice.py`와 `make live-slice`: 환경 점검(키 이름 존재, Docker, 포트, 공급사 누적액, 이유 코드) → 소재 1건 수집 → 분석 → 저장, 결과를 CLI로 출력. README에 절차 | `src/beautyads/pipeline/**`, `Makefile`(`live-slice` 추가에 한함), `README.md`, `tests/test_slice*.py` | `make live-slice`를 실행하지 않는다. verify에 live를 넣지 않는다. 호출 건수 기본값 1, 영상 임시 파일 없음(YouTube는 주소 입력). `store.connect` 실패는 `POSTGRES_AUTH_FAILED`·`POSTGRES_CONNECT_FAILED`로 출력(DSN·비밀번호 미출력). README에 `make db-up` 뒤 대기 안내와 비밀번호가 첫 볼륨에만 적용된다는 조치. PostgreSQL 볼륨 삭제 타깃은 만들지 않음 |

머지 뒤 사용자가 `docker compose up`과 `make live-slice`를 한 번 돌리고 결과를 결과 문서 PR로 남긴다.

**P1b (선택, 11-14 소요 측정 뒤 결정)**: 그래프 적재와 에이전트 한 줄을 P1 끝에 이어 붙이는 선택지. 단 P4·P5 첫 step과 중복이라 일정이 허락할 때만 한다.

### P2 sources-pilot (11 step: 4a·4b 분리 포함, TikTok은 마지막). P2가 밀리면 `batch-runner`·TikTok이 먼저 줄고 `collect-runner`는 남긴다

| step | 이름 | 내용 |
|---|---|---|
| 0 | `live-fixes-config` | P1 live 결함 수정 |
| 1 | `brand-split` | **dev/test 브랜드 분할**: `sources.yaml`의 14개 브랜드를 시드로 나눠 `config/brand_split.yaml`에 기록(수집 전, 같은 브랜드가 양쪽에 걸치지 않음, 계정이 여럿인 브랜드는 한쪽). **사전 등록 제약**: dev·test 양쪽에 3개 카테고리와 YouTube·Instagram이 모두 들어갈 것, test가 E1 100~200건(YouTube·Instagram만)과 E4 60건을 채울 수집량일 것. 안 맞으면 **라벨링 전에 한해** 이유를 적고 1회 재분할할 수 있다. 분할·시드·제약은 `docs/results/e1_preregistration.md`에 포함 |
| 2 | `instagram-source` | Business Discovery, `after` 커서, `media_url` 키 없음, 영상 여부는 `media_type == "VIDEO"`, 오류 110·190 분기, 서명 주소는 받을 때마다 새로 조회. **만료는 `media_url`의 `oe`(16진 Unix 시각)**에 있고 49건 모두 남은 시간 32~108시간이었다 → 목록 조회 뒤 수 시간 안에 받아 처리하고 저장한 URL을 나중에 쓰지 않으며, `oe`가 임박하면 재조회. 만료된 URL의 응답은 미확인. 묶음 게시물의 `media_url`은 이미지. **`permalink`는 표본 8건에 모두 있었으나 CONTRACTS에는 아직 없다**(계약 PR에서 추가). 어댑터는 `fields`에 `permalink`를 넣어 요청하고 없을 수 있다고 읽는다. 블라인드 시트(P3)는 이 `permalink`를 쓴다. **재조회 실측(2026-11-12, 4계정×50건)**: `media_url` 반환 여부는 5초·15분·약 20시간 뒤 재조회에서 모두 일관(변화 0건)해 수집 시점 `analyzable` 저장이 성립하나, 3일 뒤 일관성은 미실측이라 **분석 직전 재조회에서 `media_url`이 사라진 게시물은 `analyzable=False`로 갱신**한다. `media.limit(100)`이 한 번에 100건을 반환하므로 계정 재스캔은 계정당 1~2호출이다. 재조회 때 `oe`는 일부 게시물만 약 4시간 단위로 갱신되고 재조회 직후 남은 유효 시간은 최소 32.1시간(대부분 104~108시간). 호출당 `x-app-usage` `call_count` 약 0.5%(한도 정의는 미확인). 특정 게시물만 조회하는 방법은 없다. `oe` 임박(남은 6시간 미만)이면 어댑터가 재조회 |
| 3 | `collect-runner` | **전체 수집 실행기**(YouTube·Instagram 전 브랜드, 재개 가능, 지표 이력 누적, 소재마다 `analyzable` 저장, 수집은 메타데이터만 쓰고 분석과 무관), `make live-collect`와 환경 점검. **이 step 뒤에 끊어 사용자가 11-15~16에 `make live-collect`를 돌린다.** 영상 파일은 받지 않는다. **분석 직전 갱신 필요**: Instagram `media_url`은 32~108시간 뒤 만료하므로 11-19 이후 분석할 때는 수집 때 저장한 URL을 쓰지 않고 분석 직전에 계정을 다시 조회해 URL을 갱신한다(P3 `analyze-target`) |
| 4 | `media-upload-flow` | 영상 임시 다운로드 → `create_file` → `processed` 대기 → 분석 → `file_delete`(`deleted: true`로 판단) → 임시 파일 삭제. 실패해도 정리. **업로드 뒤 `status == "processed"`일 때만 분석**, `error`면 소재를 보류로 두고 파일 삭제. 영상 크기 0은 사전 거부(빈 파일 업로드는 `ValueError(...'sizeBytes')`). 없거나 삭제된 파일은 403 `permission_denied`, 비영상은 400 `invalid_request`로 오므로 분석 오류 분류에 넣는다. 8.19MB 기준 다운로드 9.9초·업로드 3.9초·대기 4.9초·분석 16.6초. 구간 지정은 Files 파일에서도 동작. **llm(Files)과 임시 파일 정리 오케스트레이션이 한 step에 레이어 둘이므로 step 파일 작성 때 4a(llm)·4b(pipeline)로 쪼갠다**. **`httpx`는 `sources`에서만 허용되므로 영상 임시 다운로드는 `sources`의 함수(예: `download_media`)로 두고 `pipeline`(4b)이 그 함수를 호출한다**. 받기 실패(만료 포함)는 `analyzable` 해제가 아니라 "재조회 후 재시도 1회, 그래도 실패하면 보류(`held`)" |
| 5 | `analysis-full` | 콘텐츠 유형 먼저, 제품 소재만 전체 축, 두 번 호출(첫 3초 / 전체). **성분은 원문 그대로 저장한다**(표준명 대조·목록 밖 폐기는 사전이 생기는 P4 `product-records`에서 한다. P2 시범 시점에는 사전이 없다). 시범·E1 라벨링 판정 축에서 `ingredients`는 제외하는 것을 권고(그래프 연결 품질은 역량 질문 검증으로 확인) |
| 6 | `batch-runner` | 작업 상태 4종, 소재별 실패 격리, **동시성 기본값 낮게(설정 가능)**, 429를 분당·일일로 구분(분당은 대기 후 재개, 일일은 멈춤), 비용 상한, 실행 유형 기록. 동시성 기본값은 낮게(8~16까지는 429 없이 안전, 텍스트 60건·동시 30 전부 200). 유료 등급 분당 한도 수치는 미확인 |
| 7 | `pilot-sheet` | **시범 20건은 dev 브랜드에서만**(YouTube·Instagram), 출처별 층화·시드 기록. 블라인드 시트: **모델 라벨과 지표를 숨기고**, 항목 순서를 시드로 섞고, 키 파일은 `data/interim/`에 분리. **시트 생성기만**(채점기는 P3). 키 파일에 **`thinking_level` `minimal`과 기본 두 실행**의 모델 라벨을 모두 둔다(추가 비용 약 $0.2). 비교는 사람 라벨 확정 뒤에만. 시트에는 YouTube 영상 주소와 Instagram `permalink`만 넣고 만료되는 `media_url`은 넣지 않는다. 같은 소재를 두 `thinking_level` 실행으로 분석하므로 `analysis_jobs` 키에 실행 태그(`run_tag`)를 넣거나 `kind`에 붙인다(P1 스키마의 키는 `(source, source_id, kind)`이라 `labels`가 덮어써진다. 원문은 `model_outputs`에 남는다) |
| 8 | `pilot-live-target` | `make live-pilot`: dev 브랜드 소량 수집 → 20건 분석 → 시트 출력. 환경 점검 포함 |
| 9 | `tiktok-source` | 토큰(7200초, 만료 시 재발급), 광고 조회(날짜 문자열, `max`는 어제 이전, `has_more`·`search_id` 페이지 넘김), `error.code == "ok"`로 성공 판정, 500 대기 후 재시도, 도달 구간 하한 변환(방식 기록). 집행 주체는 `config/retailers.yaml`(판매처 목록 시드)로 판정하고 **숫자 이름·목록 밖은 `불명`**(광고주 이름의 40%가 숫자). **쪽 넘김**: 같은 본문에 `search_id`를 더해 보내고(마지막으로 받은 값), 종료는 `has_more == false`(마지막 쪽에도 `search_id`가 오므로 그 유무로 판정하지 않음, 마지막 쪽은 10건 미만 가능). **쪽 사이 중복 광고**(dalba 29건 받아 28 고유, mixsoon 49건 받아 43 고유)라 `ad.id`로 중복 제거. `image_urls`는 이미지 없는 광고에서 키 자체가 없다. 쪽당 2~3초. **TikTok 소재는 E1 표본에서 제외**하고 그래프·에이전트 데이터로만 쓴다 |

끊는 지점: **step 3(`collect-runner`) 뒤** 사용자가 `make live-collect`(11-15~16), **step 8(`pilot-live-target`) 뒤** 사용자가 `make live-pilot`을 돌리고 시범 라벨링을 시작한 상태에서 step 9(`tiktok-source`)를 실행한다. P2는 live 타깃이 둘(`live-collect`, `live-pilot`)이다.

### P3 collect-freeze

| step | 이름 | 내용 |
|---|---|---|
| 0 | `live-fixes` | P2 live 결함 수정(수집·시범 live 결과 반영). 전체 수집은 P2 `collect-runner`에서 끝났다 |
| 1 | `taxonomy-partial` | **11-18 `content_type`·`category` 정의만 부분 동결**(시범 결과 반영, 사용자 승인, ADR 기록). `domain`의 두 축 값 목록과 `docs/TAXONOMY.md`가 같은지 검사하는 테스트. 사전 등록 파일에 부분 동결 날짜 기록 |
| 2 | `e1-sampling` | (분석 불필요, 수집·부분 동결만 필요) **사전 등록 파일을 먼저 커밋**한 뒤 추출. **표본 출처는 YouTube·Instagram만, 표본 프레임은 `analyzable == true`인 소재만**(YouTube 전부, Instagram은 영상이고 수집 시점에 `media_url`이 반환된 것, 릴스의 약 52%). `analyzable`이 None·없음인 소재는 뽑지 않는다. 제외 비율을 결과 문서에 한계로 기록한다(모델 라벨이 없는 소재가 섞이면 콘텐츠 유형 재현율을 정의할 수 없다). **1단계**: **test 브랜드에서만**, 모델 출력과 무관한 **출처×브랜드** 층화로 시드 셔플한 순서의 시트(시트에는 YouTube 영상 주소·Instagram `permalink`만, `media_url` 없음). 사람이 콘텐츠 유형과 **카테고리를 함께** 라벨링하다가 사람이 제품 소재로 판정한 건이 50건 이상이 되면 멈춘다(최소 100건, 상한 200건을 등록 파일에 박음). **2단계**: 사람이 제품으로 판정한 소재에서 **사람 라벨의 출처×카테고리**로 50건을 시드 추출해 나머지 축 시트를 만든다. 7일 재라벨링은 2단계 50건에만. 시트에서 모델 라벨·지표 숨김, 키 파일 분리. **2단계 시트 생성 CLI는 사용자가 직접 돌린다**: README에 키 파일·라벨 파일 경로를 적고, 라벨 파일이 없거나 형식이 틀리면 이유 코드(`LABEL_FILE_MISSING`·`LABEL_FILE_INVALID`)로 중단. **채점기는 이후 step** |
| 3 | `pilot-compare` | 시범 20건의 두 실행(`thinking_level` minimal·기본)을 사람 라벨과 비교하는 작은 CLI(축별 단순 일치율). **사람 라벨 파일이 없으면 시작하지 않는다.** 합성 데이터 테스트, 모델 값 고정 금지, 빈 집합이면 실패 |
| 4 | `cost-recalc` | 원장으로 `COST_ESTIMATE` 재계산 스크립트(시범 두 실행의 비용 포함). **이 step 뒤에 끊고 사용자에게 보고해 `thinking_level`과 Gemini 상한을 확정한 뒤 step 6을 실행한다** |
| 5 | `taxonomy-v1` | **11-19 나머지 축을 포함한 전체 v1 동결**(사용자 승인, ADR 기록), `domain` 값 목록과 문서가 같은지 검사하는 테스트. 사전 등록 파일에 전체 동결 날짜 기록. 이 동결은 2단계 라벨링 전이고 일괄 분석 전이다 |
| 6 | `analyze-target` | `make live-analyze`(재개 가능, **전체 v1 동결 뒤**, **Instagram은 분석 직전에 계정을 다시 조회해 `media_url`을 갱신하고 받은 즉시 처리**, 결정된 `thinking_level`·상한으로, 사용자가 2단계 라벨링하는 동안 돈다), 진행 보고(출처·카테고리별 건수, 실패율, 축별 `other` 비율). **step 6 실행 전에 step 4·5의 사용자 결정이 끝나 있어야 한다** |
| 7 | `metrics-normalize` | 채널 내 조회수 백분위(게시 14일 이상), 상·하위 25%, 출처 간 직접 비교 없음 |
| 8 | `e1-scorer` | 축별 일치율·Cohen's κ·소구점 정밀도·재현율·콘텐츠 유형 재현율(`pilot-compare`의 일치율 함수를 재사용, 그 모듈은 "추가에 한함"). 사람 라벨 파일이 없으면 시작하지 않는다. 합성 데이터 테스트, 모델 값 고정 금지, 빈 집합이면 실패 |

실행 끊는 지점: step 4 뒤(비용·thinking_level 결정), step 5 뒤(전체 v1 승인).

### P4 ontology

| step | 이름 | 내용 |
|---|---|---|
| 0 | `graph-sync` | (P1에서 이동) `graph/` 스키마(복합 유일 제약), PostgreSQL 변경 시각 기준 증분 MERGE, `make sync`, 가짜 드라이버로 멱등·오류 형태 재현, **짧은 live 확인 타깃 `make live-graph`**(step 뒤에 끊어 사용자가 돌림). `uv add neo4j==6.4.1` |
| 1 | `claim-rules` | `config/claim_rules.yaml`(쪽 번호 필수, 세 종류, 한·영 쌍), 로더와 금지어 사전 |
| 2 | `mfds-source` | 원료(정확히 같은 표준명만, 공백 제거 검색), 보고품목(`EE_NAME`, `SPF`·`PA`, 취하 제외), 심사품목(`EE_DOC_DATA` XML 파싱, `null` 허용, 403 오류 형태). 업체명으로 브랜드를 판정하지 않음. **자외선 차단은 `SPF`·`PA`(문자열 `"50+"`, `"4"`)에 값이 있을 때만 `FunctionalCert`로 인정하고, null(선크림·선스크린 60건 전부 null)은 "인증 없음"이 아니라 `unknown`**. `EE_NAME`·`EE_DOC_DATA`로 보완되지 않음. `ClaimRule` 검사에서 `unknown`은 위반으로 단정하지 않고 판정 불가 경고. 보고품목(선크림 4,837건)과 심사품목(1,222건)은 첫 쪽 기준 품목명이 겹치지 않아 **제품마다 두 API를 모두 조회**(겹침 전체 규모는 미확인) |
| 3 | `mall-source` | robots.txt·간격(달바 10초), 가격(메타 / JSON-LD, 정가 0이면 `price_basis`), 텍스트 표 우선·이미지 추출(저장 안 함), 단종 페이지는 가격 메타 유무로 판정, gzip |
| 4 | `product-records` | 제품 레코드, 성분 별칭 표, **광고 소재의 성분 원문을 표준명 사전과 대조해 묶고 목록 밖은 폐기·`미해결`로 보존**(P2는 원문 저장만 했다), `미해결` 성분 보존 |
| 5 | `layer1-graph` | 1층 적재 |
| 6 | `layer2-links` | `PROMOTES`(판정 못 하면 만들지 않음), `CLAIMS`, `MENTIONS` |
| 7 | `cq-verify` | 역량 질문 1~3홉 검증 실행기와 `make live-cq` |

### P5 agents (10 step)

| step | 이름 | 내용 |
|---|---|---|
| 0 | `llm-chat-models` | `llm/`에 OpenAI·Anthropic 경로 추가: **`reasoning_effort` 필수 인자**, `temperature` 기본 미지정(luna·terra `none`만 예외), 스트리밍 비용(`stream_chunk_builder`+`completion_cost`), 도구 호출 인자 JSON 문자열 파싱 실패 처리, Anthropic `cache_control`. 원본은 `litellm_*.json` |
| 1 | `agent-api-skeleton` | (P1에서 이동) 도구 1개, 노드 1개(luna, `reasoning_effort="none"`), 체크포인터 풀(`autocommit`·`dict_row`·`prepare_threshold=0`)은 api가 조립, FastAPI `/chat` SSE, **짧은 live 확인 타깃 `make live-agent`**(step 뒤에 끊어 사용자가 돌림), **서버 진입점 경유 테스트**, 테넌트 컨텍스트 fail-closed |
| 2 | `tool-registry` | 조회·집계·비교·표시 4종, 도구 등록 목록, 구조화 실패, 테넌트 범위 |
| 3 | `checks` | 근거 ID 존재, 분류 값 유효성, 금지 표현, 효능 근거 경로 |
| 4 | `tenant-memory` | 테넌트 전용 저장, 피드백 메모리, thread 소유 테넌트 검증 |
| 5 | `research-agent` | 하위 그래프(전용 상태), 지시서·구조화 핸드오프, 근거 미달이면 "근거 없음" |
| 6 | `planning-evaluation` | 기획(terra)·평가(Sonnet), 코드 검사 + LLM 채점, 되돌림 상태 카운터 최대 2회 |
| 7 | `supervisor-sse` | Supervisor, 한도, 기준일 고정, SSE 4종 |
| 8 | `obs-langfuse` | JSONL(기본), Langfuse(`obs` profile, `langfuse==3.15.0`, `cost_details` 전송) |
| 9 | `agents-live-target` | `make live-agents` |

### P6·P7
P6: E2, E3(벡터 구성은 실측 뒤), E5, 격리 검사 200건, (E4), (E1 타사 모델 라벨링 — 결정에 따라), 결과 문서, 사전 등록. P7: `web/` 골격, 화면, verify의 pnpm 단계, k3d, README. 상세는 P5 착수 시점에 쓴다.

## 4. 필수 항목 ① 외부 계약 실측 목록

| phase | 외부 지점 | CONTRACTS | 원본 |
|---|---|---|---|
| P1 | Gemini Interactions·구조화·구간 | Gemini 표 | `gemini_interactions_36flash_*.json`, `gemini_interactions_response_format_schema.json` |
| P1 | Gemini 오류 | Gemini 표 | `gemini_error_*.json` |
| P1 | LiteLLM 응답·비용·temperature·reasoning | LiteLLM 절 | `litellm_*.json` |
| P1 | YouTube | YouTube 표 | `youtube_*.json` |
| P2 | Instagram | Instagram 표 | `instagram_*.json` |
| P2 | TikTok | TikTok 표 | `tiktok_*.json` |
| P2 | Gemini Files | LiteLLM 절 | `litellm_gemini_files_flow.json` |
| P4 | Neo4j | Neo4j 절 | 원본 없음 |
| P4 | 식약처 | 식약처 절 | `mfds_*.json` |
| P4 | 공식몰 12곳 | 공식몰 절 | 원본 미저장 |
| P5 | LangGraph·Langfuse | 각 절 | `langgraph_checkpointer_probe.json`, `langfuse_probe.json` |

**사전 실측 결과(2차, 2026-11-12, 원본은 `data/interim/advisor/contracts/`, 계약 PR에서 `tests/fixtures/contracts/`로 복사)**: TikTok 쪽 넘김(`tiktok_ad_query_*`, `tiktok_pagination_report.json`), Gemini 큰 파일·실패 형태·thinking·병렬(`gemini_files_failures_thinking_burst_probe.json`), 영상 토큰 밀도(`gemini_video_tokens_per_second_probe.json`), Instagram 만료·식약처 선케어·YouTube 마지막 쪽(`instagram_mfds_youtube_probe.json`). **남은 미확인**: 만료된 Instagram URL의 응답, YouTube `quotaExceeded` 형태와 쿼터 사용량(사용자가 Cloud 콘솔에서 확인), OpenAI·Anthropic 429·503, 유료 Gemini의 실제 분당 한도 수치, 보고·심사 두 API 겹침의 전체 규모, Anthropic thinking, 캐시 최소 길이, Instagram `permalink` 키 부재 사례(표본 8건에서는 모두 있었음), 3일 뒤 Instagram `media_url` 반환 여부 일관성(5초·15분·약 20시간 뒤는 일관함을 실측, `analyzable` 수집 시점 저장의 전제), **E3 벡터 비교 구성**(임베딩 모델의 요청·응답·비용, 벡터 저장소 — pgvector면 compose의 postgres 이미지가 확장 포함 이미지로 바뀌므로 P5 전에 실측하고 compose 변경은 P5 `live-fixes`나 별도 step에 넣는다), **E1 타사 모델 라벨링**을 하기로 하면 텍스트·캡션 입력 형태.

## 5. 필수 항목 ② 첫 live에서 터질 수 있는 것

모든 live 타깃은 시작 전에 점검하고 실패하면 이유 코드로 멈춘다.

| 위험 | 막는 점검·설계 |
|---|---|
| OrbStack 꺼짐 | Docker 데몬 응답 점검 `DOCKER_DOWN` |
| B 스택과 포트 충돌 | 호스트 포트 고정(5433 등), 사용 여부 점검 `PORT_IN_USE` |
| Neo4j 비밀번호는 첫 볼륨에만 적용, 8자 미만이면 기동 실패 | `settings`가 8자 미만 거부, 인증 실패 시 `NEO4J_AUTH_VOLUME_STALE`과 `make graph-reset` 안내 |
| `.env` 키 누락 | 키 이름 존재 점검 `ENV_MISSING:<이름>`(값 출력 안 함) |
| Gemini 429 일일/분당, 503, 150초 지연 | 429 구분, 일일이면 중지·대기 보존, 호출 시간 제한, 503만 재시도 |
| 공급사 누적 상한 | 호출 직전 원장 합계 `COST_CAP:<공급사>` |
| 테스트가 실제 원장을 오염 | 원장 경로 주입, 테스트는 tmp 경로만(P1 step 4 금지사항) |
| luna `reasoning_effort` 미지정 비용, `temperature` 400 | 래퍼 필수 인자·기본 미지정 |
| 스트리밍 `response_cost` None | `stream_chunk_builder`+`completion_cost` |
| 삭제 뒤 `file_retrieve` ValueError | `deleted: true`로만 판단 |
| 단종 상품 HTTP 200 | 가격 메타 유무 |
| 체크포인터 풀 설정, 상태 속 pydantic, 하위 그래프 키 공유, 컨텍스트 없을 때 TypeError | P5 step 0·4에서 테스트로 고정(`LANGGRAPH_STRICT_MSGPACK=true`) |
| Langfuse `auth_check` ConnectError, `LANGFUSE_INIT_*`·DB 생성 스크립트, 같은 키 재생성 | P5 step 7 (JSONL 폴백, 클라이언트 하나) |
| 토큰 만료(Instagram 60일, TikTok 7200초) | TikTok 재발급, Instagram 임박 경고 |
| Gemini 상한 $12 도달(기본 thinking이면 1,500건 전에) | `thinking_level` 기본 `minimal`, 구간 상한 60초, 길이 컷, 호출 직전 상한 검사. 상한은 사용자 결정(§8) |
| 긴 YouTube 영상(14분 → 79,435토큰) | `duration_s` 길이 컷과 `end_offset` 60초 |
| Instagram 서명 URL 만료(32시간 이상 남음) | 받은 즉시 처리, `oe` 임박 시 재조회, 저장 URL 재사용 금지 |
| Gemini Files 실패(빈 파일 `ValueError`, 비영상 `status: error`, 삭제된 파일 403) | 사전 크기 검사, `processed`일 때만 분석, 오류 분류 |
| TikTok 쪽 간 중복·`search_id` 종료 오판 | `ad.id` 중복 제거, `has_more`로만 종료 |
| `import litellm`이 기본으로 GitHub에서 가격표를 내려받음(검증이 네트워크를 쓰고 가격이 실행마다 달라짐) | P1 step 5가 `LITELLM_LOCAL_MODEL_COST_MAP=True`를 `llm/__init__.py` 맨 앞에서 설정하고 `ast`로 순서를 검사 |
| PostgreSQL 비밀번호는 데이터 볼륨을 처음 만들 때만 적용(Neo4j와 같은 함정) | TCP 점검은 통과하고 `connect`에서 터지므로 `POSTGRES_AUTH_FAILED`로 변환, README에 조치. PostgreSQL 볼륨 삭제 타깃은 만들지 않음 |
| 가짜로만 통과한 SQL·Cypher | live 결함은 다음 phase `live-fixes` step, 결과 PR로 기록 |

## 6. 필수 항목 ③ 기존 단언과의 충돌 점검

`rg -n "== \d+|\[-1\]|splitlines\(\)|== \{|== \[|toHaveLength|set\(.*\) ==|iterdir|glob\("`를 `scripts/test_*.py`와 `tests/`에서 돌렸다(2026-11-12).

- `tests/`에는 픽스처뿐이라 기존 단언이 없다. 새 테스트는 파일 목록·개수 단언 대신 이름 집합·불변식을 쓴다(B-FP-061).
- `scripts/test_step_files.py:24`는 실제 `phases/*/step*.md`를 전부 검사한다. 새 step 파일이 형식 v2를 어기면 `make verify`가 깨진다. 쓴 직후 `uv run python scripts/step_file_checks.py phases/<phase>/step*.md`로 점검하고 소비자 경고는 수정 허용 경로에 "~에 한함, 단언 약화 금지"로 넣는다.
- `scripts/test_hooks.py`는 `exempt_paths.json`을 복사해 쓴다. 원장 경로를 바꾸지 않으므로 충돌 없음.
- P1 step 4가 `tests/test_settings.py`를 건드리므로 그 step의 수정 허용 경로에 "추가에 한함, 단언 약화 금지"로 넣었다. P5 step 1(agent-api-skeleton)은 `tests/test_architecture.py`의 SDK 표(`fastapi`·`langgraph`·`psycopg` 허용 계층) 단언을 갱신하므로 같은 방식으로 넣는다.
- SSE 이벤트·도구 집합 단언은 등록 목록에서 뽑은 이름 집합과 비교한다.

## 7. 필수 항목 ④ 머지 뒤 사용자 할 일

| 시점 | 할 일 |
|---|---|
| 셋업 직후 | `uv sync`, OrbStack 켜기, `.env`의 `NEO4J_PASSWORD`(8자 이상)·`POSTGRES_PASSWORD` 채우기 |
| P1 머지 뒤 | `docker compose up`, `make live-slice`, 결과 알리기 → 결과 문서 PR |
| P2 step 3 뒤 | `make live-collect`(11-15~16) |
| P2 step 8 뒤 | `make live-pilot` → **시범 20건 라벨링(11-17~18)**. 이어서 step 9 실행 |
| P3 | 11-18~19 **E1 1단계 라벨링**, 11-19 분류 v1 승인, 2단계 시트 생성 CLI 실행, **11-20까지 2단계 라벨링(축 50건)**, `make live-analyze`(라벨링 중 돌림, 12월 안, 되도록 11-24까지) |
| P4 | step 0 뒤 `make live-graph`, 11-20 역량 질문 최종 검토, 대표 단품 목록 확인, `make live-cq` |
| P5 | step 1 뒤 `make live-agent`, **11-26까지 평가셋**(§8), 이미지 시안 모델 결정(보류 중), 격리 표식 데이터 확인 |
| P6 | **11-27 E1 재라벨링(축 50건)**, 실험 실행 |
| P7 | `pnpm install`, k3d 설치, 시연 녹화 |
| 각 live 뒤 | 결과 문서 PR |

## 8. 결정 현황

**확정(사용자가 조언 세션 화면에서 직접 확정, 원래 조언 세션이 전달, 2026-11-12)**
1. P1 축소. P4 step 0·P5 step 1 뒤 `make live-graph`·`make live-agent` 유지, P1b는 선택.
2. 평가셋: EVAL 숫자를 test로 읽고 dev는 요청 10·질문 10 추가(총 요청 30·질문 50). 모델이 역량 질문에서 후보를 뽑고 사용자가 고르고 고치며 정답은 그래프 질의로 계산해 사람이 확인.
3. dev:test 5:9 + 사전 등록 제약(양쪽에 카테고리 3개·YouTube·Instagram, test가 E1·E4 수집량을 채울 것, 라벨링 전 1회 재분할 허용).
4. TikTok 집행 주체 규칙(판매처 목록 시드, 숫자 이름·목록 밖은 `불명`).
5. E1 표본 출처는 YouTube·Instagram 한정(TikTok은 그래프·에이전트 데이터로만). 시트는 Instagram `permalink`·YouTube 영상 주소, `media_url` 사용 금지. 결과 문서에 한계로 기록.
6. Gemini 상한 $12 유지, 분석은 `thinking_level` 기본 `minimal` + 구간 상한 60초 + 길이 컷. `pilot-compare`와 `cost-recalc` 뒤에 `thinking_level`·상한을 확정(올린다면 $14까지). **`analyze-target` 실행 전에 결정.**
7. 시간표 추정은 시범 20건 소요를 잰 뒤 11-18 이후를 다시 쓴다.
8. 이미지 시안 모델은 P5 전까지 보류.
9. E1 절차 3번(타사 모델 라벨링): **기본값은 "미수행, 결과 문서에 한계로 기록"**(영상 입력 방법이 계약에 없고 영상 삭제 규칙과 충돌). 일정에 여유가 생기면 텍스트·캡션 축에 한해 P6에서 재검토.

10. **`ingredients`는 E1 판정 축에서 제외 확정**(2026-11-12). `docs/results/e1_preregistration.md`에 기록하고 그래프 연결 품질은 역량 질문 검증으로 확인한다.
11. **TikTok 유지 확정**: 수집·분석·그래프·에이전트 데이터로 계속 쓰고 E1 표본에서만 제외한다. 결과 문서에 "모델 정확도는 YouTube·Instagram 소재로만 측정, TikTok 소재 분석 정확도는 미측정"을 한계로 적는다.
12. **v3 전체 승인**(2026-11-12).

**아직 확정되지 않은 것**
- 이 문서의 소요 시간은 전부 추정이다.
