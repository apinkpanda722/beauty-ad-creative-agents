# Step 3: youtube-brand

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P2 sources-pilot"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/src/beautyads/sources/youtube.py` — P1 산출물(`_creative`, `fetch_videos`, `collect_youtube`)
- `/src/beautyads/sources/config.py` — `YouTubeChannel`(`brand`, `handle`)
- `/src/beautyads/domain/creative.py` — step 2가 추가한 `brand`·`account`
- `/tests/test_youtube.py` — P1 테스트(이 step이 기대값을 갱신한다)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/sources/youtube.py`, `tests/test_youtube.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/sources/youtube.py`, `tests/test_youtube.py`(추가·갱신에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 라벨 키 파일을 읽는 채점 함수, 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

YouTube 어댑터가 만드는 `Creative`에 브랜드와 계정을 채운다. 변경은 이 두 가지뿐이다.

- `_creative`와 `fetch_videos`에 키워드 인자 `brand: str | None = None`, `account: str | None = None`을 추가하고 `Creative`의 `brand`·`account`로 넘긴다(기본값 `None`이라 직접 호출하는 기존 코드가 깨지지 않는다).
- `collect_youtube`가 채널마다 `fetch_videos`를 부를 때 `brand=channel.brand`, `account=channel.handle`을 넘긴다.

그 밖의 동작(채널 찾기, 쪽 넘김, 통계 변환, `analyzable` 판정, 오류 코드, 중단 조건)은 **한 줄도 바꾸지 않는다.**

소비자 테스트 점검 결과: `tests/test_slice.py`는 `sources.youtube`를 import하지만 소재의 필드를 개별로 단언하며 `Creative` 전체 동등성을 단언하지 않는다(확인함). 그 파일은 수정하지 않는다. 깨지면 고치지 말고 `blocked`로 보고한다.

### 반드시 있어야 하는 테스트 (`tests/test_youtube.py`)

- `collect_youtube`가 돌려준 모든 `Creative`의 `brand`와 `account`가 해당 채널의 `brand`·`handle`과 같다(채널이 둘 이상인 입력에서 채널별로 확인한다. 서로 다른 브랜드의 소재가 섞이지 않는다).
- `fetch_videos`를 `brand`·`account` 없이 부르면 둘 다 `None`이다.
- 기존에 `Creative` 전체 동등성을 단언하던 테스트가 있으면 새 필드를 반영해 **같은 강도로** 갱신한다.

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

- 채널 찾기·쪽 넘김·통계·`analyzable`·오류 처리 코드를 바꾸지 마라. 이 step은 브랜드·계정 전달만 다룬다. 이유: P1에서 승인된 동작이 조용히 바뀌면 검토되지 않은 변경이 된다.
- `brand`를 `snippet.channelTitle`이나 채널 이름 문자열에서 추측하지 마라. 설정의 `YouTubeChannel.brand`만 쓴다. 이유: 채널 이름은 브랜드 이름과 다르고 공식 계정 확인은 설정에 있다(TROUBLESHOOTING 2026-11-11).
- 기존 테스트의 단언을 약화하지 마라. 필요하면 새 필드를 반영해 같은 강도로 고친다(B-FP-056).
- `sources/config.py`나 `domain/`을 고치지 마라(수정 허용 경로 밖). 이유: 이 step의 범위는 어댑터 한 파일이다.
