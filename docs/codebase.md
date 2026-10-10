# KRONOS Codebase

**This is the single source of truth for codebase context and repository working rules. Every coding agent must read it before changing this repository and update it before declaring its work complete.** The root `AGENTS.md` directs agents here. This requirement applies to implementation, fixes, refactors, tests, configuration, dependencies, assets, generated contracts, and documentation changes.

Last reviewed: **2026-10-10**, against code commit **`446bcff`** (`Merge branch 'main' into viggy`). This describes the inspected checkout, including its integration problems; it does not claim that all present code works.

## 1. Mandatory workflow for every coding agent

1. Read this document and applicable `AGENTS.md` files. Inspect `git status`, the relevant source, its callers, tests, and contracts before editing. Preserve other people's work.
2. Follow the current user's scope and ownership constraints. Prefer extending an existing system over creating another engine, queue, world model, event taxonomy, store, or WebSocket manager.
3. Keep authoritative mutations in the simulation engine. Respect the database boundary described below. Never quietly make frontend animation or provider output authoritative.
4. Implement the requested change and run appropriate checks. For code changes the repository standard is `make check`; after wire-contract changes also run `make contracts` and inspect the generated diff. If existing failures prevent a check, report the exact failure and distinguish it from your changes.
5. **Before finishing, update this file in the same change set. This is mandatory, not a follow-up task.** Rewrite the affected architecture, behavior, paths, contracts, commands, configuration, defaults, dependencies, limitations, or troubleshooting sections. Remove facts your change made obsolete. Do not just append a changelog while leaving the body incorrect.
6. Update “Latest maintenance record” with the scope, validation actually performed, and outstanding issues. Even when a change does not alter architecture, record what changed and how it was checked. Do not copy secrets, private environment values, transient process IDs, or large command logs into this file.
7. Check documentation links, names and examples against the actual code. Include the documentation update with any commit/PR/handoff, and mention it in the completion summary. **A change is not complete until `docs/codebase.md` is current.** If work is interrupted, document the incomplete state rather than claiming completion.

This file is the canonical explanation of the repository. Other documentation is supporting detail or historical design. If a supporting document disagrees, use this file's current context and inspect the code. Executable behavior is established by source and tests: a written claim does not fix an implementation mismatch. Record discrepancies here and resolve them within the authorized task. Direct user instructions and higher-priority runtime instructions take precedence over repository documentation.

## 2. Product, scope and ownership

KRONOS is a local hackathon village simulation: citizens, businesses, plots, food, work, prices, player interventions, agent proposals, and a 3D village. One simulation tick represents one day. The frontend calls the settlement Oakhaven and presents derived Hamlet → Village → Town → City tiers.

The small core is World, Citizen, Building, Plot, JobApplication and Event. The repository also contains relationships, memories, loans, citizen trade offers, shared resources, inventions/licensing, votes/policies, rent details, snapshots, branching and rewind. These are existing systems, not a reason to expand every task into all of them.

| Area               | Location                                        | Responsibility                                                                              |
| ------------------ | ----------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Frontend / 3D      | `frontend/`                                     | Render authoritative snapshots; controls, transport and presentation                        |
| Simulation         | `backend/modules/simulation/`                   | Engine, rule validation, canonical Python contracts and read-only queries                   |
| Agents / AI        | `backend/modules/agents/`                       | Observations, structured decisions, provider adapters, deterministic fallback               |
| API                | `backend/api/`                                  | One shared service, routes, clock, queue, locking, persistence orchestration and broadcasts |
| Database / history | `backend/modules/history/`, `backend/database/` | Separately owned persistence, SQLite tables, checkpoints, event queries and branches        |
| Contracts          | `backend/contracts/`                            | Generated wire schemas, TypeScript types and offline fixture                                |

Keep the root organized around `frontend/`, `backend/`, `docs/`, `scripts/` and essential configuration. Do not recreate a competing top-level apps/packages structure. Coordinate cross-area changes and describe contract compatibility in PRs. A routine tool addition to an existing router does not require another application entry point.

## 3. Current checkout health — read before running

**The reviewed checkout has unresolved integration errors. Backend startup and frontend compilation are currently blocked.** Earlier passing test counts in older documents describe earlier code and are not a current verification result.

