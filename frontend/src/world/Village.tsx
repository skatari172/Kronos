import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import { Group, MathUtils, Vector3 } from "three";
import { activityCue } from "../api/format";
import type { Building, Citizen } from "../api/types";
import { coins } from "../api/format";
import { usePresentation, useWorld } from "../stores/world";
import { characterModel, hash } from "./assets";
import { BuildingLife } from "./BuildingLife";
import { Ground } from "./Ground";
import { joinCrowd, keepApart } from "./crowd";
import { CharacterModel, type Motion } from "./Models";
import { preloadModels } from "./preload";
import { useTown } from "./progress";
import { startRoutine, startSpot, stepRoutine } from "./routine";
import { stepSpring, type Spring } from "./spring";
import { Selection, type LabelPortal } from "./Selection";
import type { Town } from "./town";

preloadModels();

type Entity =
  { kind: "building"; value: Building } | { kind: "citizen"; value: Citizen };
type Visual = { entity: Entity; leaving: boolean; fresh: boolean };

const CAMERA: [number, number, number] = [14, 14, 16];
const FACING_VIEWER = Math.atan2(CAMERA[0], CAMERA[2]);
const KIND_NAMES: Record<Building["kind"], string> = {
  farm: "Farm",
  bakery: "Bakery",
  market: "Market",
};

function BuildingLabel({
  building,
  portal,
}: {
  building: Building;
  portal: LabelPortal;
}) {
  const details = [
    KIND_NAMES[building.kind],
    `Level ${building.level}`,
    building.kind === "bakery" ? `${coins(building.prices.bread)} / loaf` : "",
  ].filter(Boolean);
  return (
    <Html portal={portal} zIndexRange={[10, 0]} center position={[0, 2.9, 0]}>
      <span className="scene-label selected">
        {building.name}
        <span>{details.join(" · ")}</span>
      </span>
    </Html>
  );
}

