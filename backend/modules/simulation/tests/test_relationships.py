"""Relationships (agents-api.md section 5.2): interact effects, trust in hiring, observation."""

import pytest
from kronos_sim.engine import Engine, InvalidAction
from kronos_sim.models import ApplyJob, Citizen, Interact, Relationship, WorldState
from kronos_sim.queries import observe, relationship_pair, relationships, strongest_ties
from kronos_sim.seed import initial_world


def interact(state, kind, actor="citizen-0", target="citizen-6", **fields):
    return Engine(state).apply(Interact(actor_id=actor, recipient_id=target, kind=kind, **fields))


def tie(state, holder, other):
    return next((r for r in state.citizens[holder].relationships if r.citizen_id == other), None)


def set_tie(state, holder, other, **fields):
    state.citizens[holder].relationships.append(Relationship(citizen_id=other, **fields))


@pytest.mark.parametrize(
    "kind,trust,grudge,kind_type",
    [
        ("befriend", 10, 0, "acquaintance"),
        ("argue", -10, 10, "acquaintance"),
        ("insult", -15, 20, "acquaintance"),
        ("betray", -50, 50, "rival"),
        ("mentor", 10, 0, "acquaintance"),
    ],
)
def test_interact_changes_the_targets_feeling_toward_the_actor(kind, trust, grudge, kind_type):
    result = interact(initial_world(), kind)
    felt = tie(result.state, "citizen-6", "citizen-0")
    assert (felt.trust, felt.grudge, felt.type) == (trust, grudge, kind_type)
    own = tie(result.state, "citizen-0", "citizen-6")
    assert own.last_interaction_tick == 0
    if kind == "argue":  # Mutual: both sides argued.
        assert (own.trust, own.grudge) == (-10, 10)
    else:
        assert (own.trust, own.grudge) == (0, 0)
    types = [e.type for e in result.events]
    assert types[0] == "citizen_interacted"
    assert types.count("relationship_changed") == (2 if kind == "argue" else 1)
    changed = result.events[1]
    assert changed.payload.recipient_id == "citizen-6"
    assert changed.payload.citizen_id == "citizen-0"
    assert (changed.payload.trust, changed.payload.grudge) == (trust, grudge)
    assert changed.causal_refs == [result.events[0].id]
    assert result.state.citizens["citizen-6"].memories[-1].startswith("Elena ")


def test_reputation_side_effects():
    insulted = interact(initial_world(), "insult").state
    assert insulted.citizens["citizen-6"].reputation == 48
    betrayed = interact(initial_world(), "betray").state
    assert betrayed.citizens["citizen-0"].reputation == 40
    mentored = interact(initial_world(), "mentor").state
    assert mentored.citizens["citizen-6"].reputation == 52
    event = interact(initial_world(), "betray").events[0]
    assert (event.payload.actor_reputation, event.payload.recipient_reputation) == (40, 50)


def test_gift_moves_money_and_eases_a_grudge():
    state = initial_world()
    set_tie(state, "citizen-6", "citizen-0", trust=-20, grudge=3)
    result = interact(state, "gift", amount=500)
    assert result.state.citizens["citizen-0"].money == 18000 - 500
    assert result.state.citizens["citizen-6"].money == 550 + 500
    felt = tie(result.state, "citizen-6", "citizen-0")
    assert (felt.trust, felt.grudge) == (-5, 0)  # Grudge clamps at 0.
    assert len(result.state.citizens["citizen-6"].relationships) == 1  # Entry reused.
    assert [e.type for e in result.events] == [
        "transaction_completed",
        "citizen_interacted",
        "relationship_changed",
    ]
    assert result.events[1].payload.amount == 500


def test_gift_needs_the_money():
    with pytest.raises(InvalidAction) as error:
        interact(initial_world(), "gift", actor="citizen-6", target="citizen-0", amount=551)
    assert error.value.code == "insufficient_funds"


def test_ally_requires_trust_and_is_mutual():
    state = initial_world()
    set_tie(state, "citizen-6", "citizen-0", trust=49)
    with pytest.raises(InvalidAction) as error:
        interact(state, "ally")
    assert error.value.code == "trust_too_low"
    state.citizens["citizen-6"].relationships[0].trust = 50
    result = interact(state, "ally").state
    theirs, own = tie(result, "citizen-6", "citizen-0"), tie(result, "citizen-0", "citizen-6")
    assert (theirs.trust, theirs.type) == (70, "ally")
    assert (own.trust, own.type) == (20, "ally")


def test_befriend_turns_an_acquaintance_into_a_friend():
    state = initial_world()
    set_tie(state, "citizen-6", "citizen-0", trust=45)
    assert tie(interact(state, "befriend").state, "citizen-6", "citizen-0").type == "friend"
    state.citizens["citizen-6"].relationships[0].type = "creditor"
    assert tie(interact(state, "befriend").state, "citizen-6", "citizen-0").type == "creditor"


def test_values_clamp():
    state = initial_world()
    set_tie(state, "citizen-6", "citizen-0", trust=-80, grudge=90, type="ally")
    state.citizens["citizen-0"].reputation = 5
    result = interact(state, "betray").state
    felt = tie(result, "citizen-6", "citizen-0")
    assert (felt.trust, felt.grudge, felt.type) == (-100, 100, "rival")
    assert result.citizens["citizen-0"].reputation == 0


