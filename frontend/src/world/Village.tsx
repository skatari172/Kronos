import { Suspense, useEffect, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { Group, MathUtils, Vector3 } from "three";
import type { Building, Citizen } from "../api/types";
import { useChronicleView } from "../app/feed";
import { usePlayback, usePresentation, useWorld } from "../stores/world";
import { characterModel, hash, physique } from "./assets";
import { BuildingLife } from "./BuildingLife";
import { Ground } from "./Ground";
import { crowdPositions, joinCrowd, keepApart } from "./crowd";
import { DecreeEffect } from "./DecreeEffect";
import { decreeBusy, decreeReaction, useDecrees } from "./decrees";
import { directFights, useFights } from "./fights";
import { directMeetings, meetingBusy } from "./meetings";
import { OverlayLayer, OverlayProjector } from "./Overlays";
import { TieLines } from "./TieLines";
import { CharacterModel, type Motion } from "./Models";
import { preloadModels } from "./preload";
import { useTown } from "./progress";
import { startRoutine, startSpot, stepRoutine } from "./routine";
import { stepSpring, type Spring } from "./spring";
import { Selection } from "./Selection";
import type { Town } from "./town";

preloadModels();

type Entity =
  { kind: "building"; value: Building } | { kind: "citizen"; value: Citizen };
type Visual = { entity: Entity; leaving: boolean; fresh: boolean };

const CAMERA: [number, number, number] = [14, 14, 16];
/** Matches --sidebar in styles.css. */
const SIDEBAR_WIDTH = 360;
const FACING_VIEWER = Math.atan2(CAMERA[0], CAMERA[2]);

function EntityRenderer({
  entity,
  leaving,
  fresh,
  done,
  town,
}: Visual & { done: () => void; town: Town }) {
  const group = useRef<Group>(null);
  const body = useRef<Group>(null);
  // Newcomers rise out of the ground (spawn pose) instead of popping in.
  const size = useRef<Spring>({
    value: fresh && entity.kind !== "citizen" ? 0 : 1,
    velocity: 0,
  });
  const body_ = physique(entity.value.id);
  const motion = useRef<Motion>({
    speed: 0,
    pose: "idle",
    gait: body_.walk,
    run: body_.run,
  });
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
  const routine = useRef(
    entity.kind === "citizen"
      ? startRoutine(town, start, entity.value, fresh)
      : null,
  );
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
    const face = (heading: number, rate: number) => {
      if (!body.current) return;
      const turn =
        MathUtils.euclideanModulo(
          heading - body.current.rotation.y + Math.PI,
          Math.PI * 2,
        ) - Math.PI;
      body.current.rotation.y += turn * (1 - Math.exp(-rate * dt));
    };
    // A decree is falling or has just landed: stop and react to it.
    const reaction = leaving ? null : decreeReaction(seed);
    if (!leaving && !reaction && usePlayback.getState().paused) {
      // Paused: everyone holds still where they are.
      motion.current.speed = 0;
      motion.current.pose = "idle";
    } else if (reaction) {
      motion.current.speed = 0;
      motion.current.pose = reaction;
      // Turn to where the decree strikes.
      const { centre } = useDecrees.getState();
      face(Math.atan2(centre.x - p.x, centre.z - p.z), 8);
    } else if (!leaving && routine.current) {
      const { speed, heading, gait } = stepRoutine(
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
      motion.current.gait = gait;
      // Face the road while walking; turn more gently into a break.
      face(heading, speed ? 12 : 4);
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
          {selected && <Selection radius={1.7} />}
        </>
      ) : (
        <>
          <group ref={body} rotation={[0, FACING_VIEWER, 0]}>
            <group scale={body_.height}>
              <Suspense fallback={null}>
                <CharacterModel
                  url={characterModel(entity.value)}
                  motion={motion}
                  phase={(seed % 97) / 97}
                />
              </Suspense>
            </group>
          </group>
          {selected && <Selection radius={0.32} />}
        </>
      )}
    </group>
  );
}

