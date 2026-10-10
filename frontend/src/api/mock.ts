/**
 * Development-only presentation fixtures, not an alternative economic engine.
 *
 * Offline preview plays a scripted story, one step per click, that walks the
 * seed village from Hamlet to City through every visual the frontend has:
 * construction, upgrades, newcomers, leased homes, a bankruptcy, a rebuild,
 * price changes, and time passing. Each step returns a new snapshot plus the
 * events that explain it, exactly as the API would.
 */
import fixture from "../../../backend/contracts/generated/initial-world.json";
import type { SimulationEvent, WorldState, WorldUpdate } from "./types";

export function initialMock(): WorldUpdate {
  return structuredClone(fixture) as WorldUpdate;
}

type Emit = (type: string, payload: object, actor?: string) => void;
type Step = { title: string; apply: (state: WorldState, emit: Emit) => void };

const at = (state: WorldState, plotId: string) => ({
  ...state.plots[plotId].position,
});

function found(
  id: string,
  name: string,
  kind: "farm" | "bakery" | "market",
  plotId: string,
  ownerId: string,
): Step["apply"] {
  return (state, emit) => {
    const template = Object.values(state.buildings).find(
      (b) => b.kind === kind,
    )!;
    state.buildings[id] = {
      ...structuredClone(template),
      id,
      name,
      kind,
      level: 1,
      plot_id: plotId,
      position: at(state, plotId),
      owner_id: ownerId,
    };
    state.citizens[ownerId].money -= 5000;
    emit(
      "building_constructed",
      { entity_id: id, position: at(state, plotId), level: null },
      ownerId,
    );
  };
}

function upgrade(id: string): Step["apply"] {
  return (state, emit) => {
    const building = state.buildings[id];
    building.level = Math.min(3, building.level + 1);
    emit(
      "building_upgraded",
      { entity_id: id, level: building.level, position: null },
      building.owner_id,
    );
  };
}

function arrive(
  id: string,
  name: string,
  occupation: string,
  employer: string | null,
): Step["apply"] {
  return (state, emit) => {
    state.citizens[id] = {
      ...structuredClone(state.citizens["citizen-6"]),
      id,
      name,
      occupation,
      employer_id: employer,
      money: 1500,
      memories: [],
      relationships: [],
      position: { x: -8, z: 0 },
    };
    emit("citizen_spawned", {
      entity_id: id,
      position: { x: -8, z: 0 },
      level: null,
    });
  };
}

function lease(plotId: string, owner: string, tenant: string): Step["apply"] {
  return (state, emit) => {
    const plot = state.plots[plotId];
    Object.assign(plot, { owner_id: owner, tenant_id: tenant, rent: 700 });
    emit(
      "lot_leased",
      {
        plot_id: plotId,
        owner_id: owner,
        tenant_id: tenant,
        rent: 700,
        arrears: 0,
        missed_periods: 0,
        prepaid_periods: 0,
      },
      tenant,
    );
  };
}

function days(count: number): Step["apply"] {
  return (state, emit) => {
    state.tick += count;
    emit("resource_produced", {
      entity_id: "farm",
      resource: "wheat",
      quantity: 4 * count,
      stock_remaining: null,
    });
  };
}

function reprice(id: string, percent: number): Step["apply"] {
  return (state, emit) => {
    const building = state.buildings[id];
    const old = building.prices.bread;
    building.prices.bread = Math.round(old * (1 + percent / 100));
    emit("price_changed", {
      building_id: id,
      resource: "bread",
      old_price: old,
      new_price: building.prices.bread,
    });
  };
}

const both =
  (...steps: Step["apply"][]): Step["apply"] =>
  (state, emit) =>
    steps.forEach((step) => step(state, emit));

type Newcomer = [
  id: string,
  name: string,
  occupation: string,
  work: string | null,
];

/** Several people arriving together. */
const wave = (people: Newcomer[]): Step["apply"] =>
  both(...people.map((p) => arrive(...p)));

/**
 * The preview storyline. Growth tiers follow from the state (progress.ts), and
 * each tier brings a bigger wave of newcomers: 7 founders in the Hamlet, 10 by
 * the Village, 15 by the Town, 23 in the City.
 */
