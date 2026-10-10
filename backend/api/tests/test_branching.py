"""Branching, tracing and comparison (planning Phase 6, backend)."""

import time

import pytest
from fastapi.testclient import TestClient
from kronos.config import Settings
from kronos.main import create_app
from kronos_sim.engine import Engine, state_hash
from kronos_sim.models import Buy
from kronos_sim.seed import initial_world


@pytest.fixture
def client(tmp_path):
    config = Settings(database_url=f"sqlite:///{tmp_path / 'branching.db'}", ticks_per_year=2)
    with TestClient(create_app(config)) as test_client:
        yield test_client


def ctx(client):
    world = client.get("/api/world").json()
    return {"branch_id": world["branch_id"], "expected_sequence": world["sequence"]}


def tick(client):
    response = client.post("/api/simulation/tick", json=ctx(client))
    assert response.status_code == 200
    return response.json()


def first_snapshot(client, branch_id="main"):
    return client.get("/api/history/snapshots", params={"branch_id": branch_id}).json()[0]["id"]


def fork(client, name, intervention=None):
    body = {"snapshot_id": first_snapshot(client), "name": name}
    if intervention:
        body["intervention"] = intervention
    response = client.post("/api/branches", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def run(client, branch_id, ticks, agents="none"):
    started = client.post(f"/api/branches/{branch_id}/run", json={"ticks": ticks, "agents": agents})
    assert started.status_code == 202, started.text
    for _ in range(200):
        status = client.get(f"/api/branches/{branch_id}/run").json()
        if status["status"] != "running":
            return status
        time.sleep(0.02)
    raise AssertionError("background run did not finish")


def test_actions_cite_events_and_bad_refs_are_refused(client):
    tick(client)
    cited = client.get("/api/events", params={"type": "tick_completed"}).json()[-1]["id"]
    action = {
        "type": "buy",
        "actor_id": "citizen-0",
        "building_id": "bakery",
        "resource": "bread",
        "quantity": 1,
        "max_unit_price": 1000,
        "causal_refs": [cited],
    }
    queued = client.post("/api/actions", json={**ctx(client), "action": action}).json()
    tick(client)
    outcome = client.get(f"/api/actions/{queued['action_id']}").json()
    assert outcome["status"] == "applied", (outcome["error"], outcome["message"])
    events = client.get("/api/events", params={"limit": 500}).json()
    mine = [e for e in events if e["action_id"] == queued["action_id"]]
    assert mine and all(cited in e["causal_refs"] for e in mine)
    bad = {**action, "causal_refs": ["main:999999"]}
    refused = client.post("/api/actions", json={**ctx(client), "action": bad})
    assert refused.status_code == 422 and "unknown event" in refused.text


def test_trace_follows_causes_back_and_effects_forward(client):
    queued = client.post(
        "/api/interventions", json={**ctx(client), "text": "Increase bread price by 40%"}
    ).json()
    tick(client)
    events = client.get("/api/events", params={"limit": 500}).json()
    cause = next(e for e in events if e["type"] == "intervention_applied")
    effect = next(e for e in events if e["type"] == "price_changed")
    assert cause["action_id"] == queued["result"]["action_id"]

    forward = client.get(f"/api/events/{cause['id']}/trace", params={"direction": "forward"})
    ids = [e["id"] for e in forward.json()["events"]]
    assert ids[0] == cause["id"] and effect["id"] in ids
    assert {"from_id": effect["id"], "to_id": cause["id"], "kind": "cites"} in (
        forward.json()["edges"]
    )
    back = client.get(f"/api/events/{effect['id']}/trace").json()
    assert cause["id"] in [e["id"] for e in back["events"]]
    assert client.get("/api/events/nope/trace").status_code == 404


def test_event_filters(client):
    for _ in range(3):
        tick(client)
    days = client.get("/api/events", params={"type": "tick_completed", "limit": 500}).json()
    assert [e["tick"] for e in days] == [1, 2, 3]
    two_types = client.get(
        "/api/events", params=[("type", "tick_completed"), ("type", "citizen_moved")]
    ).json()
    assert {e["type"] for e in two_types} == {"tick_completed", "citizen_moved"}
    ranged = client.get("/api/events", params={"tick_from": 2, "tick_to": 2, "limit": 500}).json()
    assert ranged and all(e["tick"] == 2 for e in ranged)
    acted = client.get("/api/events", params={"actor": "citizen-3", "limit": 500}).json()
    assert acted and all(e["actor_id"] == "citizen-3" for e in acted)
    paid = client.get("/api/events", params={"target": "citizen-3", "limit": 500}).json()
    assert paid and all(
        "citizen-3"
        in {
            e["payload"].get(k)
            for k in ("sender_id", "recipient_id", "entity_id", "citizen_id", "building_id")
        }
        for e in paid
    )
    assert client.get("/api/events", params={"branch_id": "ghost"}).status_code == 404


def test_same_seed_and_actions_give_the_same_hashes():
    buy = Buy(
        actor_id="citizen-6",
        building_id="bakery",
        resource="bread",
        quantity=1,
        max_unit_price=1000,
    )

    def replay():
        world, out = initial_world(42), []
        for day in range(6):
            result = Engine(world).tick([buy] if day % 2 else [])
            world = result.state
            out.append(result.events[-1].payload.state_hash)
        return out, world

    first, world = replay()
    second, _ = replay()
    assert first == second and len(set(first)) == 6
    assert first[-1] == state_hash(world)
    # Branch ID and sequence are excluded, so a fresh fork hashes like its source.
    start = initial_world(42)
    assert state_hash(Engine(start).fork("elsewhere")) == state_hash(start)


def test_identical_forks_have_identical_hashes_and_no_divergence(client):
    left, right = fork(client, "Left"), fork(client, "Right")
    run(client, left["id"], 4)
    run(client, right["id"], 4)
    hashes_left = client.get(f"/api/branches/{left['id']}/hashes").json()
    hashes_right = client.get(f"/api/branches/{right['id']}/hashes").json()
    assert [h["tick"] for h in hashes_left] == [1, 2, 3, 4]
    assert [h["state_hash"] for h in hashes_left] == [h["state_hash"] for h in hashes_right]
    found = client.get(
        "/api/branches/divergence", params={"a": left["id"], "b": right["id"]}
    ).json()
    assert found["tick"] is None and found["decision_a"] is None


def test_fork_records_seed_and_intervention_and_diverges_there(client):
    tick(client)
    plain = fork(client, "No change")
    dear = fork(client, "Dear bread", "Increase bread price by 40%")
    assert dear["seed"] == 42 and dear["intervention"] == "Increase bread price by 40%"
    assert dear["parent_branch_id"] == "main" and plain["intervention"] is None
    listed = {b["id"]: b for b in client.get("/api/branches").json()}
    assert listed[dear["id"]]["intervention"] == dear["intervention"]
    bad = client.post(
        "/api/branches",
        json={"snapshot_id": first_snapshot(client), "name": "Bad", "intervention": "Fly"},
    )
    assert bad.status_code == 422
    assert len(client.get("/api/branches").json()) == 3  # a bad intervention creates nothing

    assert run(client, plain["id"], 3)["ticks_done"] == 3
    done = run(client, dear["id"], 3)
    assert (done["status"], done["tick"]) == ("done", 3)
    split = client.get(
        "/api/branches/divergence", params={"a": plain["id"], "b": dear["id"]}
    ).json()
    assert split["tick"] == 1 and split["common_tick"] == 0
    assert split["decision_b"]["type"] == "intervention_applied"
    assert "price_changed" in [e["type"] for e in split["chain_b"]]
    hashes = [
        [h["state_hash"] for h in client.get(f"/api/branches/{b}/hashes").json()]
        for b in (plain["id"], dear["id"])
    ]
    assert hashes[0][0] != hashes[1][0]  # They differ from the first day on.

    compared = client.get(
        "/api/branches/compare", params=[("ids", plain["id"]), ("ids", dear["id"])]
    ).json()["branches"]
    series = {s["name"]: {p["tick"]: p for p in s["points"]} for s in compared}
    assert sorted(series["Dear bread"]) == [0, 1, 2, 3]
    assert series["Dear bread"][0] == series["No change"][0]  # shared start
    assert series["Dear bread"][1]["bread_price"] > series["No change"][1]["bread_price"]
    assert {"gini_bps", "population", "total_money", "top_influence_bps"} <= set(
        series["Dear bread"][3]
    )


def test_background_runs_leave_the_live_branch_alone(client):
    live = client.get("/api/world").json()
    branch = fork(client, "Background")
    assert client.post("/api/branches/main/run", json={"ticks": 1}).status_code == 409
    status = run(client, branch["id"], 5, agents="utility")
    assert status["status"] == "done" and status["ticks_done"] == 5
    after = client.get("/api/world").json()
    assert (after["branch_id"], after["tick"], after["sequence"]) == (
        "main",
        live["tick"],
        live["sequence"],
    )
    world = client.get(f"/api/branches/{branch['id']}/world").json()
    assert world["tick"] == 5
    decided = client.get("/api/events", params={"branch_id": branch["id"], "limit": 500}).json()
    assert any(e["action_id"] for e in decided)  # utility citizens acted
    assert client.get("/api/branches/ghost/run").status_code == 404


def test_activating_a_running_branch_is_refused_until_stopped(client):
    branch = fork(client, "Long")
    started = client.post(f"/api/branches/{branch['id']}/run", json={"ticks": 365})
    assert started.status_code == 202
    assert client.post(f"/api/branches/{branch['id']}/run", json={"ticks": 1}).status_code == 409
    assert client.post(f"/api/branches/{branch['id']}/activate", json={}).status_code == 409
    stopped = client.delete(f"/api/branches/{branch['id']}/run").json()
    assert stopped["status"] in ("cancelled", "done")
    assert client.post(f"/api/branches/{branch['id']}/activate", json={}).status_code == 200


def test_yearly_checkpoints(client):
    for _ in range(5):
        tick(client)
    years = client.get("/api/branches/main/checkpoints").json()
    # ticks_per_year=2: years 0 (days 0-1), 1 (days 2-3), 2 (day 4+), each its last snapshot.
    assert [(y["year"], y["tick"]) for y in years] == [(0, 1), (1, 3), (2, 5)]
    assert all(y["snapshot"]["branch_id"] == "main" for y in years)


def test_identical_forks_stay_identical_through_newcomers_and_decisions(client):
    # Newcomers (days 3, 6, 9) used to get branch-specific IDs, which reordered citizens
    # and their random draws, so identical forks drifted apart from day 4.
    left, right = fork(client, "Left"), fork(client, "Right")
    run(client, left["id"], 9, agents="utility")
    run(client, right["id"], 9, agents="utility")
    hashes = [
        [h["state_hash"] for h in client.get(f"/api/branches/{b['id']}/hashes").json()]
        for b in (left, right)
    ]
    assert len(hashes[0]) == 9 and hashes[0] == hashes[1]
    worlds = [client.get(f"/api/branches/{b['id']}/world").json()["state"] for b in (left, right)]
    assert sorted(worlds[0]["citizens"]) == sorted(worlds[1]["citizens"])
    assert any(c.startswith("citizen-0000") for c in worlds[0]["citizens"])  # a newcomer came
