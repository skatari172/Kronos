import { describe, expect, it } from "vitest";
import { initialMock } from "../api/mock";
import { growthOf, prosperity } from "./progress";
import { homeOf } from "./routine";
import { MAX_TIER, route, townAt } from "./town";

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
});