| Confirmed problem                  | Evidence / consequence                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Python engine syntax               | Static parsing of `backend/modules/simulation/src/kronos_sim/engine.py` fails at line 1397: an `if` at 1396 has no body. Additional malformed merged code is visible in `_spawn` and the earlier `intervene`; the parser stops at the first error.                                                                                                                                                                                         |
| Python service syntax              | Static parsing of `backend/api/src/kronos/service.py` fails at line 231 with unexpected indentation after an earlier return.                                                                                                                                                                                                                                                                                                               |
| Frontend entry component syntax    | TypeScript reports unmatched JSX and unexpected tokens in `frontend/src/app/App.tsx`; it also contains duplicated imports and older control logic mixed with `useSimulation`.                                                                                                                                                                                                                                                              |
| Generated contracts invalid        | TypeScript reports a missing closing brace in `backend/contracts/generated/api.ts` and malformed JSON in `backend/contracts/generated/initial-world.json`. These must eventually be regenerated from repaired Python/API sources, not manually patched.                                                                                                                                                                                    |
| Competing provider/tick flows      | `AgentService` defines `propose` twice. The later signature takes only `world`, while `Service._deliberate` passes `(snapshot, events)`. `Service.loop` contains both a queued `tick()` path and an `_advance()` path; `stop_decisions` includes leftover tick logic referencing `request`. Reconcile these before assuming one day per clock cycle.                                                                                       |
| Competing growth/intervention code | Engine contains both `_grow` and `_growth_rules`, duplicate `_open_land`/`_welcome_newcomer`/`intervene` methods, and two `PlotOpened` classes in `models.py`. Later class methods override earlier definitions once the file can parse. The queue handles only `PriceIntervention`, despite a wider `Intervention` union. `InterventionResult` mixes queued `result` and immediate `update` fields, while Service supplies only `result`. |
| Duplicate event endpoint           | `routes/history.py` registers `GET /api/events` twice: a list response and an `EventPage` response. Runtime route matching and generated OpenAPI can disagree until this is reconciled.                                                                                                                                                                                                                                                    |

These are recorded existing issues, not fixes made by the documentation task. Line numbers are observations, not permanent identifiers. A repair must reconcile the intended single flow, preserve ownership and compatibility, regenerate contracts, run checks, and update this section. Do not delete a failing test merely to hide a competing implementation.

## 4. Toolchain and repository map

Backend: Python **3.12+**, FastAPI, Pydantic 2 / pydantic-settings, SQLAlchemy 2 and SQLite; uv manages one root environment. Optional Anthropic SDK support is an extra, not required by the mock. Frontend: **Node 22.12+**, pnpm 10, React 19, TypeScript 5.9, Vite 7, Three.js, React Three Fiber, Drei, Zustand, Lucide and Tailwind 4. Treat these as declared toolchain/dependency families; use the committed lockfiles for exact versions.

```text
AGENTS.md                         Mandatory entry point for coding agents
README.md                         Quick start and links; supporting overview
Makefile                          Shared install/run/check/export/reset commands
pyproject.toml / uv.lock           Python dependencies, pytest paths and Ruff settings
package.json / pnpm-lock.yaml      Node workspace tooling and locked dependencies
pnpm-workspace.yaml                Frontend workspace
.env.example                      Public configuration examples; never commit real keys
.github/workflows/ci.yml           Tests, lint, build and generated-contract drift
backend/
  api/src/kronos/                  FastAPI application, configuration, shared service, routes
  api/tests/                      Route, queue, transport and integration tests
  modules/simulation/src/kronos_sim/  Authoritative engine, models, queries, seed
  modules/agents/src/kronos_agents/   Providers, prompts and fallback policy
  modules/history/src/kronos_history/ SQLite history store
  modules/*/tests/                Independently scoped Python tests
  database/                       Tracked local SQLite file and database-owner guidance
  contracts/schemas/openapi.json  Generated OpenAPI
  contracts/generated/api.ts      Generated TypeScript
  contracts/generated/initial-world.json  Generated offline world
frontend/
  src/app/                        Stage/HUD, simulation hook, earlier dashboard, styles
  src/api/                        Transport, generated aliases, Event formatting, fixtures
  src/stores/                     Authoritative snapshots and separate presentation selection
  src/world/                      3D scene, terrain, models, routines, growth presentation
  src/components/                 Inspector and Event ledger components
  public/models/                  Committed KayKit assets and licenses
scripts/                          Bootstrap, backend launcher, contract exporter, DB tools
docs/                             This reference plus supporting guides/design history
world_seed.json                   Additional root data artifact; not loaded by seed.py
```

Python imports are `kronos`, `kronos_sim`, `kronos_agents` and `kronos_history`. pytest config, backend launcher and contract exporter add the modules' `src/` directories to import paths. There is no separate independently installed Python package per module. `.tools/`, `.venv/`, `.cache/`, `node_modules/` and frontend build outputs are local tool/build state, not new application subsystems.

## 5. Architecture and authority

The architecture that must remain unified is:

```text
Player / provider
  → structured action / intervention
  → Service admission + runtime queue
  → Engine.tick: freeze, order, validate, apply or reject
  → daily rules + deterministic growth + typed Events
  → existing SQLite world/Event/checkpoint transaction
  → install live state and resolve runtime attempts
  → full WorldUpdate over WebSocket
  → frontend snapshot + Event presentation
  → copied citizen observation → later proposal
```

This is the queued path currently present in `Service.tick`; the competing code listed in section 3 prevents claiming that it is integrated successfully.

