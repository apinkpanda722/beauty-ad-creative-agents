# Step 2: mfds-source

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조, 온톨로지 절, 데이터 흐름
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P4 절과 변경 기록 #36
- `/docs/COMPETENCY_QUESTIONS.md` — v1(2026-11-15 동결), 홉 정의와 한계
- `/docs/CONTRACTS.md` — 식약처 공공 API 절 전체(원료성분정보, 보고품목, 심사품목, 선케어 SPF·PA, 오류 본문 형태, 활용신청)
- `/docs/ADR.md` — ADR-013
- `/tests/fixtures/contracts/mfds_*.json`, `/tests/fixtures/contracts/instagram_mfds_youtube_probe.json` — 응답 원본(**픽스처는 이 파일들에서만 만든다**)
- `/src/beautyads/sources/youtube.py`, `/src/beautyads/sources/instagram.py` — 어댑터 구조·오류 처리 방식(**그대로 따른다**)
- `/src/beautyads/settings.py` — `.env` 읽기(`DATA_GO_KR_SERVICE_KEY`)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/mfds.py`(새 파일), `src/beautyads/sources/mfds.py`(새 파일), `tests/test_mfds.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/mfds.py`, `src/beautyads/sources/mfds.py`, `tests/test_mfds.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

식약처 공공 API 세 개(원료성분정보, 기능성화장품 보고품목, 기능성화장품 심사품목)의 어댑터를 만든다. **어댑터만 만들고 이 step 안에서는 호출하지 않는다.** 첫 실서비스 호출은 step 7(`product-records`)의 live 실행기가 한다. `httpx`는 `sources`에서만 import한다.

- **`domain/mfds.py`**: `IngredientStandard`(`name_ko`, `name_en`, `cas_no`; 없을 수 있는 값은 `None`), `FunctionalReport`(`item_name`, `entp_name`, `report_date`, `effect_text`, `spf`, `pa`, `cancelled`, `source`(`report`·`screening`)), `CertStatus`(`certified`·`unknown`·`not_certified` 중 계약이 허용하는 것만: **자외선 차단의 null은 `unknown`**), 기능성 종류 판정에 쓰는 닫힌 값 `FunctionalKind`(`brightening`·`anti_aging`·`sun_protection`)와 `functional_kinds(report)` 순수 함수(`effect_text`의 효능효과 문구 또는 `SPF`·`PA` **값이 있을 때만** 종류를 돌려주고 값이 없으면 빈 집합이 아니라 `unknown`을 구분해 돌려준다).
- **호출(`sources/mfds.py`)**: 공통 형식 `https://apis.data.go.kr/{기관코드}/{서비스}/{오퍼레이션}?serviceKey=…&type=json&pageNo=&numOfRows=`. 보고품목·원료는 기관 `1471000`, **심사품목은 기관 `1471057`**(`FtnltCosmSrngPrdlstInfoService05/getSrngPrdlstInq05`)으로 다르다. 키는 `settings.require_setting("DATA_GO_KR_SERVICE_KEY")`로만 읽고 URL·로그에 남기지 않는다. **일일 한도는 미확인이므로 호출 수 상한(`max_requests`)을 필수 인자로 받고 넘기면 `MFDS_REQUEST_CAP`으로 멈춘다.** 호출 사이에 `min_interval_s`(기본 0.5, 설정 가능) 대기를 둔다. 재시도는 503·연결 실패·시간 초과에만 한다.
- **응답 읽기**: HTTP 상태를 먼저 본다. 성공 본문은 `{header: {resultCode: "00"}, body: {...}}`이고 `resultCode`가 `"00"`이 아니면 실패다(코드·메시지를 보존). **오류 본문은 성공과 형태가 다르다**(`OpenAPI_ServiceResponse.cmmMsgHeader`, 403 `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`→`MFDS_KEY_NOT_REGISTERED`, 400 `NO_OPENAPI_SERVICE_ERROR`→`MFDS_OPERATION_UNKNOWN`). **결과 없음은 `totalCount` 0이거나 `body`에 `items` 키가 없다**(빈 배열이 아님) — 키 없음을 빈 결과로 읽는다(FP-C01). 항목의 값은 없을 수 있다고 보고 읽는다(`[]` 직접 접근 금지, `.get`).
- **원료성분 정확 일치**: 검색은 부분 일치라 "병풀추출물"이 7건을 돌려준다. 검색어의 **공백을 지우고** 보내고, 응답에서 `INGR_KOR_NAME`이 검색어(공백 제거)와 **정확히 같은** 항목만 표준명으로 인정한다. 정확히 같은 항목이 없으면 "없음"(빈 결과)이지 부분 일치를 대신 고르지 않는다. 쪽이 더 있으면(`totalCount` > 받은 수) 쪽 상한(`max_pages`) 안에서 이어 받고, 상한에서 멈췄으면 "없음"이 아니라 `stopped`(미확정)로 돌려준다(FP-C05).
- **보고품목**: `item_name`(공백 제거)으로 조회하고 **취하(`CANCEL_APPROVAL_YN`)가 `"Y"`인 품목은 걸러 낸다**(표본은 모두 `"N"`이라 `"Y"`의 형태는 미실측이므로 대문자 `Y` 외의 값은 취하로 보지 않고 원값을 `cancelled_raw`로 보존한다). **업체명 파라미터는 걸리지 않으므로 쓰지 않는다. 브랜드를 `ENTP_NAME`으로 판정하지 않는다.** 기능성 종류는 `EE_NAME`(평문)으로, 자외선 차단은 `SPF`·`PA`(문자열, `"50+"`·`"4"` 등)에 **값이 있을 때만** 인정한다. null은 `unknown`이다. `"4"`를 PA++++로 해석하지 않고 문자열 그대로 보존한다(미확인).
- **심사품목**: `EE_DOC_DATA`는 XML 문자열이다. 표준 라이브러리 XML 파서로 `PARAGRAPH`의 텍스트(CDATA 포함)를 꺼낸다. **파싱 전에 `<!DOCTYPE`·`<!ENTITY`가 있으면 거부한다**(외부 응답이라 엔티티 확장 공격을 막는다, `MFDS_XML_REJECTED`). `EE_DOC_DATA`가 `null`이면 `effect_text`는 `None`이다(오류 아님). 이 API에는 `SPF`·`PA`·취하 필드가 없으므로 자외선 차단은 이 API로 판정하지 않는다.
- 세 어댑터 모두 의존성(`get` 함수, 시계, 대기 함수)을 주입받는다. 실제 `httpx` 호출은 기본 구현에만 있고 테스트는 가짜 `get`을 쓴다.

