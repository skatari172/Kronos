import { create } from "zustand";
import type { SimulationEvent, WorldUpdate } from "../api/types";

type WorldStore = {
  update: WorldUpdate | null;
  events: SimulationEvent[];
  epoch: number;
  historical: boolean;
  replace: (update: WorldUpdate, historical?: boolean) => void;
  ingest: (update: WorldUpdate) => boolean;
};

export const useWorld = create<WorldStore>((set, get) => ({
  update: null,
  events: [],
  epoch: 0,
  historical: false,
  replace: (update, historical = false) =>
    set({ update, events: update.events, historical, epoch: get().epoch + 1 }),
  ingest: (update) => {
    const current = get();
    if (
      current.historical ||
      !current.update ||
      current.update.branch_id !== update.branch_id ||
      current.update.sequence >= update.sequence
    )
      return false;
    // Full snapshots make sequence gaps safe. Deltas would require explicit resynchronization.
    const events = [...current.events, ...update.events];
    set({
      update,
      events: [...new Map(events.map((e) => [e.id, e])).values()].slice(-150),
    });
    return true;
  },
}));

// Selection and view state never live inside the authoritative snapshot.
export const usePresentation = create<{
  selectedId: string | null;
  select: (id: string | null) => void;
}>((set) => ({
  selectedId: null,
  select: (selectedId) => set({ selectedId }),
}));

/**
 * Whether the simulation is paused. While paused the village holds still:
 * villagers stand idle, no new fights or conversations start, and live events
 * waiting to play out across the day wait too.
 */
export const usePlayback = create<{ paused: boolean }>(() => ({
  paused: false,
}));
