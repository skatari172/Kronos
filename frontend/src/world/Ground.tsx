import { Suspense, useMemo, useRef, useState, type ReactNode } from "react";
import { useFrame } from "@react-three/fiber";
import type { Group } from "three";
import type { Plot } from "../api/types";
import { usePresentation, useWorld } from "../stores/world";
import { HEX_SCALE, hex } from "./assets";
import { Dust, StaticModel } from "./Models";
import { Selection } from "./Selection";
import { stepSpring, type Spring } from "./spring";
import { tileKey, type Piece, type Town } from "./town";

/**
 * Renders the town for the current growth tier (./town, ./progress) and the
 * simulation's lots. Pieces that appear after the first frame (a new district,
 * a new home) rise from the ground in a wave from the town centre.
 */
export function Ground({ town }: { town: Town }) {
  const mountedAt = useRef(performance.now());
  // Anything mounting later than this belongs to a growth step and animates.
  const grows = () => performance.now() - mountedAt.current > 600;
  // The land only grows within a session (Ground remounts on a new epoch): a
  // tile once shown stays, so recomputing the land never removes and re-adds
  // one (which would replay its rise and flicker under the ground).
  const [shown] = useState(() => new Map<string, Piece>());
  const tiles = useMemo(() => {
    for (const piece of town.tiles) shown.set(tileKey(piece), piece);
    return [...shown.values()];
  }, [town, shown]);
  return (
    <group>
      {tiles.map((piece) => (
        <Grow
          // By grid cell, so a tile that was already there never replays its rise.
          key={`tile:${tileKey(piece)}`}
          piece={piece}
          animate={grows()}
          // Ground grows in place, never from deep below its neighbours.
          depth={0.25}
          from={0.85}
        >
          <StaticModel
            url={hex(piece.model)}
            rotation={[0, piece.rotation, 0]}
          />
        </Grow>
      ))}
      {town.scenery.map((piece) => (
        <Grow
          key={`${piece.model}:${tileKey(piece)}`}
          piece={piece}
          animate={grows()}
        >
          {piece.place ? (
            <TownBuilding piece={piece} />
          ) : (
            <StaticModel
              url={hex(piece.model)}
              rotation={[0, piece.rotation, 0]}
            />
          )}
        </Grow>
      ))}
      <Lots animate={grows} />
    </group>
  );
}

/** Rises out of the ground with a short delay by distance from the centre. */
function Grow({
  piece,
  animate,
  children,
  depth = 1.4,
  from = 0.4,
}: {
  piece: Pick<Piece, "x" | "z">;
  animate: boolean;
  children: ReactNode;
  /** How far below the ground it starts, and the scale it starts at. */
  depth?: number;
  from?: number;
}) {
  const group = useRef<Group>(null);
  const [initial] = useState(animate);
  const lift = useRef<Spring>({ value: animate ? 0 : 1, velocity: 0 });
  const delay = useRef(
    animate ? Math.hypot(piece.x, piece.z) * 0.06 + Math.random() * 0.15 : 0,
  );
  const [dust, setDust] = useState(false);
  useFrame((_, dt) => {
    if (!group.current || lift.current.value === 1) return;
    if ((delay.current -= dt) > 0) return;
    if (initial && !dust) setDust(true);
    stepSpring(lift.current, 1, dt);
    const v = lift.current.value;
    if (Math.abs(1 - v) < 0.001 && Math.abs(lift.current.velocity) < 0.01)
      lift.current.value = 1;
    group.current.position.y = (lift.current.value - 1) * depth;
    group.current.scale.setScalar(
      Math.max(0.0001, from + lift.current.value * (1 - from)),
    );
  });
  return (
    <group position={[piece.x, 0, piece.z]}>
      <group
        ref={group}
        position={[0, initial ? -depth : 0, 0]}
        scale={initial ? from : 1}
      >
        {/* A model still loading hides only this piece, never the town. */}
        <Suspense fallback={null}>{children}</Suspense>
      </group>
      {dust && <Dust radius={1} />}
    </group>
  );
}

/** A selectable house or landmark. Scenery: it has no simulated state. */
function TownBuilding({ piece }: { piece: Piece }) {
  const place = piece.place!;
  const selected = usePresentation((s) => s.selectedId === place.id);
  const select = usePresentation((s) => s.select);
  return (
    <group
      onClick={(e) => {
        e.stopPropagation();
        select(place.id);
      }}
    >
      <StaticModel url={hex(piece.model)} rotation={[0, piece.rotation, 0]} />
      {selected && <Selection radius={1.25} />}
    </group>
  );
}

type LotUse = "home" | "for-lease" | "town-land";

/** What stands on a lot without a business, straight from the snapshot. */
function lotUse(plot: Plot): LotUse {
  if (plot.tenant_id) return "home";
  return plot.owner_id ? "for-lease" : "town-land";
}

/** Lots without a business: a tenant's home, a for-lease lot, or open land. */
function Lots({ animate }: { animate: () => boolean }) {
  const state = useWorld((s) => s.update!.state);
  const selectedId = usePresentation((s) => s.selectedId);
  const select = usePresentation((s) => s.select);
  const built = new Set(Object.values(state.buildings).map((b) => b.plot_id));
  return Object.values(state.plots)
    .filter((plot) => !built.has(plot.id))
    .map((plot) => {
      const use = lotUse(plot);
      const id = `lot:${plot.id}`;
      return (
        <Grow
          // A new tenant (or a new owner) rebuilds what stands on the lot.
          key={`${plot.id}:${use}`}
          piece={plot.position}
          animate={animate()}
        >
          <group
            onClick={(e) => {
              e.stopPropagation();
              select(id);
            }}
          >
            {use === "home" ? (
              <StaticModel
                url={hex("building_home_B_red")}
                // Face the main street.
                rotation={[0, plot.position.z > 0 ? Math.PI : 0, 0]}
              />
            ) : (
              <StaticModel
                url={hex("building_dirt")}
                scale={HEX_SCALE * 0.72}
              />
            )}
            {use === "for-lease" && (
              <StaticModel
                url={hex("flag_red")}
                scale={HEX_SCALE * 1.8}
                position={[0.55, 0, 0.45]}
              />
            )}
            {selectedId === id && (
              <Selection radius={use === "home" ? 1.25 : 1.05} />
            )}
          </group>
        </Grow>
      );
    });
}
