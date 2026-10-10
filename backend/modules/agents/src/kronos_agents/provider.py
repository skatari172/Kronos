import asyncio
import json
import re
from typing import Protocol

from kronos_sim.models import (
    AgentAction,
    AgentObservation,
    AskResult,
    PriceIntervention,
    SimulationEvent,
    WorldState,
)
from kronos_sim.queries import observe
from pydantic import TypeAdapter, ValidationError


class ProviderError(ValueError):
    pass


class LLMProvider(Protocol):
    async def complete(self, task: str, observation: dict) -> str: ...


class MockProvider:
    """Narrow, honest grammar; no paid service or invented interpretation."""

    async def complete(self, task: str, observation: dict) -> str:
        if task == "intervention":
            match = re.fullmatch(
                r"\s*(increase|decrease|reduce)\s+(?:the\s+)?(?:price\s+of\s+bread|"
                r"bread\s+prices?)\s+by\s+(\d{1,3})\s*%[.!]?\s*",
                observation["text"],
                re.IGNORECASE,
            )
            if not match:
                raise ProviderError(
                    "Supported: 'Increase bread price by 40%' or decrease by a percent."
                )
            percent = int(match[2]) * (1 if match[1].lower() == "increase" else -1)
            return json.dumps(
                {
                    "type": "modify_price",
                    "percent": percent,
                    "resource": "bread",
                    "scope": "all_bakeries",
                }
            )
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


class AgentService:
    def __init__(self, provider: LLMProvider, timeout: float = 3, retries: int = 1):
        self.provider, self.timeout, self.retries = provider, timeout, min(max(retries, 0), 2)

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

    async def parse(self, text: str) -> PriceIntervention:
        return await self._validated("intervention", {"text": text}, TypeAdapter(PriceIntervention))

    async def decide(self, observation: AgentObservation) -> AgentAction:
        """One proposal for the observed citizen. The engine still decides if it is valid."""
        action = await self._validated(
            "decision", observation.model_dump(mode="json"), TypeAdapter(AgentAction)
        )
        if action.actor_id != observation.citizen.id:
            raise ProviderError("Provider proposed an action for a different citizen")
        return action

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

    async def propose(
        self, world: WorldState, events: list[SimulationEvent] | None = None
    ) -> list[AgentAction]:
        """A small post-tick decision budget; every result is a next-day proposal.

        Each provider sees only its own copied observation. gather preserves citizen
        order even when network calls finish in a different order. A failed decision
        does not discard other citizens' decisions or interrupt the clock.
        """
        candidates = [
            cid
            for cid in sorted(world.citizens)
            if (
                world.citizens[cid].inventory.bread == 0
                or any(offer.recipient_id == cid for offer in world.trade_offers.values())
                or (world.tick > 0 and world.tick % 3 == 0)
            )
        ][:8]
        selected = [observe(world, cid, events) for cid in candidates]
        outcomes = await asyncio.gather(
            *(self.decide(observation) for observation in selected), return_exceptions=True
        )
        return [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
