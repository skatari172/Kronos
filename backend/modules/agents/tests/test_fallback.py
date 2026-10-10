import asyncio

import pytest
from kronos_agents.fallback import UtilityPolicy
from kronos_agents.provider import AgentService, MockProvider, ProviderError
from kronos_sim.engine import Engine, InvalidAction
from kronos_sim.models import AgentAction, GoalWeights, Loan, Relationship, TradeBundle, TradeOffer
from kronos_sim.queries import observe
from kronos_sim.seed import initial_world
from pydantic import TypeAdapter

ACTION = TypeAdapter(AgentAction)
policy = UtilityPolicy()


def observation(citizen_id="citizen-6", world=None, **changes):
    world = world or initial_world()
    citizen = world.citizens[citizen_id]
    for key, value in changes.items():
        setattr(citizen, key, value)
    return observe(world, citizen_id)


def weights(**kw):
    return GoalWeights(**{"wealth": 0, "influence": 0, "safety": 0, "reputation": 0, **kw})


class Failing:
    calls = 0

    async def complete(self, task, observation):
        self.calls += 1
        raise ProviderError("provider is down")


class Slow:
    async def complete(self, task, observation):
        await asyncio.sleep(1)
        return "{}"


class Impostor:
    async def complete(self, task, observation):
        return '{"type": "consume", "actor_id": "citizen-0"}'


def test_hunger_dominates_every_goal():
    obs = observation(hunger=80, goal_weights=weights(influence=100))
    assert policy.choose(obs).type == "consume"
    world = initial_world()
    world.citizens["citizen-6"].inventory.bread = 0
    obs = observation(world=world, hunger=75, goal_weights=weights(wealth=100))
    action = policy.choose(obs)
    assert action.type == "buy" and action.building_id == "bakery"
    assert action.rationale.startswith("hunger:")


def test_safety_eats_when_mildly_hungry():
    assert policy.choose(observation(hunger=40, goal_weights=weights(safety=100))).type == "consume"


def test_wealth_applies_for_the_best_paid_opening():
    world = initial_world()
    world.buildings["farm"].wage = 200
    action = policy.choose(observation(world=world, hunger=0, goal_weights=weights(wealth=100)))
    assert action.type == "apply_job" and action.building_id == "farm"
    assert action.rationale.startswith("wealth:")


def test_wealth_owner_lowers_price_of_piled_up_bread():
    world = initial_world()
    world.buildings["bakery"].inventory.bread = 40
    action = policy.choose(
        observation("citizen-1", world, hunger=0, goal_weights=weights(wealth=100))
    )
    assert action.type == "set_price" and action.price == 450


def test_wealth_accepts_only_profitable_affordable_trades():
    world = initial_world()

    def offer(oid, give, get):
        world.trade_offers[oid] = TradeOffer(
            id=oid,
            offerer_id="citizen-0",
            recipient_id="citizen-6",
            give=TradeBundle(**give),
            get=TradeBundle(**get),
            created_tick=0,
            expires_tick=2,
        )

    offer("t-bad", {"money": 100}, {"money": 400})
    offer("t-good", {"money": 900}, {"goods": {"bread": 1}})
    world.citizens["citizen-6"].employer_id = "market"  # No job to apply for.
    action = policy.choose(observation(world=world, hunger=0, goal_weights=weights(wealth=100)))
    assert action.type == "respond_trade" and action.offer_id == "t-good" and action.accept
    del world.trade_offers["t-good"]
    action = policy.choose(observation(world=world, hunger=0, goal_weights=weights(wealth=100)))
    assert action.type == "respond_trade" and action.offer_id == "t-bad" and not action.accept


def test_reputation_repays_debt_keeping_a_food_reserve():
    world = initial_world()
    world.loans["loan-1"] = Loan(
        id="loan-1",
        lender_id="citizen-0",
        borrower_id="citizen-5",
        principal=2000,
        rate_bps=1000,
        due_tick=2,
        amount_owed=2200,
        status="active",
    )
    obs = observation("citizen-5", world, hunger=0, goal_weights=weights(reputation=100))
    action = policy.choose(obs)
    assert action.type == "repay" and action.amount == 2200
    world.citizens["citizen-5"].money = 1500
    action = policy.choose(observe(world, "citizen-5"))
    assert action.type == "repay" and action.amount == 1500 - 2 * 500


