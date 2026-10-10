"""End-to-end check that every API endpoint reaches the simulation engine.

Starts a real server on a throwaway database (mock provider, never your .env), then:
mutations are queued, a day is advanced, and each queued action is read back from
/api/actions/{id}. "applied" or "rejected" with the engine's reason both prove the
endpoint is connected; an HTTP error, a crash, or an action stuck "queued" is a failure.
Reads, the clock, branches and the WebSocket are checked too.

    uv run python scripts/endpoint_check.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
SOURCES = ["backend/api/src"] + [
    f"backend/modules/{name}/src" for name in ("simulation", "agents", "history")
]

rows: list[tuple[str, str, str]] = []  # (endpoint, outcome, detail)
queued: list[tuple[str, str]] = []  # (endpoint, action_id) awaiting the next tick
failures = 0


def report(endpoint: str, outcome: str, detail: str = "") -> None:
    global failures
    ok = outcome in ("applied", "rejected", "read", "done")
    failures += not ok
    mark = "ok " if ok else "ERR"
    rows.append((endpoint, outcome, detail))
    print(f"  [{mark}] {endpoint:<58} {outcome:<9} {detail}"[:160], flush=True)


def ctx(client) -> dict:
    world = client.get("/api/world").json()
    return {"branch_id": world["branch_id"], "expected_sequence": world["sequence"]}


def submit(client, method: str, path: str, body: dict, label: str | None = None) -> dict:
    """Send a mutation; queue its action ID for the next tick's read-back."""
    label = label or f"{method} {path}"
    response = client.request(method, path, json={**ctx(client), **body})
    if response.status_code >= 400:
        report(label, f"HTTP {response.status_code}", response.text[:90])
        return {}
    data = response.json()
    record = data.get("result", data)
    if record.get("status") == "queued":
        queued.append((label, record["action_id"]))
    else:
        report(label, "done", json.dumps(data)[:90])
    return data


def tick(client, day_label: str) -> dict:
    print(f"\n-- advancing a day ({day_label}) --", flush=True)
    response = client.post("/api/simulation/tick", json=ctx(client))
    if response.status_code >= 400:
        report("POST /api/simulation/tick", f"HTTP {response.status_code}", response.text[:90])
        return {}
    result = response.json()
    report("POST /api/simulation/tick", "done", f"day {result['tick']}, seq {result['sequence']}")
    for label, action_id in queued:
        record = client.get(f"/api/actions/{action_id}").json()
        status = record.get("status", "missing")
        detail = record.get("message") or ", ".join(
            sorted({e.split(":")[0] for e in record.get("event_ids", [])})
        )
        if status == "applied":
            detail = f"{len(record.get('event_ids', []))} events"
        report(label, status, detail or "")
    if queued:
        report("GET /api/actions/{action_id}", "read", f"{len(queued)} outcomes read back")
    queued.clear()
    return result


def read(client, path: str, **params) -> object:
    response = client.get(path, params=params)
    if response.status_code >= 400:
        report(f"GET {path}", f"HTTP {response.status_code}", response.text[:90])
        return None
    data = response.json()
    size = f"{len(data)} items" if isinstance(data, list) else "object"
    report(f"GET {path}", "read", size)
    return data


def start_server(workdir: Path) -> subprocess.Popen:
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("KRONOS_")},
        "PYTHONPATH": os.pathsep.join(str(ROOT / s) for s in SOURCES),
        "KRONOS_DATABASE_URL": f"sqlite:///{workdir / 'check.db'}",
        "KRONOS_LLM_PROVIDER": "mock",
        "KRONOS_LLM_CACHE": "",
        "KRONOS_TICK_SECONDS": "3600",
    }
    env.pop("ANTHROPIC_API_KEY", None)
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "kronos.main:app", "--port", str(PORT)],
        cwd=workdir,  # no .env here, so the developer's settings and key are never read
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    for _ in range(100):
        try:
            if httpx.get(f"{BASE}/health", timeout=0.5).status_code == 200:
                return server
        except httpx.HTTPError:
            time.sleep(0.1)
    server.kill()
    raise SystemExit("Server did not start:\n" + server.stderr.read().decode()[-2000:])


