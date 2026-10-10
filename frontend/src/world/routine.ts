/**
 * Presentation-only daily life. Villagers walk the town's roads between their
 * workplace and home (both from the snapshot when it has them), the bakery,
 * landmarks, and construction sites, and take breaks. Economic state is never
 * inferred from these routes; the simulation's own citizen position is only
 * the starting point.
 */
import type { Vector3 } from "three";
import type { Citizen, WorldState } from "../api/types";
import type { Pose } from "./Models";
import { PERSONAL_SPACE } from "./crowd";
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
  /** Seconds left standing still. */
  wait: number;
  pose: Pose;
  facing: number;
  road: string;
  speed: number;
  lane: number;
  siteId?: string;
  arrival?: { pose: Pose; wait: number; at?: Point };
};

type Goal = { road: string; at: Point };

const LEISURE: Pose[] = ["idle", "idleB", "idleB", "wave", "sit", "cheer"];

const pick = <T>(items: T[]) => items[Math.floor(Math.random() * items.length)];
const between = (low: number, high: number) =>
  low + Math.random() * (high - low);

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

export function startRoutine(town: Town, start: Point, seed: number): Routine {
  return {
    points: [],
    wait: 0.5 + (seed % 40) / 10,
    pose: "idle",
    facing: 0,
    road: nearestRoad(town, start),
    // Each villager has their own stride and side of the road.
    speed: 0.6 + (seed % 7) * 0.04,
    lane: ((seed % 5) - 2) * 0.13,
  };
}

/** Choose the next errand and lay out the walk there. */
function plan(
  routine: Routine,
  citizen: Citizen,
  state: WorldState,
  town: Town,
) {
  const buildings = Object.values(state.buildings);
  const near = (at: Point): Goal => ({ road: nearestRoad(town, at), at });
  const site = siteFor(citizen.id, citizen.occupation);
  const work = buildings.find((b) => b.id === citizen.employer_id);
  const bakery = pick(buildings.filter((b) => b.kind === "bakery"));
  const home = homeOf(citizen, state, town);
  const roll = Math.random();
  let goal: Goal;
  let pose: Pose;
  let wait: number;
  routine.siteId = undefined;
  if (site) {
    goal = near(site.at);
    routine.siteId = site.buildingId;
    [pose, wait] = ["hammer", (site.until - performance.now()) / 1000 + 0.5];
  } else if (work && roll < 0.35) {
    goal = near(work.position);
    [pose, wait] = ["work", between(6, 12)];
  } else if (home && roll < 0.55) {
    goal = home;
    [pose, wait] = [pick<Pose>(["idleB", "sit"]), between(5, 10)];
  } else if (bakery && roll < 0.7) {
    goal = near(bakery.position);
    [pose, wait] = ["work", between(3, 6)];
  } else {
    goal = town.places.length ? pick(town.places) : near({ x: 0, z: 0 });
    [pose, wait] = [pick(LEISURE), between(3, 8)];
  }
  // A shrinking town (another branch, a decline) can strand a villager off-road.
  if (!town.roads.has(routine.road)) routine.road = goal.road;
  const path = route(town, routine.road, goal.road);
  routine.points = waypoints(town, path, routine.lane, goal.at);
  routine.road = goal.road;
  routine.arrival = { pose, wait, at: goal.at };
}

/**
 * Advance one frame. Returns the walking speed (0 while on a break) and the
 * direction to face.
 */
export function stepRoutine(
  routine: Routine,
  position: Vector3,
  dt: number,
  citizen: Citizen,
  state: WorldState,
  town: Town,
) {
  // Drop everything to help raise a new building.
  const site = siteFor(citizen.id, citizen.occupation);
  if (site && routine.siteId !== site.buildingId) {
    routine.points = [];
    routine.wait = 0;
  }
  if (routine.wait > 0) {
    routine.wait -= dt;
    return { speed: 0, heading: routine.facing };
  }
  if (!routine.points.length) plan(routine, citizen, state, town);
  const target = routine.points[0];
  const dx = target.x - position.x;
  const dz = target.z - position.z;
  const distance = Math.hypot(dx, dz);
  const heading = Math.atan2(dx, dz);
  // Hurry to a construction site; stroll otherwise.
  const speed = routine.siteId ? routine.speed * 1.8 : routine.speed;
  const travel = Math.min(distance, speed * dt);
  position.x += (dx / (distance || 1)) * travel;
  position.z += (dz / (distance || 1)) * travel;
  // Close enough counts as arrived: someone may already be standing on the
  // exact spot, and the crowd keeps a body-width between villagers.
  const last = routine.points.length === 1;
  if (distance - travel < (last ? PERSONAL_SPACE : 0.15)) {
    routine.points.shift();
    if (!routine.points.length && routine.arrival) {
      // Break at the destination, facing it.
      const { pose, wait, at } = routine.arrival;
      routine.pose = pose;
      routine.wait = wait;
      routine.facing = at
        ? Math.atan2(at.x - position.x, at.z - position.z)
        : heading;
    } else if (!routine.siteId && Math.random() < 0.04) {
      // Now and then, stop on the way to look around or greet someone.
      routine.pose = pick<Pose>(["idle", "idleB", "wave"]);
      routine.wait = between(1.5, 3.5);
      routine.facing = heading + between(-1.2, 1.2);
    }
  }
  return { speed, heading };
}
