# Step 5: demo-kit

## 설계 검토 기록

**배경(P7 설계 승인 6, 시연 자료)**: 영상 촬영은 사용자가 하고 편집과 최종 산출물은 조언 세션이 한다. 이 step은 **촬영할 수 있는 상태**까지 만든다: `DEMO.md`(장면별 절차와 시연용 요청 문장), 시연 환경을 한 줄로 띄우는 `make demo-up`, 촬영 중 우발 오류를 줄이는 점검 목록, 사용자가 live로 직접 확인할 **리허설 확인 항목**, 상세 페이지 원고 초안, P7 결정·겪은 문제의 기록이다. **시연은 정상 흐름만 다룬다. 장애 주입·표식 조회류·격리 검사 시연은 DEMO.md와 화면 시나리오에 넣지 않는다**(사용자 원칙).

**사용자 확정 사항(P7 승인, 글자 그대로 따른다)**:
- 시연 작업 공간: test A = `test-isntree`(이즈앤트리 초저분자 히아루론산 세럼 50ml, 근거가 확인된 효능 **2개: 보습·피부 장벽**), test B = `test-bojoseon`(조선미녀 인삼선세럼 SPF 50+, **5개: 보습·미백·피부 장벽·주름 개선·자외선 차단**)(2026-11-20 읽기 전용 확인, 모델 호출 없음). dev(`dev-mixsoon`·`dev-cosrx`)는 개발 반복용이라 시연에 쓰지 않는다.
- 시연 구성(승인 Q8): **평가 모델 sonnet(최종 구성과 동일), 시안 이미지 포함, 화면에 요청 비용 한 줄**. 서버 기동과 화면 요청은 사용자가 하며 그것이 비용 승인이다. 기존 원장 상한 검사는 그대로다.
- 작업 공간 그룹(승인 Q9): 시연은 `BEAUTYADS_GROUP=test`, 개발은 `dev`로 **서버를 재기동**한다. 동시 사용 불가를 DEMO.md와 화면 안내에 적는다(화면 안내는 이미 있다).
- 촬영은 **`pnpm build`·`pnpm start`(운영 모드)**로 한다(`pnpm dev`는 화면에 개발 모드 아이콘 N이 나온다).
- **시연 문장(확정)**: test A "보습을 내세운 세럼 광고 기획안 1안을 만들어 주세요.", test B "자외선 차단을 내세운 선케어 광고 기획안 1안을 만들어 주세요.", 되묻기 ② A "진정 효과를 내세운 세럼 광고 기획안 1안을 만들어 주세요."·B "모공과 피지 관리를 내세운 선케어 광고 기획안 1안을 만들어 주세요.", 되묻기 ③ A "이 세럼의 광고 기획안 1안을 만들어 주세요."·**B "이 선세럼 제품의 광고 기획안 1안을 만들어 주세요."**(B는 인삼선세럼이다. **이 문장의 test B 해석은 live 리허설 전에는 확인되지 않았다**). 이 문장들은 `web/lib/examples.ts`의 칩과 같아야 한다.
- 장면 구성은 제안서 §2의 7장면이다: 1 시작 화면, 2 정상 요청, 3 되묻기 ②, 4 되묻기 ③, 5 결과 읽기(근거 카드·분포·aggregates·시안·승인·반려), 6 그래프(근거 그래프와 전체 스키마), 7 trace(Langfuse, 캡처용).
- **"에이전트별 지연과 비용을 Langfuse에서 관측했다"는 문구는 사용자가 실제 화면에서 지연(타임라인)이 보이는 것을 확인한 뒤에만** DEMO.md·README·상세 페이지에 쓴다. 이 step에서는 "확인 후 사용" 표시(`[Langfuse 타임라인 확인 후 사용]`)를 붙인 문장으로만 둔다.
- 사용자가 live로 리허설해서 확인해야 하는 항목(DEMO.md "리허설 확인" 절에 체크 목록으로): ① `make demo-up` 기동과 `/healthz`, ② **SSE 프록시 버퍼링**(단계 표시줄이 단계마다 갱신되는지, 끝에 한꺼번에 나오면 `web/next.config.ts`의 `compress: false`가 효과가 없다는 뜻이고 대안은 서버 CORS), ③ 시연 문장별 결과 종류(정상 요청이 되묻기·근거 없음으로 나오지 않는지, **특히 test B 되묻기 ③ 문장**), ④ **시연 요청에서 나온 근거 카드 중 분석 속성이 있는 카드가 몇 장인지**(분석된 소재만 라벨이 있다: 그래프 소재 7,429개 중 1,172개, 2026-11-20 읽기 전용 확인), ⑤ 시안 이미지 표시, ⑥ 승인·반려 저장, ⑦ 실제 YouTube 썸네일과 실패 시 아이콘 복귀, ⑧ 그래프 실데이터 렌더, ⑨ Langfuse 타임라인에서 에이전트별 지연이 보이는지(`make obs-up` → `make obs-check`).

