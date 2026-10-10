/**
 * Header event stream. Live, it is built from the backend's committed events
 * (`useLiveChronicle`, see chronicle.ts). Offline previews reveal the
 * HARD-CODED `SAMPLE_EVENTS` instead, and scripted fights write their own.
 */
import { useEffect } from "react";
import { create } from "zustand";
import { request } from "../api/client";
import type { SimulationEvent, WorldState } from "../api/types";
import { useWorld } from "../stores/world";
import { useFights } from "../world/fights";
import { HOSTILE, isRepeat, rememberNames, toEntry } from "./chronicle";

export type FeedKind =
  | "build"
  | "trade"
  | "people"
  | "talk"
  | "price"
  | "job"
  | "home"
  | "loss"
  /** Two villagers came to blows. */
  | "fight"
  /** Something the player decreed from above. */
  | "decree";

/** One person's side of a decision. */
export type Side = {
  name: string;
  /** Their part in the event, e.g. "Buyer". */
  role: string;
  /** What they wanted out of it. */
  incentive: string;
  /** How they reasoned, in their own words. */
  thought: string;
  /** Who decided: "AI agent", "Mock agent", "Utility rule", "Town rule", "Memory"… */
  source?: string;
  /** The villager, when this side is one: their name opens their details. */
  id?: string;
};

export type FeedItem = {
  id: number;
  day: number;
  kind: FeedKind;
  text: string;
  /** The people involved: whoever acted first, then the other party. */
  why: Side[];
};

