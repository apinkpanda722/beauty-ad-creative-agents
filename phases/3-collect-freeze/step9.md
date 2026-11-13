# Step 9: tiktok-collect

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P3 `tiktok-collect` 행, §8 결정 4·5·11번(집행 주체 규칙, E1 제외, TikTok 유지)
- `/docs/CONTRACTS.md` — TikTok 절(호스트, `fields`, 본문 키, 토큰, 쪽 넘김 `has_more`, `ad.id` 중복 제거)
- `/src/beautyads/sources/tiktok.py`, `/src/beautyads/sources/config.py` — `collect_tiktok`, `TokenProvider`, `tiktok_httpx_post`, `load_tiktok_config`, `load_retailers`
- `/config/sources.yaml`(`tiktok` 절), `/config/retailers.yaml`(판매처 시드, 사용자 확인 대기 중인 초안)
- `/src/beautyads/pipeline/collect.py`, `/src/beautyads/pipeline/preflight.py` — 계정 단위 저장·보고·점검·종료 코드·`--dry-run` 방식(**그대로 따른다. 이 파일들은 고치지 않는다**)
- `/.env.example`, `/README.md`, `/Makefile`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/pipeline/collect_tiktok.py`(새 파일), `Makefile`, `README.md`, `.env.example`, `tests/test_collect_tiktok.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/pipeline/collect_tiktok.py`, `Makefile`(`live-tiktok` 타깃과 `.PHONY` 추가에 한함, 기존 타깃·`verify` 불변), `README.md`(live-tiktok 절 추가에 한함), `.env.example`(변수 이름이 이미 있으면 바꾸지 않는다, 없는 이름만 추가), `tests/test_collect_tiktok.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

소비자 테스트 점검 결과: `scripts/test_hooks.py`는 임시 디렉터리에 자기 `Makefile`을 만들어 쓰므로 영향이 없다. `tests/test_compose.py`·`tests/test_slice.py`·`tests/test_collect.py`·`tests/test_pilot.py`는 저장소 `Makefile`을 읽지만 `.PHONY`는 부분집합으로, 기존 타깃의 레시피 원문은 정확히, `verify` 레시피는 `live-`가 없음을 단언한다. 따라서 **새 타깃은 추가하되 기존 타깃의 레시피 원문·`verify` 레시피·그 뒤의 빈 줄 형식은 바꾸지 않는다.** `tests/test_architecture.py`는 새 모듈에 계층 규칙을 적용한다(통과해야 한다). 이 파일들은 수정하지 않는다. 깨지면 고치지 말고 `blocked`로 보고한다.

TikTok Commercial Content API의 광고를 **브랜드별로 수집해 저장**하는 별도 실행기다(`make live-tiktok` → `uv run python -m beautyads.pipeline.collect_tiktok`). **기존 `live-collect`(`pipeline/collect.py`)와 그 테스트·Makefile 레시피는 바꾸지 않는다**(실패 격리). `pipeline/`에 두고 `httpx`·`psycopg`를 직접 import하지 않는다(어댑터와 `store`의 함수를 부른다). **TikTok 어댑터는 지금까지 가짜 응답으로만 검증됐다 — 첫 실서비스 호출이므로 작게 시작할 수 있게 한다.** **이 step 안에서는 `make live-tiktok`을 실행하지 않는다. 테스트는 모두 가짜 의존성으로 한다.**

