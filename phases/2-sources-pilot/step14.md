# Step 14: creative-attributes

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P2 sources-pilot"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/ARCHITECTURE.md` — 온톨로지 2층 `Creative`(게시 형태, 집행 주체, 지표 요약)와 "지표 정규화"(출처마다 지표의 뜻이 다르다)
- `/docs/CONTRACTS.md` — TikTok 표·주의(도달 수는 구간 문자열, 광고주 이름의 40%가 숫자, 집행 주체 혼재, 게재 시작·종료일)
- `/src/beautyads/domain/creative.py`, `/src/beautyads/domain/__init__.py`, `/src/beautyads/store/schema.py`, `/src/beautyads/store/repository.py` — 이전 step 산출물(`brand`·`account` 추가 이후)
- `/tests/test_domain.py`, `/tests/test_store.py` — 기존 테스트

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/creative.py`, `src/beautyads/store/schema.py`, `src/beautyads/store/repository.py`, `tests/test_domain.py`, `tests/test_store.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/creative.py`(필드 추가에 한함), `src/beautyads/store/schema.py`(마이그레이션 v3 추가와 `CHANGE_COLUMNS`·`INSERT_COLUMNS`·`_INSERT_TYPES` 확장에 한함, 기존 열 순서·타입 변경 금지), `src/beautyads/store/repository.py`(새 열 처리 추가에 한함), `tests/test_domain.py`(추가·갱신에 한함, 단언 약화 금지), `tests/test_store.py`(추가·갱신에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 라벨 키 파일을 읽는 채점 함수, 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

TikTok 광고에는 `Creative`로 담을 수 없는 **출처 고유 정보**가 있다: 게재 시작·종료일, 도달 구간 문자열(`"600K-700K"`), 광고주 정보(`business_id`, `business_name`, `paid_for_by`), 집행 주체 판정. 출처마다 지표의 뜻이 달라 공통 열로 만들면 안 되므로 **자유 형식 속성 하나**(`attributes`)를 추가한다. 이 step은 `domain`과 `store` 두 계층을 함께 바꾼다(P2 step 2와 같은 이유로 한 step으로 둔다). 다음 step(TikTok 어댑터)이 이 필드를 채운다.

소비자 테스트 점검 결과: `Creative`의 새 필드는 기본값이 있어 기존 호출이 깨지지 않는다. `tests/test_store.py`의 `CHANGE_COLUMNS` 정확 일치 단언은 이 step이 새 목록으로 **갱신**한다(여전히 정확 일치로 단언한다). 가짜 저장소는 Protocol을 상속하지 않는 일반 클래스이고 이 step은 Protocol 메서드를 바꾸지 않는다. 다른 테스트 파일은 수정하지 않는다. 깨지면 고치지 말고 `blocked`로 보고한다.

### 변경

- `Creative`에 `attributes: dict[str, Any] = Field(default_factory=dict)`를 추가한다(JSON 직렬화 가능한 값만. 기본은 빈 딕셔너리).
- **마이그레이션 버전 3**(`creative_attributes`): `ALTER TABLE creatives ADD COLUMN IF NOT EXISTS attributes jsonb`. 이전 버전은 고치지 않고 `DROP`·`TRUNCATE`를 쓰지 않는다. 기존 행은 NULL이고 복원할 때 빈 딕셔너리로 본다.
- `CHANGE_COLUMNS`에 `attributes`를 **추가**한다(내용 열. 수집 시각 열은 여전히 포함하지 않는다). 업서트의 `IS DISTINCT FROM` 비교와 `SET`이 새 열을 다룬다. **jsonb 비교는 키 순서와 무관**하므로 같은 속성을 다른 순서로 넣어도 `updated_at`이 바뀌지 않는다. 값은 `json.dumps`한 문자열을 `%s::jsonb`로 전달한다(매개변수 방식 유지).
- 행 복원: `attributes`가 NULL이면 `{}`, 아니면 `dict`. `collection_stats` 등 다른 쿼리는 바꾸지 않는다.

### 반드시 있어야 하는 테스트

- `tests/test_domain.py`: `attributes`를 생략하면 빈 딕셔너리, 중첩 값(문자열·숫자·목록·딕셔너리)을 보존, 서로 다른 `Creative` 인스턴스가 같은 기본 딕셔너리 객체를 공유하지 않는다(`default_factory`).
- `tests/test_store.py`: **`CHANGE_COLUMNS` 정확 일치 단언을 새 목록(이전 목록 + `attributes`)으로 갱신**하고 수집 시각 열 4개가 없음을 계속 단언한다. 마이그레이션 버전 3 SQL에 `IF NOT EXISTS`가 있고 `DROP`·`TRUNCATE`가 없다(버전 단언은 `MIGRATIONS`에서 파생한 값과 비교한다). 업서트 `params`에 `attributes`가 JSON 문자열로 들어가고 `%s::jsonb` 형태이며 값이 SQL 문자열에 없다(따옴표가 든 속성 값으로 확인). 같은 속성을 키 순서만 바꿔 넣어도 비교 열에 같은 값이 전달됨(직렬화 시 키를 정렬한다). NULL → `{}` 복원.

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

- `attributes`에 영상·이미지 주소(만료되는 서명 URL)나 토큰을 넣는 것을 허용하는 코드를 만들지 마라. 이 step은 필드만 추가하고 어댑터가 넣을 값은 다음 step이 정한다. 이유: 만료되는 주소를 저장해 두면 쓸 수 없고 서명이 포함된다.
- `CHANGE_COLUMNS`에 수집 시각 열을 넣거나 기존 단언을 느슨하게 하지 마라. 정확 일치는 새 목록으로 바꾸되 정확 일치로 유지한다(B-FP-056). 이유: 열 목록은 증분 동기화의 핵심 계약이다.
- 마이그레이션 버전 1·2를 고치거나 `DROP`·`TRUNCATE`를 쓰지 마라. 새 변경은 버전 3으로만 한다. 이유: 이미 적용된 마이그레이션을 고치면 환경마다 스키마가 달라진다.
- jsonb 값을 SQL 문자열에 이어 붙이지 마라. `%s::jsonb` 매개변수로만 전달한다. 이유: 따옴표가 든 속성 값이 쿼리를 깨뜨리거나 주입된다.
- 지표 전용 열(`latest_*`)을 TikTok 도달 구간으로 재사용하지 마라. 도달 구간은 `attributes`에 문자열로 둔다. 이유: 출처마다 지표의 뜻이 달라 직접 비교하면 안 된다(ADR-004).
