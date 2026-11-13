# Step 2: e1-sampling

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조와 패턴
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P3 `e1-sampling` 행(중복 그룹 키, 상한 1, 2단계 CLI), §8 결정 현황 5번
- `/docs/EVAL.md` — E1 절(표본 50건, 재검사, 판정 기준)과 dev/test 분리 설명
- `/docs/results/e1_preregistration.md` — 사전 등록 파일(구현 세션이 이 step 실행 전에 커밋한다. 읽기 전용. 없으면 `blocked`)
- `/src/beautyads/eval/pilot.py`, `/src/beautyads/eval/sheets.py`, `/src/beautyads/eval/pilot_run.py` — 시범의 선정·시트·CLI 방식(주입 지점, 이유 코드, 종료 코드)과 `OUTPUT_NOT_IGNORED` 규칙
- `/src/beautyads/sources/split.py` — `BrandSplit`, `brand_group`, `load_brand_split`
- `/src/beautyads/domain/creative.py`, `/src/beautyads/domain/labels.py` — `Creative`, `is_analyzable`, `ContentType`, `Category`
- `/src/beautyads/pipeline/preflight.py` — `docker_running`·`tcp_reachable`(import해서 쓴다)
- `/config/brand_split.yaml`, `/config/sources.yaml`, `/README.md`, `/Makefile`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/e1_sampling.py`(새 파일), `src/beautyads/eval/e1_stage2.py`(새 파일), `config/e1_sampling.yaml`(새 파일), `Makefile`, `README.md`, `tests/test_e1_sampling.py`(새 파일), `tests/test_e1_stage2.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/e1_sampling.py`, `src/beautyads/eval/e1_stage2.py`, `config/e1_sampling.yaml`, `Makefile`(`e1-stage1`·`e1-stage2` 타깃과 `.PHONY` 추가에 한함, `verify` 불변), `README.md`(E1 시트 절 추가에 한함), `tests/test_e1_sampling.py`, `tests/test_e1_stage2.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

소비자 테스트 점검 결과: `scripts/test_hooks.py`는 임시 디렉터리에 자기 `Makefile`을 만들어 쓰므로 영향이 없다. `tests/test_compose.py`·`tests/test_slice.py`·`tests/test_collect.py`·`tests/test_pilot.py`는 저장소 `Makefile`을 읽지만 `.PHONY`는 부분집합으로, 기존 타깃의 레시피 원문은 정확히, `verify` 레시피는 `live-`가 없음을 단언한다. 따라서 **새 타깃은 추가하되 기존 타깃의 레시피 원문·`verify` 레시피·그 뒤의 빈 줄 형식은 바꾸지 않는다.** `tests/test_architecture.py`는 새 모듈에 계층 규칙을 적용한다(통과해야 한다). 이 파일들은 수정하지 않는다. 깨지면 고치지 말고 `blocked`로 보고한다.

E1 라벨링용 표본을 만든다. 이 step은 **분석 결과를 쓰지 않는다**(수집과 부분 동결만 필요하다). `eval/`에 두고 `httpx`·`psycopg`·`litellm`을 직접 import하지 않는다(각 계층의 함수를 부른다). **이 step 안에서는 두 CLI를 실행하지 않는다. 테스트는 가짜 의존성과 합성 데이터만 쓴다.**

**사전 등록**: `docs/results/e1_preregistration.md`는 이 step 전에 커밋돼 있다(구현 세션이 작성). 이 step은 그 파일을 만들거나 고치지 않고, 두 CLI는 **그 파일의 sha256과 `config/e1_sampling.yaml`의 sha256을 산출물(시트 메타데이터·키 파일 머리)에 기록**한다. 파일이 없으면 `PREREGISTRATION_MISSING`으로 시작하지 않는다(종료 코드 2). `config/e1_sampling.yaml`에는 등록한 값만 둔다: `seed`, `stage1`(`min_labeled: 100`, `max_labeled: 200`, `target_product: 50`), `stage2`(`size: 50`), `sources`(`youtube`, `instagram`), `dedupe`(출처별 키 목록). 코드에는 이 값들의 기본값을 따로 두지 않는다(파일이 없거나 키가 빠지면 `E1_CONFIG_INVALID`).

