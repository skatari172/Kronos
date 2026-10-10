"""Relationship reads and the interact route map to the engine's interact action."""

import pytest
from fastapi.testclient import TestClient
from kronos.config import Settings
from kronos.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(Settings(database_url=f"sqlite:///{tmp_path / 'relationships.db'}"))
    ) as client:
        yield client


def interact(client, actor, sequence, **fields):
    body = {"branch_id": "main", "expected_sequence": sequence, **fields}
    return client.post(f"/api/agents/{actor}/interact", json=body)


def test_interact_round_trip(client):
    seq = client.get("/api/world").json()["sequence"]
    gift = interact(
        client, "citizen-0", seq, target_id="citizen-6", kind="gift", amount=500, rationale="Help"
    ).json()
    assert gift["status"] == "applied" and len(gift["event_ids"]) == 3
    assert client.get("/api/agents/citizen-6").json()["citizen"]["money"] == 1050

    [tie] = client.get("/api/agents/citizen-6/relationships").json()
    assert tie["citizen_id"] == "citizen-0" and tie["name"] == "Elena"
    assert (tie["trust"], tie["grudge"], tie["type"], tie["known"]) == (15, 0, "acquaintance", True)

    pair = client.get("/api/relationships/citizen-0/citizen-6").json()
    assert pair["b_to_a"]["trust"] == 15
    assert pair["a_to_b"]["trust"] == 0 and pair["a_to_b"]["last_interaction_tick"] == 0
    assert client.get("/api/relationships/citizen-0/nobody").status_code == 404
    assert client.get("/api/agents/nobody/relationships").status_code == 404

    ally = interact(
        client, "citizen-6", gift["sequence"], target_id="citizen-0", kind="ally"
    ).json()
    assert (ally["status"], ally["error"]) == ("rejected", "trust_too_low")
    again = interact(
        client, "citizen-0", ally["sequence"], target_id="citizen-6", kind="insult"
    ).json()
    assert again["error"] == "rate_limited"
    observation = client.get("/api/agents/citizen-6/observation").json()
    assert [t["citizen_id"] for t in observation["ties"]] == ["citizen-0"]


@pytest.mark.parametrize(
    "fields",
    [
        {"target_id": "citizen-6", "kind": "gift"},
        {"target_id": "citizen-6", "kind": "insult", "amount": 100},
        {"target_id": "citizen-6", "kind": "hug"},
    ],
)
def test_interact_body_is_validated(client, fields):
    assert interact(client, "citizen-0", 0, **fields).status_code == 422


def test_relationship_routes_are_tagged(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/api/agents/{citizen_id}/interact"]["post"]["tags"] == ["Agent tools"]
    assert paths["/api/agents/{citizen_id}/relationships"]["get"]["tags"] == ["World"]
    assert paths["/api/relationships/{a_id}/{b_id}"]["get"]["tags"] == ["World"]
