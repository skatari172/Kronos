/**
 * Stages live events in the village: conversations for messages, friendly
 * gestures, trade and loan offers (world/meetings.ts), and thought pops over
 * whoever acted (world/emotes.ts). Fights are staged by the chronicle hook.
 * Presentation only: everything shown comes from a committed event.
 */
import type { SimulationEvent, WorldState } from "../api/types";
import { coins } from "../api/format";
import { useEmotes, type Emote } from "../world/emotes";
import { useMeetings, type Talk } from "../world/meetings";
import { splitRationale } from "./chronicle";

const clip = (text: string, max = 30) =>
  text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;

function bundle(b: { money: number; goods: { bread: number; wheat: number } }) {
  const parts = [
    b.money ? `${coins(b.money)} coins` : "",
    b.goods.bread ? `${b.goods.bread} bread` : "",
    b.goods.wheat ? `${b.goods.wheat} wheat` : "",
  ].filter(Boolean);
  return parts.join(" and ") || "nothing";
}

/** A conversation for this event, as [speaker, listener, talk], if it is one. */
export function talkOf(
  event: SimulationEvent,
): [string, string, Omit<Talk, "day">] | null {
  const { source, reason } = splitRationale(event.rationale);
  const base = { reason: reason || "They had something to say.", source };
  switch (event.type) {
    case "agent_spoke":
      if (!event.actor_id) return null;
      return [
        event.actor_id,
        event.payload.recipient_id,
        {
          ...base,
          kind: "talk",
          bubble: clip(event.payload.message),
          line: event.payload.message,
        },
      ];
    case "citizen_interacted": {
      const p = event.payload;
      if (
        !event.actor_id ||
        !["befriend", "ally", "mentor", "gift"].includes(p.kind)
      )
        return null;
      const gift = p.kind === "gift";
      const action = gift
        ? `gives a gift of ${coins(p.amount)} coins`
        : p.kind === "ally"
          ? "proposes they stand together"
          : p.kind === "mentor"
            ? "offers to teach what they know"
            : "offers their friendship";
      return [
        event.actor_id,
        p.recipient_id,
        {
          ...base,
          kind: gift ? "gift" : "friend",
          bubble: gift
            ? "A gift for you"
            : p.kind === "ally"
              ? "Allies?"
              : "Friends?",
          action,
        },
      ];
    }
    case "trade_offered": {
      const p = event.payload;
      return [
        p.sender_id,
        p.recipient_id,
        {
          ...base,
          kind: "deal",
          bubble: "A deal?",
          action: `offers ${bundle(p.give)} for ${bundle(p.get)}`,
        },
      ];
    }
    case "loan_offered": {
      const p = event.payload;
      return [
        p.lender_id,
        p.borrower_id,
        {
          ...base,
          kind: "loan",
          bubble: `Loan: ${coins(p.principal)}?`,
          action: `offers a loan of ${coins(p.principal)} coins (repay ${coins(p.amount_owed)})`,
        },
      ];
    }
    default:
      return null;
  }
}

type Pop = [string, Omit<Emote, "key">];

/** A thought pop for whoever acted, if the event is worth one. */
export function popOf(event: SimulationEvent, world: WorldState): Pop | null {
  const actor = event.actor_id;
  const name = (id: string) => world.buildings[id]?.name ?? "work";
  switch (event.type) {
    // Everyday purchases are left to the chronicle; a pop for every loaf flashes.
    case "resource_consumed":
      // Only meals their agent chose; the engine's automatic ones are routine.
      return event.action_id && world.citizens[event.payload.entity_id]
        ? [
            event.payload.entity_id,
            { icon: "bread", text: "Ate a loaf", tone: "good" },
          ]
        : null;
    case "job_applied":
      return [
        event.payload.citizen_id,
        {
          icon: "job",
          text: `Applied at ${name(event.payload.building_id)}`,
          tone: "plain",
        },
      ];
    case "employment_changed": {
      const p = event.payload;
      return p.building_id
        ? [
            p.citizen_id,
            {
              icon: "hired",
              text: `Hired at ${name(p.building_id)}!`,
              tone: "good",
            },
          ]
        : [p.citizen_id, { icon: "no", text: "Lost their job", tone: "bad" }];
    }
    case "price_changed":
      return actor
        ? [
            actor,
            {
              icon: "price",
              text: `${event.payload.resource} → ${coins(event.payload.new_price)}`,
              tone: "plain",
            },
          ]
        : null;
    case "wage_changed":
      return actor
        ? [
            actor,
            {
              icon: "coins",
              text: `Wages → ${coins(event.payload.new_wage)}`,
              tone: "plain",
            },
          ]
        : null;
    case "action_rejected":
      return actor
        ? [
            actor,
            {
              icon: "no",
              text: `Couldn't ${event.payload.action_type.replaceAll("_", " ")}`,
              tone: "bad",
            },
          ]
        : null;
    case "building_constructed":
      return actor
        ? [actor, { icon: "build", text: "Founded a business!", tone: "good" }]
        : null;
    case "building_upgraded":
      return actor
        ? [actor, { icon: "build", text: "Expanded!", tone: "good" }]
        : null;
    case "lot_leased":
      return event.payload.tenant_id
        ? [
            event.payload.tenant_id,
            { icon: "home", text: "Rented a home", tone: "good" },
          ]
        : null;
    case "goals_changed":
      return actor
        ? [actor, { icon: "goal", text: "Rethinking goals", tone: "plain" }]
        : null;
    case "research_contributed":
      return actor
        ? [actor, { icon: "idea", text: "Researching", tone: "plain" }]
        : null;
    case "vote_proposed":
    case "vote_cast":
      return actor
        ? [actor, { icon: "vote", text: "Voted", tone: "plain" }]
        : null;
    case "citizen_spawned":
      return [
        event.payload.entity_id,
        { icon: "arrive", text: "Just arrived!", tone: "good" },
      ];
    default:
      return null;
  }
}

/** Stage one new live event in the village. */
export function stage(event: SimulationEvent, world: WorldState) {
  const talk = talkOf(event);
  if (talk) {
    const [a, b, t] = talk;
    useMeetings
      .getState()
      .request(a, b, { ...t, day: Math.max(event.tick, 1) });
    return;
  }
  const pop = popOf(event, world);
  if (pop) useEmotes.getState().pop(...pop);
}
