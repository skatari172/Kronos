"""Explicitly advance the clock for route mapping tests.

These tests isolate HTTP-to-action mapping from daily mechanics. test_queue.py and
simulation module tests exercise the real automatic rules and provider loop.
"""


def resolve(client, response):
    if response.status_code != 200:
        return response
    record = response.json()
    if not isinstance(record, dict) or record.get("status") != "queued":
        return response
    world = client.get("/api/world").json()
    tick = client.post(
        "/api/simulation/tick",
        json={
            "branch_id": world["branch_id"],
            "expected_sequence": world["sequence"],
        },
    )
    assert tick.status_code == 200
    return client.get(f"/api/actions/{record['action_id']}")
