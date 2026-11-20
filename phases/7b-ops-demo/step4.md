# Step 4: k3d-deploy

## 설계 검토 기록

**배경(PRD 로컬 실행 절차, ARCHITECTURE "실행 환경")**: 저장소를 받아 로컬 Kubernetes(k3d)에 같은 구성을 매니페스트로 올릴 수 있어야 한다(유료 서버 상시 배포 없음, ADR-007). 지금 `deploy/`에는 `docker-compose.yml`뿐이고 **Dockerfile이 없다**(2026-11-20 확인). 시연 촬영의 기본 경로는 compose + 로컬 프로세스(`make demo-up`, step 5)이고 **k3d는 배포 구성 검증용**이다. 이 step은 이미지 두 개의 Dockerfile, `deploy/k3d/` 매니페스트, `make k3d-up`·`k3d-seed`·`k3d-down`, README 절차를 만든다. **클러스터 기동·이미지 빌드·데이터 이관은 사용자가 실행한다**(실제 서비스, 이미지 pull).

**실측·확인한 사실(2026-11-20)**: 이 맥에 `k3d v5.9.0`(k3s v1.36.4-k3s1)·`kubectl v1.33.9`·`docker`가 설치돼 있고 k3d 클러스터는 아직 없다. `uv 0.11.24`. 로컬 `postgres:17.11`·`neo4j:2026.10.1-community` 이미지가 있다(compose가 쓰는 태그). 현재 데이터: PostgreSQL 27 MB, 비용 원장 `data/manifest/costs.jsonl` 약 2.8 MB.

**코드에서 확인한 제약(설계에 반영)**:
- **`store/connection.py` `postgres_dsn()`이 호스트를 `127.0.0.1`로 고정한다**(포트만 `BEAUTYADS_POSTGRES_PORT` 설정). 클러스터의 api Pod는 Service 이름(`postgres`)으로 접속해야 하므로 `BEAUTYADS_POSTGRES_HOST`(기본 `127.0.0.1`)를 더한다. 같은 함수를 `api/assembly.py`·체크포인터·`pipeline/*`이 쓰므로 **기본값은 지금과 같아야 한다**(`tests/test_store.py`가 DSN 문자열을 단언한다).
- Neo4j: `settings.neo4j_uri()`가 `BEAUTYADS_NEO4J_URI`(기본 `bolt://127.0.0.1:7688`)를 읽고 비밀번호는 `NEO4J_PASSWORD`다 → 설정만으로 Service 주소를 줄 수 있다.
- 파일 경로는 상대 경로다: `Settings.ledger_path = data/manifest/costs.jsonl`(`BEAUTYADS_LEDGER_PATH`), 시안 `data/design`(`api/assembly.py` `_DESIGN_DIR`), 설정 `config/workspaces.yaml`·`config/claim_rules.yaml`. trace는 원장 옆 `traces.jsonl`이다. → 컨테이너 작업 디렉터리 `/app`에 `config/`를 넣고 `/app/data`에 PVC를 붙인다.
- 서버는 `python -m beautyads.api.main`(step 1, `127.0.0.1` 고정). **컨테이너에서는 Pod 밖에서 접근해야 하므로 호스트를 바꿔야 한다**: `BEAUTYADS_API_HOST`(기본 `127.0.0.1`, 허용 `127.0.0.1`·`0.0.0.0`)를 `api/main.py`에 더한다(아래).
- 웹 `next.config.ts`는 `rewrites()`에서 `BEAUTYADS_API_ORIGIN`을 읽는다. **Next는 rewrites 대상을 빌드 때 결정하므로** 이미지 빌드 인자로 `http://api:8000`을 넘겨야 한다. `output: "standalone"`을 더해 작은 런타임 이미지를 만든다.
- 그래프는 PostgreSQL에서 다시 만들 수 있다(ADR-010, 멱등). `pipeline/sync.py`의 `--layers`는 `1`·`2`·`3` 중 하나이고 `--full`·`--verify` 옵션이 있다. 정확한 호출은 코드(`sync.py` 396~406행 근처, `README.md` sync 절)에서 읽어 정한다.

