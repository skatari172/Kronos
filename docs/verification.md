# Simulation engine verification

The queued engine implementation was verified incrementally: the first Phase 1 purchase and rejection tests passed before agent-loop and later-system changes.

- `make check` (with the repository's local pnpm): 182 Python tests and 7 Vitest tests pass, along with Ruff, ESLint, formatting, TypeScript, and the Vite production build.
- `make contracts`: regenerated OpenAPI, TypeScript, and seed fixture; regeneration is deterministic.
- Core checks cover no mutation on enqueue/rejection, stable competing-action order, current-state validation, durable outcomes, restart recovery, branch isolation, no repeated application, and rollback/no broadcast after a failed save.
- Delayed provider checks prove another tick and a concurrent submission complete while deliberation waits. One bounded decision task feeds the same queue; shutdown cancels it before closing persistence.
- A real-rules integration test covers job application/owner response, invention funding/licensing/adoption, loan offer/acceptance/repayment, vote closure/minimum wages, and periodic rent. Time research contributes for exactly its requested number of days.
- Browser smoke used a separate SQLite database and ports. Queued price change stayed at 5.00 until the next tick, then became 7.00. Purchases and refusals appeared with names, construction changed the scene after execution, checkpoint seeking restored 5.00, and switching from a fork recovered the original 7.00 world. Browser console error log was empty. An empty cheap bakery was excluded from mock buying choices after the smoke exposed that edge case.
- The already-running local backend added the new empty action table on reload. Every original row in the tracked local database was compared with the original Git version and remained unchanged.

The bundled provider remains a deterministic mock behind the existing provider interface. Run one backend worker. Earlier immediate-action results cannot be backfilled with missing original proposal data; their saved events and snapshots remain available.

## Earlier bootstrap checks

Validated locally with Python 3.13 and Node 22. CI targets Python 3.12 and Node 22.

- `make install`: passed against frozen uv and pnpm lockfiles, including the local tool fallback.
- `make check`: 24 pytest tests and 5 Vitest tests passed; Ruff, ESLint, formatting, TypeScript, and Vite production build passed.
- `make contracts`: regeneration produced identical artifacts, with no schema/fixture/type drift.
- Chromium live smoke: 3D canvas, entity inspection, +40% intervention, next tick, construction, historical seek, fork, branch switch, play/pause, and mobile layout passed with no JavaScript runtime errors.
- Chromium offline smoke: automatic fixture fallback, disabled real mutations, all six visual events, and inspection passed with no runtime errors.

Browser checks used an isolated temporary SQLite database and a temporary Playwright installation. The repository's automated suite is pytest/Vitest; browser smoke scripts were verification tooling, not added to CI. GitHub Actions is configured but has not been run on a remote repository.

Non-blocking tool output: Starlette warns that its httpx test-client bridge is deprecated; the pinned bridge still passes API/WebSocket tests. Vite reports a large Three.js bundle (about 1.17 MB before gzip). Both are follow-up maintenance items, not suppressed warnings.
