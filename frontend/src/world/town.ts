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
/** A tile's identity: its grid cell, so tiny float differences never make a "new" tile. */
export const tileKey = key;
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
  // Beside the main street, clear of the simulated plots and their upgrades.
  [key({ x: -7, z: ROW })]: "building_well_red",
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
  // Road ends at the island's edge: villagers fish there, facing the water.
  const shore: { road: string; at: Point }[] = [];
  for (const [id, road] of roads) {
    const open = DIRECTIONS.findIndex(
      (_, k) => !ISLAND_CELLS.has(key(step(road.at, k))),
    );
    if (road.next.length === 1 && open >= 0)
      shore.push({
        road: id,
        at: {
          x: road.at.x + DIRECTIONS[open].x * 0.38,
          z: road.at.z + DIRECTIONS[open].z * 0.38,
        },
      });
  }
  return { tier, tiles, scenery, roads, places, shore };
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

/** Hex cells whose centre lies within `radius` of a point, nearest first. */
function cellsNear(p: Point, radius: number) {
  const cells: Point[] = [];
  const row0 = Math.round(p.z / ROW);
  for (let row = row0 - 1; row <= row0 + 1; row++) {
    const offset = row % 2 ? WIDTH / 2 : 0;
    const col0 = Math.round((p.x - offset) / WIDTH);
    for (let col = col0 - 1; col <= col0 + 1; col++)
      cells.push({ x: col * WIDTH + offset, z: row * ROW });
  }
  const distance = (c: Point) => Math.hypot(c.x - p.x, c.z - p.z);
  cells.sort((a, b) => distance(a) - distance(b));
  // The nearest cell always holds the lot; neighbours only if it overhangs.
  return cells.filter((c, i) => i === 0 || distance(c) < radius);
}

/** Convex outline of points (Andrew's monotone chain), counter-clockwise. */
function convexHull(points: Point[]): Point[] {
  const sorted = [...points].sort((a, b) => a.x - b.x || a.z - b.z);
  if (sorted.length < 3) return sorted;
  const cross = (o: Point, a: Point, b: Point) =>
    (a.x - o.x) * (b.z - o.z) - (a.z - o.z) * (b.x - o.x);
  const half = (list: Point[]) => {
    const out: Point[] = [];
    for (const p of list) {
      while (
        out.length >= 2 &&
        cross(out[out.length - 2], out[out.length - 1], p) <= 0
      )
        out.pop();
      out.push(p);
    }
    out.pop();
    return out;
  };
  return [...half(sorted), ...half([...sorted].reverse())];
}

/** Inside a counter-clockwise convex outline, allowing `pad` beyond its edges. */
function insideHull(hull: Point[], p: Point, pad: number) {
  if (hull.length < 3) return false;
  for (let i = 0; i < hull.length; i++) {
    const a = hull[i];
    const b = hull[(i + 1) % hull.length];
    const edge = Math.hypot(b.x - a.x, b.z - a.z) || 1;
    // Signed distance to the edge's line; negative is outside.
    const side = ((b.x - a.x) * (p.z - a.z) - (b.z - a.z) * (p.x - a.x)) / edge;
    if (side < -pad) return false;
  }
  return true;
}

/**
 * Make the land one piece: bridge every separate patch (lots opened past the
 * shore) to the main island along the shortest hex path, then fill everything
 * inside the land's convex outline, so the town is one solid area with no thin
 * strips or notches. Adds plain grass tiles to `tiles` in place.
 */
