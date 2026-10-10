import type { SimulationEvent, WorldState } from "./types";
export const coins = (cents: number) => (cents / 100).toFixed(2);

export function describeEvent(event: SimulationEvent, world?: WorldState) {
  const name = (id: string | null | undefined) =>
    id
      ? world?.citizens[id]?.name || world?.buildings[id]?.name || id
      : "Someone";
  switch (event.type) {
    case "price_changed":
      return `${event.payload.resource} price: ${coins(event.payload.old_price)} → ${coins(event.payload.new_price)} coins`;
    case "intervention_applied":
      return "You changed the course of the village";
    case "transaction_completed": {
      const p = event.payload;
      if (p.resource && p.amount > 0 && world?.buildings[p.recipient_id])
        return `${name(p.sender_id)} bought ${p.quantity} ${p.resource} from ${name(p.recipient_id)} for ${coins(p.amount)} coins.`;
      if (!p.resource)
        return `${name(p.sender_id)} paid ${name(p.recipient_id)} ${coins(p.amount)} coins.`;
      return `${coins(event.payload.amount)} coins exchanged${event.payload.resource ? ` · ${event.payload.quantity} ${event.payload.resource}` : " · wages or transfer"}`;
    }
    case "resource_produced":
      return `${event.payload.quantity} ${event.payload.resource} produced`;
    case "resource_consumed":
      return `${event.payload.quantity} ${event.payload.resource} consumed`;
    case "plot_opened":
      return "New town land opens for building";
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
      return `${name(event.actor_id)} could not ${event.payload.action_type.replaceAll("_", " ")} · ${event.payload.message}`;
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
    case "citizen_interacted":
      return `${name(event.actor_id)} ${event.payload.kind.replaceAll("_", " ")} · ${name(event.payload.recipient_id)}`;
    case "building_removed":
      return "A building is removed";
    default:
      return "Something happens in the village";
  }
}

export function activityCue(events: SimulationEvent[], entityId: string) {
  return [...events]
    .reverse()
    .find(
      (event) =>
        (event.type === "action_rejected" && event.actor_id === entityId) ||
        (event.type === "transaction_completed" &&
          !!event.payload.resource &&
          (event.payload.sender_id === entityId ||
            event.payload.recipient_id === entityId)),
    );
}
