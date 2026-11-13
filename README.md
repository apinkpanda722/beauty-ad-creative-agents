# beauty-ad-creative-agents

뷰티 광고 크리에이티브를 분석해 근거가 달린 기획안을 만드는 멀티에이전트 프로젝트.

- 하네스 사용법: [scripts/README.md](scripts/README.md)
- 요구사항·설계·결정 기록: [docs/](docs/)

## live-slice (P1)

YouTube 소재 수집 → 첫 3초 훅 분석 → PostgreSQL 저장을 확인한다.
OrbStack을 켜고 `.env`에 `YOUTUBE_API_KEY`, `GEMINI_API_KEY`,
`POSTGRES_PASSWORD`를 설정한다. `make db-up`은 Neo4j도 올리므로
`NEO4J_PASSWORD`(8자 이상)도 필요하다. 이 CLI는 Neo4j를 사용하지 않는다.

```bash
make db-up
# 컨테이너 준비까지 수 초 기다린 뒤 실행한다.
make live-slice
```

기본 수집 상한은 1건이다. 아래 모듈 명령에 `--count`로 1~5건을 지정할 수 있다.
환경 점검만 하려면 다음을 실행한다(모델 호출·DB 접속 없음).

```bash
uv run python -m beautyads.pipeline.slice --preflight-only
```

정상 출력은 소재별 JSON 한 줄과 마지막 요약 한 줄이다. 아래는 값 없이 필드
이름만 표시한 출력 형식이다.

```text
event, source, source_id, url, status, hook_type, error_code
event, collected, analyzed, stopped, gemini_total_usd
```

`analyzed`는 분석 상태별 건수이며, 중단 시 남은 작업은 `pending`으로 보존한다.
분석 1건 비용은 약 $0.006 추정이며 실제 비용은 `data/manifest/costs.jsonl`에
기록한다. 기본 Gemini 누적 상한은 $12다. 키·DSN·API 요청 쿼리와 영상 파일
경로는 출력하지 않으며 영상 파일은 다운로드하지 않는다.

점검 실패는 `PREFLIGHT_FAILED <코드>`와 종료 코드 2, 한도 등 실행 중단은
`STOPPED <사유>`와 종료 코드 3, 정상 완료·점검 통과는 종료 코드 0이다.

| 이유 코드 | 조치 |
|---|---|
| `ENV_MISSING:YOUTUBE_API_KEY` | `.env`에 해당 이름의 공백이 아닌 값을 설정한다. |
| `ENV_MISSING:GEMINI_API_KEY` | `.env`에 해당 이름의 공백이 아닌 값을 설정한다. |
| `ENV_MISSING:POSTGRES_PASSWORD` | `.env`에 해당 이름의 공백이 아닌 값을 설정한다. |
| `DOCKER_DOWN` | OrbStack을 켜고 Docker 데몬이 준비될 때까지 기다린다. |
| `POSTGRES_UNREACHABLE` | `make db-up` 뒤 잠시 기다렸다가 다시 시도한다. 기본 포트는 5433이며 `BEAUTYADS_POSTGRES_PORT`를 쓰면 실제 노출 포트와 맞춘다. |
| `COST_CAP:gemini` | 원장 누적액과 비용 상한 설정을 확인한 뒤 예산을 결정한다. |
| `LEDGER_NOT_WRITABLE` | 원장 경로와 부모 디렉터리의 쓰기 권한·여유 공간을 확인한다. |
| `POSTGRES_AUTH_FAILED` | PostgreSQL 비밀번호는 데이터 볼륨을 처음 만들 때만 적용된다. P1은 데이터가 없으니 `.env`의 `POSTGRES_PASSWORD`를 원래 값으로 되돌리거나 볼륨을 직접 삭제한다(삭제 타깃은 만들지 않았다). |
| `POSTGRES_CONNECT_FAILED` | PostgreSQL 비밀번호는 데이터 볼륨을 처음 만들 때만 적용된다. P1은 데이터가 없으니 `.env`의 `POSTGRES_PASSWORD`를 원래 값으로 되돌리거나 볼륨을 직접 삭제한다(삭제 타깃은 만들지 않았다). 컨테이너 상태와 포트도 확인한다. |
| `DAILY_LIMIT` / `RATE_LIMITED` | 한도가 회복된 뒤 다시 실행한다. 대기 작업은 보존된다. |
| `YOUTUBE_KEY_INVALID` / `YOUTUBE_QUOTA` | YouTube 키 설정 또는 할당량을 확인한 뒤 다시 실행한다. |

