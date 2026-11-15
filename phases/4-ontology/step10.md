# Step 10: cq-verify

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조, 온톨로지 절, 데이터 흐름
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P4 절과 변경 기록 #36
- `/docs/COMPETENCY_QUESTIONS.md` — v1(2026-11-15 동결), 홉 정의와 한계
- `/docs/COMPETENCY_QUESTIONS.md` — v1 16개 중 CQ-07을 뺀 15개 질문, 탐색 경로, 홉 정의, 한계와 조건(**질문별 한계를 실행기 출력에 그대로 옮긴다**)
- `/docs/ADR.md` — ADR-012 후속 결정, ADR-011(도구 종류)
- `/docs/EVAL.md` — E3 질문 세트 설명(**동결 기준 숫자는 읽기 전용**)
- `/src/beautyads/graph/`, `/src/beautyads/pipeline/sync.py`, `/src/beautyads/eval/` — 그래프 계층, 평가 계층 구조, `Makefile`의 live 타깃 방식

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/graph/queries.py`(새 파일), `src/beautyads/eval/cq_verify.py`(새 파일), `Makefile`, `README.md`, `tests/test_graph_queries.py`, `tests/test_cq_verify.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/graph/queries.py`, `src/beautyads/eval/cq_verify.py`, `Makefile`(`live-cq` 타깃과 `.PHONY` 추가에 한함, 기존 타깃·`verify` 불변), `README.md`(live-cq 절 추가에 한함), `tests/test_graph_queries.py`, `tests/test_cq_verify.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

소비자 테스트 점검 결과: `tests/test_compose.py`·`tests/test_slice.py`·`tests/test_collect.py`·`tests/test_pilot.py`는 저장소 `Makefile`을 읽고 `.PHONY`는 부분집합으로, 기존 타깃의 레시피 원문은 정확히, `verify` 레시피는 `live-`가 없음을 단언한다. 따라서 **새 타깃은 추가하되 기존 타깃의 레시피 원문·`verify` 레시피·형식은 바꾸지 않는다.** 이 테스트 파일들은 수정하지 않는다. 깨지면 고치지 말고 `blocked`로 보고한다.

역량 질문(`docs/COMPETENCY_QUESTIONS.md` v1)이 **1~4홉 탐색으로 답해지는지** 검증하는 실행기와 `make live-cq`를 만든다. **이 step 안에서는 실제 접속·실행을 하지 않는다.**

- **질문 도구(`graph/queries.py`)**: 질문마다 고정 Cypher 하나와 파라미터 이름 목록, **선언한 홉 수**를 가진 상수 표다. 에이전트가 Cypher를 쓰지 않으므로 입력은 분류의 닫힌 값(`Claim`·`Category`·`HookType` 등)과 기준일뿐이다. 값은 항상 파라미터다. 테스트가 각 Cypher 패턴의 **관계 수를 세어 선언한 홉 수와 같고 4 이하임을 확인한다**(속성 필터는 세지 않는다, 홉의 정의). 입력에 테넌트·사용자·오늘 날짜 칸을 두지 않는다 — 기준일은 실행기가 정해 파라미터로 넣는다.
- **실행기(`eval/cq_verify.py`)**: 질문 15개(CQ-01~06, 08~16)를 각각 실행해 한 줄씩 출력한다: 질문 ID, 선언 홉 수, 실행 성공 여부(오류 코드), 결과 행 수, **연결된 소재 수(`PROMOTES` 커버리지: 해당 질문의 답에 쓰인 `Creative` 중 `PROMOTES`로 제품에 이어진 수 / 질문 범위의 제품 소재 수)**, 질문별 한계 문구(`docs/COMPETENCY_QUESTIONS.md`의 한계와 조건을 상수로 옮긴 것). 요약에 홉 기준(1~4홉)을 충족한 질문 수(실행이 오류 없이 끝나고 선언 홉 수 ≤ 4)와 결과가 0행인 질문 수를 **따로** 낸다(0행은 "데이터 부족"이지 "그래프 설계 실패"가 아니다. 두 판정을 섞지 않는다, B-FP-040).
- **질문별 범위**: CQ-09는 `source == 'tiktok'`로 한정하고 집행 주체 속성으로 나눈다(한계: 소규모 시드 표본, `config/retailers.yaml` 사용자 확인 대기). CQ-12는 **합성 데이터로만** 검증한다: 실행기는 임시 테넌트 표식 데이터를 만들지 않고 그래프에 있는 `Feedback`이 없으면 `SKIPPED_SYNTHETIC_ONLY`로 보고한다(P5 피드백 메모리 이후 실데이터 검증). CQ-03·10·11은 제품과 식약처 품목 연결의 커버리지(`certified`·`unknown`·제품 수)를 답과 함께 낸다. CQ-06은 조회수 값이 없는 소재를 백분위에서 빼고 뺀 수를 낸다(조회수 상위는 출처별로 값이 있는 소재에서만).
- **`make live-cq`**: `python -m beautyads.eval.cq_verify`. 점검(`ENV_MISSING:NEO4J_PASSWORD`, `DOCKER_DOWN`, `NEO4J_UNREACHABLE`, 그래프가 비어 있으면 `GRAPH_EMPTY` — 먼저 `make sync`) 뒤 시작한다. 결과는 출력만 하고 `docs/EVAL.md`의 기준 숫자를 바꾸거나 새 판정 기준을 만들지 않는다. 모델 호출 없음, 비용 0.
- `eval`은 다른 모든 계층을 import할 수 있고 다른 계층은 `eval`을 import하지 않는다(질문 도구가 `graph`에 있는 이유).