def test_influence_befriends_the_least_close_neighbor():
    world = initial_world()
    world.citizens["citizen-6"].relationships = [
        Relationship(citizen_id=c, trust=30) for c in sorted(world.citizens) if c != "citizen-6"
    ]
    world.citizens["citizen-6"].relationships[2].trust = 5
    action = policy.choose(observation(world=world, hunger=0, goal_weights=weights(influence=100)))
    assert action.type == "interact" and action.kind == "befriend"
    assert action.recipient_id == "citizen-2"
    assert action.rationale.startswith("influence:")


def test_only_listed_actions_and_nothing_left_raises():
    obs = observation(hunger=80)
    obs.available_actions = ["communicate"]
    assert policy.choose(obs).type == "communicate"
    obs.available_actions = []
    with pytest.raises(ProviderError):
        policy.choose(obs)


@pytest.mark.parametrize("citizen_id", sorted(initial_world().citizens))
@pytest.mark.parametrize("hunger", [0, 30, 60, 90])
def test_deterministic_valid_and_own_actions(citizen_id, hunger):
    world = initial_world()
    rng = list(world.rng_state)
    obs = observation(citizen_id, world, hunger=hunger)
    first = policy.choose(obs)
    assert first == policy.choose(obs.model_copy(deep=True))
    assert first.actor_id == citizen_id
    assert ACTION.validate_python(first.model_dump()) == first
    for candidate in policy.rank(obs):
        assert ACTION.validate_python(candidate.action).actor_id == citizen_id
    assert world.rng_state == rng


def test_ties_break_by_action_order_then_target():
    world = initial_world()
    for oid in ("t-2", "t-1"):  # Inserted out of order; equal utility (both declined).
        world.trade_offers[oid] = TradeOffer(
            id=oid,
            offerer_id="citizen-0",
            recipient_id="citizen-6",
            give=TradeBundle(money=1),
            get=TradeBundle(money=5),
            created_tick=0,
            expires_tick=2,
        )
    world.citizens["citizen-6"].employer_id = "market"
    obs = observation(world=world, hunger=0, goal_weights=weights(wealth=100))
    ranked = policy.rank(obs)
    assert [c.target for c in ranked[:2]] == ["t-1", "t-2"]
    assert ranked[0].utility == ranked[1].utility
    assert policy.choose(obs).offer_id == "t-1"


@pytest.mark.parametrize("provider", [Failing(), Slow(), Impostor()])
def test_fallback_engages_when_the_provider_fails(provider):
    service = AgentService(provider, timeout=0.05, retries=0, fallback=UtilityPolicy())
    proposal = asyncio.run(service.proposal(observation(hunger=80)))
    assert proposal.source == "fallback"
    assert proposal.action.actor_id == "citizen-6" and proposal.action.type == "consume"
    assert proposal.action.rationale.startswith("[fallback] hunger:")
    # decide() keeps returning just the action.
    assert asyncio.run(service.decide(observation(hunger=80))) == proposal.action


def test_without_fallback_the_error_propagates():
    with pytest.raises(ProviderError):
        asyncio.run(AgentService(Failing(), retries=0).decide(observation()))


def test_provider_source_is_recorded():
    service = AgentService(MockProvider(), fallback=UtilityPolicy())
    proposal = asyncio.run(service.proposal(observation(hunger=60)))
    assert proposal.source == "mock" and proposal.action.rationale.startswith("[mock] ")


def test_thirty_days_on_fallback_keep_the_world_moving():
    """Every citizen decides every day through a dead provider; the fallback keeps going."""
    service = AgentService(Failing(), retries=0, fallback=UtilityPolicy())
    world = initial_world()
    applied = rejected = 0
    kinds = set()
    for _ in range(30):
        for citizen_id in sorted(world.citizens):
            proposal = asyncio.run(service.proposal(observe(world, citizen_id)))
            assert proposal.source == "fallback"
            assert proposal.action.actor_id == citizen_id
            kinds.add(proposal.action.type)
            try:
                world = Engine(world).apply(proposal.action).state
                applied += 1
            except InvalidAction as exc:
                world = Engine(world).reject(proposal.action, exc).state
                rejected += 1
        world = Engine(world).tick([]).state
    assert world.tick == 30
    assert applied >= 4 * rejected, (applied, rejected)
    assert len(kinds) >= 3, kinds
