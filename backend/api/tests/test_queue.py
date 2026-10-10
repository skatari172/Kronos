"""The Phase 1 loop uses real daily rules, persistence, and WebSocket transport."""

from fastapi.testclient import TestClient
from kronos.config import Settings
from kronos.main import create_app


def finish_decisions(client):
    async def finish():
        task = client.app.state.service.decision_task
        if task is not None:
            await task

    client.portal.call(finish)


def test_bread_purchase_and_rejection_are_queued_persisted_as_events_and_broadcast(tmp_path):
    config = Settings(database_url=f"sqlite:///{tmp_path / 'queue.db'}")
    ids = []
    with TestClient(create_app(config)) as client:
        before = client.get("/api/world").json()
        for citizen, quantity in (("citizen-3", 1), ("citizen-6", 2)):
            response = client.post(
                f"/api/agents/{citizen}/actions",
                json={
                    "branch_id": "main",
                    "expected_sequence": 0,
                    "action": {
                        "type": "buy",
                        "actor_id": citizen,
                        "building_id": "bakery",
                        "resource": "bread",
                        "quantity": quantity,
                        "max_unit_price": 500,
                        "rationale": "I need bread.",
                    },
                },
            )
            assert response.status_code == 200
            record = response.json()
            assert record["status"] == "queued" and record["scheduled_tick"] == 1
            ids.append(record["action_id"])
        assert client.get("/api/world").json() == before
        assert len(client.get("/api/history/snapshots?branch_id=main").json()) == 1
        with client.websocket_connect("/ws/world") as socket:
            assert socket.receive_json() == before
            tick = client.post(
                "/api/simulation/tick",
                json={
                    "branch_id": "main",
                    "expected_sequence": 0,
                },
            ).json()
            frame = socket.receive_json()
        assert frame["state"] == tick["state"]
        assert frame["events"] == tick["events"]
        applied, rejected = [client.get(f"/api/actions/{aid}").json() for aid in ids]
        assert applied["status"] == "applied" and applied["error"] is None
        assert rejected["status"] == "rejected" and rejected["error"] == "insufficient_funds"
        trade = [e for e in frame["events"] if e["action_id"] == ids[0]]
        assert len(trade) == 1 and trade[0]["payload"]["amount"] == 500
        assert trade[0]["payload"]["quantity"] == 1
        assert trade[0]["rationale"] == "I need bread."
        refused = [e for e in frame["events"] if e["action_id"] == ids[1]]
        assert [e["type"] for e in refused] == ["action_rejected"]
        assert frame["state"]["citizens"]["citizen-3"]["money"] == 450  # 800 - 500 + wage
        assert frame["state"]["citizens"]["citizen-6"]["money"] == 550
        assert client.get("/api/history/events?branch_id=main").json() == frame["events"]
        assert (
            client.app.state.service.store.world("main").model_dump(mode="json") == frame["state"]
        )
    with TestClient(create_app(config)) as restarted:
        assert restarted.get(f"/api/actions/{ids[0]}").status_code == 404
        assert restarted.get(f"/api/actions/{ids[1]}").status_code == 404
        history = restarted.get("/api/events?after=0&limit=500").json()
        assert {e["action_id"] for e in history} >= set(ids)
        assert restarted.get("/api/world").json()["state"] == frame["state"]


def test_runtime_action_is_not_replayed_after_restart(tmp_path):
    config = Settings(database_url=f"sqlite:///{tmp_path / 'restart.db'}")
    with TestClient(create_app(config)) as client:
        record = client.post(
            "/api/backend/actions",
            json={
                "branch_id": "main",
                "expected_sequence": 0,
                "action": {
                    "type": "transfer_money",
                    "actor_id": "citizen-0",
                    "recipient_id": "citizen-6",
                    "amount": 100,
                },
            },
        ).json()
    with TestClient(create_app(config)) as client:
        assert client.get(f"/api/actions/{record['action_id']}").status_code == 404
        result = client.post(
            "/api/simulation/tick",
            json={
                "branch_id": "main",
                "expected_sequence": 0,
            },
        ).json()
        assert result["action_results"] == []
        assert result["state"]["citizens"]["citizen-6"]["money"] == 550


