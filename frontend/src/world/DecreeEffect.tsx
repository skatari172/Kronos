import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import {
  AdditiveBlending,
  MathUtils,
  type Group,
  type Mesh,
  type MeshBasicMaterial,
  type PointLight,
} from "three";
import { useDecrees } from "./decrees";
import { useTown } from "./progress";
import { landCentre } from "./town";

/** Length of the strike animation, in seconds. */
const STRIKE_S = 2.8;
const SPARKS = 48;

/**
 * A decree landing on the town square: a column of golden light, two
 * shockwave rings across the ground, rising sparks, and a warm flash.
 * HARD-CODED presentation; it replays whenever `useDecrees().strike` changes.
 */
export function DecreeEffect() {
  const strike = useDecrees((s) => s.strike);
  const group = useRef<Group>(null);
  // Strike the middle of the land, wherever it has grown to.
  const town = useTown();
  const centre = useMemo(() => landCentre(town), [town]);
  useEffect(() => useDecrees.setState({ centre }), [centre]);
  const beam = useRef<Mesh>(null);
  const halo = useRef<Mesh>(null);
  const rings = useRef<(Mesh | null)[]>([]);
  const sparks = useRef<Group>(null);
  const light = useRef<PointLight>(null);
  const age = useRef(STRIKE_S);

  const trajectories = useMemo(
    () =>
      Array.from({ length: SPARKS }, (_, i) => {
        const angle = (i / SPARKS) * Math.PI * 2 + (i % 5) * 0.3;
        return {
          x: Math.cos(angle) * (0.6 + (i % 7) * 0.25),
          z: Math.sin(angle) * (0.6 + (i % 7) * 0.25),
          rise: 2.5 + (i % 9) * 0.55,
          size: 0.06 + (i % 4) * 0.025,
        };
      }),
    [],
  );

  useEffect(() => {
    if (strike) age.current = 0;
  }, [strike]);

  useFrame((_, dt) => {
    if (!group.current) return;
    age.current = Math.min(STRIKE_S, age.current + dt);
    const t = age.current / STRIKE_S;
    group.current.visible = t < 1;
    if (t >= 1) return;
    const fade = (from: number, to: number) =>
      1 - MathUtils.smoothstep(t, from, to);
    const opacity = (mesh: Mesh | null, value: number) => {
      if (mesh) (mesh.material as MeshBasicMaterial).opacity = value;
    };
    // Beam: snaps in, narrows, fades.
    if (beam.current) {
      const width = MathUtils.lerp(1.6, 0.25, MathUtils.smoothstep(t, 0, 0.6));
      beam.current.scale.set(width, 1, width);
      opacity(beam.current, 0.5 * fade(0.25, 0.75));
    }
    if (halo.current) {
      halo.current.scale.setScalar(1 + t * 3);
      opacity(halo.current, 0.45 * fade(0, 0.5));
    }
    // Two shockwaves roll out across the island.
    rings.current.forEach((ring, i) => {
      if (!ring) return;
      const local = MathUtils.clamp((t - i * 0.18) / 0.7, 0, 1);
      ring.scale.setScalar(0.01 + local * (16 - i * 4));
      opacity(ring, 0.75 * (1 - local) * (local > 0 ? 1 : 0));
    });
    sparks.current?.children.forEach((spark, i) => {
      const path = trajectories[i];
      const rise = MathUtils.smoothstep(t, 0.05, 1);
      spark.position.set(
        path.x * (1 + rise * 2),
        rise * path.rise,
        path.z * (1 + rise * 2),
      );
      spark.rotation.y += dt * 4;
      opacity(spark as Mesh, fade(0.4, 1));
    });
    if (light.current) light.current.intensity = 60 * fade(0, 0.6);
  });

  const gold = {
    color: "#ffd36b",
    transparent: true,
    depthWrite: false,
    blending: AdditiveBlending,
  } as const;
  return (
    <group ref={group} visible={false} position={[centre.x, 0, centre.z]}>
      <mesh ref={beam} position={[0, 15, 0]}>
        <cylinderGeometry args={[0.6, 0.9, 30, 24, 1, true]} />
        <meshBasicMaterial {...gold} side={2} />
      </mesh>
      <mesh ref={halo} position={[0, 0.06, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[1.4, 48]} />
        <meshBasicMaterial {...gold} />
      </mesh>
      {[0, 1].map((i) => (
        <mesh
          key={i}
          ref={(m) => {
            rings.current[i] = m;
          }}
          position={[0, 0.08, 0]}
          rotation={[-Math.PI / 2, 0, 0]}
        >
          <ringGeometry args={[0.92, 1, 96]} />
          <meshBasicMaterial {...gold} side={2} />
        </mesh>
      ))}
      <group ref={sparks}>
        {trajectories.map((path, i) => (
          <mesh key={i} scale={path.size}>
            <octahedronGeometry args={[1, 0]} />
            <meshBasicMaterial {...gold} />
          </mesh>
        ))}
      </group>
      <pointLight
        ref={light}
        position={[0, 3, 0]}
        color="#ffcf6a"
        intensity={0}
        distance={22}
      />
    </group>
  );
}