export function joinLand(tiles: Piece[]) {
  const land = new Map(tiles.map((t) => [key(t), { x: t.x, z: t.z }]));
  // Every added cell sits exactly on the grid, so the same cell always gets the
  // same position however it was reached (no remounts, no replayed growth).
  const snap = (p: Point): Point => {
    const row = Math.round(p.z / ROW);
    const offset = row % 2 ? WIDTH / 2 : 0;
    return {
      x: Math.round((p.x - offset) / WIDTH) * WIDTH + offset,
      z: row * ROW,
    };
  };
  const add = (p: Point) => {
    const cell = snap(p);
    land.set(key(cell), cell);
    tiles.push({
      ...cell,
      model: "hex_grass",
      rotation: 0,
      district: district(cell),
    });
  };
  const near = (p: Point) => [0, 1, 2, 3, 4, 5].map((k) => snap(step(p, k)));
  const patches = () => {
    const seen = new Set<string>();
    const out: Point[][] = [];
    for (const [id, start] of land) {
      if (seen.has(id)) continue;
      seen.add(id);
      const patch: Point[] = [];
      const queue = [start];
      while (queue.length) {
        const cell = queue.pop()!;
        patch.push(cell);
        for (const n of near(cell)) {
          const nk = key(n);
          if (land.has(nk) && !seen.has(nk)) {
            seen.add(nk);
            queue.push(land.get(nk)!);
          }
        }
      }
      out.push(patch);
    }
    return out.sort((a, b) => b.length - a.length);
  };
  const gap = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.z - b.z);

  for (
    let parts = patches(), guard = 0;
    parts.length > 1 && guard < 50;
    guard++
  ) {
    const [main, island] = parts;
    const inMain = new Set(main.map(key));
    let from = island[0];
    let to = main[0];
    for (const a of island)
      for (const b of main) if (gap(a, b) < gap(from, to)) [from, to] = [a, b];
    // Walk hex by hex toward the main island, laying grass where there is sea.
    for (let cell = from, n = 0; !inMain.has(key(cell)) && n < 40; n++) {
      cell = near(cell).reduce((best, c) =>
        gap(c, to) < gap(best, to) ? c : best,
      );
      if (!land.has(key(cell))) add(cell);
    }
    parts = patches();
  }

  // One solid area: fill every cell inside the convex outline of all the land
  // (the island and every lot), so far-off lots never hang off on a thin strip.
  const hull = convexHull([...land.values()]);
  const pad = WIDTH * 0.45;
  const xs = [...land.values()].map((p) => p.x);
  const zs = [...land.values()].map((p) => p.z);
  const [r0, r1] = [
    Math.floor(Math.min(...zs) / ROW),
    Math.ceil(Math.max(...zs) / ROW),
  ];
  for (let row = r0; row <= r1; row++) {
    const offset = row % 2 ? WIDTH / 2 : 0;
    const c0 = Math.floor((Math.min(...xs) - offset) / WIDTH);
    const c1 = Math.ceil((Math.max(...xs) - offset) / WIDTH);
    for (let col = c0; col <= c1; col++) {
      const cell = { x: col * WIDTH + offset, z: row * ROW };
      if (!land.has(key(cell)) && insideHull(hull, cell, pad)) add(cell);
    }
  }
}

/**
 * Dress land added past the island (`base` is the town before lots): pave a
 * road from each lot out there to the road network along the shortest path
 * over the new land (re-shaping the road tiles it joins), then forest the rest
 * with the island's own trees, with a cottage now and then beside the new
 * roads. Deterministic per cell, so the same land always looks the same.
 */
