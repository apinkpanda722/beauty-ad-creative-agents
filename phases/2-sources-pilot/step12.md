# Step 12: pilot-sheet

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/docs/PHASES.md` — "P2 sources-pilot"에서 이 step의 설명
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/EVAL.md` — "E1 소재 분석 정확도"(사람이 모델 결과를 보기 전에 먼저 라벨링)와 "데이터 분할". 읽기만 한다
- `/docs/TAXONOMY.md` — "축과 값"(라벨링 시트의 열과 값 코드북)과 "라벨링 검증 절차"
- `/config/brand_split.yaml`, `/src/beautyads/sources/split.py` — 분할(`BrandSplit`, `brand_group`) 이전 step 산출물
- `/src/beautyads/domain/` 전체(`creative.py`, `labels.py`, `jobs.py`, `protocols.py`) — 분류 enum과 `JobResult`
- `/src/beautyads/pipeline/media_flow.py` — 축 종류 이름 규칙(`content_type@태그` 등)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/__init__.py`, `src/beautyads/eval/pilot.py`, `src/beautyads/eval/sheets.py`, `tests/test_pilot_sheet.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/__init__.py`, `src/beautyads/eval/pilot.py`, `src/beautyads/eval/sheets.py`, `tests/test_pilot_sheet.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 라벨 키 파일을 읽는 채점 함수, 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

시범 20건의 **선정**과 **블라인드 라벨링 시트 생성**을 만든다. 사람이 모델 라벨·지표를 보지 않은 채 먼저 라벨링하도록, 시트에는 영상 링크와 제목·캡션만 두고 모델 라벨과 지표, 브랜드, 출처는 **별도 키 파일**로 분리한다. `eval/`은 모든 계층을 import할 수 있다(다른 계층은 `eval`을 import하지 못한다). **이 step은 시트 생성기만 만든다. 채점기는 P3에서 별도로 만든다.** 파일 출력은 `data/interim/` 아래로만 한다. 테스트는 `tmp_path`와 합성 데이터만 쓴다.

소비자 테스트 점검 결과: 새 모듈만 만든다. `tests/test_architecture.py`가 `eval/`을 계층 가드로 검사한다(의도된 관계, 수정하지 않는다).

### 선정 (`eval/pilot.py`)

```python
class PilotSelection(NamedTuple):
    items: list[Creative]
    shortfall: int                    # 요청한 n보다 모자란 수

def select_pilot(creatives: Sequence[Creative], split: BrandSplit, *, n: int = 20, seed: int,
                 sources: Collection[Source] = (Source.youtube, Source.instagram)) -> PilotSelection
```

- 대상: **`brand_group(split, 브랜드) == "dev"`이고** `is_analyzable`이며 `source`가 `sources` 안이고 `brand`가 있는 소재만. 브랜드가 없는 소재(`brand is None`)와 분할 파일에 없는 브랜드는 제외하고 **예외로 끝내지 않는다**(제외 수를 `shortfall` 계산과 별도로 돌려주지 않아도 된다).
- 선정은 **결정적이고 모델 출력과 무관**하다: `(source, brand)` 그룹을 정렬하고, 그룹 안은 `(source_id)` 정렬 뒤 `random.Random(seed)`로 섞은 다음, 그룹을 돌아가며(round-robin) 한 건씩 뽑아 `n`건이 될 때까지 모은다(출처가 고르게 섞이고 한 브랜드에 쏠리지 않는다). 모자라면 있는 만큼만 돌려주고 `shortfall = n - len(items)`.
- `n < 1`이면 `ValueError`. 후보가 0건이면 `PilotSelection([], n)`을 돌려주고 호출자가 판단한다.

### 시트 (`eval/sheets.py`)

