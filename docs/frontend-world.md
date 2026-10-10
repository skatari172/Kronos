# Frontend: the living village

The frontend is a full-screen 3D village that grows from a hamlet into a city as the simulation develops. This document describes what each visual system shows, which simulation data drives it, and how to extend it.

**Ground rule (AGENTS.md):** the browser renders snapshots and never invents simulation outcomes. Everything here is either _read from the snapshot_ or _presentation only_ (scenery, animation, villager walking routes). Each section says which.

## Map

| File                                      | Responsibility                                                                                      |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `src/app/App.tsx`                         | Full-screen stage: village, growth badge, tier banner, playback HUD, time-lapse                     |
| `src/app/useSimulation.ts`                | Load, sync, auto-start, playback controls; offline fixture fallback in development                  |
| `src/app/Header.tsx`, `feed.ts`           | Header and the full-screen Chronicle (sample events)                                                |
| `src/app/EntityPanel.tsx`, `profiles.ts`  | Details panel for the selection (live numbers, sample narrative)                                    |
| `src/app/Dashboard.tsx`                   | The earlier panel dashboard, not mounted. Reuse its pieces as HUDs                                  |
| `src/world/Village.tsx`                   | Canvas, lights, camera, simulated entities (businesses, villagers), selection labels                |
| `src/world/BuildingLife.tsx`              | A business's life: construction, upgrades, ruins                                                    |
| `src/world/Ground.tsx`                    | Island tiles, roads, scenery, houses and landmarks, simulation lots, rise-from-the-ground animation |
| `src/world/town.ts`                       | Town plan: hex grid, districts, road network and auto-tiling, places, path-finding                  |
| `src/world/progress.ts`                   | Growth score and tiers (Hamlet → Village → Town → City), `useTown()`                                |
| `src/world/routine.ts`                    | Villager daily life: errands, breaks, homes, builders                                               |
| `src/world/sites.ts`                      | Construction sites currently animating, so routines can send builders                               |
| `src/world/crowd.ts`                      | Keeps villagers a body-width apart                                                                  |
| `src/world/preload.ts`                    | Starts loading every model for every tier at startup                                                |
| `src/world/Models.tsx`                    | Model loading, grass recolour, business dressing per level, dust, animated characters               |
| `src/world/assets.ts`                     | Model registry: business models, character per occupation, animation files, scales                  |
| `src/world/Selection.tsx`, `spring.ts`    | Shared selection ring and spring helper                                                             |
| `src/world/town.test.ts`, `crowd.test.ts` | Growth, road, home, tier-hold, and crowd-spacing invariants                                         |
| `public/models/`                          | KayKit CC0 models, licences, and sources ([README](../frontend/public/models/README.md))            |

## Stage and controls