## live-collect (P2)

YouTube·Instagram의 메타데이터만 수집해 PostgreSQL에 저장한다. 영상 파일을
다운로드하거나 모델을 호출하지 않으므로 모델 비용은 없다. OrbStack을 켜고
`.env`에 `YOUTUBE_API_KEY`, `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID`,
`POSTGRES_PASSWORD`를 설정한다. **`INSTAGRAM_USER_ID`는 호출 주체인 내 Instagram
사용자 ID이며, 사용자가 `.env`에 값을 추가해야 한다.** `make db-up`에는
`NEO4J_PASSWORD`(8자 이상)도 필요하다. 수집기는 Neo4j를 사용하지 않는다.
Instagram 기본 URL은 `https://graph.facebook.com/v21.0`이며 필요할 때만
`BEAUTYADS_INSTAGRAM_BASE_URL`로 바꾼다.

먼저 `--dry-run`으로 호출 수·예상 소요 시간을 확인한다. 이 모드는 키 없이
실행할 수 있으며 HTTP·DB 접속과 Docker 점검을 하지 않는다.

```bash
uv run python -m beautyads.pipeline.collect --dry-run
make db-up
# 컨테이너가 준비된 뒤 사용자가 실행한다(권장: 11-15~16).
make live-collect
```

기본값은 두 출처 모두, 계정당 최대 150건이다. `--max-per-account` 범위는
1~1000이며 YouTube는 영상 수, Instagram은 게시물 수다. 호출 수 추정은
YouTube 채널당 `1 + 2 × ceil(N / 50)`, Instagram 계정당 `ceil(N / 100)`이다.
호출당 시간은 가정(미실측)이며 YouTube 쿼터 사용량은 미확인(Cloud 콘솔에서
확인)이다. Instagram은 호출당 앱 사용량 0.5%를 적용하지만 첫 live에서 과소추정으로 드러났다(13계정·약 26호출에 80% 도달, 어느 지표가 올랐는지는 미확인).
예를 들어 22계정 × 2쪽은 44호출이고 0.5% 가정으로는 약 22%지만 실제로는 그보다 훨씬 빨리 찼다.
사용량 창은 롤링이라 멈춘 뒤 약 1시간 기다렸다가 `--skip-recent-hours`로 이어 받는다.
오류·중단으로 끝난 계정은 저장하지 않으므로 이어 받을 때 다시 수집된다. 수집기는 수집기는 사용량 80% 이상이면 Instagram을 멈춘다.

```bash
uv run python -m beautyads.pipeline.collect --sources youtube --max-per-account 100
# 최근 24시간 안에 수집된 계정을 건너뛴다(기본 0은 끄기).
uv run python -m beautyads.pipeline.collect --skip-recent-hours 24
# 실패한 YouTube handle 또는 Instagram username만 다시 수집한다.
uv run python -m beautyads.pipeline.collect --accounts @torriden,torriden_official
```

계정 하나가 끝날 때마다 업서트하므로 중간에 끊겨도 앞 계정의 결과는 남고,
다시 실행해도 같은 소재가 중복되지 않는다. 계정별 오류는 다음 계정으로
넘어가고, 인증·한도 중단은 해당 출처만 멈춘다. 일시적인 읽기 요청 실패와
HTTP 500·502·503·504는 최대 3회 시도하며 400대는 재시도하지 않는다.

