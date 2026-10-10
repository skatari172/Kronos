# Simulation Engine (`kronos_sim`)

The authoritative simulation module for KRONOS. All mutations pass through this engine; neither the browser nor the LLM agent layer may bypass engine validation.

## Module Structure

- `src/kronos_sim/`:
  - `engine.py`: Pure Python copy-on-write state machine, transaction isolation, action validation, event emission, and the daily growth step (new plots, newcomers, departures, founding, upgrades, renting, cash cap) with its tunable constants.
  - `models.py`: Shared Pydantic contracts (citizens, buildings, world state, actions, events). Source of truth for OpenAPI and TypeScript contracts.
  - `queries.py`: Read-only queries, observation builders (`observe()`), and citizen/business profile projections.
  - `seed.py`: Deterministic initial village generator.
- `tests/`:
  - Unit tests for invariant preservation, transaction rollback, and action validation.

## Architecture & Implementation Specification

The v1 core data model, event types, and growth rules are in `docs/simulation-design.md` ("v1 data model").

For the complete architectural design, invariant rules, and subsystem guides (Economics, Social Graph, Innovation Tree, Civic Governance), refer to:

- [`docs/simulation-engine-spec.md`](../../docs/simulation-engine-spec.md)
- [`docs/simulation-design.md`](../../docs/simulation-design.md)
