# Step 8: embed-vector-e3

## 설계 검토 기록

**식별자 전수 대조(bb0e64f)**: `llm/chat.py`(`chat_complete`의 `max_attempts`·`ErrorKind`·원장 기록·`check_cap` 호출 방식, **임베딩 래퍼가 같은 패턴을 따른다**), `llm/prices.py`(단가표 구조, 이 step이 임베딩 단가를 추가), `llm/errors.py`(`ErrorKind`·`CostCapExceeded` 사용), `obs/ledger.py`(`LedgerEntry`·`append`·`check_cap`·`check_purpose_cap`), `tests/test_llm_param_guard.py:21 MODELS`·`:30 SHAPES`(LLM 호출 전 검증 가드, **임베딩 조합을 새 테스트 함수로 추가**하고 기존 튜플은 불변), `tests/test_llm_prices.py`(단가표 단언, 정확 일치 단언 여부를 먼저 grep), `tests/test_schema_guard.py`(`GUARDED_MODULES`), `tests/test_architecture.py`(`litellm`은 `llm`만 import), `eval/single_agent.py`(step 4: `run_tool_loop`·`ToolLoopResult`), `eval/e2_scoring.py`(step 5: `bootstrap_ci`·`SCORING_SEED`), `eval/evalset.py`·`eval/freeze_guard.py`(step 2), `agents/research.py`(`RESEARCH_REASONING_EFFORT`·모델 `gpt-6-luna` 사용 방식, 읽기 전용), `store/sync_source.py:53 PostgresGraphSyncSource`(`read_changed`·`read_labels`: 그래프 적재가 읽는 같은 PostgreSQL 읽기)·`store/repository.py:67 PostgresCreativeStore`, `graph/layer1.py`·`store/product_store.py`(제품·성분 읽기, 읽기 전용).

**상수 단언 grep**: `tests/test_llm_prices.py`·`tests/test_llm_param_guard.py`에서 단가표 키 집합·`MODELS`·`SHAPES`를 정확 일치로 단언하는 곳을 먼저 찾아 **수정하지 않는다**(새 모델은 새 테스트 함수·새 표로 추가). 새 상수(`TOP_K`, `MAX_DOC_CHARS`, `EMBED_PURPOSE_CAP`, `ANSWER_PROMPT_VERSION`, `CORPUS_FIELDS`)를 단언하는 기존 테스트는 없다.

**새 칸 대응표**: `embedding_model`·임베딩 단가(이 step `embed.py`·`prices.py` → 원장 항목·측정 보고 → step 10 사전 등록 동결 값), `CORPUS_FIELDS`(코드가 실제로 읽은 필드 목록 → step 10 사전 등록), `TOP_K`·청킹 방식(`vector_baseline.py` → 사전 등록), 답 스키마 `E3Answer`(이 step → 두 팔의 최종 구조화 호출 → 채점), 정답 `AnswerItem`(step 3 확정본 → 이 step의 채점 코드만 읽는다, **팔 실행 코드는 정답 경로를 열지 않는다**, B-FP-042).

