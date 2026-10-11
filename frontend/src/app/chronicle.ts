/**
 * Live chronicle: turns the backend's committed events into chronicle entries.
 * The "why" comes from the simulation itself: the acting citizen's own
 * `rationale` (written by their AI agent, the mock agent, the utility
 * fallback, or a town rule), and the other side's memory of it or their
 * feelings toward the actor. Routine bookkeeping (wages, meals, movement,
 * harvests) is left out so the stream reads like a story.
 */
import type { SimulationEvent, WorldState } from "../api/types";
import { coins, describeEvent } from "../api/format";
import type { FeedItem, FeedKind, Side } from "./feed";
import { describe, reactionTo } from "./rules";

export type Entry = Omit<FeedItem, "id">;

/** Who made the call, from the `[source]` prefix the agent service writes. */
const SOURCES: Record<string, string> = {
  llm: "AI agent",
  mock: "Mock agent",
  fallback: "Utility rule",
};

export function splitRationale(rationale: string | null | undefined) {
  if (!rationale) return { source: "Routine", reason: "" };
  const match = /^\[(\w+)\]\s*(.*)$/s.exec(rationale);
  if (!match) return { source: "Town rule", reason: rationale };
  return { source: SOURCES[match[1]] ?? match[1], reason: match[2] };
}

/** Names outlive citizens who leave, so departures can still be told. */
const known = new Map<string, string>();

export function rememberNames(world: WorldState) {
  for (const [id, c] of Object.entries(world.citizens)) known.set(id, c.name);
  for (const [id, b] of Object.entries(world.buildings)) known.set(id, b.name);
}

export const nameOf = (id: string | null | undefined, fallback = "Someone") =>
  (id && known.get(id)) || fallback;

/** A memory line without internal ids ("Trade offer-main-294 …") or end punctuation. */
export const tidy = (memory: string) =>
  memory
    .replace(/\b(?:building|citizen)-[\w-]*\d\b/g, (id) =>
      nameOf(id, "a business"),
    )
    .replace(
      /\s?\b(?:offer|loan|application|plot|license|vote)-[\w-]*\d\b/g,
      "",
    )
    .replace(/[.!?]+$/, "")
    .trim();

/**
 * A memory as a short sentence: "Theo: Bread is cheap." becomes
 * 'Heard Theo say "Bread is cheap."', and "To Theo: …" becomes 'Told Theo "…"'.
 */
function recall(memory: string, actor: string) {
  const line = tidy(memory);
  const heard = new RegExp(`^${actor}: (.+)$`).exec(line);
  if (heard)
    return `Heard ${actor} say “${heard[1].replace(/\s*\(x\d+\)$/, "")}”.`;
  const told = /^To ([^:]+): (.+)$/.exec(line);
  if (told) return `Told ${told[1]} “${told[2].replace(/\s*\(x\d+\)$/, "")}”.`;
  return `${line}.`;
}

/** Is this the speaker saying the same thing again? (`said` is per chronicle.) */
export function isRepeat(event: SimulationEvent, said: Map<string, string>) {
  if (event.type !== "agent_spoke") return false;
  const speaker = event.actor_id ?? "";
  if (said.get(speaker) === event.payload.message) return true;
  said.set(speaker, event.payload.message);
  return false;
}

/** Interactions that end in a scuffle in the village scene. */
export const HOSTILE = new Set(["argue", "insult", "betray"]);

const VERBS: Record<string, string> = {
  befriend: "befriended",
  gift: "gave a gift to",
  ally: "allied with",
  argue: "argued with",
  insult: "insulted",
  betray: "betrayed",
  mentor: "took under their wing",
};

/** The acting citizen's side: their own reasoning, labelled by who decided. */
function actorSide(
  event: SimulationEvent,
  world: WorldState,
  role: string,
  fallbackThought: string,
): Side {
  const { source, reason } = splitRationale(event.rationale);
  const citizen = event.actor_id ? world.citizens[event.actor_id] : undefined;
  return {
    id: citizen ? event.actor_id! : undefined,
    name: nameOf(event.actor_id, "The town"),
    role,
    incentive:
      citizen?.goals[0] ?? citizen?.personality ?? "Keep the town running",
    thought: reason || fallbackThought,
    source,
  };
}