- **Engine owns mutations.** It copies input state; `apply` validates and executes a typed action on a candidate. `reject` emits a refusal. `tick` returns candidate state, Events and action outcomes. Engine imports no database, HTTP or rendering subsystem.
- **Service owns orchestration.** Its `asyncio.Lock` serializes admission, active world changes and commits. Provider I/O happens outside that lock. One shared local service, branch, playback speed and client set serve all tabs. Use one API process/worker.
- **Commit before publication.** `Service.commit` passes a plain `WorldUpdate` to the existing `HistoryStore.commit`, installs the candidate and runtime outcomes after save succeeds, then broadcasts. A failed save must leave live gameplay state/attempts unchanged and send no success frame.
- **Actions are intentions.** HTTP submission does not authorize a purchase to bypass the tick. Admission validates branch/version and route identity; execution rechecks funds, inventory, ownership, capacity and timing against the latest candidate state.
- **Frontend state is a snapshot.** Refs, local errands, models, camera, selection, tier and animations are presentation. They must never determine economic outcomes or authoritative plot coordinates.
- **Providers propose only.** Schema-valid output can still be rejected by engine rules. A model has no direct state or database access. The local API's caller groups and `actor_id` are not authentication.

## 6. Contracts, entities and invariants

`backend/modules/simulation/src/kronos_sim/models.py` is the canonical Python wire/entity definition. It uses typed Pydantic models with extra fields forbidden. Changes to persisted entity definitions are also data-contract changes and require the database owner's coordination. `frontend/src/api/types.ts` aliases generated types; it must not become a second world schema.

| Entity            | Main fields and meaning                                                                                                                                                                                                                 |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `WorldState`      | `schema_version`, `branch_id`, `tick`, `sequence`, `seed`, serialized `rng_state`; keyed dictionaries of citizens, buildings, plots, job applications and existing advanced entities/policies                                           |
| `Citizen`         | Stable ID/name, occupation/employer, backend `position`, money, hunger, nested inventory; goal weights, relationships, reputation, research; current model also has `destitute_days`, recent memories, `memory_summary`, `memory_tally` |
| `Building`        | Farm/bakery/market; owner, plot, position, cash, level 1–3, inventory, price mapping, wage, job capacity, missed-payroll counter                                                                                                        |
| `Plot`            | Position, nullable owner/tenant, rent, arrears, missed/prepaid periods; owner null means town land                                                                                                                                      |
| `JobApplication`  | Citizen/business, submission tick/sequence, current explicit `pending                                                                                                                                                                   | hired | rejected`status; current`_resolve` retains resolved records |
| `SimulationEvent` | Typed discriminated outcome: branch-local ID, tick/sequence, actor, rationale, action link, causal references and typed JSON payload                                                                                                    |
| `ActionResult`    | Session attempt ID, original action, source, admission order, scheduled day, queued/applied/rejected status, Event IDs and rejection details                                                                                            |

Money is **integer cents** throughout (100 cents = one coin). Wheat and bread inventories and balances cannot be negative. Hunger stays 0–100. Citizens and buildings retain stable IDs. Seeded randomness lives in the saved RNG state; use sorted entity order and the engine RNG for defined random mechanics, never provider timing or unseeded calls for authoritative effects.

One active building per plot. Construction requires town land, owned land or rented land. Owner-only actions include setting price/wage, hiring/rejecting applicants, upgrading and closing. Hiring respects `job_slots`. Closing releases employees and resolves pending applications. Backend owns plot positions. `Engine.result` revalidates nested state and includes duplicate-plot and job-capacity checks.

Important current source differences from older guides: `destitute_days` **now exists**, as do retained JobApplication statuses and memory summary fields. Do not repeat the older claim that those fields are absent. Their runtime integration remains subject to section 3. `playing` and `speed` remain Service settings, not fields on the persisted `WorldState`; Event does not currently declare `created_at`.

Citizen defaults include practical personality, reputation 50 and four equal goal weights (`wealth`, `influence`, `safety`, `reputation`). Weights total 100; requested adjustments are bounded to ±10 percentage points per goal. `queries.profile` derives `business_owner` from building ownership and employment from a valid employer; lot ownership is separate. Wealth tiers use personal money: rich ≥10,000 cents, middle ≥3,000, otherwise poor. Influence uses integer basis points: 50% of wealth share (personal money plus owned business cash), 30% normalized reputation and 20% average incoming trust. Unknown relationships count as neutral. Open vote tallies use current influence; closed votes retain their recorded weights. `queries.roles` publishes permissions, but engine action-specific ownership checks remain the authority.

## 7. Engine, daily mechanics and growth

Important files: `engine.py` (rules), `models.py` (contracts), `queries.py` (read-only projections/observations), `seed.py` (initial world). All are under `backend/modules/simulation/src/kronos_sim/`.

The queued `Engine.tick` increments candidate tick, freezes eligible attempts, orders price interventions first, then actor ID, runtime admission order and action ID, and ignores wrong-branch, already-resolved, duplicate or future attempts. Each action executes against the evolving candidate. It emits `action_rejected` for `InvalidAction` and collects outcomes, runs daily/growth rules, then emits `tick_completed` even for an empty day. The final world sequence is attached to each resolved attempt.