### 모듈 `eval/e1_sampling.py` — 1단계

```python
class E1Config(BaseModel): ...            # config/e1_sampling.yaml 모델(extra="forbid")
def load_e1_config(path: Path) -> E1Config   # 문제는 E1_CONFIG_INVALID
def dedupe_key(creative: Creative, config: E1Config) -> tuple | None
    # None이면 그룹을 만들지 않는다(각자 하나로 센다)
def build_frame(creatives, split: BrandSplit, config: E1Config) -> FrameReport
    # items, dropped_duplicates(출처별 건수), frame_size_before, frame_size_after
def order_stage1(frame_items, config: E1Config, seed: int) -> list[Creative]   # 길이 ≤ max_labeled
def build_stage1_sheet(ordered, *, seed: int, provenance: Mapping) -> Stage1Sheet   # rows, key_rows
def main(argv=None, *, environ=None, out=None, docker_check=docker_running, tcp_check=tcp_reachable, deps_factory=None) -> int
```

- **프레임**: `list_creatives(brands=test 브랜드, sources=(youtube, instagram), analyzable_only=True)`. **dev 브랜드·TikTok·`analyzable`이 `None`/`False`인 소재는 들어오지 않는다.** 분석 결과·지표·게시 시각은 선정에 쓰지 않는다.
- **중복 그룹(그룹당 1건, 상한 1)**: 키는 출처별이다 — YouTube `(source, account, title, caption)`, Instagram `(source, account, caption)`(`dedupe`에 등록한 필드 목록으로 읽는다). 같은 키의 소재가 여럿이면 **시드 고정 무작위로 1건만 대표**로 둔다(그룹 안은 `source_id` 정렬 뒤 `random.Random(seed)`로 선택해 재실행해도 같다). **캡션(또는 키에 든 필드 하나라도)이 `None`이거나 공백뿐이면 그룹을 만들지 않고 각자 하나로 센다.** 비교는 문자열 완전 일치다(대소문자·공백 정규화·유사도 비교를 하지 않는다). 이유: 조언 세션 DB 조회에서 YouTube는 같은 캡션 81그룹 중 56그룹이 제목이 달라 캡션만으로 묶으면 서로 다른 영상이 사라진다.
- **1단계 순서**: 프레임을 `(source, brand)` 층으로 나눠 시드 셔플한 뒤 층마다 하나씩 번갈아 뽑는 방식으로(시범 `select_pilot`과 같은 방식, 시범 코드를 고치지 말고 같은 규칙을 새로 구현) 최대 `max_labeled`건의 **순서 있는 목록**을 만든다. 칸이 얇아 `max_labeled`를 못 채우면 `shortfall`(출처·브랜드별 부족분)을 요약에 출력하고 계속한다.
- **시트(`e1_stage1_sheet.csv`)**: 열은 `item_id`(`E001`부터 순서대로, 시트 순서가 곧 라벨링 순서), `link`, `text`(제목·캡션), `content_type`, `category`. `link`는 YouTube 영상 주소와 Instagram `permalink`(`Creative.url`)만이고 **`media_url`·브랜드·계정·지표·게시 시각은 시트에 없다**. 코드북(`e1_stage1_codebook.csv`)은 `docs/TAXONOMY.md`에서 `content_type`·`category` 정의를 읽어 만든다(`eval.sheets.parse_taxonomy` 재사용, 정의를 코드에 복사하지 않는다). 안내문(`e1_stage1_instructions.md`)에 "위에서부터 순서대로 라벨링하고, 사람이 제품 소재로 판정한 건이 `target_product`건 이상이면서 라벨링한 건이 `min_labeled`건 이상이 되면 멈춘다. `max_labeled`를 넘기지 않는다. 건너뛰지 않는다"를 쓴다.
- **키 파일(`e1_stage1_key.json`)**: JSON 최상위에 `items`(항목 번호 → `{source, source_id, brand, account, url}`)와 머리 필드(`seed`, `split_sha256`, 사전 등록 파일·설정 파일 sha256, 중복 제거 전후 프레임 크기와 출처별 제외 건수, `generated_at`). 시트와 키는 다른 파일이고 키는 라벨링 뒤에 연다는 안내를 출력한다.
- **출력 위치**: 기본 `data/interim/e1`, `--out-dir`은 `data/interim` 아래만 허용(`OUTPUT_NOT_IGNORED`, 경로 이탈·심볼릭 링크 이탈 포함). 시범 CLI의 같은 규칙을 따른다.
- **CLI**(`make e1-stage1` → `uv run python -m beautyads.eval.e1_sampling`): 점검 순서는 `PREREGISTRATION_MISSING`, `E1_CONFIG_INVALID`, `PILOT_SPLIT_FILE_INVALID`와 같은 뜻의 분할 파일 문제(`E1_SPLIT_FILE_INVALID`), `ENV_MISSING:POSTGRES_PASSWORD`, `DOCKER_DOWN`, `POSTGRES_UNREACHABLE`이고 **하나라도 있으면 `PREFLIGHT_FAILED <코드>`를 출력하고 종료 코드 2, 그 전에는 접속하지 않는다**. 프레임이 비면 `E1_FRAME_EMPTY`. 요약에 출처·브랜드별 프레임 건수, 중복 제거 전후와 제외 건수, `shortfall`, 쓴 파일 경로를 출력한다. 이미 산출물이 있으면 덮어쓰지 않고 `E1_OUTPUT_EXISTS`로 종료한다(라벨링이 시작된 시트가 바뀌는 것을 막는다. 새로 만들려면 사용자가 파일을 직접 치운다).

