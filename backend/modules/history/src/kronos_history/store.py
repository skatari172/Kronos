import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from kronos_sim.models import (
    BranchMetadata,
    SimulationEvent,
    SnapshotMetadata,
    WorldState,
    WorldUpdate,
)
from pydantic import TypeAdapter
from sqlalchemy import (
    Column,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    event,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.engine import make_url

metadata = MetaData()
branches = Table(
    "branches",
    metadata,
    Column("id", String, primary_key=True),
    Column("metadata", String, nullable=False),
    Column("state", String, nullable=False),
)
snapshots = Table(
    "snapshots",
    metadata,
    Column("id", String, primary_key=True),
    Column("branch_id", String, nullable=False, index=True),
    Column("sequence", Integer, nullable=False),
    Column("metadata", String, nullable=False),
    Column("state", String, nullable=False),
    Index("ix_snapshots_branch_sequence", "branch_id", "sequence"),
)
events = Table(
    "events",
    metadata,
    Column("id", String, primary_key=True),
    Column("branch_id", String, nullable=False, index=True),
    Column("sequence", Integer, nullable=False),
    Column("data", String, nullable=False),
    Index("ix_events_branch_sequence", "branch_id", "sequence"),
)
# Payload fields that name the citizen an event happened to.
INVOLVEMENT_KEYS = ("sender_id", "recipient_id", "entity_id", "citizen_id")
settings = Table(
    "settings", metadata, Column("key", String, primary_key=True), Column("value", String)
)


class HistoryStore:
    def __init__(self, url: str):
        url_obj = make_url(url)
        if url_obj.drivername.startswith("sqlite"):
            db_file = url_obj.database
            if db_file and db_file != ":memory:":
                Path(db_file).resolve().parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        metadata.create_all(self.engine)

    def close(self):
        self.engine.dispose()

    def active_id(self) -> str | None:
        with self.engine.connect() as db:
            return db.execute(select(settings.c.value).where(settings.c.key == "active")).scalar()

    def activate(self, branch_id: str):
        self.world(branch_id)
        with self.engine.begin() as db:
            exists = db.execute(select(settings.c.key).where(settings.c.key == "active")).scalar()
            if exists:
                db.execute(
                    update(settings).where(settings.c.key == "active").values(value=branch_id)
                )
            else:
                db.execute(insert(settings).values(key="active", value=branch_id))

    def _snapshot(self, db, state: WorldState) -> SnapshotMetadata:
        raw = state.model_dump_json()
        meta = SnapshotMetadata(
            id=str(uuid4()),
            branch_id=state.branch_id,
            tick=state.tick,
            sequence=state.sequence,
            created_at=datetime.now(UTC).isoformat(),
            integrity_hash=hashlib.sha256(raw.encode()).hexdigest(),
        )
        db.execute(
            insert(snapshots).values(
                id=meta.id,
                branch_id=state.branch_id,
                sequence=state.sequence,
                metadata=meta.model_dump_json(),
                state=raw,
            )
        )
        return meta

    def create(self, state: WorldState, meta: BranchMetadata):
        with self.engine.begin() as db:
            db.execute(
                insert(branches).values(
                    id=meta.id, metadata=meta.model_dump_json(), state=state.model_dump_json()
                )
            )
            self._snapshot(db, state)

    def commit(self, result: WorldUpdate, expected_sequence: int):
        state = result.state
        with self.engine.begin() as db:
            current = db.execute(
                select(branches.c.state).where(branches.c.id == state.branch_id)
            ).scalar()
            if current is None or json.loads(current)["sequence"] != expected_sequence:
                raise ValueError("Concurrent or stale world update")
            if not result.events or result.events[0].sequence != expected_sequence + 1:
                raise ValueError("Commit requires contiguous events")
            for index, event in enumerate(result.events, expected_sequence + 1):
                if event.sequence != index or event.branch_id != state.branch_id:
                    raise ValueError("Event stream mismatch")
                db.execute(
                    insert(events).values(
                        id=event.id,
                        branch_id=event.branch_id,
                        sequence=event.sequence,
                        data=event.model_dump_json(),
                    )
                )
            if result.events[-1].sequence != state.sequence:
                raise ValueError("State and event versions differ")
            db.execute(
                update(branches)
                .where(branches.c.id == state.branch_id)
                .values(state=state.model_dump_json())
            )
            # Every commit is a checkpoint: simple, exact historical reconstruction, no LLM replay.
            self._snapshot(db, state)

    def world(self, branch_id: str) -> WorldState:
        with self.engine.connect() as db:
            raw = db.execute(select(branches.c.state).where(branches.c.id == branch_id)).scalar()
        if raw is None:
            raise KeyError("Unknown branch")
        return WorldState.model_validate_json(raw)

    def list_branches(self) -> list[BranchMetadata]:
        with self.engine.connect() as db:
            return [
                BranchMetadata.model_validate_json(raw)
                for raw in db.execute(select(branches.c.metadata).order_by(branches.c.id)).scalars()
            ]

    def list_snapshots(self, branch_id: str) -> list[SnapshotMetadata]:
        with self.engine.connect() as db:
            return [
                SnapshotMetadata.model_validate_json(raw)
                for raw in db.execute(
                    select(snapshots.c.metadata)
                    .where(snapshots.c.branch_id == branch_id)
                    .order_by(snapshots.c.sequence)
                ).scalars()
            ]

    def restore(self, snapshot_id: str) -> WorldState:
        with self.engine.connect() as db:
            row = (
                db.execute(select(snapshots).where(snapshots.c.id == snapshot_id))
                .mappings()
                .first()
            )
        if row is None:
            raise KeyError("Unknown snapshot")
        meta = SnapshotMetadata.model_validate_json(row["metadata"])
        if hashlib.sha256(row["state"].encode()).hexdigest() != meta.integrity_hash:
            raise ValueError("Snapshot integrity check failed")
        return WorldState.model_validate_json(row["state"])

    def list_events(
        self, branch_id: str, through: int | None = None, limit: int = 100
    ) -> list[SimulationEvent]:
        query = select(events.c.data).where(events.c.branch_id == branch_id)
        if through is not None:
            query = query.where(events.c.sequence <= through)
        with self.engine.connect() as db:
            rows = list(db.execute(query.order_by(events.c.sequence.desc()).limit(limit)).scalars())
        adapter = TypeAdapter(SimulationEvent)
        return [adapter.validate_json(raw) for raw in reversed(rows)]

    def list_events_of_types(
        self, branch_id: str, types: tuple[str, ...], after: int = 0
    ) -> list[SimulationEvent]:
        """Every event of the given types after a sequence, oldest first. Unbounded."""
        if not types:
            return []
        query = select(events.c.data).where(
            events.c.branch_id == branch_id,
            events.c.sequence > after,
            # Coarse text prefilter on the compact JSON; the exact type check below decides.
            or_(*(events.c.data.contains(f'"type":"{t}"', autoescape=True) for t in types)),
        )
        adapter = TypeAdapter(SimulationEvent)
        with self.engine.connect() as db:
            rows = db.execute(query.order_by(events.c.sequence)).scalars()
            parsed = [adapter.validate_json(raw) for raw in rows]
        return [event for event in parsed if event.type in types]

    def first_snapshot(self, branch_id: str) -> WorldState:
        """The branch's starting world (seed or fork point)."""
        with self.engine.connect() as db:
            snapshot_id = db.execute(
                select(snapshots.c.id)
                .where(snapshots.c.branch_id == branch_id)
                .order_by(snapshots.c.sequence)
                .limit(1)
            ).scalar()
        if snapshot_id is None:
            raise KeyError("Unknown branch")
        return self.restore(snapshot_id)

    def list_events_after(
        self, branch_id: str, after: int, limit: int = 100
    ) -> list[SimulationEvent]:
        query = (
            select(events.c.data)
            .where(events.c.branch_id == branch_id, events.c.sequence > after)
            .order_by(events.c.sequence)
            .limit(limit)
        )
        with self.engine.connect() as db:
            rows = list(db.execute(query).scalars())
        adapter = TypeAdapter(SimulationEvent)
        return [adapter.validate_json(raw) for raw in rows]

    def list_citizen_events(
        self, branch_id: str, citizen_id: str, through: int | None = None, limit: int = 100
    ) -> list[SimulationEvent]:
        """Events where the citizen is the actor, sender, recipient, or subject; oldest first."""
        query = select(events.c.data).where(
            events.c.branch_id == branch_id,
            # Coarse text prefilter; the exact check below decides.
            events.c.data.contains(json.dumps(citizen_id), autoescape=True),
        )
        if through is not None:
            query = query.where(events.c.sequence <= through)
        adapter = TypeAdapter(SimulationEvent)
        found: list[SimulationEvent] = []
        with self.engine.connect() as db:
            for raw in db.execute(query.order_by(events.c.sequence.desc())).scalars():
                event = adapter.validate_json(raw)
                payload = event.payload.model_dump()
                subjects = {payload.get(key) for key in INVOLVEMENT_KEYS}
                if event.actor_id == citizen_id or citizen_id in subjects:
                    found.append(event)
                    if len(found) == limit:
                        break
        return list(reversed(found))