The daily path present in `_automatic_rules` resolves due job applications before production/wages, then performs farm/bakery input purchases and production, wages, hunger, owned-bread consumption, seeded movement, bankruptcy after three missed payroll days, regrowth, existing loan/trade/research/vote deadlines and weekly rent. Newly submitted applications wait for the next day's owner/fallback round. Current automatic code does **not** buy bread for citizens; provider prompts/older descriptions that say otherwise are stale.

The small `_growth_rules` path presently called by `tick` opens two town plots when all existing plots have a building or tenant; adds one newcomer every third day when average hunger is below 50 and a job slot is open; lets a saver holding more than 8,000 cents fund a least-common-kind business with 5,000 cents on vacant town land; upgrades full businesses with cash above 10,000 cents for 2,500 business cents and two extra slots; and leases affordable owned homes for employed citizens with more than 2,000 cents. It reuses engine commands/helpers. Manual upgrades preserve the owner's personal 2,500-cent cost and gain two slots, within model capacity.

A separate `_grow` implementation contains outer-ring plots, named newcomers, three-day `destitute_days` departures for citizens who own no building/plot, non-owner-only automatic founding, busy upgrades, renting, and a **20,000-cent business cash cap** that distributes surplus to staff with remainder to the owner. This code exists but is not the `_growth_rules` path called by the inspected tick. Some method names overlap and later definitions override them. **Do not claim departure, cash redistribution or a particular expansion layout is integrated until the competing paths are reconciled and tested.** Those are current code conflicts, not permission to invent another monetary policy or growth system.

The action vocabulary includes 36 existing types: `buy`, `sell`, `transfer_money`, `set_price`, `produce`, `consume`, `communicate`, `construct_building`, `upgrade_building`, `move_to`, `adjust_goals`, `found_business`, `close_business`, `set_wage`, `hire`, `fire`, `gather_resource`, `apply_job`, `quit_job`, `reject_application`, `lend`, `respond_loan`, `repay`, `trade`, `respond_trade`, `research`, `license_invention`, `respond_license`, `adopt_invention`, `propose_vote`, `vote`, `lease_lot`, `set_rent`, `pay_rent`, `evict`, `interact`. Reuse those names instead of adding duplicate build/close/talk aliases.

Existing advanced rules include directed trust/grudges, interaction cooldowns, flat-interest loans and defaults, two-day trade offers, money/time research and production multipliers, license offers, weighted town votes, price/minimum-wage/tax policies and seven-day rent. Read the matching engine branches and tests before changing them. Memory code derives bounded recent first-person lines and routine-event summaries without LLM calls; current engine rejection handling and older promises of no citizen mutation must be reconciled with that memory behavior when restoring the integrated loop.

## 8. Seed world

`initial_world(seed=42, branch_id="main")` in `seed.py` is the runtime seed. The root `world_seed.json` is not its loader. Never replace live persistence with an offline fixture.

| ID          | Name / occupation | Initial job | Initial cents |
| ----------- | ----------------- | ----------- | ------------- |
| `citizen-0` | Elena / Farmer    | farm        | 18,000        |
| `citizen-1` | Marcus / Baker    | bakery      | 22,000        |
| `citizen-2` | Ada / Merchant    | market      | 16,000        |
| `citizen-3` | Rowan / Farmhand  | farm        | 800           |
| `citizen-4` | Theo / Miller     | bakery      | 650           |
| `citizen-5` | Mira / Builder    | none        | 6,000         |
| `citizen-6` | Finn / Weaver     | none        | 550           |

Each starts with one bread and hunger 20. Goldenfield Farm, Hearth & Grain bakery and Market Square have stable IDs `farm`, `bakery`, `market`; owners are citizens 0, 1 and 2. Seed defaults include 10,000 business cents, wage 150, three slots, bread price 500 and wheat price 100. Farm/bakery start with 12 wheat; bakery starts with 16 bread.

Six plots use x −4/0/4 and z −3/+3. Business plots belong to their owners; plots 3/4 are town land; Elena owns plot 5 and Mira rents it for 300 cents per seven-day period. Shared wheat starts at 120 with regeneration 6 and cap 200. Crop Rotation and Water Mill are the seeded inventions. Preserve the distinction between deterministic seed values, saved worlds and external starting money from setup/newcomers.

## 9. Agent layer and configuration

| File under `backend/modules/agents/src/kronos_agents/` | Purpose                                                                                                                 |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| `provider.py`                                          | `LLMProvider.complete`, MockProvider/parser, typed validation, proposal source, timeout/retry, cadence and grounded Ask |
| `anthropic_provider.py`                                | Optional Anthropic adapter, strict output schema, injected-client test seam, task responses                             |
| `prompts.py`                                           | Task prompts and schema-valid seed examples; static prompt caching                                                      |
| `fallback.py`                                          | Deterministic `UtilityPolicy`, weighted by goals with hunger/food priority and stable tie-breaking                      |

