# Step 11: product-identify

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조, 온톨로지 절(`PROMOTES` 판정 규칙, `multi_product`), 데이터 흐름
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P4 절과 변경 기록 #36~#39
- `/docs/COMPETENCY_QUESTIONS.md` — v1(2026-11-15 동결), 2층 질문의 한계(`PROMOTES` 커버리지)
- `/docs/CONTRACTS.md` — Gemini 영상 입력(YouTube 주소 입력, Files 업로드, `processing` 구간·fps, 영상 입력 토큰은 약 91토큰/초), Instagram `media_url` 만료와 재조회, TikTok은 영상 주소를 저장하지 않는다
- `/docs/ADR.md` — ADR-005(모델 구성), ADR-013
- `/src/beautyads/analysis/hook.py`, `/src/beautyads/analysis/models.py`, `/src/beautyads/analysis/prompts.py` — 영상 입력 요청·구조화 출력·검증·재요청 방식(**그대로 따른다**)
- `/src/beautyads/llm/gemini.py`(`video_part`, `text_part`, `gemini_interact`, `json_schema_format`), `/src/beautyads/llm/files.py`
- `/src/beautyads/pipeline/media_flow.py`, `/src/beautyads/pipeline/analyze.py` — Instagram 영상 준비(`media_url` 재조회·내려받기·Files 업로드·삭제), 배치 실행·장애 처리·원장 기록(**재사용한다**)
- `/src/beautyads/domain/links.py`, `/src/beautyads/graph/layer2.py`, `/src/beautyads/store/links_source.py` — `PROMOTES` 판정과 적재
- `/src/beautyads/domain/products.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/product_id.py`(새 파일), `src/beautyads/analysis/product_identify.py`(새 파일), `src/beautyads/analysis/prompts.py`(상수 추가에 한함), `src/beautyads/pipeline/product_identify.py`(새 파일), `src/beautyads/domain/links.py`, `src/beautyads/store/links_source.py`, `Makefile`, `README.md`, `tests/test_product_id_domain.py`(새 파일), `tests/test_product_identify.py`(새 파일), `tests/test_product_identify_pipeline.py`(새 파일), `tests/test_links_domain.py`, `tests/test_links_source.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/product_id.py`, `src/beautyads/analysis/product_identify.py`, `src/beautyads/analysis/prompts.py`(`PRODUCT_ID_PROMPT_VERSION`과 프롬프트 빌더 추가에 한함, 기존 상수·함수 불변), `src/beautyads/pipeline/product_identify.py`, `src/beautyads/domain/links.py`(영상 식별 결과를 `PROMOTES` 입력으로 읽는 부분 추가에 한함, 텍스트 규칙의 기존 동작·단언 불변), `src/beautyads/store/links_source.py`(`product-id@v1` 라벨 읽기 추가에 한함, 기존 동작 불변), `Makefile`(새 타깃 추가에 한함), `README.md`(절 추가에 한함), `tests/test_product_id_domain.py`, `tests/test_product_identify.py`, `tests/test_product_identify_pipeline.py`, `tests/test_links_domain.py`(케이스 추가에 한함, 단언 약화 금지), `tests/test_links_source.py`(케이스 추가에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

소비자 테스트 점검 결과: `tests/test_compose.py`·`tests/test_slice.py`·`tests/test_collect.py`·`tests/test_pilot.py`는 저장소 `Makefile`을 읽고 `.PHONY`는 부분집합으로, 기존 타깃의 레시피 원문은 정확히, `verify` 레시피는 `live-`가 없음을 단언한다. 따라서 **새 타깃은 추가하되 기존 타깃의 레시피 원문·`verify` 레시피·형식은 바꾸지 않는다.** 이 테스트 파일들은 수정하지 않는다. 깨지면 고치지 말고 `blocked`로 보고한다. `PROMOTES`의 `basis` 값에 `video`를 추가하는 것이 `tests/test_links_domain.py`·`tests/test_graph_layer2.py`의 기존 단언(`basis`가 `title`·`caption`)을 깨면 **단언을 약화하지 말고 새 값을 허용하는 케이스만 추가**하고, 그래도 깨지면 `blocked`로 보고한다.

**텍스트(제목·캡션)에서 제품 이름이 나오지 않은 YouTube·Instagram 제품 소재**를 영상 자체로 식별해 `PROMOTES`로 잇는다. 모델은 **같은 브랜드의 후보 제품 목록 안에서만** 고른다. v1 분류 축·E1·`full@v1` 라벨과 **무관한 별도 추출**이다(새 프롬프트 버전 `product-id-v1`, 새 작업 종류 `product-id@v1`). **이 step 안에서는 실제 호출을 하지 않는다.**

- **대상**: 출처가 YouTube·Instagram이고 `content_type@v1`이 `product_creative`(최종 라벨)이며, 텍스트 판정(`match_products`)이 `matched`가 아니고(연결 없음·`ambiguous`), 같은 브랜드의 저장된 제품이 있는 소재. **TikTok은 영상 주소를 저장하지 않아 제외한다.** 이미 `product-id@v1`이 `done`인 소재는 다시 하지 않는다.
- **입력**: 소재의 영상 + 같은 브랜드의 후보 제품 목록(PostgreSQL의 저장된 제품, 소재 브랜드 한정). YouTube는 주소를 그대로, Instagram은 기존 영상 준비 경로(`media_flow`: `media_url` 만료 임박이면 재조회, 내려받기, Files 업로드, 처리 뒤 삭제)를 **재사용**한다. 영상 파일은 분석이 끝나면 지운다(AGENTS.md). 구간은 `processing`으로 앞 `window_max_s`(기본 60초)까지만 넣고 `fps`는 1이다(비용은 영상 길이에 비례, 약 91토큰/초는 계약 실측).
- **출력 스키마(`domain/product_id.py`)**: 후보에 요청마다 짧은 `candidate_id`(`C1`…`Cn`)를 붙이고 모델은 `{"candidates": ["C2", "C4"]}` 또는 `{"candidates": []}`(없음)만 낸다. **목록 밖 값이거나 중복이거나 없음과 후보를 함께 내면 검증 실패 → 1회 재요청 뒤 보류**(기존 분석 방식과 같다). 제품 이름 문자열·새 이름은 받지 않는다. 프롬프트는 "영상에서 **직접 보이거나 이름이 불리는** 후보만 고르고 모르면 비워 둔다. 추측하지 않는다"를 요구하고 후보에 이름과 별칭을 보여 준다. 응답의 `candidate_id`는 코드가 제품으로 되돌린다.
- **저장**: 결과를 기존 분석 작업 저장소(`analysis_jobs`)의 새 종류 `product-id@v1`로 기록한다(`labels={"products": [{"brand", "source_url"}, ...]}`, 모델 원문, 프롬프트 버전, 시도 횟수, 오류 코드). **`full@v1`·`hook@v1`·`content_type@v1`과 E1 데이터는 읽기만 하고 수정하지 않는다.**
- **`PROMOTES` 연결(`domain/links.py`)**: 텍스트로 `matched`가 아닌 소재에 한해 `product-id@v1`이 `done`이면 거기 든 제품마다 `PROMOTES`를 만든다. **`basis`는 `video`, `confidence`는 `model`**(텍스트 규칙의 `name_full`·`alias`와 구분), `matched_text`는 비운다. 두 제품 이상이면 `multi_product: true`다. 텍스트로 이미 `matched`인 소재는 영상 식별 결과로 바꾸지 않는다. 요약에 `basis`별 연결 수(`title`·`caption`·`video`)를 따로 낸다.
- **비용·상한(CRITICAL)**: 호출 직전에 Gemini 누적액(`data/manifest/costs.jsonl`)을 검사한다(기존 `llm` 래퍼). 원장 `purpose`는 `product-identify`다. `--dry-run`은 대상 수와 예상 비용을 **"가정(미실측)" 표기**로 내고 호출하지 않는다. 예상 비용은 영상 길이 × 약 91토큰/초와 단가(원장에서 읽은 실측 단가, 없으면 가정 표기)로 계산하고 판정 기준으로 쓰지 않는다. 429 일일 한도·크레딧 소진·인증은 멈추고 남은 소재를 대기로 둔다(FP-C07), 한 소재의 실패는 기록하고 다음으로 간다. `temperature`를 지정하지 않는다. 모델 ID는 `ANALYSIS_MODEL_ID`를 import한다.
- **`make live-product-identify`**: `python -m beautyads.pipeline.product_identify`. 옵션 `--dry-run`, **`--sample N`**(대상에서 시드 고정(`--seed`) 무작위 N건만 처리하고 **끝나면 멈춘다**), `--max-videos`, `--thinking-level`, `--window-max-s`. 점검(`ENV_MISSING:GEMINI_API_KEY`·`DOCKER_DOWN`·`POSTGRES_UNREACHABLE`·`COST_CAP:gemini`) 뒤 시작한다. **전체 실행(`--sample` 없이)은 사용자의 비용 승인 뒤에 한다.** `--sample` 실행 요약에는 대상 수·처리 수·완료·보류·실패, **텍스트로 못 잇던 소재 중 새로 이어진 수와 `video` 연결의 `multi_product` 수, 비용, 정밀도 확인용 무작위 20쌍(`--sample-pairs 20`, 소재 제목·캡션(앞 120자), 영상 주소(YouTube) 또는 permalink(Instagram), 고른 제품 이름)을 출력한다**(사용자가 정밀도를 확인한다).

### 반드시 있어야 하는 테스트

(가짜 `interact`·합성 영상 입력·가짜 저장소만 쓴다. 모델 응답은 구조에 맞춘 합성 본문이다. **모델이 고른 값을 기대값으로 굳히지 않는다**, FP-C03.)
- 스키마·검증: `candidate_id`가 후보 목록 안이면 통과, 목록 밖 값·중복·`[]`과 후보 혼합은 검증 실패 → 1회 재요청 뒤 `held`(재요청 횟수 검사), `[]`은 정상(없음)으로 `done`이고 연결이 없다, 제품 이름 문자열은 받지 않는다.
- 후보: 소재 브랜드의 저장된 제품만 후보가 되고 다른 브랜드 제품은 들어가지 않는다, 후보가 없는 브랜드는 대상에서 빠진다(호출 0), `candidate_id`가 제품으로 되돌아간다.
- 대상 선택: TikTok·`product_creative`가 아닌 소재·텍스트로 `matched`인 소재·이미 `product-id@v1`이 `done`인 소재는 제외된다(손계산), `ambiguous`는 대상이다.
- 영상 입력: YouTube는 주소가 `video_part`에 그대로 들어가고 구간 상한이 걸린다, Instagram은 기존 영상 준비 경로를 쓰고 처리 뒤 파일이 지워진다(가짜 Files), 영상 파일이 디스크에 남지 않는다.
- 비용·장애: 호출 전에 상한 검사가 있다, 상한 초과면 호출하지 않는다, 일일 한도·크레딧 소진은 배치를 멈추고 남은 소재가 대기로 남는다(실패로 기록하지 않는다, FP-C07), 한 소재의 실패가 다음을 막지 않는다, `temperature`가 호출 인자에 없다, 모델 ID가 새 모듈에 문자열로 없다.
- `PROMOTES`: 영상 식별이 `done`이고 텍스트로 `matched`가 아니면 `basis=video`·`confidence=model` 관계가 만들어진다, 두 제품이면 둘 다 `multi_product`다, 텍스트로 `matched`인 소재는 영상 결과가 있어도 바뀌지 않는다, `held`·`failed`·`pending` 결과는 연결을 만들지 않는다, 요약에 `basis`별 수가 따로 나온다.
- `--sample`: 같은 시드는 같은 N건이고 처리한 뒤 더 진행하지 않는다, `--dry-run`은 호출하지 않고 "가정(미실측)"을 표기한다, 20쌍 표본이 같은 시드에서 같다.
- `Makefile`에 `live-product-identify`가 있고 `verify` 레시피에 `live-`가 없다, `tests/test_architecture.py`가 통과한다(`analysis`는 `domain`·`llm`만, `pipeline`이 조립).

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

- `make live-product-identify`를 실행하지 마라. 이유: 실제 모델 호출과 영상 내려받기는 사용자 승인 뒤 사용자가 한다(AGENTS.md, 비용).
- 후보 목록 밖의 제품 이름·새 제품을 모델이 만들게 하지 마라. 이유: 목록 안에서만 고르는 제한 분류다(없으면 `[]`).
- `full@v1`·`hook@v1`·`content_type@v1`·E1 라벨·`docs/EVAL.md`의 동결 기준을 바꾸거나 이 추출 결과로 덮어쓰지 마라. 이유: v1 분류 축과 평가는 이 추출과 무관하다.
- 텍스트로 이미 `matched`인 소재의 `PROMOTES`를 영상 식별로 바꾸지 마라. 이유: 텍스트 규칙이 기준이고 영상 식별은 못 이은 소재의 보충이다.
- TikTok 소재를 대상으로 하지 마라. 이유: 영상 주소를 저장하지 않는다(CONTRACTS).
- 영상 파일을 저장하거나 `data/raw`·`data/interim`에 남기지 마라. 이유: 분석이 끝나면 지운다(AGENTS.md).
- 모델이 고른 제품을 테스트 기대값으로 굳히지 마라. 이유: 정확도는 정밀도 표본(무작위 20쌍)으로 사람이 확인한다(FP-C03).
- 기존 `Protocol`·`graph/load.py`·텍스트 `PROMOTES` 규칙의 동작을 바꾸지 마라. 이유: 기존 테스트가 계약이다.
