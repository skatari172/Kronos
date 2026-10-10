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
    assert response.json()["status"] == "applied"
    assert client.get("/api/world").json()["state"] == expected.state.model_dump(mode="json")


@pytest.mark.parametrize(
    "path",
    [
        "/api/actions",
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


def construct(plot_id, expected_sequence=0):
    return {
        "branch_id": "main",
        "expected_sequence": expected_sequence,
        "action": {
            "type": "construct_building",
            "actor_id": "citizen-1",
            "plot_id": plot_id,
            "kind": "bakery",
            "rationale": "More bread",
        },
    }


def test_agent_action_returns_result_and_broadcasts(client):
    with client.websocket_connect("/ws/world") as socket:
        socket.receive_json()
        response = client.post("/api/agents/citizen-1/actions", json=construct("plot-3"))
        assert response.status_code == 200
        result = response.json()
        update = socket.receive_json()
    assert result["status"] == "applied"
    assert result["action_id"] == "action-main:0"
    assert result["error"] is None and result["message"] is None
    assert result["sequence"] == update["sequence"] == 1
    assert result["event_ids"] == [e["id"] for e in update["events"]]
    assert update["state"]["citizens"]["citizen-1"]["money"] == 17000


def test_agent_rule_rejection_is_logged_and_remembered(client):
    response = client.post("/api/agents/citizen-1/actions", json=construct("plot-0"))
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "rejected"
    assert result["error"] == "lot_occupied"
    assert result["sequence"] == 1
    events = client.get("/api/history/events?branch_id=main").json()
    assert [e["id"] for e in events] == result["event_ids"]
    assert events[0]["type"] == "action_rejected"
    assert events[0]["actor_id"] == "citizen-1"
    assert events[0]["rationale"] == "More bread"
    assert events[0]["payload"] == {
        "action_type": "construct_building",
        "code": "lot_occupied",
        "message": "Construction needs a vacant plot",
    }
    world = client.get("/api/world").json()
    assert world["state"]["citizens"]["citizen-1"]["memories"] == [
        "Rejected construct_building: Construction needs a vacant plot"
    ]
    assert len(world["state"]["buildings"]) == 3
    # The rejection advanced the version, so the old sequence is now stale.
    stale = client.post("/api/agents/citizen-1/actions", json=construct("plot-3"))
    assert stale.status_code == 409
    fresh = client.post("/api/agents/citizen-1/actions", json=construct("plot-3", 1))
    assert fresh.json()["status"] == "applied"


def test_other_callers_report_error_codes_without_logging(client):
    response = client.post("/api/actions", json=construct("plot-0"))
    assert response.status_code == 422
    assert response.json()["code"] == "lot_occupied"
    assert client.get("/api/history/events?branch_id=main").json() == []


def mutation(sequence=0):
    return {"branch_id": "main", "expected_sequence": sequence}


def test_list_and_read_agents_with_derived_fields(client):
    agents = client.get("/api/agents").json()
    assert [a["citizen"]["id"] for a in agents] == [f"citizen-{i}" for i in range(7)]
    owners = client.get("/api/agents?role=business_owner").json()
    assert [a["citizen"]["id"] for a in owners] == ["citizen-0", "citizen-1", "citizen-2"]
    assert all(a["owned_building_ids"] for a in owners)
    jobless = client.get("/api/agents?employed=false").json()
    assert [a["citizen"]["id"] for a in jobless] == ["citizen-5", "citizen-6"]
    poor = client.get("/api/agents?wealth_tier=poor&role=commoner").json()
    assert [a["citizen"]["id"] for a in poor] == ["citizen-3", "citizen-4", "citizen-6"]
    one = client.get("/api/agents/citizen-5").json()
    assert (one["role"], one["wealth_tier"], one["employed"]) == ("commoner", "middle", False)
    assert one["citizen"]["goal_weights"]["wealth"] == 25
    assert client.get("/api/agents/missing").status_code == 404
    assert client.get("/api/agents?role=king").status_code == 422


def test_spawn_citizen_through_engine(client):
    body = {**mutation(), "name": "Nico", "occupation": "Apprentice", "plot_id": "plot-4"}
    response = client.post("/api/agents", json=body)
    assert response.status_code == 201
    result = response.json()
    assert result["citizen_id"] == "citizen-main-1"
    assert result["update"]["events"][0]["type"] == "citizen_spawned"
    nico = client.get("/api/agents/citizen-main-1").json()
    assert nico["citizen"]["money"] == 0 and nico["role"] == "commoner"
    assert client.post("/api/agents", json=body).status_code == 409
    bad = client.post("/api/agents", json={**body, "expected_sequence": 1, "plot_id": "nowhere"})
    assert bad.status_code == 422 and bad.json()["code"] == "unknown_entity"


def test_citizen_history_includes_actor_and_recipient_events(client):
    say = {
        **mutation(),
        "action": {
            "type": "communicate",
            "actor_id": "citizen-2",
            "recipient_id": "citizen-3",
            "message": "Hello",
        },
    }
    assert client.post("/api/agents/citizen-2/actions", json=say).json()["status"] == "applied"
    speaker = client.get("/api/agents/citizen-2/history").json()
    listener = client.get("/api/agents/citizen-3/history").json()
    assert [e["type"] for e in speaker] == ["agent_spoke", "relationship_changed"]
    assert [e["type"] for e in listener] == ["agent_spoke", "relationship_changed"]
    assert client.get("/api/agents/citizen-4/history").json() == []
    assert client.get("/api/agents/citizen-2/history?limit=1").json() == speaker[-1:]
    assert client.get("/api/agents/missing/history").status_code == 404


def test_action_results_can_be_read_back(client):
    applied = client.post("/api/agents/citizen-1/actions", json=construct("plot-3")).json()
    rejected = client.post("/api/agents/citizen-1/actions", json=construct("plot-0", 1)).json()
    assert client.get(f"/api/actions/{applied['action_id']}").json() == applied
    assert client.get(f"/api/actions/{rejected['action_id']}").json() == rejected
    assert client.get("/api/actions/action-main:99").status_code == 404
    assert client.get("/api/actions/garbage").status_code == 404
    # User-route actions are not agent actions and have no action ID.
    client.post("/api/actions", json=construct("plot-4", 2))
    assert client.get("/api/actions/action-main:2").status_code == 404


def test_decide_submits_the_provider_choice(client):
    state = client.get("/api/agents/citizen-6").json()
    assert state["citizen"]["inventory"]["bread"] == 1
    response = client.post("/api/agents/citizen-6/decide", json=mutation())
    assert response.status_code == 200
    decision = response.json()
    assert decision["action"]["type"] == "communicate"
    assert decision["action"]["actor_id"] == "citizen-6"
    assert decision["result"]["status"] == "applied"
    events = client.get("/api/history/events?branch_id=main").json()
    assert [e["id"] for e in events] == decision["result"]["event_ids"]
    assert all(e["action_id"] == decision["result"]["action_id"] for e in events)
    assert client.post("/api/agents/citizen-6/decide", json=mutation()).status_code == 409
    assert client.post("/api/agents/missing/decide", json=mutation(2)).status_code == 404


def test_ask_is_read_only_and_cites_own_events(client):
    empty = client.post("/api/agents/citizen-4/ask", json={"question": "How are you?"}).json()
    assert empty == {"answer": "Nothing has happened to me yet.", "cited_event_ids": []}
    client.post("/api/agents/citizen-6/decide", json=mutation())
    before = client.get("/api/world").json()
    answer = client.post("/api/agents/citizen-6/ask", json={"question": "What did you do?"})
    assert answer.status_code == 200
    own = {e["id"] for e in client.get("/api/agents/citizen-6/history").json()}
    assert answer.json()["cited_event_ids"] and set(answer.json()["cited_event_ids"]) <= own
    assert client.get("/api/world").json() == before
    assert client.post("/api/agents/citizen-6/ask", json={"question": ""}).status_code == 422


def test_goal_update_is_bounded_and_renormalised(client):
    body = {**mutation(), "changes": {"wealth": 10, "safety": -10}, "rationale": "Saving up"}
    response = client.patch("/api/agents/citizen-6/goals", json=body)
    assert response.status_code == 200 and response.json()["status"] == "applied"
    weights = client.get("/api/agents/citizen-6").json()["citizen"]["goal_weights"]
    assert weights == {"wealth": 35, "influence": 25, "safety": 15, "reputation": 25}
    event = client.get("/api/agents/citizen-6/history").json()[-1]
    assert event["type"] == "goals_changed" and event["rationale"] == "Saving up"
    too_big = {**mutation(1), "changes": {"wealth": 11}}
    assert client.patch("/api/agents/citizen-6/goals", json=too_big).status_code == 422
    nothing = {**mutation(1), "changes": {}}
    assert client.patch("/api/agents/citizen-6/goals", json=nothing).status_code == 422


def command(actor_id, sequence=0, **fields):
    return {**mutation(sequence), "actor_id": actor_id, **fields}


def test_business_reads(client):
    listing = client.get("/api/businesses").json()
    assert [b["building"]["id"] for b in listing] == ["bakery", "farm", "market"]
    farm = client.get("/api/businesses/farm").json()
    assert farm["employee_ids"] == ["citizen-0", "citizen-3"] and farm["free_slots"] == 1
    assert farm["building"]["wage"] == 150
    assert [b["building"]["id"] for b in client.get("/api/businesses?kind=market").json()] == [
        "market"
    ]
    assert client.get("/api/businesses?owner=citizen-1").json()[0]["building"]["id"] == "bakery"
    assert client.get("/api/businesses/missing").status_code == 404


def test_business_lifecycle_through_convenience_routes(client):
    found = client.post(
        "/api/businesses",
        json=command("citizen-0", plot_id="plot-3", kind="bakery", capital=6000),
    ).json()
    assert found["status"] == "applied"
    new_id = client.get("/api/businesses?owner=citizen-0&kind=bakery").json()[0]["building"]["id"]
    seq = found["sequence"]

    def step(method, path, body):
        nonlocal seq
        result = client.request(method, f"/api/businesses/{new_id}{path}", json=body).json()
        seq = result["sequence"]
        return result

    assert step("POST", "/hire", command("citizen-0", seq, citizen_id="citizen-5"))["status"] == (
        "applied"
    )
    assert step("PATCH", "/wage", command("citizen-0", seq, wage=300))["status"] == "applied"
    assert (
        step("PATCH", "/price", command("citizen-0", seq, resource="bread", price=450))["status"]
        == "applied"
    )
    profile = client.get(f"/api/businesses/{new_id}").json()
    assert profile["employee_ids"] == ["citizen-5"]
    assert (profile["building"]["wage"], profile["building"]["prices"]["bread"]) == (300, 450)
    denied = step("POST", "/fire", command("citizen-6", seq, citizen_id="citizen-5"))
    assert (denied["status"], denied["error"]) == ("rejected", "not_owner")
    assert step("POST", "/fire", command("citizen-0", seq, citizen_id="citizen-5"))["status"] == (
        "applied"
    )
    closed = step("POST", "/close", command("citizen-0", seq, rationale="Too much competition"))
    assert closed["status"] == "applied"
    assert client.get(f"/api/businesses/{new_id}").status_code == 404
    assert client.get("/api/agents/citizen-0").json()["citizen"]["money"] == 18000


def test_buy_route_maps_to_buy_action(client):
    body = command("citizen-0", resource="bread", quantity=2, max_unit_price=500)
    result = client.post("/api/businesses/bakery/buy", json=body).json()
    assert result["status"] == "applied"
    assert client.get("/api/agents/citizen-0").json()["citizen"]["inventory"]["bread"] == 3
    too_many = command(
        "citizen-0", result["sequence"], resource="bread", quantity=99, max_unit_price=500
    )
    rejected = client.post("/api/businesses/bakery/buy", json=too_many).json()
    assert rejected["error"] == "out_of_stock"
    assert (
        client.post("/api/businesses/bakery/buy", json={**body, "quantity": 0}).status_code == 422
    )


def test_market_prices_and_history_routes(client):
    prices = client.get("/api/market/prices").json()
    bread = next(p for p in prices["prices"] if p["resource"] == "bread")
    assert bread == {"resource": "bread", "average": 500, "min": 500, "max": 500, "sellers": 3}
    body = command("citizen-1", resource="bread", price=800)
    changed = client.patch("/api/businesses/bakery/price", json=body).json()
    assert changed["status"] == "applied"
    assert client.get("/api/market/prices?branch_id=main").json()["prices"][0]["average"] == 600
    history = client.get("/api/market/prices/history?good=bread").json()
    assert [(p["sequence"], p["average"], p["max"]) for p in history["points"]] == [
        (0, 500, 500),
        (changed["sequence"], 600, 800),
    ]
    assert client.get("/api/market/prices/history?good=gold").status_code == 422
    assert client.get("/api/market/prices/history?good=bread&branch_id=nope").status_code == 404


def test_trade_offer_routes_round_trip(client):
    give, get = {"money": 300}, {"goods": {"bread": 1}}
    offered = client.post(
        "/api/market/trade",
        json=command("citizen-0", recipient_id="citizen-6", give=give, get=get),
    ).json()
    assert offered["status"] == "applied"
    offer_id = client.get("/api/agents/citizen-0/offers").json()["outgoing"][0]["id"]
    incoming = client.get("/api/agents/citizen-6/offers").json()["incoming"]
    assert [o["id"] for o in incoming] == [offer_id]
    observation = client.get("/api/agents/citizen-6/observation").json()
    assert [o["id"] for o in observation["incoming_offers"]] == [offer_id]
    assert "trade" in observation["available_actions"]

    seq = offered["sequence"]
    path = f"/api/market/trade/{offer_id}/respond"
    denied = client.post(path, json=command("citizen-0", seq, accept=True)).json()
    assert (denied["status"], denied["error"]) == ("rejected", "insufficient_authority")
    accepted = client.post(path, json=command("citizen-6", denied["sequence"], accept=True)).json()
    assert accepted["status"] == "applied"
    finn = client.get("/api/agents/citizen-6").json()["citizen"]
    assert (finn["money"], finn["inventory"]["bread"]) == (850, 0)
    assert client.get("/api/agents/citizen-6/offers").json()["incoming"] == []
    again = client.post(path, json=command("citizen-6", accepted["sequence"], accept=True)).json()
    assert again["error"] == "unknown_entity"
    assert client.get("/api/agents/missing/offers").status_code == 404
