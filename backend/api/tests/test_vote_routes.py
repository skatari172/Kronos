"""Roles, influence, and town-vote routes map onto engine actions and derived reads."""

import pytest
from fastapi.testclient import TestClient
from kronos.config import Settings
from kronos.main import create_app
from route_helpers import resolve


@pytest.fixture
def client(tmp_path, route_only):
    with TestClient(
        create_app(Settings(database_url=f"sqlite:///{tmp_path / 'votes.db'}"))
    ) as client:
        yield client


def body(actor_id, sequence, **fields):
    return {"branch_id": "main", "expected_sequence": sequence, "actor_id": actor_id, **fields}


def test_roles_and_influence_reads(client):
    roles = client.get("/api/roles").json()
    assert [r["role"] for r in roles] == ["commoner", "business_owner"]
    owner_scopes = {p["action"]: p["scope"] for p in roles[1]["permissions"]}
    assert owner_scopes["set_wage"] == "own_business" and owner_scopes["vote"] == "any"
    breakdown = client.get("/api/agents/citizen-1/influence").json()
    assert breakdown["wealth_share"] == 3404 and breakdown["trust_from_others"] == 5000
    assert client.get("/api/agents/citizen-1").json()["influence"] == breakdown["influence"]
    assert client.get("/api/agents/missing/influence").status_code == 404


def test_propose_ballot_and_tally_through_routes(client):
    proposed = resolve(
        client,
        client.post(
            "/api/votes",
            json=body("citizen-6", 0, kind="min_wage", value=300, rationale="Bread costs too much"),
        ),
    ).json()
    assert proposed["status"] == "applied"
    [view] = client.get("/api/votes?status=open").json()
    vote_id = view["vote"]["id"]
    assert view["vote"]["proposer_id"] == "citizen-6" and view["tally"]["ballots"] == 0
    cast = resolve(
        client,
        client.post(
            f"/api/votes/{vote_id}/ballot",
            json=body("citizen-1", proposed["sequence"], choice="yes"),
        ),
    ).json()
    assert cast["status"] == "applied"
    tally = client.get("/api/votes?status=open").json()[0]["tally"]
    influence = client.get("/api/agents/citizen-1/influence").json()["influence"]
    assert tally == {"yes_weight": influence, "no_weight": 0, "yes_share": 10000, "ballots": 1}
    again = resolve(
        client,
        client.post(
            "/api/votes", json=body("citizen-0", cast["sequence"], kind="market_tax", value=500)
        ),
    ).json()
    assert (again["status"], again["error"]) == ("rejected", "bad_params")
    assert client.get("/api/votes?status=passed").json() == []
    assert client.get("/api/votes?status=bogus").status_code == 422
