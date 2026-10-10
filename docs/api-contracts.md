# API contracts

Canonical Pydantic models live in `backend/modules/simulation/src/kronos_sim/models.py`. `make contracts` creates `backend/contracts/schemas/openapi.json`, the seed fixture, and `backend/contracts/generated/api.ts`. Frontend types are aliases of generated schemas, never a second handwritten definition. Serialization defaults are marked required for accurate response types.

| Endpoint                                 | Behavior                                                   |
| ---------------------------------------- | ---------------------------------------------------------- |
| `GET /health`                            | Health and provider kind                                   |
| `GET /api/world`                         | Active state plus up to 100 recent branch events           |
| `POST /api/simulations`                  | Persist a new independent village; return branch metadata  |
| `POST /api/simulation/tick`              | Advance one day                                            |
| `POST /api/simulation/play`              | Start shared loop at speed 1, 2, or 4                      |
| `POST /api/simulation/pause`             | Pause shared loop                                          |
| `GET /api/simulation/status`             | Playback state and any loop failure                        |
| `POST /api/interventions`                | Parse and queue supported free text                        |
| `POST /api/actions`                      | Queue a structured engine action                           |
| `GET /api/history/events?branch_id=…`    | Ordered events; optional `through`, bounded `limit`        |
| `GET /api/history/snapshots?branch_id=…` | Saved checkpoints in sequence order                        |
| `GET /api/history/snapshots/{id}`        | Read historical state, leaving live state unchanged        |
| `GET /api/branches`                      | Branch metadata including parent and source snapshot       |
| `POST /api/branches`                     | Fork `{snapshot_id, name}`; leaves active branch unchanged |
| `POST /api/branches/{id}/activate`       | Pause playback, activate branch, broadcast its world       |
| `GET /api/branches/{id}/world`           | Read branch head                                           |
| `WS /ws/world`                           | Initial snapshot then committed full-state updates         |

Tick, play, action, and intervention requests include `branch_id` and `expected_sequence`. Stale commands return **409**; reload the current world and reconsider the command. Malformed requests, dry-run rule failures, and invalid provider output return **422**. Gameplay rule failures become session `rejected` action results and durable Events during execution. Unknown snapshots/branches return **404**.

```json
{
  "branch_id": "main",
  "expected_sequence": 0,
  "text": "Increase bread price by 40%."
}
```

The result contains a structured `modify_price` command and a queued `result` (`ActionResult`). Advance the clock to execute it. Example: a bakery priced at 500 cents becomes 700 cents. The browser indicates all-bakery scope before submission. The API serves a local trusted session, not an authenticated public service. Action `actor_id` is not an authentication mechanism.

Create a new world with `POST /api/simulations`, then activate the returned branch ID. State saves automatically on each commit; no misleading save endpoint is needed. Historical restore is read-only; continuing from the past requires a fork.

## Route files and Swagger groups

Run `make backend` and open **http://localhost:8000/docs**. Operations are grouped by intended caller and responsibility:

| Swagger group | Route file under `backend/api/src/kronos/routes/` | Tools                                                                       |
| ------------- | ------------------------------------------------- | --------------------------------------------------------------------------- |
| User tools    | `user.py`                                         | `POST /api/interventions`, `POST /api/actions`                              |
| Agent tools   | `agents.py`                                       | Citizen observation, proposal validation, action submission                 |
| Backend tools | `backend.py`                                      | Health, simulation status/tick/play/pause, new villages, automation actions |
| World         | `world.py`                                        | `GET /api/world`, plus the WebSocket handler at `/ws/world`                 |
| History       | `history.py`                                      | Event queries, checkpoints, forks, branch activation and state              |

`main.py` sets up the application, lifecycle, errors, and routers. `dependencies.py` supplies the shared session to route handlers. Endpoint URLs and request payloads are preserved. Action responses now acknowledge queuing; gameplay state is delivered after the next committed tick. WebSocket routes are documented here but do not appear as Swagger HTTP operations.

These groups describe intended callers; the local prototype has no authentication. A browser may still call backend clock controls. Agent path identity checks prevent accidental mismatched proposals, but do not authenticate the caller. Call origin is recorded on the runtime attempt as `source`; `actor_id` remains the citizen performing an action.

### Agent tools

| Endpoint                                         | Behavior                                                                       |
| ------------------------------------------------ | ------------------------------------------------------------------------------ |
| `GET /api/agents/{citizen_id}/observation`       | Personal citizen state, public bakery prices, and current branch/tick/sequence |
| `POST /api/agents/{citizen_id}/actions/validate` | Dry-run an action through the engine without saving or broadcasting            |
| `POST /api/agents/{citizen_id}/actions`          | Queue an action whose actor matches the route citizen                          |

Example: submit the following to `/api/agents/citizen-1/actions/validate`, then to `/api/agents/citizen-1/actions` to execute it. Replace the branch/version with those from the observation:

```json
{
  "branch_id": "main",
  "expected_sequence": 0,
  "action": {
    "type": "set_price",
    "actor_id": "citizen-1",
    "building_id": "bakery",
    "resource": "bread",
    "price": 650,
    "rationale": "Try a smaller margin to make bread more affordable."
  }
}
```

Successful dry-run validation returns `valid: true`, the action, branch, and original sequence. It reserves nothing. Submission checks request version and route identity, then returns an `ActionResult` with `status: "queued"`, original `action`, `source`, stable `action_id`, admission `order`, and `scheduled_tick`. Submission does not advance the world sequence, so several proposals may share one observation version. Unknown route citizens return 404; actor/path mismatches return 422.

`GET /api/actions/{action_id}` reads a queued/applied/rejected attempt in this API session. Attempts disappear on restart; committed outcomes remain in Events, available via `GET /api/events?after=<sequence>&limit=100`. After execution it includes the resulting tick/world sequence, associated event IDs, and any stable rejection code/message. Rejected gameplay actions are HTTP 200 outcomes, including through player and backend routes. Events and full world state arrive together over the existing WebSocket envelope. `POST /api/simulation/tick` also returns `action_results` and the existing `rejected_actions` summary.

### Backend automation

`POST /api/backend/actions` and `/api/actions` accept the same `ActionRequest`; all action and convenience endpoints enter `Service.execute_action` / `submit_agent_action`. They confer no elevated rights. The engine performs current ownership, cash, stock, timing, and precondition checks when the next tick drains the queue. A player intervention uses that same queue with a typed `modify_price` command.

`POST /api/agents/{id}/decide` observes, awaits the provider outside the world lock, and queues its structured output for the next available tick. A branch activation during deliberation returns 409. The automatic post-tick strategy loop uses the same runtime queue. `GET /observation` includes up to eight relevant recent committed events; other citizens' money and private goals remain hidden.

The vocabulary preserves the existing 36 engine actions covering trade, production, business ownership, jobs, goals, relationships, lots/rent, loans, research, licenses/adoption, and votes. Select a type and its fields in Swagger; add new rules in the simulation module and regenerate contracts.

### Existing databases

This update does not change database-owned schema, entity fields or persistence helpers. The owner's existing initialization still includes a legacy `actions` table, but the v1 service does not use it. Runtime submissions do not survive restarts; committed world state, Events and checkpoints do. See [Simulation engine](simulation-engine.md#database-dependencies--handoff) for starvation state and other database-owner dependencies. Existing legacy queued rows in other installations need coordinated disposition before upgrade; the inspected development ledger was empty.
