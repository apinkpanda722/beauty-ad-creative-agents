# Step 7d: full-assembly

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`api`는 모든 런타임 계층 import 가능, `eval`은 `api` 가능), CRITICAL 규칙(비밀 값은 `settings`만, 공급사별 누적액 호출 직전 검사, `reasoning_effort` 명시·원장 기록, 체크포인터 풀 설정, 실제 서비스 접속 금지)
- `/docs/ARCHITECTURE.md` — "요청 처리 공통 장치", "상태 관리"
- `/docs/results/p5_dev_compare_preregistration.md` — §8 실측 비용
- `/src/beautyads/eval/live_agent.py`(`assemble_live`와 `budgeted_chat`의 선례), `/src/beautyads/eval/p5_compare.py`(연결·구조화 생성기 조립의 선례), `/src/beautyads/api/app.py`, `/src/beautyads/api/checkpointer.py`, `/src/beautyads/agents/supervisor.py`, `/src/beautyads/agents/research.py`, `/src/beautyads/agents/planning.py`, `/src/beautyads/agents/evaluation.py`, `/src/beautyads/agents/lookups.py`, `/src/beautyads/agents/plan_eval.py`, `/src/beautyads/agents/design_images.py`, `/src/beautyads/sources/workspaces.py`, `/src/beautyads/sources/claim_rules.py`, `/src/beautyads/obs/ledger.py`, `/src/beautyads/llm/structured.py`, `/src/beautyads/llm/image.py`, `/tests/test_live_agent.py`, `/tests/test_ledger.py`, `/tests/test_architecture.py` — step 0~7c 산출물과 기존 live 조립의 방식

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/obs/ledger.py`, `src/beautyads/api/assembly.py`(새 파일), `tests/test_ledger.py`, `tests/test_api_assembly.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/obs/ledger.py`(`ledger_total(path)` 함수 추가에 한함, 기존 동작·단언 불변), `src/beautyads/api/assembly.py`, `tests/test_ledger.py`(케이스 추가에 한함, 기존 단언 변경 0줄), `tests/test_api_assembly.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

7a~7c의 서비스를 **실제 조립**으로 묶는 `assemble_full`을 만든다(step 9의 live 도구가 쓴다). 이 step은 조립 코드와 가짜 의존성 테스트만 만들고 **실제 서비스에 접속하거나 모델을 부르지 않는다**(실제 연결 함수는 주입 가능하게 두고 테스트는 가짜). **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.**

**`obs/ledger.py`**(추가에 한함): `ledger_total(path) -> float`(모든 공급사의 `cost_usd` 합계, 파일이 없으면 0). 요청 단위 비용은 호출 직전·직후의 합계 차이로 구한다.

**`api/assembly.py`**(`api` 계층): `async def assemble_full(*, settings, workspaces_path=Path("config/workspaces.yaml"), group="dev", models=None, connect_fn=connect, graph_fn=connect_graph, saver_fn=..., environ=None, env_file=DEFAULT_ENV_FILE, limits=RequestLimits(), with_image_enabled=False, evaluation_model="claude-haiku-5-5") -> Assembly`. 동작(순서·소유권을 `AsyncExitStack`으로 닫는다. 부분 시작 실패와 정상 종료 모두 자원을 닫는다):
1. 연결: PostgreSQL(`connect(postgres_dsn())`), Neo4j(`connect_graph()`), 체크포인터 풀(`build_checkpointer`·`setup_checkpointer`, `autocommit=True`·`dict_row`·`prepare_threshold=0`은 기존 함수가 보장한다). 마지막 수집 시각은 `PostgresCreativeStore.collection_stats()`에서.
2. 작업 공간: `load_workspaces(workspaces_path)`에서 **`group` 인자(`dev` 기본)에 해당하는 것만** 허용 목록에 넣고 프로필을 `tenant_profiles`에 시드한다(`save_profile`, 멱등). **`group="test"`는 호출부가 명시할 때만**(기본값을 test로 두지 않는다). 허용 목록 `allowed_tenants`는 그 그룹의 `tenant_id` 집합이다. 가격대: 각 작업 공간의 우리 제품 단위당 정가를 7b의 `product_unit_price_query()`로 읽어(`price_basis`가 `list_price`일 때만) `domain.tenant.price_band(단위당 정가, price_band_pct)`로 `price_bands[tenant_id]`를 만든다(값이 없으면 빈 dict, 예외 아님).
3. 모델 호출 서비스: 요청 단위 비용 가드 `spent_fn`(`ledger_total` 차이), 모든 호출은 `llm.chat_complete`·`llm.structured`·`llm.image`를 거치며 **호출 직전 공급사 누적액·목적별 상한 검사는 래퍼가 이미 한다**. 리서치(`gpt-6-luna`, `reasoning_effort="none"`), Supervisor(`decide`), 기획(`PLANNING_REASONING_EFFORT` 상수 그대로), 평가(`evaluation_model`: 개발 기본 `claude-haiku-5-5`, 공식 구성은 호출부가 `claude-sonnet-5-5`를 명시), 조회 구현체(`GraphEvidenceIndex`·`GraphEfficacySupport`·`GraphCertLookup`), 규칙(`load_claim_rules(Path("config/claim_rules.yaml"))`), 이미지(`with_image_enabled`일 때만 `generate_image`+`save_design_image`를 감싼 `image_fn`, 아니면 `None`).
4. `Assembly(...)`를 만든다: `graph`(skeleton 그래프, 기존 `/chat` 호환), `tenants`, `allowed_tenants`, `as_of`(서버 오늘 날짜, UTC), `last_collected_at`, `chat`·`tool_runner`, `workspaces`, `price_bands`, `ask`(`run_request`를 감싼 함수: `ask(message, ctx, profile, feedback, with_image) -> dict`), `hydrate`(PostgreSQL `creatives`에서 `source`·`url`·`brand`·`title`·`published_at`·`latest_view_count`·`latest_like_count`만 읽는 파라미터 질의, 모든 값 JSON 안전), `design_dir`, `image_enabled`, `close`.
- 비밀·키·DSN·값은 로그·예외 메시지에 남기지 않는다. 키는 `settings`의 한 함수로만 읽는다.

