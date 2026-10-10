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

## How the AI citizens work

A quick reference so you don't need to read `backend/modules/agents/` or the engine to follow the flow. Money is in integer cents throughout.

### The decision cycle

```
world state ──observe()──▶ AgentObservation ──AgentService.decide()──▶ LLMProvider ──JSON──▶ AgentAction
                                                                                                │
          memory + action_rejected event ◀── rejected ── Engine.apply() ◀── Service.submit_agent_action()
          events + new state (saved, then broadcast) ◀── applied ──┘
```

1. **Observe:** `kronos_sim/queries.py::observe()` builds what one citizen may see: its own `Citizen` record, derived `role` and `wealth_tier`, bakery bread prices, neighbor names, and the runnable action types. It never includes other citizens' state. The observation route, `/decide`, and the tick loop all use this one builder.
2. **Decide:** `AgentService.decide()` sends the observation to an `LLMProvider` and validates the JSON reply against `AgentAction`. There's a 3 s timeout and 1 retry by default (at most 2). It refuses proposals for a different citizen. Any failure raises `ProviderError`.
3. **Submit:** `Service.submit_agent_action()` takes the lock and checks `branch_id` + `expected_sequence` (409 if stale). It then runs the action through `Engine.apply()`. The AI call happens _before_ the lock, so a slow model never blocks the API.
4. **Outcome:** the result is an `ActionResult` with `action_id`, `status` (`applied` or `rejected`), `sequence`, `event_ids`, and `error` code. Rejections are committed too: an `action_rejected` event, plus a memory such as `Rejected buy: Not enough stock`. Every event from the action carries its `action_id`.

### When citizens think, and what isn't AI

- **AI decisions:** on demand through `POST /api/agents/{id}/decide`. While the clock runs, one citizen (the highest ID) decides every 3rd tick through `AgentService.propose()`. A failed AI call skips strategy for that tick and never stops the simulation.
- **Daily routine, applied by the engine on every tick with no AI:**
  - Farms and bakeries produce, and bakeries restock wheat from the farm.
  - Each business pays its own `wage` (default 150 cents) to each employee. A business that misses a wage 3 days in a row goes bankrupt: it is removed, its cash and goods go to the owner, and its staff are released.
  - Hunger rises by 20.
  - A citizen with no bread buys one from the cheapest bakery, and eats if hunger ≥ 20 (−30 hunger).
  - Citizens walk to a random plot.

### Citizen data the AI layer uses

| Field                                                     | Meaning                                                                                                                                 |
| --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `money`, `inventory` (`wheat`, `bread`), `hunger` (0–100) | Needs and means                                                                                                                         |
| `employer_id`, `occupation`                               | Job. `employed` = the employer building exists                                                                                          |
| `goal_weights`                                            | `wealth` / `influence` / `safety` / `reputation`, integers summing to 100. Changed by `adjust_goals` (±10 per field, then renormalised) |
| `personality`, `goals`                                    | Free text for prompts                                                                                                                   |
| `memories`                                                | The last 8 lines: messages sent and received, and rejected actions                                                                      |
| `relationships`                                           | `trust` −100…100 toward others. Each message received raises it by 1                                                                    |
| _derived_ `role`                                          | `business_owner` if the citizen owns a building, otherwise `commoner`                                                                   |
| _derived_ `wealth_tier`                                   | `rich` ≥ 10,000 cents, `middle` ≥ 3,000, otherwise `poor` (placeholders until the Veloria seed)                                         |

### Actions

- **`AgentAction` has 33 types.** The engine runs the 16 in `engine.SUPPORTED_ACTIONS`: `buy`, `sell`, `transfer_money`, `set_price`, `produce`, `consume`, `communicate`, `construct_building`, `upgrade_building`, `move_to`, `adjust_goals`, `found_business`, `close_business`, `set_wage`, `hire`, `fire`.
- **The other 17 are schemas only.** These are the planned job applications, trade, lots, loans, inventions and votes actions. They are rejected with `not_supported`.
- **Error codes:** `ActionErrorCode` in `models.py` (`insufficient_funds`, `not_owner`, `out_of_stock`, `lot_occupied`, `unknown_entity`, …).

### Providers

- **`LLMProvider` protocol:** `async complete(task, observation) -> str` (JSON). The tasks are `"decision"` → `AgentAction`, `"ask"` → `AskResult`, and `"intervention"` → `PriceIntervention`.
- **`MockProvider` (the default, no key)** is deterministic:
  - **decide:** eat if it has bread and hunger ≥ 40; else buy the cheapest bread if it has none and can afford it; else tell the first neighbor about bread prices.
  - **ask:** a templated summary of its 3 latest events.
  - **intervention:** parses "increase/decrease bread price by N%".
- **`ask` is read-only.** It sees the observation plus the citizen's last 20 events, and an answer citing any other event ID is refused.

### Agent endpoints

| Route                                                                                                                         | Purpose                                                                                                   |
| ----------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `GET /api/agents`, `GET /api/agents/{id}`                                                                                     | Citizen profiles. Filters: `role`, `employed`, `wealth_tier`                                              |
| `POST /api/agents`                                                                                                            | Spawn a citizen (player/setup tool)                                                                       |
| `GET /api/agents/{id}/observation`                                                                                            | What the AI sees                                                                                          |
| `POST /api/agents/{id}/actions` (`/validate` for a dry run)                                                                   | Submit an action → `ActionResult`                                                                         |
| `POST /api/agents/{id}/decide`                                                                                                | AI chooses and submits → `{action, result}`                                                               |
| `POST /api/agents/{id}/ask`                                                                                                   | `{question}` → `{answer, cited_event_ids}`                                                                |
| `PATCH /api/agents/{id}/goals`                                                                                                | Bounded goal-weight change                                                                                |
| `GET /api/agents/{id}/history`, `GET /api/actions/{action_id}`                                                                | The citizen's events; an earlier action's result                                                          |
| `GET /api/businesses`, `/{id}`; `POST /api/businesses`, `/{id}/close`, `/hire`, `/fire`, `/buy`; `PATCH /{id}/price`, `/wage` | Business reads and owner/buyer convenience routes. Body `actor_id` is the acting citizen → `ActionResult` |

### Extending

- **New provider:**
  1. Implement `LLMProvider.complete`.
  2. Select it from `KRONOS_LLM_PROVIDER` in `Service.__init__` (only `mock` is accepted today).
  3. Keep the mock as the default and keep CI offline.
- **New action:**
  1. Add the model to `AgentAction` in `models.py`.
  2. Add an `elif` in `Engine._execute` that validates first, raising `InvalidAction(code, message)`.
  3. Add its type to `SUPPORTED_ACTIONS`, add tests, then run `make contracts`.
- **Richer observations:** extend `AgentObservation` and `observe()` only, so the route, `/decide` and the tick loop stay in sync.

See `docs/team-workflows.md` for the four-person workflow. Existing user instructions take precedence over this file.