function furnish(town: Town, base: Town, lots: Point[]): Town {
  const snapCell = (p: Point): Point => {
    const row = Math.round(p.z / ROW);
    const offset = row % 2 ? WIDTH / 2 : 0;
    return {
      x: Math.round((p.x - offset) / WIDTH) * WIDTH + offset,
      z: row * ROW,
    };
  };
  const index = new Map(town.tiles.map((t, i) => [key(t), i]));
  const baseKeys = new Set(base.tiles.map(key));
  const added = new Set(
    town.tiles.filter((t) => !baseKeys.has(key(t))).map(key),
  );
  const cellOf = (id: string) => town.tiles[index.get(id)!];
  const around = (p: Point) =>
    [0, 1, 2, 3, 4, 5].map((k) => key(snapCell(step(p, k))));
  const lotCells = new Set(lots.map((lot) => key(snapCell(lot))));
  const placeCells = new Set(town.places.map((p) => key(p.at)));
  const paveable = (id: string) =>
    cellOf(id)?.model === "hex_grass" && !placeCells.has(id);
  const roads = new Set(town.roads.keys());
  const fresh = new Set<string>();

  // Roads: nearest lots first, so farther ones can join the new roads.
  const outward = [...lots].sort(
    (a, b) => Math.hypot(a.x, a.z) - Math.hypot(b.x, b.z),
  );
  for (const lot of outward) {
    const start = key(snapCell(lot));
    if (around(snapCell(lot)).some((n) => roads.has(n))) continue;
    const previous = new Map<string, string | null>([[start, null]]);
    const queue = [start];
    let reached: string | null = null;
    while (queue.length && !reached) {
      const id = queue.shift()!;
      for (const next of around(cellOf(id) ?? snapCell(lot))) {
        if (previous.has(next) || !index.has(next)) continue;
        previous.set(next, id);
        if (roads.has(next)) {
          reached = next;
          break;
        }
        // Pave new land, or plain island grass with no house or landmark on
        // it; never another lot.
        if (!lotCells.has(next) && (added.has(next) || paveable(next)))
          queue.push(next);
      }
    }
    if (!reached) continue;
    for (
      let id = previous.get(reached);
      id && id !== start;
      id = previous.get(id)
    )
      if (!roads.has(id)) {
        roads.add(id);
        fresh.add(id);
      }
  }

  // Road tiles and the walking graph for new roads and the roads they join.
  const graph = new Map(town.roads);
  const tiles = [...town.tiles];
  const touched = new Set(fresh);
  for (const id of fresh)
    for (const n of around(cellOf(id))) if (roads.has(n)) touched.add(n);
  for (const id of touched) {
    const cell = cellOf(id);
    const near = around(cell);
    const mask = near.flatMap((n, k) => (roads.has(n) ? [k] : []));
    tiles[index.get(id)!] = {
      ...cell,
      ...roadTile(mask),
      district: cell.district,
    };
    graph.set(id, {
      at: { x: cell.x, z: cell.z },
      next: mask.map((k) => near[k]),
    });
  }

  // Forest and cottages on the rest of the new land, clear of the lots; any
  // trees standing where a new road now runs are cleared.
  const scenery = town.scenery.filter((piece) => !fresh.has(key(piece)));
  const places = [...town.places];
  const facing = (k: number) => Math.atan2(DIRECTIONS[k].x, DIRECTIONS[k].z);
  for (const id of added) {
    if (roads.has(id)) continue;
    const cell = cellOf(id);
    if (
      lots.some(
        (lot) => Math.hypot(lot.x - cell.x, lot.z - cell.z) < LOT_CLEARANCE,
      )
    )
      continue;
    const seed = hash(id);
    const roadSide = around(cell).findIndex((n) => fresh.has(n));
    if (roadSide >= 0 && seed % 4 === 0) {
      const place: Place = {
        id: `place:${id}`,
        kind: "home",
        name: "Cottage",
        road: around(cell)[roadSide],
        at: { x: cell.x, z: cell.z },
      };
      places.push(place);
      scenery.push({
        x: cell.x,
        z: cell.z,
        model: HOUSES[seed % HOUSES.length],
        rotation: facing(roadSide),
        place,
        district: cell.district,
      });
    } else if (seed % 3 !== 0)
      scenery.push({
        x: cell.x,
        z: cell.z,
        model: FOREST[seed % FOREST.length],
        rotation: ((seed % 6) * Math.PI) / 3,
        district: cell.district,
      });
  }
  return { ...town, tiles, scenery, places, roads: graph };
}

/** Scenery closer than this to a lot would stand inside its building. */
const LOT_CLEARANCE = WIDTH * 0.8;
const fitted = new Map<string, Town>();

/**
 * The town with room for the simulation's lots. The engine may open new lots
 * anywhere (new town land at the edge of the village), so every lot gets
 * ground under it, even past the island's current shore, and no scenery
 * stands on it. Cottages cleared for a lot also stop being homes.
 */
export function withLots(town: Town, lots: Point[]): Town {
  const id = `${town.tier}|${lots.map(key).sort().join(";")}`;
  const cached = fitted.get(id);
  if (cached) return cached;
  const near = (p: Point) =>
    lots.some((lot) => Math.hypot(lot.x - p.x, lot.z - p.z) < LOT_CLEARANCE);
  const scenery = town.scenery.filter((piece) => !near(piece));
  const tiles = [...town.tiles];
  const covered = new Set(tiles.map(key));
  for (const lot of lots)
    for (const cell of cellsNear(lot, LOT_CLEARANCE))
      if (!covered.has(key(cell))) {
        covered.add(key(cell));
        tiles.push({
          ...cell,
          model: "hex_grass",
          rotation: 0,
          district: district(cell),
        });
      }
  let result: Town = {
    ...town,
    tiles,
    scenery,
    places: town.places.filter((place) => !near(place.at)),
  };
  // Only lots past the shore reshape the land; the island alone stays as
  // designed. New land then gets what the rest of the town has: roads to its
  // lots, forest, and the odd cottage.
  if (tiles.length > town.tiles.length) {
    joinLand(tiles);
    result = furnish(result, town, lots);
  }
  if (fitted.size > 64) fitted.clear();
  fitted.set(id, result);
  return result;
}

/** The middle of the land (its bounding box), where the camera centres and decrees strike. */
export function landCentre(town: Town): Point {
  const xs = town.tiles.map((t) => t.x);
  const zs = town.tiles.map((t) => t.z);
  if (!xs.length) return { x: 0, z: 0 };
  return {
    x: (Math.min(...xs) + Math.max(...xs)) / 2,
    z: (Math.min(...zs) + Math.max(...zs)) / 2,
  };
}
