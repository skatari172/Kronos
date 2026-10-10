"""Read-only views derived from a world. Used by API routes and the agent layer alike."""

from kronos_sim import models as m
from kronos_sim.engine import SUPPORTED_ACTIONS

# Wealth tiers in cents, tuned for the current seed (spec: rich >= 1,000 florins, middle >= 300).
RICH_CENTS = 10000
MIDDLE_CENTS = 3000


def wealth_tier(money: int) -> m.WealthTier:
    return "rich" if money >= RICH_CENTS else "middle" if money >= MIDDLE_CENTS else "poor"


def profile(state: m.WorldState, citizen_id: str) -> m.CitizenProfile:
    citizen = state.citizens.get(citizen_id)
    if citizen is None:
        raise KeyError("Unknown citizen")
    owned = sorted(b.id for b in state.buildings.values() if b.owner_id == citizen_id)
    return m.CitizenProfile(
        citizen=citizen.model_copy(deep=True),
        role="business_owner" if owned else "commoner",
        wealth_tier=wealth_tier(citizen.money),
        employed=citizen.employer_id in state.buildings,
        owned_building_ids=owned,
    )


def observe(state: m.WorldState, citizen_id: str) -> m.AgentObservation:
    """The single observation builder for routes, /decide, and the tick loop."""
    view = profile(state, citizen_id)
    return m.AgentObservation(
        branch_id=state.branch_id,
        tick=state.tick,
        sequence=state.sequence,
        citizen=view.citizen,
        role=view.role,
        wealth_tier=view.wealth_tier,
        bread_prices={
            b.id: b.prices["bread"] for b in state.buildings.values() if b.kind == "bakery"
        },
        neighbors={
            c.id: c.name
            for c in sorted(state.citizens.values(), key=lambda c: c.id)
            if c.id != citizen_id
        },
        available_actions=list(SUPPORTED_ACTIONS),
    )


def business_profile(state: m.WorldState, building_id: str) -> m.BusinessProfile:
    building = state.buildings.get(building_id)
    if building is None:
        raise KeyError("Unknown business")
    staff = sorted(c.id for c in state.citizens.values() if c.employer_id == building_id)
    return m.BusinessProfile(
        building=building.model_copy(deep=True),
        employee_ids=staff,
        free_slots=max(0, building.job_slots - len(staff)),
    )


def job_openings(state: m.WorldState) -> list[m.JobOpening]:
    """Businesses with at least one free slot, in building ID order."""
    applications = sorted(state.job_applications.values(), key=lambda a: a.sequence)
    openings = []
    for building_id in sorted(state.buildings):
        view = business_profile(state, building_id)
        if view.free_slots < 1:
            continue
        building = view.building
        openings.append(
            m.JobOpening(
                building_id=building.id,
                name=building.name,
                kind=building.kind,
                owner_id=building.owner_id,
                plot_id=building.plot_id,
                position=building.position,
                wage=building.wage,
                free_slots=view.free_slots,
                applicant_ids=[a.citizen_id for a in applications if a.building_id == building.id],
            )
        )
    return openings
