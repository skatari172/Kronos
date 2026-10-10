/**
 * HARD-CODED SAMPLE copy for the details panel. Replace with endpoints later:
 * a citizen's latest thought from `GET /api/agents/{id}` (memories) or
 * `POST /api/agents/{id}/ask`. Numbers shown in the panel (money, hunger,
 * job, cash, prices, staff, rent) already come live from the snapshot.
 */

const THOUGHTS: Record<string, string> = {
  "citizen-0": "Wheat prices hold steady. Time to plant another field?",
  "citizen-1": "Should I raise the price of bread?",
  "citizen-2": "A market tax would hurt business.",
  "citizen-3": "Another month and I can rent a room.",
  "citizen-4": "The empty lot would make a fine market.",
  "citizen-5": "A second bakery could really work.",
  "citizen-6": "Bread is getting costly; I'm watching my savings.",
};

/** What's on a villager's mind; newcomers get a generic line. */
export const citizenThought = (id: string) =>
  THOUGHTS[id] ?? "Everyone here seems to know each other.";

export const PLACE_NOTES: Record<string, string> = {
  "Oakhaven Chapel":
    "Where the town gathers on rest days and votes are announced.",
  "The Forge": "Tools, hinges, and horseshoes. The blacksmith works late.",
  "Riverside Lumbermill": "Cuts timber for every new building in Oakhaven.",
  "Village Well": "The oldest landmark in town. Gossip travels fastest here.",
  Cottage: "A modest home on the edge of the main road.",
};
