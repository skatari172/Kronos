import { describe, expect, it } from "vitest";
import { initialMock } from "./mock";
import { activityCue, describeEvent } from "./format";
import type { SimulationEvent } from "./types";

const base = {
  id: "main:1",
  branch_id: "main",
  tick: 1,
  sequence: 1,
  actor_id: "citizen-6",
  rationale: "I need food",
  causal_refs: [],
  action_id: "action-main:1",
};
const purchase: SimulationEvent = {
  ...base,
  type: "transaction_completed",
  payload: {
    sender_id: "citizen-6",
    recipient_id: "bakery",
    amount: 500,
    resource: "bread",
    quantity: 1,
  },
};
const rejection: SimulationEvent = {
  ...base,
  id: "main:2",
  sequence: 2,
  type: "action_rejected",
  payload: {
    action_type: "buy",
    code: "insufficient_funds",
    message: "Not enough money",
  },
};

describe("engine event presentation", () => {
  it("describes newly opened backend land", () => {
    expect(
      describeEvent({
        ...base,
        type: "plot_opened",
        payload: {
          entity_id: "plot-main-2",
          position: { x: -4, z: 9 },
          level: null,
        },
      }),
    ).toBe("New town land opens for building");
  });
  it("names the buyer, bakery, quantity and price from a committed purchase", () => {
    expect(describeEvent(purchase, initialMock().state)).toBe(
      "Finn bought 1 bread from Hearth & Grain for 5.00 coins.",
    );
  });
  it("shows a named refusal without inventing a completed trade", () => {
    expect(describeEvent(rejection, initialMock().state)).toBe(
      "Finn could not buy · Not enough money",
    );
    expect(activityCue([purchase, rejection], "citizen-6")).toEqual(rejection);
    expect(activityCue([purchase, rejection], "bakery")).toEqual(purchase);
    expect(activityCue([purchase, rejection], "citizen-0")).toBeUndefined();
  });
});
