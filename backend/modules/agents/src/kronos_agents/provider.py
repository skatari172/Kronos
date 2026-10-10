import asyncio
import json
import re
from typing import Protocol

from kronos_sim.models import AgentAction, PriceIntervention, WorldState
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
        citizen = observation["citizen"]
        return json.dumps(
            {
                "type": "communicate",
                "actor_id": citizen["id"],
                "recipient_id": observation["recipient_id"],
                "message": "Bread is getting costly; I am watching my savings."
                if observation["bread_price"] >= 700
                else "There is fresh bread at the bakery.",
                "rationale": "Share the observed price with a neighbor.",
            }
        )


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

    async def propose(self, world: WorldState) -> list[AgentAction]:
        # One strategic call every third day; routine mechanics never call an LLM.
        if (world.tick + 1) % 3:
            return []
        citizens = sorted(world.citizens.values(), key=lambda c: c.id)
        if len(citizens) < 2:
            return []
        prices = [b.prices["bread"] for b in world.buildings.values() if b.kind == "bakery"]
        if not prices:
            return []
        action = await self._validated(
            "decision",
            {
                "citizen": citizens[-1].model_dump(),
                "recipient_id": citizens[0].id,
                "bread_price": min(prices),
            },
            TypeAdapter(AgentAction),
        )
        if action.actor_id != citizens[-1].id:
            raise ProviderError("Provider proposed an action for a different citizen")
        return [action]
