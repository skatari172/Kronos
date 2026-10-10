> Historical design reference. The implemented runtime now follows the supplied `KRONOS_SIMULATION_ENGINE_BUILD_SPEC.md` and [simulation mechanics](simulation-design.md): durable queued actions before daily rules, post-commit next-tick deliberation, full-state broadcasts, and no mutation on rejection. Older immediate-execution and transaction-context proposals below are not the implementation contract.

# KRONOS Simulation Engine Specification & Architecture Guide

> **Target Audience**: AI Agents and Engineers implementing or extending the authoritative world simulation in `backend/modules/simulation/`.
> **Scope**: Engine architecture, state invariants, execution pipelines, database persistence alignment, AI agent integration, and deep domain subsystems (Economics, Social Graph, Innovation Tree, and Civic Governance).

---

## 1. System Philosophy & Non-Negotiable Invariants

The product name is **KRONOS**. The backend world state is authoritative. Neither the browser frontend nor the LLM agent layer may directly mutate world state. All state mutations MUST pass through [`Engine`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/engine.py#L48).

### Authoritative Invariants

1. **Monetary Conservation**:
   - Currency is represented in **integer cents** (1 coin = 100 cents). No floating-point arithmetic.
   - Total money mass $M$ across the closed village economy is conserved:
     $$M = \sum_{c \in \text{Citizens}} c.\text{money} + \sum_{b \in \text{Buildings}} b.\text{cash} + \text{VillageTreasury}$$
     _Money is neither created nor destroyed during routine trades, wages, rents, or loans. It enters only via explicit Player Interventions or initial world seeding._
2. **Deterministic Replay & Seeded RNG**:
   - The simulation engine uses a dedicated Python `random.Random` instance seeded from [`WorldState.seed`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/models.py#L109).
   - `rng_state` is captured in every committed state and checkpoint. Historical replay uses recorded events and model outputs, never re-prompting LLMs.
3. **Strict Precondition Validation**:
   - No negative inventories, no negative cash, no double spending, no reuse of occupied lot plots.
   - Rule violations raise [`InvalidAction(code, message)`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/engine.py#L36), which are logged as `action_rejected` events and recorded into the agent's recent memories.
4. **Append-Only History & Event Sourcing**:
   - State mutations emit discrete, typed [`SimulationEvent`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/models.py#L269) records with monotonically increasing sequence IDs (`branch_id:sequence`).

---

## 2. Two-Tier Tick Execution Pipeline

To resolve the latency disparity between the fast simulation clock (1–2 s/tick) and slow LLM inference (1–3 s/call), the engine runs on a two-tier cadence:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        DAILY ENGINE TICK PIPELINE                      │
├────────────────────────────────────────────────────────────────────────┤
│ Step 1: Environmental Sampling & Invariants                            │
│         - Seeded weather / harvest multiplier calculation              │
│                                                                        │
│ Step 2: Commercial Production & Supply Chain Restock                   │
│         - Bakeries purchase wheat from farms if inventory < 2          │
│         - Farms & Bakeries execute automated daily production          │
│                                                                        │
│ Step 3: Payroll Disbursement & Bankruptcy Tracking                     │
│         - Employers disburse daily wages to employed citizens          │
│         - Track consecutive missed payroll days (3 days = Bankruptcy)  │
│                                                                        │
│ Step 4: Biological Needs & Maintenance                                 │
│         - Hunger increments (+20, capped at 100)                       │
│         - Autonomous bread purchase if inventory is empty             │
│         - Bread consumption for hunger relief (-30 hunger)             │
│         - Waypoint pathing to random plots for visual animation        │
│                                                                        │
│ Step 5: Contracts, Governance & Civic Enactments                       │
│         - Settle mature loans (due_tick == current_tick)               │
│         - Collect market taxes into the municipal treasury             │
│         - Enforce active regulatory caps (price caps, minimum wage)    │
│         - Tally closed referendums and enact winning policies          │
│                                                                        │
│ Step 6: Drain Asynchronous Strategic Action Queue                      │
│         - Execute validated agent / player proposals in FIFO order     │
│         - Isolate each proposal in a transaction boundary              │
│                                                                        │
│ Step 7: Batch Commit & Broadcast                                       │
│         - Emit ordered events and serialize state delta                │
│         - Persist to SQLite, broadcast over WebSocket                  │
└────────────────────────────────────────────────────────────────────────┘
```

### Execution Rules

- **Steps 1–5 (Tier 1: Micro-tick)** are 100% deterministic rule-based Python execution. They NEVER invoke an LLM.
- **Step 6 (Tier 2: Macro-deliberation)** drains proposals that arrived asynchronously from player inputs or background agent deliberation tasks.

---

## 3. High-Performance Transaction Model (Structural Sharing)

### The Problem with Naive Deep-Copying

In Python and Pydantic v2, executing `self.state = state.model_copy(deep=True)` on every proposal and dry-run validation introduces high latency and memory allocation overhead as citizen count and memory histories expand.

### Recommended Pattern: Entity-Level Structural Delta

Instead of copying the entire [`WorldState`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/models.py#L104) graph:

1. **Targeted Entity Clones**: For an action affecting citizen $C$ and building $B$, clone only $C$ and $B$.
2. **Working Mutation Context**:
   ```python
   class TransactionContext:
       def __init__(self, base_state: WorldState):
           self.base = base_state
           self.dirty_citizens: dict[str, Citizen] = {}
           self.dirty_buildings: dict[str, Building] = {}
           self.events: list[SimulationEvent] = []

       def get_citizen(self, cid: str) -> Citizen:
           if cid not in self.dirty_citizens:
               self.dirty_citizens[cid] = self.base.citizens[cid].model_copy(deep=True)
           return self.dirty_citizens[cid]
   ```
3. **Commit or Rollback**:
   - On success: Merge `dirty_citizens` and `dirty_buildings` into the active world state, append `events`, and increment sequence.
   - On [`InvalidAction`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/engine.py#L36): Discard the transaction context. The base world state remains completely untouched without expensive rollback logic.

---

## 4. Database Schema & Persistence Strategy

### 4.1 Event Sourcing with Sparse Checkpointing

To avoid rapid SQLite file bloat, snapshots must NOT be written on every single tick.

1. **`events` Table (Append-Only Source of Truth)**:
   - Stores every [`SimulationEvent`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/models.py#L269) with index `(branch_id, sequence)`.
2. **`branches` Table (Active Head State)**:
   - Stores the latest serialized state JSON for each branch.
3. **`snapshots` Table (Periodic Checkpoints)**:
   - Created **every 5 or 10 simulated days**, on **Player Interventions**, and upon **Branch Forks**.
   - Checkpoint records contain SHA-256 integrity hashes for accidental corruption detection.
4. **`timeline_metrics` Table (Analytical Counterfactuals)**:
   - Denormalized summary written once per tick for instant frontend charting and branch comparisons:
   ```sql
   CREATE TABLE IF NOT EXISTS timeline_metrics (
       branch_id TEXT NOT NULL,
       tick INTEGER NOT NULL,
       sequence INTEGER NOT NULL,
       avg_hunger REAL NOT NULL,
       bread_price_median INTEGER NOT NULL,
       total_circulating_cash INTEGER NOT NULL,
       unemployed_count INTEGER NOT NULL,
       PRIMARY KEY (branch_id, tick)
   );
   ```

---

## 5. AI Agent Deliberation & Observation Protocol

### 5.1 Egocentric Fog-of-War Projection

Under [`queries.observe()`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/queries.py#L29), citizens must only observe information available to them locally:

- **Personal State**: Money, hunger, personal inventory, occupation, goal weights.
- **Public Environment**: Posted prices of local bakeries/markets, vacant plots.
- **Direct Social Ties**: Relationships with citizens they have met or conversed with.
- **Recent Memories**: The last 8 interaction records (messages sent/received, rejected proposals).
- **Strict Prohibition**: Citizens must NEVER observe other citizens' private bank balances, internal thoughts, or unexpressed goal weights.

### 5.2 Salience Scoring (When to Prompt AI)

Rather than round-robin polling, agent deliberation should be triggered by a **Salience Score**:

$$\text{Salience} = w_{\text{bio}} \Delta \text{Hunger} + w_{\text{econ}} \Delta \text{Wealth} + w_{\text{soc}} \mathbb{I}_{\text{Interaction}} + w_{\text{civ}} \mathbb{I}_{\text{Referendum}}$$

- **Primary Triggers**:
  - Employer missed payroll or citizen became unemployed.
  - Business cash dropped below $2\times$ daily wage bill or bread stock hit zero.
  - Received a trade offer, loan proposal, or alliance request.
  - A town vote opened.

### 5.3 Tolerant Precondition Validation

Because an LLM may take 2 seconds to propose an action while ticks advance in the background:

- Agents must propose **bounded intents** (e.g. `Buy(max_unit_price=600)`).
- When submitting `POST /api/agents/{id}/actions`:
  - If `expected_sequence` is slightly behind, but the target building is still stocked and the price is still $\le \text{max\_unit\_price}$, the engine executes the action rather than issuing an immediate HTTP 409 conflict.

---

## 6. Domain Subsystems Specification

### 6.1 Economics & Financial Systems

#### Money & Wages

- **Daily Wage**: Default 150 cents. Business owners can change it using [`SetWage`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/models.py#L201).
- **Bankruptcy**: A business with unpaid wages for `BANKRUPTCY_DAYS = 3` closes automatically:
  - Remaining cash and inventory transfer to the owner.
  - Employed workers are released (`employer_id = None`).
  - Building is unmounted from the plot and `building_removed` event emits.

#### Credit & Debt ([`Lend`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/models.py#L317), [`Repay`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/models.py#L327))

- Rate is in basis points (`rate_bps`, e.g. 500 = 5.00%).
- Total repayment amount:
  $$\text{DueAmount} = \text{Principal} + \left\lfloor \frac{\text{Principal} \times \text{rate\_bps}}{10000} \right\rfloor$$
- Default handling: Insolvent debtors fail loan settlement. This emits `debt_defaulted`, drops trust to $-100$, and logs a debt violation memory.

---

### 6.2 Social Dynamics & Relationship Networks

Relationships in `Citizen.relationships` must expand beyond scalar trust into multi-axial ties:

```python
class Relationship(Model):
    citizen_id: str
    trust: int = Field(default=0, ge=-100, le=100)  # Honesty & creditworthiness
    affinity: int = Field(default=0, ge=-100, le=100)  # Personal friendship / warmth
    respect: int = Field(default=0, ge=-100, le=100)  # Economic/civic competence
    status: Literal["neutral", "friend", "ally", "rival", "protege", "mentor"] = "neutral"
```

#### Social Actions ([`Interact`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/models.py#L271))

- `befriend`: Increases affinity (+5) and trust (+2).
- `gift`: Transfers `amount` cents; boosts affinity proportional to gift value relative to recipient wealth.
- `ally`: Formalizes mutual voting and trade preferences; requires high mutual trust ($\ge 40$).
- `argue` / `insult`: Decreases affinity (-10) and respect (-5).
- `betray`: Emitted when an ally votes against an agreed proposal or defaults on a loan. Slashes trust by -80.
- `mentor`: Increases protege's research point yield per tick by +25%.

---

### 6.3 Technological Innovations (The Invention DAG)

Inventions are organized as a Directed Acyclic Graph (DAG) with prerequisites and productivity multipliers:

```
                  ┌──────────────────────────────┐
                  │        Invention DAG         │
                  └──────────────┬───────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
       ┌──────────────────┐            ┌──────────────────┐
       │  Crop Rotation   │            │ Heavy Iron Plow  │
       │ (+20% Farm Yield)│            │ (+40% Farm Yield)│
       └─────────┬────────┘            └─────────┬────────┘
                 │                               │
                 └───────────────┬───────────────┘
                                 ▼
                      ┌──────────────────────┐
                      │  Yeast Fermentation  │
                      │ (1 wheat -> 4 bread) │
                      └──────────┬───────────┘
                                 ▼
                      ┌──────────────────────┐
                      │ Granary Preservation │
                      │  (Halves Spoilage)   │
                      └──────────────────────┘
```

#### Research Mechanics ([`Research`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/models.py#L286))

- `mode="money"`: Spends coins to fund experiments directly.
- `mode="time"`: Citizen forfeits daily wage work to dedicate ticks to research.
- **Discovery & Patents**:
  - The first citizen to reach the research point threshold becomes the Patent Holder.
  - Patent holders may use [`LicenseInvention`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/models.py#L304) to grant usage rights in exchange for fee cents.
- **Building Tech Adoption ([`AdoptInvention`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/models.py#L311))**:
  - Business owners install licensed or public-domain technology into their buildings.
  - `Engine._execute(m.Produce)` checks installed building inventions and applies formula multipliers.

---

### 6.4 Civic Governance & Regulatory Controls

#### Referendums ([`ProposeVote`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/models.py#L333), [`CastVote`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/models.py#L341))

- **Kinds**:
  - `market_tax`: Sales tax in basis points on transactions, routed to the village treasury.
  - `bread_price_cap`: Legal ceiling on bread prices in cents.
  - `min_wage`: Legal floor on daily employee compensation in cents.
- **Tally & Invariant Enforcement**:
  - Votes remain open for 3 ticks. Citizens vote based on goal weights (`wealth`, `influence`, `safety`, `reputation`).
  - Once enacted, `Engine._execute(m.SetPrice)` rejects prices exceeding `bread_price_cap`.
  - `Engine._execute(m.Buy)` automatically deducts `market_tax` and transfers it to the municipal treasury.

---

## 7. Action Matrix & Implementation Status

| Action Type               | Engine Status | Verification Rules                                                 | Emitted Events                                  |
| :------------------------ | :------------ | :----------------------------------------------------------------- | :---------------------------------------------- |
| `buy`                     | Supported     | Buyer solvent, seller stocked, price $\le \text{max\_unit\_price}$ | `transaction_completed`                         |
| `sell`                    | Supported     | Seller has inventory, building has cash                            | `transaction_completed`                         |
| `transfer_money`          | Supported     | Sender has funds, recipient exists                                 | `transaction_completed`                         |
| `set_price`               | Supported     | Owner-only, within policy caps                                     | `price_changed`                                 |
| `produce`                 | Supported     | Consumes recipe inputs, generates output                           | `resource_produced`, `resource_consumed`        |
| `consume`                 | Supported     | Citizen has bread, hunger $\ge 20$                                 | `resource_consumed`                             |
| `communicate`             | Supported     | Recipient exists; memory bounded to 8                              | `agent_spoke`, `relationship_changed`           |
| `construct_building`      | Supported     | Vacant plot, 5,000 cents capital                                   | `building_constructed`                          |
| `upgrade_building`        | Supported     | Level $< 3$, 2,500 cents capital                                   | `building_upgraded`                             |
| `move_to`                 | Supported     | Valid waypoint plot                                                | `citizen_moved`                                 |
| `adjust_goals`            | Supported     | Sum renormalised to 100                                            | `goals_changed`                                 |
| `found_business`          | Supported     | Minimum 5,000 cents capital                                        | `building_constructed`, `transaction_completed` |
| `close_business`          | Supported     | Owner-only, assets liquidated to owner                             | `building_removed`, `employment_changed`        |
| `set_wage`                | Supported     | Owner-only, $\ge \text{min\_wage}$ policy                          | `wage_changed`                                  |
| `hire`                    | Supported     | Free slot, candidate unemployed                                    | `employment_changed`                            |
| `fire`                    | Supported     | Target citizen is employee                                         | `employment_changed`                            |
| `apply_job` / `quit_job`  | Planned       | Free slot / target is employed                                     | `employment_changed`                            |
| `trade` / `respond_trade` | Planned       | Both parties possess offered goods                                 | `trade_settled`, `transaction_completed`        |
| `lease_lot` / `set_rent`  | Planned       | Plot vacant / rent within cap                                      | `lease_signed`, `rent_changed`                  |
| `interact`                | Planned       | Valid verbs, gift funds verified                                   | `social_interaction`                            |
| `research`                | Planned       | Valid mode (time or money)                                         | `research_progressed`, `invention_discovered`   |
| `license_invention`       | Planned       | Actor owns patent, fee verified                                    | `invention_licensed`                            |
| `adopt_invention`         | Planned       | Tech licensed or public domain                                     | `invention_adopted`                             |
| `lend` / `repay`          | Planned       | Creditor solvent / loan exists                                     | `loan_issued`, `loan_settled`, `debt_defaulted` |
| `propose_vote` / `vote`   | Planned       | Referendum active, one vote/citizen                                | `vote_proposed`, `vote_cast`, `policy_enacted`  |

---

## 8. Verification & Test Strategy

All simulation engine additions MUST be verified with unit tests under `backend/modules/simulation/tests/`:

1. **Conservation Tests**: Verify that sum of citizen money, building cash, and municipal treasury remains identical before and after trades, wages, and bankruptcies.
2. **Precondition Rejection Tests**: Assert that unauthorized actions, negative balances, and out-of-stock purchases raise [`InvalidAction`](file:///Users/nicholasgonzalez/Documents/khronos/Kronos/backend/modules/simulation/src/kronos_sim/engine.py#L36) with accurate stable error codes.
3. **Deterministic Replay Tests**: Assert that resetting RNG state and replaying an identical action sequence reproduces the exact same world state byte-for-byte.
4. **Contract Synchronization**: After any addition to Pydantic models in `models.py`, regenerate contracts using `make contracts` and verify CI contract drift checks pass (`make check`).
