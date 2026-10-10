import asyncio
import json
import logging
import re
import zlib
from typing import NamedTuple, Protocol

from kronos_sim.models import (
    AgentAction,
    AgentObservation,
    AskResult,
    Intervention,
    ProposalSource,
    SimulationEvent,
    WorldState,
)
from kronos_sim.queries import observe
from pydantic import TypeAdapter, ValidationError

logger = logging.getLogger(__name__)


class ProviderError(ValueError):
    pass


class FallbackPolicy(Protocol):
    """Deterministic chooser used when the provider fails (see `kronos_agents.fallback`)."""

    def choose(self, observation: AgentObservation) -> AgentAction: ...


class Proposal(NamedTuple):
    action: AgentAction
    source: ProposalSource


class LLMProvider(Protocol):
    async def complete(self, task: str, observation: dict) -> str: ...


SUPPORTED_INTERVENTIONS = (
    "Supported: 'Increase bread price by 40%' / 'Decrease bread price by 10%'; "
    "'Set wages to 2 coins' / 'Raise wages by 20%' / 'Cut wages by 10%'; "
    "'Give 5 coins to everyone' / 'Give 50 cents to Ada' / 'Take 3 coins from Ada'; "
    "'Harvest boom' / 'Drought' / 'Add 40 wheat' / 'Remove 20 wheat' / "
    "'Set wheat regrowth to 3'; 'Feast' / 'Famine' / 'Reduce hunger by 20 for Ada'; "
    "'Set minimum wage to 2 coins' / 'Cap bread price at 6 coins' / "
    "'Set market tax to 5%' / 'Remove the market tax'."
)
BOOM_WHEAT = 50  # "Harvest boom" adds this much wheat to the village stock; "Drought" removes it.
FEAST_HUNGER = 30  # "Feast" lowers everyone's hunger by this; "Famine" raises it.
_MONEY = r"(\d{1,7})\s*(coins?|cents?)"
_EVERYONE = {"everyone", "everybody", "all", "all citizens", "the village", "the town"}
_UP = {"increase", "raise", "add"}
_POLICY_NAMES = {
    "minimum wage": "min_wage",
    "min wage": "min_wage",
    "bread price cap": "bread_price_cap",
    "bread cap": "bread_price_cap",
    "market tax": "market_tax",
    "tax": "market_tax",
}


def _cents(amount: str, unit: str) -> int:
    return int(amount) * (1 if unit.lower().startswith("cent") else 100)


def _citizen(target: str | None, citizens: dict[str, str] | None) -> str | None:
    """None for everyone, else the citizen ID named by ID or (case-insensitive) name."""
    if target is None or target.lower() in _EVERYONE:
        return None
    citizens = citizens or {}
    if target in citizens:
        return target
    for cid in sorted(citizens):
        if citizens[cid].lower() == target.lower():
            return cid
    raise ProviderError(f"Unknown citizen '{target}'. {SUPPORTED_INTERVENTIONS}")