**설계 결정**:
- **이미지**(태그는 `:local`, 레지스트리 없음, `k3d image import`로 클러스터에 넣는다): `beautyads-api:local`(`deploy/Dockerfile.api`), `beautyads-web:local`(`deploy/Dockerfile.web`). 베이스 이미지는 **명시 태그**(`latest` 금지): api는 파이썬 3.12 + uv를 쓰되 `pyproject.toml`의 `python-preference = "only-managed"` 때문에 uv가 관리 파이썬을 받으므로 `uv sync --locked --no-dev`를 이미지 빌드에서 실행해 `/app/.venv`를 만든다(실행 PATH에 `/app/.venv/bin`). uv 버전은 `0.11.24`와 호환되는 `0.11.x`로 고정한다(`pyproject.toml` 빌드 요구 `uv_build>=0.11.24,<0.12.0`). web은 node 24 계열(`jsdom`이 아니라 빌드용; `web/package.json`의 `packageManager`와 같은 pnpm 12.8.1) 다단계 빌드 + standalone 출력. **비밀·`.env`·`data/`를 이미지에 넣지 않는다**(`.dockerignore`로 `.env*`·`data/`·`web/node_modules`·`.git`·`phases/` 제외, **`.env.example`은 허용**).
- **매니페스트**(`deploy/k3d/`, 네임스페이스 `beautyads`, kustomize `kustomization.yaml`): `namespace.yaml`, `postgres.yaml`(StatefulSet `postgres:17.11`, PVC, Service `postgres`, 비밀번호는 Secret `beautyads-env`의 `POSTGRES_PASSWORD`, DB·사용자 `beautyads`), `neo4j.yaml`(StatefulSet `neo4j:2026.10.1-community`, PVC, Service `neo4j`, `NEO4J_AUTH`는 Secret의 `NEO4J_PASSWORD`로 `neo4j/<비밀번호>`를 **런타임에 조립**), `api.yaml`(Deployment `beautyads-api:local`, `imagePullPolicy: Never`, `envFrom` Secret + 설정 환경 변수 `BEAUTYADS_GROUP=test`·`BEAUTYADS_EVAL_MODEL=claude-sonnet-5-5`·`BEAUTYADS_WITH_IMAGE=1`·`BEAUTYADS_POSTGRES_HOST=postgres`·`BEAUTYADS_POSTGRES_PORT=5432`·`BEAUTYADS_NEO4J_URI=bolt://neo4j:7687`·`BEAUTYADS_API_HOST=0.0.0.0`, PVC를 `/app/data`에, `/healthz` readiness probe, Service `api`), `web.yaml`(Deployment `beautyads-web:local`, `imagePullPolicy: Never`, Service `NodePort` 30000). **Secret은 매니페스트에 넣지 않는다**: `make k3d-up`이 `.env`에서 `kubectl create secret generic beautyads-env --from-env-file=.env --dry-run=client -o yaml | kubectl apply -f -`로 만든다(값을 출력하지 않는다).
- **Makefile**(각각 별도 `.PHONY` 블록, `verify` 레시피 불변): `k3d-up`(이미지 빌드 → 클러스터 `beautyads`가 없으면 `k3d cluster create beautyads --agents 0 -p "3100:30000@server:0"`(호스트 3100: 시연의 `pnpm start` 3000과 충돌하지 않게) → `k3d image import` → Secret → `kubectl apply -k deploy/k3d` → rollout 대기), `k3d-seed`(**`CONFIRM=yes` 필요**, 없으면 `K3D_SEED_NOT_CONFIRMED: make k3d-seed CONFIRM=yes`로 종료 코드 1; compose의 `beautyads-postgres`에서 `pg_dump`를 클러스터 `postgres-0`의 `psql`로 파이프 → api Pod에서 그래프 재생성(`sync`, 계층 1·2·3 각각 `--full`) → `data/manifest/costs.jsonl`을 `kubectl cp`로 api Pod의 `/app/data/manifest/`에), `k3d-down`(**`CONFIRM=yes` 필요**, 클러스터만 삭제하고 compose 볼륨은 건드리지 않는다).
- **README의 "명령 한 줄 실행" 절차**: 두 가지를 구분해 적는다 — (a) 기본(로컬 개발·시연): `make db-up` → `make db-migrate` → `make serve` + `pnpm --dir web dev`/`make demo-up`(step 5), (b) k3d: `make k3d-up` → `make k3d-seed CONFIRM=yes` → `http://127.0.0.1:3100`. **"한 줄로 데이터까지"는 아니다**(데이터 이관이 별도 명령)임을 사실대로 적는다. `.env`에 필요한 이름은 `.env.example`을 가리킨다(값을 적지 않는다).

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `BEAUTYADS_POSTGRES_HOST` | `store/connection.py` | `api/assembly.py`·체크포인터·`pipeline/*`(`postgres_dsn()` 경유, 코드 변경 없음), `deploy/k3d/api.yaml` |
| `BEAUTYADS_API_HOST` | `api/main.py` | `deploy/k3d/api.yaml`, `tests/test_api_main.py` |
| 이미지·매니페스트 | `deploy/Dockerfile.*`, `deploy/k3d/*` | `Makefile`(`k3d-*`), `tests/test_k3d.py`(정적 검사) |
| `output: "standalone"` | `web/next.config.ts` | `deploy/Dockerfile.web` |