### 모듈 `eval/e1_stage2.py` — 2단계

```python
def read_stage1_labels(path: Path, key: Path, config: E1Config) -> Stage1Labels   # LABEL_FILE_MISSING / LABEL_FILE_INVALID
def stop_point(labels, config: E1Config) -> StopPoint        # 멈춘 위치와 사람이 제품으로 판정한 건수
def select_stage2(labels_in_scope, config: E1Config, seed: int) -> Stage2Selection   # items, shortfall
def main(argv=None, *, out=None) -> int
```

- **입력**: 사용자가 라벨링한 `e1_stage1_sheet_labeled.csv`(기본 경로 `data/interim/e1`, `--labels`로 변경)와 키 파일. 라벨 파일이 없으면 `LABEL_FILE_MISSING`, 열 이름이 시트와 다르거나 `content_type`·`category` 값이 코드북 밖이거나 `item_id`가 시트에 없거나 건너뛴 행(위에서부터 연속이 아님)이 있으면 `LABEL_FILE_INVALID`이고 **둘 다 어떤 파일도 쓰지 않고 종료 코드 2**다. 이 CLI는 데이터베이스에 접속하지 않는다.
- **멈춘 위치**: 위에서부터 읽어 **라벨링한 건수 ≥ `min_labeled`이면서 사람이 `product_creative`로 판정한 건수 ≥ `target_product`가 되는 첫 행**이 멈춘 위치다. 그 뒤에 라벨이 더 있어도 **사용하지 않고** 사용하지 않은 건수를 보고한다(멈춘 뒤의 라벨이 표본을 편향시키지 않게). 끝(`max_labeled` 또는 라벨링한 마지막 행)까지 `target_product`에 못 미치면 `E1_PRODUCT_SHORTFALL <부족 건수>`를 출력하고 지금까지의 `product_creative`로 계속한다(종료 코드는 0).
- **2단계 추출**: 범위 안에서 사람이 `product_creative`로 판정한 소재 중 **사람 라벨의 (출처, `category`) 층**마다 번갈아 뽑아 `stage2.size`건을 시드 고정으로 정한다. 층이 모자라면 `shortfall`을 출력한다. 모델 분석 결과를 쓰지 않는다.
- **2단계 시트(`e1_stage2_sheet.csv`)**: `item_id`(`F001`부터, 시드 셔플 순서), `link`, `text`, 그리고 **`content_type`·`category`를 뺀 나머지 모든 축 열**(`eval.sheets.label_columns()`에서 두 열을 제외 — 시범 시트와 같은 열 구성, `ingredients` 제외). 사람의 1단계 라벨은 시트에 넣지 않는다(키 파일에만). 코드북·안내(`e1_stage2_codebook.csv`, `e1_stage2_instructions.md`)는 `docs/TAXONOMY.md`에서 읽어 만들고 "`claims`는 쉼표 구분 여럿 선택"과 "7일 뒤 같은 시트를 다시 라벨링한다"를 쓴다. 키 파일(`e1_stage2_key.json`)에는 JSON 최상위 `items`(항목 번호 → `{source, source_id, brand, account, url, stage1_human_labels}`)와 머리 필드(시드, 사전 등록·설정 파일 sha256, 1단계 키 파일 sha256, 멈춘 위치, 사용하지 않은 건수, `shortfall`)를 쓴다. 이미 있으면 `E1_OUTPUT_EXISTS`.
- **CLI**(`make e1-stage2` → `uv run python -m beautyads.eval.e1_stage2`): 사용자가 직접 실행한다. README에 키 파일·라벨 파일 경로, 7일 재라벨링 방법, 이유 코드 표를 쓴다.

