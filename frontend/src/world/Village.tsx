import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import {
  ContactShadows,
  Html,
  OrbitControls,
  RoundedBox,
} from "@react-three/drei";
import { Group, MathUtils, Vector3 } from "three";
import { activityCue } from "../api/format";
import type { Building, Citizen } from "../api/types";
import { usePresentation, useWorld } from "../stores/world";

type Entity =
  { kind: "building"; value: Building } | { kind: "citizen"; value: Citizen };
type LabelPortal = { current: HTMLDivElement };
type Visual = { entity: Entity; leaving: boolean; fresh: boolean };

function EntityRenderer({
  entity,
  leaving,
  fresh,
  done,
  portal,
}: Visual & { done: () => void; portal: LabelPortal }) {
  const group = useRef<Group>(null);
  const ring = useRef<import("three").Mesh>(null);
  const events = useWorld((s) => s.events);
  const historical = useWorld((s) => s.historical);
  const cue = historical ? undefined : activityCue(events, entity.value.id);
  const lastCue = useRef(cue?.id);
  const pulse = useRef(0);
  useEffect(() => {
    if (cue?.id && cue.id !== lastCue.current) pulse.current = 1;
    lastCue.current = cue?.id;
  }, [cue?.id]);
  const size = useRef(fresh ? 0.01 : 1);
  const selected = usePresentation((s) => s.selectedId === entity.value.id);
  const select = usePresentation((s) => s.select);
  const position = useRef(
    new Vector3(entity.value.position.x, 0, entity.value.position.z),
  );
  const target = new Vector3(
    entity.value.position.x,
    0,
    entity.value.position.z,
  );
  const isBuilding = entity.kind === "building";
  const level = isBuilding ? entity.value.level : 1;
  useFrame((_, dt) => {
    if (!group.current) return;
    // Waypoint route uses the central lane; per-frame transforms stay outside React/Zustand.
    const p = position.current;
    const waypoint =
      Math.abs(p.x - target.x) > 0.04 && Math.abs(p.z) > 0.04
        ? new Vector3(p.x, 0, 0)
        : Math.abs(p.x - target.x) > 0.04
          ? new Vector3(target.x, 0, 0)
          : target;
    if (isBuilding) p.copy(target);
    else p.lerp(waypoint, 1 - Math.exp(-3 * dt));
    group.current.position.copy(p);
    pulse.current = Math.max(0, pulse.current - dt);
    if (ring.current) {
      ring.current.visible = pulse.current > 0;
      ring.current.scale.setScalar(1 + (1 - pulse.current) * 0.8);
    }
    size.current = MathUtils.damp(
      size.current,
      leaving ? 0 : 1 + (level - 1) * 0.14,
      5,
      dt,
    );
    group.current.scale.setScalar(size.current);
    if (leaving && size.current < 0.02) done();
  });
  const color = isBuilding
    ? { farm: "#d8b476", bakery: "#e8c6a2", market: "#b3c8b1" }[
        entity.value.kind
      ]
    : "#f0c79a";
  return (
    <group
      ref={group}
      position={[target.x, 0, target.z]}
      onClick={(e) => {
        e.stopPropagation();
        if (!leaving) select(entity.value.id);
      }}
    >
      {isBuilding ? (
        <>
          <RoundedBox
            args={[2.1, 1.6, 1.65]}
            position={[0, 0.9, 0]}
            radius={0.05}
            castShadow
            receiveShadow
          >
            <meshStandardMaterial color={color} roughness={0.9} />
          </RoundedBox>
          <mesh
            position={[0, 2.05, 0]}
            rotation={[0, Math.PI / 4, 0]}
            castShadow
          >
            <coneGeometry args={[1.85, 1.1, 4]} />
            <meshStandardMaterial
              color={entity.value.kind === "bakery" ? "#a35a42" : "#546d59"}
            />
          </mesh>
          <mesh position={[0, 0.52, 0.84]}>
            <boxGeometry args={[0.45, 0.9, 0.06]} />
            <meshStandardMaterial color="#514137" />
          </mesh>
          {[-0.65, 0.65].map((x) => (
            <mesh key={x} position={[x, 1.08, 0.85]}>
              <boxGeometry args={[0.32, 0.4, 0.06]} />
              <meshStandardMaterial
                color="#ffc575"
                emissive="#e8a34d"
                emissiveIntensity={0.3}
              />
            </mesh>
          ))}
          {entity.value.kind === "farm" &&
            Array.from({ length: 12 }, (_, i) => (
              <mesh
                key={i}
                position={[
                  (i % 4) * 0.45 - 0.7,
                  0.25,
                  -1.3 - Math.floor(i / 4) * 0.35,
                ]}
              >
                <boxGeometry args={[0.12, 0.45, 0.12]} />
                <meshStandardMaterial color="#d6b45e" />
              </mesh>
            ))}
          <Html
            portal={portal}
            zIndexRange={[10, 0]}
            center
            position={[0, 3.0, 0]}
          >
            <button
              className={`scene-label ${selected ? "selected" : ""}`}
              onClick={(event) => {
                event.stopPropagation();
                select(entity.value.id);
              }}
            >
              {entity.value.name}
              {entity.value.kind === "bakery" && (
                <span>
                  {(entity.value.prices.bread / 100).toFixed(2)} / loaf
                </span>
              )}
            </button>
          </Html>
        </>
      ) : (
        <>
          <mesh position={[0, 0.52, 0]} castShadow>
            <capsuleGeometry args={[0.17, 0.36, 4, 8]} />
            <meshStandardMaterial
              color={
                ["#819bca", "#c58364", "#d8b95d"][entity.value.name.length % 3]
              }
            />
          </mesh>
          <mesh position={[0, 0.96, 0]} castShadow>
            <sphereGeometry args={[0.18, 12, 12]} />
            <meshStandardMaterial color={color} />
          </mesh>
          <mesh position={[0, 1.1, 0]}>
            <coneGeometry args={[0.25, 0.16, 8]} />
            <meshStandardMaterial color="#6b5a3c" />
          </mesh>
          {selected && (
            <Html
              portal={portal}
              zIndexRange={[10, 0]}
              center
              position={[0, 1.6, 0]}
            >
              <span className="scene-label">{entity.value.name}</span>
            </Html>
          )}
        </>
      )}
      <mesh
        ref={ring}
        visible={false}
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, 0.04, 0]}
      >
        <ringGeometry
          args={[isBuilding ? 1.65 : 0.38, isBuilding ? 1.74 : 0.47, 32]}
        />
        <meshBasicMaterial
          color={cue?.type === "action_rejected" ? "#c58364" : "#81ba88"}
        />
      </mesh>
      {selected && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0]}>
          <ringGeometry
            args={[isBuilding ? 1.6 : 0.35, isBuilding ? 1.66 : 0.42, 40]}
          />
          <meshBasicMaterial color="#e9bd72" />
        </mesh>
      )}
    </group>
  );
}