```python
class BlindSheet(NamedTuple):
    rows: list[dict[str, str]]        # 사람이 보는 시트
    key_rows: list[dict[str, Any]]    # 키 파일 내용(item_id → 소재·모델 라벨)

class SheetError(Exception):          # 속성: code ("EMPTY_SELECTION" | "OUTPUT_NOT_IGNORED" | ...)

def label_columns() -> list[str]      # 시범 시트의 라벨 열 이름(분류 enum·결과 모델에서 만든다)
def codebook_rows() -> list[dict[str, str]]   # axis, value, note 한 줄씩(값은 enum 멤버에서 만든다. note는 아래 규칙)
def instructions_text() -> str                # 라벨링 안내문(아래 규칙)
def build_blind_sheet(items: Sequence[Creative], *, seed: int,
                      job_results: Mapping[tuple[str, CreativeKey], JobResult],     # (축 종류 "hook@minimal" 등, 키) → 결과
                      run_tags: Sequence[str], split_sha256: str, selection_seed: int) -> BlindSheet
def write_sheet_files(out_dir: Path, sheet: BlindSheet, codebook: Sequence[dict[str, str]], instructions: str) -> dict[str, Path]
    # out_dir/pilot_sheet.csv, pilot_codebook.csv, pilot_instructions.md, pilot_key.json. out_dir가 `data/interim` 아래가 아니면 SheetError("OUTPUT_NOT_IGNORED")
def sha256_of(path: Path) -> str
```

- **블라인드 규칙**: 시트의 열은 `item_id`, `link`(= `creative.url`: YouTube 영상 주소 또는 Instagram `permalink`. `media_url`은 쓰지 않는다), `text`(제목·캡션, 없으면 빈 문자열), 그리고 **빈 라벨 열들**(`label_columns()`)이다. **모델 라벨, 지표(조회수·좋아요·댓글), 브랜드, 계정, 출처(`source`), 게시 시각은 시트에 넣지 않는다.** 항목 순서는 `seed`로 섞고 `item_id`(`P001`, `P002`, …)는 섞은 **뒤의** 순서로 붙인다(원래 순서·출처·브랜드와 상관이 없다).
- 라벨 열은 **TAXONOMY v0**의 축에서 만든다: `content_type`, `category`, `hook_type`, `angle`, `format`, `talent`, 구조 불리언 4개, 플랫폼 적합성 불리언 5개, `cta_type`, `claims`(여럿 선택). **`ingredients`는 E1 판정 축에서 제외 확정이라 시트에 넣지 않는다.** 값 목록은 `domain`의 enum에서 만든다(복사하지 않는다).
- **라벨링 규칙(코드북 `note`와 `instructions_text()`에 반드시 담는다)**:
  1. **`content_type`이 `product_creative`가 아니면 나머지 열(카테고리 제외 분류 열)은 비워 둔다**(제품 소재가 아닌 영상에 라벨을 억지로 채우지 않는다. 시험 호출에서 팝업 홍보 영상이 제품 소재처럼 분류됐던 사례가 사람 라벨에서 재발하는 것을 막는다). `category`는 `product_creative`가 아니면 `other`로 둔다.
  2. **`claims`는 여럿 선택이며 쉼표로 구분한다**(예: `hydration,soothing`). 나머지 축은 하나만 고른다. 불리언 열은 `true`/`false`로 적는다.
  3. 영상과 제목·캡션에서 **관찰되는 것만** 적는다(자막·음성에 명시된 효능만, 분위기에서 추정하지 않는다). 확신이 없으면 `other`.
  4. **키 파일(`pilot_key.json`)은 라벨링을 마치기 전에 열지 않는다.**
  5. 성분(`ingredients`)은 이 시범 시트의 라벨링 대상이 아니다.
- **키 파일**(`pilot_key.json`): `item_id` → `source`, `source_id`, `brand`, `account`, `url`, `published_at`, 지표 값, 각 실행 태그(`run_tags`)별로 `content_type`·`hook`·`full` 결과(`status`, `labels`, `error_code`, `model`, `thinking_level`, `prompt_version`)와 **모델 원문 출력은 넣지 않는다**(길고 시트와 무관), 파일 최상단에 `split_sha256`·`selection_seed`·`sheet_seed`·생성 시각. 결과가 없는 항목·실행 태그는 `null`.
- 비어 있는 선정이면 `SheetError("EMPTY_SELECTION")`.

### 반드시 있어야 하는 테스트 (`tests/test_pilot_sheet.py`)

