# KRONOS Simulation Engine

The simulation engine owns authoritative village state. Players and agents submit attempted actions; the engine decides whether they succeed when a day advances. The API saves the resulting world and Events through the existing SQLite interface before installing the live state and broadcasting it. The frontend renders that state and uses explicit Events for its feed and activity effects.

This document describes the v1 update. Existing advanced features remain available for compatibility, but are not dependencies of the basic village loop.

## Architecture and important files

```text
Player / Agent Action
  → Service runtime queue
  → Tick: freeze and order attempts
  → Engine: validate → apply / reject → Events
  → Daily rules → deterministic growth
  → Existing SQLite world/event commit
  → Install live state and resolve runtime attempts
  → Full world + Events over WebSocket → Frontend
  → Copied agent observations → next day's queue
```

| File                                                                    | Responsibility                                                                           |
| ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `backend/modules/simulation/src/kronos_sim/engine.py`                   | Pure engine, rule validation, mutations, Events, daily and growth rules                  |
| `backend/modules/simulation/src/kronos_sim/models.py`                   | Existing entity serialization contracts, action/response DTOs, typed JSON Event payloads |
| `backend/modules/simulation/src/kronos_sim/queries.py`                  | Read-only profiles, jobs, bounded citizen observations                                   |
| `backend/modules/simulation/src/kronos_sim/seed.py`                     | Existing village fixture; unchanged by this update                                       |
| `backend/api/src/kronos/service.py`                                     | One session, runtime queue/results, lock, persistence orchestration, broadcast, clock    |
| `backend/api/src/kronos/main.py`                                        | FastAPI setup and clock/provider-task lifecycle                                          |
| `backend/api/src/kronos/routes/user.py`                                 | Player actions, supported price interventions, setup spawning                            |
| `backend/api/src/kronos/routes/backend.py`                              | Tick, play, pause, status and backend action admission                                   |
| `backend/api/src/kronos/routes/world.py`                                | World/citizen/jobs queries and `/ws/world`                                               |
| `backend/api/src/kronos/routes/history.py`                              | Event cursor endpoint, existing history/branch tools, session action lookup              |
| `backend/modules/history/src/kronos_history/store.py`                   | Database-owned SQLite persistence; used without modification                             |
| `backend/modules/agents/src/kronos_agents/provider.py`                  | Validated structured proposals; offline mock provider                                    |
| `frontend/src/api/client.ts`, `frontend/src/stores/world.ts`            | Full-state transport, reconnect/resync, authoritative snapshots                          |
| `frontend/src/world/Village.tsx`                                        | Render entities and plots at backend positions; animation refs are presentation only     |
| `frontend/src/api/format.ts`, `frontend/src/components/EventLedger.tsx` | Present explicit engine Events                                                           |
| `backend/contracts/`                                                    | Generated OpenAPI, TypeScript types and offline fixture                                  |

## Run and verify

From the repository root:

```sh
make install       # first-time dependencies
make backend       # FastAPI on http://localhost:8000; one worker
make frontend      # separate terminal; Vite on http://localhost:5173
make check         # Python/frontend tests, lint, format checks, frontend build
make contracts     # after changing action/Event/API wire contracts
```

The default provider is `KRONOS_LLM_PROVIDER=mock`; no key or paid call is needed. `KRONOS_DATABASE_URL` selects the existing persistence layer's database. `KRONOS_TICK_SECONDS` defaults to 2. Use the repository's `.tools/node/node_modules/.bin/pnpm` as `PNPM` if a global installation uses the wrong Node runtime.

API tests use disposable databases under pytest temporary directories through the existing store. They never need the developer's village database. Do not use `make reset`, `make db-init`, migrations, or schema edits as part of an engine update.

## State, time and the queue

`GET /api/world` returns `{branch_id, tick, sequence, state, events}`. `state` includes `citizens`, `buildings`, `plots`, and pending `job_applications`, plus the existing seed and serialized RNG state. Inventories are nested `{wheat, bread}`, prices are a building's `prices` mapping, and coordinates are `position: {x, z}`. Currency is integer cents: 1 coin = 100 cents. Tick zero is the initial world; each tick advances one simulated day. `sequence` increases for each Event, including the final `tick_completed` marker.

