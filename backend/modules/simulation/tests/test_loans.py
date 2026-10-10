"""Loans: offer, consent, flat interest, repayment, and the daily default step."""

import pytest
from kronos_sim.engine import Engine, InvalidAction
from kronos_sim.models import Lend, Relationship, Repay, RespondLoan, WorldState
from kronos_sim.queries import observe
from kronos_sim.seed import initial_world

MEMORY_FIELDS = {"memories", "memory_summary", "memory_tally"}


def holdings(citizens):
    """Citizens without their memories: what an event may not change when nothing moves."""
    return {cid: c.model_dump(exclude=MEMORY_FIELDS) for cid, c in citizens.items()}


# Ada (citizen-2, 16,000 cents) lends to Finn (citizen-6, 550 cents): the Marco -> Teo story.


def offer_loan(state, principal=6000, rate_bps=1000, due_tick=3):
    result = Engine(state).apply(
        Lend(
            actor_id="citizen-2",
            recipient_id="citizen-6",
            principal=principal,
            rate_bps=rate_bps,
            due_tick=due_tick,
            rationale="Help Finn through the winter",
        )
    )
    return result, next(iter(result.state.loans))


def accept(state, loan_id, actor_id="citizen-6"):
    return Engine(state).apply(RespondLoan(actor_id=actor_id, loan_id=loan_id, accept=True))


def code_of(state, action):
    with pytest.raises(InvalidAction) as error:
        Engine(state).apply(action)
    return error.value.code


def test_loan_offer_moves_no_money_until_the_borrower_accepts():
    state = initial_world()
    offered, loan_id = offer_loan(state)
    loan = offered.state.loans[loan_id]
    assert loan_id == "loan-main-1"
    assert (loan.status, loan.amount_owed, loan.amount_repaid) == ("offered", 6600, 0)
    assert holdings(offered.state.citizens) == holdings(state.citizens)
    assert [e.type for e in offered.events] == ["loan_offered"]
    assert offered.events[0].rationale == "Help Finn through the winter"
    assert [x.id for x in observe(offered.state, "citizen-6").loans] == [loan_id]
    lender_try = RespondLoan(actor_id="citizen-2", loan_id=loan_id, accept=True)
    assert code_of(offered.state, lender_try) == "insufficient_authority"
    accepted = accept(offered.state, loan_id)
    assert accepted.state.loans[loan_id].status == "active"
    assert accepted.state.citizens["citizen-2"].money == 10000
    assert accepted.state.citizens["citizen-6"].money == 6550
    assert [e.type for e in accepted.events] == ["loan_accepted", "transaction_completed"]
    assert (
        code_of(accepted.state, RespondLoan(actor_id="citizen-6", loan_id=loan_id, accept=False))
        == "bad_params"
    )


def test_declined_loan_and_lender_funds_are_rechecked_on_accept():
    offered, loan_id = offer_loan(initial_world())
    declined = Engine(offered.state).apply(
        RespondLoan(actor_id="citizen-6", loan_id=loan_id, accept=False)
    )
    assert declined.state.loans[loan_id].status == "declined"
    assert holdings(declined.state.citizens) == holdings(offered.state.citizens)
    assert observe(declined.state, "citizen-6").loans == []
    broke = offered.state.model_copy(deep=True)
    broke.citizens["citizen-2"].money = 100
    action = RespondLoan(actor_id="citizen-6", loan_id=loan_id, accept=True)
    assert code_of(broke, action) == "insufficient_funds"
    assert code_of(offered.state, action.model_copy(update={"loan_id": "x"})) == "unknown_entity"


@pytest.mark.parametrize(
    "fields,code",
    [
        ({"recipient_id": "citizen-2"}, "bad_params"),
        ({"recipient_id": "nobody"}, "unknown_entity"),
        ({"principal": 999999}, "insufficient_funds"),
    ],
)
def test_loan_offer_rules(fields, code):
    base = dict(actor_id="citizen-2", recipient_id="citizen-6", principal=1000, rate_bps=0)
    action = Lend(**{**base, "due_tick": 2, **fields})
    assert code_of(initial_world(), action) == code


def test_due_tick_must_be_in_the_future():
    state = initial_world()
    state.tick = 5
    action = Lend(
        actor_id="citizen-2", recipient_id="citizen-6", principal=1000, rate_bps=0, due_tick=5
    )
    assert code_of(state, action) == "bad_params"


def test_interest_is_flat_and_rounds_down_to_whole_cents():
    offered, loan_id = offer_loan(initial_world(), principal=999, rate_bps=1250)
    assert offered.state.loans[loan_id].amount_owed == 999 + 124


