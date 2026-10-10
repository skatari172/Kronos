import pytest
from kronos_sim.engine import Engine, InvalidAction
from kronos_sim.models import (
    AdoptInvention,
    LicenseInvention,
    Research,
    RespondLicense,
    WorldState,
)
from kronos_sim.seed import initial_world


def money(state):
    return sum(c.money for c in state.citizens.values()) + sum(
        b.cash for b in state.buildings.values()
    )


def apply(state, action):
    return Engine(state).apply(action).state


def rejected(state, action) -> str:
    with pytest.raises(InvalidAction) as error:
        Engine(state).apply(action)
    return error.value.code


def unlocked_crop_rotation():
    """Elena funds crop rotation outright and owns it."""
    return apply(
        initial_world(),
        Research(actor_id="citizen-0", invention_id="crop_rotation", mode="money", amount=1500),
    )


def test_seeded_inventions_fit_the_wheat_and_bread_economy():
    inventions = initial_world().inventions
    assert sorted(inventions) == ["crop_rotation", "water_mill"]
    assert inventions["crop_rotation"].effect.building_kind == "farm"
    assert inventions["water_mill"].effect.resource == "bread"
    assert not any(i.unlocked for i in inventions.values())


def test_money_research_is_capped_leaves_the_economy_and_unlocks():
    state = initial_world()
    partial = Engine(state).apply(
        Research(actor_id="citizen-2", invention_id="crop_rotation", mode="money", amount=600)
    )
    assert [e.type for e in partial.events] == ["research_contributed"]
    assert money(partial.state) == money(state) - 600
    result = Engine(partial.state).apply(
        Research(actor_id="citizen-0", invention_id="crop_rotation", mode="money", amount=5000)
    )
    invention = result.state.inventions["crop_rotation"]
    assert [e.type for e in result.events] == ["research_contributed", "invention_unlocked"]
    assert invention.progress == invention.cost == 1500
    assert invention.contributors == {"citizen-2": 600, "citizen-0": 900}
    assert invention.unlocked and invention.owner_id == "citizen-0"
    assert result.state.citizens["citizen-0"].money == 18000 - 900
    assert rejected(
        result.state,
        Research(actor_id="citizen-2", invention_id="crop_rotation", mode="money", amount=1),
    ) == ("bad_params")


def test_owner_tie_breaks_by_citizen_id():
    state = initial_world()
    for actor in ("citizen-2", "citizen-1"):
        state = apply(
            state,
            Research(actor_id=actor, invention_id="crop_rotation", mode="money", amount=750),
        )
    assert state.inventions["crop_rotation"].owner_id == "citizen-1"


def test_research_rejections():
    state = initial_world()
    assert (
        rejected(state, Research(actor_id="citizen-6", invention_id="x", mode="money", amount=1))
        == "unknown_entity"
    )
    assert (
        rejected(
            state,
            Research(actor_id="citizen-6", invention_id="water_mill", mode="money", amount=600),
        )
        == "insufficient_funds"
    )
    # Finn has no job, so he has no wage to forfeit.
    assert (
        rejected(
            state, Research(actor_id="citizen-6", invention_id="water_mill", mode="time", ticks=3)
        )
        == "bad_params"
    )


def test_time_research_forfeits_wages_and_counts_them_as_progress():
    state = apply(
        initial_world(),
        Research(actor_id="citizen-3", invention_id="crop_rotation", mode="time", ticks=2),
    )
    rowan = state.citizens["citizen-3"]
    assert (rowan.research_invention_id, rowan.research_until_tick) == ("crop_rotation", 2)
    assert (
        rejected(
            state, Research(actor_id="citizen-3", invention_id="water_mill", mode="time", ticks=1)
        )
        == "bad_params"
    )
    baseline = Engine(initial_world()).tick()
    day1 = Engine(state).tick()
    wage = 150
    assert day1.state.citizens["citizen-3"].money == (
        baseline.state.citizens["citizen-3"].money - wage
    )
    assert day1.state.buildings["farm"].cash == baseline.state.buildings["farm"].cash + wage
    assert day1.state.inventions["crop_rotation"].contributors == {"citizen-3": wage}
    contributed = [e for e in day1.events if e.type == "research_contributed"]
    assert contributed[0].payload.days_left == 1
    day2 = Engine(day1.state).tick().state
    assert day2.inventions["crop_rotation"].progress == 2 * wage
    assert day2.citizens["citizen-3"].research_invention_id is None
    day3 = Engine(day2).tick()
    assert day3.state.inventions["crop_rotation"].progress == 2 * wage
    assert any(
        e.type == "transaction_completed" and e.payload.recipient_id == "citizen-3"
        for e in day3.events
    )


def test_time_research_can_unlock_and_release_researchers():
    state = initial_world()
    state.inventions["crop_rotation"].progress = 1400
    state.inventions["crop_rotation"].contributors = {"citizen-2": 1400}
    for actor in ("citizen-3", "citizen-4"):
        state = apply(
            state,
            Research(actor_id=actor, invention_id="crop_rotation", mode="time", ticks=5),
        )
    result = Engine(state).tick()
    invention = result.state.inventions["crop_rotation"]
    assert invention.unlocked and invention.owner_id == "citizen-2"
    assert invention.contributors == {"citizen-2": 1400, "citizen-3": 100}
    unlocked = next(e for e in result.events if e.type == "invention_unlocked")
    assert unlocked.payload.released_researcher_ids == ["citizen-3", "citizen-4"]
    assert result.state.citizens["citizen-4"].research_invention_id is None


