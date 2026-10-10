"""Caller routing must preserve engine rules, version checks, and commit semantics."""

import pytest
from fastapi.testclient import TestClient
from kronos.config import Settings
from kronos.main import create_app
from kronos_sim.engine import Engine
from kronos_sim.models import Produce, WorldState
from route_helpers import resolve


@pytest.fixture
def client(tmp_path, route_only):
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
    validation = resolve(client, client.post("/api/agents/citizen-0/actions/validate", json=body))
    assert validation.status_code == 200
    assert validation.json()["valid"] is True
    assert validation.json()["sequence"] == 0
    assert client.get("/api/world").json() == before
    assert client.get("/api/history/snapshots?branch_id=main").json() == snapshots
    expected = Engine(WorldState.model_validate(before["state"])).tick([action])
    response = resolve(client, client.post("/api/agents/citizen-0/actions", json=body))
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
    body = construct("plot-0")
    rejected = resolve(client, client.post(path, json=body)).json()
    assert (rejected["status"], rejected["error"]) == ("rejected", "lot_occupied")
    body = construct("plot-3", rejected["sequence"])
    with client.websocket_connect("/ws/world") as socket:
        socket.receive_json()
        result = resolve(client, client.post(path, json=body)).json()
        update = socket.receive_json()
    assert result["status"] == "applied"
    assert result["sequence"] == update["sequence"]
    assert update["state"]["citizens"]["citizen-1"]["money"] == 17000
    assert len(update["state"]["buildings"]) == 4
    snapshots = client.get("/api/history/snapshots?branch_id=main").json()
    assert len(snapshots) == 3
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
    assert (
        resolve(client, client.post(f"/api/agents/citizen-6/{suffix}", json=body)).status_code
        == 422
    )
    assert (
        resolve(client, client.post(f"/api/agents/missing/{suffix}", json=body)).status_code == 404
    )
    assert client.get("/api/world").json()["sequence"] == 0
    assert client.get("/api/history/events?branch_id=main").json() == []


def test_backend_clock_and_creation_routes_remain_compatible(client):
    body = {"branch_id": "main", "expected_sequence": 0, "speed": 2}
    assert resolve(client, client.post("/api/simulation/play", json=body)).json()["playing"] is True
    assert client.get("/api/simulation/status").json()["speed"] == 2
    assert resolve(client, client.post("/api/simulation/pause")).json()["playing"] is False
    branch = resolve(client, client.post("/api/simulations"))
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
        response = resolve(
            client, client.post("/api/agents/citizen-1/actions", json=construct("plot-3"))
        )
        assert response.status_code == 200
        result = response.json()
        update = socket.receive_json()
    assert result["status"] == "applied"
    assert result["action_id"].startswith("action-main:")
    assert result["order"] == 1
    assert result["error"] is None and result["message"] is None
    assert result["sequence"] == update["sequence"] == 2
    assert result["event_ids"] == [
        e["id"] for e in update["events"] if e["action_id"] == result["action_id"]
    ]
    assert update["state"]["citizens"]["citizen-1"]["money"] == 17000


def test_agent_rule_rejection_is_logged_without_mutation(client):
    before = client.get("/api/world").json()["state"]
    result = resolve(
        client, client.post("/api/agents/citizen-1/actions", json=construct("plot-0"))
    ).json()
    assert (result["status"], result["error"]) == ("rejected", "lot_occupied")
    events = client.get("/api/history/events?branch_id=main").json()
    assert events[0]["type"] == "action_rejected"
    assert events[0]["rationale"] == "More bread"
    assert events[0]["payload"] == {
        "action_type": "construct_building",
        "code": "lot_occupied",
        "message": "Construction needs a vacant plot",
    }
    world = client.get("/api/world").json()["state"]
    # Only the actor's memory changes: it remembers the refusal.
    strip = ("memories", "memory_summary", "memory_tally")
    assert {
        k: {f: v for f, v in c.items() if f not in strip} for k, c in world["citizens"].items()
    } == {k: {f: v for f, v in c.items() if f not in strip} for k, c in before["citizens"].items()}
    assert world["citizens"]["citizen-1"]["memories"][-1].startswith("Rejected construct_building")
    assert world["buildings"] == before["buildings"] and world["rng_state"] == before["rng_state"]
    observation = client.get("/api/agents/citizen-1/observation").json()
    assert observation["recent_events"][0]["id"] == events[0]["id"]
    assert client.post("/api/agents/citizen-1/actions", json=construct("plot-3")).status_code == 409
    fresh = resolve(
        client,
        client.post("/api/agents/citizen-1/actions", json=construct("plot-3", result["sequence"])),
    )
    assert fresh.json()["status"] == "applied"


