/**
 * With a villager selected, arcs run from them to the people they feel most
 * strongly about: green for trust, red for a grudge, brighter when stronger.
 * Read from the snapshot's relationships; the arcs follow everyone as they walk.
 */
import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import type { Line2 } from "three/examples/jsm/lines/Line2.js";
import { usePresentation, useWorld } from "../stores/world";
import { crowdAt } from "./crowd";

const MAX_TIES = 6;
const SEGMENTS = 16;
const FLAT = new Array((SEGMENTS + 1) * 3).fill(0);

export function TieLines() {
  const selected = usePresentation((s) => s.selectedId);
  const citizen = useWorld((s) =>
    selected ? s.update?.state.citizens[selected] : undefined,
  );
  if (!citizen) return null;
  const ties = [...citizen.relationships]
    .filter((r) => r.trust !== 0 || r.grudge > 0)
    .sort(
      (a, b) => Math.abs(b.trust) + b.grudge - (Math.abs(a.trust) + a.grudge),
    )
    .slice(0, MAX_TIES);
  return ties.map((tie) => {
    const hostile = tie.grudge > Math.max(tie.trust, 0);
    const strength = Math.min(
      1,
      (hostile ? tie.grudge : Math.abs(tie.trust)) / 40,
    );
    return (
      <Arc
        key={tie.citizen_id}
        from={citizen.id}
        to={tie.citizen_id}
        color={hostile ? "#ff5a3c" : tie.trust >= 0 ? "#5fd16a" : "#f0b23c"}
        opacity={0.7 + strength * 0.3}
        width={3 + strength * 4}
      />
    );
  });
}

function Arc({
  from,
  to,
  color,
  opacity,
  width,
}: {
  from: string;
  to: string;
  color: string;
  opacity: number;
  width: number;
}) {
  const line = useRef<Line2>(null);
  const points = useRef(new Float32Array((SEGMENTS + 1) * 3));
  useFrame(() => {
    const a = crowdAt(from);
    const b = crowdAt(to);
    if (!line.current) return;
    line.current.visible = !!a && !!b;
    if (!a || !b) return;
    // A raised arc between their heads, higher the farther apart they stand.
    const lift = 0.5 + Math.hypot(a.x - b.x, a.z - b.z) * 0.18;
    const p = points.current;
    for (let i = 0; i <= SEGMENTS; i++) {
      const t = i / SEGMENTS;
      p[i * 3] = a.x + (b.x - a.x) * t;
      p[i * 3 + 1] = 0.75 + Math.sin(Math.PI * t) * lift;
      p[i * 3 + 2] = a.z + (b.z - a.z) * t;
    }
    line.current.geometry.setPositions(p);
  });
  return (
    <Line
      ref={line}
      points={FLAT}
      color={color}
      lineWidth={width}
      transparent
      opacity={opacity}
      dashed={false}
    />
  );
}
