"""Shared natural resource stocks. Gathering is an agent tool in routes/agents.py.

Interventions (for example a failed harvest) change stock and regen_per_tick through the
engine, not through this module.
"""

from fastapi import APIRouter
from kronos_sim import models as m
from kronos_sim.queries import resource_stocks

from kronos.dependencies import ServiceDependency

router = APIRouter(prefix="/api/resources", tags=["World"])


@router.get("", response_model=list[m.ResourceStock], summary="Stock and regeneration per resource")
async def resources(service: ServiceDependency):
    """Sorted by kind. Stocks regenerate once per tick up to cap; farms and gatherers draw them."""
    async with service.lock:
        return resource_stocks(service.state)
