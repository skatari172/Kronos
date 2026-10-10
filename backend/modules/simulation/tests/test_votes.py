"""Influence, the town vote, and the policies it enacts."""

from typing import get_args

import pytest
from kronos_sim.engine import Engine, InvalidAction
from kronos_sim.models import (
    AgentAction,
    Buy,
    CastVote,
    FoundBusiness,
    ProposeVote,
    Relationship,
    SetPrice,
    SetWage,
    WorldState,
)
from kronos_sim.queries import influence, profile, roles, votes
from kronos_sim.seed import initial_world


def apply(state, *actions):
    for action in actions:
        state = Engine(state).apply(action).state
    return state


def ticks(state, n):
    events = []
    for _ in range(n):
        result = Engine(state).tick()
        state, events = result.state, events + result.events
    return state, events


def open_vote(state, kind="min_wage", value=300, proposer="citizen-6"):
    state = apply(state, ProposeVote(actor_id=proposer, kind=kind, value=value))
    return state, next(v.id for v in state.votes.values() if v.status == "open")


def total_money(state):
    return sum(c.money for c in state.citizens.values()) + sum(
        b.cash for b in state.buildings.values()
    )


def test_influence_formula_in_basis_points():
    state = initial_world()
    rich = influence(state, "citizen-1")
    # Wealth 22,000 own + 10,000 bakery cash out of 94,000 total.
    assert (rich.wealth, rich.wealth_share, rich.reputation) == (32000, 3404, 5000)
    assert rich.trust_from_others == 5000  # Nobody knows anyone yet: neutral.
    assert rich.influence == (5 * 3404 + 3 * 5000 + 2 * 5000) // 10
    assert profile(state, "citizen-1").influence == rich.influence
    state.citizens["citizen-0"].relationships.append(
        Relationship(citizen_id="citizen-6", trust=100)
    )
    state.citizens["citizen-1"].relationships.append(
        Relationship(citizen_id="citizen-6", trust=-100)
    )
    state.citizens["citizen-6"].reputation = 0
    poor = influence(state, "citizen-6")
    assert poor.trust_from_others == (10000 + 0 + 4 * 5000) // 6
    assert poor.reputation == 0
    with pytest.raises(KeyError):
        influence(state, "missing")


def test_min_wage_vote_passes_after_three_days_and_raises_wages():
    state, vid = open_vote(initial_world())
    vote = state.votes[vid]
    assert (vote.opens_tick, vote.closes_tick, vote.status) == (0, 3, "open")
    state = apply(
        state,
        CastVote(actor_id="citizen-0", vote_id=vid, choice="yes"),
        CastVote(actor_id="citizen-6", vote_id=vid, choice="yes"),
        CastVote(actor_id="citizen-3", vote_id=vid, choice="no"),
    )
    state, events = ticks(state, 2)
    assert state.votes[vid].status == "open"
    assert "vote_closed" not in [e.type for e in events]
    state, events = ticks(state, 1)
    vote = state.votes[vid]
    assert vote.status == "passed" and vote.yes_weight > vote.no_weight > 0
    closed = next(e for e in events if e.type == "vote_closed")
    assert closed.payload.passed
    policy = next(e for e in events if e.type == "policy_changed")
    assert (policy.payload.old_value, policy.payload.new_value) == (0, 300)
    raised = [e for e in events if e.type == "wage_changed"]
    assert {e.payload.building_id for e in raised} >= {"bakery", "farm", "market"}
    assert all(e.causal_refs == [closed.id] for e in raised)
    assert state.policies.min_wage == 300
    assert all(b.wage == 300 for b in state.buildings.values())
    with pytest.raises(InvalidAction) as error:
        Engine(state).apply(SetWage(actor_id="citizen-0", building_id="farm", wage=299))
    assert error.value.code == "bad_params"
    apply(state, SetWage(actor_id="citizen-0", building_id="farm", wage=300))


def test_votes_are_weighted_by_influence_not_headcount():
    state, vid = open_vote(initial_world())
    state = apply(
        state,
        CastVote(actor_id="citizen-1", vote_id=vid, choice="no"),
        CastVote(actor_id="citizen-2", vote_id=vid, choice="no"),
        CastVote(actor_id="citizen-3", vote_id=vid, choice="yes"),
        CastVote(actor_id="citizen-4", vote_id=vid, choice="yes"),
        CastVote(actor_id="citizen-6", vote_id=vid, choice="yes"),
    )
    tally = votes(state, "open")[0].tally
    assert tally.ballots == 5
    expected_yes = sum(
        influence(state, c).influence for c in ("citizen-3", "citizen-4", "citizen-6")
    )
    assert tally.yes_weight == expected_yes
    state, _ = ticks(state, 3)
    # Three poor yes ballots lose to two rich no ballots.
    assert state.votes[vid].status == "failed"
    assert state.policies.min_wage == 0
    assert votes(state, "failed")[0].tally.yes_share < 5000
    assert votes(state, "open") == []


def test_a_vote_with_no_ballots_fails():
    state, vid = open_vote(initial_world())
    state, events = ticks(state, 3)
    assert state.votes[vid].status == "failed"
    assert "policy_changed" not in [e.type for e in events]


