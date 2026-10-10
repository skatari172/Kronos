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

1. **Observe:** `kronos_sim/queries.py::observe()` builds what one citizen may see: its own `Citizen` record, derived `role` and `wealth_tier`, bakery bread prices, neighbor names, the runnable action types, its open loans, trade offers waiting for its answer, and its 5 strongest ties. It never includes other citizens' state. The observation route, `/decide`, and the tick loop all use this one builder.
2. **Decide:** `AgentService.decide()` sends the observation to an `LLMProvider` and validates the JSON reply against `AgentAction`. There's a 3 s timeout and 1 retry by default (at most 2). It refuses proposals for a different citizen. Any failure raises `ProviderError`.
3. **Submit:** `Service.submit_agent_action()` takes the lock and checks `branch_id` + `expected_sequence` (409 if stale). It then runs the action through `Engine.apply()`. The AI call happens _before_ the lock, so a slow model never blocks the API.
4. **Outcome:** the result is an `ActionResult` with `action_id`, `status` (`applied` or `rejected`), `sequence`, `event_ids`, and `error` code. Rejections are committed too: an `action_rejected` event, plus a memory such as `Rejected buy: Not enough stock`. Every event from the action carries its `action_id`.

### When citizens think, and what isn't AI

- **AI decisions:** on demand through `POST /api/agents/{id}/decide`. While the clock runs, one citizen (the highest ID) decides every 3rd tick through `AgentService.propose()`. A failed AI call skips strategy for that tick and never stops the simulation.
- **Daily routine, applied by `Engine.tick()` in this order with no AI:**
  1. Bakeries low on wheat buy 2 from the farm; farms and bakeries produce. Farms harvest from the shared wheat stock (seeded roll 3–6 × level, capped by what's left), and adopted inventions multiply output.
  2. Each business pays its own `wage` (default 150 cents) to each employee. A citizen doing time-mode research forfeits the wage to research instead.
  3. Hunger rises by 20. A citizen with no bread buys one from the cheapest bakery (market tax applies), and eats if hunger ≥ 20 (−30 hunger). Citizens walk to a random plot.
  4. A business that missed a wage 3 days in a row goes bankrupt: removed, cash and goods to the owner, staff released.
  5. Daily steps, in this order: the wheat stock regrows (+6, cap 200) → unanswered job applications are resolved (hire if a slot is free and the wage is covered, else reject) → overdue loans default → trade offers older than 2 days expire → research progresses, inventions unlock, unanswered license offers expire → a town vote open 3 days closes and its policy applies → every 7th tick, rent is collected.

### Lots (`Plot`)

- `owner_id` (null = town land anyone may build on), `tenant_id`, `rent` (cents per period), `arrears`, `missed_periods`, `prepaid_periods`. Derived `use`: `business` (a building stands there), `home` (leased, no building) or `empty`.
- Founding or constructing on a lot with an owner needs the owner or the tenant, else `not_owner`.
- `lease_lot`: owned, vacant, unleased lot (`lot_occupied`), not your own, and you can afford one period. `set_rent`: owner only; while leased, at most ±20% (minimum step 100 cents); vacant lots are priced freely. `pay_rent`: clears all arrears, or prepays one period (up to 4). `evict`: owner only, tenant 3+ periods behind; arrears are written off and the tenant's business on the lot closes.

### Economy systems (one line each; rules live in `engine.py`)

- **Jobs:** `apply_job` (unemployed, free slot) → owner `hire` (needs that application) or `reject_application`; unanswered ones resolve next tick. `quit_job` leaves. `GET /api/jobs` lists openings.
- **Trade:** `trade` offers a `give`/`get` bundle (money and goods) to one citizen; only they can `respond_trade`, both sides are rechecked on accept, offers expire after 2 days, max 5 pending per offerer.
- **Loans:** `lend` makes an offer; the borrower must `respond_loan`. Owed = principal + principal × `rate_bps` / 10000 (flat). `repay` partially or fully. Unpaid after `due_tick` → defaulted: lender trust −30, borrower reputation −5.
- **Resources:** `WorldState.resources` holds shared natural stocks (wheat only for now). Employees of a matching business can `gather_resource` (partial gathers allowed).
- **Inventions:** `crop_rotation` (farm wheat ×1.4) and `water_mill` (bakery bread ×2). `research` with money or with time (forfeits wages). The top contributor owns it; licenses are offers the recipient must `respond_license` to the same tick; owners or licensees `adopt_invention` for their business.
- **Relationships:** `interact` (`befriend`, `gift`, `ally`, `argue`, `insult`, `betray`, `mentor`) changes the target's trust and grudge toward the actor (`ally` and `argue` both ways); once per pair per tick; `ally` needs trust ≥ 50. Owners prefer applicants they trust when unanswered applications resolve.
- **Town vote and influence:** influence (basis points) = 50% wealth share + 30% reputation + 20% average trust from others. One `propose_vote` at a time, at most every 10 days; open 3 days; passes if influence-weighted yes > 50% of ballots cast. Policies: `min_wage`, `bread_price_cap` (both enforced on `set_wage`/`set_price` and applied daily) and `market_tax` (share of each purchase, split equally among all citizens; remainder stays with the seller).

### Citizen data the AI layer uses

| Field                                                     | Meaning                                                                                                                                                      |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `money`, `inventory` (`wheat`, `bread`), `hunger` (0–100) | Needs and means                                                                                                                                              |
| `employer_id`, `occupation`                               | Job. `employed` = the employer building exists                                                                                                               |
| `goal_weights`                                            | `wealth` / `influence` / `safety` / `reputation`, integers summing to 100. Changed by `adjust_goals` (±10 per field, then renormalised)                      |
| `personality`, `goals`                                    | Free text for prompts                                                                                                                                        |
| `memories`                                                | The last 8 lines: messages sent and received, and rejected actions                                                                                           |
| `relationships`                                           | Directed ties: `trust` −100…100, `grudge` 0–100, `type` (acquaintance, friend, ally, rival, …). Changed by `interact`, messages (+1 trust) and loan defaults |
| `reputation`                                              | 0–100, default 50. Feeds influence; a loan default costs 5                                                                                                   |
| `research_invention_id`, `research_until_tick`            | Time-mode research in progress (wages are forfeited until then)                                                                                              |
| _derived_ `role`                                          | `business_owner` if the citizen owns a building, otherwise `commoner`                                                                                        |
| _derived_ `wealth_tier`                                   | `rich` ≥ 10,000 cents, `middle` ≥ 3,000, otherwise `poor` (placeholders until the Veloria seed)                                                              |
| _derived_ `influence`                                     | Basis points 0–10000; see "Town vote and influence" above. `GET /api/agents/{id}/influence` shows the breakdown                                              |

### Actions

- **`AgentAction` has 36 types and the engine runs all of them** (`engine.SUPPORTED_ACTIONS`): `buy`, `sell`, `transfer_money`, `set_price`, `produce`, `consume`, `communicate`, `construct_building`, `upgrade_building`, `move_to`, `adjust_goals`, `found_business`, `close_business`, `set_wage`, `hire`, `fire`, `gather_resource`, `apply_job`, `quit_job`, `reject_application`, `lend`, `respond_loan`, `repay`, `trade`, `respond_trade`, `research`, `license_invention`, `respond_license`, `adopt_invention`, `propose_vote`, `vote`, `lease_lot`, `set_rent`, `pay_rent`, `evict`, `interact`.
- **Who may do what:** `GET /api/roles` returns the permission matrix as data. Today the engine enforces ownership per action (`not_owner`); roles themselves aren't checked.
- **Error codes:** `ActionErrorCode` in `models.py` (`insufficient_funds`, `not_owner`, `out_of_stock`, `lot_occupied`, `unknown_entity`, …).

### Providers

- **`LLMProvider` protocol:** `async complete(task, observation) -> str` (JSON). The tasks are `"decision"` → `AgentAction`, `"ask"` → `AskResult`, and `"intervention"` → `PriceIntervention`.
- **`MockProvider` (the default, no key)** is deterministic:
  - **decide:** eat if it has bread and hunger ≥ 40; else buy the cheapest bread if it has none and can afford it; else tell the first neighbor about bread prices.
  - **ask:** a templated summary of its 3 latest events.
  - **intervention:** parses "increase/decrease bread price by N%".
- **`ask` is read-only.** It sees the observation plus the citizen's last 20 events, and an answer citing any other event ID is refused.

### Agent endpoints

| Route                                                                                                                                               | Purpose                                                                                                   |
| --------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `GET /api/agents`, `GET /api/agents/{id}`                                                                                                           | Citizen profiles. Filters: `role`, `employed`, `wealth_tier`                                              |
| `POST /api/agents`                                                                                                                                  | Spawn a citizen (player/setup tool)                                                                       |
| `GET /api/agents/{id}/observation`                                                                                                                  | What the AI sees                                                                                          |
| `POST /api/agents/{id}/actions` (`/validate` for a dry run)                                                                                         | Submit an action → `ActionResult`                                                                         |
| `POST /api/agents/{id}/decide`                                                                                                                      | AI chooses and submits → `{action, result}`                                                               |
| `POST /api/agents/{id}/ask`                                                                                                                         | `{question}` → `{answer, cited_event_ids}`                                                                |
| `PATCH /api/agents/{id}/goals`                                                                                                                      | Bounded goal-weight change                                                                                |
| `GET /api/agents/{id}/history`, `GET /api/actions/{action_id}`                                                                                      | The citizen's events; an earlier action's result                                                          |
| `GET /api/businesses`, `/{id}`; `POST /api/businesses`, `/{id}/close`, `/hire`, `/fire`, `/buy`; `PATCH /{id}/price`, `/wage`                       | Business reads and owner/buyer convenience routes. Body `actor_id` is the acting citizen → `ActionResult` |
| `GET /api/lots` (filters `owner`, `tenant`, `use`), `/{id}`; `POST /api/lots/{id}/lease`, `/pay`, `/evict`; `PATCH /{id}/rent`                      | Lot reads and tenant/owner convenience routes. Body `actor_id` is the acting citizen → `ActionResult`     |
| `GET /api/jobs`; `POST /api/agents/{id}/apply`, `/quit`; `POST /api/businesses/{id}/reject`                                                         | Job openings, applications, quitting, owner rejection                                                     |
| `GET /api/market/prices`, `/prices/history?good=`; `POST /api/market/trade`, `/trade/{offer_id}/respond`; `GET /api/agents/{id}/offers`             | Average prices, price history, trade offers                                                               |
| `GET /api/loans`, `/{id}`; `POST /api/loans`, `/{id}/respond`, `/{id}/repay`                                                                        | Loan offers, acceptance, repayment                                                                        |
| `GET /api/resources`; `POST /api/agents/{id}/gather`                                                                                                | Shared stocks; gathering at the citizen's employer                                                        |
| `GET /api/inventions`, `/{id}`, `/license-offers`; `POST /api/inventions/{id}/research`, `/license`, `/adopt`, `/license-offers/{offer_id}/respond` | Research, licensing, adoption                                                                             |
| `GET /api/agents/{id}/relationships`, `GET /api/relationships/{a}/{b}`; `POST /api/agents/{id}/interact`                                            | Ties and social actions                                                                                   |
| `GET /api/roles`, `GET /api/agents/{id}/influence`, `GET /api/votes?status=`; `POST /api/votes`, `/{id}/ballot`                                     | Permission matrix, influence, town votes                                                                  |

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