def test_other_callers_also_log_rule_rejections(client):
    response = resolve(client, client.post("/api/actions", json=construct("plot-0")))
    assert response.status_code == 200
    assert response.json()["error"] == "lot_occupied"
    assert client.get("/api/history/events?branch_id=main").json()[0]["type"] == "action_rejected"


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
    response = resolve(client, client.post("/api/agents", json=body))
    assert response.status_code == 201
    result = response.json()
    assert result["citizen_id"] == "citizen-main-1"
    assert result["update"]["events"][0]["type"] == "citizen_spawned"
    nico = client.get("/api/agents/citizen-main-1").json()
    assert nico["citizen"]["money"] == 0 and nico["role"] == "commoner"
    assert resolve(client, client.post("/api/agents", json=body)).status_code == 409
    bad = resolve(
        client,
        client.post("/api/agents", json={**body, "expected_sequence": 1, "plot_id": "nowhere"}),
    )
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
    assert (
        resolve(client, client.post("/api/agents/citizen-2/actions", json=say)).json()["status"]
        == "applied"
    )
    speaker = client.get("/api/agents/citizen-2/history").json()
    listener = client.get("/api/agents/citizen-3/history").json()
    assert [e["type"] for e in speaker] == ["agent_spoke", "relationship_changed"]
    assert [e["type"] for e in listener] == ["agent_spoke", "relationship_changed"]
    assert client.get("/api/agents/citizen-4/history").json() == []
    assert client.get("/api/agents/citizen-2/history?limit=1").json() == speaker[-1:]
    assert client.get("/api/agents/missing/history").status_code == 404


def test_action_results_can_be_read_back(client):
    applied = resolve(
        client, client.post("/api/agents/citizen-1/actions", json=construct("plot-3"))
    ).json()
    rejected = resolve(
        client,
        client.post("/api/agents/citizen-1/actions", json=construct("plot-0", applied["sequence"])),
    ).json()
    assert client.get(f"/api/actions/{applied['action_id']}").json() == applied
    assert client.get(f"/api/actions/{rejected['action_id']}").json() == rejected
    assert client.get("/api/actions/garbage").status_code == 404
    player = resolve(
        client, client.post("/api/actions", json=construct("plot-4", rejected["sequence"]))
    ).json()
    assert client.get(f"/api/actions/{player['action_id']}").json() == player
    assert player["source"] == "player"


def test_decide_submits_the_provider_choice(client):
    before = client.get("/api/world").json()
    response = client.post("/api/agents/citizen-6/decide", json=mutation())
    assert response.status_code == 200
    decision = response.json()
    assert decision["action"]["type"] == "communicate"
    assert decision["result"]["status"] == "queued"
    assert client.get("/api/world").json() == before
    tick = client.post("/api/simulation/tick", json=mutation()).json()
    result = client.get(f"/api/actions/{decision['result']['action_id']}").json()
    assert result["status"] == "applied"
    assert result["event_ids"] == [
        e["id"] for e in tick["events"] if e["action_id"] == result["action_id"]
    ]
    assert decision["action"]["actor_id"] == "citizen-6"
    assert decision["source"] == "mock" and decision["action"]["rationale"].startswith("[mock] ")
    assert client.post("/api/agents/citizen-6/decide", json=mutation()).status_code == 409
    assert (
        client.post("/api/agents/missing/decide", json=mutation(tick["sequence"])).status_code
        == 404
    )


