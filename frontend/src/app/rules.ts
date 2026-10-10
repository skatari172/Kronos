/** Plain-language rule changes for the header (RuleBar.tsx). */
import type { InterventionResult, WorldState } from "../api/types";
import { coins } from "../api/format";

/** Rule changes the backend understands today (agents/provider.py grammar). */
export const EXAMPLES = [
  "Cap bread price at 6 coins",
  "Set minimum wage to 2 coins",
  "Set market tax to 5%",
  "Raise wages by 20%",
  "Harvest boom",
  "Famine",
  "Give 5 coins to everyone",
  "Increase bread price by 40%",
];

export type Command = InterventionResult["command"];

/** One plain sentence for what a parsed rule change did. */
export function describe(command: Command, state?: WorldState): string {
  const who = (id?: string | null) =>
    id ? (state?.citizens[id]?.name ?? id) : "everyone";
  const c = command as Record<string, unknown> & { type: string };
  const pct = (n: unknown) => `${Math.abs(Number(n))}%`;
  switch (c.type) {
    case "modify_price":
      return `Bread prices ${Number(c.percent) > 0 ? "raised" : "cut"} by ${pct(c.percent)}`;
    case "set_wage":
      return c.wage != null
        ? `Every wage is now ${coins(Number(c.wage))} a day`
        : `Wages ${Number(c.percent) > 0 ? "raised" : "cut"} by ${pct(c.percent)}`;
    case "grant_money":
      return Number(c.amount) > 0
        ? `Gave ${coins(Number(c.amount))} to ${who(c.citizen_id as string)}`
        : `Took ${coins(-Number(c.amount))} from ${who(c.citizen_id as string)}`;
    case "adjust_resource":
      return c.regen_per_tick != null
        ? `Wheat now regrows ${c.regen_per_tick} a day`
        : Number(c.stock_change) > 0
          ? `${c.stock_change} wheat added to the fields`
          : `${-Number(c.stock_change)} wheat lost from the fields`;
    case "adjust_hunger":
      return `Hunger ${Number(c.change) < 0 ? "eased" : "worsened"} by ${Math.abs(Number(c.change))} for ${who(c.citizen_id as string)}`;
    case "set_policy": {
      const value = Number(c.value);
      if (c.kind === "min_wage")
        return value
          ? `Minimum wage set to ${coins(value)}`
          : "Minimum wage lifted";
      if (c.kind === "bread_price_cap")
        return value
          ? `Bread is now capped at ${coins(value)}`
          : "Bread price cap lifted";
      return value ? `Market tax set to ${value / 100}%` : "Market tax lifted";
    }
    default:
      return "Rule changed";
  }
}

/**
 * Offline preview only: recognise the same phrasings as the backend's mock
 * grammar (backend/modules/agents/.../provider.py) so the decree animation can
 * be seen without the API. Returns a command for `describe`, or null. The
 * world itself only changes when the backend applies the rule.
 */