- **옵션**: `--brands a,b`(기본 설정의 전체 브랜드), `--max-pages N`(브랜드당 쪽 수 상한, 기본 **1**, 범위 1~50; 첫 실행은 작게 시작하라고 README에 쓴다), `--dry-run`.
- **흐름**: 점검 뒤 `TokenProvider`로 토큰을 받고(`TIKTOK_CLIENT_KEY`·`TIKTOK_CLIENT_SECRET`을 `settings.require_setting`으로 읽는다), `collect_tiktok(post, token, config, retailers, max_pages=…, collected_at=now, brands=…)`를 부르고, **브랜드 단위 오류가 없는 브랜드의 소재만 `store.upsert_creatives`로 저장한다**(오류가 난 브랜드는 `errors`에 코드가 남고 저장하지 않는다 — P2 수집의 부분 계정 처리와 같은 방식, 다음 실행이 처음부터 다시 받는다). 중단(`stopped`) 코드가 있으면 그것을 보고하고 종료 코드 3이다.
- **환경 점검**(하나라도 있으면 `PREFLIGHT_FAILED <코드>`, 종료 코드 2, **그 전에는 호출·접속을 하지 않는다**): `ENV_MISSING:TIKTOK_CLIENT_KEY`, `ENV_MISSING:TIKTOK_CLIENT_SECRET`, `ENV_MISSING:POSTGRES_PASSWORD`, `DOCKER_DOWN`, `POSTGRES_UNREACHABLE`, 설정 문제(`TIKTOK_CONFIG_UNREADABLE`·`TIKTOK_CONFIG_INVALID`, 판매처 파일 문제는 로더의 코드를 그대로). `StoreConnectError` 코드는 출력(DSN·비밀번호 미출력).
- **보고**: 브랜드마다 JSON 한 줄(`event`, `brand`, `fetched`, `executor` 분포(`brand`·`retailer`·`불명` 등 분류기가 돌려주는 값 그대로), `error`)을 진행 중에 출력하고, 끝에 요약(브랜드별 건수, 집행 주체 분포, 오류·중단 코드, 사용한 판매처 시드 파일 경로와 항목 수, 총 소요)을 출력한다. **키·토큰·영상 주소·`Authorization` 값은 출력하지 않는다.**
- `--dry-run`: 네트워크·DB 접속 없이 호출 수 범위(브랜드 수 × 쪽 수)와 "호출당 시간은 가정(미실측)"을 `ESTIMATE ...` 한 줄로 출력하고 0으로 끝난다.
- TikTok 소재는 **영상 주소를 저장하지 않는다**(서명 URL, 분석 직전 `tiktok-plans`가 재조회한다).
- 종료 코드: 0 성공, 2 점검 실패, 3 중단(토큰 오류·레이트 리밋 등) 또는 브랜드 오류가 있음.
- `Makefile`: `live-tiktok` 타깃을 `.PHONY`와 함께 추가하고 `verify`는 바꾸지 않는다. README에 선행 조건(OrbStack, `make db-up`, `.env`의 `TIKTOK_CLIENT_KEY`·`TIKTOK_CLIENT_SECRET`, 판매처 시드 확인), 사용법(`--dry-run`, 작게 시작: `--brands mixsoon --max-pages 1`), 이유 코드 표, 토큰 만료(7200초) 안내, "TikTok은 E1 표본에서 제외된다(그래프·에이전트 데이터)"를 쓴다.

### 반드시 있어야 하는 테스트

(가짜 `post` 함수는 `tests/fixtures/contracts/`의 `tiktok_*.json` 원본에서 만든 본문이다. 가짜 `TokenProvider`·메모리 저장소.)
- 점검: 각 이유 코드가 해당 조건에서 나오고 출력에 키·토큰이 없으며, 점검 실패 시 토큰 발급·`post`·`deps_factory`가 **한 번도** 불리지 않는다.
- 저장: 오류 없는 브랜드의 소재만 저장되고 오류가 난 브랜드는 저장되지 않는다, `ad.id`가 같은 소재는 한 번만 저장된다, 저장된 소재에 영상 주소가 없다(감시 문자열 확인), `brand`가 채워진다.
- 중단: 토큰·레이트 리밋 등 `_STOP_ERRORS`에 해당하는 오류가 오면 이후 브랜드를 호출하지 않고 종료 코드 3이며, 그 전에 끝난 브랜드는 저장된다.
- `--brands`로 지정한 브랜드만 호출된다, `--max-pages 0`·`51`은 오류 종료, 기본값은 1쪽이다.
- 보고·출력에 키·토큰·영상 주소·`Authorization` 문자열이 없다(감시 값을 주입해 확인), 집행 주체 분포가 합성 입력의 손계산 값과 같다.
- `--dry-run`이 의존성 생성 함수·`post`를 한 번도 부르지 않고 `ESTIMATE`를 출력한다.
- 기존 `tests/test_collect.py`가 그대로 통과하고(수정하지 않음), `Makefile`의 `verify` 레시피에 `live-`가 없으며 `live-tiktok` 타깃과 `.PHONY` 항목이 있다.

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
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
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

- `make live-tiktok`을 실행하지 마라. 테스트는 가짜 의존성만 쓴다. 이유: 실제 호출·DB 접속은 사용자의 live 실행이고 TikTok은 실서비스 호출이 처음이다.
- `pipeline/collect.py`·`tests/test_collect.py`·`live-collect` 레시피를 바꾸지 마라. 이유: YouTube·Instagram 수집의 계약을 건드리지 않고 TikTok을 격리한다(A-FP-030).
- 영상 주소·서명 URL·토큰을 저장하거나 출력하지 마라. 이유: TikTok 서명 URL은 만료되고(저장 금지, 분석 직전 재조회) 토큰은 비밀 값이다.
- 오류가 난 브랜드의 부분 결과를 저장하지 마라(P2 수집과 같은 방식). 이유: 어느 쪽까지 받았는지 알 수 없는 상태로 남으면 다음 실행이 빈 구간을 채울 수 없다.
- 400대 응답이나 토큰 오류를 반복 재시도하지 마라. 이유: 인증 오류를 반복하면 한도만 깎는다.
- 판매처 시드(`config/retailers.yaml`)를 고치지 마라. 이유: 사용자 확인을 기다리는 초안이다.
- 환경 점검이 통과하기 전에 네트워크 호출·DB 접속을 하지 마라. `--dry-run`도 하지 않는다. 이유: B-FP-051.
