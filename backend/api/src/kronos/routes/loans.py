"""Loan reads and convenience routes. Each mutation is one agent action.

The acting citizen is body.actor_id (the lender to offer, the borrower to respond or repay);
results and logged rejections match POST /api/agents/{id}/actions.
"""

from fastapi import APIRouter
from kronos_sim import models as m
from kronos_sim.queries import loans as list_loans

from kronos.dependencies import ServiceDependency

router = APIRouter(prefix="/api/loans")


async def submit(service, body: m.LoanCommand, action: m.AgentAction) -> m.ActionResult:
    request = m.ActionRequest(
        branch_id=body.branch_id, expected_sequence=body.expected_sequence, action=action
    )
    return await service.submit_agent_action(request, body.actor_id)


def common(body: m.LoanCommand) -> dict:
    return {"actor_id": body.actor_id, "rationale": body.rationale}


@router.get("", response_model=list[m.Loan], tags=["World"], summary="List loans")
async def loans(
    service: ServiceDependency, citizen_id: str | None = None, status: m.LoanStatus | None = None
):
    """Filter by a citizen on either side of the loan (lender or borrower) and by status."""
    async with service.lock:
        return list_loans(service.state, citizen_id, status)


@router.get("/{loan_id}", response_model=m.Loan, tags=["World"], summary="Read one loan")
async def loan(loan_id: str, service: ServiceDependency):
    async with service.lock:
        found = service.state.loans.get(loan_id)
        if found is None:
            raise KeyError("Unknown loan")
        return found.model_copy(deep=True)


@router.post("", response_model=m.ActionResult, tags=["Agent tools"], summary="Offer a loan")
async def offer(body: m.LoanOfferRequest, service: ServiceDependency):
    """Creates an offer only; no money moves until the borrower accepts.

    Owed = principal + principal * rate_bps // 10000 (flat per loan, integer cents).
    """
    action = m.Lend(
        **common(body),
        recipient_id=body.borrower_id,
        principal=body.principal,
        rate_bps=body.rate_bps,
        due_tick=body.due_tick,
    )
    return await submit(service, body, action)


@router.post(
    "/{loan_id}/respond",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Accept or decline a loan offer (borrower only)",
)
async def respond(loan_id: str, body: m.LoanResponseRequest, service: ServiceDependency):
    """Accepting re-checks the lender's funds and moves the principal to the borrower."""
    action = m.RespondLoan(**common(body), loan_id=loan_id, accept=body.accept)
    return await submit(service, body, action)


@router.post(
    "/{loan_id}/repay",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Repay part or all of a loan (borrower only)",
)
async def repay(loan_id: str, body: m.LoanRepayRequest, service: ServiceDependency):
    """Partial payments are allowed; the amount may not exceed what is still owed."""
    action = m.Repay(**common(body), loan_id=loan_id, amount=body.amount)
    return await submit(service, body, action)
