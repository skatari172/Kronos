# Database

This directory stores the authoritative SQLite database for local KRONOS simulation state.

## Files

- `kronos.db`: The authoritative SQLite database containing:
  - `branches`: Active and historical branch metadata and serialized world states
  - `snapshots`: Immutable point-in-time state checkpoints with SHA-256 integrity hashes
  - `actions`: Durable pending queue and permanent original proposals / applied or rejected results
  - `events`: Append-only event ledger tracking actions, prices, transactions, and dialogue
  - `settings`: Active timeline pointer and local simulation configuration
- `*.db-wal`, `*.db-shm`: Ephemeral SQLite write-ahead log and shared memory files (ignored by Git)

## Usage

- Seed / initialize the database: `make db-init` (or start the backend with `make backend`)
- Reset local world: `make reset`
- Custom database URL: configured via `KRONOS_DATABASE_URL` in `.env`

## World state schema

The tables are deliberately simple; the world lives as JSON in `branches.state` (latest) and `snapshots.state` (every commit). Its shape is `WorldState` in `backend/modules/simulation/src/kronos_sim/models.py`, mirrored in `backend/contracts/generated/api.ts`. Money is integer cents.

| Field                                                | Contents                                                                                                                                         |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `branch_id`, `tick`, `sequence`, `seed`, `rng_state` | Timeline position and the seeded RNG state                                                                                                       |
| `citizens`                                           | People: money, inventory, hunger, `destitute_days`, job (`employer_id`), goal weights, reputation, memories, relationships, research in progress |
| `buildings`                                          | Businesses: owner, plot, cash, inventory, prices, wage, job slots, unpaid days                                                                   |
| `plots`                                              | Lots: position, owner, tenant, rent, arrears; six seed plots, more opened by the growth step                                                     |
| `resources`                                          | Shared natural stocks (wheat): stock, daily regrowth, cap                                                                                        |
| `job_applications`                                   | Job applications with `status` (`pending`, `hired`, `rejected`); resolved ones are kept                                                          |
| `trade_offers`                                       | Pending citizen-to-citizen trade offers                                                                                                          |
| `loans`                                              | Loans in every status (offered, active, repaid, defaulted, …)                                                                                    |
| `inventions`, `license_offers`                       | Research progress, owners, licensees, adopters; pending license offers                                                                           |
| `votes`, `policies`                                  | Town votes with ballots and tallies; active minimum wage, bread price cap, market tax                                                            |

The v1 core is `citizens`, `buildings`, `plots`, `job_applications`, and the event ledger (see `docs/simulation-design.md`); the other fields and branch history are beyond v1 core and already implemented.

Pending records are branch-scoped and survive restart. A tick saves outcomes, events, the world, and its checkpoint together before broadcasting. Forks inherit committed state and leave pending records on the source branch.

Each `events.data` row is one `SimulationEvent` (see the same models file); agent actions carry an `action_id`.

**Compatibility:** every field added after the first release has a default, so older databases still load. They won't have the newer seed data, though (inventions, plot owners, the leased home). To start fresh with the current seed, run `make reset && make db-init`.
