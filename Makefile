.PHONY: verify

# 하네스의 단일 검증 진입점. Stop hook, scripts/execute.py, step AC가 모두 이 타깃을 호출한다.
# 키·네트워크·실제 서비스 없이 통과해야 한다. 실제 호출용 타깃(live-*)은 verify에 넣지 않는다.
# web/ 골격과 pnpm 단계는 M3 phase의 step 0에서 추가한다.
verify:
	uv run ruff check .
	uv run ruff format --check .
	uv run pytest -q
