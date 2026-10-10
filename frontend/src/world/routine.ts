/**
 * Presentation-only daily life. Villagers walk the town's roads between their
 * workplace and home (both from the snapshot when it has them), the bakery,
 * landmarks, the shore, and construction sites, and take breaks made of short
 * pose sequences. Pace follows the errand and the villager's state in the
 * snapshot: hungry villagers hurry to the bakery, broke ones sneak, starving
 * ones faint. Economic state is never inferred from these routes; the
 * simulation's own citizen position is only the starting point.
 */
import type { Vector3 } from "three";
import type { Building, Citizen, WorldState } from "../api/types";
import { physique } from "./assets";
import { PERSONAL_SPACE } from "./crowd";
import { FIGHT_STEPS, fightFor, type Step } from "./fights";
import type { Gait, Pose, Run } from "./Models";
import { siteFor } from "./sites";
import {
  nearestRoad,
  route,
  waypoints,
  type Place,
  type Point,
  type Town,
} from "./town";

export type Routine = {
  points: Point[];
  road: string;
  lane: number;
  /** Strolling speed, from the villager's physique. */
  pace: number;
  walk: Gait;
  run: Run;
  /** Multiplier on pace for the current leg (>1 hurries, runs past RUN_FROM). */
  hurry: number;
  sneaking: boolean;
  /** Pose sequence at the current stop; the head is playing. */
  steps: Step[];
  /** Seconds left in the current step. */
  left: number;
  pose: Pose;
  facing: number;
  siteId?: string;
  fightId?: number;
  arrival?: { steps: Step[]; face?: Point };
};

type Goal = { road: string; at: Point };

const pick = <T>(items: T[]) => items[Math.floor(Math.random() * items.length)];
const between = (low: number, high: number) =>
  low + Math.random() * (high - low);
const hold = (pose: Pose, low: number, high = low): Step => ({
  pose,
  seconds: between(low, high),
});

/** What a villager does at their workplace, by kind of business. */
const WORK: Record<Building["kind"], () => Step[]> = {
  farm: () => [hold("dig", 4, 7), hold("idle", 0.8), hold("dig", 3, 5)],
  bakery: () => [hold("knead", 3, 5), hold("tend", 3, 5), hold("pickup", 1.6)],
  market: () => [hold("work", 2, 3), hold("throw", 1.4), hold("tend", 3, 4)],
};

/** What a villager does at each landmark. */
const LANDMARK: Record<string, () => Step[]> = {
  "The Forge": () => [hold("hammer", 4, 6), hold("idleB", 1.5)],
  "Riverside Lumbermill": () => [hold("chop", 3, 5), hold("saw", 3, 5)],
  "Village Well": () => [hold("pickup", 1.6), hold("eat", 2), hold("idle", 1)],
  "Oakhaven Chapel": () => [hold("idleB", 2, 4), hold("sit", 3, 5)],
};

const LEISURE = (): Step[] =>
  pick([
    [hold("idleB", 3, 6)],
    [hold("wave", 2, 3), hold("idle", 2)],
    [hold("sit", 4, 8)],
    [hold("cheer", 2), hold("idleB", 2)],
    [hold("jump", 1.6), hold("idle", 1.5)],
  ]);

/**
 * Where a villager lives: the lot they lease in the simulation, otherwise a
 * cottage, nearest first in citizen-ID order so homes stay put as the town grows.
 */
export function homeOf(
  citizen: Citizen,
  state: WorldState,
  town: Town,
): Goal | undefined {
  const lot = Object.values(state.plots).find(
    (plot) =>
      plot.tenant_id === citizen.id &&
      !Object.values(state.buildings).some((b) => b.plot_id === plot.id),
  );
  if (lot) return { road: nearestRoad(town, lot.position), at: lot.position };
  const cottages = town.places.filter((p) => p.kind === "home");
  if (!cottages.length) return undefined;
  const renters = new Set(
    Object.values(state.plots).flatMap((p) =>
      p.tenant_id ? [p.tenant_id] : [],
    ),
  );
  const rank = Object.keys(state.citizens)
    .sort()
    .filter((id) => !renters.has(id))
    .indexOf(citizen.id);
  return rank < 0 ? undefined : cottages[rank % cottages.length];
}

/** Names of villagers living in a cottage. */
export function residentsOf(place: Place, state: WorldState, town: Town) {
  return Object.values(state.citizens)
    .filter((c) => homeOf(c, state, town) === place)
    .map((c) => c.name);
}

/**
 * Where a villager is standing when the scene loads: in front of their home,
 * or, if an earlier villager already starts there, at another cottage,
 * landmark, or business spread across the town. Presentation only.
 */
