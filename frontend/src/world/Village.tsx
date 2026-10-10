import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import { Group, MathUtils, Vector3 } from "three";
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
import { startRoutine, stepRoutine } from "./routine";
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
  const body = useRef<Group>(null);
  const size = useRef<Spring>({ value: fresh ? 0 : 1, velocity: 0 });
  const motion = useRef<Motion>({ speed: 0, pose: "idle" });
  const selected = usePresentation((s) => s.selectedId === entity.value.id);
  const select = usePresentation((s) => s.select);
  const seed = hash(entity.value.id);
  const home = new Vector3(entity.value.position.x, 0, entity.value.position.z);
  const position = useRef(home.clone());
  const routine = useRef(startRoutine(town, home, seed));
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
      position={[home.x, 0, home.z]}
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
