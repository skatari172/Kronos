.DEFAULT_GOAL := help
UV ?= $(shell command -v uv 2>/dev/null || echo $(CURDIR)/.tools/python/bin/uv)
PNPM ?= $(shell command -v pnpm 2>/dev/null || echo $(CURDIR)/.tools/node/node_modules/.bin/pnpm)
export PATH := $(dir $(PNPM)):$(PATH)
export UV_CACHE_DIR ?= $(CURDIR)/.cache/uv

.PHONY: help install backend frontend test lint format build contracts check reset
help:
	@echo 'make install | backend | frontend | test | lint | format | build | contracts | check | reset'
install:
	./scripts/bootstrap.sh
	$(UV) sync --frozen
	CI=true $(PNPM) install --frozen-lockfile
backend:
	$(UV) run python scripts/run_backend.py
frontend:
	$(PNPM) dev
test:
	$(UV) run pytest -q
	$(PNPM) test
lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(PNPM) lint
	$(PNPM) format:check
format:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .
	$(PNPM) format
build:
	$(PNPM) build
contracts:
	$(UV) run python scripts/export_contracts.py
	$(PNPM) exec openapi-typescript backend/contracts/schemas/openapi.json -o backend/contracts/generated/api.ts
check: test lint build
reset:
	$(UV) run python scripts/reset_data.py
