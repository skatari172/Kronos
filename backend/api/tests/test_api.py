from fastapi.testclient import TestClient
from kronos.config import Settings
from kronos.main import create_app


def test_vertical_slice_persistence_websocket_and_fork(tmp_path):
    config = Settings(database_url=f"sqlite:///{tmp_path / 'api.db'}")
    with TestClient(create_app(config)) as client:
        assert client.get("/health").json()["status"] == "ok"
        initial = client.get("/api/world").json()
        assert len(initial["state"]["citizens"]) == 7
        snapshot = client.get("/api/history/snapshots?branch_id=main").json()[0]
        with client.websocket_connect("/ws/world") as socket:
            assert socket.receive_json()["sequence"] == 0
            response = client.post(
                "/api/interventions",
                json={
                    "text": "Increase bread price by 40%.",
                    "branch_id": "main",
                    "expected_sequence": 0,
                },
            )
            assert response.status_code == 200
            assert response.json()["result"]["status"] == "queued"
            assert client.get("/api/world").json() == initial
            tick = client.post(
                "/api/simulation/tick", json={"branch_id": "main", "expected_sequence": 0}
            )
            assert tick.status_code == 200
            changed = socket.receive_json()
            assert changed["state"]["buildings"]["bakery"]["prices"]["bread"] == 700
            assert changed["tick"] == 1
        fork = client.post(
            "/api/branches", json={"snapshot_id": snapshot["id"], "name": "Alternate"}
        )
        assert fork.status_code == 201
        bid = fork.json()["id"]
        restored = client.post(f"/api/branches/{bid}/activate").json()
        assert restored["state"]["buildings"]["bakery"]["prices"]["bread"] == 500
        assert client.get("/api/branches/main/world").json()["tick"] == 1
        assert len(client.get("/api/history/events?branch_id=main").json()) > 2
    with TestClient(create_app(config)) as restarted:
        assert restarted.get("/api/world").json()["branch_id"] == bid


def test_rejects_stale_and_unsupported_requests(tmp_path):
    with TestClient(
        create_app(Settings(database_url=f"sqlite:///{tmp_path / 'api.db'}"))
    ) as client:
        assert (
            client.post(
                "/api/simulation/tick", json={"branch_id": "wrong", "expected_sequence": 0}
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/interventions",
                json={"text": "Invent electricity", "branch_id": "main", "expected_sequence": 0},
            ).status_code
            == 422
        )
        assert client.get("/api/branches/missing/world").status_code == 404
        assert (
            client.post(
                "/api/actions",
                json={
                    "branch_id": "main",
                    "expected_sequence": 0,
                    "action": {
                        "type": "construct_building",
                        "actor_id": "citizen-1",
                        "plot_id": "plot-3",
                        "kind": "bakery",
                    },
                },
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/simulation/tick", json={"branch_id": "main", "expected_sequence": 0}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/simulation/tick", json={"branch_id": "main", "expected_sequence": 0}
            ).status_code
            == 409
        )
