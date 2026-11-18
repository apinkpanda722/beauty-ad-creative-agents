.PHONY: verify db-up db-down db-migrate graph-reset live-slice live-collect live-pilot pilot-compare cost-recalc e1-stage1 e1-stage2 live-analyze e1-score live-tiktok live-tiktok-analyze sync live-graph live-products live-ingredient-catalog live-cert-recheck live-cq live-compare

# 하네스의 단일 검증 진입점. Stop hook, scripts/execute.py, step AC가 모두 이 타깃을 호출한다.
# 키·네트워크·실제 서비스 없이 통과해야 한다. 실제 호출용 타깃(live-*)은 verify에 넣지 않는다.
# web/ 골격과 pnpm 단계는 M3 phase의 step 0에서 추가한다.
verify:
	uv run ruff check .
	uv run ruff format --check .
	uv run pytest -q

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
