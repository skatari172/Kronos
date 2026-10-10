import { Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { joinCrowd, keepApart, PERSONAL_SPACE } from "./crowd";

describe("crowd", () => {
  it("spreads villagers standing on the same spot", () => {
    const people = Array.from({ length: 7 }, (_, i) => ({
      id: `citizen-${i}`,
      seed: i * 53,
      at: new Vector3(0.01 * i, 0, 0),
    }));
    const leave = people.map((p) => joinCrowd(p.id, p.at));
    // A couple of seconds of frames.
    for (let frame = 0; frame < 120; frame++)
      for (const p of people) keepApart(p.id, p.at, p.seed);
    let closest = Infinity;
    for (const a of people)
      for (const b of people)
        if (a !== b) closest = Math.min(closest, a.at.distanceTo(b.at));
    expect(closest).toBeGreaterThan(PERSONAL_SPACE * 0.95);
    leave.forEach((fn) => fn());
  });

  it("ignores villagers who have left", () => {
    const a = new Vector3(0, 0, 0);
    const b = new Vector3(0.1, 0, 0);
    joinCrowd("a", a);
    joinCrowd("b", b)();
    keepApart("a", a, 1);
    expect(a.x).toBe(0);
  });
});