**조언 세션 결정**: 새 의존성 없이 stdlib `math` 코사인 + litellm 임베딩. 임베딩 모델은 **dev 질문으로만** 실측해 고른다. 코퍼스(그래프와 같은 텍스트 필드)·top-k·청크 방식은 사전 등록에 고정한다. 코퍼스에 test 브랜드 소재가 섞이는 한계는 사전 등록에 적는다. 새 의존성이 필요하면 추가 전에 `blocked`로 보고한다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 모델 호출은 `llm/` 한 곳(LiteLLM SDK), 유료 호출 직전 공급사별 누적액 검사, 외부 응답은 CONTRACTS에 실측된 형태만 전제(없으면 키를 없을 수 있다고 읽는다), 패키지 설치 금지
- `/docs/EVAL.md`(E3 질문 30·단순 검색 10·정답률·95% CI), `/docs/COMPETENCY_QUESTIONS.md`, `/docs/CONTRACTS.md`(읽기 전용: 임베딩 응답 실측 항목이 아직 없다), `/.claude/skills/failure-patterns/SKILL.md`(FP-C01·C13·C15·C16, B-FP-042)
- `/src/beautyads/llm/chat.py`, `/src/beautyads/llm/prices.py`, `/src/beautyads/llm/errors.py`, `/src/beautyads/obs/ledger.py`, `/src/beautyads/settings.py`(읽기 전용)
- `/tests/test_llm_param_guard.py`, `/tests/test_llm_prices.py`, `/tests/test_schema_guard.py`, `/tests/test_architecture.py`, `/tests/test_llm.py`(가짜 litellm 호출 선례, 읽기 전용)
- `/src/beautyads/eval/single_agent.py`, `/src/beautyads/eval/e2_scoring.py`, `/src/beautyads/eval/evalset.py`, `/src/beautyads/eval/freeze_guard.py`, `/src/beautyads/agents/research.py`(읽기 전용), `/src/beautyads/store/sync_source.py`, `/src/beautyads/store/repository.py`, `/src/beautyads/graph/layer1.py`, `/src/beautyads/store/product_store.py`(읽기 전용)
- `/Makefile`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/llm/embed.py`(새 파일), `src/beautyads/llm/prices.py`(임베딩 단가 추가에 한함, 기존 항목·함수 불변), `src/beautyads/eval/vector_baseline.py`(새 파일), `src/beautyads/eval/e3_live.py`(새 파일), `tests/test_embed.py`(새 파일), `tests/test_vector_baseline.py`(새 파일), `tests/test_e3_live.py`(새 파일), `tests/test_llm_param_guard.py`(임베딩 호출 모양을 검사하는 새 테스트 함수 추가에 한함, `MODELS`·`SHAPES`·기존 단언 불변), `tests/test_schema_guard.py`(`GUARDED_MODULES`에 `eval/e3_live.py` 한 개 추가와 새 테스트 함수 추가에 한함, 기존 단언 약화 금지), `tests/test_llm_prices.py`(단가 추가용 새 테스트 함수 추가에 한함, 기존 단언 약화 금지), `Makefile`(`live-e3` 타깃 한 개 추가에 한함)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/llm/embed.py`, `src/beautyads/llm/prices.py`, `src/beautyads/eval/vector_baseline.py`, `src/beautyads/eval/e3_live.py`, `tests/test_embed.py`, `tests/test_vector_baseline.py`, `tests/test_e3_live.py`, `tests/test_llm_param_guard.py`, `tests/test_schema_guard.py`, `tests/test_llm_prices.py`, `Makefile`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로, 평가 정답을 읽는 채점 함수)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

E3(그래프 대 벡터)의 **임베딩 래퍼, 벡터 기준선, 실행기**를 만든다. 이 step 안에서는 모델·DB·그래프에 접속하지 않는다. **테스트를 먼저 쓴다.** 임베딩 응답 형태는 아직 `docs/CONTRACTS.md`에 실측이 없으므로 응답을 읽을 때 **키는 없을 수 있다고 보고 읽는다**(`[]` 직접 접근 금지, 없으면 고정 오류 코드). CONTRACTS 추가는 사용자가 `measure`를 돌려 실측한 뒤 구현 세션이 한다(이 step에서 CONTRACTS를 고치지 않는다).

새 식별자: `embed_texts`, `EmbedResult`, `EMBEDDING_PRICES`, `CorpusDoc`, `CORPUS_FIELDS`, `TOP_K`, `MAX_DOC_CHARS`, `cosine`, `top_k`, `ANSWER_PROMPT_VERSION`, `E3Answer`, `answer_prompt`, `score_answer`, `EMBED_PURPOSE_CAP`

