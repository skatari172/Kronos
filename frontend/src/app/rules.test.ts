import { describe as group, expect, it } from "vitest";
import { initialMock } from "../api/mock";
import type { InterventionResult } from "../api/types";
import { describe, previewCommand } from "./rules";

const say = (command: Record<string, unknown>) =>
  describe(command as InterventionResult["command"], initialMock().state);

group("rule change descriptions", () => {
  it("names every kind of rule change in plain words", () => {
    expect(say({ type: "modify_price", percent: 40 })).toBe(
      "Bread prices raised by 40%",
    );
    expect(say({ type: "set_wage", wage: 200, percent: null })).toBe(
      "Every wage is now 2.00 a day",
    );
    expect(say({ type: "set_wage", wage: null, percent: -10 })).toBe(
      "Wages cut by 10%",
    );
    expect(say({ type: "grant_money", amount: 500, citizen_id: null })).toBe(
      "Gave 5.00 to everyone",
    );
    expect(
      say({ type: "grant_money", amount: -300, citizen_id: "citizen-2" }),
    ).toBe("Took 3.00 from Ada");
    expect(
      say({ type: "adjust_resource", stock_change: 50, regen_per_tick: null }),
    ).toBe("50 wheat added to the fields");
    expect(say({ type: "adjust_hunger", change: 30, citizen_id: null })).toBe(
      "Hunger worsened by 30 for everyone",
    );
    expect(
      say({ type: "set_policy", kind: "bread_price_cap", value: 600 }),
    ).toBe("Bread is now capped at 6.00");
    expect(say({ type: "set_policy", kind: "market_tax", value: 500 })).toBe(
      "Market tax set to 5%",
    );
    expect(say({ type: "set_policy", kind: "min_wage", value: 0 })).toBe(
      "Minimum wage lifted",
    );
  });

  it("recognises the backend's phrasings offline, and nothing else", () => {
    const said = (text: string) => {
      const command = previewCommand(text);
      return command && describe(command, initialMock().state);
    };
    expect(said("Cap bread price at 6 coins")).toBe(
      "Bread is now capped at 6.00",
    );
    expect(said("famine.")).toBe("Hunger worsened by 30 for everyone");
    expect(said("Set market tax to 5%")).toBe("Market tax set to 5%");
    expect(said("Raise wages by 20%")).toBe("Wages raised by 20%");
    expect(said("Remove the market tax")).toBe("Market tax lifted");
    expect(previewCommand("make everyone a dragon")).toBeNull();
  });
});