def test_partial_and_full_repayment_with_interest():
    offered, loan_id = offer_loan(initial_world())
    state = accept(offered.state, loan_id).state
    for actor, amount, code in [
        ("citizen-2", 100, "insufficient_authority"),
        ("citizen-6", 6601, "bad_params"),
        ("citizen-6", 6600, "insufficient_funds"),
    ]:
        assert code_of(state, Repay(actor_id=actor, loan_id=loan_id, amount=amount)) == code
    missing = Repay(actor_id="citizen-6", loan_id="loan-x", amount=1)
    assert code_of(state, missing) == "unknown_entity"
    partial = Engine(state).apply(Repay(actor_id="citizen-6", loan_id=loan_id, amount=6000))
    assert partial.state.loans[loan_id].status == "active"
    assert partial.state.loans[loan_id].amount_repaid == 6000
    assert [e.type for e in partial.events] == ["loan_repaid", "transaction_completed"]
    assert partial.events[0].payload.amount == 6000
    funded = partial.state.model_copy(deep=True)
    funded.citizens["citizen-6"].money = 1000
    final = Engine(funded).apply(Repay(actor_id="citizen-6", loan_id=loan_id, amount=600))
    assert final.state.loans[loan_id].status == "repaid"
    assert final.state.citizens["citizen-2"].money == 10000 + 6600
    assert final.state.citizens["citizen-6"].money == 400
    done = Repay(actor_id="citizen-6", loan_id=loan_id, amount=1)
    assert code_of(final.state, done) == "bad_params"


def test_offered_loan_cannot_be_repaid():
    offered, loan_id = offer_loan(initial_world())
    action = Repay(actor_id="citizen-6", loan_id=loan_id, amount=1)
    assert code_of(offered.state, action) == "bad_params"


def test_missed_due_date_defaults_once_with_trust_and_reputation_penalty():
    offered, loan_id = offer_loan(initial_world(), due_tick=1)
    state = accept(offered.state, loan_id).state
    on_time = Engine(state).tick()  # tick 1 == due_tick: still active
    assert on_time.state.loans[loan_id].status == "active"
    late = Engine(on_time.state).tick()  # tick 2 > due_tick
    assert late.state.loans[loan_id].status == "defaulted"
    lender = late.state.citizens["citizen-2"]
    assert [(r.citizen_id, r.trust) for r in lender.relationships] == [("citizen-6", -30)]
    assert late.state.citizens["citizen-6"].reputation == 45
    default = next(e for e in late.events if e.type == "loan_defaulted")
    assert (default.payload.borrower_reputation, default.payload.lender_trust) == (45, -30)
    assert default.actor_id == "citizen-6"
    changed = next(e for e in late.events if e.type == "relationship_changed")
    assert changed.causal_refs == [default.id] and changed.payload.recipient_id == "citizen-2"
    assert [x.status for x in observe(late.state, "citizen-6").loans] == ["defaulted"]
    again = Engine(late.state).tick()
    assert not [e for e in again.events if e.type == "loan_defaulted"]
    assert again.state.citizens["citizen-6"].reputation == 45
    funded = again.state.model_copy(deep=True)
    funded.citizens["citizen-6"].money = 7000
    repaid = Engine(funded).apply(Repay(actor_id="citizen-6", loan_id=loan_id, amount=6600))
    assert repaid.state.loans[loan_id].status == "repaid"


def test_default_penalties_clamp_and_reuse_existing_relationship():
    offered, loan_id = offer_loan(initial_world(), due_tick=1)
    state = accept(offered.state, loan_id).state
    state.tick = 1
    state.citizens["citizen-6"].reputation = 3
    state.citizens["citizen-2"].relationships = [Relationship(citizen_id="citizen-6", trust=-90)]
    late = Engine(state).tick()
    assert late.state.citizens["citizen-6"].reputation == 0
    assert late.state.citizens["citizen-2"].relationships[0].trust == -100
    assert len(late.state.citizens["citizen-2"].relationships) == 1


def test_unanswered_offer_expires_on_its_due_tick():
    offered, loan_id = offer_loan(initial_world(), due_tick=1)
    expired = Engine(offered.state).tick()
    assert expired.state.loans[loan_id].status == "expired"
    assert any(e.type == "loan_expired" for e in expired.events)
    action = RespondLoan(actor_id="citizen-6", loan_id=loan_id, accept=True)
    assert code_of(expired.state, action) == "bad_params"


def test_worlds_saved_before_loans_still_load():
    data = initial_world().model_dump()
    del data["loans"]
    for citizen in data["citizens"].values():
        del citizen["reputation"]
    state = WorldState.model_validate(data)
    assert state.loans == {} and state.citizens["citizen-0"].reputation == 50