function Entities({ town }: { town: Town }) {
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

/**
 * Stages fights (fights.ts) and conversations (meetings.ts); checks about once
 * a second. Nobody is pulled into a fight mid-conversation, or the other way.
 */
function Director({ town }: { town: Town }) {
  const clock = useRef(0);
  useFrame((_, dt) => {
    if ((clock.current += dt) < 1) return;
    clock.current = 0;
    if (usePlayback.getState().paused) return; // nothing new starts while paused
    const crowd = crowdPositions();
    const talking = meetingBusy();
    directFights(
      crowd.filter((c) => !talking.has(c.id)),
      town,
      decreeBusy(),
    );
    const fight = useFights.getState().current;
    const fighting = new Set(
      fight && fight.endAt > performance.now() ? [fight.a, fight.b] : [],
    );
    const day = (useWorld.getState().update?.state.tick ?? 0) + 1;
    directMeetings(crowd, town, fighting, day);
  });
  return null;
}

/**
 * Fit the whole landmass into the space left of the chronicle sidebar and
 * centre it there. Refits only when the land's extent or the screen changes,
 * so a player's own zoom holds otherwise.
 */
function ResponsiveCamera({ town }: { town: Town }) {
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls) as unknown as {
    target: Vector3;
    update: () => void;
  } | null;
  const width = useThree((state) => state.size.width);
  const height = useThree((state) => state.size.height);
  const sidebar = useChronicleView((s) => s.sidebar);
  // The land's outline, as a stable key: refit only when it changes.
  const extent = town.tiles
    .map((t) => `${t.x.toFixed(1)}:${t.z.toFixed(1)}`)
    .sort()
    .join(";");
  useEffect(() => {
    const cells = extent
      .split(";")
      .map((c) => c.split(":").map(Number) as [number, number]);
    const xs = cells.map(([x]) => x);
    const zs = cells.map(([, z]) => z);
    const centre = new Vector3(
      (Math.min(...xs) + Math.max(...xs)) / 2,
      0,
      (Math.min(...zs) + Math.max(...zs)) / 2,
    );
    camera.position.set(centre.x + CAMERA[0], CAMERA[1], centre.z + CAMERA[2]);
    camera.lookAt(centre);
    if (controls) {
      controls.target.copy(centre);
      controls.update();
    }
    // Measure every tile's footprint on screen at zoom 1, then scale to fit.
    camera.clearViewOffset();
    camera.zoom = 1;
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld();
    const r = 1.4; // a tile's radius
    let [left, right, bottom, top] = [Infinity, -Infinity, Infinity, -Infinity];
    const p = new Vector3();
    for (const [x, z] of cells)
      for (const [dx, dz] of [
        [r, 0],
        [-r, 0],
        [0, r],
        [0, -r],
      ])
        for (const y of [-0.8, 0.5]) {
          p.set(x + dx, y, z + dz).project(camera);
          [left, right] = [Math.min(left, p.x), Math.max(right, p.x)];
          [bottom, top] = [Math.min(bottom, p.y), Math.max(top, p.y)];
        }
    const side = sidebar && width > 900 ? SIDEBAR_WIDTH : 0;
    // Room for the header, decree box and HUD above and below.
    const room = { w: width - side - 110, h: height - 300 };
    const span = {
      w: ((right - left) / 2) * width,
      h: ((top - bottom) / 2) * height,
    };
    camera.zoom = MathUtils.clamp(
      Math.min(room.w / span.w, room.h / span.h),
      10,
      90,
    );
    // Shift the view so the land's centre sits in the middle of the free space.
    // Centre the land's on-screen footprint in the free space: left of the
    // sidebar, and between the decree box (top) and the HUD (bottom).
    const cx = ((left + right) / 4) * width * camera.zoom;
    const cy = ((top + bottom) / 4) * height * camera.zoom;
    camera.setViewOffset(width, height, side / 2 + cx, -28 - cy, width, height);
    camera.updateProjectionMatrix();
  }, [camera, controls, width, height, sidebar, extent]);
  return null;
}

/** `autoRotate` slowly circles the town (time-lapse mode). */
export function Village({ autoRotate = false }: { autoRotate?: boolean }) {
  const epoch = useWorld((s) => s.epoch);
  const town = useTown();
  return (
    <div className="village-canvas">
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
        <ResponsiveCamera town={town} />
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
          <Ground key={`ground:${epoch}`} town={town} />
          <Entities key={epoch} town={town} />
          <DecreeEffect />
          <Director town={town} />
          <OverlayProjector />
          <TieLines />
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
        />
      </Canvas>
      <OverlayLayer />
    </div>
  );
}
