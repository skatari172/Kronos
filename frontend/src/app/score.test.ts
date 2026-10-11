import { describe, expect, it } from "vitest";
import { initialMock } from "../api/mock";
import type { SimulationEvent } from "../api/types";
import { CRITICAL_DAYS, health, noReturn, pointsFor } from "./score";

const world = () => structuredClone(initialMock().state);
const name = (id?: string | null) => id ?? "?";

describe("world health and the point of no return", () => {
  it("rates the seed town healthy and explains a starving one", () => {
    const fresh = health(world());
    expect(fresh.value).toBeGreaterThan(60);
    const starving = world();
    for (const c of Object.values(starving.citizens)) c.hunger = 100;
    const h = health(starving);
    expect(h.value).toBeLessThan(fresh.value);
    expect(h.reasons[0]).toMatch(/hungry/);
  });

  it("is lost when almost no one is left, when bread runs out, or after critical days", () => {
    expect(noReturn(world(), 0)).toBeNull();
    const empty = world();
    for (const id of Object.keys(empty.citizens).slice(2))
      delete empty.citizens[id];
    expect(noReturn(empty, 0)?.reason).toBe("Almost everyone has gone");
    const famine = world();
    for (const c of Object.values(famine.citizens)) c.hunger = 100;
    delete famine.buildings["bakery"];
    expect(noReturn(famine, 0)?.reason).toBe("Starvation");
    expect(noReturn(world(), CRITICAL_DAYS)?.reason).toBe("Collapse");
  });

  it("charges more for handouts than for other decrees", () => {
    const decree = (kind: string, command: object) =>
      ({
        type: "intervention_applied",
        payload: { text: "x", kind, command },
      }) as unknown as SimulationEvent;
    expect(pointsFor(decree("grant_money", { amount: 500 }), name)![0]).toBe(
      -15,
    );
    expect(pointsFor(decree("adjust_hunger", { change: -30 }), name)![0]).toBe(
      -10,
    );
    expect(
      pointsFor(decree("set_policy", { kind: "min_wage" }), name)![0],
    ).toBe(-5);
  });
});
