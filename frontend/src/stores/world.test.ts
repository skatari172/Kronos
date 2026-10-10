import { beforeEach, describe, expect, it } from "vitest";
import { initialMock, mockEvent, STORY } from "../api/mock";
import { prosperity } from "../world/progress";
import { useWorld } from "./world";

/** The first story step: a new bakery, one sequence ahead of the seed. */
const newer = () => mockEvent(initialMock(), 0)!;
const cheaperBread = STORY.findIndex((s) => s.title === "Bread gets cheaper");

describe("authoritative synchronization", () => {
  beforeEach(() => useWorld.getState().replace(initialMock()));
  it("accepts a newer full state, deduplicates events and rejects stale updates", () => {
    const update = mockEvent(initialMock(), cheaperBread)!;
    expect(useWorld.getState().ingest(update)).toBe(true);
    expect(
      useWorld.getState().update?.state.buildings.bakery.prices.bread,
    ).toBe(400);
    expect(useWorld.getState().ingest(update)).toBe(false);
    expect(useWorld.getState().ingest(initialMock())).toBe(false);
    expect(useWorld.getState().events).toHaveLength(1);
  });
  it("rejects updates from a different branch", () => {
    const update = newer();
    update.branch_id = "other";
    expect(useWorld.getState().ingest(update)).toBe(false);
  });
  it("invalidates animation epoch and ignores live frames while viewing history", () => {
    const epoch = useWorld.getState().epoch;
    useWorld.getState().replace(initialMock(), true);
    expect(useWorld.getState().epoch).toBe(epoch + 1);
    expect(useWorld.getState().ingest(newer())).toBe(false);
    expect(useWorld.getState().update?.sequence).toBe(0);
  });
  it("replaces history atomically on a branch switch", () => {
    useWorld.getState().ingest(newer());
    const next = initialMock();
    next.branch_id = next.state.branch_id = "fork";
    useWorld.getState().replace(next);
    expect(useWorld.getState().events).toEqual([]);
    expect(useWorld.getState().update?.branch_id).toBe("fork");
  });
});

describe("offline preview story", () => {
  it("grows the seed hamlet into a city, then ends", () => {
    let update = initialMock();
    const tiers = new Set<string>();
    for (let i = 0; i < STORY.length; i++) {
      const next = mockEvent(update, i)!;
      expect(next.sequence).toBeGreaterThan(update.sequence);
      expect(next.events.length).toBeGreaterThan(0);
      update = next;
      tiers.add(prosperity(update.state).name);
    }
    expect([...tiers]).toEqual(
      expect.arrayContaining(["Village", "Town", "City"]),
    );
    expect(prosperity(update.state).name).toBe("City");
    expect(mockEvent(update, STORY.length)).toBeNull();
  });
  it("brings a bigger wave of newcomers with each tier", () => {
    let update = initialMock();
    const population: Record<string, number> = {};
    STORY.forEach((_, i) => {
      update = mockEvent(update, i)!;
      const tier = prosperity(update.state).name;
      population[tier] = Object.keys(update.state.citizens).length;
    });
    expect(population).toEqual({ Hamlet: 7, Village: 10, Town: 15, City: 23 });
  });
  it("stages construction, upgrades, arrivals, leases, and a bankruptcy", () => {
    const types = new Set<string>();
    let update = initialMock();
    STORY.forEach((_, i) => {
      update = mockEvent(update, i)!;
      update.events.forEach((e) => types.add(e.type));
    });
    for (const type of [
      "building_constructed",
      "building_upgraded",
      "building_removed",
      "citizen_spawned",
      "lot_leased",
      "price_changed",
    ])
      expect(types).toContain(type);
  });
});
