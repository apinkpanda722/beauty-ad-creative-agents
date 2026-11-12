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
확인)이다. Instagram은 호출당 앱 사용량 약 0.5%(실측 추정)를 적용한다.
예를 들어 22계정 × 2쪽은 44호출, 예상 앱 사용량 약 22%다. 실제 한도와
시간당 사용량 창은 다를 수 있으며 수집기는 사용량 80% 이상이면 Instagram을 멈춘다.

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