**기존 단언과의 충돌 점검**: `tests/test_store.py`는 `postgres_dsn`의 DSN을 단언한다(기본 호스트·포트는 불변이므로 **케이스 추가에 한함**). `tests/test_api_main.py`는 호스트가 `127.0.0.1`이고 `uvicorn.run`의 호스트가 고정임을 단언한다(`BEAUTYADS_API_HOST` 기본값 불변, 케이스 추가에 한함: 허용 값 `127.0.0.1`·`0.0.0.0` 외는 `InvalidSetting`, 기본은 `127.0.0.1`). `web/tests`와 `tests/test_web_contract.py`는 `web/next.config.ts`에서 `agentRules: false`를 단언한다(step 8) → **그 줄을 유지**한다. `tests/test_compose.py`·`Makefile` 소비자 테스트는 `verify` 본문과 `.PHONY` 첫 줄을 단언하므로 새 타깃은 별도 `.PHONY` 블록이고 `verify`에 `k3d-`가 들어가지 않는다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`(실행 환경), `/docs/ADR.md`(ADR-007, ADR-009, ADR-010), `/docs/PRD.md`(시연과 포트폴리오 산출물: 로컬 실행 절차)
- `/deploy/docker-compose.yml`, `/Makefile`, `/README.md`, `/.env.example`, `/pyproject.toml`, `/uv.lock`(읽기 전용)
- `/src/beautyads/store/connection.py`, `/src/beautyads/api/main.py`, `/src/beautyads/settings.py`, `/src/beautyads/pipeline/sync.py`(CLI 옵션), `/src/beautyads/pipeline/migrate.py`
- `/web/package.json`, `/web/next.config.ts`, `/web/pnpm-lock.yaml`(읽기 전용)
- `/tests/test_store.py`(DSN 단언), `/tests/test_api_main.py`, `/tests/test_compose.py`(`recipe()`·YAML 읽기 방식)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `deploy/Dockerfile.api`, `deploy/Dockerfile.web`, `.dockerignore`, `deploy/k3d/`, `Makefile`, `README.md`, `src/beautyads/store/connection.py`, `src/beautyads/api/main.py`, `web/next.config.ts`, `tests/test_k3d.py`, `tests/test_store.py`, `tests/test_api_main.py`, `tests/test_api_assembly.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `deploy/Dockerfile.api`, `deploy/Dockerfile.web`, `.dockerignore`, `deploy/k3d/`, `Makefile`, `README.md`, `src/beautyads/store/connection.py`, `src/beautyads/api/main.py`, `web/next.config.ts`, `tests/test_k3d.py`, `tests/test_store.py`, `tests/test_api_main.py`, `tests/test_api_assembly.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1. `store/connection.py`**: `postgres_dsn`이 `BEAUTYADS_POSTGRES_HOST`(기본 `127.0.0.1`)를 `get_setting`으로 읽어 호스트에 쓴다(포트와 같은 방식, 빈 값은 기본값, 비밀번호 처리 불변). **`api/main.py`**: `BEAUTYADS_API_HOST`(기본 `127.0.0.1`, 허용 `127.0.0.1`·`0.0.0.0`, 그 밖은 `InvalidSetting`)를 `uvicorn.run(host=...)`에 쓰고 시작 줄의 URL도 같은 호스트를 보여 준다. **`web/next.config.ts`**: `output: "standalone"`을 더한다(`agentRules: false`·`rewrites` 유지).

**2. 이미지·매니페스트·Makefile·README**: 위 "설계 결정"대로. 매니페스트는 평문 YAML(kustomize)이고 비밀 값이 없다. Dockerfile은 베이스 이미지에 명시 태그를 쓴다.

**3. 이전 step이 만든 불안정 테스트 수정(`tests/test_api_assembly.py`, 이 step의 첫 실행이 blocked돼 추가)**: 7b step 3이 추가한 `test_ask_exports_after_local_append_in_daemon_without_affecting_result`(두 케이스: `raises` False·True)가 **해시 시드에 따라 실패한다**(재현: `PYTHONHASHSEED=1`·`3`에서 2건 실패, `0`·`2`는 통과, 2026-11-20). 원인: 마지막 단언 `assert record.tenant_id == next(iter(rig.profiles))`가 딕셔너리 첫 항목(`dev-mixsoon`)과 비교하는데, 요청은 `invoke(services)`가 `next(iter(services.allowed_tenants))`(frozenset 순회 순서, 시드마다 달라짐)로 고른 테넌트를 쓴다(`invoke`는 388행 부근). **이 단언을 요청이 실제로 쓴 테넌트와 비교하도록 갱신한다**: `run()` 안에서 `invoke` 호출과 같은 방식으로 고른 테넌트(`next(iter(services.allowed_tenants))`, 743행 부근 기존 단언과 같은 패턴)를 변수에 저장해 두고 그 값과 `record.tenant_id`가 같음을 단언한다. **단언을 `in`·존재 확인으로 약화하지 않는다.** 이 파일의 다른 테스트·단언은 바꾸지 않는다. 같은 seed 목록(`PYTHONHASHSEED`를 0~3으로 바꿔 이 두 케이스를 돌려도 통과)을 최종 응답에 적는다.

**테스트(합성 데이터, 서비스·키·네트워크·Docker·`kubectl` 없음, 파일만 읽는다)**
- `tests/test_store.py`(케이스 추가에 한함): (1) 호스트 설정이 없거나 빈 값·공백이면 DSN이 지금과 **같은 문자열**, (2) `BEAUTYADS_POSTGRES_HOST=postgres`이면 호스트만 바뀌고 포트·비밀번호 인코딩 불변, (3) 비밀번호가 예외·DSN 외 어디에도 안 남음(기존 단언 유지).
- `tests/test_api_main.py`(케이스 추가에 한함): (4) `BEAUTYADS_API_HOST` 기본 `127.0.0.1`, `0.0.0.0` 허용, 그 밖(`localhost`·`::`·빈 값이 아닌 임의 문자열)은 `InvalidSetting`이고 예외 문자열에 입력 값이 없음, (5) `main()`이 `uvicorn.run`에 그 호스트를 넘김.
- `tests/test_k3d.py`(새): (6) `deploy/k3d/*.yaml`이 모두 `yaml.safe_load_all`로 읽히고 모든 객체가 `namespace: beautyads`(Namespace 자신 제외), (7) **어떤 매니페스트에도 `kind: Secret`이 없고** 비밀 값(비밀번호·키 형태 문자열)이 없다, (8) 모든 컨테이너 이미지에 명시 태그가 있고 `latest`가 아니다(앱 이미지는 `:local`이고 `imagePullPolicy: Never`), (9) api Deployment에 필수 환경 변수 이름(`BEAUTYADS_GROUP`·`BEAUTYADS_EVAL_MODEL`·`BEAUTYADS_WITH_IMAGE`·`BEAUTYADS_POSTGRES_HOST`·`BEAUTYADS_POSTGRES_PORT`·`BEAUTYADS_NEO4J_URI`·`BEAUTYADS_API_HOST`)과 `/app/data` 마운트, `/healthz` readiness, (10) postgres·neo4j 이미지 태그가 `deploy/docker-compose.yml`의 같은 서비스와 같다, (11) Dockerfile 베이스 이미지에 `latest`·태그 없음이 없고 `.env`·`data/`를 `COPY`하는 줄이 없으며 `.dockerignore`에 `.env*`·`data/`가 있고 `.env.example`은 제외하지 않는다, (12) Makefile: `k3d-up`·`k3d-seed`·`k3d-down`이 별도 `.PHONY` 블록, **`verify` 본문에 `k3d-`가 없음**, `k3d-seed`·`k3d-down`이 `CONFIRM`을 검사하고 메시지 `K3D_SEED_NOT_CONFIRMED`가 있음, `k3d-down`이 `volume rm`을 쓰지 않음, (13) `web/next.config.ts`에 `standalone`과 `agentRules: false`가 함께 있고 `Dockerfile.web`이 빌드 인자 `BEAUTYADS_API_ORIGIN`을 받음.

## Acceptance Criteria

```bash
make verify   # ruff + pytest + pnpm lint·typecheck·test 통과
NEXT_TELEMETRY_DISABLED=1 pnpm --dir web build   # standalone 출력으로도 프로덕션 빌드 통과
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - AGENTS.md CRITICAL 규칙을 위반하지 않았는가?
3. 결과를 최종 응답(JSON)으로 보고한다. `phases/` 아래 파일은 수정하지 않고 git commit도 하지 않는다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약(설치한 패키지 버전 포함, 승인 목록에서 조정한 것은 이유까지)"`
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

- `make k3d-up`·`make k3d-seed`·`make k3d-down`·`docker build`·`k3d cluster create`·`kubectl apply`를 실행하지 마라. 이유: 이미지 빌드·pull·클러스터 기동·데이터 이관은 실제 서비스 접속이고 사용자가 한다(AGENTS.md CRITICAL, A-FP-040). 매니페스트·Dockerfile은 정적 파일 테스트(`tests/test_k3d.py`)로만 검증한다.
- Secret 값·`.env`·`data/`를 이미지나 매니페스트에 넣거나 `kind: Secret` 매니페스트를 만들지 마라. `.env`를 열거나 `cat`·`echo`로 출력하지 마라. 이유: 비밀 값은 `.env`에서 `settings`의 한 함수로만 읽고 어디에도 남기지 않는다(AGENTS.md CRITICAL). Secret은 `make k3d-up`이 로컬 `.env`에서 만든다.
- `postgres_dsn`의 기본 호스트·포트·비밀번호 처리와 `BEAUTYADS_API_HOST` 기본값을 바꾸지 마라. 서버를 `0.0.0.0`으로 기본 노출하지 마라. 이유: 기본 동작(로컬 전용, `127.0.0.1`)은 `tests/test_store.py`·`tests/test_api_main.py`가 고정했고 ADR-007은 로컬 실행이다. 컨테이너에서만 환경 변수로 연다.
- `k3d-seed`가 compose의 볼륨·컨테이너를 지우거나 `docker volume rm`·`down -v`를 쓰지 마라. `k3d-down`이 클러스터 밖 자원을 지우지 마라. 이유: compose 데이터가 원본이고 클러스터는 파생물이다(ADR-010, 기존 `graph-reset` 안전 규칙과 같다).
- 매니페스트·README에 "한 줄로 데이터까지 올라간다"고 쓰지 마라. 모델 호출이 드는 `make live-*`를 절차에 넣지 마라. 이유: 데이터 이관은 `k3d-seed`가 따로 하는 사실 그대로 적는다(사용자 원칙: 사실과 다른 문구를 만들지 않는다).
