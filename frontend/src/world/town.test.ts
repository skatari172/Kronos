import { describe, expect, it } from "vitest";
import { initialMock } from "../api/mock";
import { growthOf, prosperity } from "./progress";
import { homeOf } from "./routine";
import {
  MAX_TIER,
  nearestRoad,
  route,
  tileKey,
  townAt,
  withLots,
} from "./town";

describe("town growth", () => {
  it("only ever adds ground, roads, and places as tiers rise", () => {
    // The island stops growing once the outermost ring is visible as forest;
    // the last tier develops that ring instead.
    for (let tier = 1; tier <= MAX_TIER; tier++) {
      const [before, after] = [townAt(tier - 1), townAt(tier)];
      expect(after.tiles.length).toBeGreaterThanOrEqual(before.tiles.length);
      expect(after.roads.size).toBeGreaterThan(before.roads.size);
      for (const id of before.roads.keys())
        expect(after.roads.has(id)).toBe(true);
      const ids = after.places.map((p) => p.id);
      // Each tier's places start with the previous tier's, in the same order.
      expect(ids.slice(0, before.places.length)).toEqual(
        before.places.map((p) => p.id),
      );
    }
  });

  it("keeps every road reachable from the main street at every tier", () => {
    for (let tier = 0; tier <= MAX_TIER; tier++) {
      const town = townAt(tier);
      const [start] = town.roads.keys();
      for (const id of town.roads.keys())
        expect(route(town, start, id).at(-1)).toBe(id);
    }
  });

  it("starts the seed world as a hamlet and grows with age and development", () => {
    const state = initialMock().state;
    expect(prosperity(state).name).toBe("Hamlet");
    expect(prosperity({ ...state, tick: 60 }).name).toBe("Village");
    const developed = structuredClone(state);
    for (const b of Object.values(developed.buildings)) b.level = 3;
    expect(prosperity({ ...developed, tick: 60 }).tier).toBeGreaterThan(1);
  });

  it("stalls a starving town", () => {
    const state = structuredClone(initialMock().state);
    state.tick = 60;
    for (const c of Object.values(state.citizens)) c.hunger = 100;
    expect(prosperity(state).score).toBeLessThan(
      prosperity({ ...state, tick: 60, citizens: initialMock().state.citizens })
        .score,
    );
  });

  it("keeps each villager's home as the town grows", () => {
    const state = initialMock().state;
    for (const citizen of Object.values(state.citizens)) {
      const homes = [1, 2, 3].map((tier) =>
        homeOf(citizen, state, townAt(tier)),
      );
      expect(new Set(homes.map((h) => `${h?.at.x}:${h?.at.z}`)).size).toBe(1);
    }
  });

  it("holds a reached tier while the score wobbles near the line", () => {
    const base = initialMock().state;
    // Find the day the seed world first scores Village.
    let day = 0;
    while (prosperity({ ...base, tick: day }).tier < 1) day++;
    const epoch = 9001;
    expect(growthOf({ ...base, tick: day }, epoch).tier).toBe(1);
    // Slightly hungrier the next day: the raw score dips under the line...
    const hungry = structuredClone(base);
    for (const c of Object.values(hungry.citizens)) c.hunger = 70;
    expect(prosperity({ ...hungry, tick: day }).tier).toBe(0);
    // ...but the town stays a Village until it falls clearly below.
    expect(growthOf({ ...hungry, tick: day }, epoch).tier).toBe(1);
    // A seek or branch switch starts fresh.
    expect(growthOf({ ...hungry, tick: day }, epoch + 1).tier).toBe(0);
  });

  it("gives runtime-opened lots ground and room at every tier", () => {
    const seedLots = Object.values(initialMock().state.plots).map(
      (p) => p.position,
    );
    // New town land at the edge, including past the hamlet's shore.
    const opened = [
      { x: -8, z: -6 },
      { x: 8, z: 6 },
      { x: 14, z: -8 },
    ];
    const lots = [...seedLots, ...opened];
    for (let tier = 0; tier <= MAX_TIER; tier++) {
      const town = withLots(townAt(tier), lots);
      for (const lot of lots) {
        const ground = Math.min(
          ...town.tiles.map((t) => Math.hypot(t.x - lot.x, t.z - lot.z)),
        );
        expect(ground).toBeLessThan(1.7);
        for (const piece of town.scenery)
          expect(Math.hypot(piece.x - lot.x, piece.z - lot.z)).toBeGreaterThan(
            2,
          );
        for (const place of town.places)
          expect(
            Math.hypot(place.at.x - lot.x, place.at.z - lot.z),
          ).toBeGreaterThan(2);
      }
      // Adding lots never removes ground or roads.
      expect(town.tiles.length).toBeGreaterThanOrEqual(
        townAt(tier).tiles.length,
      );
      // ...and never a road (new lots may add roads to reach them).
      for (const road of townAt(tier).roads.keys())
        expect(town.roads.has(road)).toBe(true);
      // Same lots, same town object: no re-render churn.
      expect(withLots(townAt(tier), [...lots].reverse())).toBe(town);
    }
  });

  it("leaves the seed town untouched by the seed lots", () => {
    const lots = Object.values(initialMock().state.plots).map(
      (p) => p.position,
    );
    for (let tier = 0; tier <= MAX_TIER; tier++) {
      const town = withLots(townAt(tier), lots);
      expect(town.places.map((p) => p.id)).toEqual(
        townAt(tier).places.map((p) => p.id),
      );
      expect(town.tiles.length).toBe(townAt(tier).tiles.length);
    }
  });

  it("scores the seed world at 0 and follows the growth rules", () => {
    const state = structuredClone(initialMock().state);
    expect(prosperity(state).score).toBe(0);
    // +0.5 a day, capped at day 240.
    expect(prosperity({ ...state, tick: 300 }).score).toBe(120);
    // +6 for a rented home (tenant, no building), +2 per citizen.
    const grown = structuredClone(state);
    const free = Object.values(grown.plots).find(
      (p) => !Object.values(grown.buildings).some((b) => b.plot_id === p.id),
    )!;
    free.tenant_id = "citizen-0";
    grown.citizens.newcomer = {
      ...structuredClone(grown.citizens["citizen-0"]),
      id: "newcomer",
    };
    expect(prosperity(grown).score).toBe(8);
  });

  it("keeps all land in one piece, even with lots far out at sea", () => {
    const WIDTH = 2.8;
    const ROW = WIDTH * (Math.sqrt(3) / 2);
    const neighbours = [0, 1, 2, 3, 4, 5].map((k) => ({
      x: Math.cos((k * Math.PI) / 3) * WIDTH,
      z: Math.sin((k * Math.PI) / 3) * WIDTH,
    }));
    const id = (p: { x: number; z: number }) =>
      `${Math.round(p.x * 10)}:${Math.round(p.z * 10)}`;
    for (let tier = 0; tier <= MAX_TIER; tier++) {
      const lots = [
        { x: -4 * WIDTH, z: 7 * ROW },
        { x: 9 * WIDTH, z: -6 * ROW },
      ];
      const { tiles } = withLots(townAt(tier), lots);
      const land = new Set(tiles.map(id));
      const seen = new Set([id(tiles[0])]);
      const queue: { x: number; z: number }[] = [tiles[0]];
      while (queue.length) {
        const cell = queue.pop()!;
        for (const d of neighbours) {
          const n = { x: cell.x + d.x, z: cell.z + d.z };
          if (land.has(id(n)) && !seen.has(id(n))) {
            seen.add(id(n));
            queue.push(n);
          }
        }
      }
      expect(seen.size).toBe(land.size);
    }
  });

  it("never moves or drops an existing tile when a new lot opens", () => {
    // A tile that changes identity remounts and replays its rise: the land
    // flickers and buildings float while their tile grows back underneath.
    const lots = [-4, 0, 4].flatMap((x) =>
      [-3, 3, 9, 15, 21].map((z) => ({ x, z })),
    );
    for (let tier = 0; tier <= MAX_TIER; tier++)
      for (let n = 6; n < lots.length; n++) {
        const before = withLots(townAt(tier), lots.slice(0, n)).tiles;
        const after = new Map(
          withLots(townAt(tier), lots.slice(0, n + 1)).tiles.map((t) => [
            tileKey(t),
            t,
          ]),
        );
        for (const tile of before) {
          const same = after.get(tileKey(tile));
          expect(same, `tier ${tier}, lot ${n}`).toBeDefined();
          expect([same!.x, same!.z]).toEqual([tile.x, tile.z]);
        }
      }
  });

  it("gives new land roads to every lot, forest, and nothing on the lots", () => {
    const lots = [-4, 0, 4].flatMap((x) =>
      [-3, 3, 9, 15, 21].map((z) => ({ x, z })),
    );
    for (let tier = 0; tier <= MAX_TIER; tier++) {
      const base = townAt(tier);
      const town = withLots(base, lots);
      const centre = nearestRoad(town, { x: 0, z: 0 });
      for (const lot of lots) {
        // A road beside the lot, and a way along the roads to the centre.
        const road = nearestRoad(town, lot);
        const at = town.roads.get(road)!.at;
        expect(
          Math.hypot(at.x - lot.x, at.z - lot.z),
          `lot ${lot.x},${lot.z}`,
        ).toBeLessThan(4.2); // next to the lot's cell (lots sit off the grid by up to half a cell)
        expect(route(town, road, centre).at(-1)).toBe(centre);
      }
      // The new land is wooded, and nothing stands on a lot.
      expect(town.scenery.length).toBeGreaterThan(base.scenery.length - 10);
      for (const piece of town.scenery)
        for (const lot of lots)
          expect(Math.hypot(piece.x - lot.x, piece.z - lot.z)).toBeGreaterThan(
            1.5,
          );
    }
  });
});
