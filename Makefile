UV ?= uv
export UV_CACHE_DIR ?= /tmp/apg-uv-cache

.PHONY: setup demo test check eval-fixtures eval-live smoke-live browser-test docker-smoke
setup:
	$(UV) sync --frozen

demo:
	$(UV) run --frozen python -m apg

test:
	$(UV) run --frozen pytest -m 'not browser' -q

check:
	$(UV) run --frozen ruff format --check .
	$(UV) run --frozen ruff check .
	$(UV) run --frozen mypy
	$(UV) run --frozen python scripts/forbidden_character.py

eval-fixtures:
	$(UV) run --frozen python -m apg.evaluation --mode fixture --output reports/fixtures.json

eval-live:
	$(UV) run --frozen python -m apg.evaluation --mode live --output reports/live.json

smoke-live:
	$(UV) run --frozen python -m apg.evaluation --mode live --cases L01 A01 --output reports/live-smoke.json

browser-test:
	$(UV) run --frozen playwright install chromium
	$(UV) run --frozen pytest -m browser -q

docker-smoke:
	docker build -t agent-permission-gateway:local .
	$(UV) run --frozen python scripts/docker_smoke.py
