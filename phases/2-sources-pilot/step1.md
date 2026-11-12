# Step 1: brand-split

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P2 sources-pilot"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/EVAL.md` — "데이터 분할"(브랜드 단위로 dev·test를 나누고 같은 브랜드가 양쪽에 걸치지 않는다). 읽기만 한다
- `/config/sources.yaml` — 브랜드 목록의 출처(`youtube`·`instagram`·`tiktok` 절의 `brand`). 읽기만 한다
- `/config/product_candidates.yaml` — 브랜드별 카테고리(`candidates[].brand`·`category`, 일부 브랜드만 있다). 읽기만 한다
- `/src/beautyads/sources/config.py` — P1의 설정 로더(YAML 읽기와 `ConfigError` 방식)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/sources/split.py`, `config/brand_split.yaml`, `tests/test_brand_split.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/sources/split.py`, `config/brand_split.yaml`, `tests/test_brand_split.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 라벨 키 파일을 읽는 채점 함수, 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

이 step은 브랜드 단위 dev/test 분할을 **수집 전에, 모델 출력과 무관하게** 정하고 그 결과를 `config/brand_split.yaml`에 기록한다. dev는 분류 정의·프롬프트를 고치는 데이터(시범 20건 등), test는 E1 표본·E4처럼 최종 수치를 내는 데이터다. `sources/`는 `domain`과 `settings`만 import할 수 있다. 이 step은 `docs/EVAL.md`와 `docs/results/`를 만들거나 고치지 않는다(사전 등록 문서는 사람이 이 YAML을 보고 따로 쓴다).

소비자 테스트 점검 결과: `tests/test_architecture.py`는 `src/beautyads` 아래 모든 새 `.py`를 스캔하므로 이 모듈도 계층 가드의 검사 대상이 된다(의도된 관계이며 그 파일은 수정하지 않는다).

### 모듈 `sources/split.py` — 시그니처

```python
CATEGORIES = ("mask_pack", "serum_ampoule", "sun_care")

class BrandSplit(BaseModel):                 # extra="forbid"
    registered_on: str                       # ISO 날짜
    seed: int
    attempt: int                             # 정적 제약을 처음 만족한 시도 번호(0부터)
    dev_size: int
    brands: list[str]                        # 분할 당시의 전체 브랜드(정렬)
    dev: list[str]
    test: list[str]
    static_constraints: list[str]            # 사람이 읽는 제약 설명(아래 목록)
    volume: VolumeConstraints
    resplit: ResplitRule
    history: list[ResplitRecord] = []        # 재분할 이력(이유 필수)

class VolumeConstraints(BaseModel):
    test_analyzable_min_total: int = 300     # 초안 수치. 사용자 확정 전
    test_analyzable_min_per_source: int = 100
    dev_analyzable_min_total: int = 60

class ResplitRule(BaseModel):
    max_times: int = 1
    allowed_until: str = "E1 1단계 라벨링 시작 전"

class SplitError(Exception):                 # 속성: code

def brands_by_source(path: Path) -> dict[str, frozenset[str]]             # 키 "youtube"·"instagram"·"tiktok" → 그 절의 브랜드 집합
def brands_from_sources(path: Path) -> list[str]                          # 세 절의 브랜드 합집합, 정렬, 중복 제거
def load_brand_categories(path: Path) -> dict[str, frozenset[str]]        # product_candidates.yaml: 브랜드 → 카테고리 집합(후보가 없는 브랜드는 키 없음)
def static_violations(dev: Sequence[str], test: Sequence[str], *, brands: Sequence[str],
                      categories: Mapping[str, frozenset[str]], dev_size: int) -> list[str]
def make_split(brands: Sequence[str], *, seed: int, dev_size: int, categories: Mapping[str, frozenset[str]],
               max_attempts: int = 1000) -> tuple[list[str], list[str], int]    # (dev, test, 채택된 attempt)
def load_brand_split(path: Path) -> BrandSplit                            # 검증 실패는 SplitError
def brand_group(split: BrandSplit, brand: str) -> Literal["dev", "test"]  # 없는 브랜드는 SplitError("BRAND_NOT_IN_SPLIT")
def volume_violations(split: BrandSplit, analyzable_by_source_brand: Mapping[tuple[str, str], int]) -> list[str]
class ResplitRecord(BaseModel):              # 이전 분할과 재분할 이유
    resplit_on: str; reason: str; previous_seed: int; previous_attempt: int
    previous_dev: list[str]; previous_test: list[str]

def resplit(split: BrandSplit, *, reason: str, categories: Mapping[str, frozenset[str]],
            resplit_on: str) -> BrandSplit                                # 재분할. 한도 초과는 SplitError("RESPLIT_LIMIT"), 빈 이유는 SplitError("RESPLIT_REASON_REQUIRED")
def main(argv: Sequence[str] | None = None) -> int
    # CLI: python -m beautyads.sources.split --write PATH [--seed 20261112] [--dev-size 5] [--registered-on YYYY-MM-DD]
    #      python -m beautyads.sources.split --resplit --reason "<이유>" --path PATH   (기존 YAML을 읽어 재분할하고 같은 파일에 쓴다)
```

