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