진행 중에는 계정별 JSON 한 줄(`event=account`)에 `source`, `brand`, `account`,
`fetched`, `analyzable_true`, `analyzable_false`, `analyzable_null`, `error`,
`skipped`를 출력한다. 마지막 `event=summary`의 `by_source_brand`는 저장소 전체의
출처·브랜드별 분석 가능 분포이며, `split_analyzable_true`는
`config/brand_split.yaml`에 따른 dev·test 합계다. 분할에 없는 브랜드와 브랜드가
없는 소재는 `unassigned`에 따로 센다. `stopped`는 출처별 중단 이유,
`elapsed_s`는 총 소요 초다. 키·토큰·요청 URL 쿼리·임시 영상 주소는 출력하지 않는다.

| 이유 코드 | 의미와 조치 |
|---|---|
| `ENV_MISSING:YOUTUBE_API_KEY` | YouTube를 선택했다면 해당 키를 설정한다. |
| `ENV_MISSING:INSTAGRAM_ACCESS_TOKEN` / `ENV_MISSING:INSTAGRAM_USER_ID` | Instagram을 선택했다면 토큰과 호출 주체 ID를 설정한다. |
| `ENV_MISSING:POSTGRES_PASSWORD` | PostgreSQL 비밀번호를 설정한다. |
| `DOCKER_DOWN` / `POSTGRES_UNREACHABLE` | OrbStack과 `make db-up`, 노출 포트(기본 5433)를 확인한다. |
| `POSTGRES_AUTH_FAILED` / `POSTGRES_CONNECT_FAILED` | 비밀번호·컨테이너·포트를 확인한다. 비밀번호는 볼륨 최초 생성 시 적용되므로 기존 볼륨이면 원래 값을 확인한다. |
| `YOUTUBE_KEY_INVALID` / `YOUTUBE_QUOTA` | YouTube만 중단한다. 키나 Cloud 콘솔 할당량을 확인한 뒤 재개한다. |
| `INSTAGRAM_TOKEN_INVALID` | Instagram만 중단한다. 토큰을 갱신한 뒤 재개한다. |
| `INSTAGRAM_USAGE_HIGH` / `INSTAGRAM_RATE_LIMITED` | Instagram만 중단한다. 사용량 창이 회복된 뒤 재개한다. |
| `CHANNEL_NOT_FOUND` / `CHANNEL_MISMATCH` / `INSTAGRAM_ACCOUNT_NOT_FOUND` | 해당 계정 설정을 확인한다. 다른 계정은 계속 수집한다. |
| `YOUTUBE_HTTP_*` / `YOUTUBE_REQUEST_FAILED` / `INSTAGRAM_ERROR_*` / `INSTAGRAM_REQUEST_FAILED` / `*_INVALID_RESPONSE` | 해당 계정의 요청·응답 오류다. 나머지 계정 수집 후 재실행한다. |
| `COLLECTION_ACCOUNT_FAILED` | 해당 계정의 수집 또는 저장이 실패했다. 저장소 상태와 계정 설정을 확인해 재실행한다. |
| `SPLIT_VOLUME_INSUFFICIENT` | 전체 저장소 기준 `volume_violations`를 확인한다. 자동 재분할은 하지 않는다. |

점검 실패는 `PREFLIGHT_FAILED <코드>`와 종료 코드 2, 출처 중단이 있으면
종료 코드 3, 그 밖에는 0이다. 수집량 미달만 있으면 종료 코드는 0이다.

**live 순서: `make live-collect` → 수집량 확인(`SPLIT_VOLUME_INSUFFICIENT` 유무)
→ 필요하면 라벨링 전에 1회 재분할 → 그 뒤에 `make live-pilot`.**
수집량이 모자라면 추가 수집을 검토하고, 라벨링 시작 전에 한해 이유를 적어
다음 명령으로 1회 재분할할 수 있다.

```bash
uv run python -m beautyads.sources.split --resplit --reason "수집량 확인 후 재분할 사유" --path config/brand_split.yaml
```

분할이 바뀌면 시범 20건도 바뀌므로 `make live-pilot`은 분할 확정 뒤에 실행한다
(P2 step 13에서 제공).