**`llm/embed.py`(litellm은 이 계층에서만 import)**
- `embed_texts(texts, *, model, ledger_path, caps, api_key, purpose="embed", batch_size=64, embedding_fn=None) -> EmbedResult`(`EmbedResult`: `vectors: list[list[float]]`, `input_tokens: int`, `cost_usd: float`). `embedding_fn`은 주입(기본 `litellm.embedding`). 호출 **직전**에 `check_cap`으로 공급사 누적액을 검사하고(`additional_usd`는 입력 길이 상한 추정으로), 닿으면 호출하지 않고 `CostCapExceeded`다. 재시도는 503·연결 실패·시간 초과에만(`chat.py`와 같은 `ErrorKind` 분류), 일일 한도 429는 재시도하지 않는다. 응답은 `data` 항목의 `embedding`을 **항목의 `index`로 정렬해** 읽고(위치 가정 금지, FP-C02) 항목 수가 입력 수와 다르면 `EMBED_RESPONSE_INVALID`. 비용은 가격표(`llm/prices.py`의 `EMBEDDING_PRICES`: 모델→100만 토큰당 USD, 출처·조회일 주석)와 `usage.prompt_tokens`로 계산하고 원장에 `cost_source="price_table"`로 한 항목 기록한다(`reasoning_effort`는 없음). 가격표에 없는 모델은 호출을 거부한다(`EMBED_MODEL_UNPRICED`). `temperature`·`dimensions` 등 지정하지 않은 옵션을 넘기지 않는다. 오류 문장에 키·입력 본문을 싣지 않는다.
- `llm/prices.py`에 임베딩 단가를 추가한다: 설치된 litellm 1.103.3이 인식하는 OpenAI 임베딩 모델 후보(`text-embedding-3-small`·`text-embedding-3-large`)의 단가를 **litellm의 내장 `model_cost` 표를 읽어 확인한 값**으로 쓰고 주석에 "출처: litellm 1.103.3 model_cost" 조회 방법을 적는다. 값을 확인하지 못하면 추정으로 채우지 말고 `blocked`로 보고한다. 기존 단가표 항목·함수는 불변이다.

**`eval/vector_baseline.py`(표준 라이브러리 `math`만, numpy 없음)**
- `CorpusDoc(id, text)`, `cosine(a, b)`(`math.sumprod`·`math.sqrt`, 영벡터는 0.0), `top_k(query_vec, doc_vecs, ids, k=TOP_K)`(점수 내림차순, 같은 점수는 `id` 오름차순으로 결정적), `TOP_K = 10`, `MAX_DOC_CHARS = 1500`(문서는 **청크로 나누지 않고** 소재·제품 하나당 문서 하나, 길이만 잘라 임베딩), 벡터 캐시는 `data/interim/e3/`에 `array('f')` 바이너리와 id 목록 JSON으로 저장·읽기(모델 이름이 파일 이름에 들어가고 모델이 다르면 섞이지 않는다).
- **코퍼스(그래프와 같은 텍스트 필드)**: 그래프 적재가 읽는 PostgreSQL의 기존 읽기(`PostgresGraphSyncSource.read_changed`·`read_labels` 등 **이미 있는 읽기 메서드**)로 소재 문서를 만들고(브랜드·카테고리·콘텐츠 유형·훅 유형·각도·포맷·소구점 등 라벨 값을 `키: 값` 줄로), 제품 문서는 그래프 1층 적재가 읽는 기존 저장소 읽기로 만든다(제품명·카테고리·성분·인증). **새 SQL·새 Cypher를 만들지 않는다.** 기존 읽기로 얻을 수 없는 필드는 코퍼스에 넣지 않고 실제로 읽은 필드 이름을 `CORPUS_FIELDS`(튜플)에 모아 보고한다(이 목록이 사전 등록에 그대로 들어간다). 모든 브랜드(test 브랜드 포함)를 담는다 — **한계로 사전 등록에 적는다**.

