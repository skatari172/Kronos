import { Activity, ArrowUpRight } from "lucide-react";
import type { SimulationEvent } from "../api/types";
import { useWorld } from "../stores/world";
import { coins } from "../api/format";
function describe(event: SimulationEvent) {
  switch (event.type) {
    case "price_changed":
      return `Bread price: ${coins(event.payload.old_price)} → ${coins(event.payload.new_price)} coins`;
    case "intervention_applied":
      return "You changed the course of the village";
    case "transaction_completed":
      return `${coins(event.payload.amount)} coins exchanged${event.payload.resource ? ` · ${event.payload.quantity} ${event.payload.resource}` : " · wages or transfer"}`;
    case "resource_produced":
      return `${event.payload.quantity} ${event.payload.resource} produced`;
    case "resource_consumed":
      return `${event.payload.quantity} ${event.payload.resource} consumed`;
    case "building_constructed":
      return "A new business opens its doors";
    case "building_upgraded":
      return `Building upgraded to level ${event.payload.level}`;
    case "citizen_spawned":
      return "A traveler arrives in the village";
    case "citizen_removed":
      return "A citizen leaves the village";
    case "citizen_moved":
      return "A citizen heads across the village";
    case "agent_spoke":
      return event.payload.message;
    case "relationship_changed":
      return `Familiarity grows · trust ${event.payload.trust}`;
    case "goals_changed":
      return "A citizen rethinks what matters most";
    case "action_rejected":
      return `A plan fell through · ${event.payload.message}`;
    default:
      return "A building is removed";
  }
}
export function EventLedger() {
  const events = useWorld((s) => s.events);
  const important = events
    .filter((e) => e.type !== "citizen_moved" && e.type !== "resource_consumed")
    .slice(-40)
    .reverse();
  return (
    <section className="ledger panel">
      <div className="section-heading">
        <span>THE CHRONICLE</span>
        <Activity size={15} />
      </div>
      <div className="ledger-title">
        <h2>History in the making</h2>
        <span>{events.length} events</span>
      </div>
      <div className="event-list">
        {important.length ? (
          important.map((e) => (
            <details className="event" key={e.id}>
              <summary>
                <i
                  className={
                    e.type === "price_changed" ||
                    e.type === "intervention_applied"
                      ? "gold"
                      : ""
                  }
                />
                <div>
                  <small>
                    DAY {e.tick + 1} <span>#{e.sequence}</span>
                  </small>
                  <p>{describe(e)}</p>
                </div>
                <ArrowUpRight size={13} />
              </summary>
              <div className="event-detail">
                {e.rationale && <p>Agent-stated rationale: {e.rationale}</p>}
                <pre>{JSON.stringify(e, null, 2)}</pre>
              </div>
            </details>
          ))
        ) : (
          <div className="quiet">
            <span>◷</span>
            <p>The village is waking up.</p>
            <small>Advance a day or make your first intervention.</small>
          </div>
        )}
      </div>
    </section>
  );
}
