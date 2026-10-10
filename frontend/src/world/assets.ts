/** KayKit model registry. Sources and licenses: public/models/README.md. */
import type { Building, Citizen } from "../api/types";

const HEX = "/models/kaykit/hexagon";
const CHARACTERS = "/models/kaykit/characters";

export const hex = (name: string) => `${HEX}/${name}.gltf`;

/** Hexagon pack units: one tile is 2 units wide. */
export const HEX_SCALE = 1.4;
/** Characters are ~2.4 units tall in the source rig. */
export const CHARACTER_SCALE = 0.36;

export const BUILDING_MODELS: Record<Building["kind"], string> = {
  farm: hex("building_windmill_red"),
  bakery: hex("building_tavern_red"),
  market: hex("building_market_red"),
};

type Prop = {
  model: string;
  at: [number, number];
  turn?: number;
  size?: number;
  /** Building level at which this piece appears. */
  level?: 2 | 3;
};

// Local dressing per business, in hexagon units before HEX_SCALE (+z faces the
// street). Upgrades (simulation levels 2 and 3) extend the business toward the
// back of its lot instead of just scaling it, so neighbours never overlap.
export const BUSINESS_DRESSING: Record<Building["kind"], Prop[]> = {
  farm: [
    { model: "building_grain", at: [-1.15, -0.85], size: 0.62 },
    { model: "sack", at: [0.62, 0.42], turn: 0.4 },
    { model: "sack", at: [0.72, 0.28], turn: 1.2 },
    { model: "wheelbarrow", at: [-0.62, 0.5], turn: 2.2 },
    { model: "building_grain", at: [0.15, -1.3], size: 0.55, level: 2 },
    { model: "barrel", at: [0.42, 0.62], level: 2 },
    { model: "fence_wood_straight", at: [-1.6, -0.75], size: 0.9, level: 2 },
    { model: "building_well_red", at: [0.95, -0.55], size: 0.5, level: 3 },
    { model: "resource_lumber", at: [-1.15, 0.45], turn: 0.5, level: 3 },
    {
      model: "fence_wood_straight",
      at: [0.75, -1.45],
      size: 0.9,
      turn: 1.57,
      level: 3,
    },
  ],
  bakery: [
    { model: "barrel", at: [0.66, 0.42] },
    { model: "sack", at: [-0.62, 0.5], turn: 0.8 },
    { model: "sack", at: [-0.5, 0.58], turn: 2.1 },
    {
      model: "building_home_A_red",
      at: [-0.45, -1.1],
      size: 0.72,
      turn: 0.3,
      level: 2,
    },
    { model: "crate_long_A", at: [-0.75, 0.55], turn: 1.6, level: 2 },
    {
      model: "building_home_B_red",
      at: [0.6, -1.05],
      size: 0.7,
      turn: -0.3,
      level: 3,
    },
    { model: "flag_red", at: [0.35, 0.72], size: 1.4, level: 3 },
    { model: "pallet", at: [0.95, 0.55], level: 3 },
  ],
  market: [
    { model: "crate_A_small", at: [-0.98, 0.42], turn: 0.3 },
    { model: "barrel", at: [0.98, 0.38] },
    { model: "sack", at: [0.86, 0.56], turn: 1.4 },
    { model: "tent", at: [-0.65, -1.0], size: 1.5, turn: 0.5, level: 2 },
    { model: "crate_long_A", at: [-0.2, -0.95], turn: 0.2, level: 2 },
    { model: "tent", at: [0.7, -1.05], size: 1.5, turn: -0.4, level: 3 },
    { model: "flag_red", at: [-0.6, 0.7], size: 1.4, level: 3 },
    { model: "flag_red", at: [0.6, 0.7], size: 1.4, level: 3 },
    { model: "resource_stone", at: [1.15, -0.55], level: 3 },
  ],
};

/** Construction stages, scaffolding, and ruins (see BuildingLife.tsx). */
export const CONSTRUCTION_STAGES = [
  "building_stage_A",
  "building_stage_B",
  "building_stage_C",
];
export const LIFECYCLE_MODELS = [
  ...CONSTRUCTION_STAGES,
  "building_scaffolding",
  "building_destroyed",
];
/** Lot markers (see Ground.tsx Lots). */
export const LOT_MODELS = ["building_dirt", "flag_red", "building_home_B_red"];

export const ANIMATION_FILES = [
  `${CHARACTERS}/Rig_Medium_General.glb`,
  `${CHARACTERS}/Rig_Medium_MovementBasic.glb`,
  `${CHARACTERS}/Rig_Medium_Simulation.glb`,
  `${CHARACTERS}/Rig_Medium_Tools.glb`,
  `${CHARACTERS}/Rig_Medium_CombatMelee.glb`,
  `${CHARACTERS}/Rig_Medium_CombatRanged.glb`,
  `${CHARACTERS}/Rig_Medium_MovementAdvanced.glb`,
];

const BY_OCCUPATION: Record<string, string> = {
  Farmer: "Farmer_A",
  Baker: "Helper_B",
  Merchant: "Lorekeeper",
  Farmhand: "Farmer_B",
  Miller: "Protagonist_B",
  Builder: "Engineer",
  Weaver: "Hiker",
};
/** Newcomers draw from every look, starting with ones the founders do not use. */
const NEWCOMERS = [
  "Druid",
  "Protagonist_A",
  "Cleric",
  "Ranger",
  "Helper_A",
  "Knight",
  "Mage",
  "Rogue",
  "Rogue_Hooded",
  "Barbarian",
  "Witch",
  ...Object.values(BY_OCCUPATION),
];
export const CHARACTER_FILES = [...new Set(NEWCOMERS)].map(
  (name) => `${CHARACTERS}/${name}.glb`,
);

/** Stable per-entity number for presentation-only variation. */
export function hash(id: string) {
  let h = 0;
  for (const char of id) h = (h * 31 + char.charCodeAt(0)) >>> 0;
  return h;
}

/** The seed's seven founders (`citizen-0` … `citizen-6`). */
const FOUNDER = /^citizen-[0-6]$/;

export function characterModel(citizen: Citizen) {
  // Founders look like their trade; everyone who arrives later varies.
  const name = FOUNDER.test(citizen.id)
    ? (BY_OCCUPATION[citizen.occupation] ?? NEWCOMERS[0])
    : NEWCOMERS[hash(citizen.id) % NEWCOMERS.length];
  return `${CHARACTERS}/${name}.glb`;
}

/**
 * Presentation-only body and gait for a villager, stable per ID: height
 * varies a little, and everyone has their own pace and walking style so a
 * crowd never moves in lockstep.
 */
export function physique(id: string) {
  // Mix the bits: IDs often differ only in their last character.
  let h = hash(id);
  h = Math.imul(h ^ (h >>> 16), 0x45d9f3b);
  h = Math.imul(h ^ (h >>> 16), 0x45d9f3b);
  h = (h ^ (h >>> 16)) >>> 0;
  return {
    height: 0.9 + ((h >>> 4) % 17) / 100, // 0.90–1.06
    /** Strolling speed in world units per second. */
    pace: 0.45 + ((h >>> 8) % 11) * 0.05, // 0.45–0.95
    walk: (["walkA", "walkB", "walkC"] as const)[(h >>> 12) % 3],
    run: (["runA", "runB"] as const)[(h >>> 14) % 2],
  };
}