def mock_intervention(text: str, citizens: dict[str, str] | None = None) -> dict:
    """The mock's regex grammar: one intervention command (as JSON data) or ProviderError."""
    t = re.sub(r"\s+", " ", text).strip().rstrip(".!").strip()

    def match(pattern):
        return re.fullmatch(pattern, t, re.IGNORECASE)

    if m := match(
        r"(increase|raise|decrease|reduce|lower|cut) (?:the )?(?:price of bread|"
        r"bread prices?) by (\d{1,3}) ?%"
    ):
        sign = 1 if m[1].lower() in _UP else -1
        return {
            "type": "modify_price",
            "resource": "bread",
            "scope": "all_bakeries",
            "percent": sign * int(m[2]),
        }
    if m := match(r"set (?:all )?wages to " + _MONEY):
        return {"type": "set_wage", "scope": "all_businesses", "wage": _cents(m[1], m[2])}
    if m := match(r"(increase|raise|decrease|reduce|lower|cut) (?:all )?wages by (\d{1,3}) ?%"):
        sign = 1 if m[1].lower() in _UP else -1
        return {"type": "set_wage", "scope": "all_businesses", "percent": sign * int(m[2])}
    if m := match(r"(give|grant|pay) " + _MONEY + r" to (.+)"):
        return {
            "type": "grant_money",
            "amount": _cents(m[2], m[3]),
            "citizen_id": _citizen(m[4], citizens),
        }
    if m := match(r"(take|remove|confiscate) " + _MONEY + r" from (.+)"):
        return {
            "type": "grant_money",
            "amount": -_cents(m[2], m[3]),
            "citizen_id": _citizen(m[4], citizens),
        }
    if match(r"(?:a )?(?:harvest boom|bumper harvest)"):
        return {"type": "adjust_resource", "resource": "wheat", "stock_change": BOOM_WHEAT}
    if match(r"(?:a )?drought"):
        return {"type": "adjust_resource", "resource": "wheat", "stock_change": -BOOM_WHEAT}
    if m := match(r"(add|remove) (\d{1,5}) wheat(?: (?:to|from) (?:the )?(?:fields?|stock))?"):
        sign = 1 if m[1].lower() in _UP else -1
        return {"type": "adjust_resource", "resource": "wheat", "stock_change": sign * int(m[2])}
    if m := match(r"set (?:the )?wheat (?:regrowth|regen(?:eration)?) to (\d{1,4})(?: per day)?"):
        return {"type": "adjust_resource", "resource": "wheat", "regen_per_tick": int(m[1])}
    if m := match(r"(?:(?:hold|throw) )?(?:a )?(feast|famine)"):
        sign = 1 if m[1].lower() == "famine" else -1
        return {"type": "adjust_hunger", "change": sign * FEAST_HUNGER, "citizen_id": None}
    if m := match(
        r"(increase|raise|decrease|reduce|lower) (?:the )?hunger by (\d{1,3})(?: for (.+))?"
    ):
        sign = 1 if m[1].lower() in _UP else -1
        return {
            "type": "adjust_hunger",
            "change": sign * int(m[2]),
            "citizen_id": _citizen(m[3], citizens),
        }
    if m := match(r"set (?:the )?(minimum wage|min wage) to " + _MONEY):
        return {"type": "set_policy", "kind": "min_wage", "value": _cents(m[2], m[3])}
    if m := match(r"cap (?:the )?bread prices? at " + _MONEY):
        return {"type": "set_policy", "kind": "bread_price_cap", "value": _cents(m[1], m[2])}
    if m := match(r"set (?:the )?(?:market )?tax to (\d{1,3}) ?%"):
        return {"type": "set_policy", "kind": "market_tax", "value": int(m[1]) * 100}
    if m := match(r"(?:remove|lift|abolish) (?:the )?(" + "|".join(_POLICY_NAMES) + ")"):
        return {"type": "set_policy", "kind": _POLICY_NAMES[m[1].lower()], "value": 0}
    raise ProviderError(SUPPORTED_INTERVENTIONS)


class MockProvider:
    """Narrow, honest grammar; no paid service or invented interpretation."""

    source = "mock"  # Proposal source recorded in history; real providers default to "llm".

    async def complete(self, task: str, observation: dict) -> str:
        if task == "intervention":
            return json.dumps(mock_intervention(observation["text"], observation.get("citizens")))
        if task == "ask":
            return json.dumps(self._answer(observation))
        return json.dumps(self._decide(observation))

    @staticmethod
    def _decide(observation: dict) -> dict:
        """Needs first (eat, then buy bread), otherwise share the bread price with a neighbor."""
        citizen, prices = observation["citizen"], observation["bread_prices"]
        bread, actor = citizen["inventory"]["bread"], {"actor_id": citizen["id"]}
        if bread and citizen["hunger"] >= 40:
            return {**actor, "type": "consume", "rationale": "I am hungry and have bread."}
        stocked = [b for b in prices if observation.get("bread_stock", {}).get(b, 1) > 0]
        if not bread and stocked:
            bakery = min(stocked, key=lambda b: (prices[b], b))
            if citizen["money"] >= prices[bakery]:
                return {
                    **actor,
                    "type": "buy",
                    "building_id": bakery,
                    "resource": "bread",
                    "quantity": 1,
                    "max_unit_price": prices[bakery],
                    "rationale": "I have no bread left; this bakery is cheapest.",
                }
        if not observation["neighbors"] or not prices:
            raise ProviderError("The mock has no sensible action for this citizen")
        return {
            **actor,
            "type": "communicate",
            "recipient_id": min(observation["neighbors"]),
            "message": (
                "There is no bread in stock right now."
                if not stocked
                else "Bread is getting costly; I am watching my savings."
                if min(prices[b] for b in stocked) >= 700
                else "There is fresh bread at the bakery."
            ),
            "rationale": "Share the observed price with a neighbor.",
        }

    @staticmethod
    def _answer(observation: dict) -> dict:
        """Templated answer from the citizen's own latest events; never invents causes."""
        recent = observation["events"][-3:]
        if not recent:
            return {"answer": "Nothing has happened to me yet.", "cited_event_ids": []}
        parts = [
            f"{e['type'].replace('_', ' ')} on day {e['tick']}"
            + (f" ({e['rationale']})" if e.get("rationale") else "")
            for e in reversed(recent)
        ]
        return {
            "answer": "I can only speak from my own records. Most recently: "
            + "; ".join(parts)
            + ".",
            "cited_event_ids": [e["id"] for e in reversed(recent)],
        }


