# Step 6: product-detail

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조, 온톨로지 절, 데이터 흐름
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P4 절과 변경 기록 #36
- `/docs/COMPETENCY_QUESTIONS.md` — v1(2026-11-15 동결), 홉 정의와 한계
- `/docs/CONTRACTS.md` — "Gemini 이미지 입력(2026-11-15)", 공식몰 절(상세 이미지 규모, 뒤쪽부터 읽기, Gemini 추출 방식)
- `/docs/ADR.md` — ADR-013
- `/src/beautyads/llm/gemini.py`(`image_part`, `gemini_interact`, `json_schema_format`), `/src/beautyads/analysis/` — 구조화 출력 요청, 스키마 검증, 목록 밖이면 1회 재요청 뒤 보류하는 방식(**그대로 따른다**), `/src/beautyads/analysis/models.py`(`ANALYSIS_MODEL_ID`)
- `/src/beautyads/domain/products.py`, `/src/beautyads/domain/mall.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `pyproject.toml`, `uv.lock`, `src/beautyads/analysis/product_detail.py`(새 파일), `src/beautyads/domain/products.py`, `tests/test_product_detail.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `pyproject.toml`, `uv.lock`(`uv add pillow`만), `src/beautyads/analysis/product_detail.py`, `src/beautyads/domain/products.py`(추출 결과 스키마 추가에 한함, 기존 타입 불변), `tests/test_product_detail.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

전성분 텍스트가 없는 제품의 상세 이미지를 모델로 읽어 제품 정보를 뽑는다. `uv add pillow`(상세 이미지를 조각내기 위함, 다른 패키지 추가 금지, 해석된 버전을 `summary`에 적는다). **이 step 안에서는 실제 호출을 하지 않는다.**

- **조각 나누기**: 이미지는 호출 쪽이 메모리 바이트로 넘긴다(디스크에 쓰지 않는다). 가로를 1,000px로 맞추고(더 좁으면 그대로) 세로 2,000px 조각을 400px 겹치게 자른다(공식몰 절의 방식). **높이가 두 배여도 이미지 토큰이 같다(큰 이미지는 고정 예산으로 축소된다, 계약 실측)는 것이 조각을 나누는 이유이고 조각당 입력이 약 1,000토큰이다.** 마지막 조각이 짧아도 버리지 않는다.
- **읽는 순서**: 상세 이미지를 **뒤쪽부터**(전성분은 보통 끝부분) 조각내어 모델에 넣고, **전성분이 추출되면(비어 있지 않은 성분 목록) 멈춘다**. 앞쪽 이미지는 읽지 않는다(단 용량·제형·효능 문구가 필요하면 `read_all=True` 옵션으로 전부 읽을 수 있고 기본은 `False`).
- **구조화 출력**: `domain/products.py`의 `ProductDetailResult` 스키마(전성분 목록(인쇄 순서, 원문 그대로, 괄호 속 함량 표기는 별도 필드), 용량 값·단위, 제형, 권장 피부 타입, 효능 문구 목록, 기능성 표기 목록)로 `response_format`을 만들고, **목록 밖 값이면 1회 재요청 뒤 보류**한다. 모델 호출은 `llm` 래퍼만, 모델 ID는 `ANALYSIS_MODEL_ID`를 import해서 쓴다(문자열을 쓰지 않는다). `thinking_level`은 필수 인자로 받는다. 원장 `purpose`는 `product-detail`이다. 프롬프트에는 가격을 묻지 않는다.
- **격리**: 조각 하나의 호출 실패는 기록하고 다음 조각으로 넘어간다, 시스템 장애(크레딧 소진 402·일일 한도·인증)는 멈추고 예외를 올려 호출 쪽이 제품을 대기로 둔다(FP-C07). 잘못된 이미지·디컴프레션 봄·움직이는 GIF(첫 프레임만 쓰거나 건너뛴다, 둘 중 하나를 정해 문서화)는 `PRODUCT_IMAGE_INVALID`로 격리한다. `Image.MAX_IMAGE_PIXELS`를 설정해 디컴프레션 봄을 막는다.
- 모델 출력 원문은 `ProductExtraction`으로 돌려준다(저장은 step 7).
- **비용 가정(실측 기반, 추정)**: 2026-11-15 합성 이미지 실측으로 조각(1000×2000)당 입력 약 1,081토큰, 호출당 약 $0.0009(출력 약 25토큰, `minimal`)다. 코스알엑스 1개 상품은 이미지 9장·세로 합계 50,881px이었고 조각 36개였다(관측 1건). 실제 이미지·긴 출력(전성분 목록)에서는 달라진다. **이 값을 코드의 상한·기준으로 쓰지 않는다.**

### 반드시 있어야 하는 테스트

(가짜 `interactions_fn`·합성 이미지(Pillow로 만든 흰 배경 PNG)만 쓴다. 모델 응답은 `gemini_interactions_image_input.json`의 구조에 맞춘 합성 본문이다.)
- 조각 나누기: 합성 1000×5000 이미지가 2,000px 조각·400px 겹침으로 나뉘고 조각 수·각 조각 높이·겹침이 불변식으로 맞다(손계산), 가로가 1,000보다 넓으면 줄이고 좁으면 그대로다, 마지막 조각이 짧아도 남는다, 디스크에 파일이 쓰이지 않는다(`tmp_path`에 새 파일 없음).
- 읽는 순서: 이미지가 여러 장이면 마지막 이미지의 마지막 조각부터 호출된다(호출 인자의 순서 기록), 전성분이 나오면 이후 조각을 호출하지 않는다(호출 횟수), 전성분이 끝내 나오지 않으면 모든 조각을 읽고 `성분 없음`으로 돌려준다(오류가 아니다), `read_all=True`면 전부 읽는다.
- 검증: 목록 밖 값은 1회 재요청 뒤 보류(재요청 횟수 검사), 형식·재요청·보류만 검사하고 모델이 고른 값을 기대값으로 굳히지 않는다(FP-C03), 재시도 가능 오류만 재시도한다, 크레딧 소진·일일 한도는 예외가 올라간다(제품을 실패로 기록하지 않는다, FP-C07).
- 격리: 조각 하나의 오류가 다음 조각을 막지 않는다, 잘못된 이미지·거대한 합성 이미지는 `PRODUCT_IMAGE_INVALID`다.
- 모델 ID가 `analysis/product_detail.py`에 문자열로 없다(`tests/test_analysis_full.py::test_analysis_model_id_has_one_source`가 통과), 호출 인자에 `temperature`가 없다.
- `tests/test_architecture.py`가 통과한다(`analysis`는 `domain`·`llm`만).

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

- 실제 Gemini를 호출하지 마라. 테스트는 가짜 `interactions_fn`만 쓴다. 이유: 비용이 든다(AGENTS.md CRITICAL).
- 이미지를 디스크에 쓰거나 저장하지 마라. 이유: AGENTS.md CRITICAL(공식몰 이미지는 저장·재배포하지 않는다).
- `analysis/product_detail.py`에 모델 ID 문자열(`gemini-3.6-flash`)을 쓰지 마라. 이유: `tests/test_analysis_full.py::test_analysis_model_id_has_one_source`가 모델 ID는 `analysis/models.py` 한 곳에만 있어야 한다고 단언한다. `models.py`는 수정하지 않는다.
- 전성분·효능·피부 타입의 모델 출력 값을 테스트 기대값으로 굳히지 마라. 이유: FP-C03.
- 가격을 이미지에서 읽지 마라. 이유: 행사 문구가 뽑힌다(계약).
- 비용 가정치를 코드의 상한·판정 기준으로 쓰지 마라. 이유: 합성 이미지 2장의 실측이다(FP-C06). 상한은 `llm` 래퍼의 원장 검사가 한다.
- 시스템 장애(402·일일 한도)를 제품 실패로 기록하거나 재시도하지 마라. 이유: FP-C07.