Actions and their `ActionResult` records are runtime-only in this API process. All admission paths—player, agent, backend and convenience routes—use `Service.enqueue` while holding the same lock. Admission checks the requested branch/version and route citizen identity. It does not reserve stock, spend money, advance the world version, save a snapshot, or broadcast. Rule checks occur at execution against the current world.

Each attempt has an opaque session-unique `action_id`, monotonically increasing admission `order`, source, original action and earliest `scheduled_tick`. `GET /api/actions/{action_id}` reports `queued`, `applied` or `rejected` for this running session. Restart discards pending attempts and session result lookup returns 404; committed state and Events remain durable. Read Events for historical outcomes. Do not parse action IDs or use them as stable citizen IDs.

The database owner's existing `actions` table and repository helpers remain untouched, but the v1 service never reads or writes them. Startup still uses the owner's existing table initialization. The inspected development database had no legacy action rows. If deploying over another database with queued legacy rows, drain those with the prior version or coordinate their disposition with the database owner before switching; this version does not replay them.

Existing branches remain compatible: pending runtime attempts belong to their original branch, are not cloned by a fork, and cannot execute twice. Branch activation pauses playback and invalidates in-flight deliberation. Branching is not needed to use the v1 loop.

## What happens on a tick

1. Under the service lock, freeze queued attempts for the active branch. Newly admitted attempts target a later tick.
2. Advance the copied candidate world to the new day. This preserves existing Event/timing conventions rather than moving the clock increment to the end.
3. Process price interventions first, then citizen ID, admission order and action ID. Revalidate each against the evolving candidate. Apply it on an isolated copy, or emit `action_rejected`. A rejected action changes no gameplay values or RNG; later daily rules can still change the world.
4. Resolve applications from earlier days, after the owner's queued hire/reject commands and before wages. Applications submitted during this tick remain pending until the following day. A successful hire withdraws the applicant's other applications. A close or bankruptcy immediately rejects applications to that business and clears its employees.
5. Run existing daily production/input purchases, wages, hunger (+20, capped at 100), consumption of owned bread (−30, floored at zero), seeded movement, bankruptcy and resource regeneration. Preserve existing rent/deadline/research/vote mechanics where already present. Citizen bread buying is an agent proposal, not an automatic purchase.
6. Run deterministic growth, described below. Revalidate the resulting nested state against existing serialization constraints; rule checks preserve unique occupied plots and job capacities.
7. Emit `tick_completed`, even in an empty village. Use the unchanged `HistoryStore.commit(WorldUpdate, expected_sequence)` interface to atomically save world, Events and the existing checkpoint. Do not pass runtime action outcomes into the legacy database action ledger.
8. Only after that commit succeeds, install the live world, resolve session attempts and broadcast. A failed save leaves the world and attempts unchanged and sends no update. The automatic clock pauses with an error; a manual tick can be retried after resolving the failure.
9. Build bounded observations of the committed world. At most one background decision batch runs outside the world lock; up to eight citizens can propose next-day actions. Provider latency or invalid output cannot block daily mechanics. A late proposal uses the next available tick and is validated again there.

## Deterministic growth

Growth lives in `Engine._growth_rules`, separate from provider strategy. It runs once per day in this order. Existing commands/helpers perform founding, spawning, applying, upgrading and leasing.

| Rule         | Trigger                                                                                                     | Outcome                                                                                                                                                            |
| ------------ | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Open land    | A nonempty village's every plot has a building or tenant                                                    | Add exactly two unowned plots; extend the seed's three-column grid, skip occupied coordinates, emit `plot_opened` for each                                         |
| Newcomer     | Day divisible by 3; average post-routine hunger strictly below 50; a business has a free slot               | One traveler arrives with 1,000 cents and applies to the first open business in ID order; emit `citizen_spawned` and `job_applied`                                 |
| Saver founds | A citizen has strictly more than 8,000 cents; an unleased, vacant town plot exists                          | At most one founder across town per day, first in citizen ID order; transfer 5,000 cents into business cash; choose least-common kind, ties farm → bakery → market |
| Busy upgrade | Cash strictly above 10,000 cents after daily mechanics; positive job capacity fully occupied; level below 3 | Spend 2,500 business cents, gain one level and two slots; emit `building_upgraded`                                                                                 |
| Worker home  | Employed, no unbuilt owned/leased home, more than 2,000 cents; affordable owned vacant plot available       | Lease first eligible plot in ID order; emit `lot_leased`; reuse weekly rent collection, without inventing an immediate payment                                     |