## live-pilot (P2)

**live 순서: `make live-collect` → 수집량 확인 → 필요 시 라벨링 전에 1회
재분할 → 그 뒤에 `make live-pilot`.** 수집을 완료하고
`config/brand_split.yaml`의 dev·test 수집량 기준을 충족해야 한다.
시범 실행기는 저장소의 `collection_stats()`로 이를 다시 검사하며 우회 옵션은 없다.
분할이 바뀌면 시범 20건도 바뀌므로 분할을 확정한 뒤 시작한다.

OrbStack을 켜고 `.env`에 `GEMINI_API_KEY`, `POSTGRES_PASSWORD`,
`INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID`를 설정한다. 시작 점검에서는
대상 출처를 아직 모르므로 Instagram 두 설정도 확인한다. `make db-up`에는
`NEO4J_PASSWORD`(8자 이상)도 필요하다. 시범은 PostgreSQL만 사용한다.

먼저 `--dry-run`으로 계획 호출 수와 영상 입력 토큰 추정을 확인한다.
이 모드는 키 없이 실행하며 Docker 점검·네트워크 호출·DB 접속·모델 호출을 하지 않는다.
금액은 추정하지 않는다. 비용은 원장에 기록되며 시범 뒤 `cost-recalc`가 계산한다.

```bash
uv run python -m beautyads.eval.pilot_run --dry-run
make db-up
# 컨테이너가 준비되고 수집량·분할을 확인한 뒤 사용자가 실행한다.
make live-pilot
# 개수·선정 seed·구간 상한·출력 폴더를 바꾸는 예
uv run python -m beautyads.eval.pilot_run --n 20 --seed 20261112 --content-type-window-s 60 --full-window-s 60 --out-dir data/interim/pilot
```

기본값은 dev 브랜드의 분석 가능한 YouTube·Instagram 소재 20건,
seed `20261112`, 콘텐츠 유형·전체 분석 구간 각각 최대 60초다. `--n`은
1~40이며 지표나 분석 결과를 선정에 쓰지 않는다. 같은 선정 소재를
`thinking_level=minimal` → `default` 순으로 분석한다. **두 실행이므로
단일 실행보다 계획 호출 수가 두 배다.** 제품 소재는 콘텐츠 유형·첫 3초 훅·전체
세 축을 분석하고 스키마 검증 실패 시 축당 한 번 재요청한다. `--dry-run`의 입력
추정은 영상만 계산하며 프롬프트·캡션·출력·thought 토큰은 제외한다.
실제 Gemini 비용에는 thought 토큰도 포함되므로 원장으로 확인한다.
누적 상한 기본값은 Gemini $12, OpenAI $10, Anthropic $8이다.
시범은 Gemini를 호출하며 첫 실행이 한도로 중단되면 두 번째 실행을 시작하지 않는다.

**재시도와 코드북 재생성(시트·키는 건드리지 않는다)**

```bash
# 코드북·안내만 다시 쓴다(API·DB·키 파일 접근 없음). 값 정의·우선순위는 docs/TAXONOMY.md에서 읽는다.
uv run python -m beautyads.eval.pilot_docs
# default 실행에서 Instagram 주소 재조회가 중단돼(MEDIA_REFRESH_STOPPED) 또는 못 찾아(MEDIA_URL_MISSING)
# 실패한 content_type만 다시 분석한다. 시트와 pilot_key.json은 그대로 두고 결과를
# pilot_key_supplement.json(같은 item_id)에 쓴다. 완료된 작업은 건드리지 않는다.
uv run python -m beautyads.eval.pilot_run --retry-missing
```