- `make_split`은 **결정적**이다: 브랜드를 정렬한 뒤 시도 `k`(0, 1, 2, …)마다 `random.Random(seed * 1000 + k)`로 섞어 앞의 `dev_size`개를 dev로, 나머지를 test로 만들고 `static_violations`가 비는 **첫 번째 시도**를 채택한다. 어느 시도도 만족하지 못하면 `SplitError("NO_VALID_SPLIT")`.
- **`sources.yaml`의 절마다 구조가 다르다**(실제 파일 확인): `youtube`와 `instagram`은 항목 리스트이고 각 항목의 `brand`를 읽는다. **`tiktok`은 리스트가 아니라 dict**(`countries`, `lookback_days`, `search_type`, `brands`)이며 브랜드는 **`tiktok.brands[].brand`**에 있다. `brands_by_source`가 이 세 구조를 각각 읽는다. 구조가 다르면(절이 없거나 형식이 다르면) `SplitError("SOURCES_CONFIG_INVALID")`.
- 정적 제약(`static_violations`): ① dev와 test가 겹치지 않고 합집합이 `brands` 전체와 같다 ② `len(dev) == dev_size` ③ **dev와 test 각각이 `CATEGORIES` 세 가지를 모두 포함한다**(후보가 있는 브랜드가 그 카테고리를 가진 경우로 센다. 후보 정보가 없는 브랜드는 어떤 카테고리도 채우지 못하는 것으로 본다) ④ dev와 test 각각이 YouTube 계정과 Instagram 계정을 가진 브랜드를 하나 이상 포함한다(`sources.yaml`의 절별 `brand`로 판정한다. 이 판정에 필요한 절별 브랜드 집합을 돌려주는 보조 함수를 둔다).
- **수집량 제약은 분할 시점에 알 수 없다.** 그래서 `volume`은 YAML에 기준만 적어 두고 `volume_violations`가 나중에(P2 수집 뒤) 소재 수를 받아 검사한다. 입력은 `(출처, 브랜드) → analyzable이 true인 소재 수`이고 위반 문장 목록을 돌려준다(`test` 합계 < `test_analyzable_min_total`, `test`의 출처별 합계 < `test_analyzable_min_per_source`, `dev` 합계 < `dev_analyzable_min_total`). 이 수치는 초안이며 사용자가 확정한다.
- **재분할 경로**(수집량 미달 때 라벨링 전에 한해 1회): `resplit`은 `len(history) >= resplit.max_times`이면 `SplitError("RESPLIT_LIMIT")`, 이유가 비어 있으면 `SplitError("RESPLIT_REASON_REQUIRED")`. 통과하면 새 시드를 **이전 `seed + 1`**로 하고 `make_split`과 **같은 규칙**(시도 번호 0부터, 첫 정적 제약 만족)으로 만들되 **결과가 이전 분할(dev 집합)과 같으면 시드를 하나 더 올려 다시 만든다**. 이전 분할과 이유를 `history`에 추가하고 새 `seed`·`attempt`·`dev`·`test`를 기록한다. `--resplit --reason`은 이 함수를 불러 같은 파일에 쓴다(`--reason` 없이는 오류 종료).
- CLI `--write PATH`는 위 `make_split`으로 `BrandSplit`을 만들어 YAML로 쓴다. `--registered-on`을 주지 않으면 오늘 날짜(ISO)를 쓴다. `history`는 빈 목록으로 시작한다. **YAML 파일은 손으로 쓰지 말고 이 CLI를 한 번 실행해서 만든다**(시드 `20261112`, `--dev-size 5`). 재분할 기능은 테스트로만 검증하고 이 step에서 실제 파일에 재분할을 적용하지 않는다(`history`는 빈 채로 둔다).
- `load_brand_split`은 YAML을 읽어 검증한다: 모델 검증, dev·test가 겹치지 않음, `brands`가 dev와 test의 합집합과 같음, 날짜 형식, `len(history) <= resplit.max_times`. 하나라도 어긋나면 `SplitError`(코드로 구분).

