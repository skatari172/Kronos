"""Invention routes map one-to-one onto engine actions and return ActionResult."""

import pytest
from fastapi.testclient import TestClient
from kronos.config import Settings
from kronos.main import create_app
from route_helpers import resolve


@pytest.fixture
def client(tmp_path, route_only):
    with TestClient(
        create_app(Settings(database_url=f"sqlite:///{tmp_path / 'inventions.db'}"))
    ) as client:
        yield client


def command(actor_id, sequence, **fields):
    return {"branch_id": "main", "expected_sequence": sequence, "actor_id": actor_id, **fields}


def test_invention_reads(client):
    listing = client.get("/api/inventions").json()
    assert [i["id"] for i in listing] == ["crop_rotation", "water_mill"]
    assert client.get("/api/inventions/water_mill").json()["cost"] == 2500
    assert client.get("/api/inventions/missing").status_code == 404
    assert client.get("/api/inventions/license-offers").json() == []


def test_research_license_and_adopt_through_routes(client):
    seq = 0

    def post(path, body):
        nonlocal seq
        result = resolve(client, client.post(f"/api/inventions{path}", json=body)).json()
        seq = result["sequence"]
        return result

    locked = post("/crop_rotation/adopt", command("citizen-0", seq, building_id="farm"))
    assert (locked["status"], locked["error"]) == ("rejected", "invention_locked")
    funded = post("/crop_rotation/research", command("citizen-0", seq, mode="money", amount=1500))
    assert funded["status"] == "applied"
    invention = client.get("/api/inventions/crop_rotation").json()
    assert invention["unlocked"] and invention["owner_id"] == "citizen-0"
    timed = post("/water_mill/research", command("citizen-3", seq, mode="time", ticks=3))
    assert timed["status"] == "applied"
    assert (
        client.get("/api/agents/citizen-3").json()["citizen"]["research_until_tick"]
        == timed["tick"] + 3
    )

    offer = post(
        "/crop_rotation/license",
        command("citizen-0", seq, recipient_id="citizen-1", fee=300),
    )
    assert offer["status"] == "applied"
    [pending] = client.get("/api/inventions/license-offers?recipient=citizen-1").json()
    accepted = post(
        f"/license-offers/{pending['id']}/respond", command("citizen-1", seq, accept=True)
    )
    assert accepted["status"] == "applied"
    assert client.get("/api/agents/citizen-1").json()["citizen"]["money"] == 22000 - 300
    adopted = post("/crop_rotation/adopt", command("citizen-0", seq, building_id="farm"))
    assert adopted["status"] == "applied"
    assert client.get("/api/inventions/crop_rotation").json()["adopters"] == ["farm"]


def test_research_request_validates_mode_fields(client):
    bad = command("citizen-0", 0, mode="money", ticks=3)
    assert (
        resolve(client, client.post("/api/inventions/water_mill/research", json=bad)).status_code
        == 422
    )
