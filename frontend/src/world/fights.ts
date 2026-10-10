/**
 * Village scuffles. HARD-CODED presentation for now: every half-minute or so
 * two villagers fall out, run to a spot on the road, and trade blows. Later
 * this should follow real relationship events (argue, insult, betray, and
 * grudges) from the backend instead of a timer.
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
};

type Fights = {
  current: Fight | null;
  /** performance.now() after which a new fight may start. */
  nextAt: number;
  begin: (fight: Fight) => void;
};

export const useFights = create<Fights>((set) => ({
  current: null,
  nextAt: performance.now() + 18_000,
  begin: (fight) =>
    set({
      current: fight,
      nextAt: fight.endAt + 30_000 + Math.random() * 25_000,
    }),
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
  const { current, nextAt, begin } = useFights.getState();
  if (busy || citizens.length < 2 || now < nextAt) return;
  if (current && current.endAt > now) return;
  const [a, b] = [...citizens].sort(() => Math.random() - 0.5);
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
  });
}