export const STORY: Step[] = [
  {
    title: "Mira opens a second bakery",
    apply: found(
      "mira-bakery",
      "Mira's Bakehouse",
      "bakery",
      "plot-3",
      "citizen-5",
    ),
  },
  { title: "Two weeks pass", apply: days(14) },
  { title: "Hearth & Grain expands", apply: upgrade("bakery") },
  {
    title: "A family of three arrives",
    apply: wave([
      ["visitor-sage", "Sage", "Farmhand", "farm"],
      ["visitor-wren", "Wren", "Baker", "mira-bakery"],
      ["visitor-pip", "Pip", "Weaver", null],
    ]),
  },
  {
    title: "Sage rents a home from Elena",
    apply: lease("plot-4", "citizen-0", "visitor-sage"),
  },
  { title: "A month passes", apply: days(30) },
  { title: "Goldenfield Farm adds a field", apply: upgrade("farm") },
  { title: "Market Square adds a tent", apply: upgrade("market") },
  {
    title: "Five newcomers follow the work",
    apply: wave([
      ["visitor-bram", "Bram", "Builder", null],
      ["visitor-hollis", "Hollis", "Miller", "bakery"],
      ["visitor-ivy", "Ivy", "Farmer", "farm"],
      ["visitor-corin", "Corin", "Merchant", "market"],
      ["visitor-tess", "Tess", "Baker", "mira-bakery"],
    ]),
  },
  { title: "Bread gets cheaper", apply: reprice("bakery", -20) },
  { title: "Another month passes", apply: days(30) },
  { title: "The farm reaches its full size", apply: upgrade("farm") },
  { title: "Hearth & Grain reaches its full size", apply: upgrade("bakery") },
  {
    title: "Mira's Bakehouse goes bankrupt",
    apply: (state, emit) => {
      const building = state.buildings["mira-bakery"];
      delete state.buildings["mira-bakery"];
      for (const c of Object.values(state.citizens))
        if (c.employer_id === building.id) c.employer_id = null;
      emit(
        "building_removed",
        { entity_id: building.id, position: building.position, level: null },
        building.owner_id,
      );
    },
  },
  { title: "Six weeks pass", apply: days(45) },
  {
    title: "Theo opens a market on the empty lot",
    apply: found(
      "theo-market",
      "Theo's Exchange",
      "market",
      "plot-3",
      "citizen-4",
    ),
  },
  {
    title: "Eight settlers arrive as Oakhaven becomes a city",
    apply: wave([
      ["visitor-maren", "Maren", "Merchant", "theo-market"],
      ["visitor-tobin", "Tobin", "Farmhand", "farm"],
      ["visitor-elowen", "Elowen", "Weaver", null],
      ["visitor-rook", "Rook", "Builder", null],
      ["visitor-linnea", "Linnea", "Baker", "bakery"],
      ["visitor-odo", "Odo", "Miller", "bakery"],
      ["visitor-fern", "Fern", "Merchant", "market"],
      ["visitor-calla", "Calla", "Farmer", "farm"],
    ]),
  },
  { title: "Theo's Exchange expands", apply: upgrade("theo-market") },
  { title: "Market Square reaches its full size", apply: upgrade("market") },
  { title: "Two months pass", apply: days(60) },
  {
    title: "Theo's Exchange reaches its full size",
    apply: upgrade("theo-market"),
  },
  { title: "A season passes", apply: days(70) },
];

/**
 * Apply story step `index` to `current`. Returns null when the story is over;
 * start again from `initialMock()`.
 */
export function mockEvent(
  current: WorldUpdate,
  index: number,
): WorldUpdate | null {
  const step = STORY[index];
  if (!step) return null;
  const update = structuredClone(current);
  const state = update.state;
  update.events = [];
  const emit: Emit = (type, payload, actor) => {
    state.sequence++;
    update.events.push({
      id: `offline:${state.sequence}`,
      branch_id: state.branch_id,
      tick: state.tick,
      sequence: state.sequence,
      actor_id: actor ?? null,
      rationale: step.title,
      causal_refs: [],
      action_id: null,
      type,
      payload,
    } as SimulationEvent);
  };
  step.apply(state, emit);
  update.tick = state.tick;
  update.sequence = state.sequence;
  return update;
}