/** The other party: what they remember of it, or how they feel toward the actor. */
export function otherSide(
  id: string,
  actorId: string | null | undefined,
  world: WorldState,
  role: string,
): Side {
  const citizen = world.citizens[id];
  const actor = nameOf(actorId, "");
  const memory = actor
    ? [...(citizen?.memories ?? [])].reverse().find((m) => m.includes(actor))
    : undefined;
  const tie = citizen?.relationships.find((r) => r.citizen_id === actorId);
  const feeling = !tie
    ? "I barely know them."
    : tie.grudge > 20 && tie.grudge >= tie.trust
      ? `I won't forget this. (grudge ${tie.grudge})`
      : tie.trust >= 20
        ? `I trust ${actor || "them"}. (trust ${tie.trust})`
        : `We'll see where this goes. (trust ${tie.trust}, grudge ${tie.grudge})`;
  return {
    id: citizen ? id : undefined,
    name: nameOf(id),
    role,
    incentive: citizen?.personality ?? "Get by",
    thought: memory ? `${recall(memory, actor)} ${feeling}` : feeling,
    source: "Memory",
  };
}

const entry = (
  event: SimulationEvent,
  kind: FeedKind,
  text: string,
  why: Side[],
): Entry => ({ day: Math.max(event.tick, 1), kind, text, why });

/**
 * One chronicle entry for a story-worthy event, or null for routine ones.
 * `world` is the latest snapshot; names come from every snapshot seen.
 */