`queries.observe` is the shared builder: own copied citizen state; derived role/wealth tier; bounded public bakery prices/stock and neighbor names; supported action names; relevant Events; own loans, incoming offers and strongest ties; public job openings and owned business views. Do not expose other citizens' private balances/goals as a shortcut.

Provider tasks are `decision`, `ask`, `intervention`. AgentService validates JSON against the task schema, checks acting-citizen identity and grounds Ask citations in the supplied Events. Timeout/retries are bounded. `proposal()` labels source `llm|mock|fallback` and prefixes the rationale; `decide()` returns the action. Service configures `UtilityPolicy` as fallback. Do not confuse proposal-source labels with ActionResult caller sources `agent|player|backend`.

The later provider scheduler assigns each citizen a stable CRC32-derived slot once per `agent_round_ticks` days (default three), with concurrent calls and independent failures. The earlier eight-citizen needs-based `propose(world, events)` definition is still in the file but shadowed. Service still calls that older signature in its post-tick task: see the integration blocker rather than assuming either cadence works end to end.

Mock decisions consume owned food, buy affordable stocked bread, or communicate. The expanded mock intervention parser covers price percentages, wages, giving/taking money, wheat stock/regrowth, hunger/feast/famine and policies. The wider union and parser exist, but queued ActionResult/tick integration still only recognizes price interventions; targeted citizen parsing also needs the citizen-name map that the inspected Service does not currently pass. Do not advertise all expanded interventions as working API features yet.

The optional Anthropic adapter is selected explicitly by `build_provider`. Its default model string and schema adaptation live in `anthropic_provider.py`; model-name presence in code does not verify current remote availability. Optional calls can cost money. Default/offline tests must not require network access or credentials. Never record API keys in source, fixtures, this file, or logs.

## 10. API, action lifetime and transport

`backend/api/src/kronos/main.py` constructs FastAPI, routers, exception handlers and CORS. Its lifespan creates Service, starts the clock and cancels tasks/closes the store on shutdown. `dependencies.py` supplies the shared service. CORS permits local frontend origins on port 5173.

| Router / endpoints                                                                                                        | Responsibility                                             |
| ------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `world.py`: `GET /api/world`, citizen reads, `GET /api/jobs`, `WS /ws/world`                                              | Authoritative queries and full-state streaming             |
| `user.py`: `POST /api/actions`, `/api/interventions`, setup `POST /api/agents`                                            | Player proposals and explicit spawning                     |
| `agents.py`: citizen `/observation`, `/actions`, `/actions/validate`, `/decide`, `/ask`, goals                            | Citizen-specific proposal/validation/read tools            |
| `backend.py`: `/health`, `/api/simulation/status`, `/play`, `/pause`, `/tick`, `/api/backend/actions`, `/api/simulations` | Shared clock, automation and new village creation          |
| `businesses.py`, `lots.py`, `market.py`, `resources.py`                                                                   | Existing business, job, property and economic conveniences |
| `loans.py`, `relationships.py`, `inventions.py`, `votes.py`                                                               | Existing advanced feature routes                           |
| `history.py`: `/api/events`, `/api/history/events`, snapshots, branches, action lookup, citizen history                   | Event/history queries and timeline tools                   |

