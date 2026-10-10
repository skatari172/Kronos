# KRONOS

**A living world you can rewrite.** A runnable hackathon foundation: a procedural 3D village, a small economy, validated natural-language price changes, and saved alternate timelines.

## Run locally

Requires **Python 3.12+**, **Node 22.12+**, npm, and Make. No Docker, API keys, or paid services.

```sh
make install
make backend       # terminal 1 — http://localhost:8000
make frontend      # terminal 2 — http://localhost:5173
```

`make install` uses uv and pnpm if installed, otherwise installs them inside ignored `.tools/`. It installs the committed lockfiles. Python modules use a single uv environment. Optional settings are in `.env.example`; copy to `.env` to customize the backend. Vite reads the root `.env` / `.env.local` or shell variables:

```sh
VITE_OFFLINE=true make frontend
```

Without an API, the Vite development server automatically shows a clearly labeled fixture preview. Start the API and reload to enable real simulation. A production build requires the API.

## Repository map

```text
Kronos/
├── frontend/                  # React, 3D village, dashboard, transport, tests
├── backend/
│   ├── api/                   # FastAPI orchestration and API tests
│   ├── database/              # Authoritative SQLite database files
│   ├── modules/
│   │   ├── simulation/        # Pure Python world, contracts, action engine
│   │   ├── agents/            # Provider interface and deterministic mock
│   │   └── history/           # SQLite ledger, checkpoints, branches
│   └── contracts/             # Generated OpenAPI, TypeScript, demo fixture
├── docs/                      # Design, protocol, team workflow, demo guide
├── scripts/                   # Bootstrap, server, export, local reset
└── .github/workflows/         # Tests, lint, build, contract drift checks
```

Root configuration files manage the shared toolchain. Each Python module has its own `src/` and `tests/`; the source paths are configured by pytest and the backend launcher.

## What works

- Seven citizens, farm, bakery, market, six plots, ownership, cents, wheat, bread, hunger, wages, transactions, and seeded harvest/movement.
- Dark dashboard, isometric scene, building/citizen selection, inspector, live price labels, play/pause/step/speed, and expandable event ledger.
- Enter **“Increase bread price by 40%.”** Prices change from 5 to 7 coins; state/events persist before the WebSocket update. Subsequent trades use the new price. Decreases work too.
- The existing 36 typed engine actions cover trade, food, business management, jobs, relationships, rent, loans, research, inventions, and votes. Gameplay submissions queue for the next tick; the engine alone validates and changes the world.
- Build a real bakery from the dashboard; Marcus pays 50 coins and a free plot is occupied.
- Every commit saves a complete immutable checkpoint. Seek, fork, switch branches, and restart without losing state or re-running provider calls.
- Development preview cycles construction, upgrade, arrival, movement, price change, and departure with animation.

## Commands

| Command                          | Purpose                                               |
| -------------------------------- | ----------------------------------------------------- |
| `make install`                   | Install toolchain if needed, then locked dependencies |
| `make backend` / `make frontend` | Start each app independently                          |
| `make test`                      | pytest + Vitest                                       |
| `make lint`                      | Ruff, ESLint, and formatting checks                   |
| `make format`                    | Apply formatting and safe Python lint fixes           |
| `make build`                     | Typecheck and production frontend build               |
| `make contracts`                 | Export OpenAPI, fixture, and TypeScript               |
| `make check`                     | Tests, lint, formatting, production build             |
| `make reset`                     | Remove default local SQLite data; stop API first      |
| `make db-init`                   | Initialize or seed local SQLite database              |

Swagger UI: **http://localhost:8000/docs**, grouped into User tools, Agent tools, Backend tools, World, and History. Route ownership and request examples are in [API contracts](docs/api-contracts.md). The default SQLite file is `backend/database/kronos.db`, tracked in Git for local persistence. A custom database URL is not touched by `make reset`.

## Deliberate limits

This is a foundation, not a complete village game. The mock parser accepts percentage bread-price changes only; unsupported natural language returns a clear error. Post-tick strategies use copied observations to propose food purchases or neighbor conversations; proposals execute on the next tick. All gameplay tools share a runtime queue and return session queued/applied/rejected results. Committed outcomes persist as Events; pending attempts are discarded on restart. A configurable provider interface exists; no real LLM adapter is bundled and the mock ignores model selection. Citizens are rule-driven for daily routines. Deterministic rules open land, welcome newcomers, found and upgrade businesses, and house workers. Starvation departure awaits a database-owned persisted counter. See [the engine developer guide](docs/simulation-engine.md) for the current v1 contract and database handoffs.

Run one API process/worker. Active branch and playback are shared across local browser tabs, not per-user. No authentication or internet deployment is included. Checkpoints store full worlds on every commit for simplicity; introduce retention and migrations before long-running use. The timeline shows branch-local events; parent ancestry remains available through branch metadata. Existing historical outcomes are reproducible; future real LLM decisions would not guarantee identical counterfactuals.

The 3D renderer requires WebGL. Procedural geometry is intentionally replaceable; see `frontend/public/models/README.md`. The initial Three.js bundle is relatively large; optimize assets and code splitting when the scene grows.

See [demo scenarios](docs/demo-scenarios.md), [architecture](docs/architecture.md), and [team workflow](docs/team-workflows.md). Team defaults to review: village-wide one-time price interventions, one day per tick, 1.50-coin wages, 50-coin construction cost, and full-state WebSocket updates.