def test_license_needs_consent_and_moves_the_fee_on_accept():
    state = unlocked_crop_rotation()
    offer = LicenseInvention(
        actor_id="citizen-0", invention_id="crop_rotation", recipient_id="citizen-1", fee=400
    )
    assert rejected(state, offer.model_copy(update={"actor_id": "citizen-1"})) == "not_owner"
    assert (
        rejected(initial_world(), offer.model_copy(update={"invention_id": "water_mill"}))
        == "invention_locked"
    )
    offered = Engine(state).apply(offer)
    [oid] = offered.state.license_offers
    assert offered.events[0].type == "license_offered"
    assert oid in offered.state.citizens["citizen-1"].memories[-1]
    assert rejected(offered.state, offer) == "bad_params"  # Already pending.
    assert (
        rejected(offered.state, RespondLicense(actor_id="citizen-2", offer_id=oid, accept=True))
        == "insufficient_authority"
    )
    accepted = Engine(offered.state).apply(
        RespondLicense(actor_id="citizen-1", offer_id=oid, accept=True)
    )
    assert [e.type for e in accepted.events] == ["transaction_completed", "license_resolved"]
    assert accepted.state.citizens["citizen-1"].money == 22000 - 400
    assert accepted.state.citizens["citizen-0"].money == offered.state.citizens[
        "citizen-0"
    ].money + (400)
    assert accepted.state.inventions["crop_rotation"].licensees == ["citizen-1"]
    assert accepted.state.license_offers == {}
    assert money(accepted.state) == money(offered.state)


def test_license_decline_expiry_and_funds_recheck():
    state = unlocked_crop_rotation()
    offer = LicenseInvention(
        actor_id="citizen-0", invention_id="crop_rotation", recipient_id="citizen-6", fee=900
    )
    offered = apply(state, offer)
    [oid] = offered.license_offers
    respond = RespondLicense(actor_id="citizen-6", offer_id=oid, accept=True)
    assert rejected(offered, respond) == "insufficient_funds"
    declined = Engine(offered).apply(respond.model_copy(update={"accept": False}))
    assert declined.events[0].payload.status == "declined"
    assert declined.state.inventions["crop_rotation"].licensees == []
    first_day = Engine(offered).tick()
    assert oid in first_day.state.license_offers
    later = Engine(first_day.state).tick()
    expired = [e for e in later.events if e.type == "license_resolved"]
    assert [e.payload.status for e in expired] == ["expired"]
    assert later.state.license_offers == {}
    assert rejected(later.state, respond) == "unknown_entity"


def test_adoption_requires_unlock_and_rights_and_boosts_production():
    locked = AdoptInvention(actor_id="citizen-0", invention_id="crop_rotation", building_id="farm")
    assert rejected(initial_world(), locked) == "invention_locked"
    state = unlocked_crop_rotation()
    assert rejected(state, locked.model_copy(update={"actor_id": "citizen-1"})) == "not_owner"
    assert (
        rejected(
            state, locked.model_copy(update={"building_id": "bakery", "actor_id": "citizen-1"})
        )
        == "insufficient_authority"
    )
    adopted = Engine(state).apply(locked)
    assert adopted.events[0].type == "invention_adopted"
    assert adopted.state.buildings["farm"].cash == state.buildings["farm"].cash - 1000
    assert adopted.state.inventions["crop_rotation"].adopters == ["farm"]
    assert rejected(adopted.state, locked) == "bad_params"

    def farm_wheat(result):
        return next(
            e.payload.quantity
            for e in result.events
            if e.type == "resource_produced" and e.payload.entity_id == "farm"
        )

    base, boosted = Engine(state).tick(), Engine(adopted.state).tick()
    assert farm_wheat(boosted) == farm_wheat(base) * 140 // 100
    assert boosted.state.rng_state == base.state.rng_state


def test_licensee_adopts_water_mill_for_double_bread():
    state = apply(
        initial_world(),
        Research(actor_id="citizen-0", invention_id="water_mill", mode="money", amount=2500),
    )
    wrong_kind = AdoptInvention(actor_id="citizen-0", invention_id="water_mill", building_id="farm")
    assert rejected(state, wrong_kind) == "bad_params"
    state = apply(
        state,
        LicenseInvention(
            actor_id="citizen-0", invention_id="water_mill", recipient_id="citizen-1", fee=0
        ),
    )
    [oid] = state.license_offers
    state = apply(state, RespondLicense(actor_id="citizen-1", offer_id=oid, accept=True))
    state = apply(
        state, AdoptInvention(actor_id="citizen-1", invention_id="water_mill", building_id="bakery")
    )
    result = Engine(state).tick()
    bread = [
        e.payload.quantity
        for e in result.events
        if e.type == "resource_produced" and e.payload.entity_id == "bakery"
    ]
    assert bread == [6]


def test_worlds_saved_before_inventions_still_load():
    data = initial_world().model_dump()
    del data["inventions"], data["license_offers"]
    for citizen in data["citizens"].values():
        del citizen["research_invention_id"], citizen["research_until_tick"]
    state = WorldState.model_validate(data)
    assert state.inventions == {} and state.license_offers == {}
    assert Engine(state).tick().tick == 1


def test_queued_time_research_forfeits_exactly_the_requested_number_of_days():
    action = Research(actor_id="citizen-3", invention_id="crop_rotation", mode="time", ticks=2)
    first = Engine(initial_world()).tick([action]).state
    assert first.citizens["citizen-3"].money == 950
    assert first.inventions["crop_rotation"].progress == 0  # Research starts next day.
    second = Engine(first).tick().state
    third = Engine(second).tick().state
    assert third.citizens["citizen-3"].money == 950
    assert third.inventions["crop_rotation"].progress == 300
    assert third.citizens["citizen-3"].research_invention_id is None
    fourth = Engine(third).tick().state
    assert fourth.citizens["citizen-3"].money == 1100