**코드에서 확인한 사실(설계에 반영)**: `make serve`(`api/main.py`)는 `BEAUTYADS_GROUP`(기본 `dev`, 허용 `dev`·`test`)·`BEAUTYADS_EVAL_MODEL`·`BEAUTYADS_WITH_IMAGE`·`BEAUTYADS_API_PORT`를 읽고 `127.0.0.1`에서 8000번으로 서비스한다. 웹은 `web/`(`pnpm build`·`pnpm start`, 포트 3000)가 `/api/*`를 `http://127.0.0.1:8000`으로 프록시한다. 기존 `Makefile`에는 `db-up`(compose의 postgres·neo4j)이 있고 `demo-clarify`(개발용 되묻기 점검)가 있다. 새 타깃 이름 `demo-up`은 `verify` 본문에 들어가면 안 된다(`tests/test_clarify_demo.py`가 `demo-`를 검사한다).

**기존 단언과의 충돌 점검**: `Makefile` 소비자 테스트(`tests/test_clarify_demo.py`의 `demo-` 금지, `tests/test_compose.py`의 `db-`·`graph-`·`live-` 금지, `tests/test_pilot.py`의 `verify` 본문 정확 일치)는 `verify` 본문을 읽으므로 **`verify`를 바꾸지 않고** 파일 끝에 별도 `.PHONY: demo-up` 블록만 더한다. `README.md`·`docs/PHASES.md`·`docs/TROUBLESHOOTING_LOG.md`는 **추가만** 한다(기존 문장·행·항목은 고치지 않는다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/PRD.md`(시연과 포트폴리오 산출물: 상세 페이지 구성 순서, 수치 표 규칙), `/docs/ARCHITECTURE.md`, `/docs/ADR.md`
- `/docs/results/2026-11-20-p6-final.md`, `/docs/results/2026-11-19-e1-scoring.md`, `/docs/results/2026-11-18-p5-live-agents.md`(읽기 전용: 모든 수치는 여기서만 가져온다), `/docs/COST_ESTIMATE.md`, `/docs/TROUBLESHOOTING_LOG.md`, `/docs/PHASES.md`(결정 표)
- `/Makefile`, `/README.md`, `/web/lib/examples.ts`, `/web/components/`(화면 구성, 읽기 전용), `/web/next.config.ts`
- `/src/beautyads/api/main.py`, `/config/workspaces.yaml`(읽기 전용), `/.env.example`
- `/tests/test_clarify_demo.py`(`test_make_target_leaves_verify_offline`), `/tests/test_pilot.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `DEMO.md`, `docs/portfolio/DETAIL_PAGE.md`, `Makefile`, `README.md`, `docs/PHASES.md`, `docs/TROUBLESHOOTING_LOG.md`, `tests/test_demo_docs.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `DEMO.md`, `docs/portfolio/DETAIL_PAGE.md`, `Makefile`, `README.md`, `docs/PHASES.md`, `docs/TROUBLESHOOTING_LOG.md`, `tests/test_demo_docs.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1. `Makefile`**: 파일 끝에 `.PHONY: demo-up` / `demo-up:`을 더한다. 한 줄 요약: compose의 postgres·neo4j를 올리고(`$(MAKE) db-up`) 한 셸에서 api(`BEAUTYADS_GROUP=test BEAUTYADS_EVAL_MODEL=claude-sonnet-5-5 BEAUTYADS_WITH_IMAGE=1 uv run python -m beautyads.api.main`)와 웹 운영 모드(`cd web && pnpm build && pnpm start`)를 함께 띄우고 Ctrl+C로 둘 다 끝나게 한다(`bash -c 'trap "kill 0" EXIT; ... & ... & wait'` 형태). 시작 전에 `.env`·키 값을 출력하지 않는다. 사용 안내 한 줄 주석(`# make demo-up: 시연(test 그룹, sonnet, 시안 포함, 웹 운영 모드). 개발은 make serve`). 기존 줄·`verify` 레시피는 바꾸지 않는다.

**2. `DEMO.md`(새, 저장소 루트)** — 아래 절을 이 순서로:
- `## 한 줄로 시연 환경 띄우기`: `make db-up`이 먼저 필요한지(처음 한 번 `make db-migrate`), `make demo-up`, 접속 `http://127.0.0.1:3000`, 종료는 Ctrl+C, 서비스(Docker) 선행 조건. **dev와 test 그룹은 동시에 쓸 수 없다**(서버를 재기동해야 함)를 명시.
- `## 시연 구성과 비용`: 평가 모델 sonnet·시안 포함, 화면의 요청 비용 한 줄은 텍스트 모델 비용(이미지 제외), 비용 승인은 사용자가 서버를 켜고 요청을 보내는 것, 원장 상한 검사는 그대로(상한 숫자는 `AGENTS.md`에서 읽어 옮긴다).
- `## 장면별 절차`: 장면 1~7. 장면마다 **입력 문장(확정 문장 그대로)·화면에서 확인할 것·촬영 포인트**를 표 또는 목록으로. 장면 2는 A·B 각각, 장면 3·4는 A·B 각각의 문장. 장면 3·4의 선택 후 흐름(선택지 → 재요청 → 기획안)을 적는다. **정상 흐름만**: 오류·한도·효능 조회 불가·중단 선택을 시연 절차에 넣지 않는다.
- `## 촬영 안내`: 30초 이내 영상은 요청 하나가 끝까지 처리되는 장면(장면 2)으로 구성, 운영 모드(`pnpm build`·`pnpm start`) 사용 이유(개발 모드 아이콘), 화면 캡처 3장(대화 화면·그래프 화면·trace 화면) 목록과 "재가공 없이 원본 그대로"(PRD).
- `## 촬영 전 점검 목록`(우발 오류 줄이기): Docker 컨테이너 상태, 포트 충돌(3000·8000·5433·7688·3001), `.env`에 필요한 **이름**이 있는지(값을 화면·로그에 내지 않는다), 비용 원장 잔여 상한 확인 방법(원장 합계를 읽는 한 줄 명령: `uv run python -c` 형태로 `beautyads.obs.ledger.provider_total`만 호출하고 공급사별 합계 숫자만 출력, 키·경로 외 값 출력 없음), 브라우저 확장·알림 끄기, 해상도, 첫 요청 후 캐시 영향, 마지막 요청 비용 확인.
- `## 리허설 확인`: 위 ①~⑨를 **체크 목록**으로(항목마다 "무엇을·어떻게 확인·결과 기록 칸"). 이 절의 확인은 모두 **사용자가 live로** 한다고 명시. ⑨에는 Langfuse 문구 사용 조건을 적는다.
- 금지: "장애", "주입", "표식", "격리 검사" 시연 절차를 넣지 않는다(리허설 확인 ⑥의 승인·반려 저장은 정상 흐름이다).

**3. `docs/portfolio/DETAIL_PAGE.md`(새, 상세 페이지 원고 초안)**: `docs/PRD.md`의 상세 페이지 순서를 따른다: 30초 요약 → 수치 → 기술 스택 → 시연 영상·그래프 화면 → 배경(이전·이후) → 핵심 전략 3개 → 아키텍처와 선택 이유 → 데이터 파이프라인 → 부딪힌 문제와 해결 3건 → 성과와 회고. 규칙(사용자 원칙 — 구직용이라 "푼 문제와 측정된 긍정 결과"가 보이게, 사실과 다른 문구는 쓰지 않는다):
  - **수치 표**: 열 `값 | 종류 | 기준일 | 측정 조건 | 출처`. `종류`는 `측정값`·`관측값`·`설계 추정` 중 하나. **모든 수치는 `docs/results/`의 결과 문서에서 그대로 옮기고**(도구 수는 코드의 등록 목록 `agents/tools.py`에서) `출처`에 파일 경로와 절 번호를 적는다. 해석·반올림·합산·비교 우위를 덧붙이지 않는다.
  - 결과 문서의 판정 이름은 그대로 쓴다(예: E2 `single_better`, E3 `not_adopted`, E5 `not_met:both`, 격리 `observed_zero`). **"그래프가 벡터 검색보다 정답률이 높다" 같은 결과 문서에 없는 우열 문장을 쓰지 않는다.** 긍정 결과로 앞세우는 것은 결과 문서가 실제로 측정한 것(예: 격리 200건 노출 0·정상 응답 100%·스레드 접근 25/25 거부, E1 축별 κ 중 기준을 넘은 것, 근거 ID 코드 검사)에 한하고, 미달·반대 결과는 "성과와 회고"에 판정 이름 그대로 적는다(앞세우지 않되 숨기지 않는다).
  - "부딪힌 문제와 해결 3건"은 `docs/TROUBLESHOOTING_LOG.md`에서 **실제로 일어난 일**만 고른다(문제·원인·해결·결과·근거). 일어나지 않은 일은 쓰지 않는다.
  - Langfuse 문장은 `[Langfuse 타임라인 확인 후 사용]` 표시를 붙여 둔다. "배경(이전·이후)"·시연 영상 링크처럼 이 저장소에서 알 수 없는 내용은 `[사용자 작성]`으로 비워 둔다(지어내지 않는다).

**4. `README.md`**: 끝에 `## 시연 (DEMO.md)` 절을 **추가**한다: `DEMO.md` 링크, `make demo-up` 한 줄, 개발은 `make serve`, k3d(`step 4`의 절차)와의 관계. 기존 절은 고치지 않는다. Langfuse(`make obs-up`·`make obs-check`) 사용 방법을 한 단락 더하고 위 문구 사용 조건을 적는다.

**5. `docs/PHASES.md`**: 결정 표 끝에 P7 결정 행 **하나를 추가**한다(번호는 표의 다음 번호): 시연 구성(sonnet·시안·test 그룹), 7a(web-core)·7b(ops-demo) 분할, 카드 분석 속성·`show_cost` 등 서버 추가 승인, 승인 목록 밖 동반 패키지 5개와 조정된 버전(typescript 6.0.3·eslint 9.39.5·vite 7.3.8), Langfuse ingestion 방식과 미확인 항목. 기존 행은 고치지 않는다. **`docs/TROUBLESHOOTING_LOG.md`**: 이 저장소에서 P7 동안 **실제로 겪은 문제**만 형식(문제/원인/해결/근거)에 맞춰 끝에 추가한다: (a) 클린 클론에서 `make verify`가 1건 실패한 키 의존 테스트(`tests/test_products_pipeline.py::test_model_contract_cost_summary_and_bytes_never_written`, step 1), (b) 웹 의존성 버전 조정(typescript 7.0.2·eslint 10.15.0이 Next 16.4.6과 호환되지 않아 6.0.3·9.39.5로 조정, 7a step 4), (c) step 파일의 요구와 금지사항이 서로 모순돼 선점검에서 blocked된 두 건(7a step 2: 스키마 레이블, 7a step 4: 승인 표기, 조치: step 파일만 수정).

**테스트(`tests/test_demo_docs.py`, 합성 데이터, 파일만 읽는다)**: (1) `DEMO.md`에 위 확정 문장 6개가 **글자 그대로** 있고, `web/lib/examples.ts`의 `test-isntree`·`test-bojoseon` 칩 문장과 같다(검사한 문장이 0이면 실패, B-FP-069). (2) `DEMO.md`에 절 제목 `한 줄로 시연 환경 띄우기`·`시연 구성과 비용`·`장면별 절차`·`촬영 안내`·`촬영 전 점검 목록`·`리허설 확인`이 이 순서로 있고 장면 1~7이 모두 있다. (3) `DEMO.md`에 `장애 주입`·`표식 조회`·`격리 검사`가 없다. (4) `DEMO.md`·`README.md`·`DETAIL_PAGE.md`의 Langfuse 지연 문장은 모두 `[Langfuse 타임라인 확인 후 사용]` 표시를 같은 줄에 가진다(`관측했다`가 있는 줄 기준). (5) `DETAIL_PAGE.md`의 수치 표 행마다 `종류`가 닫힌 목록 안이고 `출처`가 `docs/results/` 아래 **실제로 있는 파일**(또는 `agents/tools.py`)이며, `그래프가 벡터`·`정답률이 높`·`더 낫다` 같은 우열 문구가 없다. (6) `Makefile`의 `demo-up`이 별도 `.PHONY` 블록이고 `verify` 본문에 `demo-up`이 없다. (7) `docs/PHASES.md`·`docs/TROUBLESHOOTING_LOG.md`의 기존 줄이 그대로이고(이 step 이전 `git`을 읽지 말고 **추가된 항목의 존재**만 검사) P7 행·세 항목이 있다.

## Acceptance Criteria

```bash
make verify   # ruff + pytest + pnpm lint·typecheck·test 통과
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

- `make demo-up`·`make serve`·`make db-up`·`make obs-up`·`make obs-check`·`pnpm start`를 실행하지 마라. 문서의 명령을 실제로 돌려 보지 마라. 이유: 서버 기동·모델 호출(비용)·컨테이너는 사용자가 한다(AGENTS.md CRITICAL, A-FP-040). 문서는 코드에서 읽은 사실만 쓴다.
- `docs/results/`·`docs/EVAL.md`의 동결 기준·`data/evalset/`을 수정하지 마라. 수치를 결과 문서 밖에서 가져오거나 계산하지 마라. 이유: 모든 수치는 결과 문서에서만 가져온다(PRD). 동결 기준은 결과를 본 뒤 바꾸지 않는다(AGENTS.md CRITICAL).
- 결과 문서에 없는 우열·성능 주장(그래프가 벡터보다 낫다, 기획 품질이 높다 등)을 DEMO.md·README·원고·화면 문구에 쓰지 마라. 이유: 사실과 다른 문구를 만들지 않는다(사용자 원칙, E3 비교 구성의 한계는 `docs/results/2026-11-20-p6-final.md` 3.2).
- 시연 절차에 장애 주입·표식 조회·격리 검사·오류 유도를 넣지 마라. 일어나지 않은 일을 "부딪힌 문제"로 쓰지 마라. 이유: 사용자가 시연에서 뺀 항목이고, 상세 페이지의 문제 기록은 실제로 일어난 일만 쓴다(PRD).
- `Makefile`의 `verify`·기존 줄, `docs/PHASES.md`·`docs/TROUBLESHOOTING_LOG.md`·`README.md`의 기존 문장을 고치지 마라. `src/`·`web/`는 읽기만 하고 수정하지 마라(`.env`는 열지도 마라). 이유: 이 step은 문서와 타깃 하나뿐이다(소비자 테스트가 `verify` 본문을 단언한다, B-FP-060).
