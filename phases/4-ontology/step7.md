# Step 7: product-records

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조, 온톨로지 절, 데이터 흐름
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P4 절과 변경 기록 #36
- `/docs/COMPETENCY_QUESTIONS.md` — v1(2026-11-15 동결), 홉 정의와 한계
- `/docs/ADR.md` — ADR-013, ADR-012 후속 결정(성분→효능 수기 표는 이 step의 live 뒤)
- `/docs/CONTRACTS.md` — 식약처 절, 공식몰 절과 2026-11-15 재실측, Gemini 이미지 입력 절
- `/src/beautyads/sources/mfds.py`, `/src/beautyads/sources/mall.py`, `/src/beautyads/analysis/product_detail.py`, `/src/beautyads/store/product_repository.py`, `/src/beautyads/domain/products.py` — step 2~6 산출물
- `/src/beautyads/pipeline/preflight.py`, `/src/beautyads/pipeline/collect_tiktok.py`, `/src/beautyads/pipeline/analyze_target.py` — 실행기 구조(점검·보고·종료 코드·`--dry-run`, **그대로 따른다**)
- `/config/product_candidates.yaml`(임시, 사용자 확정 대기, **고치지 않는다**), `/Makefile`, `/README.md`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/pipeline/products.py`(새 파일), `config/ingredient_aliases.yaml`(새 파일), `config/product_aliases.yaml`(새 파일), `Makefile`, `README.md`, `tests/test_products_pipeline.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/pipeline/products.py`, `config/ingredient_aliases.yaml`, `config/product_aliases.yaml`, `Makefile`(`live-products` 타깃과 `.PHONY` 추가에 한함, 기존 타깃·`verify` 불변), `README.md`(live-products 절 추가에 한함), `tests/test_products_pipeline.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

소비자 테스트 점검 결과: `tests/test_compose.py`·`tests/test_slice.py`·`tests/test_collect.py`·`tests/test_pilot.py`는 저장소 `Makefile`을 읽고 `.PHONY`는 부분집합으로, 기존 타깃의 레시피 원문은 정확히, `verify` 레시피는 `live-`가 없음을 단언한다. 따라서 **새 타깃은 추가하되 기존 타깃의 레시피 원문·`verify` 레시피·형식은 바꾸지 않는다.** 이 테스트 파일들은 수정하지 않는다. 깨지면 고치지 말고 `blocked`로 보고한다.

대표 단품 목록의 공식몰 상세페이지와 식약처 표준명·기능성 보고품목으로 제품 레코드를 만들어 저장하는 실행기와 `make live-products`를 만든다(PHASES 목록에 없던 추가, 사용자 승인 2026-11-15). **이 step 안에서는 `make live-products`를 실행하지 않는다.**

- **흐름**: 대표 단품 목록(`config/product_candidates.yaml`) → 공식몰(`sources/mall`: 가격·전성분 텍스트·이미지 주소, 제외 몰은 건너뜀) → 텍스트가 없으면 이미지를 메모리로 받아 추출(`analysis/product_detail`, 뒤쪽부터, 전성분을 찾으면 멈춤) → **성분 원문을 식약처 표준명과 정확 일치로 대조**(`sources/mfds`, 표준명 캐시 우선, 통용명→표준명은 `config/ingredient_aliases.yaml`) → 묶이지 않는 표기는 버리지 않고 `미해결`로 보존 → 제품의 기능성 보고·심사품목 대조(제품명 일치 규칙: 공백 제거 정확 일치, 자외선 차단의 null은 `unknown`) → 저장(`store/product_repository`). **광고 소재의 성분 원문(`full@v1`의 `ingredients`)도 같은 표준명 사전으로 묶고, 목록 밖은 폐기하지 않고 `미해결`로 남긴다.**
- **별칭**: 제품 별칭은 `derive_aliases`(step 5)가 제품명에서 **기계적으로 만든다**(사용자가 채우지 않는다). `config/product_aliases.yaml`은 선택적인 추가·제외 목록(제품 `brand`·`name_ko`별 `extra`·`drop`)이고 비어 있어도 된다. `config/ingredient_aliases.yaml`(성분 통용명→표준명, 항목마다 출처 필수)은 사용자·조언 세션이 채운다. 이 step은 두 파일의 로더와 빈 파일(머리 주석만)을 만든다. 파일이 없거나 비어 있으면 추가 별칭 0개로 동작하고 요약에 별칭 수를 낸다. 출처가 없는 성분 별칭은 로더가 `ALIAS_INVALID`로 거부한다.
- **`--scan`(공식몰 HTTP만, 모델·식약처 호출 없음)**: 후보 제품마다 가격·텍스트 전성분 여부·**상세 이미지 수**를 읽어 출력하고 멈춘다. 예상 비용은 "가정"으로 표시한다: 이미지 수 × `ASSUMED_PIECES_PER_IMAGE`(관측 1건 기반 가정 4) × `ASSUMED_COST_PER_PIECE_USD`(2026-11-15 합성 이미지 실측 약 0.0009)이며 **전성분을 찾으면 멈추므로 상한 추정이다**(두 상수 모두 "가정(미실측)"으로 출력하고 판정 기준으로 쓰지 않는다). 이 출력이 사용자에게 보고되는 "이미지 수·예상 비용"이다.
- **`--dry-run`**: 네트워크·DB 접속 없이 호출 수 범위(후보 수 × 호출 종류)와 "호출당 시간·비용은 가정(미실측)"을 `ESTIMATE ...` 한 줄로 출력하고 0으로 끝난다.
- **`make live-products`**(`uv run python -m beautyads.pipeline.products $(ARGS)`): 점검(`ENV_MISSING:DATA_GO_KR_SERVICE_KEY`·`GEMINI_API_KEY`·`POSTGRES_PASSWORD`, `DOCKER_DOWN`, `POSTGRES_UNREACHABLE`, 공급사 누적액 `COST_CAP:gemini`, 실패하면 `PREFLIGHT_FAILED <코드>` 종료 코드 2, 그 전에는 호출·접속하지 않는다) 뒤 시작한다. 옵션 `--scan`, `--dry-run`, `--products a,b`(작게 시작), **`--max-mfds-requests N`(필수, 식약처 일일 한도 미확인)**, `--thinking-level`(기본 `minimal`). **Gemini 상한은 이 live에 한해 `BEAUTYADS_CAP_GEMINI_USD=14`까지 승인됐다(사용자 결정 2026-11-15). 실행 전에 `--scan`으로 이미지 수·예상 비용을 보고하고 멈춘 뒤 사용자 지시를 받아 실행한다.** README에 이 순서(`--scan` → 보고 → 승인 → 실행)와 상한 환경 변수 사용법을 쓴다. 상한을 코드·테스트에 박지 않는다.
- **보고(실행 요약)**: 제품 수, 성분 묶임 비율(`미해결` 수), 기능성 연결 커버리지(`certified`·`unknown` 수), 모델 호출 수·비용(호출 종류별 원장 `purpose`), 별칭 수, 실패·보류 코드. **성분 빈도 표(성분 표준명·건수만, 건수 내림차순 상위 N, 기본 50)를 별도 출력한다**(조언 세션이 성분→효능 수기 표의 상위 약 20개에 출처를 붙이는 입력이다). 키·토큰은 출력하지 않는다.
- 제품 하나·성분 하나의 실패는 기록하고 넘어간다(A-FP-030). 시스템 장애(402·인증·일일 한도)는 멈추고 제품을 대기로 둔다(FP-C07). 식약처 대조가 쪽 상한에서 멈추면 `미해결`이 아니라 재시도 대상이다(FP-C05).
- 종료 코드: 0 성공, 2 점검 실패, 3 중단(시스템 장애) 또는 제품 오류가 있음.