# Decisions per post-tick batch; bounds latency however large the town grows.
MAX_DECISIONS = 8


class AgentService:
    def __init__(
        self,
        provider: LLMProvider,
        timeout: float = 3,
        retries: int = 1,
        round_ticks: int = 3,
        fallback: FallbackPolicy | None = None,
        calls_per_tick: int | None = None,
        concurrency: int | None = None,
        strategic_ids: list[str] | None = None,
        strategic_limit: int | None = None,
    ):
        self.provider, self.timeout, self.retries = provider, timeout, min(max(retries, 0), 2)
        self.round_ticks = max(round_ticks, 1)
        # Used when the provider fails; None keeps the old behavior (ProviderError propagates).
        self.fallback = fallback
        # Cost controls for the tick loop (None = unlimited): provider calls per tick, calls
        # in flight at once, and which citizens are strategic (the rest use the fallback).
        self.calls_per_tick, self.concurrency = calls_per_tick, concurrency
        self.strategic_ids, self.strategic_limit = strategic_ids, strategic_limit

    async def _validated(self, task, observation, adapter):
        for attempt in range(self.retries + 1):
            try:
                raw = await asyncio.wait_for(
                    self.provider.complete(task, observation), self.timeout
                )
                return adapter.validate_json(raw)
            except ProviderError:
                raise
            except (TimeoutError, ValidationError, ValueError) as exc:
                if attempt == self.retries:
                    raise ProviderError("Provider returned invalid output or timed out") from exc

    async def parse(self, text: str, citizens: dict[str, str] | None = None) -> Intervention:
        """Turn player text into one validated intervention command.

        `citizens` (ID to name) lets a provider resolve "give 5 coins to Ada" to an ID.
        """
        observation = {"text": text, "citizens": dict(sorted((citizens or {}).items()))}
        return await self._validated("intervention", observation, TypeAdapter(Intervention))

    async def decide(self, observation: AgentObservation) -> AgentAction:
        """One proposal for the observed citizen. The engine still decides if it is valid."""
        return (await self.proposal(observation)).action

    async def proposal(
        self, observation: AgentObservation, *, use_provider: bool = True
    ) -> Proposal:
        """Like `decide`, plus who chose: the provider (`llm`/`mock`) or the `fallback`.

        A provider error, timeout, invalid output or a proposal for another citizen engages
        the fallback policy when one is configured. The source is prefixed to the rationale
        ("[fallback] safety: ...") so event history shows it without a schema change.
        `use_provider=False` (non-strategic citizen, or over the call budget) goes straight
        to the fallback.
        """
        try:
            if not use_provider:
                raise ProviderError("Provider skipped (tier or call budget)")
            action = await self._validated(
                "decision", observation.model_dump(mode="json"), TypeAdapter(AgentAction)
            )
            if action.actor_id != observation.citizen.id:
                raise ProviderError("Provider proposed an action for a different citizen")
            source: ProposalSource = getattr(self.provider, "source", "llm")
        except ProviderError as exc:
            if self.fallback is None:
                raise
            logger.info("Fallback policy for %s: %s", observation.citizen.id, exc)
            action, source = self.fallback.choose(observation), "fallback"
        rationale = f"[{source}] {action.rationale or ''}".strip()[:300]
        return Proposal(action.model_copy(update={"rationale": rationale}), source)

    async def ask(
        self, question: str, observation: AgentObservation, events: list[SimulationEvent]
    ) -> AskResult:
        """Answer from the citizen's point of view, citing only events it was given."""
        context = observation.model_dump(mode="json")
        context["question"] = question
        context["events"] = [event.model_dump(mode="json") for event in events]
        result = await self._validated("ask", context, TypeAdapter(AskResult))
        if not set(result.cited_event_ids) <= {event.id for event in events}:
            raise ProviderError("Answer cited events outside the citizen's history")
        return result


    def scheduled(self, world: WorldState) -> list[str]:
        """Citizens whose slot falls on the coming day, in stable ID order.

        Each citizen decides once per round of `round_ticks` days, on day
        `crc32(citizen_id) % round_ticks` of the round. The slot depends only on the ID,
        so citizens arriving or leaving never shift anyone else's turn.
        """
        rounds = max(self.round_ticks, 1)
        due = (world.tick + 1) % rounds
        return [c for c in sorted(world.citizens) if decision_slot(c, rounds) == due]

    def strategic(self, world: WorldState) -> set[str]:
        """Citizens whose decisions may use the provider (agent tiers).

        An explicit `strategic_ids` list wins. Otherwise business owners come first, then
        everyone else by ID, up to `strategic_limit` (no limit: everyone is strategic).
        """
        if self.strategic_ids is not None:
            return {c for c in self.strategic_ids if c in world.citizens}
        owners = {b.owner_id for b in world.buildings.values()}
        ranked = sorted(world.citizens, key=lambda c: (c not in owners, c))
        return set(ranked if self.strategic_limit is None else ranked[: self.strategic_limit])

    def due(self, world: WorldState) -> list[str]:
        """Who decides after this day, at most MAX_DECISIONS per batch, in ID order.

        Urgent citizens (no bread, or an offer waiting for their answer) decide now; everyone
        else decides once per round on their staggered slot (see `scheduled`).
        """
        urgent = {
            cid
            for cid, citizen in world.citizens.items()
            if citizen.inventory.bread == 0
            or any(offer.recipient_id == cid for offer in world.trade_offers.values())
        }
        return sorted(urgent | set(self.scheduled(world)))[:MAX_DECISIONS]

    async def propose(
        self, world: WorldState, events: list[SimulationEvent] | None = None
    ) -> list[AgentAction]:
        """Next-day proposals for the citizens `due` after this day; daily mechanics never
        call an LLM, and each provider sees only its own copied observation.

        Strategic citizens ask the provider, up to `calls_per_tick` of them in ID order;
        the rest decide with the fallback. At most `concurrency` calls are in flight. Calls
        fail independently: a citizen with no usable decision is skipped this round.
        Nothing here touches the world's seeded RNG.
        """
        due = self.due(world)
        strategic = [c for c in due if c in self.strategic(world)]
        budget = len(strategic) if self.calls_per_tick is None else self.calls_per_tick
        callers = set(strategic[: max(budget, 0)])
        limit = asyncio.Semaphore(self.concurrency or max(len(callers), 1))

        async def one(citizen_id: str) -> AgentAction | None:
            try:
                observation = observe(world, citizen_id, events)
                if citizen_id not in callers:
                    return (await self.proposal(observation, use_provider=False)).action
                async with limit:
                    return (await self.proposal(observation)).action
            except Exception as exc:  # One citizen's failure never stops others.
                logger.warning("Skipping %s's decision this round: %s", citizen_id, exc)
                return None

        actions = await asyncio.gather(*(one(c) for c in due))
        return [action for action in actions if action is not None]


def decision_slot(citizen_id: str, round_ticks: int) -> int:
    """Stable (process-independent) day within a round on which a citizen decides."""
    return zlib.crc32(citizen_id.encode()) % max(round_ticks, 1)
