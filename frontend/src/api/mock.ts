/** Development-only presentation fixtures, not an alternative economic engine. */
import fixture from "../../../backend/contracts/generated/initial-world.json";
import type { WorldUpdate, SimulationEvent } from "./types";

export function initialMock(): WorldUpdate {
  return structuredClone(fixture) as WorldUpdate;
}

export function mockEvent(current: WorldUpdate, index: number): WorldUpdate {
  const update = structuredClone(current);
  const state = update.state;
  update.events = [];
  const base = {
    id: `offline:${state.sequence + 1}`,
    branch_id: state.branch_id,
    tick: state.tick,
    sequence: state.sequence + 1,
    actor_id: null,
    rationale: null,
    causal_refs: [],
  };
  let event: SimulationEvent;
  switch (index % 6) {
    case 0: {
      state.buildings["demo-bakery"] = {
        ...structuredClone(state.buildings.bakery),
        id: "demo-bakery",
        name: "The Second Hearth",
        plot_id: "plot-4",
        position: { x: 0, z: 3 },
      };
      event = {
        ...base,
        type: "building_constructed",
        payload: {
          entity_id: "demo-bakery",
          position: { x: 0, z: 3 },
          level: null,
        },
      };
      break;
    }
    case 1:
      state.buildings.bakery.level = Math.min(
        3,
        state.buildings.bakery.level + 1,
      );
      event = {
        ...base,
        type: "building_upgraded",
        payload: {
          entity_id: "bakery",
          level: state.buildings.bakery.level,
          position: null,
        },
      };
      break;
    case 2:
      state.citizens.visitor = {
        ...structuredClone(state.citizens["citizen-0"]),
        id: "visitor",
        name: "Sage",
        occupation: "Traveler",
        position: { x: -6, z: 0 },
      };
      event = {
        ...base,
        type: "citizen_spawned",
        payload: {
          entity_id: "visitor",
          position: { x: -6, z: 0 },
          level: null,
        },
      };
      break;
    case 3:
      state.citizens["citizen-0"].position = { x: 4, z: 0 };
      event = {
        ...base,
        type: "citizen_moved",
        payload: {
          entity_id: "citizen-0",
          position: { x: 4, z: 0 },
          level: null,
        },
      };
      break;
    case 4: {
      const old = state.buildings.bakery.prices.bread;
      state.buildings.bakery.prices.bread = Math.round(old * 1.4);
      event = {
        ...base,
        type: "price_changed",
        payload: {
          building_id: "bakery",
          resource: "bread",
          old_price: old,
          new_price: state.buildings.bakery.prices.bread,
        },
      };
      break;
    }
    default:
      delete state.citizens.visitor;
      event = {
        ...base,
        type: "citizen_removed",
        payload: { entity_id: "visitor", position: null, level: null },
      };
  }
  state.sequence++;
  update.sequence = state.sequence;
  update.events = [event];
  return update;
}
