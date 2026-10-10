# Demo guide

## A price change with consequences

1. Start `make backend` and `make frontend`, open localhost:5173. The badge reads WORLD CONNECTED.
2. Click Hearth & Grain to inspect the 5.00-coin bread price.
3. Select the +40% suggestion and submit it. The label and inspector become 7.00, and the chronicle records the intervention and price event.
4. Step twice. Initial citizens start with one loaf, so the second day of consumption exposes affordability differences. Finn has 5.50 coins and no employer; he cannot buy a 7.00-coin loaf. There is no scripted riot or predetermined narrative.
5. Open a ledger row to see its typed payload, version, and causal references.
6. Advance to the third tick for one mock neighbor conversation, stored memories, and increased familiarity.

## Construction and alternate history

1. While paused, click Build a bakery. Marcus spends 50 coins, a free plot becomes occupied, and a new structure grows into view.
2. Move the historical checkpoint slider to origin. Playback pauses and the scene replaces its current state without replaying animations.
3. Click Fork here. The new branch starts from that checkpoint with the same RNG state and stable entity IDs.
4. Apply a different price change and step. Switch to Original timeline to see the preserved original state.
5. Restart the API. It recovers the active branch and latest committed world from SQLite.

## Offline visual fallback

Stop the API and reload the Vite development page, or use `VITE_OFFLINE=true make frontend`. The badge explicitly reads OFFLINE DEMO. Click Next visual event six times: construction, upgrade, citizen arrival, movement, price change, departure. Selection/inspection still works. These are development fixtures; live simulation, intervention, and history controls are disabled. A real mock AI provider is also the default on the backend, so no LLM credentials are ever necessary for the live flow.