- **선정**: 같은 입력·시드에서 같은 결과(두 번 호출 비교), **dev 브랜드가 아닌 소재·`analyzable`이 아닌 소재·`brand is None`인 소재·분할에 없는 브랜드·허용 출처 밖은 절대 뽑히지 않는다**, 출처가 고르게 섞인다(두 출처가 충분하면 둘 다 포함), 한 브랜드가 `n`을 독점하지 않는다(그룹이 여럿일 때), 모자라면 `shortfall`이 맞고 예외가 없다, `n < 1`은 `ValueError`, 모델 출력(분석 라벨)을 입력으로 받지 않는다(함수 시그니처 확인).
- **블라인드 시트**: 시트 열 집합이 `{item_id, link, text} ∪ label_columns()`이고 **금지 열(`source`, `brand`, `account`, 지표 이름, 모델 라벨 열)이 없다**. 합성 소재의 브랜드 이름·계정·지표 값·모델 라벨 값에 감시용 문자열을 넣고 **시트 CSV 텍스트 전체에 그 문자열이 없음**을 확인한다(키 파일에는 있다). `link`가 `Creative.url`이고 `media_url` 문자열이 없다. `item_id`는 `P001`부터 연속이고 유일하다. 같은 시드에서 항목 순서가 같고 시드가 다르면 다른 순서가 될 수 있다(단 단언은 같은 시드의 재현성만). 시트 행 집합이 입력 소재 집합과 일대일이다(키 파일의 `item_id`로 모든 소재가 정확히 한 번 복원된다).
- **라벨링 규칙**: `instructions_text()`와 코드북 `note`(또는 코드북 안내 행)에 위 1·2·4의 핵심 구절(`product_creative`가 아니면 나머지 열을 비워 둔다, `claims`는 쉼표로 구분하는 여럿 선택, 키 파일은 라벨링 뒤에 연다)이 들어 있다(문장 전체가 아니라 핵심 구절 포함 여부로 확인한다). `claims` 열의 코드북 `note`에 여럿 선택·쉼표 구분이 적혀 있다. `write_sheet_files`가 `pilot_instructions.md`도 쓴다.
- **라벨 열·코드북**: `label_columns()`에 `ingredients`가 없고, 코드북 `(axis, value)` 집합이 `domain` enum 멤버에서 만든 집합과 같다(멤버를 순회해 비교한다).
- **키 파일**: 실행 태그별 결과가 들어가고 결과가 없는 항목은 `null`, 모델 **원문 출력**(`raw_output`)이 어디에도 없다, 최상단에 `split_sha256`가 있다. `sha256_of`가 파일 내용 해시를 돌려준다.
- **출력 경로 가드**: `data/interim` 아래가 아닌 `out_dir`(예: `tmp_path/tracked`)는 `OUTPUT_NOT_IGNORED`이고 파일이 만들어지지 않는다. `data/interim` 아래면 네 파일(시트·코드북·안내문·키)이 만들어진다(`tmp_path/data/interim/pilot`). 빈 선정은 `EMPTY_SELECTION`.

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

- 시트에 모델 라벨·지표·브랜드·계정·출처·게시 시각을 넣지 마라. 이유: 사람이 모델 결과를 보기 전에 먼저 라벨링해야 하고(EVAL E1), 지표·브랜드를 보면 라벨이 편향된다.
- 항목 순서를 입력 순서나 출처 순서로 두지 마라. 시드로 섞은 뒤에 `item_id`를 붙인다. 이유: 순서가 출처·브랜드·모델 결과와 상관이 있으면 블라인드가 깨진다.
- 선정에 모델 출력, 조회수, 게시물 수를 쓰지 마라. 이유: 결과를 본 뒤의 선정은 사전 등록의 신뢰를 깬다(B-FP-043). 시범은 dev 브랜드에서만 뽑는다.
- 시트·키·코드북을 `data/interim/` 밖에 쓰지 마라(`OUTPUT_NOT_IGNORED`). 이유: 키 파일이 커밋되면 블라인드가 깨지고 라벨이 공개 저장소에 남는다.
- 채점기(일치율 계산)를 이 step에 만들지 마라. 생성기와 채점기는 다른 step이다. 이유: 같은 코드가 모델 라벨을 보고 시트를 만들고 채점까지 하면 블라인드 경계가 흐려진다.