def test_agents_deliberate_after_commit_and_buy_on_the_following_tick(tmp_path):
    config = Settings(database_url=f"sqlite:///{tmp_path / 'agents.db'}")
    with TestClient(create_app(config)) as client:
        first = client.post(
            "/api/simulation/tick",
            json={
                "branch_id": "main",
                "expected_sequence": 0,
            },
        ).json()
        assert not first["action_results"]  # No decisions applied during deliberation.
        finish_decisions(client)
        queued = client.app.state.service.pending()
        assert len(queued) == 7
        assert all(r.scheduled_tick == 2 and r.action.type == "buy" for r in queued)
        second = client.post(
            "/api/simulation/tick",
            json={
                "branch_id": "main",
                "expected_sequence": first["sequence"],
            },
        ).json()
        assert {r["action_id"] for r in second["action_results"]} == {r.action_id for r in queued}
        assert all(r["status"] == "applied" for r in second["action_results"])
        assert any(
            e["type"] == "transaction_completed" and e["action_id"] for e in second["events"]
        )
        assert second["state"]["citizens"]["citizen-6"]["money"] == 50


def test_frozen_batch_validates_conflicting_actions_in_stable_actor_order(tmp_path):
    from kronos_history.store import HistoryStore
    from kronos_sim.engine import Engine
    from kronos_sim.models import BranchMetadata, Buy, SetPrice
    from kronos_sim.seed import initial_world

    state = initial_world()
    state.buildings["bakery"].inventory.bread = 1
    store = HistoryStore(f"sqlite:///{tmp_path / 'ordering.db'}")
    store.create(state, BranchMetadata(id="main", name="Ordering"))
    # Network admission order is the opposite of actor order.
    batch = [
        store.enqueue(
            state,
            Buy(
                actor_id=cid, building_id="bakery", resource="bread", quantity=1, max_unit_price=500
            ),
        )
        for cid in ("citizen-6", "citizen-5")
    ]
    left = Engine(state).tick(queued=batch)
    right = Engine(state).tick(queued=list(reversed(batch)))
    assert left == right
    assert [(r.action.actor_id, r.status) for r in left.action_results] == [
        ("citizen-5", "applied"),
        ("citizen-6", "rejected"),
    ]
    assert left.action_results[-1].error == "out_of_stock"
    # Current state wins over the price the buyer originally observed.
    repriced = (
        Engine(state)
        .apply(SetPrice(actor_id="citizen-1", building_id="bakery", resource="bread", price=700))
        .state
    )
    result = Engine(repriced).tick(queued=batch)
    assert all(r.status == "rejected" for r in result.action_results)
    assert all(r.error == "bad_params" for r in result.action_results)
    assert result.state.citizens["citizen-6"].money == 550
    store.close()


def test_failed_save_keeps_queue_and_live_world_and_sends_no_frame(tmp_path, monkeypatch):
    import asyncio

    import pytest
    from kronos.service import Service
    from kronos_sim.models import ActionRequest

    async def scenario():
        service = Service(Settings(database_url=f"sqlite:///{tmp_path / 'rollback.db'}"))
        before = service.state.model_copy(deep=True)
        record = await service.execute_action(
            ActionRequest(
                branch_id="main",
                expected_sequence=0,
                action={
                    "type": "buy",
                    "actor_id": "citizen-6",
                    "building_id": "bakery",
                    "resource": "bread",
                    "quantity": 1,
                    "max_unit_price": 500,
                },
            )
        )
        frames = []

        async def capture(update):
            frames.append(update)

        def fail_snapshot(*args):
            raise RuntimeError("disk failure")

        monkeypatch.setattr(service, "broadcast", capture)
        monkeypatch.setattr(service.store, "_snapshot", fail_snapshot)
        with pytest.raises(RuntimeError, match="disk failure"):
            await service.tick()
        assert service.state == before and service.store.world("main") == before
        assert service.action_result(record.action_id).status == "queued"
        assert service.store.list_events("main") == [] and frames == []
        service.store.close()

    asyncio.run(scenario())