### 반드시 있어야 하는 테스트 (`tests/test_brand_split.py`)

- `make_split`이 같은 입력에서 같은 결과를 내고(두 번 호출 비교), 다른 시드에서 (대체로) 다른 결과를 낸다는 점은 단언하지 않는다(우연히 같을 수 있다). 채택된 시도 앞의 모든 시도가 `static_violations`를 어겼음을 단언한다(시도 번호가 최소임).
- `static_violations`: 겹침, 합집합 불일치, `dev_size` 불일치, 한 그룹에 카테고리가 빠짐, 한 그룹에 YouTube(또는 Instagram) 계정 브랜드가 없음을 각각 임시 입력으로 확인한다.
- **저장소의 실제 파일 검사**: `config/brand_split.yaml`을 `load_brand_split`으로 읽을 수 있고, 현재 `config/sources.yaml`의 브랜드 집합(`brands_from_sources`)과 YAML의 `brands`가 같으며(다르면 재등록이 필요하다는 실패), 기록된 `seed`·`attempt`·`dev_size`로 `make_split`을 다시 돌리면 YAML의 `dev`·`test`가 그대로 재현된다. `static_violations`가 비어 있다. 브랜드 수와 분할 크기는 숫자로 고정하지 말고 `sources.yaml`에서 읽은 값·YAML의 `dev_size`와 비교한다.
- `volume_violations`: 기준 미달 합계·출처별 미달·dev 미달을 각각 합성 입력으로 확인하고, 모두 충족하면 빈 목록. 입력이 비어 있으면(검사 대상 0건) 위반이 아니라 **모든 기준 미달 위반**을 돌려준다(빈 집합 통과 방지).
- `brand_group`: 알려진 브랜드의 그룹, 없는 브랜드는 `BRAND_NOT_IN_SPLIT`.
- `history`가 `resplit.max_times`를 넘으면 `load_brand_split`이 실패한다.
- `brands_by_source`: 임시 YAML로 **`tiktok`이 dict인 구조**(`brands: [{brand, search_term}]`)와 `youtube`·`instagram` 리스트 구조를 각각 읽고, 구조가 다르면 `SOURCES_CONFIG_INVALID`. 실제 `config/sources.yaml`로도 세 출처가 모두 1개 이상의 브랜드를 갖는다.
- `resplit`: 첫 재분할은 `history`에 이전 분할·이유가 들어가고 새 `seed == 이전 seed + 1`(또는 같은 결과를 피하려 더 올린 값)이며 새 `dev`가 이전 `dev`와 다르다, 정적 제약을 만족한다, 두 번째 재분할은 `RESPLIT_LIMIT`, 빈 이유는 `RESPLIT_REASON_REQUIRED`, 재분할 결과 파일을 `load_brand_split`이 다시 읽을 수 있다. CLI `--resplit`에 `--reason`이 없으면 오류 종료.

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

- 분할을 모델 출력이나 수집 결과(분석 라벨, 조회수, 게시물 수)로 정하지 마라. 이유: 결과를 본 뒤에 나눈 분할은 dev와 test를 가른 의미가 없고 사전 등록의 신뢰를 깬다(EVAL 데이터 분할, B-FP-043).
- `config/brand_split.yaml`을 손으로 쓰거나 고치지 마라. 최초 생성(`--write`)과 재분할(`--resplit --reason`)은 CLI로만 한다. 이유: 시드와 시도 번호로 재현되지 않는 분할은 검증할 수 없다.
- 브랜드 수·분할 크기·특정 브랜드 이름을 테스트에 숫자나 문자열로 고정하지 마라. `sources.yaml`과 YAML의 값에서 읽어 비교한다. 이유: 브랜드가 추가돼도 테스트가 분할의 일관성만 검사해야 한다(B-FP-061).
- `docs/EVAL.md`, `docs/results/`, `config/sources.yaml`, `config/product_candidates.yaml`을 고치지 마라(읽기만). 이유: 평가 기준은 동결돼 있고 입력 설정을 바꾸면 분할 재현이 깨진다.
- 수집량 기준(`volume`)을 분할 생성 로직에 쓰지 마라. 기준은 기록만 하고 검사는 `volume_violations`가 나중에 한다. 이유: 이 시점에는 소재 수를 알 수 없고, 수를 본 뒤 분할을 조정하면 안 된다(재분할은 `history`에 이유를 적는 1회뿐).
