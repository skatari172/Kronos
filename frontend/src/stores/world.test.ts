import { beforeEach, describe, expect, it } from "vitest";
import { initialMock, mockEvent } from "../api/mock";
import { useWorld } from "./world";

describe("authoritative synchronization", () => {
  beforeEach(() => useWorld.getState().replace(initialMock()));
  it("accepts a newer full state, deduplicates events and rejects stale updates", () => {
    const update = mockEvent(initialMock(), 4);
    expect(useWorld.getState().ingest(update)).toBe(true);
    expect(
      useWorld.getState().update?.state.buildings.bakery.prices.bread,
    ).toBe(700);
    expect(useWorld.getState().ingest(update)).toBe(false);
    expect(useWorld.getState().ingest(initialMock())).toBe(false);
    expect(useWorld.getState().events).toHaveLength(1);
  });
  it("rejects updates from a different branch", () => {
    const update = mockEvent(initialMock(), 0);
    update.branch_id = "other";
    expect(useWorld.getState().ingest(update)).toBe(false);
  });
  it("invalidates animation epoch and ignores live frames while viewing history", () => {
    const epoch = useWorld.getState().epoch;
    useWorld.getState().replace(initialMock(), true);
    expect(useWorld.getState().epoch).toBe(epoch + 1);
    expect(useWorld.getState().ingest(mockEvent(initialMock(), 4))).toBe(false);
    expect(useWorld.getState().update?.sequence).toBe(0);
  });
  it("replaces history atomically on a branch switch", () => {
    useWorld.getState().ingest(mockEvent(initialMock(), 4));
    const next = initialMock();
    next.branch_id = next.state.branch_id = "fork";
    useWorld.getState().replace(next);
    expect(useWorld.getState().events).toEqual([]);
    expect(useWorld.getState().update?.branch_id).toBe("fork");
  });
  it("demonstrates construction, upgrades, spawning, movement, price changes, and departure", () => {
    let update = initialMock();
    for (let i = 0; i < 6; i++) update = mockEvent(update, i);
    expect(update.state.buildings["demo-bakery"]).toBeDefined();
    expect(update.state.buildings.bakery.level).toBe(2);
    expect(update.state.citizens.visitor).toBeUndefined();
    expect(update.state.citizens["citizen-0"].position.x).toBe(4);
    expect(update.state.buildings.bakery.prices.bread).toBe(700);
  });
});
