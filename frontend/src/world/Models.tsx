import { useEffect, useMemo, useRef, type RefObject } from "react";
import { useFrame, type ThreeElements } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import {
  AnimationMixer,
  LoopOnce,
  type AnimationAction,
  MathUtils,
  type AnimationClip,
  type Mesh,
  type Object3D,
} from "three";
import { clone as cloneSkinned } from "three/examples/jsm/utils/SkeletonUtils.js";
import type { Building } from "../api/types";
import {
  ANIMATION_FILES,
  BUILDING_MODELS,
  BUSINESS_DRESSING,
  CHARACTER_SCALE,
  HEX_SCALE,
  hex,
} from "./assets";

function withShadows<T extends Object3D>(object: T, receive = true) {
  object.traverse((child) => {
    const mesh = child as Mesh;
    if (!mesh.isMesh) return;
    mesh.castShadow = true;
    mesh.receiveShadow = receive;
  });
  return object;
}

/**
 * The hexagon pack paints grass with an olive swatch of its 8×4 gradient atlas.
 * Point those UVs at the fresh-green swatch instead, once per loaded model.
 */
const freshGrass = new WeakMap<Object3D, Object3D>();
function withFreshGrass(scene: Object3D) {
  let result = freshGrass.get(scene);
  if (result) return result;
  result = scene.clone(true);
  result.traverse((child) => {
    const mesh = child as Mesh;
    if (!mesh.isMesh) return;
    mesh.geometry = mesh.geometry.clone();
    const uv = mesh.geometry.getAttribute("uv");
    if (!uv) return;
    for (let i = 0; i < uv.count; i++) {
      const [u, v] = [uv.getX(i), uv.getY(i)];
      if (u >= 0 && u < 0.125 && v >= 0.5 && v < 0.75)
        uv.setXY(i, u + 0.5, v - 0.25);
    }
    uv.needsUpdate = true;
  });
  freshGrass.set(scene, result);
  return result;
}

/** Static model instance. Geometry and materials stay shared with the cache. */
export function StaticModel({
  url,
  scale = HEX_SCALE,
  ...props
}: { url: string; scale?: number } & Omit<ThreeElements["group"], "scale">) {
  const { scene } = useGLTF(url);
  const object = useMemo(
    () => withShadows(withFreshGrass(scene).clone(true)),
    [scene],
  );
  return (
    <group scale={scale} {...props}>
      <primitive object={object} />
    </group>
  );
}

/**
 * A business with the dressing for its level. `flip` turns it to face north,
 * for lots south of the main street. The camera looks from the south-east, so
 * all dressing then stays on the street side: anything behind the building
 * would stand between it and the camera.
 */
export function BuildingModel({
  kind,
  level = 1,
  flip = false,
}: {
  kind: Building["kind"];
  level?: number;
  flip?: boolean;
}) {
  return (
    <group scale={HEX_SCALE}>
      <StaticModel
        url={BUILDING_MODELS[kind]}
        scale={1}
        rotation={[0, flip ? Math.PI : 0, 0]}
      />
      {BUSINESS_DRESSING[kind]
        .filter((prop) => (prop.level ?? 1) <= level)
        .map((prop) => {
          const [x, z] = prop.at;
          return (
            <StaticModel
              key={`${prop.model}:${prop.at}`}
              url={hex(prop.model)}
              scale={prop.size ?? 1}
              position={flip ? [-x, 0, -Math.abs(z)] : [x, 0, z]}
              rotation={[0, (prop.turn ?? 0) + (flip ? Math.PI : 0), 0]}
            />
          );
        })}
    </group>
  );
}

const DUST = Array.from({ length: 12 }, (_, i) => {
  const angle = (i / 12) * Math.PI * 2 + (i % 3) * 0.4;
  return {
    x: Math.cos(angle),
    z: Math.sin(angle),
    size: 0.18 + (i % 4) * 0.06,
  };
});

/** A puff of dust rolling outward; remount (new key) to play again. */
export function Dust({ radius = 1.3 }: { radius?: number }) {
  const group = useRef<Object3D>(null);
  const age = useRef(0);
  useFrame((_, delta) => {
    age.current += delta;
    const t = Math.min(1, age.current / 1.4);
    group.current?.children.forEach((child, i) => {
      const puff = DUST[i];
      const spread = radius * (0.5 + t * 0.7);
      child.position.set(puff.x * spread, 0.15 + t * 0.6, puff.z * spread);
      child.scale.setScalar(puff.size * (1 + t * 1.6));
      const material = (child as Mesh).material as { opacity: number };
      material.opacity = 0.55 * (1 - t);
    });
  });
  return (
    <group ref={group}>
      {DUST.map((_, i) => (
        <mesh key={i}>
          <icosahedronGeometry args={[1, 1]} />
          <meshStandardMaterial
            color="#e6d8b8"
            roughness={1}
            transparent
            depthWrite={false}
            opacity={0.55}
          />
        </mesh>
      ))}
    </group>
  );
}

function useClips() {
  const files = useGLTF(ANIMATION_FILES);
  return useMemo(() => {
    const clips = new Map<string, AnimationClip>();
    for (const clip of files.flatMap((file) => file.animations))
      clips.set(clip.name, clip);
    return clips;
  }, [files]);
}

/** Natural ground speed of each gait at CHARACTER_SCALE, in world units/second. */
const GAIT_SPEED = { walk: 0.62, sneak: 0.4, run: 1.7 };
/** Above this speed a villager runs instead of walking. */
export const RUN_FROM = 1.15;

