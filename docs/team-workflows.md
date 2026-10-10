# Four-person workflow

| Engineer        | Owns                                                       | Suggested first task                                                                          |
| --------------- | ---------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| 1 — Frontend/3D | `frontend/`                                                | Replace procedural buildings with licensed GLBs and add speech presentation                   |
| 2 — Simulation  | `backend/modules/simulation/`                              | Extract economic routines, add daily production limits, and test sustained scarcity           |
| 3 — AI          | `backend/modules/agents/`                                  | Add one environment-configured provider with structured strategic proposals and adapter tests |
| 4 — API/history | `backend/api/`, `backend/modules/history/`, infrastructure | Add checkpoint retention/migrations and branch comparison metrics                             |

Use short-lived `feat/3d-world`, `feat/simulation-engine`, `feat/ai-agents`, and `feat/history-backend` branches, adding a suffix for distinct PRs. Integrate into main frequently. A PR should state the behavior change, tests, and any contract changes; include a screenshot when the visual interaction changes.

## Shared contracts

Propose a schema change in the PR description with a request/event example and expected compatibility impact. Ask the affected owners to review it. The engine owns Pydantic models; the API/history owner coordinates the exported schema. Regenerate with `make contracts` and include all generated outputs in the same PR. CI rejects schema drift. Do not change TypeScript types directly. Additive fields should have suitable defaults; persisted schema changes require a version/migration plan before loading old worlds.

## Independent work

- Frontend: `VITE_OFFLINE=true make frontend`, then `pnpm --filter @kronos/web test`. No API required.
- Simulation: `uv run pytest backend/modules/simulation/tests`. No database or API required.
- Agents: `uv run pytest backend/modules/agents/tests`. No paid calls required.
- History/API: `uv run pytest backend/modules/history/tests backend/api/tests`. Tests use temporary databases.

If uv/pnpm were installed locally by bootstrap, use `make test` or their paths under `.tools/`. Run `make check` before merging and `make contracts` after interface changes. Core module edits should stay in the owner's directory. API and frontend should integrate through the shared contract, not duplicate engine rules.

## Defaults for team agreement

One global local session, one API worker, one day per tick, seven initial citizens, 150-cent wages, 5,000-cent construction, independent business prices with explicitly all-bakery one-time interventions, and checkpoint forks only. The scaffold makes these concrete defaults, not blockers. Revisit strategy cadence and snapshot retention as scale grows. The PDF's broader three-intervention/product ambitions remain future work; the bootstrap brief's complete bread-price slice is implemented first.

## Adding tool endpoints

Within the integration owner's API area, endpoint files are split by responsibility under `backend/api/src/kronos/routes/`. Agent endpoint work goes in `agents.py`, player endpoint work in `user.py`, and simulation controls/automation in `backend.py`; shared reads and history have their own files. Coordinate API edits with engineer 4, but ordinary additions to an existing router do not require editing `main.py`. Keep engine rules in engineer 2's module and provider reasoning in engineer 3's module. Update the canonical models and regenerate contracts when an endpoint needs new wire types.
