from fastapi.testclient import TestClient
from kronos.config import Settings
from kronos.main import create_app
from kronos_sim import models as m
from kronos_sim.queries import job_openings
from kronos_sim.seed import initial_world

V1_HTTP_ROUTES = {
    ("get", "/api/world"),
    ("get", "/api/simulation/status"),
    ("post", "/api/simulation/play"),
    ("post", "/api/simulation/pause"),
    ("post", "/api/simulation/tick"),
    ("post", "/api/actions"),
    ("post", "/api/interventions"),
    ("get", "/api/events"),
    ("get", "/api/jobs"),
}


def test_every_v1_route_is_registered(tmp_path):
    # FastAPI may nest included routers, so read HTTP routes from the generated schema.
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'api.db'}"))
    paths = app.openapi()["paths"]
    registered = {(method, path) for path, ops in paths.items() for method in ops}
    assert V1_HTTP_ROUTES <= registered, V1_HTTP_ROUTES - registered
    # WebSockets are not in OpenAPI; connect to prove /ws/world is mounted.
    with TestClient(app) as client, client.websocket_connect("/ws/world") as socket:
        assert socket.receive_json()["branch_id"] == "main"


def _advance(client, days: int) -> int:
    sequence = client.get("/api/world").json()["sequence"]
    for _ in range(days):
        sequence = client.post(
            "/api/simulation/tick", json={"branch_id": "main", "expected_sequence": sequence}
        ).json()["sequence"]
    return sequence


def test_events_pages_in_sequence_order(tmp_path):
    config = Settings(database_url=f"sqlite:///{tmp_path / 'api.db'}")
    with TestClient(create_app(config)) as client:
        latest = _advance(client, 3)
        world = client.get("/api/world").json()
        assert world["events"], "the world envelope carries recent events"
        assert world["events"][-1]["sequence"] == latest

        everything = client.get("/api/events", params={"limit": 500}).json()
        sequences = [e["sequence"] for e in everything]
        assert sequences == sorted(sequences) and len(set(sequences)) == len(sequences)
        assert sequences[-1] == latest and len(sequences) > 4

        # Walk the log two at a time, passing the last sequence seen as `after`.
        paged, after = [], 0
        while page := client.get("/api/events", params={"after": after, "limit": 2}).json():
            assert len(page) <= 2 and all(e["sequence"] > after for e in page)
            paged += [e["sequence"] for e in page]
            after = page[-1]["sequence"]
        assert paged == sequences
        assert client.get("/api/events", params={"after": latest}).json() == []
        assert client.get("/api/history/events", params={"branch_id": "main"}).status_code == 200


def test_events_rejects_bad_queries(tmp_path):
    config = Settings(database_url=f"sqlite:///{tmp_path / 'api.db'}")
    with TestClient(create_app(config)) as client:
        assert client.get("/api/events", params={"limit": 0}).status_code == 422
        assert client.get("/api/events", params={"limit": 501}).status_code == 422
        assert client.get("/api/events", params={"after": -1}).status_code == 422


def test_jobs_lists_only_pending_applicants():
    state = initial_world()
    opening = job_openings(state)[0]
    citizens = sorted(state.citizens)
    for index, status in enumerate(("pending", "hired", "rejected")):
        application = m.JobApplication(
            id=f"application-{index}",
            citizen_id=citizens[index],
            building_id=opening.building_id,
            tick=0,
            sequence=index,
            status=status,
        )
        state.job_applications[application.id] = application
    listed = next(o for o in job_openings(state) if o.building_id == opening.building_id)
    assert listed.applicant_ids == [citizens[0]]
    assert listed.free_slots == opening.free_slots