**`eval/e3_live.py`**
- CLI: `uv run python -m beautyads.eval.e3_live <measure|run|report> [--mode dev|final] [--arms graph,vector] [--models a,b] [--limit N] [--dry-run]`. `Makefile`에 `live-e3` 타깃 한 개.
- 공통 답: `E3Answer`(pydantic: `count: int | None`, `items: list[str]`, `evidence_ids: list[str]`)와 `StructuredSpec("e3_answer", …)`(OpenAI strict 검증기를 통과하는 모양, 널 허용은 허용 형태로), `ANSWER_PROMPT_VERSION = "2026-11-19-1"`. **두 팔이 같은 모델(`gpt-6-luna`, `reasoning_effort`는 `agents/research.py`의 연구 에이전트 값)·같은 답 프롬프트·같은 구조화 호출**을 쓰고, 입력의 근거 부분만 다르다: 그래프 팔은 `single_agent.run_tool_loop`(도구 호출 한도는 `ResearchBrief` 기본값)가 만든 관측 JSON, 벡터 팔은 질문을 임베딩해 `top_k`로 뽑은 문서 텍스트 JSON. 외부 텍스트는 JSON 데이터 필드로만 넣고 시스템 지시에 섞지 않는다(FP-C14). 모든 호출 직전 공급사별 누적액 검사(주입 래퍼).
- **정답 경로 분리(B-FP-042)**: 팔 실행 코드(그래프·벡터)는 `answers.jsonl`을 열지 않는다. 정답은 `score_answer`를 부르는 `report` 단계에서만 읽는다(함수 인자 분리, 테스트로 확인).
- **`score_answer(answer, truth) -> dict`**(코드 판정, 모델 채점 없음): `answer_type="count"`는 `abs(count − value) <= tolerance_abs`이면 정답, `"set"`은 정규화(앞뒤 공백 제거·중복 제거)한 `items` 집합이 정답 집합과 같으면 정답. 근거 소재 적중률 = `answer.evidence_ids` 중 `truth.evidence_ids`에 있는 비율(정답에 근거 ID가 없으면 `None`으로 제외). 팔별 정답률, 질문 쌍의 정답률 차이(그래프 − 벡터)에 `e2_scoring.bootstrap_ci`(요청 대신 질문 단위), 판정 `graph_adopted`(CI 하한 > 0)·`not_adopted`(그 외)·`undecidable`(질문 20개 미만). 전체 40건과 **단순 검색형 10건 부분집합을 따로** 보고하고, 질문의 `stratum`별(`reliable`/`unreliable`) 정답률도 서술용으로 따로 낸다(결론 근거 아님, `MIN_STRATUM_N` 미만이면 판정 불가).
- **`measure`(dev 질문만)**: 후보 임베딩 모델 각각에 대해 코퍼스를 임베딩하고 dev 질문(`split == "dev"`)의 정답 `evidence_ids`에 대한 `hit@TOP_K`(top-k 문서 id 중 정답 근거 소재가 하나라도 있는 질문의 비율)를 코드로 계산해 모델별로 출력한다. 같은 출력에 **잘린 문서 비율**(`len(text) > MAX_DOC_CHARS`인 문서 수 ÷ 전체 문서 수, 그리고 dev 질문의 정답 근거 소재 문서만의 잘린 비율)을 코드로 계산해 함께 낸다(모델 호출 없음). 이는 길이 자르기가 정답 근거를 잘라 벡터 팔을 불리하게 만들지 않는지 보기 위한 것이다. `MAX_DOC_CHARS`·`TOP_K`는 **임시 값**이며 dev hit@k와 잘린 문서 비율을 본 뒤 사용자가 사전 등록 전에 확정한다. 선택 기준은 사전에 고정한다: **hit@TOP_K가 가장 높은 모델, 같으면 단가가 낮은 모델**. 비용은 목적 `embed` 상한(`EMBED_PURPOSE_CAP = 1.0`, `check_purpose_cap`)으로 막고 `--dry-run`은 문서 수·추정 토큰·"가정(미실측)"만 출력한다. 응답 형태 실측용으로 첫 응답의 **키 구조만**(벡터는 앞 3개 값) `data/interim/e3/embedding_response_shape.json`에 쓴다(CONTRACTS 추가 자료).
- `--mode dev`: dev 질문만, test 질문·test 작업 공간 거부(`check_run(mode="dev")`). `--mode final`: test 질문 40건만, **호출 전** `check_run(mode="final", groups={"test"}, extra=…)`(`extra`에 임베딩 모델·`TOP_K`·`MAX_DOC_CHARS`·`ANSWER_PROMPT_VERSION`·`CORPUS_FIELDS` 줄)를 통과해야 하며 실패 시 호출 0건이다. 기록에 `RunIdentity`를 싣는다.

