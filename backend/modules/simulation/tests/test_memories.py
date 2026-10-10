"""Event-derived memories: salient lines, routine aggregation, folding and the summary."""

from kronos_sim.engine import MEMORY_WINDOW, SUMMARY_MAX, Engine, InvalidAction, remember
from kronos_sim.models import (
    Buy,
    Communicate,
    Fire,
    Lend,
    SetWage,
    WorldState,
)
from kronos_sim.queries import observe
from kronos_sim.seed import initial_world


def run(state, days):
    for _ in range(days):
        state = Engine(state).tick().state
    return state


def test_routine_wages_and_meals_aggregate_into_the_summary_not_the_window():
    state = initial_world()
    later = run(state, 6)
    rowan = later.citizens["citizen-3"]  # Farmhand at the farm, paid every day.
    assert rowan.memory_tally["wage_days"] == 6
    assert rowan.memory_tally["wage_cents"] == 6 * 150
    assert rowan.memory_tally["meals"] >= 1
    assert rowan.memory_summary.startswith("Earlier: earned 900 cents in wages over 6 days")
    assert "ate " in rowan.memory_summary
    assert not any("wage" in line.lower() for line in rowan.memories)
    for citizen in later.citizens.values():
        assert len(citizen.memories) <= MEMORY_WINDOW
        assert len(citizen.memory_summary) <= SUMMARY_MAX


def test_purchases_are_counted_with_their_cost():
    state = initial_world()
    result = Engine(state).apply(
        Buy(
            actor_id="citizen-6",
            building_id="bakery",
            resource="bread",
            quantity=1,
            max_unit_price=500,
        )
    )
    finn = result.state.citizens["citizen-6"]
    assert finn.memories == []
    assert finn.memory_tally == {"purchases": 1, "spent_cents": 500}
    assert finn.memory_summary == "Earlier: bought goods 1 time for 500 cents"


def test_overflow_folds_oldest_lines_by_category_and_repeats_collapse():
    citizen = initial_world().citizens["citizen-6"]
    remember(citizen, "Rejected buy: Not enough stock")
    remember(citizen, "Rejected buy: Not enough stock")
    assert citizen.memories == ["Rejected buy: Not enough stock (x2)"]
    remember(citizen, "Ada: Hello")
    for i in range(MEMORY_WINDOW):
        remember(citizen, f"Event {i}")
    assert len(citizen.memories) == MEMORY_WINDOW
    assert citizen.memories[0] == "Event 0"
    assert citizen.memory_tally == {"rejections": 2, "messages": 1}
    assert citizen.memory_summary == "Earlier: 2 rejected actions; 1 message"
    remember(citizen, "One more")
    assert citizen.memory_tally["notes"] == 1
    assert citizen.memory_summary.endswith("1 older event")


def test_messages_are_remembered_once_by_each_side_without_rng():
    state = initial_world()
    result = Engine(state).apply(
        Communicate(actor_id="citizen-0", recipient_id="citizen-6", message="Fresh bread today")
    )
    assert result.state.citizens["citizen-0"].memories == ["To Finn: Fresh bread today"]
    assert result.state.citizens["citizen-6"].memories == ["Elena: Fresh bread today"]
    assert result.state.rng_state == state.rng_state


def test_salient_job_and_wage_events_become_first_person_lines():
    state = initial_world()
    raised = Engine(state).apply(SetWage(actor_id="citizen-0", building_id="farm", wage=200))
    assert raised.state.citizens["citizen-3"].memories == [
        "My wage at Goldenfield Farm went from 150 to 200 cents"
    ]
    fired = Engine(raised.state).apply(
        Fire(actor_id="citizen-0", building_id="farm", citizen_id="citizen-3")
    )
    assert fired.state.citizens["citizen-3"].memories[-1] == "I lost my job at Goldenfield Farm"
    assert fired.state.citizens["citizen-0"].memories == []  # The owner acted; nothing to learn.


def test_loan_default_is_remembered_by_both_sides():
    state = initial_world()
    offered = Engine(state).apply(
        Lend(actor_id="citizen-2", recipient_id="citizen-6", principal=100, rate_bps=0, due_tick=1)
    )
    loan_id = next(iter(offered.state.loans))
    assert offered.state.citizens["citizen-6"].memories == [
        f"Ada offered me a 100-cent loan ({loan_id})"
    ]
    from kronos_sim.models import RespondLoan

    accepted = Engine(offered.state).apply(
        RespondLoan(actor_id="citizen-6", loan_id=loan_id, accept=True)
    )
    assert accepted.state.citizens["citizen-2"].memories == [f"Finn accepted my loan {loan_id}"]
    later = run(accepted.state, 2)
    assert f"I defaulted on loan {loan_id} from Ada" in later.citizens["citizen-6"].memories
    assert f"Finn defaulted on my loan {loan_id}" in later.citizens["citizen-2"].memories


def test_rejections_keep_the_reject_memory_and_are_not_duplicated():
    state = initial_world()
    action = Buy(
        actor_id="citizen-6",
        building_id="bakery",
        resource="bread",
        quantity=99,
        max_unit_price=500,
    )
    try:
        Engine(state).apply(action)
    except InvalidAction as error:
        rejected = Engine(state).reject(action, error)
    assert rejected.state.citizens["citizen-6"].memories == ["Rejected buy: Not enough stock"]


def test_newcomers_are_announced_and_the_summary_is_observed():
    state = run(initial_world(), 3)
    newcomer = next(c for c in state.citizens.values() if c.occupation == "Newcomer")
    assert "I arrived in the village" in newcomer.memories
    assert f"{newcomer.name} arrived in the village" in state.citizens["citizen-6"].memories
    seen = observe(state, "citizen-3").citizen
    assert seen.memory_summary == state.citizens["citizen-3"].memory_summary != ""


def test_worlds_saved_before_summaries_still_load():
    raw = initial_world().model_dump(mode="json")
    for citizen in raw["citizens"].values():
        citizen.pop("memory_summary")
        citizen.pop("memory_tally")
        citizen["memories"] = ["An old line"]
    world = WorldState.model_validate(raw)
    assert world.citizens["citizen-0"].memory_summary == ""
    assert world.citizens["citizen-0"].memory_tally == {}
    assert Engine(world).tick().state.citizens["citizen-0"].memories[0] == "An old line"


def test_memories_are_deterministic():
    first, second = run(initial_world(), 8), run(initial_world(), 8)
    assert {c.id: (c.memories, c.memory_summary) for c in first.citizens.values()} == {
        c.id: (c.memories, c.memory_summary) for c in second.citizens.values()
    }