- **Full screen.** The village fills the window. HUDs float over it.
- **Auto-start.** On the first status poll, if the server clock is paused, the page starts it once (`useSimulation`). A later pause by anyone is respected until reload. Playback is shared server state, so every tab sees the same clock.
- **Bottom HUD:** day and connection, play/pause, one-day step, speed, and **time-lapse**. Time-lapse sets the _real_ simulation to 4× and slowly orbits the camera; stopping it returns to 1×.
- **Header:** brand, the town's current tier ("Oakhaven · Village"), and a **Chronicle** button with a count of new events. The button opens the event stream full screen, with a search box and filter chips (All, Your decrees, Trade, Building, People, Talk, Money, Homes, Losses) showing counts; one large line per event (icon, sentence, day), newest first and scrolling. Clicking an event opens a box explaining why it happened: each person involved (both sides of a trade, a rent, a loan, a vote) with what they wanted and their reasoning. While that box is open the stream behind it freezes; closing it (✕, Esc, or a click outside) lets new events flow in again. The stream is a hard-coded sample for now (`src/app/feed.ts`); swap in the snapshot's events or `GET /api/history/events`.
- **Decrees (the player as the town's god):** a glowing box floats above the village (`src/app/GodBar.tsx`). Plain language ("Cap bread price at 6 coins", "Famine", "Set market tax to 5%") goes to `POST /api/interventions`, which parses it into a validated command and applies it through the engine. An accepted decree drifts down from the box onto the town in gold; when it lands, a column of light strikes the square with shockwaves and sparks (`world/DecreeEffect.tsx`), every villager stops, turns to the square, and cheers for a few seconds, and the decree joins the Chronicle as a gold "Your decree" entry whose why box shows your words and the town's reaction (`rules.ts › reactionTo`, sample copy). A rejected sentence shakes the box and says why. Any text may be typed; the frontend never filters it. Live, it is sent as-is (with a 45 s wait and a pulsing "listening" box, since an AI provider can take ~20 s) and the backend decides what it means. With the default mock provider only its fixed phrasings apply; with `KRONOS_LLM_PROVIDER=anthropic` free-form text is interpreted. Offline, anything is accepted as a preview: known phrasings get an exact summary (`rules.ts › previewCommand`), everything else is recorded in the player's own words. The examples list opens when the box is clicked and closes once something is submitted, an example is picked, or Esc is pressed.
- **Details panel** (right side, a bottom sheet on phones): opens when anything is selected and closes with ✕ or Esc. It stays short and large: a title, a tag (job, business kind and level, home, landmark, or lot), two to four live numbers from the snapshot (coins, job, hunger; owner, cash, bread price or wheat, staff; owner and rent), and for villagers one sample thought from `src/app/profiles.ts`.
- **Tier banner:** "Oakhaven is now a Village", shown for 4 s when the tier rises during play. Seeks and branch switches (a new epoch) set the baseline silently.
- **Selection:** click any business, villager, house, landmark, or lot for a gold ring and the details panel. Click empty ground or press Esc to clear. Nothing floats over the scene.
- **Camera:** drag to orbit, scroll to zoom (very close is allowed). Panning is off.

## Growth tiers (`progress.ts`) — derived from the snapshot

`prosperity(state)` is a pure function of the world state, so every client, historical seek, and branch shows the same town. The simulation itself has no tiers.

| Part       | Points                                    | Source in `WorldState`  |
| ---------- | ----------------------------------------- | ----------------------- |
| Age        | 0.5 per day, up to 240 days               | `tick`                  |
| Businesses | 8 each                                    | `buildings`             |
| Upgrades   | 10 per level above 1                      | `buildings[].level`     |
| Homes      | 6 per leased lot without a business       | `plots[].tenant_id`     |
| Population | 2 per citizen                             | `citizens`              |
| Inventions | 12 per adopting business (beyond v1 core) | `inventions[].adopters` |
| Hardship   | −0.5 per point of average hunger above 60 | `citizens[].hunger`     |

The score is the sum minus 44 (`SEED_OFFSET`), so the seed world (3 businesses, 1 leased home, 7 citizens) starts at exactly zero. Tier thresholds: **Hamlet 0, Village 25, Town 70, City 140**. With the seed world, age alone reaches Village after ~50 days and Town after ~140 if the town stays fed. City needs real development: new businesses, upgrades, homes, newcomers, inventions. A starving town stalls.

**Holding a tier.** Hunger moves daily, so a score near a threshold would flip the town between tiers and shrink and regrow the island. `growthOf` holds a reached tier until the score falls 8 points (`MARGIN`) below its threshold. A new epoch (seek or branch switch) starts from the raw tier. The HUD and the town both use this settled tier.

To tune growth, change `THRESHOLDS`, `MARGIN`, or the weights in `parts`. `town.test.ts` checks the seed world starts as a Hamlet and that a reached tier holds.

## Town plan (`town.ts`) — presentation only

- **Grid.** Pointy-top hexagons from the KayKit hexagon pack at `HEX_SCALE` 1.4: tiles are 2.8 units across, neighbours sit at 60° steps.
- **Districts.** Each cell belongs to a ring by its elliptical distance from the centre (`DISTRICT_LIMITS`). At tier _t_, rings ≤ _t_ are **developed** (roads, houses, landmarks) and ring _t_+1 is a **forest frontier**. Anything further out does not exist yet, so the island itself grows.
- **Roads** are written as walks over the grid (`ROADS`: start cell + list of directions). Each visible road cell picks the `hex_road_*` tile and rotation that matches its visible road neighbours (`ROAD_TILES` lists which edges each tile connects, measured from the tile geometry). Unfinished roads end in dead-end tiles until the next district opens.
- **Houses** stand on developed cells beside a road, facing it. **Landmarks** (`LANDMARKS`: chapel, forge, lumbermill, well) appear when their district develops. The core rectangle around the simulated plots (`CORE`) is kept clear.
- **Places** are the houses and landmarks villagers can visit and players can select. Each tier's list extends the previous one in the same order, so homes stay stable.
- **Layouts are precomputed** for all four tiers (`townAt(tier)`).

When a tier rises, new tiles, roads, and buildings rise out of the ground with dust, in a wave from the centre (`Grow` in `Ground.tsx`). Frontier trees that become houses are swapped.

**Extend:** add a road by appending a `walk(...)` to `ROADS`. Add a landmark by adding its cell and model to `LANDMARKS` and a name to `LANDMARK_NAMES`. Run `pnpm --filter @kronos/web test`; it checks that every road stays reachable at every tier.

## Businesses (`BuildingLife.tsx`) — real events, staged over seconds

The simulation changes a building instantly; the frontend stages that real change:

| Snapshot change                                                    | What you see                                                                                                                                | Duration |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| New building ID (`building_constructed` from construct/found)      | Foundation (`building_stage_A`) → walls (`B`) → frame (`C`) under scaffolding, a dust puff per stage, then the finished building springs up | 7 s      |
| `level` rises (`building_upgraded`)                                | Scaffolding and dust around the building while the new level's annexes and props appear                                                     | 2.8 s    |
| Building ID disappears (`building_removed`: closure or bankruptcy) | It collapses into `building_destroyed` ruins with dust, which then sink away                                                                | 2.6 s    |

- **Builders.** While a site is animating it is registered in `sites.ts`. The villager with occupation **Builder**, and the building's owner, drop their errand, hurry over, and play the hammering animation until it is done.
- **Seeks and branch switches** remount entities with `fresh = false`, so saved buildings appear finished. History never replays construction.
- **Upgrade dressing** (`DRESSING` in `Models.tsx`) extends each business toward the back of its lot:

| Kind   | Level 1                              | Level 2                     | Level 3                    |
| ------ | ------------------------------------ | --------------------------- | -------------------------- |
| Farm   | Windmill, wheat field, sacks, barrow | Second field, barrel, fence | Well, lumber, more fence   |
| Bakery | Tavern-style bakery, barrel, sacks   | Cottage annex, crates       | Second annex, flag, pallet |
| Market | Market stall, crates, barrel         | Tent, long crate            | Second tent, flags, stone  |

- **Facing:** businesses on the south side of the main street are turned to face it. Their dressing stays on the street side, because anything behind them would stand between the building and the camera (which looks from the south-east) and hide it.
- **Label:** name, kind, level, and the bread price for bakeries.

**Extend:** add a building kind by giving it a model in `BUILDING_MODELS` (`assets.ts`) and a `DRESSING` entry. The kind itself comes from `BuildingKind` in `models.py` (simulation owner).

## Lots (`Ground.tsx` › `Lots`) — read from the snapshot

Every plot without a business shows what the simulation says about it:

| `Plot` state              | Shown as                 | Label                                      |
| ------------------------- | ------------------------ | ------------------------------------------ |
| `tenant_id` set           | The tenant's cottage     | "Mira's home" · leased lot · rent per week |
| `owner_id` set, no tenant | Dirt lot with a red flag | "Lot for lease" · owner · rent             |
| No owner                  | Dirt lot                 | "Town land" · open for anyone to build on  |

A change of use (a new lease, a new owner) rebuilds the lot with the rise animation.

Lots are not tied to any hard-coded layout: each one renders at its own `position`, including lots the engine opens at runtime (`plot_opened`). `useTown()` passes every lot position to `withLots` (`town.ts`), which adds grass under a lot past the island's current shore and clears scenery (trees, cottages, landmarks) standing on it.

## Villagers — models from the snapshot, routes presentation only

- **Looks** (`assets.ts`). The seven founders (`citizen-0` … `citizen-6`) look like their trade: Farmer → Farmer_A, Baker → Helper_B, Merchant → Lorekeeper, Farmhand → Farmer_B, Miller → Protagonist_B, Builder → Engineer, Weaver → Hiker. Later arrivals draw from 18 looks (Druid, Protagonist_A, Cleric, Ranger, Helper_A, Knight, Mage, Rogue, Rogue_Hooded, Barbarian, Witch, then the founders' looks). `physique(id)` gives everyone a slightly different height (0.90–1.06), their own strolling pace (0.45–0.95 units/s), a walking style (Walking_A/B/C), and a run (Running_A/B).
- **Animation** (`Models.tsx › CharacterModel`). Every character shares KayKit's `Rig_Medium`, so any of ~45 clips from seven sets (General, MovementBasic, Simulation, Tools, CombatMelee, CombatRanged, MovementAdvanced) plays on anyone. Only clips that are playing or fading out are evaluated, so the large set costs nothing until used. One-shot clips (punch, faint, pick up, spawn…) play once and hold. Speed picks the gait: the villager's walk, or their run above 1.15 units/s; broke villagers sneak.
- **Errands** (`routine.ts`). Each stop is a short pose sequence. Pace follows the errand and the snapshot:

| Errand     | When                                    | Pace          | At the stop                                                                                   |
| ---------- | --------------------------------------- | ------------- | --------------------------------------------------------------------------------------------- |
| Fight      | Picked by the fight director            | Sprint (×2.8) | Fists up, punch / block, hit / kick, dodge                                                    |
| Help build | Builder or owner, while a site animates | Run (×2.6)    | Hammering until it's done                                                                     |
| Faint      | Hunger ≥ 95                             | —             | Collapse, lie there, get up                                                                   |
| Buy bread  | Hunger ≥ 70                             | Hurry (×1.8)  | Pick up a loaf, eat it                                                                        |
| Work       | Has an employer                         | Brisk (×1.3)  | Farm: dig. Bakery: knead, tend. Market: handle goods, toss, tend                              |
| Home       | 15%                                     | Stroll        | Nap (lie down, sleep, get up), sit, or rest                                                   |
| Fishing    | Road ends at the shore exist            | Stroll        | Cast, wait, catch, cheer                                                                      |
| Exercise   | 8%                                      | —             | Push-ups, sit-ups                                                                             |
| Landmarks  | Otherwise                               | Stroll        | Forge: hammer. Lumbermill: chop, saw. Well: draw and drink. Chapel: rest, sit. Cottages: wave |

Villagers sometimes stop on the way to look around or wave (4% per road segment). Anyone with under 1.50 coins sneaks instead of strolling unless in a hurry.

- **Newcomers** rise out of the ground (`Spawn_Ground`) instead of popping in.
- **Fights** (`fights.ts`, HARD-CODED for now). Every 30–55 s the director picks two villagers, a meeting point on the nearest road, and a start time 7 s ahead. Both sprint there, face off, and play a choreographed exchange. Each fight is written into the Chronicle with both sides' grudges (Fights filter). Later this should follow the backend's relationship events (argue, insult, betray, grudges).
- **Decree reactions** (`decrees.ts`). While words fall, everyone stops, turns to the square, and raises their arms to the sky (`Ranged_Magic_Raise`). After the strike they react to what was decreed (`rules.ts › moodOf`): good news (raises, gifts, feasts, harvests, caps) brings cheering and jumping for joy; bad news (famine, drought, price hikes, wage cuts, taxes) brings a flinch, then grumbling.
- **Homes** (`homeOf`). A citizen who leases a lot lives there. Everyone else gets a cottage in citizen-ID order, and it stays the same as the town grows (tested).
- **Starting spots** (`startSpot`). When the scene loads, each villager stands in front of their home, or another cottage, landmark, or business if someone earlier already starts there.
- **No walking through each other** (`crowd.ts`). Each villager keeps at least `PERSONAL_SPACE` (0.42 units) from every other; villagers visiting the same building stand side by side, and a stop counts as reached within a body width. Villagers can still pass through buildings and scenery.
- **These routes are not simulation state.** The simulation still records each citizen's position on the main street. Do not read economic meaning into where a villager walks.

## Testing

- `pnpm --filter @kronos/web test` runs the store tests, `town.test.ts`, `crowd.test.ts`, `routine.test.ts`, and `rules.test.ts`. These cover: growth only adds, roads stay connected, the seed starts as a Hamlet, starvation stalls growth, homes stay stable, a reached tier holds, and seven villagers on one spot spread to a body width apart.
- `make check` runs everything, including the production build.
- To try growth by hand without touching the committed database, start the backend on a scratch database:

  ```sh
  KRONOS_DATABASE_URL=sqlite:////tmp/kronos-test.db uv run python scripts/run_backend.py
  ```

  Then submit actions with `POST /api/actions`, for example `found_business` (Mira, 5,000 capital, on `plot-3`), `upgrade_building`, or `close_business`. Watch the construction, upgrades, and ruins play out.

- `VITE_OFFLINE=true make frontend` runs without the API (it also falls back to this when the API is unreachable). The ⏭ button plays a scripted, clearly labelled fixture story (`src/api/mock.ts`, `STORY`), one step per click, with the step shown in the HUD. In 22 steps it grows the seed hamlet into a City: a new bakery, upgrades to level 3, a leased home, cheaper bread, a bankruptcy, a rebuild on the empty lot, and a bigger wave of newcomers at each tier (3, then 5, then 8: population 7 → 10 → 15 → 23). It reaches Village at step 3, Town at step 8, and City at step 18. The next click after the last step restarts from the seed world. `world.test.ts` checks the story reaches City, grows the population 7 → 10 → 15 → 23 by tier, and then ends.

## Known limits and requests for other owners

- **Committed database (API/history).** `backend/database/kronos.db` is tracked, and the page auto-starts the clock. Running the app locally therefore changes a tracked file. Consider ignoring it, or seeding it on first run.
- **Economy stability (simulation).** In testing, the seed economy starved by about day 60–90 at 4×: average hunger 94, villagers nearly broke, a bakery holding most of the cash, and the market bankrupt. Growth stalls by design when that happens. A healthier money loop would let towns reach Town and City on their own.
- **Lots and population (simulation).** The v1 growth step (`simulation-design.md`) targets this: 2 town-land plots open when every plot is used, newcomers arrive every 3 days while the town is fed, destitute citizens leave, and citizens found, upgrade, and rent on their own. New plots appear through `plot_opened` and are shown by the existing lot rules.
- **More building kinds (simulation).** Chapel, forge, and lumbermill are scenery. Making them `BuildingKind`s would let the existing lifecycle stage them.
- **Loading.** `preload.ts` starts loading every model any tier, upgrade, construction, or lot can show (about 9.5 MB) when the page opens. Each tile, building, and villager also has its own loading boundary, so a model that is still downloading hides only that piece instead of the whole scene.
- **Rendering cost.** A City has ~150 tiles plus scenery as individual objects. If frame rate drops on low-end machines, switch tiles to instanced meshes.
