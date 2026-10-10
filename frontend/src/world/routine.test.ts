import { Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { initialMock } from "../api/mock";
import { RUN_FROM } from "./Models";
import { useFights } from "./fights";
import { startRoutine, stepRoutine } from "./routine";
import { townAt } from "./town";

const town = townAt(1);

/** Run a villager's routine for `seconds`, recording poses, speeds, and gaits. */
function live(
  id: string,
  seconds: number,
  edit?: (s: ReturnType<typeof initialMock>["state"]) => void,
) {
  const state = structuredClone(initialMock().state);
  edit?.(state);
  const citizen = state.citizens[id];
  const at = new Vector3(citizen.position.x, 0, citizen.position.z);
  const routine = startRoutine(town, at, citizen, false);
  const poses = new Set<string>();
  const gaits = new Set<string>();
  let fastest = 0;
  for (let t = 0; t < seconds; t += 0.05) {
    const { speed, gait } = stepRoutine(
      routine,
      at,
      0.05,
      citizen,
      state,
      town,
    );
    if (speed) gaits.add(gait);
    else poses.add(routine.pose);
    fastest = Math.max(fastest, speed);
  }
  return { poses, gaits, fastest, at };
}

describe("villager routines", () => {
  it("runs to a fight and trades blows from the agreed start", () => {
    const now = performance.now();
    useFights.setState({
      current: {
        id: 1,
        a: "citizen-0",
        b: "citizen-1",
        at: { x: 0, z: 0 },
        startAt: now,
        endAt: now + 1e7,
      },
    });
    const { poses, fastest, at } = live("citizen-0", 30);
    expect(fastest).toBeGreaterThan(RUN_FROM);
    expect([...poses]).toEqual(
      expect.arrayContaining(["fists", "punch", "hit"]),
    );
    // Stands off to one side of the meeting point, facing the other fighter.
    expect(Math.hypot(at.x + 0.42, at.z)).toBeLessThan(0.6);
    useFights.setState({ current: null });
  });

  it("faints when starving and gets back up", () => {
    const { poses } = live("citizen-3", 200, (s) => {
      for (const c of Object.values(s.citizens)) c.hunger = 100;
      for (const b of Object.values(s.buildings))
        if (b.kind === "bakery") delete s.buildings[b.id];
    });
    expect([...poses]).toEqual(expect.arrayContaining(["faint", "getUp"]));
  });

  it("sneaks around town when broke", () => {
    const { gaits } = live("citizen-6", 200, (s) => {
      s.citizens["citizen-6"].money = 0;
    });
    expect(gaits).toContain("sneak");
  });

  it("gives every villager their own pace", () => {
    const paces = Object.values(initialMock().state.citizens).map(
      (c) => startRoutine(town, new Vector3(), c, false).pace,
    );
    expect(new Set(paces).size).toBeGreaterThan(3);
  });
});
