# Simulation mechanics

A tick represents one day. The engine runs these steps in stable insertion order:

1. If a bakery lacks wheat, buy two wheat from the first farm if cash/stock permit.
2. Farms produce a seeded 3–6 wheat per level. Bakeries consume two wheat for three bread per level.
3. Employers with available cash pay each employed citizen 150 cents.
4. Each citizen gains 20 hunger, capped at 100. If they have no bread, purchase one loaf from the cheapest stocked bakery they can afford. Consume one bread for 30 hunger relief.
5. Citizens choose a seeded plot waypoint and walk via the central lane in presentation time.
6. Run the daily bookkeeping steps (resources, applications, loans, offers, research, votes, rent), then the **growth step** (see below).
7. Apply optional strategic proposals in order, each in an isolated validation transaction.
8. Return the new world, ordered events, final RNG state, and rejected proposal reasons.

The API obtains the bounded strategic proposal from the pre-tick observation every third day. It therefore observes yesterday's state, not half-finished production/trades. Routine mechanics never call a model. This timing is explicit and can be revised by the team without changing renderer ownership.

Player price changes occur between ticks and take effect immediately in all existing bakeries, using Decimal half-up rounding into cents. This is a one-time operation, not a continuing constraint; newly built businesses start at the default price and owner `set_price` actions can revise it. Accepted percent range is −90% through +200%, with final prices constrained to 1–1,000,000 cents.

Buy/sell validate cash, stock, quantities, and buyer limits. Owner actions validate ownership. Construction requires a vacant predefined plot and 5,000 cents; upgrades cost 2,500 cents and cap at level three. Costs leave the modeled economy as construction inputs; trades and wages conserve money. Communication stores bounded recent memories and increases familiarity by one, capped at 100; its content is not a proven economic cause. Citizens cannot spend each other's money through agent proposals.

Current omissions: production cooldown on manually submitted `produce`, richer market roles, need-based occupations, death, investments driven by strategy, and ownership transfers. Daily routines deliberately stay small. Add constraints and test them before exposing new command vocabularies.

## v1 data model

The v1 core is the smallest model the village needs to run, grow, and be replayed. Money is integer cents (1 coin = 100 cents), one tick is one day, and IDs are stable strings (`citizen-0`, `farm`, `plot-3`). Field names follow `models.py`, flattened here where the models nest (position, inventory, prices).

| Entity           | Fields                                                                                                                                                                                         |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `World`          | One row: `id`, `tick`, `sequence`, `seed`, `rng_state`. Playing and speed are runtime state reported by `GET /api/simulation/status`                                                           |
| `Citizen`        | `id`, `name`, `occupation`, `employer_id` (building or null), `money`, `hunger` 0–100, `wheat`, `bread`, position `x`/`z`, `destitute_days`. Seed: Elena, Marcus, Ada, Rowan, Theo, Mira, Finn |
| `Building`       | `farm`, `bakery`, or `market`: `id`, `name`, `kind`, `level` 1–3, `owner_id`, `plot_id` (unique), `cash`, `wheat`, `bread`, `bread_price`, `wheat_price`, `wage`, `job_slots`                  |
| `Plot`           | `id`, position, `owner_id` (null = town land), `tenant_id` (or null), `rent` per week. Six seed plots; more open as the town grows                                                             |
| `JobApplication` | `id`, `citizen_id`, `building_id`, `status` (`pending`, `hired`, `rejected`), `tick`. Resolved applications are kept with their status                                                         |
| `Event`          | `sequence`, `tick`, `type`, `actor_id` (or null), `payload` JSON, `created_at`                                                                                                                 |

The world has citizens, plots, buildings, and events. A plot holds at most one building. Citizens own buildings, own plots as landlords, rent one plot as a home, and submit applications; buildings employ citizens and receive applications. `destitute_days` counts consecutive days at hunger 100 with no money.

**Rules.** One building per plot, and only on a vacant one. Build on town land or on a plot you own or rent. Only the owner sets prices and wages, hires, upgrades, and closes. Hiring stops at `job_slots`. Closing a building clears its employees' `employer_id` and rejects its pending applications. Money, cash, wheat, and bread stay ≥ 0 and hunger stays within 0–100. Each change saves its events and state in one transaction before broadcast.

**v1 event types.** Money and goods: `transaction_completed`, `price_changed`, `resource_produced`, `resource_consumed`. Buildings: `building_constructed`, `building_upgraded`, `building_removed`. Lots: `lot_leased`, `plot_opened`. Jobs: `job_applied`, `job_application_resolved`, `employment_changed`. People: `citizen_spawned`, `citizen_removed`, `citizen_moved`, `agent_spoke`. Player: `intervention_applied`, `action_rejected`.

**v1 endpoints.** `GET /api/world`, `WS /ws/world`, `GET /api/simulation/status`, `POST /api/simulation/play`, `/pause`, `/tick` (speeds 1×, 2×, 4×), `POST /api/actions`, `POST /api/interventions`, `GET /api/events?after=<sequence>&limit=`, `GET /api/jobs`.