export function startSpot(
  citizen: Citizen,
  state: WorldState,
  town: Town,
  lane: number,
): Point {
  const ids = Object.keys(state.citizens).sort();
  const rank = Math.max(0, ids.indexOf(citizen.id));
  const spot = (goal: Goal) => `${goal.road}`;
  const homes = ids.map((id) => homeOf(state.citizens[id], state, town));
  const spots: Goal[] = [
    ...town.places,
    ...Object.values(state.buildings).map((b) => ({
      road: nearestRoad(town, b.position),
      at: b.position,
    })),
  ];
  const home = homes[rank];
  const shared =
    home && homes.slice(0, rank).some((h) => h && spot(h) === spot(home));
  // Step through the list in strides so neighbours start far apart.
  const goal =
    home && !shared
      ? home
      : (spots[(rank * 5 + 2) % Math.max(1, spots.length)] ?? home);
  if (!goal || !town.roads.has(goal.road)) return { ...citizen.position };
  return waypoints(town, [goal.road], lane, goal.at).at(-1)!;
}

export function startRoutine(
  town: Town,
  start: Point,
  citizen: Citizen,
  fresh: boolean,
): Routine {
  const body = physique(citizen.id);
  const seed = Math.floor(body.pace * 100);
  return {
    points: [],
    road: nearestRoad(town, start),
    lane: ((seed % 5) - 2) * 0.13,
    pace: body.pace,
    walk: body.walk,
    run: body.run,
    hurry: 1,
    sneaking: false,
    // Newcomers rise out of the ground; everyone else starts with a pause.
    steps: fresh ? [hold("spawn", 2.4)] : [hold("idle", 0.5, 4)],
    left: 0,
    pose: fresh ? "spawn" : "idle",
    facing: 0,
  };
}

/** The bakery a villager would buy from: the cheapest one. */
const cheapestBakery = (buildings: Building[]) =>
  buildings
    .filter((b) => b.kind === "bakery")
    .sort((x, y) => x.prices.bread - y.prices.bread)[0];

/** Choose the next errand and lay out the walk there. */
function plan(
  routine: Routine,
  citizen: Citizen,
  state: WorldState,
  town: Town,
  position: Vector3,
) {
  const buildings = Object.values(state.buildings);
  const near = (at: Point): Goal => ({ road: nearestRoad(town, at), at });
  const here = { x: position.x, z: position.z };
  const work = buildings.find((b) => b.id === citizen.employer_id);
  const bakery = cheapestBakery(buildings);
  const home = homeOf(citizen, state, town);
  const broke = citizen.money < 150;
  const roll = Math.random();
  let goal: Goal | null;
  let steps: Step[];
  let hurry = 1;
  routine.siteId = undefined;
  routine.fightId = undefined;

  const site = siteFor(citizen.id, citizen.occupation);
  const fight = fightFor(citizen.id);
  if (fight) {
    // Run to the fight; trade blows from the agreed start.
    routine.fightId = fight.fight.id;
    goal = { road: nearestRoad(town, fight.spot), at: fight.spot };
    const until = Math.max(0, (fight.fight.startAt - performance.now()) / 1000);
    steps = [{ pose: "fists", seconds: until }, ...FIGHT_STEPS[fight.role]];
    hurry = 2.8;
    routine.arrival = { steps, face: fight.opponent };
    return walkTo(routine, town, goal, hurry, false, true);
  }
  if (site) {
    goal = near(site.at);
    routine.siteId = site.buildingId;
    steps = [hold("hammer", (site.until - performance.now()) / 1000 + 0.5)];
    hurry = 2.6;
  } else if (citizen.hunger >= 95 && roll < 0.3) {
    // Starving: faint where they stand, then get back up.
    goal = null;
    steps = [hold("faint", 3), hold("getUp", 2.2), hold("idleB", 1.5)];
  } else if (bakery && citizen.hunger >= 70 && roll < 0.65) {
    // Hungry: hurry to the cheapest bakery, buy a loaf, eat it.
    goal = near(bakery.position);
    steps = [hold("pickup", 1.6), hold("eat", 2.2), hold("idle", 1)];
    hurry = 1.8;
  } else if (work && roll < 0.35) {
    goal = near(work.position);
    steps = WORK[work.kind]();
    hurry = 1.3;
  } else if (home && roll < 0.5) {
    goal = home;
    steps = pick([
      [hold("lieDown", 2.2), hold("sleep", 6, 10), hold("getUp", 2.2)],
      [hold("sit", 5, 9)],
      [hold("idleB", 4, 6)],
    ]);
  } else if (town.shore.length && roll < 0.58) {
    // Fishing off the end of the road.
    goal = pick(town.shore);
    steps = [
      hold("fishCast", 2.2),
      hold("fishIdle", 6, 10),
      hold("fishCatch", 2.6),
      hold("cheer", 1.6),
    ];
  } else if (roll < 0.66) {
    // Exercise right where they are.
    goal = null;
    steps = [hold("pushups", 3, 5), hold("situps", 3, 5), hold("idleB", 1)];
  } else if (bakery && roll < 0.74) {
    goal = near(bakery.position);
    steps = [hold("pickup", 1.6), hold("eat", 2.2)];
  } else {
    const place = town.places.length ? pick(town.places) : null;
    goal = place ?? near(here);
    steps =
      (place && LANDMARK[place.name]?.()) ||
      (place?.kind === "home"
        ? [hold("wave", 2), hold("idleB", 2, 4)]
        : null) ||
      LEISURE();
  }
  routine.arrival = { steps, face: goal?.at };
  if (!goal) {
    routine.points = [];
    beginSteps(routine, steps, routine.facing);
    return;
  }
  // Villagers short of money keep their heads down unless they are in a hurry.
  walkTo(routine, town, goal, hurry, broke && hurry <= 1, false);
}

