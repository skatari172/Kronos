# Frontend: the living village

The frontend is a full-screen 3D village that grows from a hamlet into a city as the simulation develops. This document describes what each visual system shows, which simulation data drives it, and how to extend it.

**Ground rule (AGENTS.md):** the browser renders snapshots and never invents simulation outcomes. Everything here is either _read from the snapshot_ or _presentation only_ (scenery, animation, villager walking routes). Each section says which.

## Map

| File                                                          | Responsibility                                                                                      |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `src/app/App.tsx`                                             | Full-screen stage: village, growth badge, tier banner, playback HUD, time-lapse                     |
| `src/app/useSimulation.ts`                                    | Load, sync, auto-start, playback controls; offline fixture fallback in development                  |
| `src/app/Header.tsx`, `feed.ts`                               | Header and the full-screen Chronicle (sample events)                                                |
| `src/app/EntityPanel.tsx`, `VillagerPanel.tsx`, `profiles.ts` | Details panel; villagers get a five-tab summary (overview, activity, mind, ties, ask)               |
| `src/app/Dashboard.tsx`                                       | The earlier panel dashboard, not mounted. Reuse its pieces as HUDs                                  |
| `src/world/Village.tsx`                                       | Canvas, lights, camera, simulated entities (businesses, villagers), selection labels                |
| `src/world/BuildingLife.tsx`                                  | A business's life: construction, upgrades, ruins                                                    |
| `src/world/Ground.tsx`                                        | Island tiles, roads, scenery, houses and landmarks, simulation lots, rise-from-the-ground animation |
| `src/world/town.ts`                                           | Town plan: hex grid, districts, road network and auto-tiling, places, path-finding                  |
| `src/world/progress.ts`                                       | Growth score and tiers (Hamlet → Village → Town → City), `useTown()`                                |
| `src/world/routine.ts`                                        | Villager daily life: errands, breaks, homes, builders                                               |
| `src/world/sites.ts`                                          | Construction sites currently animating, so routines can send builders                               |
| `src/world/crowd.ts`                                          | Keeps villagers a body-width apart                                                                  |
| `src/world/preload.ts`                                        | Starts loading every model for every tier at startup                                                |
| `src/world/Models.tsx`                                        | Model loading, grass recolour, business dressing per level, dust, animated characters               |
| `src/world/assets.ts`                                         | Model registry: business models, character per occupation, animation files, scales                  |
| `src/world/Selection.tsx`, `spring.ts`                        | Shared selection ring and spring helper                                                             |
| `src/world/town.test.ts`, `crowd.test.ts`                     | Growth, road, home, tier-hold, and crowd-spacing invariants                                         |
| `public/models/`                                              | KayKit CC0 models, licences, and sources ([README](../frontend/public/models/README.md))            |

## Stage and controls