def test_slow_provider_cannot_hold_world_lock_or_execute_new_submissions(tmp_path):
    import asyncio
    import json

    from kronos.service import Service
    from kronos_sim.models import ActionRequest

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class SlowProvider:
            async def complete(self, task, observation):
                entered.set()
                await release.wait()
                return json.dumps(
                    {
                        "type": "communicate",
                        "actor_id": observation["citizen"]["id"],
                        "recipient_id": min(observation["neighbors"]),
                        "message": "Hello",
                    }
                )

        service = Service(Settings(database_url=f"sqlite:///{tmp_path / 'slow.db'}"))
        service.agents.provider = SlowProvider()
        task = asyncio.create_task(service.tick())
        await asyncio.wait_for(entered.wait(), 1)
        assert service.state.tick == 1  # Commit and broadcast precede provider work.
        record = await asyncio.wait_for(
            service.execute_action(
                ActionRequest(
                    branch_id="main",
                    expected_sequence=service.state.sequence,
                    action={
                        "type": "transfer_money",
                        "actor_id": "citizen-0",
                        "recipient_id": "citizen-6",
                        "amount": 100,
                    },
                )
            ),
            0.2,
        )
        assert record.status == "queued" and record.scheduled_tick == 2
        assert service.state.citizens["citizen-6"].money == 550
        result = await task
        assert result.tick == 1 and service.action_result(record.action_id).status == "queued"
        # Another day's mechanics complete even while this provider still waits.
        next_day = await asyncio.wait_for(service.tick(), 1)
        assert next_day.tick == 2 and service.action_result(record.action_id).status == "applied"
        release.set()
        await service.decision_task
        pending = service.pending()
        assert len(pending) == 7 and all(r.scheduled_tick == 3 for r in pending)
        service.store.close()

    asyncio.run(scenario())


def test_pending_actions_stay_with_their_branch_and_are_never_applied_twice(tmp_path):
    with TestClient(
        create_app(Settings(database_url=f"sqlite:///{tmp_path / 'branch.db'}"))
    ) as client:
        record = client.post(
            "/api/actions",
            json={
                "branch_id": "main",
                "expected_sequence": 0,
                "action": {
                    "type": "transfer_money",
                    "actor_id": "citizen-0",
                    "recipient_id": "citizen-6",
                    "amount": 100,
                },
            },
        ).json()
        snapshot = client.get("/api/history/snapshots?branch_id=main").json()[0]
        branch = client.post(
            "/api/branches", json={"snapshot_id": snapshot["id"], "name": "Copy"}
        ).json()
        client.post(f"/api/branches/{branch['id']}/activate")
        fork_day = client.post(
            "/api/simulation/tick",
            json={
                "branch_id": branch["id"],
                "expected_sequence": 0,
            },
        ).json()
        assert not fork_day["action_results"]
        assert client.get(f"/api/actions/{record['action_id']}").json()["status"] == "queued"
        client.post("/api/branches/main/activate")
        first = client.post(
            "/api/simulation/tick", json={"branch_id": "main", "expected_sequence": 0}
        ).json()
        client.post(
            "/api/simulation/tick",
            json={"branch_id": "main", "expected_sequence": first["sequence"]},
        )
        events = client.get("/api/history/events?branch_id=main&limit=500").json()
        tagged = [e for e in events if e["action_id"] == record["action_id"]]
        assert len(tagged) == 1 and tagged[0]["payload"]["amount"] == 100