function Entities({ portal }: { portal: LabelPortal }) {
  const world = useWorld((s) => s.update!.state);
  const [visuals, setVisuals] = useState<Record<string, Visual>>(() =>
    Object.fromEntries([
      ...Object.values(world.buildings).map((value) => [
        value.id,
        { entity: { kind: "building", value }, leaving: false, fresh: false },
      ]),
      ...Object.values(world.citizens).map((value) => [
        value.id,
        { entity: { kind: "citizen", value }, leaving: false, fresh: false },
      ]),
    ]),
  );
  useEffect(() => {
    const next: Entity[] = [
      ...Object.values(world.buildings).map((value) => ({
        kind: "building" as const,
        value,
      })),
      ...Object.values(world.citizens).map((value) => ({
        kind: "citizen" as const,
        value,
      })),
    ];
    setVisuals((previous) => {
      const result = Object.fromEntries(
        Object.entries(previous).map(([id, visual]) => [
          id,
          { ...visual, leaving: true },
        ]),
      );
      for (const entity of next)
        result[entity.value.id] = {
          entity,
          leaving: false,
          fresh: !previous[entity.value.id],
        };
      return result;
    });
  }, [world]);
  return Object.entries(visuals).map(([id, visual]) => (
    <EntityRenderer
      key={id}
      portal={portal}
      {...visual}
      done={() =>
        setVisuals((previous) => {
          if (!previous[id]?.leaving) return previous;
          const next = { ...previous };
          delete next[id];
          return next;
        })
      }
    />
  ));
}

function Tree({ x, z, scale = 1 }: { x: number; z: number; scale?: number }) {
  return (
    <group position={[x, 0, z]} scale={scale}>
      <mesh position={[0, 0.65, 0]} castShadow>
        <cylinderGeometry args={[0.12, 0.16, 1.3, 6]} />
        <meshStandardMaterial color="#665440" />
      </mesh>
      <mesh position={[0, 1.6, 0]} castShadow>
        <icosahedronGeometry args={[0.85, 0]} />
        <meshStandardMaterial color="#4e7659" />
      </mesh>
      <mesh position={[0.25, 2.1, 0]} castShadow>
        <icosahedronGeometry args={[0.6, 0]} />
        <meshStandardMaterial color="#6b9169" />
      </mesh>
    </group>
  );
}

