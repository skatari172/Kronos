# Working on KRONOS

The product name is **KRONOS**. Keep the root simple: `frontend/`, `backend/`, `docs/`, `scripts/` plus essential tool configuration. Do not recreate a top-level apps/packages layout.

- Frontend ownership: `frontend/`. Render snapshots; never treat browser changes as real simulation outcomes. Local offline fixtures are explicitly labeled development previews.
- Simulation ownership: `backend/modules/simulation/`. All authoritative mutations go through `Engine`. Preserve cents, stable IDs, seeded RNG state, and transaction validation.
- AI ownership: `backend/modules/agents/`. Providers return structured proposals. They cannot mutate a world or bypass engine validation.
- API/history ownership: `backend/api/`, `backend/modules/history/`, and developer infrastructure. Keep one local API worker and one active village session. Serialize writes, persist before broadcast, and preserve original branch history.
- Shared schema source: `backend/modules/simulation/src/kronos_sim/models.py`. Coordinate changes in the PR, run `make contracts`, and include the generated OpenAPI, TypeScript, and fixture. Never hand-edit generated types.
- Historical seeks and branch switches must replace snapshots atomically, increment animation epoch, and ignore stale transport data.
- No paid AI calls, proprietary assets, or secrets are required for local development.
- Validate with `make check`; regenerate contracts after Python model or API changes. Keep CI contract drift checks passing.
- Avoid unnecessary empty directories and abstraction layers. Document module extension points instead.

See `docs/team-workflows.md` for the four-person workflow. Existing user instructions take precedence over this file.