Manual `upgrade_building` shares the level/capacity rule, adds two slots, and preserves the existing 2,500-cent charge to the owner's personal money. Both upgrade paths respect the existing 20-slot model limit: a building with more than 18 slots cannot gain another two. New construction/founding honors current minimum wage and bread-price caps.

Land opened this day can be used by this day's founding rule. New businesses produce and pay wages starting the following day. Newcomers' applications can be answered on the next action round or resolved by the following daily fallback. Existing tenants without a building occupy land for expansion purposes.

Three-day starvation departure is deliberately blocked pending the database handoff below. No transient counter or inferred historical counter pretends to provide durable starvation state. The undefined “money keeps moving” redistribution policy remains an open decision; this update adds none.

## Submit actions

First fetch `/api/world` and use its `branch_id` and `sequence` as request context. Replace these sample version values with the current ones. POST each body to `/api/actions`:

```json
{
  "branch_id": "main",
  "expected_sequence": 0,
  "action": {
    "type": "buy",
    "actor_id": "citizen-3",
    "building_id": "bakery",
    "resource": "bread",
    "quantity": 1,
    "max_unit_price": 500,
    "rationale": "I need food."
  }
}
```

```json
{
  "branch_id": "main",
  "expected_sequence": 0,
  "action": {
    "type": "set_price",
    "actor_id": "citizen-1",
    "building_id": "bakery",
    "resource": "bread",
    "price": 650
  }
}
```

```json
{
  "branch_id": "main",
  "expected_sequence": 0,
  "action": {
    "type": "apply_job",
    "actor_id": "citizen-6",
    "building_id": "market"
  }
}
```

Response: an `ActionResult` with `status: "queued"`, `action_id`, `scheduled_tick` and the original action. Advance a day to execute it. Multiple admissions may share the same world version. A later price change can invalidate an earlier buyer's price limit.

Existing vocabulary maps PRD names as follows; no duplicate aliases are needed:

| PRD                                                  | Existing action type                                                                                                    |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| build / upgrade / close                              | `construct_building` (construction cost) or `found_business` (capital transfer) / `upgrade_building` / `close_business` |
| reject / lease / move / talk                         | `reject_application` / `lease_lot` / `move_to` / `communicate`                                                          |
| buy / sell / set_price / set_wage / apply_job / hire | Same names                                                                                                              |

`GET /api/jobs` returns current openings, wages, capacity and pending applicants. Ownership, stock, money, vacant plots, build rights, buyer limits and job slots are checked by the engine. Route caller groups describe trusted local use, not authentication.

## Clock controls

| Method and endpoint          | Body                                                                              |
| ---------------------------- | --------------------------------------------------------------------------------- |
| `GET /api/simulation/status` | None; returns `playing`, `speed`, active `branch_id`, `error`                     |
| `POST /api/simulation/tick`  | `{"branch_id":"main","expected_sequence":0}`                                      |
| `POST /api/simulation/play`  | `{"branch_id":"main","expected_sequence":0,"speed":2}`; supported speed 1, 2 or 4 |
| `POST /api/simulation/pause` | `{}`                                                                              |

Playback uses one process-local clock; manual ticks use the same service/engine path. Play also changes speed; there is no separate speed endpoint. A stale context returns 409. Playback always starts paused after a restart. `POST /api/interventions` accepts version context and narrow text such as `Increase bread price by 40%`; it queues a typed command for the same tick path.

## WebSocket and Events

Connect to `ws://localhost:8000/ws/world`. The initial frame contains the full current world and up to 100 recent Events. Later frames contain full state plus the new committed Events:

```json
{
  "branch_id": "main",
  "tick": 1,
  "sequence": 2,
  "state": {
    "...": "complete WorldState, including citizens, buildings, plots and job_applications"
  },
  "events": [
    {
      "id": "main:2",
      "branch_id": "main",
      "tick": 1,
      "sequence": 2,
      "type": "plot_opened",
      "actor_id": null,
      "rationale": null,
      "causal_refs": [],
      "action_id": null,
      "payload": {
        "entity_id": "plot-main-2",
        "position": { "x": -4, "z": 9 },
        "level": null
      }
    }
  ]
}
```

