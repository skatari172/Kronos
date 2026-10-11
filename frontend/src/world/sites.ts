/**
 * Construction sites currently animating, registered by building renderers so
 * villager routines can send builders there. Presentation state only.
 */
import type { Point } from "./town";

export type Site = {
  buildingId: string;
  ownerId: string;
  at: Point;
  /** performance.now() when the scaffolding comes down. */
  until: number;
  /** The founder has reached the plot (building starts when they do). */
  arrived?: boolean;
};

const sites = new Map<string, Site>();

export function openSite(site: Site) {
  sites.set(site.buildingId, site);
  return () => {
    if (sites.get(site.buildingId) === site) sites.delete(site.buildingId);
  };
}

/** The site this citizen should help at, if any. Builders help everywhere. */
export function siteFor(citizenId: string, occupation: string) {
  const now = performance.now();
  for (const site of sites.values())
    if (
      site.until > now &&
      (occupation === "Builder" || site.ownerId === citizenId)
    )
      return site;
  return undefined;
}

/** A villager reached a site; the founder arriving lets building begin. */
export function arriveAt(buildingId: string, citizenId: string) {
  const site = sites.get(buildingId);
  if (site && site.ownerId === citizenId) site.arrived = true;
}

/** Whether the founder has reached this site yet. */
export function founderArrived(buildingId: string) {
  return !!sites.get(buildingId)?.arrived;
}