The intended action contract is `POST /api/actions` with current context:

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
    "rationale": "I need bread."
  }
}
```

Use actual latest branch/sequence, not the literal sample zero. Queued action attempts/results live in Service memory, grouped by branch; they disappear on process restart. Committed Events/world/checkpoints persist. `GET /api/actions/{id}` is session lookup, not durable history. Attempts have opaque session-unique IDs and monotonically increasing order; do not parse the ID format. Admission itself neither changes world sequence nor broadcasts. Convenience routes must reuse the same service/engine path.

Stale context returns 409; malformed input/dry-run rule failure/provider failure maps to 422; missing entities/history to 404. Gameplay rejection at execution is an outcome with a typed `action_rejected` Event, not an optimistic world mutation. Validation reserves no stock or funds. This is a trusted local prototype without public-user authentication.

`GET /api/world` and WebSocket frames use **`{branch_id, tick, sequence, state, events}`**. `state` is the complete serialized WorldState, not a delta. WebSocket sends an initial snapshot/recent Events, then new saved state plus the committed Event batch. Tick HTTP results additionally include `action_results` and `rejected_actions`. Events describe outcomes, carry sequence and optional action/causal links, and are the source for the feed. Never infer a completed trade from browser movement or snapshot differences.

`GET /api/events?after=N&limit=100` currently has conflicting list and `EventPage` handlers. `EventPage` defines `branch_id`, `events`, `next_after`, `has_more`. Both implementations use ascending exclusive-after queries. Consumers must not assume a final page envelope until section 3 is resolved. `/api/history/events` remains the explicit branch/through historical route.

Play requires branch/version and speed 1/2/4; pause uses an empty body; manual tick uses branch/version. Backend playback starts paused/1 after restart. The newer frontend hook auto-starts play once on visiting a connected live village, then respects later pauses. Shared playback affects all tabs.

## 11. Persistence and database ownership

**The database is separately owned. The standing scope restriction is no database/schema/model/migration changes without explicit authorization superseding that restriction.** Inspect and use existing interfaces; do not silently alter tables, persisted fields, repositories or seed structure to make an engine task easier. Missing capabilities belong under “Database dependencies / handoff.” Do not introduce a second engine-owned database.

`backend/modules/history/src/kronos_history/store.py` defines SQLAlchemy Core tables `branches`, `snapshots`, `events`, `settings`, and the legacy `actions` table. Branch worlds and typed Event data are serialized JSON; this is not one SQL row per Citizen/Building. Snapshots include integrity hashes and full world state. `settings` stores the active branch pointer. The runtime queue uses no legacy action writes in the queued Service path, although old enqueue/pending/lookup helpers remain database-owned.

`HistoryStore.commit(result, expected_sequence)` checks current branch sequence, contiguous Events and final state/Event version, writes the world/Events and an immutable checkpoint in one transaction. Other public helpers create/activate/read branches, restore/check snapshots and query Events. Service must call these rather than inventing another repository. Forks preserve stable entity IDs, tick and RNG, and reset branch-local sequence; saved snapshots reconstruct without calling providers.

**Starting the existing backend can write to the tracked database even before a tick:** `HistoryStore.__init__` invokes `metadata.create_all`, and Service seeds/activates a world if empty. Auto-reload can repeat startup after source edits. The live frontend can auto-play and add world changes. Do not start or leave a reloading server against a protected developer database while promising not to change it. Use an explicitly selected disposable test database through the existing interface when runtime verification is authorized; tests already do this.

`backend/database/kronos.db` is tracked. `make reset` deletes the default database and sidecars (and old root-level equivalents), regardless of a custom database URL; it does not reset an arbitrary configured database. `make db-init` runs existing initialization. Both are mutation tools, not harmless validation commands. Stop the backend before an explicitly authorized reset.

### Database dependencies / handoff

- `Citizen.destitute_days`, JobApplication status and memory-summary fields are now declared in the current entity contract. Coordinate compatibility with saved worlds; do not add duplicate `starvation_days` merely because an older PRD named it differently. Departure integration is currently an engine merge issue, not proof of a missing current field.
- Persistent playback settings and Event wall-clock timestamps are not represented on current WorldState/Event contracts. Hand them off if requested; current tick/sequence already represent simulation ordering.
- Legacy action-table retirement, startup schema creation, migrations, tracked-database policy and snapshot retention belong to the persistence owner.
- Models have changed while malformed generated artifacts remain in the tree. Repair the integration and regenerate contracts before claiming DB/world/frontend compatibility.

## 12. Frontend architecture and assets

`frontend/src/main.tsx` mounts App. The newer full-screen App/HUD uses `useSimulation`; `Dashboard.tsx` preserves the earlier panel layout, and Inspector/EventLedger components remain available. Current App contains mixed versions and cannot compile; the following describes the separate modules present, not a verified working entry component.

| File(s) under `frontend/src/`                     | Purpose                                                                                                                     |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `api/client.ts`                                   | HTTP requests with timeout, context from current snapshot, WebSocket reconnect and HTTP resync                              |
| `api/types.ts`                                    | Aliases of generated backend types                                                                                          |
| `api/format.ts`, `components/EventLedger.tsx`     | Named human-readable Events and activity cues; feed filters routine noise                                                   |
| `api/mock.ts`                                     | Clearly labeled development fixture story, never live simulation authority                                                  |
| `stores/world.ts`                                 | `useWorld` snapshot/Event store, branch/sequence guards, historical replacement epoch; separate `usePresentation` selection |
| `app/useSimulation.ts`                            | Load/connect, status polling, auto-play once, controls and offline preview stepping                                         |
| `world/Village.tsx`                               | Canvas/camera/lighting/controls, entities, activity and scene composition                                                   |
| `world/Ground.tsx`, `town.ts`, `progress.ts`      | Terrain/roads/lots/scenery, road graph, backend-plot accommodation and derived growth tiers                                 |
| `world/Models.tsx`, `assets.ts`, `preload.ts`     | Model rendering, character animation, asset registry and preloading                                                         |
| `world/BuildingLife.tsx`, `sites.ts`, `spring.ts` | Construction/upgrade/removal presentation and builder-site registration                                                     |
| `world/routine.ts`, `crowd.ts`                    | Cosmetic errands and local personal-space separation                                                                        |
| `world/Selection.tsx`                             | Scene selection presentation                                                                                                |
| `app/styles.css`                                  | Shared layout, HUD and visual styles                                                                                        |

`useWorld.ingest` rejects stale/wrong-branch/historical frames, merges explicit Events by ID and retains a bounded recent feed. Full snapshots make sequence gaps safe. `replace` swaps the complete world and increments the animation epoch so seeks/branch switches do not replay stale transitions. Per-frame transforms/animation live in Three.js refs; avoid per-frame React/Zustand writes.

Town tiers and prosperity score are derived presentation, with hysteresis/epoch reset. Decorative houses, chapels, forges and lumbermills are not new authoritative BuildingKinds. `Ground.Lots` renders actual plot ownership/tenancy at backend coordinates; `town.withLots` makes room around them. Villagers' road-graph routines, shopping poses, cosmetic homes and crowd avoidance do not spend money, assign jobs or override backend positions.

Committed assets are under `frontend/public/models/kaykit/`: the medieval hexagon set and rig-compatible characters/animation clips. `assets.ts` is the registry. Preserve accompanying licenses and linked `.gltf`/`.bin`/texture or `.glb` dependencies. The asset README records CC0 licensing and pinned origins. Keep replacement models compatible with stable IDs, x/z ground coordinates, selection and existing animation groups. No proprietary assets are required.

The development preview works without an API by intention: VITE_OFFLINE or connection failure loads generated seed plus a labeled fixture story. Production requires the backend. Invalid generated JSON currently blocks even that preview's compilation. WebGL is required; large bundles/many scene objects remain optimization considerations, not grounds to rewrite authority boundaries.

## 13. Configuration and development commands

Settings live in `backend/api/src/kronos/config.py`; Pydantic reads root `.env` with prefix `KRONOS_`. Vite reads root env files via `envDir: ".."`. Do not inspect or copy private `.env` values just to update documentation.

| Variable                   | Current default / meaning                                                                  |
| -------------------------- | ------------------------------------------------------------------------------------------ |
| `KRONOS_DATABASE_URL`      | `sqlite:///./backend/database/kronos.db`                                                   |
| `KRONOS_SEED`              | 42; affects newly seeded worlds, not a rewrite of existing worlds                          |
| `KRONOS_TICK_SECONDS`      | 2; divided by playback speed, clock sleep floored at 0.1 seconds                           |
| `KRONOS_LLM_PROVIDER`      | `mock`; optional `anthropic` selection                                                     |
| `KRONOS_LLM_MODEL`         | `deterministic-v1`; real adapter substitutes its code-defined default for this placeholder |
| `KRONOS_LLM_TIMEOUT`       | 3 seconds for mock; Anthropic selection uses 20 seconds unless explicitly configured       |
| `KRONOS_LLM_RETRIES`       | 1; AgentService clamps to at most 2 retries                                                |
| `KRONOS_AGENT_ROUND_TICKS` | 3; stable scheduled decision round length (integration issue noted above)                  |
| `ANTHROPIC_API_KEY`        | Required only when explicitly opting into the optional paid provider; secret               |
| `VITE_API_URL`             | `http://localhost:8000`                                                                    |
| `VITE_OFFLINE`             | `true` forces the labeled development preview                                              |

