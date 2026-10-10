/**
 * How a simulated business looks over its life. The simulation changes a
 * building instantly; this stages those real changes over a few seconds:
 *
 * - built (`building_constructed`, a new ID): foundation → walls → frame
 *   under scaffolding, then the finished building rises; builders come to help.
 * - upgraded (`level` increases): scaffolding and dust while the new
 *   annexes and props for that level appear.
 * - removed (`building_removed`, bankruptcy or closure): it collapses into
 *   ruins, which then sink away.
 *
 * Historical seeks and branch switches remount with `fresh` false, so they
 * show the saved state without replaying construction.
 */
import { useEffect, useRef, useState } from "react";
import { useFrame } from "@react-three/fiber";
import { MathUtils, type Group } from "three";
import type { Building } from "../api/types";
import { CONSTRUCTION_STAGES, HEX_SCALE, hex } from "./assets";
import { BuildingModel, Dust, StaticModel } from "./Models";
import { openSite } from "./sites";
import { stepSpring, type Spring } from "./spring";

const BUILD_SECONDS = 7;
const UPGRADE_SECONDS = 2.8;
const RUIN_SECONDS = 2.6;

type Phase = "build" | "stand" | "upgrade" | "ruin";

export function BuildingLife({
  building,
  fresh,
  leaving,
  onGone,
}: {
  building: Building;
  fresh: boolean;
  leaving: boolean;
  onGone: () => void;
}) {
  const [phase, setPhase] = useState<Phase>(fresh ? "build" : "stand");
  const [stage, setStage] = useState(0);
  const [burst, setBurst] = useState(fresh ? 1 : 0);
  const [level, setLevel] = useState(building.level);
  const timer = useRef(0);
  const body = useRef<Group>(null);
  const ruins = useRef<Group>(null);
  const rise = useRef<Spring>({ value: fresh ? 0 : 1, velocity: 0 });

  // A level change in the snapshot starts an upgrade.
  if (building.level !== level && phase !== "ruin") {
    setLevel(building.level);
    if (building.level > level && phase === "stand") {
      setPhase("upgrade");
      setBurst((b) => b + 1);
      timer.current = 0;
    }
  }
  if (leaving && phase !== "ruin") {
    setPhase("ruin");
    setBurst((b) => b + 1);
    timer.current = 0;
  }

  // Builders (and the owner) come over while the scaffolding is up.
  useEffect(() => {
    if (phase !== "build" && phase !== "upgrade") return;
    const seconds = phase === "build" ? BUILD_SECONDS : UPGRADE_SECONDS;
    return openSite({
      buildingId: building.id,
      ownerId: building.owner_id,
      at: building.position,
      until: performance.now() + seconds * 1000,
    });
  }, [phase, building.id, building.owner_id, building.position]);

  useFrame((_, dt) => {
    timer.current += dt;
    const t = timer.current;
    if (phase === "build") {
      const next = Math.min(3, Math.floor((t / BUILD_SECONDS) * 4));
      if (next !== stage) {
        setStage(next);
        setBurst((b) => b + 1);
      }
      if (t >= BUILD_SECONDS) setPhase("stand");
    } else if (phase === "upgrade" && t >= UPGRADE_SECONDS) setPhase("stand");
    else if (phase === "ruin" && t >= RUIN_SECONDS) onGone();

    const standing = phase !== "ruin" && (phase !== "build" || stage === 3);
    stepSpring(rise.current, standing ? 1 : 0, dt);
    body.current?.scale.setScalar(Math.max(0.0001, rise.current.value));
    if (ruins.current) {
      // Settle, then sink into the ground.
      const sink = Math.max(0, t - RUIN_SECONDS * 0.55) / (RUIN_SECONDS * 0.45);
      ruins.current.position.y = -MathUtils.smoothstep(sink, 0, 1) * 1.6;
    }
  });

  const building_ = phase !== "ruin";
  const scaffolding = (phase === "build" && stage > 0) || phase === "upgrade";
  return (
    <group>
      {building_ && (
        <group ref={body} scale={Math.max(0.0001, rise.current.value)}>
          {/* Face the main street (z = 0) from either side of it. */}
          <BuildingModel
            kind={building.kind}
            level={level}
            flip={building.position.z > 0}
          />
        </group>
      )}
      {phase === "build" && stage < 3 && (
        <StaticModel
          url={hex(CONSTRUCTION_STAGES[stage])}
          scale={HEX_SCALE * 1.2}
        />
      )}
      {scaffolding && (
        <StaticModel
          url={hex("building_scaffolding")}
          scale={HEX_SCALE * (phase === "upgrade" ? 1.12 : 1)}
        />
      )}
      {phase === "ruin" && (
        <group ref={ruins}>
          <StaticModel
            url={hex("building_destroyed")}
            scale={HEX_SCALE * 1.15}
          />
        </group>
      )}
      {burst > 0 && <Dust key={burst} />}
    </group>
  );
}