function EntityRenderer({
  entity,
  leaving,
  fresh,
  done,
  portal,
  town,
}: Visual & { done: () => void; portal: LabelPortal; town: Town }) {
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
  const body = useRef<Group>(null);
  const size = useRef<Spring>({ value: fresh ? 0 : 1, velocity: 0 });
  const motion = useRef<Motion>({ speed: 0, pose: "idle" });
  const selected = usePresentation((s) => s.selectedId === entity.value.id);
  const select = usePresentation((s) => s.select);
  const seed = hash(entity.value.id);
  const home = new Vector3(entity.value.position.x, 0, entity.value.position.z);
  // Villagers begin spread across the town rather than on the main street.
  const [start] = useState(() => {
    if (entity.kind !== "citizen") return home;
    const lane = ((seed % 5) - 2) * 0.13;
    const spot = startSpot(
      entity.value,
      useWorld.getState().update!.state,
      town,
      lane,
    );
    return new Vector3(spot.x, 0, spot.z);
  });
  const position = useRef(start.clone());
  const routine = useRef(startRoutine(town, start, seed));
  const townRef = useRef(town);
  useEffect(() => {
    townRef.current = town;
  }, [town]);
  useEffect(() => {
    if (entity.kind !== "citizen" || leaving) return;
    return joinCrowd(entity.value.id, position.current);
  }, [entity.kind, entity.value.id, leaving]);

  useFrame((_, dt) => {
    if (!group.current) return;
    const p = position.current;
    if (entity.kind === "building") {
      group.current.position.copy(home);
      return;
    }
    if (!leaving) {
      const { speed, heading } = stepRoutine(
        routine.current,
        p,
        Math.min(dt, 0.1),
        entity.value,
        useWorld.getState().update!.state,
        townRef.current,
      );
      // Step around anyone already standing here.
      keepApart(entity.value.id, p, seed);
      motion.current.speed = speed;
      motion.current.pose = routine.current.pose;
      // Face the road while walking; turn more gently into a break.
      if (body.current) {
        const turn =
          MathUtils.euclideanModulo(
            heading - body.current.rotation.y + Math.PI,
            Math.PI * 2,
          ) - Math.PI;
        body.current.rotation.y +=
          turn * (1 - Math.exp((speed ? -12 : -4) * dt));
      }
    }
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
    // New villagers pop in; departing ones shrink away.
    if (leaving)
      size.current.value = MathUtils.damp(size.current.value, 0, 7, dt);
    else stepSpring(size.current, 1, dt);
    group.current.scale.setScalar(Math.max(0.0001, size.current.value));
    if (leaving && size.current.value < 0.02) done();
  });

  return (
    <group
      ref={group}
      position={[start.x, 0, start.z]}
      scale={
        entity.kind === "building" ? 1 : Math.max(0.0001, size.current.value)
      }
      onClick={(e) => {
        e.stopPropagation();
        if (!leaving) select(entity.value.id);
      }}
    >
      {entity.kind === "building" ? (
        <>
          <Suspense fallback={null}>
            <BuildingLife
              building={entity.value}
              fresh={fresh}
              leaving={leaving}
              onGone={done}
            />
          </Suspense>
          {selected && (
            <BuildingLabel building={entity.value} portal={portal} />
          )}
          {selected && <Selection radius={1.7} />}
        </>
      ) : (
        <>
          <group ref={body} rotation={[0, FACING_VIEWER, 0]}>
            <Suspense fallback={null}>
              <CharacterModel
                url={characterModel(entity.value)}
                motion={motion}
                phase={(seed % 97) / 97}
              />
            </Suspense>
          </group>
          {selected && (
            <Html
              portal={portal}
              zIndexRange={[10, 0]}
              center
              position={[0, 1.25, 0]}
            >
              <span className="scene-label selected">
                {entity.value.name}
                <span>{entity.value.occupation}</span>
              </span>
            </Html>
          )}
          {selected && <Selection radius={0.32} />}
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

function Entities({ portal, town }: { portal: LabelPortal; town: Town }) {
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
      town={town}
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
  const height = useThree((state) => state.size.height);
  useEffect(() => {
    camera.zoom = MathUtils.clamp(Math.min(width / 37, height / 21), 10, 90);
    camera.updateProjectionMatrix();
  }, [camera, width, height]);
  return null;
}

/** `autoRotate` slowly circles the town (time-lapse mode). */
export function Village({ autoRotate = false }: { autoRotate?: boolean }) {
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
  const town = useTown();
  const [labelElement, setLabelElement] = useState<HTMLDivElement | null>(null);
  const portal = useMemo(() => ({ current: labelElement! }), [labelElement]);
  return (
    <div className="village-canvas">
      <div className="scene-overlays" ref={setLabelElement} />
      {labelElement && (
        <Canvas
          shadows
          flat
          orthographic
          camera={{ position: CAMERA, zoom: 40, near: 0.1, far: 100 }}
          onPointerMissed={(event) => {
            if ((event.target as HTMLElement).tagName === "CANVAS")
              usePresentation.getState().select(null);
          }}
        >
          <ResponsiveCamera />
          <hemisphereLight args={["#ffffff", "#c9cbbd", 1.05]} />
          <directionalLight
            castShadow
            color="#fff1dc"
            position={[-12, 20, 9]}
            intensity={1.55}
            shadow-mapSize={[4096, 4096]}
            shadow-camera-left={-24}
            shadow-camera-right={24}
            shadow-camera-top={24}
            shadow-camera-bottom={-24}
            shadow-bias={-0.0005}
            shadow-normalBias={0.02}
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
            <Ground key={`ground:${epoch}`} portal={portal} town={town} />
            <Entities key={epoch} portal={portal} town={town} />
          </Suspense>
          <OrbitControls
            makeDefault
            autoRotate={autoRotate}
            autoRotateSpeed={0.6}
            minZoom={8}
            maxZoom={260}
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