**반드시 있어야 하는 테스트**(가짜 `connect_fn`·`graph_fn`·`saver_fn`·가짜 저장소·가짜 모델 함수. 실제 서비스 접속 없음):
- 소유권·종료: 정상 종료와 중간 단계 실패(예: 그래프 연결 실패) 모두에서 이미 열린 자원이 닫힌다(가짜의 `close` 호출 기록).
- 작업 공간: 기본 `group="dev"`에서 허용 목록이 dev 작업 공간의 `tenant_id`뿐이고 test 작업 공간 ID가 **들어 있지 않다**(실제 `config/workspaces.yaml`을 읽되 개수·값을 단언하지 않고 그룹 불변식만). `group="test"`를 명시해야 test 작업 공간이 들어간다. 프로필이 `save_profile`로 시드되고(멱등: 두 번 호출해도 같은 결과) 가격대가 `price_band` 함수 결과와 같다(합성 단위당 정가 값). 정가가 없으면 빈 dict이고 예외가 없다.
- 비용 가드: `spent_fn`이 `ledger_total` 차이이고(합성 원장 파일), 파일이 없으면 0. 가짜 모델 함수가 한 번 불린 뒤 `spent_fn`이 증가분을 낸다.
- 평가 모델: 기본이 `claude-haiku-5-5`이고 `claude-sonnet-5-5`를 명시해야 바뀐다(알 수 없는 모델은 `ValueError`). 이미지: 기본 `image_fn is None`, 켜면 호출 가능하고 가짜 `generate_image`가 텍스트 프롬프트만 받는다.
- `hydrate`: 가짜 연결에서 파라미터 질의를 쓰고(문자열 연결 없음) 열 목록이 위 다섯 개뿐이다.
- `ask`: 가짜 서비스로 `run_request`가 돌고 결과가 `json.dumps`를 통과한다. 모델 호출 인자에 `reasoning_effort`가 명시돼 있다(luna `none`, 기획 상수, 평가는 `None`).
- 비밀: 예외·로그에 합성 키·DSN이 없다.
- `tests/test_architecture.py` 통과(`api`가 `neo4j`·`litellm`을 직접 import하지 않는다).

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

- 테스트·기본 인자에서 `group`을 `test`로 두거나 test 작업 공간을 허용 목록에 넣지 마라. 이유: test 브랜드(isntree·beauty_of_joseon)는 최종 평가·시연에만 쓴다(P5 결정). 호출부가 명시할 때만 포함한다.
- 모델·그래프·저장소에 실제로 접속하거나 `make live-agent`·`make live-compare`를 실행하지 마라. 이유: 실제 접속은 사용자가 한다(AGENTS.md CRITICAL). 모든 연결 함수는 주입해 테스트한다.
- `reasoning_effort`를 생략하거나 평가 모델의 기본을 `claude-sonnet-5-5`로 두지 마라. 이유: 개발 반복 기본은 `haiku`이고 공식 구성은 명시적으로 켠다(AGENTS.md CRITICAL). luna·terra는 `reasoning_effort`를 명시하고 원장에 기록한다.
- 키·DSN·비밀번호를 로그·예외·결과에 남기지 마라. 이유: AGENTS.md CRITICAL(비밀 값은 `settings`의 한 함수로만 읽는다).
- 조립 실패 시 열린 자원을 남기지 마라. 이유: 체크포인터 풀과 연결이 새면 다음 실행이 막힌다. `AsyncExitStack`으로 부분 시작과 정상 종료를 모두 닫는다.
- `obs/ledger.py`의 기존 함수 동작과 `tests/test_ledger.py`의 기존 단언을 바꾸지 마라. 이유: 비용 상한 검사가 이 파일의 합계 함수에 의존한다. 새 함수만 추가한다.