### 반드시 있어야 하는 테스트

**`tests/test_e1_sampling.py`** (합성 `Creative`, 가짜 저장소, 모두 tmp 경로):
- 프레임: test 브랜드만, YouTube·Instagram만, `analyzable is True`만 들어온다(dev 브랜드·TikTok·`analyzable` `None`/`False` 소재를 섞어 넣고 모두 빠짐을 확인).
- **중복 그룹**: YouTube에서 `(account, caption)`이 같아도 `title`이 다르면 **둘 다 남는다**, `(account, title, caption)`이 모두 같으면 1건만 남는다, 계정이 다르면 별개다. Instagram에서 `(account, caption)`이 같으면 1건만 남는다. 캡션이 `None`·빈 문자열·공백뿐이면 같은 값이라도 그룹을 만들지 않고 모두 남는다. 대표 선택은 시드가 같으면 같고 `source_id` 목록 순서가 달라도 같다. 제외 건수가 출처별로 정확히 센다(기대값은 작은 합성 입력의 손계산 값).
- 1단계 순서: 같은 시드면 같은 순서, 시드가 다르면 순서가 달라질 수 있음, 길이가 `max_labeled` 이하, 층이 모자라면 `shortfall`.
- 시트·키: 시트에 `media_url`·브랜드·계정·지표·게시 시각 감시 문자열이 없다, `link`는 `Creative.url`뿐, 키 파일에 머리 필드(사전 등록·설정 sha256)가 있다, 이미 산출물이 있으면 `E1_OUTPUT_EXISTS`이고 파일이 바뀌지 않는다.
- CLI: 사전 등록 파일이 없으면 `PREREGISTRATION_MISSING`(종료 코드 2)이고 `deps_factory`가 **한 번도** 불리지 않는다, 설정 파일 문제는 `E1_CONFIG_INVALID`, `DOCKER_DOWN`·`POSTGRES_UNREACHABLE`·`ENV_MISSING:POSTGRES_PASSWORD`, `--out-dir`이 `data/interim` 밖이면 오류 종료, 출력에 DSN·비밀번호가 없다.
- `Makefile`: `verify` 레시피에 `e1-`가 없고 두 타깃과 `.PHONY` 항목이 있다.