### Growth step

The last daily step in `Engine.tick()`, after the existing ones. It uses no AI, and its numbers are tunable constants in `engine.py`.

| Rule       | Behaviour                                                                                                                       | Events                                  |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| New land   | When every plot has a building or a tenant, 2 town-land plots open on the outer ring                                            | `plot_opened`                           |
| Newcomers  | Every 3 days, if average hunger < 50 and a job slot is open, one citizen arrives with 10 coins and applies                      | `citizen_spawned`, `job_applied`        |
| Departures | A non-owner at hunger 100 with no money for 3 days in a row leaves; their job and rented plot are freed                         | `citizen_removed`, `employment_changed` |
| Founding   | At most one per day: a citizen with > 80 coins founds the kind the town has fewest of on free town land, with 50 coins as cash  | `building_constructed`                  |
| Upgrades   | A building with > 100 coins cash and every slot filled gains a level (max 3) for 25 coins, plus 2 job slots                     | `building_upgraded`                     |
| Renting    | An employed citizen with no home and > 20 coins leases a free owned plot                                                        | `lot_leased`                            |
| Cash cap   | Business cash above 200 coins (`BUSINESS_CASH_CAP`) is paid out evenly to its employees, so money does not pool in one business | `transaction_completed`                 |

### Beyond v1 core, already implemented

The backend keeps everything below; it is outside the v1 core but fully supported: history branches and forks, inventions, relationships and `interact`, loans, trade offers, town votes and policies, rent details (arrears, prepayment, eviction), shared natural resources, and AI personality and goal weights.

## Innovation

`WorldState.inventions` is seeded with `crop_rotation` (1,500 cents; adopting farms make wheat ×1.4) and `water_mill` (2,500 cents; adopting bakeries make bread ×2). Costs are the spec's florins at 10 cents each. Multipliers are integer percentages applied in invention-ID order inside `Produce`, so production stays deterministic and uses no extra RNG.

- `research` money mode spends at most the remaining cost; the money leaves the economy like construction inputs. Time mode needs a job: for the next `ticks` days the employer keeps the wage (`research_invention_id` / `research_until_tick` on the citizen; the wage loop skips them) and each skipped wage counts as progress. At full cost the top contributor owns the invention (ties go to the lowest citizen ID) and other time researchers are released.
- `license_invention` only creates a `LicenseOffer`; the recipient answers with `respond_license` on the same tick (funds re-checked) or the offer expires at the next tick. The fee moves recipient → owner.
- `adopt_invention` is for the building owner who owns or licenses an unlocked invention matching the building kind; the business pays `adoption_cost` (a sink).
- Waiting on richer goods: `printing_press` (books, scribes) and `ledger_banking` (loans). Add them with a matching `InventionEffect` once those goods and actions exist. Closed buildings stay in `adopters`; building IDs are never reused.

## Relationships

`Citizen.relationships` holds directed ties: A's entry for B is how A feels about B. Spec 0..1 values are scaled by 100: `trust` −100..100, `grudge` 0..100, plus a `type` (`acquaintance` by default, `friend`, `ally`, `rival`, `trade`, `employer`, `creditor`, `landlord`) and `last_interaction_tick`. Missing entries count as trust 0. Entries are created on first contact.

`interact` (`POST /api/agents/{id}/interact`) applies fixed engine rules to the **target's** feeling toward the actor. `ally` and `argue` are mutual and change the actor's feeling toward the target the same way.

| kind     | trust | grudge | side effect                                                                               |
| -------- | ----- | ------ | ----------------------------------------------------------------------------------------- |
| befriend | +10   | —      | an `acquaintance` at trust ≥ 50 becomes a `friend`                                        |
| gift     | +15   | −5     | moves `amount` cents actor → target (`insufficient_funds` if short)                       |
| ally     | +20   | —      | `type = ally` both ways; needs the target's trust toward the actor ≥ 50 (`trust_too_low`) |
| argue    | −10   | +10    | —                                                                                         |
| insult   | −15   | +20    | target reputation −2                                                                      |
| betray   | −50   | +50    | target's `type = rival`; actor reputation −10                                             |
| mentor   | +10   | —      | target reputation +2 (there is no skill yet; reputation stands in for it)                 |

An actor may interact with a given target once per tick (`rate_limited`). Each interaction emits `citizen_interacted` (kind, amount, both reputations afterwards), a `transaction_completed` for a gift, and one `relationship_changed` per changed direction. `relationship_changed` carries `recipient_id` (whose feeling changed), `citizen_id` (whom it is about; null in older events means the event's actor), and the resulting `trust`, `grudge`, and `type`. Communicating adds +1 trust; a loan default costs the lender −30 trust and adds +30 grudge toward the borrower.

Trust feeds hiring (the daily fallback takes applications in order of the owner's trust toward the applicant, then first come), influence (average trust from others), and the observation's `ties`: the five strongest feelings by |trust| or grudge, with names. `GET /api/agents/{id}/relationships` lists all ties by trust; `GET /api/relationships/{a}/{b}` returns both directions.
