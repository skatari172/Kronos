"""Loan convenience routes map to lend / respond_loan / repay agent actions."""

import pytest
from fastapi.testclient import TestClient
from kronos.config import Settings
from kronos.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(Settings(database_url=f"sqlite:///{tmp_path / 'loans.db'}"))
    ) as client:
        yield client


def command(actor_id, sequence, **fields):
    return {"branch_id": "main", "expected_sequence": sequence, "actor_id": actor_id, **fields}


def money(client, citizen_id):
    return client.get(f"/api/agents/{citizen_id}").json()["citizen"]["money"]


def test_loan_lifecycle_through_routes(client):
    offer = client.post(
        "/api/loans",
        json=command(
            "citizen-2",
            0,
            borrower_id="citizen-6",
            principal=6000,
            rate_bps=1000,
            due_tick=5,
            rationale="Help Finn",
        ),
    ).json()
    assert offer["status"] == "applied"
    [loan] = client.get("/api/loans?citizen_id=citizen-6&status=offered").json()
    assert (loan["lender_id"], loan["amount_owed"]) == ("citizen-2", 6600)
    assert client.get("/api/loans?citizen_id=citizen-0").json() == []
    assert client.get(f"/api/loans/{loan['id']}").json() == loan
    assert client.get("/api/loans/missing").status_code == 404
    observation = client.get("/api/agents/citizen-6/observation").json()
    assert [x["id"] for x in observation["loans"]] == [loan["id"]]

    seq = offer["sequence"]
    stolen = client.post(
        f"/api/loans/{loan['id']}/respond", json=command("citizen-2", seq, accept=True)
    ).json()
    assert (stolen["status"], stolen["error"]) == ("rejected", "insufficient_authority")
    seq = stolen["sequence"]
    accepted = client.post(
        f"/api/loans/{loan['id']}/respond", json=command("citizen-6", seq, accept=True)
    ).json()
    assert accepted["status"] == "applied"
    assert (money(client, "citizen-2"), money(client, "citizen-6")) == (10000, 6550)

    seq = accepted["sequence"]
    too_much = client.post(
        f"/api/loans/{loan['id']}/repay", json=command("citizen-6", seq, amount=7000)
    ).json()
    assert too_much["error"] == "bad_params"
    seq = too_much["sequence"]
    paid = client.post(
        f"/api/loans/{loan['id']}/repay", json=command("citizen-6", seq, amount=6550)
    ).json()
    assert paid["status"] == "applied"
    current = client.get(f"/api/loans/{loan['id']}").json()
    assert (current["status"], current["amount_repaid"]) == ("active", 6550)
    assert money(client, "citizen-2") == 16550
    assert (
        client.post(
            f"/api/loans/{loan['id']}/repay", json=command("citizen-6", seq, amount=0)
        ).status_code
        == 422
    )


def test_loan_routes_are_tagged(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/api/loans"]["get"]["tags"] == ["World"]
    assert paths["/api/loans"]["post"]["tags"] == ["Agent tools"]
    assert paths["/api/loans/{loan_id}/respond"]["post"]["tags"] == ["Agent tools"]
    assert paths["/api/loans/{loan_id}/repay"]["post"]["tags"] == ["Agent tools"]