The abbreviated `state` above is illustrative; real frames always carry every world field. The repository's key is **`state`**, equivalent to the PRD's conceptual `world`. Preserve it across HTTP and WebSocket; no `state_diff` or cosmetic endpoint renaming is needed. Tick HTTP responses additionally include session `action_results` and `rejected_actions`; WebSocket frames use the standard `WorldUpdate` envelope.

Events are meaningful outcomes, not pending intentions. Important types include `transaction_completed`, `price_changed`, `resource_produced`, `resource_consumed`, building lifecycle events, `plot_opened`, `lot_leased`, job application/employment events, citizen lifecycle/movement, `agent_spoke`, `intervention_applied` and `action_rejected`. Purchases use `sender_id`, `recipient_id`, `resource`, `quantity`, and total `amount`; current job resolution uses `outcome: accepted|rejected|withdrawn`. Applied/rejected action Events carry the session action ID. Automatic growth Events have no action ID.

`GET /api/events?after=18&limit=100` returns active-branch Events with sequence **greater than** 18, oldest first; limit is 1–500. Continue using the last returned sequence until caught up. Sequence is branch-local, so reset the cursor on a branch switch. Existing `/api/history/events?branch_id=main&through=...` remains available for historical reads.

The frontend must ingest full state, deduplicate Events by ID and ignore stale sequence/branch frames. It must not infer an authoritative purchase or new land from differences between snapshots. Render plot coordinates from state; derived terrain bounds, animation positions and optional town tier are presentation only. Reconnect resynchronizes through `/api/world`; a historical seek replaces the full snapshot and resets animation state.

## Branching, tracing and comparison

A fork (`POST /api/branches`, `{snapshot_id, name, intervention?}`) copies a snapshot into a new timeline that records its `seed` and optional `intervention`; the intervention is parsed and queued for the fork's next day, so the fork differs from its parent by exactly that change. A fork keeps its parent's sequence, and new entity IDs are `<kind>-<6-digit sequence>` without the branch, so forks of one snapshot that do the same things stay identical. Analyses walk a branch's lineage: its ancestors' history up to each fork point, then its own (`kronos_history/branching.py`).