Commands run from the repository root. Python needs 3.12+, Node needs 22.12+, and Make/npm must be available. Bootstrap uses local `.tools/` installations of missing uv/pnpm; no global administrator installation is needed. `uv sync --frozen` and `pnpm install --frozen-lockfile` use committed locks.

| Command                           | Purpose / side effects                                                                      |
| --------------------------------- | ------------------------------------------------------------------------------------------- |
| `make install`                    | Bootstrap tools, install locked Python/Node dependencies                                    |
| `make backend`                    | Start local Uvicorn with backend auto-reload on 8000; can initialize/write DB               |
| `make frontend`                   | Start Vite on 5173                                                                          |
| `make stop`                       | Stop listeners on both development ports                                                    |
| `VITE_OFFLINE=true make frontend` | Development fixture preview                                                                 |
| `make test`                       | All pytest then frontend Vitest                                                             |
| `make lint`                       | Ruff check/format check, ESLint and Prettier check                                          |
| `make build`                      | TypeScript check/build and Vite production output                                           |
| `make check`                      | Tests, lint/format and frontend build                                                       |
| `make format`                     | Writes formatting/lint fixes broadly; avoid when only selected files should change          |
| `make contracts`                  | Export OpenAPI + seed fixture and generate TypeScript; does not intentionally start Service |
| `make db-init`, `make reset`      | Database mutation tools; ownership/authorization required                                   |

Current Makefile frees its configured port before starting either app, so a start command can terminate an existing listener. Do not use it as a read-only health probe. Use `.tools/node/node_modules/.bin/pnpm` and `.tools/python/bin/uv` explicitly if global tools use incompatible runtimes. Example: `make check PNPM="$PWD/.tools/node/node_modules/.bin/pnpm"`.

Opting into the real provider additionally needs `uv sync --extra anthropic` and explicit environment selection/key. Do not enable it just to verify unrelated code. Swagger is `/docs`, health is `/health`; the inspected health handler hard-codes `provider: mock`, so it is not reliable evidence of configured provider selection.

## 14. Tests, generated artifacts and extension workflow

Python tests live in module `tests/` and `backend/api/tests/`. Simulation tests cover economic/domain rules, memories, growth, interventions and invariants. Agent tests cover mock, utility fallback and injected Anthropic responses using fixtures; no paid calls are needed. History tests cover persistence/snapshot/sequence behavior. API tests cover routes, queue timing, provider selection, branch isolation, save-failure rollback, WebSocket envelopes and integration.

