import { Suspense, useRef, useState, type ReactNode } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import type { Group } from "three";
import type { Plot, WorldState } from "../api/types";
import { coins } from "../api/format";
import { usePresentation, useWorld } from "../stores/world";
import { HEX_SCALE, hex } from "./assets";
import { Dust, StaticModel } from "./Models";
import { residentsOf } from "./routine";
import { Selection, type LabelPortal } from "./Selection";
import { stepSpring, type Spring } from "./spring";
import type { Piece, Town } from "./town";

/**
 * Renders the town for the current growth tier (./town, ./progress) and the
 * simulation's lots. Pieces that appear after the first frame (a new district,
 * a new home) rise from the ground in a wave from the town centre.
 */
export function Ground({ portal, town }: { portal: LabelPortal; town: Town }) {
  const mountedAt = useRef(performance.now());
  // Anything mounting later than this belongs to a growth step and animates.
  const grows = () => performance.now() - mountedAt.current > 600;
  return (
    <group>
      {town.tiles.map((piece) => (
        <Grow
          key={`tile:${piece.x}:${piece.z}`}
          piece={piece}
          animate={grows()}
        >
          <StaticModel
            url={hex(piece.model)}
            rotation={[0, piece.rotation, 0]}
          />
        </Grow>
      ))}
      {town.scenery.map((piece) => (
        <Grow
          key={`${piece.model}:${piece.x}:${piece.z}`}
          piece={piece}
          animate={grows()}
        >
          {piece.place ? (
            <TownBuilding piece={piece} portal={portal} town={town} />
          ) : (
            <StaticModel
              url={hex(piece.model)}
              rotation={[0, piece.rotation, 0]}
            />
          )}
        </Grow>
      ))}
      <Lots portal={portal} animate={grows} />
    </group>
  );
}

/** Rises out of the ground with a short delay by distance from the centre. */
function Grow({
  piece,
  animate,
  children,
}: {
  piece: Pick<Piece, "x" | "z">;
  animate: boolean;
  children: ReactNode;
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
    group.current.position.y = (lift.current.value - 1) * 1.4;
    group.current.scale.setScalar(
      Math.max(0.0001, 0.4 + lift.current.value * 0.6),
    );
  });
  return (
    <group position={[piece.x, 0, piece.z]}>
      <group
        ref={group}
        position={[0, initial ? -1.4 : 0, 0]}
        scale={initial ? 0.4 : 1}
      >
        {/* A model still loading hides only this piece, never the town. */}
        <Suspense fallback={null}>{children}</Suspense>
      </group>
      {dust && <Dust radius={1} />}
    </group>
  );
}

/** A selectable house or landmark. Scenery: it has no simulated state. */
function TownBuilding({
  piece,
  portal,
  town,
}: {
  piece: Piece;
  portal: LabelPortal;
  town: Town;
}) {
  const place = piece.place!;
  const selected = usePresentation((s) => s.selectedId === place.id);
  const select = usePresentation((s) => s.select);
  const residents = useWorld((s) =>
    place.kind === "home"
      ? residentsOf(place, s.update!.state, town).join(" & ")
      : "",
  );
  const title =
    place.kind === "home" && residents ? `${residents}'s home` : place.name;
  const detail =
    place.kind === "home" ? (residents ? "Home" : "Empty cottage") : "Landmark";
  return (
    <group
      onClick={(e) => {
        e.stopPropagation();
        select(place.id);
      }}
    >
      <StaticModel url={hex(piece.model)} rotation={[0, piece.rotation, 0]} />
      {selected && (
        <>
          <Selection radius={1.25} />
          <Label portal={portal} title={title} detail={detail} height={2.4} />
        </>
      )}
    </group>
  );
}

function Label({
  portal,
  title,
  detail,
  height,
}: {
  portal: LabelPortal;
  title: string;
  detail: string;
  height: number;
}) {
  return (
    <Html
      portal={portal}
      zIndexRange={[10, 0]}
      center
      position={[0, height, 0]}
    >
      <span className="scene-label selected">
        {title}
        <span>{detail}</span>
      </span>
    </Html>
  );
}

type LotUse = "home" | "for-lease" | "town-land";

/** What stands on a lot without a business, straight from the snapshot. */
function lotUse(plot: Plot): LotUse {
  if (plot.tenant_id) return "home";
  return plot.owner_id ? "for-lease" : "town-land";
}

function lotLabel(plot: Plot, use: LotUse, state: WorldState) {
  const name = (id?: string | null) => (id && state.citizens[id]?.name) || "—";
  if (use === "home")
    return {
      title: `${name(plot.tenant_id)}'s home`,
      detail: `Leased lot · ${coins(plot.rent)} rent / week`,
    };
  if (use === "for-lease")
    return {
      title: "Lot for lease",
      detail: `Owned by ${name(plot.owner_id)} · ${coins(plot.rent)} / week`,
    };
  return { title: "Town land", detail: "Open for anyone to build on" };
}

/** Lots without a business: a tenant's home, a for-lease lot, or open land. */
function Lots({
  portal,
  animate,
}: {
  portal: LabelPortal;
  animate: () => boolean;
}) {
  const state = useWorld((s) => s.update!.state);
  const selectedId = usePresentation((s) => s.selectedId);
  const select = usePresentation((s) => s.select);
  const built = new Set(Object.values(state.buildings).map((b) => b.plot_id));
  return Object.values(state.plots)
    .filter((plot) => !built.has(plot.id))
    .map((plot) => {
      const use = lotUse(plot);
      const id = `lot:${plot.id}`;
      const label = lotLabel(plot, use, state);
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
              <>
                <Selection radius={use === "home" ? 1.25 : 1.05} />
                <Label
                  portal={portal}
                  title={label.title}
                  detail={label.detail}
                  height={use === "home" ? 2.4 : 1}
                />
              </>
            )}
          </group>
        </Grow>
      );
    });
}
