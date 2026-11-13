.PHONY: verify db-up db-down graph-reset live-slice live-collect live-pilot pilot-compare cost-recalc

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
