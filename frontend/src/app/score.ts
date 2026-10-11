/**
 * The game layer: World Health, a score with reasons, and the point of no
 * return. Everything is read from the backend's snapshot and committed events
 * (like the growth tiers, a presentation score the simulation knows nothing
 * about), so every viewer of the same world sees the same health and score.
 */
import { useEffect } from "react";
import { create } from "zustand";
import type { SimulationEvent, WorldState } from "../api/types";
import { useWorld } from "../stores/world";
import { nameOf, rememberNames } from "./chronicle";

export type Part = {
  key: string;
  label: string;
  /** 0-100, higher is healthier. */
  value: number;
  weight: number;
  /** Why it is low, in plain words (only when it is). */
  why?: string;
};

const avg = (values: number[]) =>
  values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;

/** World Health, 0-100, from its parts; the lowest parts give the reasons. */
export function health(state: WorldState) {
  const citizens = Object.values(state.citizens);
  const buildings = Object.values(state.buildings);
  const bakeries = buildings.filter((b) => b.kind === "bakery");
  const loaf = bakeries.length
    ? Math.min(...bakeries.map((b) => b.prices.bread))
    : Infinity;
  const owners = new Set(buildings.map((b) => b.owner_id));
  const hunger = avg(citizens.map((c) => c.hunger));
  const canEat = citizens.filter((c) => c.money >= loaf).length;
  const working = citizens.filter(
    (c) =>
      owners.has(c.id) || (c.employer_id && state.buildings[c.employer_id]),
  ).length;
  const grudges = citizens.flatMap((c) => c.relationships.map((r) => r.grudge));
  const wheat = state.resources.wheat?.stock ?? 0;
  const n = Math.max(1, citizens.length);
  const parts: Part[] = [
    {
      key: "food",
      label: "Food",
      value: 100 - hunger,
      weight: 0.35,
      why:
        hunger > 60
          ? `Villagers are hungry (average hunger ${Math.round(hunger)})`
          : undefined,
    },
    {
      key: "livelihood",
      label: "Livelihoods",
      value: (canEat / n) * 100,
      weight: 0.2,
      why:
        canEat < n / 2
          ? bakeries.length
            ? `${n - canEat} of ${n} can't afford a loaf`
            : "There is no bakery to buy bread from"
          : undefined,
    },
    {
      key: "jobs",
      label: "Jobs",
      value: (working / n) * 100,
      weight: 0.2,
      why: working < n / 2 ? `${n - working} of ${n} have no work` : undefined,
    },
    {
      key: "harmony",
      label: "Harmony",
      value: Math.max(0, 100 - avg(grudges) * 2.5),
      weight: 0.1,
      why: avg(grudges) > 20 ? "Grudges are running high" : undefined,
    },
    {
      key: "harvest",
      label: "Harvest",
      value: Math.min(100, (wheat / 120) * 100),
      weight: 0.15,
      why:
        wheat < 40
          ? `The wheat field is nearly bare (${wheat} left)`
          : undefined,
    },
  ];
  const weighted = parts.reduce(
    (sum, p) => sum + Math.max(0, Math.min(100, p.value)) * p.weight,
    0,
  );
  // Nothing outweighs starvation: health never sits more than 20 above food.
  const food = Math.max(0, parts[0].value);
  const value = Math.round(Math.min(weighted, food + STARVING_CAP));
  const reasons = parts
    .filter((p) => p.why)
    .sort((a, b) => a.value - b.value)
    .map((p) => p.why!);
  return { value, parts, reasons };
}

/** Points for a committed event, with the reason shown in the ledger. */
export function pointsFor(
  event: SimulationEvent,
  name: (id?: string | null) => string,
): [number, string] | null {
  switch (event.type) {
    case "citizen_spawned":
      return [5, `${name(event.payload.entity_id)} arrived`];
    case "citizen_removed":
      return [-15, `${name(event.payload.entity_id)} left Oakhaven`];
    case "building_constructed":
      return [10, `${name(event.actor_id)} founded a business`];
    case "building_upgraded":
      return [8, `${name(event.payload.entity_id)} expanded`];
    case "building_removed":
      return [-20, `${name(event.payload.entity_id)} closed down`];
    case "lot_leased":
      return [3, `${name(event.payload.tenant_id)} rented a home`];
    case "employment_changed":
      return event.payload.building_id
        ? [2, `${name(event.payload.citizen_id)} found work`]
        : [-3, `${name(event.payload.citizen_id)} lost their job`];
    case "citizen_interacted":
      return ["argue", "insult", "betray"].includes(event.payload.kind)
        ? [
            -1,
            `${name(event.actor_id)} quarrelled with ${name(event.payload.recipient_id)}`,
          ]
        : null;
    case "intervention_applied": {
      // God's help has a price: the best towns thrive on their own. Handouts
      // (gifts, feasts) cost most; they also tax the town in the simulation.
      const c = (event.payload.command ?? {}) as {
        amount?: number;
        change?: number;
      };
      const kind = event.payload.kind;
      const cost =
        kind === "grant_money" && (c.amount ?? 0) > 0
          ? 15
          : kind === "adjust_hunger" && (c.change ?? 0) < 0
            ? 10
            : 5;
      return [-cost, `You stepped in: “${event.payload.text}”`];
    }
    default:
      return null;
  }
}

export type Entry = { id: number; day: number; delta: number; reason: string };

export type Loss = { day: number; reason: string; detail: string };