const SAMPLE_EVENTS: Omit<FeedItem, "id">[] = [
  {
    day: 1,
    kind: "trade",
    text: "Rowan bought a loaf from Hearth & Grain",
    why: [
      {
        name: "Rowan",
        role: "Buyer",
        incentive: "Hunger was at 60 and rising",
        thought:
          "I had no bread left and a full day in the fields ahead. Five coins is steep, but it's the only bakery open.",
      },
      {
        name: "Marcus",
        role: "Seller",
        incentive: "Turn fresh bread into coin before it goes stale",
        thought:
          "Rowan buys every morning. Keeping the price at 5.00 pays Theo's wage and the next sack of wheat.",
      },
    ],
  },
  {
    day: 1,
    kind: "talk",
    text: "Finn told Elena bread is getting costly",
    why: [
      {
        name: "Finn",
        role: "Speaker",
        incentive: "Protect his thin savings",
        thought:
          "If enough of us complain, maybe Marcus will lower his price. Elena has the most sway in town.",
      },
      {
        name: "Elena",
        role: "Listener",
        incentive: "Keep her workers fed and productive",
        thought:
          "If Finn is struggling, Rowan will be next. Hungry farmhands harvest less.",
      },
    ],
  },
  {
    day: 2,
    kind: "job",
    text: "Theo was paid 1.50 at Hearth & Grain",
    why: [
      {
        name: "Marcus",
        role: "Employer",
        incentive: "Keep his miller loyal",
        thought:
          "Without Theo, I mill my own flour and bake half as much. Paying on time is cheaper than training someone new.",
      },
      {
        name: "Theo",
        role: "Worker",
        incentive: "Save toward his own market",
        thought:
          "Every wage goes in the jar. One day the empty lot will be mine.",
      },
    ],
  },
  {
    day: 3,
    kind: "build",
    text: "Mira broke ground on Mira's Bakehouse",
    why: [
      {
        name: "Mira",
        role: "Founder",
        incentive: "Stop paying rent and build wealth",
        thought:
          "Hearth & Grain sells out by noon. A second bakery on the open lot will have customers from day one.",
      },
    ],
  },
  {
    day: 4,
    kind: "trade",
    text: "Hearth & Grain bought 2 wheat from Goldenfield Farm",
    why: [
      {
        name: "Marcus",
        role: "Buyer",
        incentive: "Never run out of flour",
        thought:
          "Two wheat makes three loaves. I'm down to my last sack, so I buy before the price climbs.",
      },
      {
        name: "Elena",
        role: "Seller",
        incentive: "Sell the harvest while it's fresh",
        thought:
          "The silo is full and Marcus always pays. Better a steady buyer than a perfect price.",
      },
    ],
  },
  {
    day: 5,
    kind: "people",
    text: "Sage arrived looking for work",
    why: [
      {
        name: "Sage",
        role: "Newcomer",
        incentive: "Find steady work and a roof",
        thought:
          "Word on the road is Oakhaven's farm is hiring and bread is plentiful. Worth the walk.",
      },
    ],
  },
  {
    day: 5,
    kind: "home",
    text: "Sage rented a cottage from Elena",
    why: [
      {
        name: "Sage",
        role: "Tenant",
        incentive: "Live close to work",
        thought:
          "Seven coins a week is fair, and the cottage is a short walk from the fields.",
      },
      {
        name: "Elena",
        role: "Landlord",
        incentive: "Earn rent from an empty lot",
        thought:
          "An empty lot earns nothing. A tenant who works my farm is good for both of us.",
      },
    ],
  },
  {
    day: 6,
    kind: "job",
    text: "Sage was hired at Goldenfield Farm",
    why: [
      {
        name: "Elena",
        role: "Employer",
        incentive: "Harvest more before winter",
        thought:
          "Rowan can't work both fields alone. Sage already lives next door.",
      },
      {
        name: "Sage",
        role: "Worker",
        incentive: "Pay the rent",
        thought: "A daily wage covers rent and bread with a little left over.",
      },
    ],
  },
  {
    day: 8,
    kind: "price",
    text: "Marcus cut bread to 4.00 a loaf",
    why: [
      {
        name: "Marcus",
        role: "Baker",
        incentive: "Win customers before Mira opens",
        thought:
          "If Mira undercuts me, I lose the morning crowd. Cheaper bread now keeps them coming to me.",
      },
    ],
  },
  {
    day: 9,
    kind: "talk",
    text: "Ada and Marcus argued about market fees",
    why: [
      {
        name: "Ada",
        role: "Market owner",
        incentive: "Keep her stall profitable",
        thought:
          "Marcus sells straight from his door and skips my market. That isn't fair to the rest of us.",
      },
      {
        name: "Marcus",
        role: "Baker",
        incentive: "Keep his margins",
        thought:
          "Why pay Ada a cut for bread people already walk to my door for?",
      },
    ],
  },
  {
    day: 11,
    kind: "build",
    text: "Goldenfield Farm planted a second field",
    why: [
      {
        name: "Elena",
        role: "Owner",
        incentive: "Supply two bakeries",
        thought:
          "With Mira's bakery coming, wheat demand will double. More fields now, profit later.",
      },
    ],
  },
  {
    day: 12,
    kind: "trade",
    text: "Ada sold 6 wheat at Market Square",
    why: [
      {
        name: "Ada",
        role: "Seller",
        incentive: "Clear stock before the price drops",
        thought:
          "Elena's new field means cheap wheat next week. Sell now while it's still worth something.",
      },
      {
        name: "Finn",
        role: "Buyer",
        incentive: "Bake his own bread",
        thought: "If I bake at home, I don't have to pay Marcus's price.",
      },
    ],
  },
  {
    day: 14,
    kind: "people",
    text: "Wren the baker moved to Oakhaven",
    why: [
      {
        name: "Wren",
        role: "Newcomer",
        incentive: "Work at a growing bakery",
        thought:
          "A town opening its second bakery needs bakers. Better here than competing in the city.",
      },
    ],
  },
  {
    day: 15,
    kind: "talk",
    text: "Mira asked Elena for a loan",
    why: [
      {
        name: "Mira",
        role: "Borrower",
        incentive: "Survive until the bakery turns a profit",
        thought:
          "Wages are due and sales are slow. One loan buys me two more weeks.",
      },
      {
        name: "Elena",
        role: "Lender",
        incentive: "Keep her tenant afloat",
        thought:
          "If Mira fails, I lose a tenant and a wheat buyer. But I've seen her books.",
      },
    ],
  },
  {
    day: 17,
    kind: "loss",
    text: "Mira's Bakehouse missed its wages",
    why: [
      {
        name: "Mira",
        role: "Owner",
        incentive: "Keep the doors open",
        thought:
          "Marcus cut his price and took my customers. I can pay wheat or wages, not both.",
      },
      {
        name: "Wren",
        role: "Worker",
        incentive: "Get paid",
        thought:
          "One missed wage I can forgive. Three and I'm looking for work elsewhere.",
      },
    ],
  },
  {
    day: 19,
    kind: "build",
    text: "Market Square put up a new tent",
    why: [
      {
        name: "Ada",
        role: "Owner",
        incentive: "Draw more traders",
        thought:
          "More stalls means more fees. With newcomers arriving, the market needs room.",
      },
    ],
  },
  {
    day: 21,
    kind: "price",
    text: "The town voted for a bread price cap",
    why: [
      {
        name: "Finn",
        role: "Voted yes",
        incentive: "Afford to eat every day",
        thought:
          "Bread shouldn't cost a day's wage. A cap protects people like me.",
      },
      {
        name: "Marcus",
        role: "Voted no",
        incentive: "Set his own prices",
        thought:
          "If wheat gets dear, a cap means I bake at a loss. The vote ignores my costs.",
      },
    ],
  },
  {
    day: 23,
    kind: "job",
    text: "Bram started work as a builder",
    why: [
      {
        name: "Bram",
        role: "Builder",
        incentive: "Steady pay in a growing town",
        thought:
          "Three new buildings this month. Wherever there's scaffolding, there's work.",
      },
    ],
  },
];

const KEEP = 600;

type Chronicle = {
  /** Newest first. */
  items: FeedItem[];
  nextId: number;
  /** Next sample to reveal. */
  cursor: number;
  add: (item: Omit<FeedItem, "id">) => void;
  revealSample: () => void;
  reset: () => void;
};

/**
 * The chronicle: sample events revealed over time plus the player's decrees,
 * newest first. One store, so the header badge and the full page agree.
 */