/** Clip for every pose and gait. Clips in ONCE play a single time and hold. */
const CLIPS = {
  // Standing
  idle: "Idle_A",
  idleB: "Idle_B",
  wave: "Waving",
  cheer: "Cheering",
  jump: "Jump_Full_Short",
  raise: "Ranged_Magic_Raise",
  crouch: "Crouching",
  // Work
  work: "Interact",
  hammer: "Hammering",
  dig: "Digging",
  chop: "Chopping",
  saw: "Sawing",
  knead: "Working_A",
  tend: "Working_B",
  pickup: "PickUp",
  eat: "Use_Item",
  throw: "Throw",
  // Breaks
  sit: "Sit_Floor_Idle",
  pushups: "Push_Ups",
  situps: "Sit_Ups",
  lieDown: "Lie_Down",
  sleep: "Lie_Idle",
  getUp: "Lie_StandUp",
  faint: "Death_A",
  fishCast: "Fishing_Cast",
  fishIdle: "Fishing_Idle",
  fishCatch: "Fishing_Catch",
  spawn: "Spawn_Ground",
  // Fights
  fists: "Melee_Unarmed_Idle",
  punch: "Melee_Unarmed_Attack_Punch_A",
  kick: "Melee_Unarmed_Attack_Kick",
  block: "Melee_Block",
  dodge: "Dodge_Backward",
  hit: "Hit_A",
  hitB: "Hit_B",
  // Gaits
  walkA: "Walking_A",
  walkB: "Walking_B",
  walkC: "Walking_C",
  sneak: "Sneaking",
  runA: "Running_A",
  runB: "Running_B",
} as const;
type Clip = keyof typeof CLIPS;
const ONCE = new Set<Clip>([
  "raise",
  "pickup",
  "eat",
  "throw",
  "lieDown",
  "getUp",
  "faint",
  "fishCast",
  "fishCatch",
  "spawn",
  "punch",
  "kick",
  "block",
  "dodge",
  "hit",
  "hitB",
]);

export type Gait = "walkA" | "walkB" | "walkC" | "sneak";
export type Run = "runA" | "runB";
/** What a villager does while standing still. */
export type Pose = Exclude<Clip, Gait | Run>;
export type Motion = { speed: number; pose: Pose; gait: Gait; run: Run };

type Playing = { action: AnimationAction; weight: number };

/**
 * Skinned villager. Movement is driven by the parent; this blends between the
 * current pose and the villager's own walk or run from the current speed, so
 * feet roughly match the ground. Only clips that are playing or fading out
 * are evaluated, so dozens of clips cost nothing until used.
 */
export function CharacterModel({
  url,
  motion,
  phase,
}: {
  url: string;
  motion: RefObject<Motion>;
  phase: number;
}) {
  const { scene } = useGLTF(url);
  const clips = useClips();
  const model = useMemo(() => {
    const object = withShadows(cloneSkinned(scene), false);
    // Skinned bounds do not follow animation; avoid characters popping at screen edges.
    object.traverse((child) => (child.frustumCulled = false));
    return object;
  }, [scene]);
  const mixer = useMemo(() => new AnimationMixer(model), [model]);
  const playing = useRef(new Map<Clip, Playing>());
  const current = useRef<Clip | null>(null);

  useEffect(() => {
    const map = playing.current;
    // The mixer is per instance and garbage collected with it; uncaching here
    // would break actions reused by React's development re-run of effects.
    return () => {
      mixer.stopAllAction();
      map.clear();
      current.current = null;
    };
  }, [mixer]);

  useFrame((_, delta) => {
    const {
      speed = 0,
      pose = "idle",
      gait = "walkA",
      run = "runA",
    } = motion.current ?? {};
    const active: Clip = speed < 0.05 ? pose : speed < RUN_FROM ? gait : run;
    const map = playing.current;
    if (active !== current.current) {
      current.current = active;
      let entry = map.get(active);
      if (!entry) {
        const action = mixer.clipAction(clips.get(CLIPS[active])!);
        entry = { action, weight: 0 };
        map.set(active, entry);
        if (!ONCE.has(active))
          // De-synchronize villagers so loops do not run in unison.
          action.time = phase * action.getClip().duration;
      }
      if (ONCE.has(active)) {
        entry.action.setLoop(LoopOnce, 1);
        entry.action.clampWhenFinished = true;
        entry.action.reset();
      }
      entry.action.enabled = true;
      entry.action.play();
    }
    for (const [name, entry] of map) {
      entry.weight = MathUtils.damp(
        entry.weight,
        name === active ? 1 : 0,
        8,
        delta,
      );
      if (name !== active && entry.weight < 0.002) {
        entry.action.stop();
        map.delete(name);
        continue;
      }
      entry.action.setEffectiveWeight(entry.weight);
    }
    const walking = gait === "sneak" ? GAIT_SPEED.sneak : GAIT_SPEED.walk;
    map
      .get(gait)
      ?.action.setEffectiveTimeScale(
        MathUtils.clamp(speed / walking, 0.6, 1.8),
      );
    map
      .get(run)
      ?.action.setEffectiveTimeScale(
        MathUtils.clamp(speed / GAIT_SPEED.run, 0.75, 1.4),
      );
    mixer.update(Math.min(delta, 0.1));
  });

  return <primitive object={model} scale={CHARACTER_SCALE} />;
}
