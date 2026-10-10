# Frontend

React + Vite + TypeScript + R3F/Drei + Zustand. Start with `make frontend` from the repository root. `src/app` owns the dashboard; `src/world` owns geometry and ref-based animation; `src/api` owns generated type aliases, transport, and development fixtures; `src/stores` owns authoritative and presentation state; `src/components` owns inspector and ledger views.

Offline preview runs independently. Real mutations require the backend. All wire types come from generated OpenAPI. See the root README for commands and limitations.
