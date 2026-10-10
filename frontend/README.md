# Frontend

React + Vite + TypeScript + R3F/Drei + Zustand. Start with `make frontend` from the repository root.

- `src/app`: the full-screen stage, HUDs, and simulation session (`useSimulation`). `Dashboard.tsx` keeps the earlier panel layout for reuse.
- `src/world`: the 3D village: town plan and growth tiers, business lifecycle, villagers and their routines, models and animation.
- `src/api`: generated type aliases, transport, and development fixtures.
- `src/stores`: authoritative snapshots and presentation state.
- `src/components`: inspector and ledger views, not mounted in the full-screen layout.

How the village looks, grows, and moves, and how to extend it, is documented in [docs/frontend-world.md](../docs/frontend-world.md). Models and licences are in [public/models/README.md](public/models/README.md).

Offline preview runs independently. Real mutations require the backend. All wire types come from generated OpenAPI. See the root README for commands and limitations.
