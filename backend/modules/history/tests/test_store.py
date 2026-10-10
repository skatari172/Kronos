import pytest
from kronos_history.store import HistoryStore, events
from kronos_sim.engine import Engine
from kronos_sim.models import BranchMetadata, PriceIntervention
from kronos_sim.seed import initial_world
from sqlalchemy import insert


@pytest.fixture
def store(tmp_path):
    store = HistoryStore(f"sqlite:///{tmp_path / 'test.db'}")
    store.create(initial_world(), BranchMetadata(id="main", name="Original"))
    yield store
    store.close()


def test_snapshot_restore_and_rng_resume(store):
    result = Engine(store.world("main")).tick()
    store.commit(result, 0)
    snapshot = store.list_snapshots("main")[-1]
    restored = store.restore(snapshot.id)
    assert restored == result.state
    assert Engine(restored).tick() == Engine(result.state).tick()
    assert store.list_events("main") == result.events


def test_branch_isolation_and_immutable_past(store):
    snapshot = store.list_snapshots("main")[0]
    original = store.restore(snapshot.id)
    fork = Engine(original).fork("alternate")
    store.create(
        fork,
        BranchMetadata(
            id="alternate",
            name="Alternate",
            parent_branch_id="main",
            source_snapshot_id=snapshot.id,
        ),
    )
    result = Engine(fork).intervene(PriceIntervention(percent=40), "Increase bread price by 40%")
    store.commit(result, 0)
    assert store.world("main") == original
    assert store.restore(snapshot.id) == original
    assert store.world("alternate").buildings["bakery"].prices["bread"] == 700
    assert store.list_events("main") == []
    assert all(e.branch_id == "alternate" for e in store.list_events("alternate"))


def test_failed_commit_rolls_back_state_events_and_snapshot(store):
    result = Engine(store.world("main")).tick()
    # Force a duplicate midway through insertion to exercise the database transaction.
    with store.engine.begin() as db:
        e = result.events[1]
        db.execute(
            insert(events).values(
                id=e.id, branch_id=e.branch_id, sequence=e.sequence, data=e.model_dump_json()
            )
        )
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        store.commit(result, 0)
    assert store.world("main").tick == 0
    assert len(store.list_events("main")) == 1
    assert len(store.list_snapshots("main")) == 1


def test_stale_commit_is_rejected(store):
    result = Engine(store.world("main")).tick()
    store.commit(result, 0)
    with pytest.raises(ValueError, match="stale"):
        store.commit(result, 0)


def test_history_store_creates_parent_directory(tmp_path):
    nested_db = tmp_path / "deeply" / "nested" / "database" / "store.db"
    assert not nested_db.parent.exists()
    store = HistoryStore(f"sqlite:///{nested_db}")
    assert nested_db.parent.exists()
    store.close()