def test_existing_jobs_inventions_loans_votes_and_rent_work_through_ticks(tmp_path, monkeypatch):
    from kronos_agents.provider import AgentService

    async def no_strategy(self, world, events=None):
        return []

    # Keep actual production, wages, rent, deadlines, and fallback hiring enabled.
    monkeypatch.setattr(AgentService, "propose", no_strategy)
    with TestClient(
        create_app(Settings(database_url=f"sqlite:///{tmp_path / 'systems.db'}"))
    ) as client:

        def advance():
            world = client.get("/api/world").json()
            return client.post(
                "/api/simulation/tick",
                json={
                    "branch_id": "main",
                    "expected_sequence": world["sequence"],
                },
            ).json()

        def submit(action):
            world = client.get("/api/world").json()
            response = client.post(
                "/api/actions",
                json={
                    "branch_id": "main",
                    "expected_sequence": world["sequence"],
                    "action": action,
                },
            )
            assert response.status_code == 200 and response.json()["status"] == "queued", (
                response.text
            )
            return response.json()["action_id"]

        def applied(action):
            aid = submit(action)
            result = advance()
            outcome = client.get(f"/api/actions/{aid}").json()
            assert outcome["status"] == "applied", outcome
            return result["state"]

        submit(
            {
                "type": "research",
                "actor_id": "citizen-0",
                "invention_id": "crop_rotation",
                "mode": "money",
                "amount": 1500,
            }
        )
        submit({"type": "apply_job", "actor_id": "citizen-5", "building_id": "market"})
        submit(
            {
                "type": "lend",
                "actor_id": "citizen-2",
                "recipient_id": "citizen-6",
                "principal": 100,
                "rate_bps": 0,
                "due_tick": 8,
            }
        )
        submit({"type": "propose_vote", "actor_id": "citizen-6", "kind": "min_wage", "value": 300})
        first = advance()["state"]
        assert first["inventions"]["crop_rotation"]["unlocked"]
        assert first["citizens"]["citizen-5"]["employer_id"] is None
        assert len(first["job_applications"]) == 1
        loan_id, vote_id = next(iter(first["loans"])), next(iter(first["votes"]))

        submit(
            {
                "type": "reject_application",
                "actor_id": "citizen-2",
                "building_id": "market",
                "citizen_id": "citizen-5",
            }
        )
        submit(
            {
                "type": "license_invention",
                "actor_id": "citizen-0",
                "invention_id": "crop_rotation",
                "recipient_id": "citizen-1",
                "fee": 300,
            }
        )
        submit(
            {"type": "respond_loan", "actor_id": "citizen-6", "loan_id": loan_id, "accept": True}
        )
        submit({"type": "vote", "actor_id": "citizen-1", "vote_id": vote_id, "choice": "yes"})
        second = advance()["state"]
        assert second["job_applications"] == {}
        assert second["citizens"]["citizen-5"]["employer_id"] is None
        assert second["loans"][loan_id]["status"] == "active"
        offer_id = next(iter(second["license_offers"]))
        submit(
            {
                "type": "respond_license",
                "actor_id": "citizen-1",
                "offer_id": offer_id,
                "accept": True,
            }
        )
        submit({"type": "repay", "actor_id": "citizen-6", "loan_id": loan_id, "amount": 100})
        third = advance()["state"]
        assert third["inventions"]["crop_rotation"]["licensees"] == ["citizen-1"]
        assert third["loans"][loan_id]["status"] == "repaid"
        fourth = applied(
            {
                "type": "adopt_invention",
                "actor_id": "citizen-0",
                "invention_id": "crop_rotation",
                "building_id": "farm",
            }
        )
        assert fourth["inventions"]["crop_rotation"]["adopters"] == ["farm"]
        assert fourth["votes"][vote_id]["status"] == "passed"
        assert fourth["policies"]["min_wage"] == 300
        assert all(b["wage"] >= 300 for b in fourth["buildings"].values())
        for _ in range(3):
            last = advance()
        assert last["tick"] == 7
        assert last["state"]["citizens"]["citizen-5"]["money"] == 5700
        assert any(
            e["type"] == "transaction_completed"
            and e["payload"]["sender_id"] == "citizen-5"
            and e["payload"]["amount"] == 300
            for e in last["events"]
        )
