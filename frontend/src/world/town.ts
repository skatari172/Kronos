/**
 * Presentation-only town around the simulated core: hex island, road network,
 * houses, landmarks, and forest. Only buildings and citizens in the snapshot
 * are simulated; everything here is scenery that villagers can visit.
 */
import { HEX_SCALE, hash } from "./assets";

/** Pointy-top hexagons: neighbours sit one tile width apart at 60° steps. */
const WIDTH = 2 * HEX_SCALE;
const ROW = WIDTH * (Math.sqrt(3) / 2);
const DIRECTIONS = Array.from({ length: 6 }, (_, k) => ({
  x: Math.cos((k * Math.PI) / 3) * WIDTH,
  z: Math.sin((k * Math.PI) / 3) * WIDTH,
}));
const ISLAND = { x: 17.6, z: 10.6 };
/** Keep scenery off the simulated buildings, plots, and citizens' lane. */
const CORE = { x: 6.8, z: 5.4 };

export type Point = { x: number; z: number };
const key = (p: Point) => `${Math.round(p.x * 10)}:${Math.round(p.z * 10)}`;
const step = (p: Point, k: number) => ({
  x: p.x + DIRECTIONS[k].x,
  z: p.z + DIRECTIONS[k].z,
});

/** Road tiles and the edges (direction k at 60k°) each one connects. */
const ROAD_TILES: [string, number[]][] = [
  ["hex_road_M", [3]],
  ["hex_road_A", [0, 3]],
  ["hex_road_B", [3, 5]],
  ["hex_road_C", [3, 4]],
  ["hex_road_D", [1, 3, 5]],
  ["hex_road_E", [0, 3, 5]],
  ["hex_road_F", [0, 1, 3]],
  ["hex_road_G", [2, 3, 4]],
  ["hex_road_H", [0, 2, 3, 4]],
  ["hex_road_I", [1, 2, 4, 5]],
  ["hex_road_J", [0, 1, 2, 3]],
  ["hex_road_K", [1, 2, 3, 4, 5]],
  ["hex_road_L", [0, 1, 2, 3, 4, 5]],
];

/** Pick the tile and sixth-turn whose edges match the neighbours. */
function roadTile(mask: number[]) {
  const wanted = [...mask].sort().join();
  for (const [model, edges] of ROAD_TILES)
    for (let turn = 0; turn < 6; turn++) {
      // Turning a model by +60° moves each of its edges to k - 1.
      const turned = edges.map((k) => (k - turn + 6) % 6).sort();
      if (turned.join() === wanted)
        return { model, rotation: (turn * Math.PI) / 3 };
    }
  return { model: "hex_road_L", rotation: 0 };
}

function walk(start: Point, moves: number[]) {
  const cells = [start];
  for (const k of moves) cells.push(step(cells.at(-1)!, k));
  return cells;
}

const east = (n: number) => Array<number>(n).fill(0);
const ROADS = [
  // Main street: the simulation's lane along z = 0.
  walk({ x: -16.8, z: 0 }, east(12)),
  // Ring road through the outer districts.
  walk({ x: -11.2, z: 0 }, [5, 4, 5, ...east(7), 1, 2, 1]),
  walk({ x: -11.2, z: 0 }, [1, 2, 1, ...east(7), 5, 4, 5]),
  // Side streets between the businesses and plots.
  walk({ x: -2.8, z: 0 }, [5, 4, 5]),
  walk({ x: -2.8, z: 0 }, [1, 2, 1]),
  walk({ x: 2.8, z: 0 }, [2, 1, 2]),
].flat();

const LANDMARKS: Record<string, string> = {
  [key({ x: 0, z: -4 * ROW })]: "building_church_red",
  [key({ x: -12.6, z: -ROW })]: "building_blacksmith_red",
  [key({ x: 12.6, z: ROW })]: "building_lumbermill_red",
  [key({ x: -5.6, z: 2 * ROW })]: "building_well_red",
};
const HOUSES = ["building_home_A_red", "building_home_B_red"];
const FOREST = [
  "trees_A_medium",
  "trees_B_medium",
  "hills_A_trees",
  "trees_B_small",
  "tree_single_A",
  "tree_single_B",
];