def test_ballots_replace_and_vote_rules():
    state, vid = open_vote(initial_world())
    state = apply(state, CastVote(actor_id="citizen-0", vote_id=vid, choice="yes"))
    changed = Engine(state).apply(CastVote(actor_id="citizen-0", vote_id=vid, choice="no"))
    assert changed.state.votes[vid].ballots == {"citizen-0": "no"}
    assert changed.events[0].payload.previous_choice == "yes"
    cases = [
        (CastVote(actor_id="citizen-0", vote_id=vid, choice="yes"), "bad_params"),
        (CastVote(actor_id="citizen-0", vote_id="vote-x", choice="yes"), "unknown_entity"),
        (ProposeVote(actor_id="citizen-1", kind="market_tax", value=500), "bad_params"),
    ]
    for action, code in cases:
        with pytest.raises(InvalidAction) as error:
            Engine(state).apply(action)
        assert error.value.code == code
    state, _ = ticks(state, 3)
    with pytest.raises(InvalidAction) as error:
        Engine(state).apply(CastVote(actor_id="citizen-1", vote_id=vid, choice="yes"))
    assert error.value.code == "bad_params"
    # One vote may open every 10 days.
    with pytest.raises(InvalidAction) as error:
        Engine(state).apply(ProposeVote(actor_id="citizen-1", kind="market_tax", value=500))
    assert error.value.code == "rate_limited"
    state, _ = ticks(state, 7)
    assert state.tick == 10
    state, second = open_vote(state, "market_tax", 500)
    assert state.votes[second].opens_tick == 10


@pytest.mark.parametrize(
    "kind,value",
    [("market_tax", 10001), ("market_tax", 0), ("min_wage", 0), ("bread_price_cap", 0)],
)
def test_proposals_must_change_a_valid_policy(kind, value):
    with pytest.raises(InvalidAction) as error:
        Engine(initial_world()).apply(ProposeVote(actor_id="citizen-0", kind=kind, value=value))
    assert error.value.code == "bad_params"


def test_bread_price_cap_lowers_prices_and_blocks_raises():
    state, vid = open_vote(initial_world(), "bread_price_cap", 400)
    state = apply(state, CastVote(actor_id="citizen-1", vote_id=vid, choice="yes"))
    state, events = ticks(state, 3)
    assert state.policies.bread_price_cap == 400
    assert state.buildings["bakery"].prices["bread"] == 400
    lowered = [e for e in events if e.type == "price_changed"]
    assert (lowered[0].payload.old_price, lowered[0].payload.new_price) == (500, 400)
    with pytest.raises(InvalidAction) as error:
        Engine(state).apply(
            SetPrice(actor_id="citizen-1", building_id="bakery", resource="bread", price=401)
        )
    assert error.value.code == "bad_params"
    apply(state, SetPrice(actor_id="citizen-1", building_id="bakery", resource="wheat", price=900))


def test_market_tax_is_shared_equally_and_conserves_money(monkeypatch):
    # Isolate circulation from newcomer starting money and upgrade construction costs.
    monkeypatch.setattr(Engine, "_growth_rules", lambda self: None)
    state = initial_world()
    state.policies.market_tax_bps = 1000
    before = total_money(state)
    buy = Buy(
        actor_id="citizen-0", building_id="bakery", resource="bread", quantity=2, max_unit_price=500
    )
    result = Engine(state).apply(buy)
    after = result.state
    assert total_money(after) == before
    # 10% of 1,000 is 100; 7 citizens get 14 each and the 2-cent remainder stays with the seller.
    tax = next(e for e in result.events if e.type == "tax_collected")
    assert (tax.payload.amount, tax.payload.per_citizen) == (98, 14)
    assert after.buildings["bakery"].cash == state.buildings["bakery"].cash + 1000 - 98
    assert after.citizens["citizen-0"].money == state.citizens["citizen-0"].money - 1000 + 14
    assert after.citizens["citizen-6"].money == state.citizens["citizen-6"].money + 14
    for _ in range(15):
        after = Engine(after).tick().state
    assert total_money(after) == before


def test_policies_also_bind_businesses_founded_later():
    state = initial_world()
    state.policies.min_wage = 300
    state = apply(
        state, FoundBusiness(actor_id="citizen-5", plot_id="plot-3", kind="bakery", capital=5000)
    )
    new = next(b for b in state.buildings.values() if b.owner_id == "citizen-5")
    assert new.wage == 300
    state, _ = ticks(state, 1)
    assert state.buildings[new.id].wage == 300


def test_vote_ids_are_stable_and_ticks_reproducible():
    state, vid = open_vote(initial_world())
    assert vid == "vote-main-1"
    assert Engine(state).tick() == Engine(state).tick()


def test_worlds_saved_before_votes_still_load():
    data = initial_world().model_dump()
    del data["votes"], data["policies"]
    state = WorldState.model_validate(data)
    assert state.votes == {} and state.policies.min_wage == 0


def test_role_matrix_covers_every_action_once():
    union = get_args(get_args(AgentAction)[0])
    types = {cls.model_fields["type"].default for cls in union}
    commoner, owner = roles()
    owner_actions = [p.action for p in owner.permissions]
    assert sorted(owner_actions) == sorted(types)
    assert {p.action for p in commoner.permissions} < set(owner_actions)
    assert "set_wage" not in {p.action for p in commoner.permissions}
    assert next(p for p in owner.permissions if p.action == "vote").supported