export function previewCommand(text: string): Command | null {
  const t = text
    .trim()
    .replace(/\s+/g, " ")
    .replace(/[.!]+$/, "");
  const m = (pattern: RegExp) => t.match(pattern);
  const money = "(\\d{1,7}) ?(coins?|cents?)";
  const cents = (n: string, unit: string) =>
    Number(n) * (unit.toLowerCase().startsWith("cent") ? 1 : 100);
  const up = (word: string) => /^(increase|raise|add)$/i.test(word);
  let r: RegExpMatchArray | null;
  const command = (c: Record<string, unknown>) => c as Command;
  if (
    (r = m(
      /^(increase|raise|decrease|reduce|lower|cut) (?:the )?(?:price of bread|bread prices?) by (\d{1,3}) ?%$/i,
    ))
  )
    return command({
      type: "modify_price",
      percent: (up(r[1]) ? 1 : -1) * Number(r[2]),
    });
  if ((r = m(new RegExp(`^set (?:all )?wages to ${money}$`, "i"))))
    return command({
      type: "set_wage",
      wage: cents(r[1], r[2]),
      percent: null,
    });
  if (
    (r = m(
      /^(increase|raise|decrease|reduce|lower|cut) (?:all )?wages by (\d{1,3}) ?%$/i,
    ))
  )
    return command({
      type: "set_wage",
      wage: null,
      percent: (up(r[1]) ? 1 : -1) * Number(r[2]),
    });
  if ((r = m(new RegExp(`^(give|grant|pay) ${money} to (.+)$`, "i"))))
    return command({
      type: "grant_money",
      amount: cents(r[2], r[3]),
      citizen_id: null,
    });
  if ((r = m(new RegExp(`^(take|remove|confiscate) ${money} from (.+)$`, "i"))))
    return command({
      type: "grant_money",
      amount: -cents(r[2], r[3]),
      citizen_id: null,
    });
  if (m(/^(?:a )?(?:harvest boom|bumper harvest)$/i))
    return command({
      type: "adjust_resource",
      stock_change: 50,
      regen_per_tick: null,
    });
  if (m(/^(?:a )?drought$/i))
    return command({
      type: "adjust_resource",
      stock_change: -50,
      regen_per_tick: null,
    });
  if ((r = m(/^(?:(?:hold|throw) )?(?:a )?(feast|famine)$/i)))
    return command({
      type: "adjust_hunger",
      change: r[1].toLowerCase() === "famine" ? 30 : -30,
      citizen_id: null,
    });
  if (
    (r = m(new RegExp(`^set (?:the )?(?:minimum|min) wage to ${money}$`, "i")))
  )
    return command({
      type: "set_policy",
      kind: "min_wage",
      value: cents(r[1], r[2]),
    });
  if ((r = m(new RegExp(`^cap (?:the )?bread prices? at ${money}$`, "i"))))
    return command({
      type: "set_policy",
      kind: "bread_price_cap",
      value: cents(r[1], r[2]),
    });
  if ((r = m(/^set (?:the )?(?:market )?tax to (\d{1,3}) ?%$/i)))
    return command({
      type: "set_policy",
      kind: "market_tax",
      value: Number(r[1]) * 100,
    });
  if (
    (r = m(
      /^(?:remove|lift|abolish) (?:the )?(minimum wage|min wage|bread price cap|bread cap|market tax|tax)$/i,
    ))
  )
    return command({
      type: "set_policy",
      kind: /wage/i.test(r[1])
        ? "min_wage"
        : /bread/i.test(r[1])
          ? "bread_price_cap"
          : "market_tax",
      value: 0,
    });
  return null;
}

/** How the town takes a decree. HARD-CODED SAMPLE until agents react for real. */
export function reactionTo(command: Command): string {
  const c = command as Record<string, unknown> & { type: string };
  switch (c.type) {
    case "modify_price":
      return Number(c.percent) > 0
        ? "Marcus counts his coins; the farmhands count theirs and frown."
        : "A queue forms at the bakery before the bread is even out.";
    case "set_wage":
      return "Owners check their tills. Workers start planning what to buy.";
    case "grant_money":
      return Number(c.amount) > 0
        ? "Coins jingle in every pocket. The market will be busy tonight."
        : "Grumbling in the square. Purses feel lighter.";
    case "adjust_resource":
      return Number(c.stock_change) < 0
        ? "Elena walks the dry fields, worried about the next harvest."
        : "The fields sway heavy with wheat. The bakers smile.";
    case "adjust_hunger":
      return Number(c.change) > 0
        ? "Stomachs growl. Everyone eyes the bakery."
        : "A feast in the square. For once, nobody is hungry.";
    case "set_policy":
      return Number(c.value)
        ? "The new law is posted on the chapel door. Merchants adjust their signs."
        : "The old law is torn down. The market breathes easier.";
    default:
      return "The town takes note.";
  }
}