/** A building villagers can visit and players can select. */
export type Place = {
  id: string;
  kind: "home" | "landmark";
  name: string;
  /** Road cell in front of the door. */
  road: string;
  at: Point;
};
export type Piece = {
  model: string;
  x: number;
  z: number;
  rotation: number;
  /** Growth ring (0 = core); outer rings appear later. */
  district: number;
  place?: Place;
};

const LANDMARK_NAMES: Record<string, string> = {
  building_church_red: "Oakhaven Chapel",
  building_blacksmith_red: "The Forge",
  building_lumbermill_red: "Riverside Lumbermill",
  building_well_red: "Village Well",
};

/** Districts unlock outward from the core as the settlement grows (see progress.ts). */
const DISTRICT_LIMITS = [0.55, 0.72, 0.88];
const district = (p: Point) => {
  const d = Math.hypot(p.x / ISLAND.x, p.z / ISLAND.z);
  const index = DISTRICT_LIMITS.findIndex((limit) => d < limit);
  return index < 0 ? DISTRICT_LIMITS.length : index;
};

const ISLAND_CELLS = (() => {
  const cells = new Map<string, Point>();
  for (let row = -4; row <= 4; row++)
    for (let col = -7; col <= 7; col++) {
      const p = { x: col * WIDTH + (row % 2 ? WIDTH / 2 : 0), z: row * ROW };
      if ((p.x / ISLAND.x) ** 2 + (p.z / ISLAND.z) ** 2 <= 1)
        cells.set(key(p), p);
    }
  return cells;
})();
const ROAD_CELLS = new Set(ROADS.map(key));

export type Town = ReturnType<typeof layout>;

/**
 * The town at a growth tier: developed districts get roads, houses, and
 * landmarks; the next district out is a forest frontier; beyond is sea.
 */
function layout(tier: number) {
  const visible = new Map(
    [...ISLAND_CELLS].filter(([, p]) => district(p) <= tier + 1),
  );
  const developed = (p: Point) => district(p) <= tier;
  const roadKeys = new Set(
    [...ROAD_CELLS].filter(
      (id) => visible.has(id) && developed(visible.get(id)!),
    ),
  );
  const roads = new Map<string, { at: Point; next: string[] }>();
  const tiles: Piece[] = [];
  const scenery: Piece[] = [];
  const places: Place[] = [];
  const facing = (k: number) => Math.atan2(DIRECTIONS[k].x, DIRECTIONS[k].z);

  for (const [id, p] of visible) {
    const near = DIRECTIONS.map((_, k) => key(step(p, k)));
    const ring = district(p);
    if (roadKeys.has(id)) {
      const mask = near.flatMap((n, k) => (roadKeys.has(n) ? [k] : []));
      tiles.push({ ...p, ...roadTile(mask), district: ring });
      roads.set(id, { at: p, next: mask.map((k) => near[k]) });
      continue;
    }
    tiles.push({ ...p, model: "hex_grass", rotation: 0, district: ring });
    const roadSide = near.findIndex((n) => roadKeys.has(n));
    const edge = near.some((n) => !ISLAND_CELLS.has(n));
    const seed = hash(id);
    const turn = ((seed % 6) * Math.PI) / 3;
    const forest = {
      ...p,
      model: FOREST[seed % FOREST.length],
      rotation: turn,
      district: ring,
    };
    if (!developed(p)) {
      // Frontier: dense forest waiting to be cleared.
      if (seed % 4 !== 0) scenery.push(forest);
    } else if (LANDMARKS[id] && roadSide >= 0) {
      const model = LANDMARKS[id];
      const place: Place = {
        id: `place:${id}`,
        kind: "landmark",
        name: LANDMARK_NAMES[model],
        road: near[roadSide],
        at: p,
      };
      places.push(place);
      scenery.push({
        ...p,
        model,
        rotation: facing(roadSide),
        place,
        district: ring,
      });
    } else if (Math.abs(p.x) <= CORE.x && Math.abs(p.z) <= CORE.z) continue;
    else if (roadSide >= 0 && !edge && seed % 7 !== 0) {
      const place: Place = {
        id: `place:${id}`,
        kind: "home",
        name: "Cottage",
        road: near[roadSide],
        at: p,
      };
      places.push(place);
      scenery.push({
        ...p,
        model: HOUSES[seed % HOUSES.length],
        rotation: facing(roadSide),
        place,
        district: ring,
      });
    } else if (seed % 5 !== 0) scenery.push(forest);
  }
  return { tier, tiles, scenery, roads, places };
}

