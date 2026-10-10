# Working on KRONOS

## Mandatory codebase reference

[docs/codebase.md](docs/codebase.md) is the **single source of truth** for repository context, architecture, behavior, ownership, development commands and known issues.

**Every coding agent MUST:**

1. Read `docs/codebase.md` completely before changing this repository, along with applicable agent instructions and relevant source/tests.
2. Update `docs/codebase.md` in the same change set before declaring the task complete, committing, opening a PR or handing off the work. This applies to code, tests, configuration, dependencies, assets, generated contracts and documentation changes.
3. Correct affected sections and remove obsolete facts; a changelog alone is insufficient. Update its latest maintenance record with the change, checks actually performed and unresolved limitations, even when architecture stays the same.
4. Include the documentation update in the completion summary. Do not defer it to another task. **The work is not complete while the codebase reference is stale.**

Keep detailed codebase context in that document rather than duplicating it here. Verify claims against source and tests; document conflicts honestly. Never add secrets or private environment values.

## Working boundaries

- Reuse existing systems and preserve other people's changes. Keep the root simple: `frontend/`, `backend/`, `docs/`, `scripts/` and essential configuration.
- The simulation engine alone authorizes world mutations. Providers propose, the API orchestrates and persists before broadcasting, and the frontend renders snapshots. Preserve stable IDs, integer cents, seeded RNG and branch/sequence checks.
- Respect database ownership and the current no-database-change restriction. Do not change database files, schemas, migrations or persisted models without explicit superseding authorization. Record missing capabilities under `Database dependencies / handoff` in the codebase reference.
- Do not hand-edit generated contracts. For authorized model/API changes, regenerate through `make contracts`. Run appropriate checks; the code-change standard is `make check`. Report existing failures separately and do not claim passing checks that were not run.
- Keep mock/offline development available; no paid provider calls or proprietary assets are required.

Direct user instructions and higher-priority instructions take precedence over repository documentation.