/** Days in a row below this health count toward the point of no return. */
export const CRITICAL = 25;
/** World Health is at most this far above the food score (see `health`). */
const STARVING_CAP = 20;
/** That many days in a row, and Oakhaven is lost. */
export const CRITICAL_DAYS = 3;

type Score = {
  points: number;
  ledger: Entry[];
  /** Consecutive days at critical health, and the last day counted. */
  criticalDays: number;
  lastDay: number;
  peakPopulation: number;
  lost: Loss | null;
  /** The player chose to keep watching a lost town. */
  dismissed: boolean;
  add: (day: number, delta: number, reason: string) => void;
  reset: () => void;
};

let nextId = 1;

export const useScore = create<Score>((set) => ({
  points: 0,
  ledger: [],
  criticalDays: 0,
  lastDay: -1,
  peakPopulation: 0,
  lost: null,
  dismissed: false,
  add: (day, delta, reason) =>
    set((s) => ({
      points: Math.max(0, s.points + delta),
      ledger: [{ id: nextId++, day, delta, reason }, ...s.ledger].slice(0, 200),
    })),
  reset: () =>
    set({
      points: 0,
      ledger: [],
      criticalDays: 0,
      lastDay: -1,
      peakPopulation: 0,
      lost: null,
      dismissed: false,
    }),
}));

/**
 * The point of no return, if this world has reached it: almost no one left,
 * no bakery while everyone starves, or critical health for days on end.
 */
export function noReturn(
  state: WorldState,
  criticalDays: number,
): Omit<Loss, "day"> | null {
  const citizens = Object.values(state.citizens);
  const bakeries = Object.values(state.buildings).filter(
    (b) => b.kind === "bakery",
  );
  const hunger = avg(citizens.map((c) => c.hunger));
  if (citizens.length < 3)
    return {
      reason: "Almost everyone has gone",
      detail: `Only ${citizens.length} villager${citizens.length === 1 ? "" : "s"} remain${citizens.length === 1 ? "s" : ""}. There is no town left to run.`,
    };
  if (!bakeries.length && hunger >= 95)
    return {
      reason: "Starvation",
      detail:
        "The last bakery has closed and every villager is starving. No one is left to bake bread.",
    };
  if (criticalDays >= CRITICAL_DAYS) {
    const why = health(state).reasons[0];
    return {
      reason: "Collapse",
      detail: `World Health stayed below ${CRITICAL} for ${CRITICAL_DAYS} days.${why ? ` ${why}.` : ""}`,
    };
  }
  return null;
}

const SAVE = "kronos.score.";

function save(branch: string) {
  try {
    const {
      points,
      ledger,
      criticalDays,
      lastDay,
      peakPopulation,
      lost,
      dismissed,
    } = useScore.getState();
    localStorage.setItem(
      SAVE + branch,
      JSON.stringify({
        points,
        ledger: ledger.slice(0, 60),
        criticalDays,
        lastDay,
        peakPopulation,
        lost,
        dismissed,
      }),
    );
  } catch {
    /* The score still works for this visit. */
  }
}

function restore(branch: string) {
  try {
    const saved = localStorage.getItem(SAVE + branch);
    if (saved) useScore.setState(JSON.parse(saved));
  } catch {
    /* Start from zero. */
  }
}

/**
 * Keep score as the world changes: points for each committed event, daily
 * points from World Health, a bonus for each new tier, critical-day tracking,
 * and the point of no return. Saved per village in this browser, so a reload
 * keeps the score. Mount once.
 */
export function useGame(
  tierOf: (state: WorldState, epoch: number) => number,
  tierName: (tier: number) => string,
) {
  useEffect(() => {
    const seen = new Set<string>();
    let epoch = -1;
    let branch = "";
    let tier = -1;
    const sync = () => {
      const world = useWorld.getState();
      const state = world.update?.state;
      if (!state) return;
      rememberNames(state);
      const score = useScore.getState();
      if (world.epoch !== epoch) {
        // A new village, a reload or a branch switch: its own score.
        epoch = world.epoch;
        branch = world.update!.branch_id;
        seen.clear();
        score.reset();
        restore(branch);
        tier = tierOf(state, epoch);
        world.events.forEach((e) => seen.add(e.id));
      }
      const day = state.tick;
      for (const event of world.events) {
        if (seen.has(event.id)) continue;
        seen.add(event.id);
        const scored = pointsFor(event, (id) => nameOf(id));
        if (scored) score.add(event.tick, ...scored);
      }
      const now = useScore.getState();
      if (day > now.lastDay) {
        const h = health(state).value;
        if (now.lastDay >= 0) {
          const daily = Math.round(h / 20);
          if (daily) score.add(day, daily, `Day ${day}: World Health ${h}`);
        }
        useScore.setState({
          lastDay: day,
          criticalDays: h < CRITICAL ? now.criticalDays + 1 : 0,
          peakPopulation: Math.max(
            now.peakPopulation,
            Object.keys(state.citizens).length,
          ),
        });
      }
      const reached = tierOf(state, epoch);
      if (reached > tier && tier >= 0)
        score.add(day, 50, `Oakhaven became a ${tierName(reached)}`);
      tier = Math.max(tier, reached);
      const after = useScore.getState();
      if (!after.lost && !after.dismissed) {
        const loss = noReturn(state, after.criticalDays);
        if (loss) useScore.setState({ lost: { ...loss, day } });
      }
      save(branch);
    };
    sync();
    return useWorld.subscribe(sync);
  }, [tierOf, tierName]);
}
