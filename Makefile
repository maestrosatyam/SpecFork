PY ?= .venv/bin/python
.PHONY: setup dev web test lint probe eval docker-build

setup:            ## create venv + install backend and frontend deps
	uv venv --python 3.12 .venv || python3 -m venv .venv
	uv pip install --python $(PY) -r requirements-dev.txt || $(PY) -m pip install -r requirements-dev.txt
	cd web && npm ci

dev:              ## run API on :8000 (frontend dev server: make web)
	$(PY) -m uvicorn app.main:app --reload --port 8000

web:
	cd web && npm run dev

build:
	cd web && npm run build

test:             ## backend + frontend tests (offline, no API key needed)
	$(PY) -m pytest -q
	cd web && npm test --silent

lint:
	$(PY) -m ruff check app tests evals scripts

probe:            ## live Nebius Token Factory / NVIDIA Nemotron probe (needs NEBIUS_API_KEY)
	$(PY) scripts/probe_nebius.py

eval:             ## live benchmark evaluation (needs NEBIUS_API_KEY; costs a few cents)
	$(PY) evals/run_eval.py