def test_ask_is_read_only_and_cites_own_events(client):
    empty = resolve(
        client, client.post("/api/agents/citizen-4/ask", json={"question": "How are you?"})
    ).json()
    assert empty == {"answer": "Nothing has happened to me yet.", "cited_event_ids": []}
    client.post("/api/agents/citizen-6/decide", json=mutation())
    client.post("/api/simulation/tick", json=mutation())
    before = client.get("/api/world").json()
    answer = resolve(
        client, client.post("/api/agents/citizen-6/ask", json={"question": "What did you do?"})
    )
    assert answer.status_code == 200
    own = {e["id"] for e in client.get("/api/agents/citizen-6/history").json()}
    assert answer.json()["cited_event_ids"] and set(answer.json()["cited_event_ids"]) <= own
    assert client.get("/api/world").json() == before
    assert (
        resolve(client, client.post("/api/agents/citizen-6/ask", json={"question": ""})).status_code
        == 422
    )


def test_goal_update_is_bounded_and_renormalised(client):
    body = {**mutation(), "changes": {"wealth": 10, "safety": -10}, "rationale": "Saving up"}
    response = resolve(client, client.patch("/api/agents/citizen-6/goals", json=body))
    assert response.status_code == 200 and response.json()["status"] == "applied"
    weights = client.get("/api/agents/citizen-6").json()["citizen"]["goal_weights"]
    # Finn starts at 15/15/30/40.
    assert weights == {"wealth": 25, "influence": 15, "safety": 20, "reputation": 40}
    event = client.get("/api/agents/citizen-6/history").json()[-1]
    assert event["type"] == "goals_changed" and event["rationale"] == "Saving up"
    too_big = {**mutation(1), "changes": {"wealth": 11}}
    assert (
        resolve(client, client.patch("/api/agents/citizen-6/goals", json=too_big)).status_code
        == 422
    )
    nothing = {**mutation(1), "changes": {}}
    assert (
        resolve(client, client.patch("/api/agents/citizen-6/goals", json=nothing)).status_code
        == 422
    )


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
    found = resolve(
        client,
        client.post(
            "/api/businesses",
            json=command("citizen-0", plot_id="plot-3", kind="bakery", capital=6000),
        ),
    ).json()
    assert found["status"] == "applied"
    new_id = client.get("/api/businesses?owner=citizen-0&kind=bakery").json()[0]["building"]["id"]
    seq = found["sequence"]

    def step(method, path, body):
        nonlocal seq
        result = resolve(
            client, client.request(method, f"/api/businesses/{new_id}{path}", json=body)
        ).json()
        seq = result["sequence"]
        return result

    unasked = step("POST", "/hire", command("citizen-0", seq, citizen_id="citizen-5"))
    assert (unasked["status"], unasked["error"]) == ("rejected", "bad_params")
    seq = unasked["sequence"]
    applied = resolve(
        client,
        client.post("/api/agents/citizen-5/apply", json={**mutation(seq), "business_id": new_id}),
    ).json()
    assert applied["status"] == "applied"
    seq = applied["sequence"]
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
    result = resolve(client, client.post("/api/businesses/bakery/buy", json=body)).json()
    assert result["status"] == "applied"
    assert client.get("/api/agents/citizen-0").json()["citizen"]["inventory"]["bread"] == 3
    too_many = command(
        "citizen-0", result["sequence"], resource="bread", quantity=99, max_unit_price=500
    )
    rejected = resolve(client, client.post("/api/businesses/bakery/buy", json=too_many)).json()
    assert rejected["error"] == "out_of_stock"
    assert (
        resolve(
            client, client.post("/api/businesses/bakery/buy", json={**body, "quantity": 0})
        ).status_code
        == 422
    )