**테스트(합성 환경)**
- `tests/test_embed.py`: 가짜 `embedding_fn`으로 항목 `index` 순서 뒤섞임 처리, 항목 수 불일치·키 누락의 고정 오류 코드(키를 없을 수 있다고 읽음), 호출 직전 `check_cap`(닿으면 호출 0건), 재시도 분류(503·연결 실패·시간 초과만, 429 일일 한도 재시도 안 함), 원장 한 항목 기록(`cost_source="price_table"`, 가격표 계산), 미등록 모델 거부, 오류 문장에 입력 본문·키 없음.
- `tests/test_llm_param_guard.py` 새 테스트 함수: 실제 litellm의 **호출 전 검증 함수**에 임베딩 호출 인자(`model`·`input`·`api_key`)를 넣어 예외가 없음을 확인한다(검사한 조합 수 0은 실패, FP-C13). 후보 모델 두 개를 모두 덮는다.
- `tests/test_llm_prices.py` 새 테스트 함수: 임베딩 가격표가 양수이고 모델 키가 비어 있지 않다(값 자체를 리터럴로 굳히지 않는다).
- `tests/test_vector_baseline.py`: `cosine`(직교·동일·영벡터)·`top_k`의 결정적 정렬·같은 점수 처리, `array('f')` 캐시 왕복과 모델 이름이 다르면 섞이지 않음, 문서 길이 자르기, 코퍼스 빌더가 가짜 읽기 소스로 `CORPUS_FIELDS`와 같은 필드만 쓰고 새 SQL·Cypher 문자열이 모듈에 없음(AST), numpy·litellm import 없음(`tests/test_architecture.py`와 함께).
- `tests/test_e3_live.py`: 가짜 `structured`·`chat`·`embed`가 받은 입력을 직접 검사(FP-C14: 그래프 팔 입력에 관측, 벡터 팔 입력에 문서 텍스트, 두 팔의 프롬프트·모델·`reasoning_effort` 동일, `temperature` 없음), 팔 실행 중 `answers.jsonl`을 열지 않음(가짜 파일 시스템 감시), `score_answer`의 `count` 허용 오차 경계 위아래·`set` 같음·다름·`None` 처리, 정답률 차이 판정 분기(`graph_adopted`·`not_adopted`·`undecidable`)와 단순 검색 부분집합 분리 보고, `measure`의 선택 기준(최고 hit@k·동률이면 저가)과 출력의 잘린 문서 비율(전체·정답 근거 소재 문서, 합성 코퍼스에서 손으로 센 값과 같음, 모델 호출 0건), final 가드 실패 시 호출 0건과 dev 모드의 test 질문 거부, 합성 문장을 기대값으로 굳히지 않음.
- `tests/test_schema_guard.py`: `GUARDED_MODULES`에 `"eval/e3_live.py"` 추가와 새 테스트 함수(스펙이 strict 검증기를 통과, 검사한 스펙 수 0은 실패).

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

- 새 의존성(numpy·벡터 DB·청킹 라이브러리 등)을 추가하거나 새 SQL·새 Cypher를 만들지 마라. 이유: 승인된 구성은 stdlib 코사인 + litellm 임베딩이다. 새 의존성이 필요하면 추가 전에 `blocked`로 보고한다(조언 세션 결정, AGENTS.md).
- 임베딩 호출을 `llm/embed.py` 밖에서 하거나 `eval`·다른 계층에서 `litellm`을 import하지 마라. 이유: 모델 호출은 `llm/` 한 곳이다(AGENTS.md CRITICAL, `tests/test_architecture.py`).
- 단가를 추정으로 채우거나 임베딩 응답을 `data[0]["embedding"]`처럼 위치·키 직접 접근으로 읽지 마라. 이유: 단가는 확인된 값만, 응답은 실측되지 않은 계약이라 키가 없을 수 있다고 본다(FP-C01·C02, FP-C06).
- 팔 실행 코드에서 정답 파일을 열거나 두 팔의 모델·프롬프트·`reasoning_effort`를 다르게 하지 마라. 이유: 정답 접근은 채점 단계에만 허용하고(B-FP-042), 비교는 근거 입력만 다른 조건이어야 한다(docs/EVAL.md E3).
- `make live-e3`로 임베딩·모델을 실제 호출하는 테스트를 만들거나 `docs/CONTRACTS.md`를 고치지 마라. 이유: 실측은 사용자가 비용 보고 뒤 승인하고 실행한다. CONTRACTS는 측정 결과를 받은 뒤 구현 세션이 추가한다(AGENTS.md).