| Endpoint                                                              | What it gives                                                                                                                                                                                                                                                                          |
| --------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST /api/branches/{id}/run` `{ticks, agents}` · `GET` · `DELETE`    | Advance a non-active branch in the background at full speed; citizens decide with the free utility policy (`agents: "utility"`) or not at all (`"none"`). The active branch is refused (409), and a running branch cannot be activated until stopped. Saves skip the relational mirror |
| `GET /api/branches/{id}/hashes`                                       | `tick_completed.payload.state_hash` per day: SHA-256 of the world without branch ID and sequence. Same seed + same actions → same hashes                                                                                                                                               |
| `GET /api/branches/{id}/checkpoints`                                  | The last snapshot of each simulated year (`KRONOS_TICKS_PER_YEAR`, default 30), for forking                                                                                                                                                                                            |
| `GET /api/branches/compare?ids=a&ids=b&stride=`                       | Per day: average bread price, Gini of citizen money, population, total money, top influence; ancestors' days included                                                                                                                                                                  |
| `GET /api/branches/divergence?a=&b=&depth=`                           | After the shared events, the first differing decision (an event with an `action_id`) and each side's forward cause chain                                                                                                                                                               |
| `GET /api/events/{id}/trace?direction=back\|forward&depth=`           | `back`: `causal_refs`, recursively; `forward`: events citing it; plus events from the same action                                                                                                                                                                                      |
| `GET /api/events?type=&actor=&target=&tick_from=&tick_to=&branch_id=` | Filters on the event cursor; `type` may repeat                                                                                                                                                                                                                                         |

Actions may carry `causal_refs` (up to 5 event IDs on the active branch, else 422); every event the action emits cites them, so an agent can say what it reacted to.

## Invariants and extension points

- Only `Engine` changes world values. Routers and providers submit structured proposals; read helpers do not mutate.
- Money and goods remain nonnegative; hunger stays 0–100; levels stay 1–3. Actions validate first and execute on copies. `Engine.result` revalidates mutated nested models before persistence.
- One building per plot; only town land, owner land or leased land grants construction rights. Only owners set business prices/wages, hire/reject, upgrade or close. Hiring cannot exceed `job_slots`.
- Backend assigns authoritative plot coordinates and stable entity IDs. Iteration order and RNG are deterministic for identical saved state and attempts.
- A save must succeed before live state/outcomes change or clients receive a frame. Do not bypass the existing store or introduce another database/schema.
- Database-owned schema, models, repositories and seed structure require coordination with their owner. Missing fields are handoffs, not permission to edit them during engine work.

To add an action: add its runtime DTO to `AgentAction` in `models.py`, include its name in `SUPPORTED_ACTIONS`, validate and implement it in `Engine._execute` (use `InvalidAction` with an existing stable code), emit a typed Event, and test success and rejection atomicity. Use the existing service queue; world and Events are already saved by `commit`. Coordinate any new persisted entity fields with the database owner. Regenerate contracts and update this guide.

To add an automatic rule: put a small deterministic helper in `engine.py` and invoke it from `_automatic_rules` or `_growth_rules` in an explicit order. Reuse `_execute` or shared engine helpers, emit Events, sort entities by stable IDs and use the saved RNG only for defined randomness. Cover thresholds, repeatability, current-state validation and reference cleanup. Never call the LLM inside those helpers.

## Database dependencies / handoff

No database-owned implementation or persisted entity fields were changed in this update.

1. **Required for departure:** expose and persist `Citizen.starvation_days`, integer ≥ 0 with default 0, across world save/load and snapshots. The current store serializes Citizen in JSON; there is no existing field or equivalent durable counter. The database owner should decide the representation and compatibility. Then the engine can increment at post-routine `hunger == 100 && money == 0`, reset otherwise, and remove at 3. Departure must clear employment, home tenancy, applications and references from existing ownership/advanced systems before emitting removal/employment Events. That behavior and its acceptance test remain blocked; no in-memory substitute was added.
2. **Job status representation:** current `WorldState.job_applications` stores pending records only; resolution removes the record and persists an Event (`accepted` maps to PRD `hired`). If persistent resolved application rows with explicit `pending|hired|rejected` status are required, the database owner must expose that lifecycle. Current gameplay and UI can use pending state plus Events without new fields.
3. **Playback persistence:** `playing` and `speed` live in Service and reset to paused/1 on restart. If required on the persisted World, the database owner must expose these settings. The current clock API works without them.
4. **Event timestamps:** Events currently have tick/sequence but no persisted `created_at`; snapshots have timestamps. If wall-clock Event time is required, the database owner must expose it. This update preserves the existing Event fields.
5. **Legacy action table:** v1 execution has no dependency on action persistence. The owner's store initialization still declares/creates the legacy table. Removing its definition or migrating legacy rows is database-owned work; this update leaves both untouched.

## Intentionally deferred and troubleshooting

Relationships, loans, inventions/licensing, votes/policies, branching/rewind and advanced personality/memories remain existing compatibility features. Do not expand them as core v1 requirements. No causal-graph redesign, state delta protocol, monetary redistribution rule, new persistence subsystem or stored town-growth score is introduced.

| Symptom                             | What to check                                                                                                                                       |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Action is still queued              | Tick/play the clock; confirm it belongs to the active branch and this API session                                                                   |
| Unexpected rejection                | Inspect its `ActionResult` or `action_rejected` Event; current price, stock, funds, ownership and capacity may differ from the original observation |
| HTTP 409                            | Reload `/api/world`, reconsider the command, use the new branch/version                                                                             |
| Action ID returns 404 after restart | Session attempts are transient; committed Events and world survive; resubmit unexecuted work                                                        |
| Application not resolving           | It waits until the day after submission; owner commands run first; no slot or insufficient business cash produces a rejection Event                 |
| No arrivals                         | Check day divisible by 3, average hunger after daily routines below 50, and free job slots                                                          |
| No departures                       | Persisted starvation counter is missing; see handoff above                                                                                          |
| WebSocket not updating              | Confirm backend/VITE_API_URL, `/ws/world`, current branch, and that persistence succeeded; reconnect reloads full state                             |
| World does not persist              | Check `KRONOS_DATABASE_URL`, file permissions and the commit error; do not modify schema to bypass the error                                        |
| Clock stops                         | Inspect `/api/simulation/status.error`; resolve the save/rule failure and use play again; a provider failure alone does not stop daily mechanics    |

Verification covers purchase application/refusal, owner-only actions, occupied plots, job capacity/close cleanup, save-failure rollback, full-state transport, runtime restart semantics, Event cursors, growth boundaries and deterministic replay. Starvation departure cannot be verified until its persisted field is supplied.