`backend/api/tests/conftest.py` has a `route_only` fixture that disables strategy/daily/growth mechanics for mapping tests. Queue/v1 integration tests exercise real rules. Do not mistake an isolated route check for whole-day verification. Use temporary SQLite paths through the existing store, not the tracked developer database.

Frontend Vitest tests cover snapshot ingestion, fixture story, Event formatting, town tiers/roads/homes and crowd separation. CI installs Python 3.12 and Node 22, runs `make check`, then `make contracts` and rejects a diff under `backend/contracts`.

Canonical generation flow:

```text
models.py + FastAPI route definitions
  → scripts/export_contracts.py
  → backend/contracts/schemas/openapi.json
  → openapi-typescript → backend/contracts/generated/api.ts
  → frontend/src/api/types.ts aliases

seed.py + WorldUpdate
  → backend/contracts/generated/initial-world.json → development preview/tests
```

Never hand-edit generated artifacts. Repair Python import/route issues first, regenerate all three outputs, then inspect/validate them. Contract export currently cannot succeed while engine/service imports are syntactically broken. A successful old schema file is not evidence that today's source imports.

For a new action, extend its DTO/union and supported names, add current-state validation and mutation in the existing Engine path, emit a typed Event, test successful effects and rejection isolation, integrate through the service queue, regenerate contracts, and update this file. New persisted entity fields need database-owner coordination.

For an automatic rule, extend the single reconciled daily/growth path with deterministic helpers and explicit ordering. Reuse action helpers, emit outcomes, sort stable IDs and test thresholds/repeatability/reference cleanup. Never add an LLM call to automatic mechanics or a second tick loop.

For a provider, implement `LLMProvider.complete`, validate task outputs and actor identity, integrate selection in `build_provider`, use injected clients for offline tests, keep mock default, and document env/cost/timeout behavior here. For a scene change, reuse the asset registry and separate visual modules; update generated contracts only if wire behavior actually changes.

For any change, reconcile the relevant known issues rather than treating competing implementations as established behavior. Run the appropriate owner tests plus required wider checks, update this document and affected supporting guides, and report remaining limitations honestly.

## 15. Supporting documentation and troubleshooting

This file is the entry point and maintained overview. Supporting documents are:

| Document                                                                                                 | Use / caveat                                                                                                      |
| -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| [simulation-engine.md](simulation-engine.md)                                                             | Detailed queued-loop usage; older claims about missing destitution/application fields are superseded by this file |
| [simulation-design.md](simulation-design.md)                                                             | Domain/growth design; compare with current competing implementation paths                                         |
| [api-contracts.md](api-contracts.md), [event-protocol.md](event-protocol.md)                             | Request/Event conventions; verify against repaired routes and regenerated schemas                                 |
| [frontend-world.md](frontend-world.md)                                                                   | Terrain, models, routines, lifecycle effects and visual extension detail                                          |
| [architecture.md](architecture.md), [team-workflows.md](team-workflows.md)                               | Module boundaries and team coordination; this file controls current context                                       |
| [simulation-engine-spec.md](simulation-engine-spec.md), [implementation-plan.md](implementation-plan.md) | Historical specification/planning, not automatic permission or proof of implemented features                      |
| [demo-scenarios.md](demo-scenarios.md), [verification.md](verification.md)                               | Demo/historical checks; rerun relevant verification before citing current health                                  |
| [frontend/public/models/README.md](../frontend/public/models/README.md)                                  | Asset sources/licenses and file dependencies                                                                      |
| Module/root READMEs                                                                                      | Supporting orientation; known old statements must not override this document                                      |

Common diagnoses: 409 means reload branch/version and reconsider the command; queued means wait for a tick on the correct branch/session; 404 after restart means read persisted Events and resubmit only unexecuted work. Job applications need the next-day owner/fallback round and free funded slots. WebSocket issues need full-state resync, branch/sequence checks and successful persistence. A cosmetic visit to a bakery is not a purchase. A growing visual tier is not an authoritative land expansion.

For this checkout, fix the syntax/integration blockers before investigating runtime symptoms. Offline mode does not mean the real backend is healthy. A database changed after “just starting” the app may be startup table initialization or frontend auto-play; inspect without migrations or resetting someone else's state.

## 16. Latest maintenance record

- **2026-10-10 — Documentation centralization:** created this codebase reference from current sources, made the read/update requirement mandatory through root `AGENTS.md`, and added a README entry point. Runtime code, generated contracts, database files and persistence implementation were not changed.
- **Validation performed:** source/path inspection; static parse of backend/script Python; frontend TypeScript check with `--noEmit --incremental false`; targeted Markdown formatting and local-link checks. Python/TypeScript checks found the existing failures in section 3. No full-suite pass is claimed and no backend or paid provider was started.
- **Outstanding:** reconcile the merged engine/service/provider/frontend paths and generated artifacts, then run `make check` and `make contracts`. Update this record and remove resolved blockers when that authorized repair is complete.