### 반드시 있어야 하는 테스트

(가짜 `get`은 `tests/fixtures/contracts/mfds_*.json`·`instagram_mfds_youtube_probe.json` 원본에서 만든 본문이다.)
- 원료: 원본 응답에서 "병풀추출물" 검색 시 부분 일치 항목들 중 **정확히 같은 표준명만** 돌려준다, 정확 일치가 없으면 빈 결과(부분 일치 대체 금지), 검색어의 공백이 제거되어 요청된다, `no_match` 원본(`totalCount` 0)은 빈 결과, 쪽 상한에서 멈추면 `stopped`.
- 보고품목: 원본에서 항목이 `FunctionalReport`로 바뀐다, `CANCEL_APPROVAL_YN`이 `"Y"`인 합성 항목은 빠지고 `"N"`은 남는다, `SPF`·`PA`가 null이면 `unknown`이고 값이 있으면 `certified`(**"인증 없음"으로 읽지 않는다**), `EE_NAME`의 미백·주름 개선 문구에서 종류가 나온다(합성 문구로 검사, 실제 응답의 문구를 기대값으로 굳히지 않는다).
- 심사품목: 원본의 `EE_DOC_DATA` XML에서 `PARAGRAPH` 텍스트가 나온다(형식·비어 있지 않음만 단언), `null`이면 `effect_text`가 `None`, `<!DOCTYPE`·`<!ENTITY`가 든 합성 XML은 `MFDS_XML_REJECTED`, `items` 키가 없는 `no_match` 본문은 빈 결과.
- 오류: 403 `mfds_error_key_not_registered.json` 본문→`MFDS_KEY_NOT_REGISTERED`(성공 본문과 다른 형태를 받는다), HTTP 상태를 먼저 본다(상태가 200이 아니면 본문 형태에 상관없이 실패 코드), 400 `NO_OPENAPI_SERVICE_ERROR`→`MFDS_OPERATION_UNKNOWN`, 503은 재시도하고 403·400은 재시도하지 않는다, `resultCode`가 `"00"`이 아니면 실패.
- 호출 수 상한: `max_requests`를 넘으면 더 호출하지 않고 `MFDS_REQUEST_CAP`이다, 상한 인자 없이는 호출할 수 없다(필수 인자), 간격 대기 함수가 호출 사이에 불린다.
- 비밀: 키가 URL·로그·예외 메시지·반환값에 없다(감시 값 주입), `DATA_GO_KR_SERVICE_KEY` 미설정은 `MissingSetting`을 코드로 바꾼 결과(`ENV_MISSING:DATA_GO_KR_SERVICE_KEY`).

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

- 실제 식약처 API를 호출하지 마라. 테스트는 가짜 `get`만 쓴다. 이유: 실제 호출은 사용자의 live 실행이고 일일 한도가 미확인이다.
- 부분 일치 결과에서 "가장 비슷한" 항목을 고르지 마라. 이유: "시카"는 무관한 성분 20건을 돌려준다(계약). 정확히 같은 표준명만 인정한다.
- `ENTP_NAME`·업체명으로 브랜드나 제품을 판정하지 마라. 이유: 업체명은 브랜드와 다를 수 있다(코스알엑스 사례).
- `SPF`·`PA`의 null을 "인증 없음"으로 읽거나 품목명의 "SPF" 글자를 파싱해 판정하지 마라. 이유: 선케어 대부분이 null이고 필드가 비어 있어도 제품명에 SPF가 있다(계약). null은 `unknown`.
- 심사품목에서 자외선 차단을 판정하지 마라. 이유: 이 API에는 `SPF`·`PA`가 없다.
- `items` 키·값이 항상 있다고 가정하지 마라(`[]`·`[0]` 직접 접근 금지). 이유: FP-C01.
- 쪽 상한에서 멈춘 조회를 "없음"으로 확정하지 마라. 이유: FP-C05.
- 키를 코드·테스트·문서·로그에 남기지 마라. 이유: 비밀 값이다.
- 한도 수치·겹침 규모를 추정해 코드 상수로 박지 마라. 이유: 미확인이다(FP-C06). 호출 수 상한은 호출하는 쪽이 정한다.
