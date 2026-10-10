/**
 * The player as the town's god: a decree falls from the sky, strikes the
 * town square, and the villagers stop to cheer. Presentation state only; the
 * rule itself is applied by the backend (POST /api/interventions).
 */
import { create } from "zustand";

/** How long villagers cheer after a decree lands, in ms. */
export const CHEER_MS = 3600;

type Decrees = {
  /** Increments with every landing; the 3D strike replays on change. */
  strike: number;
  /** performance.now() until which villagers stop and cheer. */
  cheerUntil: number;
  land: () => void;
};

export const useDecrees = create<Decrees>((set) => ({
  strike: 0,
  cheerUntil: 0,
  land: () =>
    set((s) => ({
      strike: s.strike + 1,
      cheerUntil: performance.now() + CHEER_MS,
    })),
}));
