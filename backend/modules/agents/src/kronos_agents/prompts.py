"""Prompt templates for real LLM providers.

The system prompts and few-shot examples are static per code version so a provider can cache
them; everything that varies (the observation, the question) goes in the user message.
"""

import json
from functools import cache

from kronos_sim.models import AgentAction
from kronos_sim.queries import observe
from kronos_sim.seed import initial_world
from pydantic import TypeAdapter

DECISION_RULES = """\
You are the mind of one citizen in KRONOS, a small simulated village economy. Each turn you \
receive an observation of exactly one citizen (`citizen`) and reply with ONE action for that \
citizen as a JSON object. The simulation engine validates every action; invalid ones are \
rejected and remembered by the citizen, so choose actions that will succeed.

Hard rules:
- Act only as the observed citizen: `actor_id` must equal `citizen.id`. Never act for anyone else.
- `type` must be one of `available_actions`.
- Only reference IDs that appear in the observation (bakery IDs in `bread_prices`, citizen IDs in \
`neighbors`, loan, offer and tie IDs). Never invent IDs.
- Always include a short first-person `rationale` (one sentence, at most 300 characters) that \
explains the choice from the citizen's own goals and needs.
- You only know what the observation shows. Do not assume other citizens' money or stock.

How the village works (all money is integer cents; 100 cents = 1 coin):
- Hunger runs 0-100 and rises by 20 each day. `consume` eats one bread (-30 hunger). At the \
end of each day a citizen with no bread automatically buys one from the cheapest bakery, so \
buying bread matters most when hunger is high or prices are low.
- `buy` needs `building_id`, `resource`, `quantity` and `max_unit_price`; it fails when the \
price is above `max_unit_price`, the shop is out of stock, or the buyer cannot pay \
(`insufficient_funds`). A market tax may apply to every purchase.
- Jobs: an unemployed citizen (`employer_id` null) may `apply_job` at a business; owners `hire` \
or `reject_application`, and unanswered applications resolve the next day. Each business pays \
its own `wage` per employee per day; three missed wage days bankrupt it.
- Owners (`role` = business_owner) can `set_price` and `set_wage`, `produce`, `hire` and `fire`. \
Only owners may change their own business (`not_owner` otherwise).
- Loans: `lend` makes an offer the borrower must `respond_loan` to; owed = principal + \
principal x rate_bps / 10000; unpaid after the due day it defaults (lender trust -30, \
borrower reputation -5). `repay` can be partial.
- Trade: `trade` offers a give/get bundle to one citizen; only they may `respond_trade`; offers \
expire after 2 days.
- Social: `communicate` sends a short message (+1 trust); `interact` (befriend, gift, ally, \
argue, insult, betray, mentor) changes trust and grudges; `ally` needs trust >= 50.
- Town: influence comes from wealth, reputation and others' trust. `propose_vote` and `vote` \
decide min_wage, bread_price_cap and market_tax policies.
- `goal_weights` (wealth, influence, safety, reputation; sum 100) describe what this citizen \
values. Weigh choices by them, but survival (not starving, not going broke) comes first.

Reply with the JSON action only."""

ASK_RULES = """\
You are one citizen of KRONOS, a simulated village, answering a question from the player in \
the first person. You receive your own observation, the question and `events`: the only records \
of what happened to you.

Rules:
- Answer only from the given `events` and your observation. If they do not answer the question, \
say you do not know. Never invent events, motives or other people's thoughts.
- `cited_event_ids` must list the `id` of every event your answer relies on, and only IDs that \
appear in `events`.
- Keep the answer under 1000 characters, in plain words, as the citizen would speak.

Reply with the JSON object only."""

INTERVENTION_RULES = """\
You translate a player's plain-language command for the KRONOS village simulation into one \
structured intervention object. The `text` field holds the command.

Rules:
- Only express what the command literally asks for; never add effects it did not mention.
- Percentages are whole numbers: "increase by 40%" is 40, "decrease by 20%" is -20.
- If the command cannot be expressed by the schema, still return the closest valid object only \
when the intent is unambiguous; the server rejects anything out of bounds.

Reply with the JSON object only."""


def _example(world, citizen_id: str, action: dict) -> str:
    observation = observe(world, citizen_id).model_dump(mode="json")
    TypeAdapter(AgentAction).validate_python(action)  # examples must stay real model shapes
    return (
        f"Observation:\n{json.dumps(observation, separators=(',', ':'))}\n"
        f"Action:\n{json.dumps(action, separators=(',', ':'))}"
    )


@cache
def decision_examples() -> list[str]:
    """Three observation -> action pairs built from the real seed world and models."""
    world = initial_world(42)
    examples = []

    hungry = world.model_copy(deep=True)
    hungry.citizens["citizen-6"].hunger = 70
    examples.append(
        _example(
            hungry,
            "citizen-6",
            {
                "type": "consume",
                "actor_id": "citizen-6",
                "rationale": "I am hungry and I already have a loaf, so I eat it.",
            },
        )
    )

    no_bread = world.model_copy(deep=True)
    no_bread.citizens["citizen-5"].inventory.bread = 0
    examples.append(
        _example(
            no_bread,
            "citizen-5",
            {
                "type": "buy",
                "actor_id": "citizen-5",
                "building_id": "bakery",
                "resource": "bread",
                "quantity": 1,
                "max_unit_price": 500,
                "rationale": "I have no bread left and can afford the bakery's 500-cent loaf.",
            },
        )
    )

    examples.append(
        _example(
            world,
            "citizen-6",
            {
                "type": "apply_job",
                "actor_id": "citizen-6",
                "building_id": "farm",
                "rationale": "I am fed but have little money and no job; a wage keeps me safe.",
            },
        )
    )
    return examples


@cache
def system_prompt(task: str) -> str:
    if task == "decision":
        shots = "\n\n".join(
            f"Example {i}:\n{text}" for i, text in enumerate(decision_examples(), 1)
        )
        return f"{DECISION_RULES}\n\n<examples>\n{shots}\n</examples>"
    if task == "ask":
        return ASK_RULES
    if task == "intervention":
        return INTERVENTION_RULES
    raise ValueError(f"Unknown task {task!r}")


def user_message(task: str, observation: dict) -> str:
    """The per-request part. Sorted keys keep identical inputs byte-identical."""
    payload = json.dumps(observation, sort_keys=True, separators=(",", ":"))
    if task == "decision":
        return f"Observation:\n{payload}\nAction:"
    if task == "ask":
        return f"Context:\n{payload}\nAnswer the `question` as this citizen."
    return f"Command:\n{payload}"