def find(world: dict, collection: str, **match) -> str | None:
    for key, item in world["state"][collection].items():
        if all(item.get(k) == v for k, v in match.items()):
            return key
    return None


def run(client) -> None:
    read(client, "/health")
    print("\nDay 0 -> 1: actions, interventions and convenience routes", flush=True)
    buy = {"type": "buy", "actor_id": "citizen-6", "building_id": "bakery", "resource": "bread"}
    submit(
        client, "POST", "/api/actions", {"action": {**buy, "quantity": 1, "max_unit_price": 1000}}
    )
    submit(
        client,
        "POST",
        "/api/backend/actions",
        {"action": {"type": "move_to", "actor_id": "citizen-3", "plot_id": "plot-1"}},
    )
    talk = {"type": "communicate", "actor_id": "citizen-5", "recipient_id": "citizen-0"}
    submit(
        client,
        "POST",
        "/api/agents/citizen-5/actions",
        {"action": {**talk, "message": "Rent is fair this week."}},
    )
    dry = client.post(
        "/api/agents/citizen-6/actions/validate",
        json={**ctx(client), "action": {**buy, "quantity": 1, "max_unit_price": 1000}},
    )
    report(
        "POST /api/agents/{id}/actions/validate",
        "done" if dry.status_code == 200 else f"HTTP {dry.status_code}",
        "dry run, world unchanged",
    )
    submit(client, "POST", "/api/interventions", {"text": "Increase bread price by 10%"})
    submit(
        client,
        "POST",
        "/api/interventions",
        {"text": "Give 5 coins to Finn"},
        "POST /api/interventions (grant)",
    )
    submit(
        client,
        "PATCH",
        "/api/agents/citizen-6/goals",
        {"changes": {"wealth": 10, "safety": -10}},
        "PATCH /api/agents/{id}/goals",
    )
    submit(
        client,
        "POST",
        "/api/agents/citizen-3/gather",
        {"resource": "wheat", "quantity": 2},
        "POST /api/agents/{id}/gather",
    )
    submit(
        client,
        "POST",
        "/api/agents/citizen-6/apply",
        {"business_id": "market"},
        "POST /api/agents/{id}/apply",
    )
    submit(
        client,
        "POST",
        "/api/agents/citizen-5/apply",
        {"business_id": "farm"},
        "POST /api/agents/{id}/apply (2nd)",
    )
    submit(client, "POST", "/api/agents/citizen-4/quit", {}, "POST /api/agents/{id}/quit")
    submit(
        client,
        "PATCH",
        "/api/businesses/bakery/price",
        {"actor_id": "citizen-1", "resource": "bread", "price": 600},
        "PATCH /api/businesses/{id}/price",
    )
    submit(
        client,
        "PATCH",
        "/api/businesses/farm/wage",
        {"actor_id": "citizen-0", "wage": 160},
        "PATCH /api/businesses/{id}/wage",
    )
    submit(
        client,
        "POST",
        "/api/businesses/bakery/buy",
        {"actor_id": "citizen-5", "resource": "bread", "quantity": 1, "max_unit_price": 2000},
        "POST /api/businesses/{id}/buy",
    )
    submit(
        client,
        "POST",
        "/api/businesses",
        {"actor_id": "citizen-2", "plot_id": "plot-3", "kind": "farm", "capital": 5000},
    )
    submit(
        client,
        "POST",
        "/api/inventions/crop_rotation/research",
        {"actor_id": "citizen-0", "mode": "money", "amount": 1500},
        "POST /api/inventions/{id}/research",
    )
    submit(
        client,
        "POST",
        "/api/loans",
        {
            "actor_id": "citizen-0",
            "borrower_id": "citizen-6",
            "principal": 1000,
            "rate_bps": 500,
            "due_tick": 10,
        },
    )
    submit(
        client,
        "PATCH",
        "/api/lots/plot-5/rent",
        {"actor_id": "citizen-0", "rent": 400},
        "PATCH /api/lots/{id}/rent",
    )
    submit(
        client, "POST", "/api/lots/plot-5/pay", {"actor_id": "citizen-5"}, "POST /api/lots/{id}/pay"
    )
    submit(
        client,
        "POST",
        "/api/lots/plot-5/evict",
        {"actor_id": "citizen-0"},
        "POST /api/lots/{id}/evict",
    )
    submit(
        client,
        "POST",
        "/api/lots/plot-4/lease",
        {"actor_id": "citizen-6"},
        "POST /api/lots/{id}/lease",
    )
    submit(
        client,
        "POST",
        "/api/market/trade",
        {
            "actor_id": "citizen-0",
            "recipient_id": "citizen-6",
            "give": {"money": 200},
            "get": {"goods": {"bread": 1}},
        },
    )
    submit(
        client, "POST", "/api/votes", {"actor_id": "citizen-0", "kind": "min_wage", "value": 160}
    )
    submit(
        client,
        "POST",
        "/api/agents/citizen-0/interact",
        {"target_id": "citizen-6", "kind": "befriend"},
        "POST /api/agents/{id}/interact",
    )
    submit(client, "POST", "/api/agents/citizen-6/decide", {}, "POST /api/agents/{id}/decide")
    asked = client.post("/api/agents/citizen-6/ask", json={"question": "How are you?"})
    report(
        "POST /api/agents/{id}/ask",
        "done" if asked.status_code == 200 else f"HTTP {asked.status_code}",
        asked.json().get("answer", "")[:70],
    )
    spawned = client.post(
        "/api/agents",
        json={
            **ctx(client),
            "name": "Ivo",
            "occupation": "Mason",
            "plot_id": "plot-4",
            "money": 1000,
        },
    )
    report(
        "POST /api/agents (spawn)",
        "applied" if spawned.status_code == 201 else f"HTTP {spawned.status_code}",
        "immediate setup tool via Engine.spawn",
    )
    tick(client, "day 1")

    print("\nDay 1 -> 2: answers that need yesterday's IDs", flush=True)
    world = client.get("/api/world").json()
    loan_id = next(iter(client.get("/api/loans").json()), {}).get("id")
    offer = next(iter(client.get("/api/agents/citizen-6/offers").json()["incoming"]), {})
    vote_id = next(iter(client.get("/api/votes").json()), {}).get("vote", {}).get("id")
    new_farm = find(world, "buildings", owner_id="citizen-2", plot_id="plot-3")
    submit(
        client,
        "POST",
        "/api/businesses/market/hire",
        {"actor_id": "citizen-2", "citizen_id": "citizen-6"},
        "POST /api/businesses/{id}/hire",
    )
    submit(
        client,
        "POST",
        "/api/businesses/farm/reject",
        {"actor_id": "citizen-0", "citizen_id": "citizen-5"},
        "POST /api/businesses/{id}/reject",
    )
    submit(
        client,
        "POST",
        "/api/businesses/farm/fire",
        {"actor_id": "citizen-0", "citizen_id": "citizen-3"},
        "POST /api/businesses/{id}/fire",
    )
    if new_farm:
        submit(
            client,
            "POST",
            f"/api/businesses/{new_farm}/close",
            {"actor_id": "citizen-2"},
            "POST /api/businesses/{id}/close",
        )
    else:
        report("POST /api/businesses/{id}/close", "SKIPPED", "founding did not apply")
    if loan_id:
        submit(
            client,
            "POST",
            f"/api/loans/{loan_id}/respond",
            {"actor_id": "citizen-6", "accept": True},
            "POST /api/loans/{id}/respond",
        )
    if offer:
        submit(
            client,
            "POST",
            f"/api/market/trade/{offer['id']}/respond",
            {"actor_id": "citizen-6", "accept": True},
            "POST /api/market/trade/{id}/respond",
        )
    if vote_id:
        submit(
            client,
            "POST",
            f"/api/votes/{vote_id}/ballot",
            {"actor_id": "citizen-1", "choice": "yes"},
            "POST /api/votes/{id}/ballot",
        )
    submit(
        client,
        "POST",
        "/api/inventions/crop_rotation/license",
        {"actor_id": "citizen-0", "recipient_id": "citizen-2", "fee": 100},
        "POST /api/inventions/{id}/license",
    )
    submit(
        client,
        "POST",
        "/api/inventions/crop_rotation/adopt",
        {"actor_id": "citizen-0", "building_id": "farm"},
        "POST /api/inventions/{id}/adopt",
    )
    tick(client, "day 2")

    print("\nDay 2 -> 3: follow-ups", flush=True)
    license_offer = next(iter(client.get("/api/inventions/license-offers").json()), {})
    if license_offer:
        submit(
            client,
            "POST",
            f"/api/inventions/license-offers/{license_offer['id']}/respond",
            {"actor_id": "citizen-2", "accept": True},
            "POST /api/inventions/license-offers/{id}/respond",
        )
    if loan_id:
        submit(
            client,
            "POST",
            f"/api/loans/{loan_id}/repay",
            {"actor_id": "citizen-6", "amount": 200},
            "POST /api/loans/{id}/repay",
        )
    tick(client, "day 3")

    print("\nClock, branches and the WebSocket", flush=True)
    played = client.post("/api/simulation/play", json={**ctx(client), "speed": 2}).json()
    report(
        "POST /api/simulation/play", "done", f"playing={played['playing']} speed={played['speed']}"
    )
    paused = client.post("/api/simulation/pause", json={}).json()
    report("POST /api/simulation/pause", "done", f"playing={paused['playing']}")
    snapshots = read(client, "/api/history/snapshots", branch_id="main") or []
    if snapshots:
        first = snapshots[0]["id"]
        read(client, f"/api/history/snapshots/{first}")
        branch = client.post("/api/branches", json={"snapshot_id": first, "name": "Check fork"})
        report(
            "POST /api/branches",
            "done" if branch.status_code < 400 else f"HTTP {branch.status_code}",
            "fork from the first snapshot",
        )
        if branch.status_code < 400:
            fork_id = branch.json()["id"]
            moved = client.post(f"/api/branches/{fork_id}/activate", json={})
            report(
                "POST /api/branches/{id}/activate",
                "done" if moved.status_code == 200 else f"HTTP {moved.status_code}",
                f"active day {moved.json().get('tick')}",
            )
            read(client, f"/api/branches/{fork_id}/world")
            client.post("/api/branches/main/activate", json={})
    created = client.post("/api/simulations", json={})
    report(
        "POST /api/simulations",
        "done" if created.status_code == 201 else f"HTTP {created.status_code}",
        "new independent village (not activated)",
    )
    with httpx.Client(base_url=BASE) as _:
        try:
            from websockets.sync.client import connect

            with connect(f"ws://127.0.0.1:{PORT}/ws/world") as ws:
                frame = json.loads(ws.recv(timeout=5))
            report(
                "WS /ws/world",
                "read",
                f"initial frame: day {frame['tick']}, "
                f"{len(frame['state']['citizens'])} citizens, {len(frame['events'])} events",
            )
        except ImportError:
            report("WS /ws/world", "SKIPPED", "websockets package not installed")

    print("\nBranching, tracing and comparison", flush=True)
    origin = client.get("/api/history/snapshots", params={"branch_id": "main"}).json()[0]["id"]
    plain = client.post("/api/branches", json={"snapshot_id": origin, "name": "No change"})
    dear = client.post(
        "/api/branches",
        json={
            "snapshot_id": origin,
            "name": "Dear bread",
            "intervention": "Increase bread price by 40%",
        },
    )
    report(
        "POST /api/branches (with intervention)",
        "done" if dear.status_code == 201 else f"HTTP {dear.status_code}",
        f"seed={dear.json().get('seed')}, intervention={dear.json().get('intervention')!r}",
    )
    plain_id, dear_id = plain.json()["id"], dear.json()["id"]
    for branch_id in (plain_id, dear_id):
        started = client.post(
            f"/api/branches/{branch_id}/run", json={"ticks": 6, "agents": "utility"}
        )
        if started.status_code != 202:
            report("POST /api/branches/{id}/run", f"HTTP {started.status_code}", started.text[:80])
            continue
        for _ in range(300):
            status = client.get(f"/api/branches/{branch_id}/run").json()
            if status["status"] != "running":
                break
            time.sleep(0.02)
        report(
            "POST /api/branches/{id}/run",
            "done" if status["status"] == "done" else status["status"],
            f"{status['ticks_done']} days in the background, now day {status['tick']}",
        )
    report("GET /api/branches/{id}/run", "read", "progress polled until done")
    live = client.get("/api/world").json()
    report("live branch untouched", "done", f"active={live['branch_id']} day {live['tick']}")
    split = client.get("/api/branches/divergence", params={"a": plain_id, "b": dear_id}).json()
    first = split["decision_b"] or {}
    report(
        "GET /api/branches/divergence",
        "read",
        f"split on day {split['tick']}: {first.get('type')} -> "
        + ", ".join(e["type"] for e in split["chain_b"][:3]),
    )
    compared = client.get(
        "/api/branches/compare", params=[("ids", plain_id), ("ids", dear_id)]
    ).json()["branches"]
    last = {b["name"]: b["points"][-1] for b in compared}
    report(
        "GET /api/branches/compare",
        "read",
        f"day {last['Dear bread']['tick']} bread: "
        f"{last['No change']['bread_price']} vs {last['Dear bread']['bread_price']} cents, "
        f"Gini {last['No change']['gini_bps']} vs {last['Dear bread']['gini_bps']} bps",
    )
    hashes = [client.get(f"/api/branches/{b}/hashes").json() for b in (plain_id, dear_id)]
    report(
        "GET /api/branches/{id}/hashes",
        "read",
        f"{len(hashes[1])} daily hashes; day 1 equal across forks: "
        f"{hashes[0][0]['state_hash'] == hashes[1][0]['state_hash']}",
    )
    years = client.get(f"/api/branches/{dear_id}/checkpoints").json()
    report("GET /api/branches/{id}/checkpoints", "read", f"{len(years)} yearly checkpoint(s)")
    if first:
        traced = client.get(
            f"/api/events/{first['id']}/trace", params={"direction": "forward"}
        ).json()
        report(
            "GET /api/events/{id}/trace (forward)",
            "read",
            f"{len(traced['events'])} events, {len(traced['edges'])} links",
        )
        effect = next((e for e in split["chain_b"] if e["type"] == "price_changed"), None)
        if effect:
            back = client.get(f"/api/events/{effect['id']}/trace").json()
            report(
                "GET /api/events/{id}/trace (back)",
                "read",
                "price_changed <- " + ", ".join(e["type"] for e in back["events"][1:]),
            )
    filtered = client.get(
        "/api/events", params={"branch_id": dear_id, "type": "price_changed", "limit": 500}
    ).json()
    report("GET /api/events (filters)", "read", f"{len(filtered)} price_changed events on the fork")

    print("\nReads", flush=True)
    for path, params in [
        ("/api/world", {}),
        ("/api/simulation/status", {}),
        ("/api/events", {"after": 0}),
        ("/api/history/events", {"branch_id": "main"}),
        ("/api/branches", {}),
        ("/api/agents", {}),
        ("/api/agents/citizen-6", {}),
        ("/api/agents/citizen-6/observation", {}),
        ("/api/agents/citizen-6/history", {}),
        ("/api/agents/citizen-6/offers", {}),
        ("/api/agents/citizen-6/relationships", {}),
        ("/api/relationships/citizen-0/citizen-6", {}),
        ("/api/agents/citizen-0/influence", {}),
        ("/api/jobs", {}),
        ("/api/businesses", {}),
        ("/api/businesses/bakery", {}),
        ("/api/lots", {}),
        ("/api/lots/plot-5", {}),
        ("/api/loans", {}),
        ("/api/inventions", {}),
        ("/api/inventions/crop_rotation", {}),
        ("/api/inventions/license-offers", {}),
        ("/api/market/prices", {}),
        ("/api/market/prices/history", {"good": "bread"}),
        ("/api/resources", {}),
        ("/api/roles", {}),
        ("/api/votes", {}),
    ]:
        read(client, path, **params)
    if loan_id:
        read(client, f"/api/loans/{loan_id}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        server = start_server(Path(tmp))
        try:
            with httpx.Client(base_url=BASE, timeout=30) as client:
                run(client)
        finally:
            server.terminate()
            server.wait(timeout=10)
    counts: dict[str, int] = {}
    for _, outcome, _ in rows:
        counts[outcome] = counts.get(outcome, 0) + 1
    print(f"\n{len(rows)} checks: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
    print("FAILED" if failures else "All endpoints reached the engine.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
