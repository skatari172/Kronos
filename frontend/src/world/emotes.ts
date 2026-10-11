/**
 * Thought pops: a small icon and caption that floats up over a villager when
 * their agent acts (buys, applies for work, changes a price…), so a player
 * can watch decisions happen in the town. Fed by the live chronicle.
 */
import { create } from "zustand";

export type EmoteIcon =
  | "bread"
  | "job"
  | "hired"
  | "price"
  | "coins"
  | "no"
  | "build"
  | "home"
  | "goal"
  | "idea"
  | "vote"
  | "arrive";

export type Emote = {
  key: number;
  icon: EmoteIcon;
  text: string;
  tone: "good" | "bad" | "plain";
};

/** Seconds a pop stays up. */
export const EMOTE_SECONDS = 5.5;

let next = 1;

/** At most this many pops show at once; more would flash rather than inform. */
const MAX_SHOWING = 3;
const showing: number[] = [];

export const useEmotes = create<{
  byId: Record<string, Emote>;
  pop: (id: string, emote: Omit<Emote, "key">) => void;
}>((set) => ({
  byId: {},
  pop: (id, emote) => {
    const now = performance.now();
    while (showing.length && showing[0] < now - EMOTE_SECONDS * 1000)
      showing.shift();
    if (showing.length >= MAX_SHOWING) return;
    showing.push(now);
    set((s) => ({ byId: { ...s.byId, [id]: { ...emote, key: next++ } } }));
  },
}));
