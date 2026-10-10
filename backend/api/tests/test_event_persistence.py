"""Durable event outcomes are available over HTTP independently of realtime delivery."""

import pytest
from fastapi.testclient import TestClient
from kronos.config import Settings
from kronos.main import create_app
from kronos.routes.history import router
from kronos.service import Service


@pytest.mark.parametrize(
    "broadcast_mode", ["no_clients", "failed", "disabled", "disconnected_client"]
)
def test_action_events_can_be_read_and_survive_restart_without_websockets(
    tmp_path, monkeypatch, route_only, broadcast_mode
):
    # Isolate the action's economic effects from wages, hunger and growth. The real
    # engine validation, queue, SQLite transaction and HTTP routes remain enabled.
    if broadcast_mode == "failed":

        async def failed_broadcast(self, update):
            raise RuntimeError("realtime transport unavailable")

        monkeypatch.setattr(Service, "broadcast", failed_broadcast)
    elif broadcast_mode == "disabled":

        async def disabled_broadcast(self, update):
            pass

        monkeypatch.setattr(Service, "broadcast", disabled_broadcast)

    class DisconnectedClient:
        async def send_json(self, payload):
            raise RuntimeError("client disconnected")

        async def close(self):
            pass

    config = Settings(database_url=f"sqlite:///{tmp_path / 'events.db'}")
    with TestClient(create_app(config)) as client:
        service = client.app.state.service
        assert not service.clients
        if broadcast_mode == "disconnected_client":
            service.clients.add(DisconnectedClient())
        before = client.get("/api/world").json()
        assert client.get("/api/events").json() == []
        attempts = []
        # Rowan can afford one bread; Finn cannot afford two.
        for citizen_id, quantity in (("citizen-3", 1), ("citizen-6", 2)):
            response = client.post(
                "/api/actions",
                json={
                    "branch_id": "main",
                    "expected_sequence": before["sequence"],
                    "action": {
                        "type": "buy",
                        "actor_id": citizen_id,
                        "building_id": "bakery",
                        "resource": "bread",
                        "quantity": quantity,
                        "max_unit_price": 500,
                    },
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "queued"
            attempts.append(response.json()["action_id"])
        # Admission is an intention, not a persisted simulation outcome.
        assert client.get("/api/events").json() == []
        assert client.get("/api/world").json() == before
        response = client.post(
            "/api/simulation/tick",
            json={"branch_id": "main", "expected_sequence": before["sequence"]},
        )
        assert response.status_code == 200, response.text
        tick = response.json()
        assert [r["status"] for r in tick["action_results"]] == ["applied", "rejected"]
        state = tick["state"]
        assert state["citizens"]["citizen-3"]["money"] == 300
        assert state["citizens"]["citizen-3"]["inventory"]["bread"] == 2
        for key in ("money", "inventory", "hunger", "employer_id", "position"):
            assert (
                state["citizens"]["citizen-6"][key] == before["state"]["citizens"]["citizen-6"][key]
            )
        assert state["buildings"]["bakery"]["cash"] == 10500
        assert state["buildings"]["bakery"]["inventory"]["bread"] == 15

        response = client.get("/api/events", params={"after": 0, "limit": 500})
        assert response.status_code == 200
        saved = response.json()
        assert saved == tick["events"]
        assert [e["sequence"] for e in saved] == [1, 2, 3]
        assert [e["type"] for e in saved] == [
            "transaction_completed",
            "action_rejected",
            "tick_completed",
        ]
        purchase, rejection = saved[:2]
        assert purchase["action_id"] == attempts[0]
        assert purchase["payload"]["amount"] == 500
        assert purchase["payload"]["quantity"] == 1
        assert rejection["action_id"] == attempts[1]
        assert rejection["payload"]["code"] == "insufficient_funds"
        assert client.get("/api/events", params={"after": 1, "limit": 1}).json() == [rejection]
        assert client.get("/api/events", params={"after": 2}).json() == saved[2:]
        assert client.get("/api/events", params={"after": tick["sequence"]}).json() == []
        assert not service.clients

    # A fresh API session has no runtime action records or connected clients. Its
    # event query must still read exactly the same committed SQLite rows.
    with TestClient(create_app(config)) as restarted:
        assert not restarted.app.state.service.clients
        assert restarted.get("/api/events", params={"limit": 500}).json() == saved
        assert restarted.get("/api/world").json()["state"] == state
        assert restarted.get(f"/api/actions/{attempts[0]}").status_code == 404


def test_events_has_one_handler_and_matches_the_documented_list_contract():
    handlers = [route for route in router.routes if route.path == "/api/events"]
    assert len(handlers) == 1
    operation = create_app().openapi()["paths"]["/api/events"]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
