# Event and synchronization protocol

Every committed event contains `id`, `branch_id`, `tick`, `sequence`, discriminated `type`, typed `payload`, optional `actor_id`/`rationale`, and `causal_refs`. IDs are `branch:sequence`; entity IDs remain stable across ticks and forks. Sequence increases for every event, even multiple interventions at the same tick. Version is the last committed event sequence.

Event variants cover spawn/removal, movement, construction/upgrade/removal, production/consumption, transactions, price changes, communication/relationships, and applied interventions. Spawn/removal variants are reserved engine integration points and are exercised by offline fixtures; the API does not pretend to implement population lifecycle.

`WorldUpdate` always contains a complete `state` plus associated events and matching branch/tick/sequence. A normal frame contains the new event batch; initial HTTP/socket states contain up to 100 recent events. Complete snapshots allow safe convergence across sequence gaps; the event ledger endpoint retrieves durable history if needed.

The browser rejects stale/equal versions and different-branch frames. On every socket reconnection it reloads `/api/world`. Epoch checks invalidate HTTP requests that started before a seek/switch. Historical mode ignores incoming live frames. A branch switch atomically replaces the world and event window, clears selection, and remounts entity animations. It never replays every historical movement. Transport retries use capped exponential backoff.

Playback and active branch are shared server session state. The initiating browser explicitly replaces state after activation; another tab with an old branch rejects foreign frames and must reload or select the active branch. User writes still cannot cross branches because the server checks branch and version. Per-client subscriptions are a future extension.

`rationale` is the agent's stated reason, not proof. Causal references are only emitted for a price change directly caused by the corresponding applied intervention. Full saved state records all outcomes, including hunger changes and RNG; events alone are not claimed to be an exhaustive reducer log.
