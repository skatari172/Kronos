/**
 * The player as the town's god: while a decree falls from the sky villagers
 * raise their arms to it; when it strikes the square they react to what was
 * decreed. Presentation state only; the rule itself is applied by the
 * backend (POST /api/interventions).
 */
import { create } from "zustand";
import type { Pose } from "./Models";

/** How a decree lands with the villagers. */
export type Mood = "good" | "bad" | "neutral";
/** How long villagers react after a decree lands, in ms. */
export const REACT_MS = 3600;

type Decrees = {
  /** Increments with every landing; the 3D strike replays on change. */
  strike: number;
  /** performance.now() while words are falling, and when they landed. */
  fallingUntil: number;
  landedAt: number;
  mood: Mood;
  /** Where decrees strike: the middle of the land (set by DecreeEffect). */
  centre: { x: number; z: number };
  fall: (ms: number) => void;
  land: (mood: Mood) => void;
};

export const useDecrees = create<Decrees>((set) => ({
  strike: 0,
  fallingUntil: 0,
  landedAt: -Infinity,
  mood: "neutral",
  centre: { x: 0, z: 0 },
  fall: (ms) => set({ fallingUntil: performance.now() + ms }),
  land: (mood) =>
    set((s) => ({
      strike: s.strike + 1,
      landedAt: performance.now(),
      fallingUntil: 0,
      mood,
    })),
}));

/**
 * What a villager does because of a decree right now, if anything: arms
 * raised to the falling words, then joy (cheering or jumping) for good news,
 * or a flinch and grumbling for bad news.
 */
export function decreeReaction(seed: number): Pose | null {
  const { fallingUntil, landedAt, mood } = useDecrees.getState();
  const now = performance.now();
  if (now < fallingUntil) return "raise";
  const since = now - landedAt;
  if (since > REACT_MS) return null;
  if (mood === "bad")
    return since < 1100 ? (seed % 2 ? "hit" : "hitB") : "idleB";
  if (mood === "good") return seed % 3 ? "cheer" : "jump";
  return "cheer";
}

/** True while any decree is falling or being reacted to. */
export function decreeBusy() {
  const { fallingUntil, landedAt } = useDecrees.getState();
  const now = performance.now();
  return now < fallingUntil || now - landedAt < REACT_MS;
}