- **Full screen.** The village fills the window. HUDs float over it.
- **Auto-start.** On the first status poll, if the server clock is paused, the page starts it once (`useSimulation`). A later pause by anyone is respected until reload. Playback is shared server state, so every tab sees the same clock.
- **Bottom HUD:** day and connection, play/pause, the speed slider, and **time-lapse**. Time-lapse slowly orbits the camera at the current speed (it starts the clock if paused, and never changes the speed). **Pause** freezes the village as well as the clock (`stores/world.ts › usePlayback`): villagers stand idle where they are, no new fights or conversations start, and live events still waiting to play out across the day wait too, resuming on play. The frontend polls `GET /api/simulation/status` every 2 s only to keep play/pause and speed in sync (another tab may change them); world updates arrive pushed over the WebSocket.
- **Header:** brand, the town's current tier ("Oakhaven · Village"), and a **Chronicle** button with a count of new events. The button opens the event stream full screen, with a search box and filter chips (All, Your decrees, Trade, Building, People, Fights, Talk, Money, Homes, Losses) showing counts; one large line per event (icon, sentence, day), newest first and scrolling. Clicking an event opens a box explaining why it happened: each person involved (both sides of a trade, a rent, a loan, a vote) with what they wanted and their reasoning. While that box is open the stream behind it freezes; closing it (✕, Esc, or a click outside) lets new events flow in again. Live, the stream is built from the backend's committed events (`useLiveChronicle` in `src/app/feed.ts`, mapping in `src/app/chronicle.ts`). On load or a branch change it rebuilds from the last ~4,000 events via `GET /api/events`, then follows the WebSocket. Routine bookkeeping (wages, meals, harvests, movement, a scripted agent's daily loaf, repeated messages) is left out. The "why" box shows the actor's own `rationale` with a source chip (AI agent, Mock agent, Utility rule, Town rule, from the `[source]` prefix the agent service writes) and the other party's latest memory of the actor plus their trust and grudge. Decrees come from the backend's `intervention_applied` event, so they survive reloads. Offline previews, which have no agents, reveal the hard-coded `SAMPLE_EVENTS` instead.
- **World Health, score and the point of no return** (`src/app/score.ts`, bottom bar `WorldHealth.tsx`, `GameOver.tsx`). World Health (0–100, in the bottom bar beside the day, with the score) weighs food (100 − average hunger, 35%), livelihoods (share who can afford the cheapest loaf, 20%), jobs (owners and employees, 20%), harmony (low grudges, 10%) and harvest (field wheat, 15%), and never more than 20 above the food score, so a starving town is always in danger; hovering it opens a card above the bar that lists why it is low, each part as a bar, and the latest points. The score adds a day's health/20 each day, +5 a newcomer, +10 a business, +8 an upgrade, +3 a rented home, +2 a hire, +50 a new tier; it loses 15 when someone leaves, 20 when a business closes, 3 for a lost job, 1 per quarrel, and for each decree (15 for a gift of money, 10 for a feast, 5 otherwise). It is saved per village in the browser. The town is lost when fewer than 3 villagers remain, when no bakery is left and average hunger is 95+, or when health stays under 25 for 3 days: the clock stops and **Oakhaven has fallen** shows the reason, days survived, peak population and final score, with **Start a new village** (`POST /api/simulations`, then activate it, then play; offline the story restarts) or **Keep watching**. Gifts and feasts are zero-sum in the engine (a gift is a tax on businesses and the well-off; a feast eats the bakeries' bread), so handouts can't carry a failing town for free.
- **Soundtrack** (`src/app/music.ts`, header control `MusicControl.tsx`): original ambient piano music composed live with the Web Audio API (no audio files or licences): five tracks (Dawn over Oakhaven, Hearth, Meadow, Lanterns, Rainfall), each with its own key, scale, tempo and chord cycle, played in a loop with a breath between them; melodies are a gentle random walk with long rests, so each performance differs. It starts as soon as the browser allows sound: on load where the site is trusted, otherwise on the first click, key or touch, fading in within a fraction of a second. The header shows the track, a next-track button and mute; mute is remembered per browser and suspends the audio entirely.
- **What you can change** (the ⓘ in the decree box, `GodBar.tsx › PowersHint`): hover or focus it for a card of everything the player can change, grouped (the whole town; businesses and land; people and time), one example each, matching the backend's tools (`kronos_agents/tools.py`). Clicking an example puts it in the box.
- **Decrees (the player as the town's god):** a glowing box floats above the village (`src/app/GodBar.tsx`). Plain language goes to `POST /api/user/query`. The backend's model calls one tool (a town-wide intervention, a business owner's price, wage or hiring, a new citizen, the clock) and the world changes through the engine; when nothing fits ("hello", "what's the weather?", "fly to Mars"), it calls no tool and its reply appears in a card under the box ("Oakhaven answers · nothing changed"), with no strike and no change. Town-wide interventions are written into the Chronicle from the backend's `intervention_applied` event; other tools are recorded when the decree lands (`rules.ts › describeTool`), and their effects arrive as events (a spawned villager walks in, a wage changes). An accepted decree drifts down from the box onto the town in gold; when it lands, a column of light strikes the square with shockwaves and sparks (`world/DecreeEffect.tsx`), every villager stops, turns to the square, and cheers for a few seconds, and the decree joins the Chronicle as a gold "Your decree" entry whose why box shows your words and the town's reaction (`rules.ts › reactionTo`, sample copy). A rejected sentence shakes the box and says why. Any text may be typed; the frontend never filters it. Live, it is sent as-is (with a 45 s wait and a pulsing "listening" box, since an AI provider can take ~20 s) and the backend decides what it means. With the default mock provider only its fixed phrasings apply; with `KRONOS_LLM_PROVIDER=anthropic` free-form text is interpreted. Offline, anything is accepted as a preview: known phrasings get an exact summary (`rules.ts › previewCommand`), everything else is recorded in the player's own words. The examples list opens when the box is clicked and closes once something is submitted, an example is picked, or Esc is pressed.
- **World page** (`src/app/WorldPage.tsx`, the header's **World** button): the town today against its founding (the seed fixture): population, businesses, homes rented, villagers' money, average hunger, bread price, daily wage, wheat and policies, each with an arrow coloured by whether the change is good news. Choosing a card shows **How we got here**: from Day 0 (the founding), every event that changed that part of the world, grouped by day, each as a sentence with the actor's reason and who decided (your decrees in gold with your words). **Everything** is the whole story. Live it reads the full record from `GET /api/events` (up to 30,000 events, pages of 500); offline it uses the preview's events.
- **Speed** (HUD slider, 1× · 2× · 4×): 1× is 30 s a simulated day (`KRONOS_TICK_SECONDS`), slow enough to follow everything; changing it never locks the slider. Each day's live events play out across the day (pops, conversations, chronicle lines), paced by the measured day length, instead of arriving in one burst.
- **Chronicle sidebar** (`src/app/EventSidebar.tsx`, right side): the live event stream, newest first, one line per event with its icon and day. Hovering the list holds it still (new events wait behind an "N new events" pill); clicking a line opens the same "why" box as the full page. **See full screen** opens the full chronicle with search and filters; the » button tucks the sidebar into a tab at the right edge (narrow screens start tucked). With the sidebar open, the decree box, HUD and banners centre in the remaining space, and the camera centres the town there too.
- **Camera framing** (`Village.tsx` › `ResponsiveCamera`): fits the whole landmass into the free space (left of the sidebar, between the decree box and the HUD) by measuring every tile's on-screen footprint, and centres it. It refits only when the land's outline or the screen size changes, so a player's own zoom holds otherwise.
- **Details panel** (left side, a bottom sheet on phones): opens when anything is selected and closes with ✕ or Esc. It stays short and large: a title, a tag (job, business kind and level, home, landmark, or lot), two to four live numbers from the snapshot (coins, job, hunger; owner, cash, bread price or wheat, staff; owner and rent), and, for villagers, a full summary in five tabs (`src/app/VillagerPanel.tsx`):
  - **Overview:** coins, job, home (rents from whom, or lots owned), bread, business owned, reputation, influence and standing (`GET /api/agents/{id}`), hunger, and what's on their mind: their latest decision's reasoning with who decided, else their latest memory.
  - **Activity:** what they did and what happened to them, newest first, from `GET /api/agents/{id}/history` (refreshed each day). Each of their own decisions shows its reasoning and source, and a line counts who decided (for example "Mock agent ×75").
  - **Mind:** personality, goals, priorities (goal weights as bars), memories and the memory summary.
  - **Ties:** their strongest relationships, with trust (−100 to 100, centred) and grudge bars.
  - **Ask:** a question answered by their agent from their own history (`POST /api/agents/{id}/ask`), with how many events it cited. Live only.

  Offline previews use the snapshot and the store's events, with a sample thought from `src/app/profiles.ts`. In the Chronicle's "why" box, a villager's name opens their summary.

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

| Snapshot change                                                    | What you see                                                                                                                                                                                                                                                             | Duration |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- |
| New building ID (`building_constructed` from construct/found)      | A marked lot (dirt and a flag) until the founder walks over and reaches the plot (`sites.ts › arriveAt`; at most 15 s), then foundation (`building_stage_A`) → walls (`B`) → frame (`C`) under scaffolding, a dust puff per stage, then the finished building springs up | 7 s      |
| `level` rises (`building_upgraded`)                                | Scaffolding and dust around the building while the new level's annexes and props appear                                                                                                                                                                                  | 2.8 s    |
| Building ID disappears (`building_removed`: closure or bankruptcy) | It collapses into `building_destroyed` ruins with dust, which then sink away                                                                                                                                                                                             | 2.6 s    |

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

Tiles are identified by their grid cell (`tileKey`), and every added tile is snapped exactly onto the grid, so recomputing the land when a lot opens never remounts an existing tile (which would replay its rise, flicker, and leave buildings floating). New land is dressed like the island (`town.ts › furnish`): a road from each lot out there to the road network along the shortest path over new land or plain island grass (never through houses, landmarks or other lots; joined road tiles re-shaped, and the walking graph extended so villagers can reach it), forest from the island's own tree models on most of the rest, and a cottage now and then beside the new roads. The land is always one piece: `joinLand` (`town.ts`) bridges any separate patch, such as a lot the engine opened past the shore, to the main island along the shortest hex path with grass, then fills coastal notches (sea cells with four or more land neighbours). Lots are not tied to any hard-coded layout: each one renders at its own `position`, including lots the engine opens at runtime (`plot_opened`). `useTown()` passes every lot position to `withLots` (`town.ts`), which adds grass under a lot past the island's current shore and clears scenery (trees, cottages, landmarks) standing on it.

## Villagers — models from the snapshot, routes presentation only

- **Looks** (`assets.ts`). The seven founders (`citizen-0` … `citizen-6`) look like their trade: Farmer → Farmer_A, Baker → Helper_B, Merchant → Lorekeeper, Farmhand → Farmer_B, Miller → Protagonist_B, Builder → Engineer, Weaver → Hiker. Later arrivals draw from 18 looks (Druid, Protagonist_A, Cleric, Ranger, Helper_A, Knight, Mage, Rogue, Rogue_Hooded, Barbarian, Witch, then the founders' looks). `physique(id)` gives everyone a slightly different height (0.90–1.06), their own strolling pace (0.45–0.80 units/s), a walking style (Walking_A/B/C), and a run (Running_A/B).
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
- **Fights** (`fights.ts`). Live, each new `citizen_interacted` event of kind argue, insult or betray is staged as a fight between those two villagers (`useFights.request`; at most 3 waiting, 12 s apart, history replays are never staged). The director picks a meeting point on the nearest road and a start time 7 s ahead; both sprint there, face off, and play a choreographed exchange. The Chronicle entry comes from the event itself (Fights filter). Offline previews, which have no agents, script a fight every 30–55 s between random villagers instead, with hard-coded grudges.
- **Conversations** (`meetings.ts`, staged by `app/stage.ts`). Live, each new `agent_spoke`, friendly `citizen_interacted` (befriend, ally, mentor, gift), `trade_offered` or `loan_offered` event becomes a meeting: both villagers walk to a point on the road between them (4–9 s), face each other for 10 s and play gestures for the kind of exchange (talk, wave, cheer, `give`/`pickup` for gifts and deals; at most 2 at once, 4 waiting, nobody already fighting). A speech bubble over the speaker shows the opening words; halfway through, a reaction badge appears over the listener. Clicking the bubble opens the conversation window (`app/Conversation.tsx`): the words type themselves out, then the speaker's private reasoning (the event's `rationale` and its source), then how the listener took it (their memory of the speaker plus trust and grudge). Live, **Hear their side** asks the listener's own agent (`POST /api/agents/{id}/ask`) and types out the reply with how many events it cited. Replay, and Open either person. Offline previews stage a scripted chat every 20–35 s.
- **Voices** (`app/voice.ts`, backend `routes/voice.py`): only when the player opens a conversation does the speaker say their line aloud, and when they press **Hear their side** the listener answers aloud. Each villager has their own voice: with `ELEVENLABS_API_KEY` set, a young ElevenLabs premade voice matched to each founder's personality (newcomers draw one from a pool by ID), at a natural, slightly brisk pace (ElevenLabs speed 1.08, `voice.SPEED`, played as generated), synthesised by `POST /api/voice` (the key stays on the server; replies cached under `.cache/voice`, so a replay is free); without a key (503), the browser's own speech with a per-villager voice, pitch and pace. While a conversation is open the soundtrack drops about 26 dB (a gain after the loudness processing, so it is not squeezed back up), a speaker icon and glow mark who is talking, and closing the conversation stops it.
- **Thought pops** (`emotes.ts`, `Overlays.tsx`). Each new event a villager caused floats a small icon and caption over them for 5.5 s (at most 3 at once; everyday bread purchases are left to the chronicle): ate a loaf they chose, applied at a business, hired, lost a job, price or wage change, a rejected action (red), founded or expanded a business, rented a home, rethinking goals, research, voting, just arrived.
- **Relationship arcs** (`TieLines.tsx`). With a villager selected, raised arcs run to the 6 people they feel most strongly about (green trust, red grudge, amber mistrust), thicker and brighter when stronger, following everyone as they walk.
- **Decree reactions** (`decrees.ts`). While words fall, everyone stops, turns to the square, and raises their arms to the sky (`Ranged_Magic_Raise`). After the strike they react to what was decreed (`rules.ts › moodOf`, `toolMood` for other tools): good news (raises, gifts, feasts, harvests, caps) brings cheering and jumping for joy; bad news (famine, drought, price hikes, wage cuts, taxes) brings a flinch, then grumbling.
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

- `VITE_OFFLINE=true make frontend` runs without the API (it also falls back to this when the API is unreachable). It plays a scripted, clearly labelled fixture story (`src/api/mock.ts`, `STORY`) on its own: one step every 12 s at 1× (the HUD's play, pause, speed and time-lapse controls work as they do live), with the step shown in the HUD. In 22 steps it grows the seed hamlet into a City: a new bakery, upgrades to level 3, a leased home, cheaper bread, a bankruptcy, a rebuild on the empty lot, and a bigger wave of newcomers at each tier (3, then 5, then 8: population 7 → 10 → 15 → 23). It reaches Village at step 3, Town at step 8, and City at step 18. After the last step it restarts from the seed world. `world.test.ts` checks the story reaches City, grows the population 7 → 10 → 15 → 23 by tier, and then ends.

## Known limits and requests for other owners

- **Committed database (API/history).** `backend/database/kronos.db` is tracked, and the page auto-starts the clock. Running the app locally therefore changes a tracked file. Consider ignoring it, or seeding it on first run.
- **Saved worlds keep their old citizens.** Founder personalities and newcomer names live in the seed (`kronos_sim/seed.py`), so a database created before them still has identical "practical" founders. `make reset` (with the backend stopped) starts a fresh world.
- **Economy stability (simulation).** In testing, the seed economy starved by about day 60–90 at 4×: average hunger 94, villagers nearly broke, a bakery holding most of the cash, and the market bankrupt. Growth stalls by design when that happens. A healthier money loop would let towns reach Town and City on their own.
- **Lots and population (simulation).** The v1 growth step (`simulation-design.md`) targets this: 2 town-land plots open when every plot is used, newcomers arrive every 3 days while the town is fed, destitute citizens leave, and citizens found, upgrade, and rent on their own. New plots appear through `plot_opened` and are shown by the existing lot rules.
- **More building kinds (simulation).** Chapel, forge, and lumbermill are scenery. Making them `BuildingKind`s would let the existing lifecycle stage them.
- **Loading.** `preload.ts` starts loading every model any tier, upgrade, construction, or lot can show (about 9.5 MB) when the page opens. Each tile, building, and villager also has its own loading boundary, so a model that is still downloading hides only that piece instead of the whole scene.
- **Rendering cost.** A City has ~150 tiles plus scenery as individual objects. If frame rate drops on low-end machines, switch tiles to instanced meshes.