@pytest.mark.parametrize(
    "target,code",
    [("citizen-0", "bad_params"), ("nobody", "unknown_entity")],
)
def test_bad_targets(target, code):
    with pytest.raises(InvalidAction) as error:
        interact(initial_world(), "befriend", target=target)
    assert error.value.code == code


def test_one_interaction_per_pair_per_tick():
    state = interact(initial_world(), "befriend").state
    with pytest.raises(InvalidAction) as error:
        interact(state, "insult")
    assert error.value.code == "rate_limited"
    interact(state, "befriend", actor="citizen-6", target="citizen-0")  # Reverse is separate.
    tomorrow = Engine(state).tick().state
    interact(tomorrow, "insult")


def test_communicate_keeps_existing_tie_fields():
    from kronos_sim.models import Communicate

    state = initial_world()
    set_tie(state, "citizen-6", "citizen-0", trust=10, grudge=40, type="creditor")
    result = Engine(state).apply(
        Communicate(actor_id="citizen-0", recipient_id="citizen-6", message="Pay up")
    )
    felt = tie(result.state, "citizen-6", "citizen-0")
    assert (felt.trust, felt.grudge, felt.type) == (11, 40, "creditor")
    payload = result.events[-1].payload
    assert (payload.trust, payload.grudge, payload.type) == (11, 40, "creditor")


def test_owner_hires_the_more_trusted_applicant_first():
    state = initial_world()
    state.buildings["market"].job_slots = 2  # One free slot, two applicants.
    state = Engine(state).apply(ApplyJob(actor_id="citizen-6", building_id="market")).state
    state = Engine(state).apply(ApplyJob(actor_id="citizen-5", building_id="market")).state
    first_come = Engine(state).tick().state
    assert first_come.citizens["citizen-6"].employer_id == "market"
    set_tie(state, "citizen-2", "citizen-5", trust=30)
    trusted = Engine(state).tick().state
    assert trusted.citizens["citizen-5"].employer_id == "market"
    assert trusted.citizens["citizen-6"].employer_id is None
    set_tie(state, "citizen-2", "citizen-6", trust=30)  # Tie: first come again.
    assert Engine(state).tick().state.citizens["citizen-6"].employer_id == "market"


def test_relationship_queries_and_observation():
    state = initial_world()
    set_tie(state, "citizen-0", "citizen-1", trust=20)
    set_tie(state, "citizen-0", "citizen-6", trust=-60, grudge=70, type="creditor")
    set_tie(state, "citizen-0", "citizen-3", trust=0)  # Neutral: not a strong tie.
    set_tie(state, "citizen-0", "gone", trust=90)  # Departed citizen: hidden.
    listed = relationships(state, "citizen-0")
    assert [(v.citizen_id, v.name, v.trust) for v in listed] == [
        ("citizen-1", "Marcus", 20),
        ("citizen-3", "Rowan", 0),
        ("citizen-6", "Finn", -60),
    ]
    assert [v.citizen_id for v in strongest_ties(state, "citizen-0")] == ["citizen-6", "citizen-1"]
    assert [v.citizen_id for v in observe(state, "citizen-0").ties] == ["citizen-6", "citizen-1"]
    assert "interact" in observe(state, "citizen-0").available_actions
    pair = relationship_pair(state, "citizen-0", "citizen-6")
    assert (pair.a_to_b.grudge, pair.a_to_b.type, pair.a_to_b.known) == (70, "creditor", True)
    assert (pair.b_to_a.trust, pair.b_to_a.known, pair.b_to_a.name) == (0, False, "Elena")
    with pytest.raises(KeyError):
        relationship_pair(state, "citizen-0", "nobody")


def test_ties_are_capped():
    state = initial_world()
    for i in range(1, 7):
        set_tie(state, "citizen-0", f"citizen-{i}", trust=i * 10)
    assert [v.trust for v in observe(state, "citizen-0").ties] == [60, 50, 40, 30, 20]


def test_saved_relationships_without_new_fields_still_load():
    saved = initial_world().model_dump()
    saved["citizens"]["citizen-0"]["relationships"] = [{"citizen_id": "citizen-1", "trust": 5}]
    loaded = WorldState.model_validate(saved).citizens["citizen-0"].relationships[0]
    assert (loaded.grudge, loaded.type, loaded.last_interaction_tick) == (0, "acquaintance", None)
    assert Citizen.model_validate(saved["citizens"]["citizen-0"]).relationships[0].trust == 5


def test_old_relationship_events_still_load():
    from kronos_sim.engine import EVENT

    event = EVENT.validate_python(
        dict(
            id="main:1",
            branch_id="main",
            tick=0,
            sequence=1,
            type="relationship_changed",
            actor_id="citizen-0",
            payload={"recipient_id": "citizen-6", "trust": 1},
        )
    )
    assert (event.payload.grudge, event.payload.type, event.payload.citizen_id) == (
        0,
        "acquaintance",
        None,
    )
