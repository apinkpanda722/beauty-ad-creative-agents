# Step 4: obs-ledger

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P1 collect-analyze-core"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드(step 0 산출물). 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/COST_ESTIMATE.md` — "확정 계획"과 "보정" 절(공급사별 누적 상한, thought 토큰)
- `/docs/ADR.md` — ADR-015(비용 원장 필드)
- `/docs/CONTRACTS.md` — "Gemini API"의 `usage` 필드와 "LiteLLM SDK" 절의 usage·비용 행
- `/src/beautyads/settings.py`와 `/tests/test_settings.py` — step 1 산출물
- `/scripts/exempt_paths.json` — 비용 원장이 검증 없이 넘어가는 유일한 경로(읽기만)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/obs/__init__.py`, `src/beautyads/obs/ledger.py`, `src/beautyads/settings.py`, `tests/test_ledger.py`, `tests/test_settings.py`

열람 금지 경로: (없음)
수정 허용 경로: `src/beautyads/obs/**`, `src/beautyads/settings.py`(공급사별 상한 설정 추가에 한함), `tests/test_ledger.py`, `tests/test_settings.py`(해당 케이스 추가에 한함, 단언 약화 금지)

이 step은 비용 원장(JSONL)과 공급사별 누적액 상한 검사를 만든다. `obs/`는 `domain`과 `settings`만 import할 수 있다. 원장 파일의 경로는 **항상 호출하는 쪽이 인자로 넘긴다**(기본값은 `Settings.ledger_path`에 있다). 이 모듈의 어떤 함수도 기본 경로를 가지지 않는다.

### settings.py 추가 (추가에 한함)

`Settings`에 `provider_caps_usd: dict[str, float]`를 추가한다. 기본값 `{"gemini": 12.0, "openai": 10.0, "anthropic": 8.0}`. 환경 변수 `BEAUTYADS_CAP_GEMINI_USD`, `BEAUTYADS_CAP_OPENAI_USD`, `BEAUTYADS_CAP_ANTHROPIC_USD`로 바꿀 수 있고, 숫자가 아니거나 음수면 `InvalidSetting`(이름만 메시지에 넣는다). 빈 값은 기본값을 덮지 않는다. `tests/test_settings.py`에 이 케이스를 **추가**한다(기존 단언은 고치지 않는다).

### obs/ledger.py — 시그니처

```python
Provider = Literal["gemini", "openai", "anthropic"]

class LedgerEntry(BaseModel):   # extra="forbid"
    ts: datetime                # 시간대 포함 UTC
    provider: Provider
    model: str                  # 응답이 알려 준 실제 모델 이름
    requested_model: str | None = None
    purpose: str                # 실행 유형(예: "slice", "pilot", "analysis"). 필수
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float
    cost_source: Literal["response_cost", "computed", "missing"]

class LedgerRead(NamedTuple):
    entries: list[LedgerEntry]
    skipped_lines: int

def append_entry(path: Path, entry: LedgerEntry) -> None        # 부모 디렉터리를 만들고 JSON 한 줄을 한 번의 write로 추가. 스레드 안전(락)
def read_entries(path: Path) -> LedgerRead                      # 파일이 없으면 빈 결과. JSON이 아니거나 provider·cost_usd가 없는 줄은 건너뛰고 건수만 센다. 토큰 필드가 없으면 0
def provider_total(path: Path, provider: str) -> float
class CostCapExceeded(Exception):                               # 속성: provider, total_usd, cap_usd, code = f"COST_CAP:{provider}"
def check_cap(path: Path, provider: str, caps: Mapping[str, float], *, additional_usd: float = 0.0) -> None   # total + additional >= cap 이면 CostCapExceeded. caps에 없는 공급사는 ValueError
```

### 반드시 있어야 하는 테스트 (`tests/test_ledger.py`, 모두 `tmp_path`)

- 추가한 줄을 `read_entries`가 같은 값으로 읽는다(왕복). 필드 순서·개수 고정 단언 대신 `model_dump` 값으로 비교한다.
- 파일이 없으면 합계 0. 손상 줄(깨진 JSON, `provider`·`cost_usd` 없는 줄)이 섞여 있어도 예외 없이 나머지를 합산하고 `skipped_lines`로 건수를 알린다. 토큰 필드가 없는 줄은 0으로 읽힌다.
- `check_cap`: 합계가 상한 미만이면 통과, `additional_usd`를 더해 상한 이상이면 예외, 정확히 상한과 같을 때의 동작을 정해 단언한다(위 부등호 기준). 공급사별로 합계가 따로 계산된다. 알 수 없는 공급사는 `ValueError`.
- 동시 추가: 여러 스레드가 각각 여러 줄을 추가한 뒤 **모든 줄이 파싱되고 줄 수가 총합과 같다**(순서는 단언하지 않는다).
- `LedgerEntry`가 알 수 없는 필드와 시간대 없는 `ts`를 거부한다. 함수 시그니처(`inspect.signature`)에 기본 경로 인자가 없다.
- 이 파일의 어떤 테스트도 `Settings().ledger_path`의 기본 경로(`data/manifest/costs.jsonl`)에 쓰지 않는다. 경로는 항상 `tmp_path` 아래에서 만든다.

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

- 테스트에서 `data/manifest/costs.jsonl`(설정 기본 원장 경로)에 쓰지 마라. 경로는 `tmp_path` 아래만 쓴다. 이유: 그 파일은 검증 예외 경로라서 테스트가 쓰면 작업 트리와 실제 비용 기록이 오염된다.
- `LedgerEntry`에 프롬프트·응답 본문·헤더·키 같은 필드를 허용하지 마라(`extra="forbid"`). 이유: 원장은 커밋될 수 있는 파일이고 본문이 새면 안 된다.
- 손상 줄 하나 때문에 합계 계산 전체를 예외로 끝내지 마라. 건너뛰고 건수만 센다. 이유: 한 줄의 결함이 비용 상한 검사를 막으면 안 된다(A-FP-030).
- 동시 쓰기 결과의 순서를 단언하지 마라. 줄 수와 파싱 가능 여부만 단언한다. 이유: 스레드 실행 순서는 보장되지 않는다(B-FP-012).
- 공급사 상한 기본값을 `settings.py` 밖에 쓰지 마라. 이유: 상한이 여러 곳에 흩어지면 하나만 바뀐다(B-FP-030).