function ResponsiveCamera() {
  const camera = useThree((state) => state.camera);
  const width = useThree((state) => state.size.width);
  const plots = useWorld((s) => s.update!.state.plots);
  const span = Math.max(
    23,
    ...Object.values(plots).map((p) => Math.abs(p.position.z) * 2 + 8),
  );
  useEffect(() => {
    camera.zoom = Math.min(44, width / span);
    camera.updateProjectionMatrix();
  }, [camera, width, span]);
  return null;
}

export function Village() {
  const epoch = useWorld((s) => s.epoch);
  const plots = useWorld((s) => s.update!.state.plots);
  const plotList = Object.values(plots);
  const extentX = Math.max(
    8.5,
    ...plotList.map((p) => Math.abs(p.position.x) + 3),
  );
  const extentZ = Math.max(
    7,
    ...plotList.map((p) => Math.abs(p.position.z) + 3),
  );
  const [labelElement, setLabelElement] = useState<HTMLDivElement | null>(null);
  const portal = useMemo(() => ({ current: labelElement! }), [labelElement]);
  return (
    <div className="village-canvas">
      <div className="scene-overlays" ref={setLabelElement} />
      {labelElement && (
        <Canvas
          shadows
          orthographic
          camera={{ position: [14, 14, 16], zoom: 44, near: 0.1, far: 100 }}
          onPointerMissed={(event) => {
            if ((event.target as HTMLElement).tagName === "CANVAS")
              usePresentation.getState().select(null);
          }}
        >
          <ResponsiveCamera />
          <color attach="background" args={["#b7c5b1"]} />
          <fog attach="fog" args={["#b7c5b1", 28, 65]} />
          <ambientLight intensity={1.1} />
          <directionalLight
            castShadow
            position={[-8, 15, 6]}
            intensity={2.2}
            shadow-mapSize={[2048, 2048]}
            shadow-camera-left={-14}
            shadow-camera-right={14}
            shadow-camera-top={14}
            shadow-camera-bottom={-14}
            shadow-bias={-0.001}
          />
          <Suspense fallback={null}>
            <RoundedBox
              args={[extentX * 2, 0.6, extentZ * 2]}
              position={[0, -0.35, 0]}
              radius={0.35}
              receiveShadow
            >
              <meshStandardMaterial color="#83966b" />
            </RoundedBox>
            <mesh
              rotation={[-Math.PI / 2, 0, 0]}
              position={[0, 0.08, 0]}
              receiveShadow
            >
              <planeGeometry args={[16, 1.5]} />
              <meshStandardMaterial color="#c5b390" />
            </mesh>
            {[-4, 0, 4].map((x) => (
              <mesh
                key={x}
                rotation={[-Math.PI / 2, 0, 0]}
                position={[x, 0.09, 0]}
                receiveShadow
              >
                <planeGeometry args={[1.1, 7]} />
                <meshStandardMaterial color="#c5b390" />
              </mesh>
            ))}
            {plotList.map((plot) => (
              <mesh
                key={plot.id}
                rotation={[-Math.PI / 2, 0, 0]}
                position={[plot.position.x, 0.07, plot.position.z]}
              >
                <planeGeometry args={[2.7, 2.4]} />
                <meshStandardMaterial color="#92a47b" />
              </mesh>
            ))}
            {[
              [-7, -5],
              [-6, 5],
              [7, -5],
              [7, 4],
              [-7, 2],
              [3, 6],
              [-2, -6],
            ].map(([x, z], i) => (
              <Tree key={i} x={x} z={z} scale={0.8 + (i % 3) * 0.15} />
            ))}
            <Entities key={epoch} portal={portal} />
            <ContactShadows
              position={[0, -0.02, 0]}
              opacity={0.2}
              scale={25}
              blur={2}
              far={5}
            />
          </Suspense>
          <OrbitControls
            makeDefault
            minZoom={12}
            maxZoom={85}
            minPolarAngle={0.4}
            maxPolarAngle={1.2}
            enablePan={false}
            target={[0, 0, 0]}
          />
        </Canvas>
      )}
    </div>
  );
}
