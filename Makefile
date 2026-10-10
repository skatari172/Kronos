.DEFAULT_GOAL := help
UV ?= $(shell command -v uv 2>/dev/null || echo $(CURDIR)/.tools/python/bin/uv)
PNPM ?= $(shell command -v pnpm 2>/dev/null || echo $(CURDIR)/.tools/node/node_modules/.bin/pnpm)
export PATH := $(dir $(PNPM)):$(PATH)
export UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
BACKEND_PORT := 8000
FRONTEND_PORT := 5173

# Stop whatever is listening on a port, so a stale dev server never blocks a restart.
define free_port
	@pids=$$(lsof -ti tcp:$(1) -sTCP:LISTEN); \
	if [ -n "$$pids" ]; then \
		echo "Stopping existing server on port $(1)"; \
		kill $$pids; \
		for _ in 1 2 3 4 5 6 7 8 9 10; do lsof -ti tcp:$(1) -sTCP:LISTEN >/dev/null || break; sleep 0.5; done; \
	fi
endef

# Fresh village plus backend and frontend in one terminal (scripts/start.sh; KEEP=1 keeps the world).
.PHONY: help start install backend frontend stop test lint format build contracts check reset db-init
help:
	@echo 'make start | install | backend | frontend | stop | test | lint | format | build | contracts | check | reset | db-init'
start:
	./scripts/start.sh $(if $(KEEP),--keep,)
install:
	./scripts/bootstrap.sh
	$(UV) sync --frozen
	CI=true $(PNPM) install --frozen-lockfile
backend:
	$(call free_port,$(BACKEND_PORT))
	$(UV) run python scripts/run_backend.py
frontend:
	$(call free_port,$(FRONTEND_PORT))
	$(PNPM) dev
stop:
	$(call free_port,$(BACKEND_PORT))
	$(call free_port,$(FRONTEND_PORT))
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
db-init:
	$(UV) run python scripts/init_db.py

