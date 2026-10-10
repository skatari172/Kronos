"""Caller routing must preserve engine rules, version checks, and commit semantics."""

import pytest
from fastapi.testclient import TestClient
from kronos.config import Settings
from kronos.main import create_app
from kronos_sim.engine import Engine
from kronos_sim.models import Produce, WorldState


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(Settings(database_url=f"sqlite:///{tmp_path / 'tools.db'}"))
    ) as client:
        yield client


def test_openapi_groups_are_complete_and_operation_ids_unique(client):
    schema = client.get("/openapi.json").json()
    groups = {tag["name"] for tag in schema["tags"]}
    assert groups == {"User tools", "Agent tools", "Backend tools", "World", "History"}
    operations = [operation for path in schema["paths"].values() for operation in path.values()]
    assert all(len(op["tags"]) == 1 and op["tags"][0] in groups for op in operations)
    assert len({op["operationId"] for op in operations}) == len(operations)
    assert schema["paths"]["/api/actions"]["post"]["tags"] == ["User tools"]
    assert schema["paths"]["/api/agents/{citizen_id}/actions"]["post"]["tags"] == ["Agent tools"]
    assert schema["paths"]["/api/backend/actions"]["post"]["tags"] == ["Backend tools"]
    assert client.get("/docs").status_code == 200


def test_agent_observation_is_read_only_and_scoped(client):
    before = client.get("/api/world").json()
    response = client.get("/api/agents/citizen-6/observation")
    assert response.status_code == 200
    observation = response.json()
    assert observation["citizen"]["id"] == "citizen-6"
    assert observation["bread_prices"] == {"bakery": 500}
    assert "citizens" not in observation
    assert observation["sequence"] == before["sequence"]
    assert client.get("/api/world").json() == before
    assert client.get("/api/agents/missing/observation").status_code == 404


def test_agent_validation_does_not_save_or_advance_rng(client):
    before = client.get("/api/world").json()
    snapshots = client.get("/api/history/snapshots?branch_id=main").json()
    action = Produce(actor_id="citizen-0", building_id="farm")
    body = {"branch_id": "main", "expected_sequence": 0, "action": action.model_dump()}
    validation = client.post("/api/agents/citizen-0/actions/validate", json=body)
    assert validation.status_code == 200
    assert validation.json()["valid"] is True
    assert validation.json()["sequence"] == 0
    assert client.get("/api/world").json() == before
    assert client.get("/api/history/snapshots?branch_id=main").json() == snapshots
    expected = Engine(WorldState.model_validate(before["state"])).apply(action)
    response = client.post("/api/agents/citizen-0/actions", json=body)
    assert response.status_code == 200
    assert response.json()["state"] == expected.state.model_dump(mode="json")


@pytest.mark.parametrize(
    "path",
    [
        "/api/actions",
        "/api/agents/citizen-1/actions",
        "/api/backend/actions",
    ],
)
def test_all_callers_share_validation_persistence_and_broadcast(client, path):
    body = {
        "branch_id": "main",
        "expected_sequence": 0,
        "action": {
            "type": "construct_building",
            "actor_id": "citizen-1",
            "plot_id": "plot-0",
            "kind": "bakery",
        },
    }
    assert client.post(path, json=body).status_code == 422  # Occupied plot.
    assert client.get("/api/world").json()["sequence"] == 0
    body["action"]["plot_id"] = "plot-3"
    with client.websocket_connect("/ws/world") as socket:
        socket.receive_json()
        result = client.post(path, json=body)
        assert result.status_code == 200
        update = result.json()
        assert socket.receive_json() == update
    assert update["state"]["citizens"]["citizen-1"]["money"] == 17000
    assert len(update["state"]["buildings"]) == 4
    assert client.get("/api/history/events?branch_id=main").json() == update["events"]
    snapshots = client.get("/api/history/snapshots?branch_id=main").json()
    assert len(snapshots) == 2
    assert (
        client.get(f"/api/history/snapshots/{snapshots[-1]['id']}").json()["state"]
        == update["state"]
    )
    assert client.post(path, json=body).status_code == 409


@pytest.mark.parametrize("suffix", ["actions", "actions/validate"])
def test_agent_cannot_submit_for_another_citizen(client, suffix):
    body = {
        "branch_id": "main",
        "expected_sequence": 0,
        "action": {
            "type": "set_price",
            "actor_id": "citizen-1",
            "building_id": "bakery",
            "resource": "bread",
            "price": 1,
        },
    }
    assert client.post(f"/api/agents/citizen-6/{suffix}", json=body).status_code == 422
    assert client.post(f"/api/agents/missing/{suffix}", json=body).status_code == 404
    assert client.get("/api/world").json()["sequence"] == 0
    assert client.get("/api/history/events?branch_id=main").json() == []


def test_backend_clock_and_creation_routes_remain_compatible(client):
    body = {"branch_id": "main", "expected_sequence": 0, "speed": 2}
    assert client.post("/api/simulation/play", json=body).json()["playing"] is True
    assert client.get("/api/simulation/status").json()["speed"] == 2
    assert client.post("/api/simulation/pause").json()["playing"] is False
    branch = client.post("/api/simulations")
    assert branch.status_code == 201
    assert client.get("/api/world").json()["branch_id"] == "main"
    assert client.get(f"/api/branches/{branch.json()['id']}/world").status_code == 200
