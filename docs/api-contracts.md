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
| `POST /api/interventions`                | Parse and commit supported free text                       |
| `POST /api/actions`                      | Validate and commit a structured engine action             |
| `GET /api/events?after=…&limit=…`        | Active-branch events after a sequence, ascending, paged    |
| `GET /api/jobs`                          | Open job slots                                             |
| `GET /api/history/events?branch_id=…`    | Ordered events; optional `through`, bounded `limit`        |
| `GET /api/history/snapshots?branch_id=…` | Saved checkpoints in sequence order                        |
| `GET /api/history/snapshots/{id}`        | Read historical state, leaving live state unchanged        |
| `GET /api/branches`                      | Branch metadata including parent and source snapshot       |
| `POST /api/branches`                     | Fork `{snapshot_id, name}`; leaves active branch unchanged |
| `POST /api/branches/{id}/activate`       | Pause playback, activate branch, broadcast its world       |
| `GET /api/branches/{id}/world`           | Read branch head                                           |
| `WS /ws/world`                           | Initial snapshot then committed full-state updates         |

The v1 core endpoints are `GET /api/world`, `WS /ws/world`, simulation status/play/pause/tick, `POST /api/actions`, `POST /api/interventions`, `GET /api/events`, and `GET /api/jobs`. New villages, history, branches, and the agent routes are beyond v1 core and already implemented. Poll `GET /api/events?after=<sequence>` to catch up on the ledger; `/api/history/events` remains for branch-scoped queries.

Tick, play, action, and intervention requests include `branch_id` and `expected_sequence`. Stale commands return **409**; reload the current world and reconsider the command. Unsupported/invalid actions and provider output return **422**. Unknown snapshots/branches return **404**.

```json
{
  "branch_id": "main",
  "expected_sequence": 0,
  "text": "Increase bread price by 40%."
}
```

The result contains a structured `modify_price` command and committed world update. Example: a bakery priced at 500 cents becomes 700 cents. The browser indicates all-bakery scope before submission. The API serves a local trusted session, not an authenticated public service. Action `actor_id` is not an authentication mechanism.

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

`main.py` sets up the application, lifecycle, errors, and routers. `dependencies.py` supplies the shared session to route handlers. Existing endpoint URLs and payloads remain compatible, so frontend transport does not need changes. WebSocket routes are documented here but do not appear as Swagger HTTP operations.

These groups describe intended callers; the local prototype has no authentication. A browser may still call backend clock controls. Agent path identity checks prevent accidental mismatched proposals, but do not authenticate the caller. Call origin is not added to persisted events in this change; `actor_id` remains the citizen performing an action.

### Agent tools

| Endpoint                                         | Behavior                                                                       |
| ------------------------------------------------ | ------------------------------------------------------------------------------ |
| `GET /api/agents/{citizen_id}/observation`       | Personal citizen state, public bakery prices, and current branch/tick/sequence |
| `POST /api/agents/{citizen_id}/actions/validate` | Dry-run an action through the engine without saving or broadcasting            |
| `POST /api/agents/{citizen_id}/actions`          | Validate and commit an action whose actor matches the route citizen            |

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

Successful validation returns `valid: true`, the action, branch, and original sequence. Invalid actions return 422. Validation does not reserve the action; execution must still match the current sequence, or it returns 409. Both validation and execution return 404 for an unknown route citizen and 422 if `actor_id` differs from that citizen. The engine additionally checks business ownership, money, stock, and other preconditions.

### Backend automation

`POST /api/backend/actions` accepts the same `ActionRequest` as `/api/actions`. It has no elevated powers or bypasses. All three execution routes call `Service.execute_action`, which takes the mutation lock, checks version/identity, evaluates through `Engine`, saves, and broadcasts. In-process jobs may call that service method directly without HTTP; do not hold `service.lock` when calling it because it acquires the lock itself. The existing clock loop continues to use the engine's daily tick flow.

Each action route accepts the same typed vocabulary: buy, sell, transfer_money, set_price, produce, consume, communicate, construct_building, upgrade_building, and move_to. Select the action's `type` and matching fields in Swagger. Adding a rule belongs in the simulation module, while adding a caller-specific endpoint belongs in the matching route file.