def test_resources_and_gather_route(client):
    assert client.get("/api/resources").json() == [
        {"kind": "wheat", "stock": 120, "regen_per_tick": 6, "cap": 200}
    ]
    body = {**mutation(), "resource": "wheat", "quantity": 4, "rationale": "Bring in the harvest"}
    result = resolve(client, client.post("/api/agents/citizen-3/gather", json=body)).json()
    assert result["status"] == "applied"
    assert client.get("/api/resources").json()[0]["stock"] == 116
    assert client.get("/api/businesses/farm").json()["building"]["inventory"]["wheat"] == 16
    event = client.get("/api/agents/citizen-3/history").json()[-1]
    assert event["type"] == "resource_gathered" and event["payload"]["quantity"] == 4
    unemployed = resolve(
        client,
        client.post("/api/agents/citizen-5/gather", json={**body, **mutation(result["sequence"])}),
    ).json()
    assert (unemployed["status"], unemployed["error"]) == ("rejected", "bad_params")
    assert resolve(client, client.post("/api/agents/missing/gather", json=body)).status_code == 404
    assert resolve(
        client, client.post("/api/agents/citizen-3/gather", json={**body, "quantity": 0})
    ).status_code == (422)


def test_jobs_listing_and_apply_quit_routes(client):
    jobs = client.get("/api/jobs").json()
    assert [j["building_id"] for j in jobs] == ["bakery", "farm", "market"]
    market = jobs[2]
    assert (market["free_slots"], market["wage"], market["plot_id"]) == (2, 150, "plot-2")
    assert market["position"] == {"x": 4.0, "z": -3.0} and market["applicant_ids"] == []
    assert client.get("/api/jobs?kind=farm").json()[0]["building_id"] == "farm"
    assert client.get("/api/jobs?min_wage=151").json() == []

    body = {**mutation(), "business_id": "market", "rationale": "I need work"}
    applied = resolve(client, client.post("/api/agents/citizen-5/apply", json=body)).json()
    assert applied["status"] == "applied"
    event = client.get("/api/agents/citizen-5/history").json()[-1]
    assert event["type"] == "job_applied" and event["rationale"] == "I need work"
    assert client.get("/api/jobs?kind=market").json()[0]["applicant_ids"] == ["citizen-5"]
    employed = resolve(
        client,
        client.post(
            "/api/agents/citizen-3/apply", json={**body, "expected_sequence": applied["sequence"]}
        ),
    )
    assert employed.json()["error"] == "already_employed"

    rejected = resolve(
        client,
        client.post(
            "/api/businesses/market/reject",
            json=command("citizen-2", employed.json()["sequence"], citizen_id="citizen-5"),
        ),
    ).json()
    assert rejected["status"] == "applied"
    assert client.get("/api/jobs?kind=market").json()[0]["applicant_ids"] == []

    quit_ = resolve(
        client,
        client.post(
            "/api/agents/citizen-3/quit",
            json={**mutation(rejected["sequence"]), "rationale": "Bored"},
        ),
    )
    assert quit_.json()["status"] == "applied"
    assert client.get("/api/agents/citizen-3").json()["employed"] is False
    assert client.get("/api/jobs?kind=farm").json()[0]["free_slots"] == 2
    again = resolve(
        client, client.post("/api/agents/citizen-3/quit", json=mutation(quit_.json()["sequence"]))
    ).json()
    assert (again["status"], again["error"]) == ("rejected", "bad_params")
    assert (
        resolve(
            client, client.post("/api/agents/missing/quit", json=mutation(again["sequence"]))
        ).status_code
        == 404
    )


def test_market_prices_and_history_routes(client):
    prices = client.get("/api/market/prices").json()
    bread = next(p for p in prices["prices"] if p["resource"] == "bread")
    assert bread == {"resource": "bread", "average": 500, "min": 500, "max": 500, "sellers": 3}
    body = command("citizen-1", resource="bread", price=800)
    changed = resolve(client, client.patch("/api/businesses/bakery/price", json=body)).json()
    assert changed["status"] == "applied"
    assert client.get("/api/market/prices?branch_id=main").json()["prices"][0]["average"] == 600
    history = client.get("/api/market/prices/history?good=bread").json()
    assert [(p["sequence"], p["average"], p["max"]) for p in history["points"]] == [
        (0, 500, 500),
        (int(changed["event_ids"][0].rsplit(":", 1)[1]), 600, 800),
    ]
    assert client.get("/api/market/prices/history?good=gold").status_code == 422
    assert client.get("/api/market/prices/history?good=bread&branch_id=nope").status_code == 404


