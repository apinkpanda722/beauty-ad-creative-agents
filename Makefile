.PHONY: verify db-up db-down db-migrate graph-reset live-slice live-collect live-pilot pilot-compare cost-recalc e1-stage1 e1-stage2 live-analyze e1-score live-tiktok live-tiktok-analyze sync live-graph live-products live-ingredient-catalog live-cert-recheck live-cq live-compare

# 하네스의 단일 검증 진입점. Stop hook, scripts/execute.py, step AC가 모두 이 타깃을 호출한다.
# 키·네트워크·실제 서비스 없이 통과해야 한다. 실제 호출용 타깃(live-*)은 verify에 넣지 않는다.
# web/ 골격과 pnpm 린트·타입·테스트도 이 타깃에서 검증한다.
verify:
	uv run ruff check .
	uv run ruff format --check .
	uv run pytest -q
	@test -d web/node_modules || { echo "WEB_DEPS_MISSING: make web-install"; exit 1; }
	cd web && pnpm lint && pnpm typecheck && pnpm test

COMPOSE := docker compose --env-file .env -f deploy/docker-compose.yml

db-up:
	$(COMPOSE) up -d postgres neo4j

db-down:
	$(COMPOSE) down

db-migrate:
	uv run python -m beautyads.pipeline.migrate

graph-reset:
	@if [ "$(CONFIRM)" != "yes" ]; then echo "GRAPH_RESET_NOT_CONFIRMED: make graph-reset CONFIRM=yes"; exit 1; fi
	$(COMPOSE) stop neo4j
	$(COMPOSE) rm -f neo4j
	docker volume rm beautyads_neo4j_data

live-slice:
	uv run python -m beautyads.pipeline.slice

live-collect:
	uv run python -m beautyads.pipeline.collect

live-pilot:
	uv run python -m beautyads.eval.pilot_run

pilot-compare:
	uv run python -m beautyads.eval.pilot_compare

cost-recalc:
	uv run python -m beautyads.eval.cost_recalc $(ARGS)

e1-stage1:
	uv run python -m beautyads.eval.e1_sampling

e1-stage2:
	uv run python -m beautyads.eval.e1_stage2

live-analyze:
	uv run python -m beautyads.pipeline.analyze_target $(ARGS)

e1-score:
	uv run python -m beautyads.eval.e1_scorer $(ARGS)

live-tiktok:
	uv run python -m beautyads.pipeline.collect_tiktok $(ARGS)

live-tiktok-analyze:
	uv run python -m beautyads.pipeline.tiktok_collect_analyze $(ARGS)

sync:
	uv run python -m beautyads.pipeline.sync $(ARGS)

live-graph:
	uv run python -m beautyads.pipeline.sync --sample 50 --verify

live-products:
	uv run python -m beautyads.pipeline.products $(ARGS)

live-ingredient-catalog:
	uv run python -m beautyads.pipeline.ingredient_catalog $(ARGS)

live-cert-recheck:
	uv run python -m beautyads.pipeline.cert_recheck $(ARGS)

live-cq:
	uv run python -m beautyads.eval.cq_verify

.PHONY: live-product-identify
live-product-identify:
	uv run python -m beautyads.pipeline.product_identify $(ARGS)

.PHONY: live-agent
live-agent:
	uv run python -m beautyads.eval.live_agent $(ARGS)

.PHONY: live-agents
live-agents:
	uv run python -m beautyads.eval.agents_live $(ARGS)

.PHONY: live-evidence
live-evidence:
	uv run python -m beautyads.eval.evidence_check $(ARGS)

live-compare:
	uv run python -m beautyads.eval.p5_compare $(ARGS)

.PHONY: fetch-font
fetch-font:
	uv run python scripts/fetch_design_font.py $(ARGS)

.PHONY: live-evalset
live-evalset:
	uv run python -m beautyads.eval.evalset_candidates $(ARGS)

.PHONY: live-e2e5
live-e2e5:
	uv run python -m beautyads.eval.e2e5_live $(ARGS)

.PHONY: live-e3
live-e3:
	uv run python -m beautyads.eval.e3_live $(ARGS)

.PHONY: live-isolation
live-isolation:
	uv run python -m beautyads.eval.isolation_live $(ARGS)

.PHONY: demo-clarify
demo-clarify:
	uv run python -m beautyads.eval.clarify_demo $(ARGS)

.PHONY: obs-up obs-down obs-check
obs-up:
	uv run python -m beautyads.obs.langfuse_check preflight
	$(COMPOSE) --profile obs up -d

obs-down:
	$(COMPOSE) --profile obs stop
	$(COMPOSE) --profile obs rm -f

