# Village models

All models are by Kay Lousberg (KayKit, [kaylousberg.com](https://www.kaylousberg.com)) and licensed **CC0 1.0**: free for commercial use, no attribution required. The original license text sits beside each set. Only the files the village uses are committed.

| Folder              | Source pack                                                                                  | Pinned source                                                                                                                                                                         |
| ------------------- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `kaykit/hexagon`    | KayKit Medieval Hexagon Pack 1.0 (official repository)                                       | [KayKit-Game-Assets/KayKit-Medieval-Hexagon-Pack-1.0 @ 84fa4e9](https://github.com/KayKit-Game-Assets/KayKit-Medieval-Hexagon-Pack-1.0/tree/84fa4e91af6a88989be7c99e0891cede11f2ca38) |
| `kaykit/characters` | KayKit Adventurers 2.0, Mystery Monthly series 5–6, Character Animations 1.1 (collection v6) | [GeorgeQLe/assets-kaykit-3d-characters @ af08a62](https://github.com/GeorgeQLe/assets-kaykit-3d-characters/tree/af08a62d3669370ec4636ae6314b38cdcd5dd759) (community mirror)          |

The KayKit itch.io pages hold the official downloads for every pack.

## How the village uses them

`src/world/assets.ts` is the single registry: building per business kind, character per occupation, animation files, and scale constants. To add or swap a model, copy its `.gltf` + `.bin` (hexagon pack, which shares `hexagons_medieval.png`) or `.glb` (characters) here and reference it there.

- **Buildings** use the hexagon pack's red set at `HEX_SCALE`. One hex tile is 2 units across in pack units.
- **Characters** share the KayKit `Rig_Medium` skeleton, so any clip in the seven `Rig_Medium_*.glb` animation files (General, MovementBasic, Simulation, Tools, CombatMelee, CombatRanged, MovementAdvanced) plays on any character. The Special set (skeleton clips) is in the mirror under `character-animations-1.1`.
- **Construction** uses `building_stage_A/B/C`, `building_scaffolding`, and `building_destroyed` from the hexagon pack's neutral set.
- Clips are in place (no root motion). The renderer moves villagers and blends idle → walk → run from their speed.
- **Town scenery** (`src/world/town.ts`, rendered by `Ground.tsx`) is presentation only and grows by tier; see [docs/frontend-world.md](../../../docs/frontend-world.md).
- **Daily life** (`src/world/routine.ts`) is presentation only: villagers walk the road graph between work, home, the bakery, landmarks, and construction sites, with poses from `Rig_Medium_Simulation.glb` and `Rig_Medium_Tools.glb`.
- Grass UVs are remapped at load time from the atlas's olive swatch to its green swatch (`Models.tsx`); the source files are unmodified.

Keep the animated outer group, stable entity IDs, click handlers, and ground-plane x/z coordinates. Do not mix animation time with authoritative tick time.