def test_trade_offer_routes_round_trip(client):
    give, get = {"money": 300}, {"goods": {"bread": 1}}
    offered = resolve(
        client,
        client.post(
            "/api/market/trade",
            json=command("citizen-0", recipient_id="citizen-6", give=give, get=get),
        ),
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
    denied = resolve(client, client.post(path, json=command("citizen-0", seq, accept=True))).json()
    assert (denied["status"], denied["error"]) == ("rejected", "insufficient_authority")
    accepted = resolve(
        client, client.post(path, json=command("citizen-6", denied["sequence"], accept=True))
    ).json()
    assert accepted["status"] == "applied"
    finn = client.get("/api/agents/citizen-6").json()["citizen"]
    assert (finn["money"], finn["inventory"]["bread"]) == (850, 0)
    assert client.get("/api/agents/citizen-6/offers").json()["incoming"] == []
    again = resolve(
        client, client.post(path, json=command("citizen-6", accepted["sequence"], accept=True))
    ).json()
    assert again["error"] == "unknown_entity"
    assert client.get("/api/agents/missing/offers").status_code == 404


def test_lot_reads(client):
    listing = client.get("/api/lots").json()
    assert [lot["lot"]["id"] for lot in listing] == [f"plot-{i}" for i in range(6)]
    assert [lot["use"] for lot in listing] == ["business"] * 3 + ["empty", "empty", "home"]
    home = client.get("/api/lots/plot-5").json()
    assert (home["lot"]["owner_id"], home["lot"]["tenant_id"], home["lot"]["rent"]) == (
        "citizen-0",
        "citizen-5",
        300,
    )
    assert [lot["lot"]["id"] for lot in client.get("/api/lots?owner=citizen-0").json()] == [
        "plot-0",
        "plot-5",
    ]
    assert [lot["lot"]["id"] for lot in client.get("/api/lots?use=home").json()] == ["plot-5"]
    assert client.get("/api/lots?tenant=citizen-5").json()[0]["lot"]["id"] == "plot-5"
    assert client.get("/api/lots/missing").status_code == 404


def test_rent_routes_map_to_lot_actions(client):
    raised = resolve(
        client, client.patch("/api/lots/plot-5/rent", json=command("citizen-0", rent=360))
    ).json()
    assert raised["status"] == "applied"
    seq = raised["sequence"]
    too_far = resolve(
        client, client.patch("/api/lots/plot-5/rent", json=command("citizen-0", seq, rent=1000))
    )
    assert (too_far.json()["status"], too_far.json()["error"]) == ("rejected", "bad_params")
    seq = too_far.json()["sequence"]
    paid = resolve(
        client, client.post("/api/lots/plot-5/pay", json=command("citizen-5", seq))
    ).json()
    assert paid["status"] == "applied"
    assert client.get("/api/lots/plot-5").json()["lot"]["prepaid_periods"] == 1
    assert client.get("/api/agents/citizen-5").json()["citizen"]["money"] == 6000 - 360
    seq = paid["sequence"]
    evict = resolve(
        client, client.post("/api/lots/plot-5/evict", json=command("citizen-0", seq))
    ).json()
    assert (evict["status"], evict["error"]) == ("rejected", "bad_params")
    seq = evict["sequence"]
    lease = resolve(
        client, client.post("/api/lots/plot-5/lease", json=command("citizen-6", seq))
    ).json()
    assert (lease["status"], lease["error"]) == ("rejected", "lot_occupied")
    assert resolve(
        client, client.patch("/api/lots/plot-5/rent", json=command("citizen-0", rent=-1))
    ).status_code == (422)
