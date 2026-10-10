import json

from kronos_sim import models as m
from kronos_sim.engine import SUPPORTED_ACTIONS, Engine
from kronos_sim.queries import OBSERVED_JOBS, OBSERVED_NEIGHBORS, observe
from kronos_sim.seed import initial_world

OWNER_ACTIONS = {"set_price", "set_wage", "close_business", "upgrade_building", "produce"}
# ~1,000-1,300 tokens of JSON (A5). Raised from 2,400 when observations gained bread stock
# and owned-business caps; recent events (up to 8, passed by the service) come on top.
MAX_OBSERVATION_CHARS = 4000


def crowded_world(citizens: int = 30) -> m.WorldState:
    world = initial_world(42)
    for _ in range(60):
        world = Engine(world).tick().state
    while len(world.citizens) < citizens:
        request = m.SpawnCitizenRequest(
            branch_id=world.branch_id,
            expected_sequence=world.sequence,
            name=f"Visitor {len(world.citizens)}",
            occupation="Laborer",
            money=500,
            plot_id=sorted(world.plots)[0],
        )
        world = Engine(world).spawn(request).state
    return world


def test_observations_stay_within_the_token_budget():
    world = crowded_world()
    for citizen_id in world.citizens:
        observation = observe(world, citizen_id)
        size = len(json.dumps(observation.model_dump(mode="json")))
        assert size <= MAX_OBSERVATION_CHARS, (citizen_id, size)
        assert len(observation.neighbors) <= OBSERVED_NEIGHBORS
        assert len(observation.open_jobs) <= OBSERVED_JOBS
        # The full tie list and raw memory counts are summarised elsewhere.
        assert observation.citizen.relationships == []
        assert observation.citizen.memory_tally == {}


def test_neighbors_put_strongest_ties_first():
    world = crowded_world()
    observation = observe(world, "citizen-0")
    tie_ids = [t.citizen_id for t in observation.ties]
    assert list(observation.neighbors)[: len(tie_ids)] == tie_ids


def test_menu_follows_role_and_state():
    world = initial_world(42)
    owner, commoner = observe(world, "citizen-0"), observe(world, "citizen-6")
    assert OWNER_ACTIONS <= set(owner.available_actions)
    assert not OWNER_ACTIONS & set(commoner.available_actions)
    # Finn is unemployed: he may apply, not quit, and sees the openings.
    assert "apply_job" in commoner.available_actions
    assert "quit_job" not in commoner.available_actions
    assert commoner.open_jobs
    # Elena has a job, so openings are left out of her prompt.
    assert "apply_job" not in owner.available_actions and owner.open_jobs == []
    # Nothing to answer yet.
    for action in ("respond_loan", "respond_trade", "respond_license", "repay", "vote"):
        assert action not in commoner.available_actions
    # Menus keep the engine's order and never invent types.
    assert [a for a in SUPPORTED_ACTIONS if a in commoner.available_actions] == (
        commoner.available_actions
    )


def test_menu_opens_when_there_is_something_to_answer():
    world = initial_world(42)
    lend = m.Lend(
        actor_id="citizen-0", recipient_id="citizen-6", principal=1000, rate_bps=500, due_tick=10
    )
    world = Engine(world).apply(lend).state
    assert "respond_loan" in observe(world, "citizen-6").available_actions
    assert "respond_loan" not in observe(world, "citizen-5").available_actions


def test_consume_needs_bread():
    world = initial_world(42)
    world.citizens["citizen-6"].inventory.bread = 0
    assert "consume" not in observe(world, "citizen-6").available_actions
    world.citizens["citizen-6"].inventory.bread = 1
    assert "consume" in observe(world, "citizen-6").available_actions