obs-check:
	uv run python -m beautyads.obs.langfuse_check

# make serve; make serve BEAUTYADS_GROUP=test BEAUTYADS_EVAL_MODEL=claude-sonnet-5-5 BEAUTYADS_WITH_IMAGE=1
.PHONY: serve
serve:
	uv run python -m beautyads.api.main

.PHONY: web-install
web-install:
	cd web && pnpm install --frozen-lockfile

K3D_KUBECTL := kubectl --context k3d-beautyads -n beautyads

.PHONY: k3d-up
k3d-up:
	@test -f .env || { echo "K3D_ENV_MISSING: see .env.example"; exit 1; }
	docker build -f deploy/Dockerfile.api -t beautyads-api:local .
	docker build -f deploy/Dockerfile.web --build-arg BEAUTYADS_API_ORIGIN=http://api:8000 -t beautyads-web:local .
	@bash -o pipefail -c 'clusters=$$(k3d cluster list --no-headers) && { printf "%s\n" "$$clusters" | awk '\''$$1 == "beautyads" {found=1} END {exit !found}'\'' || k3d cluster create beautyads --agents 0 -p "3100:30000@server:0"; }'
	k3d image import beautyads-api:local beautyads-web:local -c beautyads
	$(K3D_KUBECTL) apply -f deploy/k3d/namespace.yaml
	@bash -o pipefail -c '$(K3D_KUBECTL) create secret generic beautyads-env --from-env-file=.env --dry-run=client -o yaml | $(K3D_KUBECTL) apply -f -'
	$(K3D_KUBECTL) apply -k deploy/k3d
	$(K3D_KUBECTL) rollout status statefulset/postgres --timeout=300s
	$(K3D_KUBECTL) rollout status statefulset/neo4j --timeout=300s
	$(K3D_KUBECTL) rollout restart deployment/api deployment/web
	$(K3D_KUBECTL) rollout status deployment/api --timeout=300s
	$(K3D_KUBECTL) rollout status deployment/web --timeout=300s

.PHONY: k3d-seed
k3d-seed:
	@if [ "$(CONFIRM)" != "yes" ]; then echo "K3D_SEED_NOT_CONFIRMED: make k3d-seed CONFIRM=yes"; exit 1; fi
	@test -f data/manifest/costs.jsonl || { echo "K3D_LEDGER_MISSING: data/manifest/costs.jsonl"; exit 1; }
	$(K3D_KUBECTL) rollout status deployment/api --timeout=300s
	@bash -o pipefail -c 'docker exec beautyads-postgres pg_dump -U beautyads -d beautyads --clean --if-exists --no-owner --no-privileges | $(K3D_KUBECTL) exec -i postgres-0 -- psql -U beautyads -d beautyads --set ON_ERROR_STOP=1'
	# kubectl verifies the Pod runtime; retain bounded Service TCP checks through sync's existing injection points.
	$(K3D_KUBECTL) exec deployment/api -c api -- sh -ec 'for layer in 1 2 3; do python -c '\''from beautyads.pipeline.sync import main, tcp_reachable; from beautyads.settings import get_setting; raise SystemExit(main(docker_check=lambda: True, tcp_check=lambda host, port, timeout: tcp_reachable(get_setting("BEAUTYADS_POSTGRES_HOST", "127.0.0.1") if host == "127.0.0.1" else host, port, timeout)))'\'' --layers "$$layer" --full; done'
	$(K3D_KUBECTL) exec deployment/api -c api -- mkdir -p /app/data/manifest
	@set -eu; pod=$$($(K3D_KUBECTL) get pods -l app=api --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}'); test -n "$$pod"; $(K3D_KUBECTL) cp data/manifest/costs.jsonl "$$pod:/app/data/manifest/costs.jsonl" -c api
	$(K3D_KUBECTL) rollout restart deployment/api
	$(K3D_KUBECTL) rollout status deployment/api --timeout=300s

.PHONY: k3d-down
k3d-down:
	@if [ "$(CONFIRM)" != "yes" ]; then echo "K3D_DOWN_NOT_CONFIRMED: make k3d-down CONFIRM=yes"; exit 1; fi
	k3d cluster delete beautyads

# make demo-up: 시연(test 그룹, sonnet, 시안 포함, 웹 운영 모드). 개발은 make serve
.PHONY: demo-up
demo-up:
	$(MAKE) db-up
	@bash -c 'trap "kill 0" EXIT; BEAUTYADS_GROUP=test BEAUTYADS_EVAL_MODEL=claude-sonnet-5-5 BEAUTYADS_WITH_IMAGE=1 uv run python -m beautyads.api.main & (cd web && pnpm build && pnpm start) & wait'
