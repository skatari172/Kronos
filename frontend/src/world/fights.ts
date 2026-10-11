/**
 * Village scuffles: two villagers run to a spot on the road and trade blows.
 * Live, each one is staged from a real `citizen_interacted` event (argue,
 * insult, betray) via `request`. Offline previews, which have no agents,
 * fall back to a scripted fight every half-minute or so.
 */
import { create } from "zustand";
import type { Pose } from "./Models";
import { nearestRoad, type Point, type Town } from "./town";

export type Step = { pose: Pose; seconds: number };

/** Seconds from the agreed start: who swings, who blocks, who gets hit. */
export const FIGHT_STEPS: Record<"a" | "b", Step[]> = {
  a: [
    { pose: "fists", seconds: 1 },
    { pose: "punch", seconds: 1 },
    { pose: "hit", seconds: 1.1 },
    { pose: "fists", seconds: 0.7 },
    { pose: "punch", seconds: 1 },
  ],
  b: [
    { pose: "fists", seconds: 1 },
    { pose: "block", seconds: 1 },
    { pose: "kick", seconds: 1.1 },
    { pose: "fists", seconds: 0.7 },
    { pose: "dodge", seconds: 1 },
  ],
};
const FIGHT_SECONDS = FIGHT_STEPS.a.reduce((sum, s) => sum + s.seconds, 0);
/** Time for both to run to the spot before the first swing. */
const GATHER_SECONDS = 7;

export type Fight = {
  id: number;
  a: string;
  b: string;
  at: Point;
  /** performance.now() of the first swing, and of the last. */
  startAt: number;
  endAt: number;
  /** Staged from a real event rather than the offline script. */
  real?: boolean;
};

type Fights = {
  current: Fight | null;
  /** performance.now() after which a new fight may start. */
  nextAt: number;
  /** Offline previews script fights on a timer; live ones only follow events. */
  scripted: boolean;
  /** Real quarrels waiting for the road to clear (oldest first, a few at most;
   *  extras are still in the chronicle, just not staged). */
  pending: { a: string; b: string }[];
  begin: (fight: Fight) => void;
  request: (a: string, b: string) => void;
};

export const useFights = create<Fights>((set) => ({
  current: null,
  nextAt: performance.now() + 18_000,
  // Off until the app knows it is an offline preview (App.tsx turns it on).
  scripted: false,
  pending: [],
  begin: (fight) =>
    set((s) => ({
      current: fight,
      // Real quarrels play back to back; scripted ones are spaced out.
      nextAt:
        fight.endAt + (fight.real ? 12_000 : 30_000 + Math.random() * 25_000),
      pending: fight.real ? s.pending.slice(1) : s.pending,
    })),
  request: (a, b) =>
    set((s) =>
      s.pending.length >= 3 || a === b
        ? s
        : {
            pending: [...s.pending, { a, b }],
            nextAt: Math.min(s.nextAt, performance.now()),
          },
    ),
}));

/** This villager's part in the current fight, if any. */
export function fightFor(citizenId: string) {
  const fight = useFights.getState().current;
  if (!fight || fight.endAt < performance.now()) return undefined;
  const role = fight.a === citizenId ? "a" : fight.b === citizenId ? "b" : null;
  if (!role) return undefined;
  const side = role === "a" ? -1 : 1;
  return {
    fight,
    role,
    spot: { x: fight.at.x + side * 0.42, z: fight.at.z + 0.05 * side },
    opponent: { x: fight.at.x - side * 0.42, z: fight.at.z },
  } as const;
}

/**
 * Start a fight when it's time: two random villagers meet halfway, on the
 * nearest road. Called every frame by the scene; cheap when idle.
 */
export function directFights(
  citizens: { id: string; x: number; z: number }[],
  town: Town,
  busy: boolean,
) {
  const now = performance.now();
  const { current, nextAt, begin, scripted, pending } = useFights.getState();
  if (busy || citizens.length < 2) return;
  if ((current && current.endAt > now) || now < nextAt) return;
  let a, b;
  if (pending.length) {
    a = citizens.find((c) => c.id === pending[0].a);
    b = citizens.find((c) => c.id === pending[0].b);
    if (!a || !b) {
      // Someone left or isn't in the scene yet: drop this quarrel.
      useFights.setState({ pending: pending.slice(1) });
      return;
    }
  } else {
    if (!scripted) return;
    [a, b] = [...citizens].sort(() => Math.random() - 0.5);
  }
  const middle = { x: (a.x + b.x) / 2, z: (a.z + b.z) / 2 };
  const road = town.roads.get(nearestRoad(town, middle));
  if (!road) return;
  const startAt = now + GATHER_SECONDS * 1000;
  begin({
    id: Math.round(now),
    a: a.id,
    b: b.id,
    at: road.at,
    startAt,
    endAt: startAt + FIGHT_SECONDS * 1000,
    real: pending.length > 0,
  });
}
