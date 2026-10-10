import { describe, expect, it } from "vitest";
import { initialMock } from "../api/mock";
import type { SimulationEvent } from "../api/types";
import { rememberNames, splitRationale, toEntry } from "./chronicle";

const world = initialMock().state;
rememberNames(world);

const event = (fields: object) =>
  ({
    id: "main:1",
    branch_id: "main",
    tick: 4,
    sequence: 1,
    actor_id: null,
    rationale: null,
    causal_refs: [],
    action_id: null,
    ...fields,
  }) as unknown as SimulationEvent;

describe("live chronicle", () => {
  it("labels who decided from the rationale prefix", () => {
    expect(splitRationale("[llm] Bread is cheap today.")).toEqual({
      source: "AI agent",
      reason: "Bread is cheap today.",
    });
    expect(splitRationale("Saver founds a business").source).toBe("Town rule");
    expect(splitRationale(null).source).toBe("Routine");
  });

  it("tells an argument as a fight, with both sides", () => {
    const entry = toEntry(
      event({
        type: "citizen_interacted",
        actor_id: "citizen-3",
        rationale: "[mock] I won't let Elena talk down to me.",
        action_id: "a1",
        payload: { recipient_id: "citizen-0", kind: "argue", amount: 0 },
      }),
      world,
    );
    expect(entry?.kind).toBe("fight");
    expect(entry?.text).toBe("Rowan argued with Elena");
    expect(entry?.why[0]).toMatchObject({
      name: "Rowan",
      thought: "I won't let Elena talk down to me.",
      source: "Mock agent",
    });
    expect(entry?.why[1]).toMatchObject({ name: "Elena", source: "Memory" });
  });

  it("keeps chosen purchases and drops routine bookkeeping", () => {
    const bought = toEntry(
      event({
        type: "transaction_completed",
        actor_id: "citizen-6",
        rationale: "[llm] I have no bread left.",
        action_id: "a2",
        payload: {
          sender_id: "citizen-6",
          recipient_id: "bakery",
          amount: 500,
          resource: "bread",
          quantity: 1,
        },
      }),
      world,
    );
    expect(bought?.text).toBe(
      "Finn bought 1 bread from Hearth & Grain for 5.00",
    );
    expect(bought?.why[1].name).toBe("Marcus");

    const wage = event({
      type: "transaction_completed",
      actor_id: "citizen-0",
      payload: {
        sender_id: "farm",
        recipient_id: "citizen-3",
        amount: 150,
        resource: null,
        quantity: 0,
      },
    });
    expect(toEntry(wage, world)).toBeNull();
    expect(
      toEntry(
        event({ type: "citizen_moved", payload: { entity_id: "citizen-1" } }),
        world,
      ),
    ).toBeNull();
  });
});
