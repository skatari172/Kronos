# Bootstrap verification

Validated locally with Python 3.13 and Node 22. CI targets Python 3.12 and Node 22.

- `make install`: passed against frozen uv and pnpm lockfiles, including the local tool fallback.
- `make check`: 24 pytest tests and 5 Vitest tests passed; Ruff, ESLint, formatting, TypeScript, and Vite production build passed.
- `make contracts`: regeneration produced identical artifacts, with no schema/fixture/type drift.
- Chromium live smoke: 3D canvas, entity inspection, +40% intervention, next tick, construction, historical seek, fork, branch switch, play/pause, and mobile layout passed with no JavaScript runtime errors.
- Chromium offline smoke: automatic fixture fallback, disabled real mutations, all six visual events, and inspection passed with no runtime errors.

Browser checks used an isolated temporary SQLite database and a temporary Playwright installation. The repository's automated suite is pytest/Vitest; browser smoke scripts were verification tooling, not added to CI. GitHub Actions is configured but has not been run on a remote repository.

Non-blocking tool output: Starlette warns that its httpx test-client bridge is deprecated; the pinned bridge still passes API/WebSocket tests. Vite reports a large Three.js bundle (about 1.17 MB before gzip). Both are follow-up maintenance items, not suppressed warnings.
