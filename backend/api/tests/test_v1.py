from fastapi.testclient import TestClient
from kronos.config import Settings
from kronos.main import create_app
from kronos_history.store import HistoryStore


def test_v1_growth_persists_and_broadcasts_without_action_repository(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("V1 must not use the database action queue or ledger")

    for name in ("enqueue", "pending", "action"):
        monkeypatch.setattr(HistoryStore, name, forbidden)
    config = Settings(database_url=f"sqlite:///{tmp_path / 'v1.db'}")
    with TestClient(create_app(config)) as client:
        before = client.get("/api/world").json()
        queued = client.post(
            "/api/actions",
            json={
                "branch_id": "main",
                "expected_sequence": 0,
                "action": {
                    "type": "set_price",
                    "actor_id": "citizen-1",
                    "building_id": "bakery",
                    "resource": "bread",
                    "price": 500,
                },
            },
        ).json()
        assert queued["status"] == "queued"
        with client.websocket_connect("/ws/world") as socket:
            assert socket.receive_json() == before
            sequence = 0
            collected = []
            for _ in range(3):
                response = client.post(
                    "/api/simulation/tick",
                    json={
                        "branch_id": "main",
                        "expected_sequence": sequence,
                    },
                )
                assert response.status_code == 200, response.text
                tick = response.json()
                frame = socket.receive_json()
                assert set(frame) == {"branch_id", "tick", "sequence", "state", "events"}
                assert frame["state"] == tick["state"]
                assert frame["events"] == tick["events"]
                assert (
                    client.app.state.service.store.world("main").model_dump(mode="json")
                    == frame["state"]
                )
                sequence = tick["sequence"]
                collected.extend(tick["events"])

                async def finish():
                    await client.app.state.service.decision_task

                client.portal.call(finish)
        assert client.get(f"/api/actions/{queued['action_id']}").json()["status"] == "applied"
        assert len([e for e in collected if e["type"] == "plot_opened"]) == 2
        assert len([e for e in collected if e["type"] == "citizen_spawned"]) == 1
        assert any(e["type"] == "job_applied" for e in collected)
        history = client.get("/api/events?after=0&limit=500").json()
        assert history == collected
        first = client.get("/api/events?after=0&limit=1").json()[0]
        rest = client.get(f"/api/events?after={first['sequence']}&limit=500").json()
        assert [first, *rest] == collected
        assert client.get(f"/api/events?after={sequence}").json() == []
        assert client.get("/api/events?after=-1").status_code == 422
        with client.app.state.service.store.engine.connect() as connection:
            assert connection.exec_driver_sql("select count(*) from actions").scalar() == 0
    with TestClient(create_app(config)) as client:
        assert client.get("/api/world").json()["state"] == frame["state"]
        assert client.get("/api/events?after=0&limit=500").json() == collected
        assert client.get(f"/api/actions/{queued['action_id']}").status_code == 404


def test_purchase_failure_and_occupied_plot_cannot_mutate_world():
    import pytest
    from kronos_sim import models as m
    from kronos_sim.engine import Engine, InvalidAction
    from kronos_sim.seed import initial_world

    state = initial_world()
    state.citizens["citizen-6"].money = 0
    engine = Engine(state)
    with pytest.raises(InvalidAction) as error:
        engine.apply(
            m.Buy(
                actor_id="citizen-6",
                building_id="bakery",
                resource="bread",
                quantity=1,
                max_unit_price=500,
            )
        )
    assert error.value.code == "insufficient_funds"
    assert engine.state == state
    with pytest.raises(InvalidAction) as error:
        engine.apply(m.ConstructBuilding(actor_id="citizen-1", plot_id="plot-0", kind="bakery"))
    assert error.value.code == "lot_occupied"
    assert engine.state == state