**`tests/test_e1_stage2.py`** (합성 시트·키·라벨 CSV, tmp 경로):
- 라벨 파일이 없으면 `LABEL_FILE_MISSING`, 열 이름 불일치·값이 코드북 밖·알 수 없는 `item_id`·건너뛴 행이면 `LABEL_FILE_INVALID`이고 **어떤 파일도 만들지 않는다**.
- 멈춘 위치: 합성 라벨에서 두 조건(`min_labeled`건 이상, 제품 `target_product`건 이상)을 처음 만족하는 행에서 멈추고 그 뒤 라벨은 쓰지 않으며 사용하지 않은 건수를 보고한다(손계산 값). 제품이 모자라면 `E1_PRODUCT_SHORTFALL`이고 종료 코드 0.
- 2단계 추출: 사람 라벨의 (출처, `category`) 층으로 번갈아 뽑는다, 같은 시드면 같다, 모델 라벨이 입력에 없어도 동작한다(모델 결과를 읽지 않음), 층이 모자라면 `shortfall`.
- 시트에 `content_type`·`category` 열과 사람의 1단계 라벨이 없고 나머지 축 열이 `label_columns()`와 일치한다(열 이름 집합 비교), 키 파일에 1단계 라벨이 있다.
- 이 CLI가 데이터베이스 접속 함수를 부르지 않는다(가짜 의존성이 있다면 호출 0회).

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

- 두 CLI(`make e1-stage1`, `make e1-stage2`)를 실행하지 마라. 이유: DB 접속과 사용자의 라벨 파일이 필요한 사용자 실행이다. 테스트는 가짜 의존성만 쓴다.
- E1 표본 선정에 모델 분석 결과·조회수 등 지표·게시 시각을 쓰지 마라. 이유: 모델 출력과 무관한 층화여야 모델이 `other`로 보낸 소재가 빠져 재현율이 부풀려지는 것을 막는다(PHASES 변경 기록 #10).
- 중복 제거를 **분석 대상 선정이나 DB 행 삭제**에 쓰지 마라. E1 표본 추출에만 적용한다. 이유: 그래프·에이전트 데이터는 모든 소재를 쓴다.
- YouTube 중복 키에서 제목을 빼지 마라(캡션만으로 묶지 마라). 이유: 같은 캡션 81그룹 중 56그룹이 제목이 달라 서로 다른 영상이 표본에서 사라진다.
- 캡션을 정규화(공백 제거·소문자·유사도)해서 비교하지 마라. 이유: 기준을 사전 등록에 적은 "완전 일치"에서 벗어난다. 변형 게시물을 더 잡는 것은 이 step의 범위가 아니다.
- 시트에 `media_url`·브랜드·계정·지표·모델 라벨을 넣지 마라, 라벨링 뒤 멈춘 위치 이후의 라벨을 사용하지 마라. 이유: 블라인드가 깨지거나 표본이 편향된다.
- `docs/results/`의 사전 등록 파일을 만들거나 고치지 마라(읽는 것은 허용된다). `data/interim/`의 파일은 만들거나 고치거나 읽지 마라. 이유: 사전 등록은 구현 세션이 커밋하고(읽기 전용) `data/interim`은 열람 금지다.
- 기존 시범 코드(`pilot.py`, `sheets.py`, `pilot_run.py`)를 수정하지 마라(읽고 재사용만). 이유: 사용자가 이미 시범 라벨링을 끝냈고 파일 형식이 바뀌면 `pilot-compare`가 깨진다.
- 이미 있는 산출물을 덮어쓰지 마라(`E1_OUTPUT_EXISTS`). 이유: 라벨링이 시작된 시트가 바뀌면 사람의 라벨이 헛수고가 된다.
