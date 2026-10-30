# SpecFork developer tasks. Run `make help` for a list.
# Python tooling goes through uv (https://docs.astral.sh/uv/); the frontend uses npm in web/.

UV   ?= uv
PORT ?= 8000

.DEFAULT_GOAL := help
.PHONY: help setup dev web build test lint typecheck probe eval docker-build mcp package openapi

help: ## show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## install backend (uv, Python >= 3.11) and frontend (npm) dependencies
	@command -v $(UV) >/dev/null 2>&1 || { echo "uv not found: see https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
	$(UV) python find '>=3.11' >/dev/null 2>&1 || $(UV) python install 3.12
	$(UV) sync --extra dev
	cd web && npm ci

dev: ## run the API with auto-reload on :8000 (frontend hot reload: make web)
	$(UV) run uvicorn --factory specfork.server.main:create_app --reload --port $(PORT)

web: ## run the Vite frontend dev server (proxies /api to make dev)
	cd web && npm run dev

build: ## production frontend build into web/dist
	cd web && npm run build

test: ## backend + frontend tests (offline, no API key needed)
	$(UV) run pytest -q
	cd web && npm test --silent

lint: ## ruff lint + basedpyright type check
	$(UV) run ruff check .
	$(UV) run basedpyright

typecheck: ## TypeScript typecheck of the frontend
	cd web && npm run typecheck

probe: ## check configuration and the live model provider (needs an API key)
	$(UV) run specfork doctor

eval: ## live benchmark evaluation (needs an API key; costs a few cents)
	$(UV) run python evals/run_eval.py

docker-build: ## build the production Docker image
	docker build -t specfork .

mcp: ## run the SpecFork MCP server
	$(UV) run specfork mcp

package: ## build sdist + wheel with the web UI bundled (dist/)
	cd web && npm ci && npm run build
	rm -rf specfork/_web && cp -r web/dist specfork/_web
	$(UV) build
	rm -rf specfork/_web

openapi: ## regenerate docs/openapi.json from the server
	$(UV) run python scripts/gen_openapi.py