export const useChronicle = create<Chronicle>((set, get) => ({
  items: [],
  nextId: 1,
  cursor: 0,
  add: (item) =>
    set((s) => ({
      items: [{ ...item, id: s.nextId }, ...s.items].slice(0, KEEP),
      nextId: s.nextId + 1,
    })),
  reset: () => set({ items: [], cursor: 0 }),
  revealSample: () => {
    const { cursor } = get();
    const sample = SAMPLE_EVENTS[cursor % SAMPLE_EVENTS.length];
    // Each loop continues the day count so the stream keeps moving forward.
    const loop = Math.floor(cursor / SAMPLE_EVENTS.length);
    get().add({ ...sample, day: sample.day + loop * 24 });
    set({ cursor: cursor + 1 });
  },
}));

/** Offline only: reveals a few samples at once, then one every few seconds. */
export function useSampleClock(enabled: boolean, everyMs = 2800) {
  useEffect(() => {
    if (!enabled) return;
    const { items, revealSample } = useChronicle.getState();
    if (!items.length) for (let i = 0; i < 4; i++) revealSample();
    const timer = setInterval(
      () => useChronicle.getState().revealSample(),
      everyMs,
    );
    return () => clearInterval(timer);
  }, [enabled, everyMs]);
}

/** HARD-CODED grudges behind the village scuffles (world/fights.ts). */
const GRUDGES: [string, string][] = [
  ["Owed them coin and never paid", "Tired of being chased for money"],
  ["Was undercut at the market", "Sold fair and square"],
  ["Heard an insult about their bread", "Only said what everyone thinks"],
  ["Lost a job to them", "Was simply better at it"],
  ["Their cart blocked the road all week", "Had nowhere else to park"],
];

/** Offline only: write each scripted scuffle into the chronicle. */
export function useFightChronicle(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    return useFights.subscribe((now, before) => {
      const fight = now.current;
      if (!fight || fight.id === before.current?.id || fight.real) return;
      const state = useWorld.getState().update?.state;
      const name = (id: string) => state?.citizens[id]?.name ?? "Someone";
      const [a, b] = [name(fight.a), name(fight.b)];
      const [grudge, reply] = GRUDGES[fight.id % GRUDGES.length];
      useChronicle.getState().add({
        day: (state?.tick ?? 0) + 1,
        kind: "fight",
        text: `${a} and ${b} came to blows`,
        why: [
          {
            name: a,
            role: "Threw the first punch",
            incentive: grudge,
            thought: `${b} has had this coming for weeks.`,
          },
          {
            name: b,
            role: "Fought back",
            incentive: reply,
            thought: `If ${a} wants a fight, ${a} gets one.`,
          },
        ],
      });
    });
  }, [enabled]);
}

/**
 * Live: rebuild the chronicle from the backend's events, and stage a scuffle
 * in the village for each new argument, insult or betrayal. Mount once.
 */
export function useLiveChronicle(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    const seen = new Set<string>();
    const said = new Map<string, string>();
    let epoch = -1;
    // While earlier history loads, new events wait so the order stays right.
    let loading = false;
    let cancelled = false;

    const take = (
      events: SimulationEvent[],
      state: WorldState,
      live: boolean,
    ) => {
      for (const event of [...events].sort((a, b) => a.sequence - b.sequence)) {
        if (seen.has(event.id)) continue;
        seen.add(event.id);
        if (isRepeat(event, said)) continue;
        const item = toEntry(event, state);
        if (item) useChronicle.getState().add(item);
        if (
          live &&
          event.type === "citizen_interacted" &&
          HOSTILE.has(event.payload.kind) &&
          event.actor_id
        )
          useFights
            .getState()
            .request(event.actor_id, event.payload.recipient_id);
      }
    };

    const sync = () => {
      const world = useWorld.getState();
      const state = world.update?.state;
      if (!state || cancelled) return;
      rememberNames(state);
      if (world.epoch !== epoch) {
        // A new epoch (load, seek, branch switch) replaces history: rebuild it
        // from the event log, quietly (no fights for the past).
        epoch = world.epoch;
        seen.clear();
        said.clear();
        useChronicle.getState().reset();
        loading = true;
        const mine = epoch;
        void loadHistory(state.sequence)
          .catch(() => [] as SimulationEvent[])
          .then((history) => {
            if (cancelled || mine !== epoch) return;
            const latest = useWorld.getState();
            take(history, latest.update?.state ?? state, false);
            take(latest.events, latest.update?.state ?? state, false);
            loading = false;
          });
        return;
      }
      if (!loading) take(world.events, state, true);
    };
    sync();
    const stop = useWorld.subscribe(sync);
    return () => {
      cancelled = true;
      stop();
    };
  }, [enabled]);
}

/** Story-sized history: the last few thousand events, read page by page. */
async function loadHistory(sequence: number, span = 4000) {
  const events: SimulationEvent[] = [];
  let after = Math.max(0, sequence - span);
  while (after < sequence) {
    const page = await request<SimulationEvent[]>(
      `/api/events?after=${after}&limit=500`,
    );
    if (!page.length) break;
    events.push(...page);
    after = page[page.length - 1].sequence;
  }
  return events;
}
