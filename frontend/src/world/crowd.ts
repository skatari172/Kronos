/**
 * Keeps villagers from walking through each other. Each villager registers its
 * position; every frame it steps half of any overlap away from its neighbours
 * (the neighbour does the other half on its own frame). Presentation only.
 */
import type { Vector3 } from "three";

/** Closest two villagers may stand, centre to centre, in world units. */
export const PERSONAL_SPACE = 0.42;

const crowd = new Map<string, Vector3>();

export function joinCrowd(id: string, position: Vector3) {
  crowd.set(id, position);
  return () => {
    if (crowd.get(id) === position) crowd.delete(id);
  };
}

export function keepApart(id: string, position: Vector3, seed: number) {
  for (const [other, at] of crowd) {
    if (other === id) continue;
    let dx = position.x - at.x;
    let dz = position.z - at.z;
    let distance = Math.hypot(dx, dz);
    if (distance >= PERSONAL_SPACE) continue;
    if (distance < 1e-4) {
      // Exactly on top of each other: split in a stable, per-villager direction.
      const angle = (seed % 360) * (Math.PI / 180);
      [dx, dz, distance] = [Math.cos(angle), Math.sin(angle), 1];
    }
    const push = (PERSONAL_SPACE - Math.min(distance, PERSONAL_SPACE)) / 2;
    position.x += (dx / distance) * push;
    position.z += (dz / distance) * push;
  }
}

/** Everyone currently in the crowd and where they stand. */
export function crowdPositions() {
  return [...crowd].map(([id, at]) => ({ id, x: at.x, z: at.z }));
}

/** Where one villager stands right now (live; do not modify). */
export function crowdAt(id: string) {
  return crowd.get(id);
}
