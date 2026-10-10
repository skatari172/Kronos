import { Activity, ArrowUpRight } from "lucide-react";
import type { SimulationEvent } from "../api/types";
import { useWorld } from "../stores/world";
import { coins } from "../api/format";
const INTERACTIONS: Record<string, string> = {
  befriend: "Two citizens become friendlier",
  gift: "A citizen gives a gift",
  ally: "Two citizens form an alliance",
  argue: "Two citizens argue",
  insult: "A citizen trades insults",
  betray: "A citizen betrays a friend",
  mentor: "A citizen mentors another",
};
function describe(event: SimulationEvent) {
  switch (event.type) {
    case "plot_opened":
      return "New town land opens at the edge of the village";
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
    case "employment_changed":
      return event.payload.building_id
        ? "A citizen starts a new job"
        : "A citizen loses their job";
    case "wage_changed":
      return `Wage: ${coins(event.payload.old_wage)} → ${coins(event.payload.new_wage)} coins a day`;
    case "goals_changed":
      return "A citizen rethinks what matters most";
    case "action_rejected":
      return `A plan fell through · ${event.payload.message}`;
    case "job_applied":
      return "A citizen applies for a job";
    case "job_application_resolved":
      return `Job application ${event.payload.outcome}`;
    case "resource_gathered":
      return `${event.payload.quantity} ${event.payload.resource} gathered`;
    case "resource_regenerated":
      return `The ${event.payload.resource} field regrows`;
    case "trade_offered":
      return "A trade is offered";
    case "trade_accepted":
      return "A trade is agreed";
    case "trade_declined":
      return "A trade is turned down";
    case "trade_expired":
      return "A trade offer lapses";
    case "loan_offered":
      return "A loan is offered";
    case "loan_accepted":
      return "A loan is taken";
    case "loan_declined":
      return "A loan is refused";
    case "loan_repaid":
      return "A debt is paid down";
    case "loan_expired":
      return "A loan offer lapses";
    case "loan_defaulted":
      return "A borrower defaults";
    case "lot_leased":
      return "A lot is leased";
    case "rent_changed":
      return `Rent: ${coins(event.payload.old_rent)} → ${coins(event.payload.new_rent)} coins`;
    case "rent_covered":
      return "Prepaid rent covers this period";
    case "rent_missed":
      return "A tenant misses rent";
    case "tenant_evicted":
      return "A tenant is evicted";
    case "research_contributed":
      return "Research moves forward";
    case "invention_unlocked":
      return "A new invention is unlocked";
    case "license_offered":
      return "An invention license is offered";
    case "license_resolved":
      return `License offer ${event.payload.status}`;
    case "invention_adopted":
      return "A business adopts an invention";
    case "vote_proposed":
      return "A town vote is proposed";
    case "vote_cast":
      return "A ballot is cast";
    case "vote_closed":
      return "The town vote closes";
    case "policy_changed":
      return "Town policy changes";
    case "tax_collected":
      return `${coins(event.payload.amount)} coins of market tax shared out`;
    case "building_removed":
      return "A building is removed";
    case "citizen_interacted":
      return INTERACTIONS[event.payload.kind] ?? "Two citizens cross paths";
    default:
      return "Something happens in the village";
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
