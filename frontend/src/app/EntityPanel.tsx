import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";
import type {
  Building,
  Citizen,
  Plot,
  SimulationEvent,
  WorldState,
} from "../api/types";
import { coins } from "../api/format";
import { usePresentation, useWorld } from "../stores/world";
import { useTown } from "../world/progress";
import { residentsOf } from "../world/routine";
import type { Place, Town } from "../world/town";
import { PLACE_NOTES } from "./profiles";
import { VillagerPanel } from "./VillagerPanel";

const KIND_NAMES: Record<Building["kind"], string> = {
  farm: "Farm",
  bakery: "Bakery",
  market: "Market",
};

/**
 * Details for whatever is selected in the village, docked on the right.
 * Businesses, lots and places get a few large numbers from the snapshot;
 * villagers get the full summary in VillagerPanel.tsx.
 */
export function EntityPanel({ live }: { live: boolean }) {
  const selectedId = usePresentation((s) => s.selectedId);
  const select = usePresentation((s) => s.select);
  const state = useWorld((s) => s.update?.state);
  const events = useWorld((s) => s.events);
  const town = useTown();

  useEffect(() => {
    const close = (e: KeyboardEvent) => e.key === "Escape" && select(null);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [select]);

  if (!selectedId || !state) return null;
  const body = resolve(selectedId, state, town, events, live);
  if (!body) return null;
  return (
    <aside
      className={`entity-panel ${state.citizens[selectedId] ? "villager" : ""}`}
      aria-label={`${body.title} details`}
    >
      <header>
        <div>
          <h2>{body.title}</h2>
          <span className="chip">{body.tag}</span>
        </div>
        <button
          className="panel-close"
          aria-label="Close details"
          onClick={() => select(null)}
        >
          <X size={18} />
        </button>
      </header>
      {body.content}
    </aside>
  );
}

type Body = { title: string; tag: string; content: ReactNode };

function resolve(
  id: string,
  state: WorldState,
  town: Town,
  events: SimulationEvent[],
  live: boolean,
): Body | null {
  if (state.citizens[id])
    return citizenBody(state.citizens[id], state, events, live);
  if (state.buildings[id]) return buildingBody(state.buildings[id], state);
  if (id.startsWith("lot:")) {
    const plot = state.plots[id.slice(4)];
    return plot ? lotBody(plot, state) : null;
  }
  const place = town.places.find((p) => p.id === id);
  return place ? placeBody(place, state, town) : null;
}

const name = (state: WorldState, id?: string | null) =>
  (id && (state.citizens[id]?.name ?? state.buildings[id]?.name)) || "—";

function citizenBody(
  citizen: Citizen,
  state: WorldState,
  events: SimulationEvent[],
  live: boolean,
): Body {
  return {
    title: citizen.name,
    tag: citizen.occupation,
    content: (
      <VillagerPanel
        key={citizen.id}
        citizen={citizen}
        state={state}
        events={events}
        live={live}
      />
    ),
  };
}

function buildingBody(building: Building, state: WorldState): Body {
  const staff = Object.values(state.citizens).filter(
    (c) => c.employer_id === building.id,
  ).length;
  return {
    title: building.name,
    tag: `${KIND_NAMES[building.kind]} · Level ${building.level}`,
    content: (
      <dl className="stats">
        <Stat label="Owner" value={name(state, building.owner_id)} />
        <Stat label="Cash" value={coins(building.cash)} />
        {building.kind === "farm" ? (
          <Stat label="Wheat" value={`${building.inventory.wheat}`} />
        ) : (
          <Stat label="Bread" value={coins(building.prices.bread)} />
        )}
        <Stat label="Staff" value={`${staff} / ${building.job_slots}`} />
      </dl>
    ),
  };
}

function placeBody(place: Place, state: WorldState, town: Town): Body {
  const residents =
    place.kind === "home" ? residentsOf(place, state, town) : [];
  return {
    title:
      place.kind === "home" && residents.length
        ? `${residents.join(" & ")}'s home`
        : place.name,
    tag: place.kind === "home" ? "Home" : "Landmark",
    content: <p className="panel-line">{PLACE_NOTES[place.name] ?? ""}</p>,
  };
}

function lotBody(plot: Plot, state: WorldState): Body {
  const use = plot.tenant_id ? "home" : plot.owner_id ? "lease" : "open";
  return {
    title:
      use === "home"
        ? `${name(state, plot.tenant_id)}'s home`
        : use === "lease"
          ? "Lot for lease"
          : "Town land",
    tag: "Lot",
    content:
      use === "open" ? (
        <p className="panel-line">Anyone can build a business here.</p>
      ) : (
        <dl className="stats">
          <Stat label="Owner" value={name(state, plot.owner_id)} />
          <Stat label="Rent / week" value={coins(plot.rent)} />
        </dl>
      ),
  };
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