export function toEntry(
  event: SimulationEvent,
  world: WorldState,
): Entry | null {
  const actor = nameOf(event.actor_id);
  switch (event.type) {
    case "citizen_interacted": {
      const p = event.payload;
      const other = nameOf(p.recipient_id);
      const hostile = HOSTILE.has(p.kind);
      const text =
        p.kind === "gift" && p.amount
          ? `${actor} gave ${other} ${coins(p.amount)} coins`
          : `${actor} ${VERBS[p.kind] ?? p.kind} ${other}`;
      return entry(event, hostile ? "fight" : "talk", text, [
        actorSide(
          event,
          world,
          hostile ? "Started it" : "Reached out",
          `I had my reasons with ${other}.`,
        ),
        otherSide(
          p.recipient_id,
          event.actor_id,
          world,
          hostile ? "Target" : "Recipient",
        ),
      ]);
    }
    case "agent_spoke": {
      const p = event.payload;
      const other = nameOf(p.recipient_id);
      return entry(event, "talk", `${actor} told ${other}: “${p.message}”`, [
        actorSide(event, world, "Speaker", "Word should get around."),
        otherSide(p.recipient_id, event.actor_id, world, "Listener"),
      ]);
    }
    case "transaction_completed": {
      const p = event.payload;
      // Only purchases a citizen chose to make; wages and stock top-ups are routine.
      if (!p.resource || !event.action_id || !world.buildings[p.recipient_id])
        return null;
      // A scripted agent's daily loaf is routine; an AI agent's reasoning is worth telling.
      const { source } = splitRationale(event.rationale);
      if (source !== "AI agent" && p.quantity <= 1) return null;
      const shop = world.buildings[p.recipient_id];
      return entry(
        event,
        "trade",
        `${actor} bought ${p.quantity} ${p.resource} from ${shop.name} for ${coins(p.amount)}`,
        [
          actorSide(event, world, "Buyer", "I needed it."),
          otherSide(shop.owner_id, event.actor_id, world, "Seller"),
        ],
      );
    }
    case "building_constructed": {
      const building = world.buildings[event.payload.entity_id];
      return entry(
        event,
        "build",
        `${actor} founded ${building?.name ?? "a new business"}`,
        [
          actorSide(
            event,
            world,
            "Founder",
            "Time to build something of my own.",
          ),
        ],
      );
    }
    case "building_upgraded":
      return entry(
        event,
        "build",
        `${nameOf(event.payload.entity_id, "A business")} grew to level ${event.payload.level}`,
        [actorSide(event, world, "Owner", "Business is good; time to expand.")],
      );
    case "building_removed":
      return entry(
        event,
        "loss",
        `${nameOf(event.payload.entity_id, "A business")} closed for good`,
        [actorSide(event, world, "Town", "It could not pay its workers.")],
      );
    case "plot_opened":
      return entry(event, "build", "New land opened at the edge of town", [
        {
          name: "Oakhaven",
          role: "The town",
          incentive: "Room to grow",
          thought: "Every lot was taken, so the town cleared more land.",
          source: "Town rule",
        },
      ]);
    case "citizen_spawned": {
      const id = event.payload.entity_id;
      const citizen = world.citizens[id];
      return entry(
        event,
        "people",
        `${nameOf(id, "A traveler")} arrived in Oakhaven`,
        [
          {
            name: nameOf(id, "A traveler"),
            role: "Newcomer",
            incentive: citizen?.personality ?? "A fresh start",
            thought: "Folk here look well fed. There may be work for me.",
            source: "Town rule",
          },
        ],
      );
    }
    case "citizen_removed":
      return entry(
        event,
        "loss",
        `${nameOf(event.payload.entity_id)} left Oakhaven`,
        [
          {
            name: nameOf(event.payload.entity_id),
            role: "Departed",
            incentive: "Survive",
            thought:
              "Three days hungry with empty pockets. There's nothing for me here.",
            source: "Town rule",
          },
        ],
      );
    case "employment_changed": {
      const p = event.payload;
      const who = nameOf(p.citizen_id);
      const text = p.building_id
        ? `${who} started work at ${nameOf(p.building_id, "a business")}`
        : `${who} lost their job at ${nameOf(p.previous_building_id, "a business")}`;
      const sides = [
        actorSide(event, world, "Employer", "The numbers decided it."),
      ];
      if (p.citizen_id !== event.actor_id)
        sides.push(
          otherSide(
            p.citizen_id,
            event.actor_id,
            world,
            p.building_id ? "New hire" : "Let go",
          ),
        );
      return entry(event, p.building_id ? "job" : "loss", text, sides);
    }
    case "job_application_resolved":
      if (event.payload.outcome !== "rejected") return null; // the hire is told above
      return entry(
        event,
        "job",
        `${nameOf(event.payload.citizen_id)} was turned away by ${nameOf(event.payload.building_id)}`,
        [
          actorSide(event, world, "Owner", "No room for another worker."),
          otherSide(
            event.payload.citizen_id,
            event.actor_id,
            world,
            "Applicant",
          ),
        ],
      );
    case "price_changed":
    case "wage_changed":
      return entry(event, "price", describeEvent(event, world), [
        actorSide(event, world, "Owner", "The market moved."),
      ]);
    case "lot_leased":
    case "tenant_evicted":
    case "rent_missed": {
      const p = event.payload;
      const tenant = nameOf(p.tenant_id);
      const text =
        event.type === "lot_leased"
          ? `${tenant} rented a home from ${nameOf(p.owner_id)}`
          : event.type === "tenant_evicted"
            ? `${nameOf(p.owner_id)} evicted ${tenant}`
            : `${tenant} missed rent to ${nameOf(p.owner_id)}`;
      return entry(event, event.type === "lot_leased" ? "home" : "loss", text, [
        actorSide(
          event,
          world,
          event.type === "lot_leased" ? "Tenant" : "Landlord",
          "A roof costs money.",
        ),
        otherSide(
          event.actor_id === p.owner_id ? p.tenant_id! : p.owner_id!,
          event.actor_id,
          world,
          "Other party",
        ),
      ]);
    }
    case "action_rejected":
      return entry(
        event,
        "loss",
        `${actor} tried to ${event.payload.action_type.replaceAll("_", " ")}, but: ${event.payload.message.toLowerCase()}`,
        [actorSide(event, world, "Tried", "It was worth a try.")],
      );
    case "trade_offered":
    case "trade_accepted":
    case "trade_declined":
    case "loan_offered":
    case "loan_accepted":
    case "loan_repaid":
    case "loan_defaulted":
      return entry(
        event,
        "trade",
        `${actor}: ${describeEvent(event, world).toLowerCase()}`,
        [actorSide(event, world, "Dealmaker", "A deal worth making.")],
      );
    case "vote_proposed":
    case "vote_closed":
    case "policy_changed":
    case "invention_unlocked":
    case "invention_adopted":
      return entry(event, "build", describeEvent(event, world), [
        actorSide(event, world, "Citizen", "The town should move forward."),
      ]);
    case "intervention_applied": {
      // The player's decree, as the backend applied it (so it survives reloads).
      const { text, command } = event.payload;
      return entry(
        event,
        "decree",
        command ? describe(command, world) : `“${text}”`,
        [
          {
            name: "You",
            role: "Decree",
            incentive: "Shape the town from above",
            thought: text,
          },
          {
            name: "Oakhaven",
            role: "The town",
            incentive: "Live with the new rule",
            thought: command
              ? reactionTo(command)
              : "Villagers repeat your words to one another, unsure what comes next.",
          },
        ],
      );
    }
    default:
      // Routine: wages, meals, harvests, movement, ties (told with the interaction),
      // tick markers.
      return null;
  }
}