function walkTo(
  routine: Routine,
  town: Town,
  goal: Goal,
  hurry: number,
  sneaking: boolean,
  exact: boolean,
) {
  // A shrinking town (another branch, a decline) can strand a villager off-road.
  if (!town.roads.has(routine.road)) routine.road = goal.road;
  const path = route(town, routine.road, goal.road);
  routine.points = exact
    ? [...waypoints(town, path, routine.lane).slice(0, -1), goal.at]
    : waypoints(town, path, routine.lane, goal.at);
  routine.road = goal.road;
  routine.hurry = hurry;
  routine.sneaking = sneaking;
}

function beginSteps(routine: Routine, steps: Step[], facing: number) {
  routine.steps = [...steps];
  routine.left = steps[0]?.seconds ?? 0;
  routine.pose = steps[0]?.pose ?? "idle";
  routine.facing = facing;
}

/**
 * Advance one frame. Returns the speed (0 while stopped), the direction to
 * face, and the gait to animate.
 */
export function stepRoutine(
  routine: Routine,
  position: Vector3,
  dt: number,
  citizen: Citizen,
  state: WorldState,
  town: Town,
): { speed: number; heading: number; gait: Gait } {
  // Drop everything for a fight or to help raise a new building.
  const fight = fightFor(citizen.id);
  const site = siteFor(citizen.id, citizen.occupation);
  if (
    (fight && routine.fightId !== fight.fight.id) ||
    (!fight && site && routine.siteId !== site.buildingId)
  ) {
    routine.points = [];
    routine.steps = [];
  }
  // Playing a pose sequence.
  if (routine.steps.length) {
    routine.left -= dt;
    if (routine.left <= 0) {
      routine.steps.shift();
      if (routine.steps.length) {
        routine.left = routine.steps[0].seconds;
        routine.pose = routine.steps[0].pose;
      } else routine.fightId = undefined;
    }
    if (routine.steps.length)
      return { speed: 0, heading: routine.facing, gait: routine.walk };
  }
  if (!routine.points.length) {
    plan(routine, citizen, state, town, position);
    if (routine.steps.length)
      return { speed: 0, heading: routine.facing, gait: routine.walk };
  }
  const target = routine.points[0];
  const dx = target.x - position.x;
  const dz = target.z - position.z;
  const distance = Math.hypot(dx, dz);
  const heading = Math.atan2(dx, dz);
  const speed = routine.sneaking
    ? routine.pace * 0.6
    : routine.pace * routine.hurry;
  const travel = Math.min(distance, speed * dt);
  position.x += (dx / (distance || 1)) * travel;
  position.z += (dz / (distance || 1)) * travel;
  // Close enough counts as arrived: someone may already be standing on the
  // exact spot, and the crowd keeps a body-width between villagers. Fighters
  // need their exact spots to face off.
  const last = routine.points.length === 1;
  const reach = last ? (routine.fightId ? 0.12 : PERSONAL_SPACE) : 0.15;
  if (distance - travel < reach) {
    routine.points.shift();
    if (!routine.points.length && routine.arrival) {
      // Begin the stop's poses, facing what they came for.
      const { steps, face } = routine.arrival;
      routine.arrival = undefined;
      beginSteps(
        routine,
        steps,
        face ? Math.atan2(face.x - position.x, face.z - position.z) : heading,
      );
      routine.hurry = 1;
    } else if (!routine.siteId && !routine.fightId && Math.random() < 0.04) {
      // Now and then, stop on the way to look around or greet someone.
      beginSteps(
        routine,
        [hold(pick<Pose>(["idle", "idleB", "wave"]), 1.5, 3.5)],
        heading + between(-1.2, 1.2),
      );
    }
  }
  return {
    speed,
    heading,
    gait: routine.sneaking ? "sneak" : routine.walk,
  };
}
