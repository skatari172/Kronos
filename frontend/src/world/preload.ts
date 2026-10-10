import { useGLTF } from "@react-three/drei";
import {
  ANIMATION_FILES,
  BUILDING_MODELS,
  BUSINESS_DRESSING,
  CHARACTER_FILES,
  LIFECYCLE_MODELS,
  LOT_MODELS,
  hex,
} from "./assets";
import { MAX_TIER, townAt } from "./town";

/**
 * Start loading every model the village can show, for every growth tier, so
 * growing into a new district or staging a construction never waits on the
 * network.
 */
export function preloadModels() {
  const pieces = new Set<string>([
    ...LIFECYCLE_MODELS,
    ...LOT_MODELS,
    ...Object.values(BUSINESS_DRESSING).flatMap((props) =>
      props.map((p) => p.model),
    ),
  ]);
  for (let tier = 0; tier <= MAX_TIER; tier++)
    for (const piece of [...townAt(tier).tiles, ...townAt(tier).scenery])
      pieces.add(piece.model);
  for (const url of [
    ...Object.values(BUILDING_MODELS),
    ...ANIMATION_FILES,
    ...CHARACTER_FILES,
    ...[...pieces].map(hex),
  ])
    useGLTF.preload(url);
}
