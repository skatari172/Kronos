/**
 * Settlement growth, derived only from the authoritative snapshot so every
 * client, historical seek, and branch shows the same town for the same state.
 * It is a presentation score: the simulation has no notion of tiers.
 */
import type { WorldState } from "../api/types";
import { useMemo } from "react";
import { useWorld } from "../stores/world";
import { townAt, withLots } from "./town";

export const TIERS = ["Hamlet", "Village", "Town", "City"] as const;
export type TierName = (typeof TIERS)[number];

/**
 * Score needed to reach each tier. With the seed world, age alone reaches
 * Village after ~50 days and Town after ~140; City needs real construction,
 * upgrades, homes, newcomers, or inventions.
 */
const THRESHOLDS = [0, 25, 70, 140];
const SEED_OFFSET = 44;

export function prosperity(state: WorldState) {
  const buildings = Object.values(state.buildings);
  const citizens = Object.values(state.citizens);
  const homes = Object.values(state.plots).filter(
    (plot) => plot.tenant_id && !buildings.some((b) => b.plot_id === plot.id),
  ).length;
  const adopted = Object.values(state.inventions ?? {}).reduce(
    (sum, invention) => sum + (invention.adopters?.length ?? 0),
    0,
  );
  const hunger =
    citizens.reduce((sum, c) => sum + c.hunger, 0) /
    Math.max(1, citizens.length);
  const parts = {
    // The settlement matures with every day it survives...
    age: Math.min(state.tick, 240) * 0.5,
    // ...and faster with real development.
    businesses: buildings.length * 8,
    upgrades: buildings.reduce((sum, b) => sum + (b.level - 1), 0) * 10,
    homes: homes * 6,
    population: citizens.length * 2,
    // Beyond the v1 score list; kept because inventions are already implemented.
    inventions: adopted * 12,
    // A starving town stalls.
    hardship: -Math.max(0, hunger - 60) * 0.5,
  };
  // The seed world (3 businesses, 1 rented home, 7 citizens, day 0) scores 0.
  const score = Math.max(
    0,
    Object.values(parts).reduce((sum, v) => sum + v, 0) - SEED_OFFSET,
  );
  let tier = 0;
  while (tier + 1 < THRESHOLDS.length && score >= THRESHOLDS[tier + 1]) tier++;
  const next = THRESHOLDS[tier + 1];
  return {
    score,
    tier,
    name: TIERS[tier],
    /** 0–1 toward the next tier; 1 at the top. */
    toNext:
      next === undefined
        ? 1
        : (score - THRESHOLDS[tier]) / (next - THRESHOLDS[tier]),
    next: next === undefined ? null : TIERS[tier + 1],
  };
}

/** A reached tier is only lost once the score falls this far below it. */
const MARGIN = 8;
let settled = { epoch: -1, tier: 0 };

/**
 * The tier to show. Hunger swings daily, so a score near a threshold would
 * flicker the town between tiers; hold a reached tier until the score drops
 * clearly below it. A seek or branch switch (new epoch) starts fresh.
 */
function settle(score: number, tier: number, epoch: number) {
  if (epoch !== settled.epoch || tier > settled.tier) settled = { epoch, tier };
  else if (score < THRESHOLDS[settled.tier] - MARGIN) settled = { epoch, tier };
  return settled.tier;
}

/** Growth for the HUD: the score with the settled tier. */
export function growthOf(state: WorldState, epoch: number) {
  const raw = prosperity(state);
  const tier = settle(raw.score, raw.tier, epoch);
  const next = THRESHOLDS[tier + 1];
  return {
    ...raw,
    tier,
    name: TIERS[tier],
    toNext:
      next === undefined
        ? 1
        : Math.min(
            1,
            Math.max(
              0,
              (raw.score - THRESHOLDS[tier]) / (next - THRESHOLDS[tier]),
            ),
          ),
    next: next === undefined ? null : TIERS[tier + 1],
  };
}

/**
 * The town for the current snapshot's settled growth tier, with ground under
 * and room around every lot, including lots the simulation opens at runtime.
 */
export function useTown() {
  const tier = useWorld((s) => growthOf(s.update!.state, s.epoch).tier);
  // A string, so the selector stays stable until a lot is added or removed.
  const lots = useWorld((s) =>
    Object.values(s.update!.state.plots)
      .map((plot) => `${plot.position.x},${plot.position.z}`)
      .sort()
      .join(";"),
  );
  return useMemo(
    () =>
      withLots(
        townAt(tier),
        lots
          ? lots.split(";").map((pair) => {
              const [x, z] = pair.split(",").map(Number);
              return { x, z };
            })
          : [],
      ),
    [tier, lots],
  );
}