Instagram 주소 재조회가 사용량 한도로 도중에 멈추면 못 찾은 소재는
`MEDIA_REFRESH_STOPPED`(재시도 대상)로 기록하고, 재조회가 끝까지 돌았는데도 없으면
`MEDIA_URL_MISSING`으로 확정한다. 키가 사라진 게시물(`MEDIA_URL_GONE`)과는 다르다.
`--retry-missing`은 호출 전 점검과 비용 상한 검사를 시범과 똑같이 한다.
재시도 출력에는 `REFRESH_SCAN` 줄이 계정마다 붙는다. 스캔한 쪽수(`pages`), 못 찾은 게시물 수(`remaining`),
마지막 앱 사용량 세 지표(`usage`), 중단 코드(`stopped`)이며, 사용량이 높아 멈춘 시점을 보여 준다.

출력은 실행 태그별 상태 분포, 이번 실행의 `gemini_cost_usd`, 분할 파일의
`split_sha256`, 네 파일의 경로다. 기본 출력 폴더 `data/interim/pilot` 아래에
`pilot_sheet.csv`, `pilot_codebook.csv`, `pilot_instructions.md`, `pilot_key.json`을 쓴다.
`--out-dir`은 `data/interim` 아래만 허용하고 경로 이탈·심볼릭 링크 이탈도 거부한다.
시범 명령은 키 파일을 읽거나 모델 라벨을 출력하지 않는다.

11-17~18에는 **시트의 영상 링크·제목·캡션으로 먼저 라벨링**하고,
값 선택과 비제품 소재의 빈칸 규칙은 코드북·`pilot_instructions.md`를 참고한다.
**키 파일(pilot_key.json)은 라벨링을 마치기 전에 열지 마세요.**
키 파일은 라벨링 뒤에 열어 두 실행 결과와 비교한다.

| 이유 코드 | 의미와 조치 |
|---|---|
| `ENV_MISSING:GEMINI_API_KEY` / `ENV_MISSING:POSTGRES_PASSWORD` | 해당 이름의 공백이 아닌 값을 설정한다. |
| `ENV_MISSING:INSTAGRAM_ACCESS_TOKEN` / `ENV_MISSING:INSTAGRAM_USER_ID` | 토큰과 호출 주체 ID를 설정한다. |
| `DOCKER_DOWN` / `POSTGRES_UNREACHABLE` | OrbStack·`make db-up`과 포트(기본 5433, `BEAUTYADS_POSTGRES_PORT`)를 확인한다. |
| `POSTGRES_AUTH_FAILED` / `POSTGRES_CONNECT_FAILED` | 비밀번호·컨테이너·포트를 확인한다. 비밀번호는 볼륨 최초 생성 시 적용되므로 기존 볼륨의 원래 값을 확인한다. |
| `COST_CAP:gemini` | 원장 누적액과 예산을 확인한다. 상한에 도달하면 호출하지 않는다. |
| `LEDGER_NOT_WRITABLE` | 원장과 부모 디렉터리의 쓰기 권한·여유 공간을 확인한다. |
| `PILOT_SPLIT_FILE_INVALID` | `config/brand_split.yaml`의 존재·형식을 확인한다. |
| `PILOT_SPLIT_NOT_VERIFIED` | 수집량 기준 미달이다. 수집 결과를 확인하고 추가 수집 또는 허용된 1회 재분할 후 실행한다. |
| `PILOT_NO_COLLECTION` | dev에 분석 가능한 YouTube·Instagram 소재가 없다. 수집 결과를 확인한다. |
| `PILOT_SHORTFALL <k>` | 목표보다 k건 부족하다. 가능한 소재로 계속 실행한다. |
| `OUTPUT_NOT_IGNORED` | 출력 폴더를 `data/interim` 아래로 지정한다. |
| `DAILY_LIMIT` / `RATE_LIMITED` | 한도 회복 뒤 재실행한다. 남은 작업은 pending으로 유지한다. |
| `INVALID_SETTING:<이름>` | 해당 설정의 형식·범위를 확인한다. 값은 출력하지 않는다. |

점검·수집량·옵션 오류는 종료 코드 2, 실행 중 한도 중단은 3,
정상 완료와 `--dry-run`은 0이다. 분석 도중 소재별 실패나 한도로 일부 결과가 비어도
선정 소재의 블라인드 시트는 생성하고 누락 결과는 키 파일에 빈 값으로 남긴다.