### 반드시 있어야 하는 테스트

(가짜 드라이버로 문장·파라미터만 검사한다.)
- 질문 표: 질문 ID 집합이 `docs/COMPETENCY_QUESTIONS.md`의 표에서 읽은 ID 집합(CQ-07 제외)과 같다(**개수를 `== 15`로 박지 않는다**, 문서에서 읽은 집합과 비교, B-FP-061), 모든 질문의 선언 홉 수가 1~4이고 Cypher 패턴의 관계 수와 같다, 속성 필터는 세지 않는다, 입력에 테넌트·사용자·날짜 칸이 없다, 값이 문자열에 끼지 않는다.
- 실행기: 오류 없이 끝난 질문과 0행인 질문이 따로 집계된다, 질문 하나의 오류가 다음 질문을 막지 않는다(A-FP-030), 오류 본문의 종류별 코드(`Neo.ClientError.Statement.SyntaxError`→`CQ_SYNTAX_ERROR`, 연결 실패→`NEO4J_UNREACHABLE`)가 구분된다.
- 커버리지: 합성 결과로 `PROMOTES` 커버리지 수가 손계산 값과 같다, `PROMOTES`가 0건이면 0이라고 보고하고 오류가 아니다, 질문별 한계 문구가 출력에 붙는다.
- CQ-09는 TikTok 한정 파라미터가 걸리고 CQ-12는 피드백이 없으면 `SKIPPED_SYNTHETIC_ONLY`다.
- 점검: 이유 코드가 해당 조건에서 나오고 점검 실패 시 드라이버 생성이 **한 번도** 없다, 빈 그래프는 `GRAPH_EMPTY`.
- `Makefile`에 `live-cq`가 있고 `verify` 레시피에 `live-`가 없다, `tests/test_architecture.py` 통과.

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

- `make live-cq`를 실행하지 마라. 이유: 실제 Neo4j 접속은 사용자가 한다.
- 질문 도구에 자유 Cypher 입력을 만들지 마라. 이유: 에이전트에게 Cypher를 쓰게 하지 않는다(ARCHITECTURE).
- 결과가 0행이거나 답이 작다는 이유로 질문을 바꾸거나 홉 기준을 완화하지 마라. 이유: 질문 세트는 v1 동결본이고 E3의 관계형 질문 세트로 쓰인다.
- `docs/EVAL.md`·`docs/COMPETENCY_QUESTIONS.md`의 기준·질문을 고치지 마라. 이유: 동결본.
- 합성 `Feedback` 데이터를 실제 그래프에 쓰지 마라. 이유: 테넌트 데이터는 P5 피드백 메모리가 만든다.
- 0행과 실행 실패를 한 판정으로 합치지 마라. 이유: B-FP-040(아무것도 안 해서 통과하는 지표 금지).
