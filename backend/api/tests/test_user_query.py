"""Tests for user query endpoint and determined toolkit execution."""

import pytest
from fastapi.testclient import TestClient
from kronos.config import Settings
from kronos.main import create_app


@pytest.fixture
def client(tmp_path):
    config = Settings(database_url=f"sqlite:///{tmp_path / 'user_query.db'}")
    with TestClient(create_app(config)) as client:
        yield client


def test_user_query_interventions(client):
    # 1. Modify price intervention
    res = client.post("/api/user/query", json={"query": "Increase bread price by 40%"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert data["tool_call"]["endpoint"] == "/api/interventions"
    assert data["tool_call"]["tool"] == "modify_price"
    assert data["tool_call"]["parameters"]["percent"] == 40
    assert data["action_id"] is not None

    # 2. Grant money intervention to specific citizen
    res = client.post("/api/user/query", json={"query": "Give 5 coins to citizen-0"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert data["tool_call"]["endpoint"] == "/api/interventions"
    assert data["tool_call"]["tool"] == "grant_money"
    assert data["tool_call"]["parameters"]["amount"] == 500

    # 3. Adjust resource intervention
    res = client.post("/api/user/query", json={"query": "Harvest boom"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert data["tool_call"]["endpoint"] == "/api/interventions"
    assert data["tool_call"]["tool"] == "adjust_resource"

    # 4. Adjust hunger intervention
    res = client.post("/api/user/query", json={"query": "Feast"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert data["tool_call"]["endpoint"] == "/api/interventions"
    assert data["tool_call"]["tool"] == "adjust_hunger"

    # 5. Policy intervention
    res = client.post("/api/user/query", json={"query": "Set minimum wage to 2 coins"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert data["tool_call"]["endpoint"] == "/api/interventions"
    assert data["tool_call"]["tool"] == "set_policy"


def test_user_query_spawn_citizen(client):
    res = client.post(
        "/api/user/query",
        json={"query": "Spawn citizen Alice with occupation baker with 20 coins"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "applied"
    assert data["tool_call"]["endpoint"] == "/api/agents"
    assert data["tool_call"]["tool"] == "spawn_citizen"
    assert data["result"]["citizen_id"] is not None

    # Verify citizen actually exists in world
    world = client.get("/api/world").json()
    alice = [c for c in world["state"]["citizens"].values() if c["name"] == "Alice"]
    assert len(alice) == 1
    assert alice[0]["money"] == 2000
    assert alice[0]["occupation"] == "baker"


def test_user_query_simulation_tick(client):
    before = client.get("/api/world").json()
    res = client.post("/api/user/query", json={"query": "Next day"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "applied"
    assert data["tool_call"]["endpoint"] == "/api/simulation/tick"
    assert data["tool_call"]["tool"] == "simulation_tick"

    after = client.get("/api/world").json()
    assert after["tick"] == before["tick"] + 1


def test_user_query_simulation_playback(client):
    # Play
    res = client.post("/api/user/query", json={"query": "Play simulation"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "applied"
    assert data["tool_call"]["endpoint"] == "/api/simulation/play"
    assert data["result"]["playing"] is True

    # Pause
    res = client.post("/api/user/query", json={"query": "Pause simulation"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "applied"
    assert data["tool_call"]["endpoint"] == "/api/simulation/pause"
    assert data["result"]["playing"] is False


def test_user_query_business_and_lot_actions(client):
    # Found business
    res = client.post("/api/user/query", json={"query": "Found a bakery on plot-1"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert data["tool_call"]["endpoint"] == "/api/actions"
    assert data["tool_call"]["tool"] == "found_business"
    assert data["tool_call"]["parameters"]["plot_id"] == "plot-1"

    # Set price at building
    res = client.post("/api/user/query", json={"query": "Set bakery bread price to 6 coins"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert data["tool_call"]["endpoint"] == "/api/actions"
    assert data["tool_call"]["tool"] == "set_price"
    assert data["tool_call"]["parameters"]["price"] == 600

    # Set wage at building
    res = client.post("/api/user/query", json={"query": "Set wage at farm to 2 coins"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert data["tool_call"]["endpoint"] == "/api/actions"
    assert data["tool_call"]["tool"] == "set_wage"
    assert data["tool_call"]["parameters"]["wage"] == 200

    # Lease lot
    res = client.post("/api/user/query", json={"query": "Lease plot-2"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert data["tool_call"]["endpoint"] == "/api/actions"
    assert data["tool_call"]["tool"] == "lease_lot"


def test_user_query_concurrency_conflict(client):
    # Mismatched expected sequence returns 409
    res = client.post(
        "/api/user/query",
        json={"query": "Next day", "branch_id": "main", "expected_sequence": 999},
    )
    assert res.status_code == 409
    assert "World changed" in res.json()["detail"]


def test_user_query_unsupported_query_returns_422(client):
    res = client.post(
        "/api/user/query",
        json={"query": "Fly a rocket to Mars and back"},
    )
    assert res.status_code == 422


def test_user_query_alias_endpoint(client):
    res = client.post("/api/query", json={"query": "Next day"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "applied"
    assert data["tool_call"]["endpoint"] == "/api/simulation/tick"