const TOWNS = [0, 1, 2, 3].map(layout);
// Order places by the tier they first appear in, then by distance from the
// centre: each tier's list extends the previous one, so villagers keep their
// cottages as the town grows (see routine.homeOf).
{
  const since = new Map<string, number>();
  for (const town of TOWNS)
    for (const place of town.places)
      if (!since.has(place.id)) since.set(place.id, town.tier);
  const order = (p: Place) =>
    since.get(p.id)! * 1000 + Math.hypot(p.at.x, p.at.z);
  for (const town of TOWNS) town.places.sort((a, b) => order(a) - order(b));
}
export const MAX_TIER = TOWNS.length - 1;
export const townAt = (tier: number) =>
  TOWNS[Math.max(0, Math.min(MAX_TIER, tier))];

export function nearestRoad(town: Town, p: Point) {
  let best = "";
  let distance = Infinity;
  for (const [id, road] of town.roads) {
    const d = Math.hypot(road.at.x - p.x, road.at.z - p.z);
    if (d < distance) [best, distance] = [id, d];
  }
  return best;
}

/** Shortest route along the roads, as road-cell ids from start to goal. */
export function route(town: Town, start: string, goal: string) {
  const previous = new Map<string, string | null>([[start, null]]);
  const queue = [start];
  while (queue.length) {
    const id = queue.shift()!;
    if (id === goal) break;
    for (const next of town.roads.get(id)?.next ?? [])
      if (!previous.has(next)) {
        previous.set(next, id);
        queue.push(next);
      }
  }
  if (!previous.has(goal)) return [start];
  const path = [goal];
  while (previous.get(path[0])) path.unshift(previous.get(path[0])!);
  return path;
}

/**
 * Turn a road route into walkable points: through the shared edge between
 * cells (so curves are followed), keeping to one side of the road.
 */
export function waypoints(
  town: Town,
  path: string[],
  lane: number,
  end?: Point,
) {
  const centers = path.map((id) => town.roads.get(id)!.at);
  const points: Point[] = [];
  for (let i = 0; i < centers.length - 1; i++) {
    const [a, b] = [centers[i], centers[i + 1]];
    const length = Math.hypot(b.x - a.x, b.z - a.z);
    const side = { x: -(b.z - a.z) / length, z: (b.x - a.x) / length };
    points.push({
      x: (a.x + b.x) / 2 + side.x * lane,
      z: (a.z + b.z) / 2 + side.z * lane,
    });
  }
  const last = centers.at(-1)!;
  if (!end) points.push(last);
  else {
    // Stop at the edge of the road, in front of the destination.
    // Each villager's lane also spreads them along the frontage, so people
    // visiting the same building stand side by side.
    const length = Math.hypot(end.x - last.x, end.z - last.z) || 1;
    const reach = Math.min(1.05, length - 0.9);
    const [ux, uz] = [(end.x - last.x) / length, (end.z - last.z) / length];
    points.push({
      x: last.x + ux * reach - uz * lane * 2,
      z: last.z + uz * reach + ux * lane * 2,
    });
  }
  return points;
}
