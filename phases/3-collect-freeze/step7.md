# Step 7: metrics-normalize

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P3 `metrics-normalize` 행
- `/docs/EVAL.md` — "지표 정규화"와 E4(상위·하위 25% 표본에 쓰임)
- `/docs/ARCHITECTURE.md` — "지표 정규화" 절(출처 간 직접 비교 없음)
- `/src/beautyads/domain/creative.py` — `Creative`, `Metrics`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/analysis/metrics.py`(새 파일), `tests/test_metrics_normalize.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/analysis/metrics.py`, `tests/test_metrics_normalize.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

채널 안에서의 조회수 백분위와 상·하위 구분을 계산하는 **순수 함수**를 만든다(`analysis/`는 `domain`, `llm`만 import할 수 있고 이 모듈은 `domain`만 쓴다). DB·네트워크·모델을 쓰지 않는다. 결과의 저장·그래프 적재는 P4 `graph-sync`가 한다.

```python
class MetricBand(StrEnum): top = "top"; middle = "middle"; bottom = "bottom"

class NormalizedMetric(BaseModel):   # frozen
    key: CreativeKey
    channel: tuple[Source, str]      # (출처, 채널 식별자)
    percentile: float | None         # [0, 1], 값이 클수록 조회수 상위
    band: MetricBand | None
    reason: str | None               # 계산하지 않은 이유 코드

def normalize_views(creatives: Sequence[Creative], *, as_of: date | datetime,
                    min_age_days: int = 14, min_channel_size: int = 8) -> list[NormalizedMetric]
```

- **채널**: `(source, account)`. `account`가 없으면 `(source, brand)`로 대신하지 않고 `reason="NO_CHANNEL"`로 계산하지 않는다. **출처 간 직접 비교는 하지 않는다**(채널이 출처를 포함하므로 YouTube·Instagram의 백분위는 서로 다른 모집단에서 나온다).
- **대상**: 게시 후 `min_age_days`(기본 14)일 이상 지난 소재만 계산한다. `published_at`이 없으면 `NO_PUBLISHED_AT`, 14일 미만이면 `TOO_RECENT`, `metrics.view_count`가 없으면(키 부재가 정상 상태다) `NO_VIEW_COUNT`로 계산하지 않고 `reason`을 돌려준다. `as_of`는 인자로 받는다(함수 안에서 오늘 날짜를 읽지 않는다).
- **백분위**: 채널 내 대상 소재를 조회수 오름차순으로 세워 **평균 순위 방식**으로 계산한다. 조회수가 같은 소재는 그 순위들의 평균을 순위로 갖고(1부터 시작), `percentile = (순위 - 0.5) / n`(`n`은 채널의 대상 소재 수)이다. 이 정의를 모듈 docstring에 쓴다.
- **구분**: `percentile >= 0.75`이면 `top`, `<= 0.25`이면 `bottom`, 그 사이는 `middle`(경계값은 포함).
- **작은 채널**: 대상 소재가 `min_channel_size`(기본 8, **가정값**이며 docstring에 "가정"이라 적는다) 미만이면 백분위를 계산하지 않고 `reason="CHANNEL_TOO_SMALL"`이다(몇 건만으로 25%를 나누면 의미가 없다).
- 입력 순서가 달라도 결과가 같다(키로 정렬해 결정적으로 계산). 입력을 수정하지 않는다.
- 문서 표현: 조회수에는 광고비 효과가 섞여 있으므로 모듈 docstring과 `MetricBand` 설명에 "성과가 좋다"가 아니라 "조회수 상위"라고 적는다.

### 반드시 있어야 하는 테스트

(합성 `Creative`로 한다. 기대값은 작은 입력의 손계산 값이고 구현과 같은 공식으로 만들지 않는다.)
- 한 채널 8건 조회수가 서로 다른 합성 입력에서 백분위와 구분이 손계산 값과 같다(경계 `0.25`·`0.75` 포함 여부 포함).
- 동률은 평균 순위로 같은 백분위를 갖는다.
- 출처가 다르면 같은 계정 이름이어도 별개 채널이다(YouTube와 Instagram 소재가 섞인 입력에서 각자 자기 채널 안에서만 계산됨).
- 게시 13일 된 소재는 `TOO_RECENT`, 14일 된 소재는 계산된다(`as_of` 고정), `published_at`·`view_count`가 없으면 각 이유 코드, `account`가 없으면 `NO_CHANNEL`.
- 대상이 `min_channel_size` 미만인 채널은 `CHANNEL_TOO_SMALL`이다.
- 입력 순서를 바꿔도 결과가 같고 입력 객체가 바뀌지 않는다. 함수가 현재 시각·네트워크를 읽지 않는다(고정 `as_of`로 재현).

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

- 출처 간 조회수를 하나의 모집단으로 묶어 백분위를 내지 마라. 이유: 출처마다 지표의 뜻이 다르다(ARCHITECTURE 지표 정규화).
- `view_count`가 없는 소재를 0으로 간주하지 마라. 이유: 키 부재는 "없음"이지 0이 아니다(FP-C01). 계산에서 빼고 이유 코드를 돌려준다.
- 함수 안에서 오늘 날짜를 읽지 마라(`as_of`로 받는다). 이유: 재현성과 테스트 가능성.
- DB·네트워크·모델을 쓰거나 결과를 저장하지 마라. 이유: 이 step은 계산 함수만이고 저장·적재는 P4다.
- "성과가 좋다" 같은 표현을 쓰지 마라. 이유: 조회수에는 광고비 효과가 섞여 있다(EVAL).