### 반드시 있어야 하는 테스트

(가짜 mall·mfds·모델·저장소만 쓴다. 가짜 본문은 `tests/fixtures/contracts/`의 원본에서 만든다.)
- 성분 대조: **정확 일치만** 묶고 부분 일치는 묶지 않는다, 묶이지 않는 표기는 `미해결`로 남는다(폐기 0건), 별칭 표가 통용명(합성 항목)을 표준명으로 잇는다, 광고 소재 성분 원문도 같은 대조를 거친다, 대조 조회가 `stopped`면 `미해결`이 아니라 재시도 대상이다, 출처 없는 성분 별칭은 `ALIAS_INVALID`.
- 제품 인증: 자외선 차단의 null은 `unknown`이고 `certified`로 읽히지 않는다, 취하 품목은 빠진다, 업체명으로 브랜드를 판정하지 않는다.
- 흐름: 텍스트 전성분이 있으면 모델이 호출되지 않는다, 없으면 이미지를 받아 추출하고 전성분을 찾으면 멈춘다, 제외 몰은 요청이 한 번도 없다, 한 제품의 실패가 다음 제품을 막지 않는다, 402는 중단하고 제품이 실패로 기록되지 않는다.
- `--scan`: 모델·식약처·DB가 한 번도 불리지 않는다, 이미지 수·가정 비용 출력에 "가정(미실측)" 표기가 있다, 이미지를 내려받지 않고 주소 수만 센다(`download_detail_image` 호출 0건).
- 점검: 각 이유 코드가 해당 조건에서 나오고 점검 실패 시 호출·접속이 **한 번도** 없다, `--dry-run`이 호출·접속을 하지 않는다, `--max-mfds-requests` 없이는 시작하지 않는다, 출력에 키·토큰·이미지 바이트가 없다(감시 값 주입).
- 빈도 표가 합성 입력의 손계산 값과 같다(성분·건수 이름 집합 비교).
- `Makefile`에 `live-products`가 있고 `verify` 레시피에 `live-`가 없다.

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

- `make live-products`(`--scan` 포함)를 실행하지 마라. 이유: 공식몰 요청·식약처 호출·Gemini 비용은 사용자가 승인하고 실행한다.
- Gemini 상한(`$12`·`$14`)을 코드·테스트·Makefile에 박지 마라. 이유: 정지선은 사용자가 환경 변수로 정한다(AGENTS.md CRITICAL). `14`는 이 live에 한한 승인이라 README에 절차로만 적는다.
- 표준명과 부분 일치로 묶거나 목록 밖 성분을 폐기하지 마라. 이유: 묶이지 않는 표기는 `미해결`로 보존한다(ARCHITECTURE).
- `config/product_candidates.yaml`·`config/retailers.yaml`을 고치지 마라. 이유: 사용자 확인 대기 파일이다.
- 성분 별칭을 모델로 만들거나 추측해 채우지 마라. 이유: 출처가 필요하고 사용자·조언 세션이 채운다. 제품 별칭도 모델로 만들지 않고 `derive_aliases`만 쓴다.
- 식약처 업체명으로 브랜드·제품을 판정하지 마라. 이유: 계약.
- 이미지를 디스크에 쓰거나 저장하지 마라. 이유: AGENTS.md CRITICAL.
- 환경 점검이 통과하기 전에 네트워크 호출·DB 접속을 하지 마라(`--dry-run` 제외 시). 이유: B-FP-051.
