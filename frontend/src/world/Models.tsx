import { useEffect, useMemo, useRef, type RefObject } from "react";
import { useFrame, type ThreeElements } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import {
  AnimationMixer,
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

/** Natural ground speed of each clip at CHARACTER_SCALE, in world units/second. */
const WALK_SPEED = 0.62;
const RUN_SPEED = 1.7;

/** What a villager does while standing still. */
export type Pose =
  "idle" | "idleB" | "sit" | "wave" | "work" | "cheer" | "hammer";
export type Motion = { speed: number; pose: Pose };

const CLIPS = {
  idle: "Idle_A",
  idleB: "Idle_B",
  sit: "Sit_Floor_Idle",
  wave: "Waving",
  work: "Interact",
  cheer: "Cheering",
  hammer: "Hammering",
  walk: "Walking_A",
  run: "Running_A",
} as const;
type Clip = keyof typeof CLIPS;
const ALL = Object.keys(CLIPS) as Clip[];

/**
 * Skinned villager. Movement is driven by the parent; this only blends
 * between the standing pose and walk → run from the current speed, so feet
 * roughly match the ground.
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
  const { mixer, actions } = useMemo(() => {
    const mixer = new AnimationMixer(model);
    const actions = Object.fromEntries(
      ALL.map((name) => [name, mixer.clipAction(clips.get(CLIPS[name])!)]),
    ) as Record<Clip, AnimationAction>;
    return { mixer, actions };
  }, [model, clips]);
  const weights = useRef(
    Object.fromEntries(
      ALL.map((name) => [name, name === "idle" ? 1 : 0]),
    ) as Record<Clip, number>,
  );

  useEffect(() => {
    for (const name of ALL) {
      const action = actions[name];
      action.enabled = true;
      action.setEffectiveWeight(name === "idle" ? 1 : 0);
      action.play();
      // De-synchronize villagers so idles do not breathe in unison.
      action.time = phase * action.getClip().duration;
    }
    // The mixer is per instance and garbage collected with it; uncaching here
    // would break actions reused by React's development re-run of effects.
    return () => void mixer.stopAllAction();
  }, [actions, mixer, phase]);

  useFrame((_, delta) => {
    const { speed = 0, pose = "idle" } = motion.current ?? {};
    const active: Clip = speed < 0.05 ? pose : speed < 1.15 ? "walk" : "run";
    const w = weights.current;
    for (const name of ALL) {
      w[name] = MathUtils.damp(w[name], name === active ? 1 : 0, 7, delta);
      actions[name].setEffectiveWeight(w[name]);
    }
    actions.walk.timeScale = MathUtils.clamp(speed / WALK_SPEED, 0.7, 1.7);
    actions.run.timeScale = MathUtils.clamp(speed / RUN_SPEED, 0.75, 1.4);
    mixer.update(Math.min(delta, 0.1));
  });

  return <primitive object={model} scale={CHARACTER_SCALE} />;
}
