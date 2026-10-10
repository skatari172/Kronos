import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from kronos_sim.models import (
    ActionResult,
    BranchMetadata,
    SimulationEvent,
    SnapshotMetadata,
    WorldState,
    WorldUpdate,
)
from pydantic import TypeAdapter
from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    event,
    func,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.engine import make_url

metadata = MetaData()

# History infrastructure tables
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
    Column("branch_id", String, nullable=False, default="main", index=True),
    Column("sequence", Integer, nullable=False),
    Column("tick", Integer, nullable=False, default=0),
    Column("type", String, nullable=False, default=""),
    Column("actor_id", String, nullable=True),
    Column("payload", String, nullable=False, default="{}"),
    Column("data", String, nullable=False, default="{}"),
    Column("created_at", String, nullable=False, default=""),
    Index("ix_events_branch_sequence", "branch_id", "sequence"),
)

actions = Table(
    "actions",
    metadata,
    Column("id", String, primary_key=True),
    Column("branch_id", String, nullable=False, index=True),
    Column("ordinal", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("data", String, nullable=False),
    Index("ix_actions_branch_status", "branch_id", "status"),
)

# Payload fields that name the citizen an event happened to.
INVOLVEMENT_KEYS = ("sender_id", "recipient_id", "entity_id", "citizen_id")
settings = Table(
    "settings", metadata, Column("key", String, primary_key=True), Column("value", String)
)

# Relational Tables (KRONOS v1 + Economy Data Model)
world_table = Table(
    "world",
    metadata,
    Column("id", String, primary_key=True),
    Column("tick", Integer, nullable=False, default=0),
    Column("sequence", Integer, nullable=False, default=0),
    Column("seed", Integer, nullable=False, default=42),
    Column("rng_state", String, nullable=False),
    Column("playing", Integer, nullable=False, default=0),
    Column("speed", Integer, nullable=False, default=1),
    Column("market_tax_bps", Integer, nullable=False, default=0),
    Column("bread_price_cap", Integer, nullable=False, default=0),
    Column("min_wage", Integer, nullable=False, default=0),
)

plots_table = Table(
    "plots",
    metadata,
    Column("id", String, primary_key=True),
    Column("position_x", Float, nullable=False),
    Column("position_z", Float, nullable=False),
    Column("owner_id", String, ForeignKey("citizens.id", ondelete="SET NULL"), nullable=True),
    Column("tenant_id", String, ForeignKey("citizens.id", ondelete="SET NULL"), nullable=True),
    Column("rent", Integer, nullable=False, default=0),
    Column("arrears", Integer, nullable=False, default=0),
    Column("missed_periods", Integer, nullable=False, default=0),
    Column("prepaid_periods", Integer, nullable=False, default=0),
)

inventions_table = Table(
    "inventions",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("cost", Integer, nullable=False),
    Column("progress", Integer, nullable=False, default=0),
    Column("contributors", String, nullable=False, default="{}"),
    Column("unlocked", Integer, nullable=False, default=0),
    Column("owner_id", String, ForeignKey("citizens.id", ondelete="SET NULL"), nullable=True),
    Column("licensees", String, nullable=False, default="[]"),
    Column("adopters", String, nullable=False, default="[]"),
    Column("adoption_cost", Integer, nullable=False, default=1000),
    Column("building_kind", String, nullable=False),
    Column("resource", String, nullable=False),
    Column("multiplier_pct", Integer, nullable=False),
)

citizens_table = Table(
    "citizens",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("occupation", String, nullable=False),
    Column("employer_id", String, ForeignKey("buildings.id", ondelete="SET NULL"), nullable=True),
    Column("money", Integer, nullable=False),
    Column("hunger", Integer, nullable=False),
    Column("wheat", Integer, nullable=False, default=0),
    Column("bread", Integer, nullable=False, default=0),
    Column("position_x", Float, nullable=False),
    Column("position_z", Float, nullable=False),
    Column("reputation", Integer, nullable=False, default=50),
    Column("destitute_days", Integer, nullable=False, default=0),
    Column("personality", String, nullable=False, default="practical"),
    Column("goals", String, nullable=False, default='["Stay fed", "Save for tomorrow"]'),
    Column(
        "goal_weights",
        String,
        nullable=False,
        default='{"wealth": 25, "influence": 25, "safety": 25, "reputation": 25}',
    ),
    Column("relationships", String, nullable=False, default="[]"),
    Column("memories", String, nullable=False, default="[]"),
    Column("memory_summary", String, nullable=False, default=""),
    Column("memory_tally", String, nullable=False, default="{}"),
    Column(
        "research_invention_id",
        String,
        ForeignKey("inventions.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("research_start_tick", Integer, nullable=False, default=0),
    Column("research_until_tick", Integer, nullable=False, default=0),
)

buildings_table = Table(
    "buildings",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("level", Integer, nullable=False, default=1),
    Column("owner_id", String, ForeignKey("citizens.id"), nullable=False),
    Column("plot_id", String, ForeignKey("plots.id"), nullable=False, unique=True),
    Column("cash", Integer, nullable=False, default=0),
    Column("wheat", Integer, nullable=False, default=0),
    Column("bread", Integer, nullable=False, default=0),
    Column("bread_price", Integer, nullable=False, default=500),
    Column("wheat_price", Integer, nullable=False, default=100),
    Column("wage", Integer, nullable=False, default=150),
    Column("job_slots", Integer, nullable=False, default=3),
    Column("unpaid_days", Integer, nullable=False, default=0),
)

resources_table = Table(
    "resources",
    metadata,
    Column("kind", String, primary_key=True),
    Column("stock", Integer, nullable=False, default=0),
    Column("regen_per_tick", Integer, nullable=False, default=0),
    Column("cap", Integer, nullable=True),
)

job_applications_table = Table(
    "job_applications",
    metadata,
    Column("id", String, primary_key=True),
    Column("citizen_id", String, nullable=False),
    Column("building_id", String, nullable=False),
    Column("status", String, nullable=False, default="pending"),
    Column("tick", Integer, nullable=False, default=0),
    Column("sequence", Integer, nullable=False, default=0),
)

loans_table = Table(
    "loans",
    metadata,
    Column("id", String, primary_key=True),
    Column("lender_id", String, nullable=False),
    Column("borrower_id", String, nullable=False),
    Column("principal", Integer, nullable=False),
    Column("rate_bps", Integer, nullable=False),
    Column("due_tick", Integer, nullable=False),
    Column("amount_owed", Integer, nullable=False),
    Column("amount_repaid", Integer, nullable=False, default=0),
    Column("status", String, nullable=False, default="offered"),
    Column("created_tick", Integer, nullable=False, default=0),
)

trade_offers_table = Table(
    "trade_offers",
    metadata,
    Column("id", String, primary_key=True),
    Column("offerer_id", String, ForeignKey("citizens.id", ondelete="CASCADE"), nullable=False),
    Column("recipient_id", String, ForeignKey("citizens.id", ondelete="CASCADE"), nullable=False),
    Column("give_money", Integer, nullable=False, default=0),
    Column("give_wheat", Integer, nullable=False, default=0),
    Column("give_bread", Integer, nullable=False, default=0),
    Column("get_money", Integer, nullable=False, default=0),
    Column("get_wheat", Integer, nullable=False, default=0),
    Column("get_bread", Integer, nullable=False, default=0),
    Column("created_tick", Integer, nullable=False, default=0),
    Column("expires_tick", Integer, nullable=False, default=0),
    Column("event_id", String, nullable=True),
    Column("rationale", String, nullable=True),
)

license_offers_table = Table(
    "license_offers",
    metadata,
    Column("id", String, primary_key=True),
    Column("invention_id", String, ForeignKey("inventions.id", ondelete="CASCADE"), nullable=False),
    Column("owner_id", String, ForeignKey("citizens.id", ondelete="CASCADE"), nullable=False),
    Column("recipient_id", String, ForeignKey("citizens.id", ondelete="CASCADE"), nullable=False),
    Column("fee", Integer, nullable=False, default=0),
    Column("tick", Integer, nullable=False, default=0),
)

votes_table = Table(
    "votes",
    metadata,
    Column("id", String, primary_key=True),
    Column("proposer_id", String, ForeignKey("citizens.id", ondelete="CASCADE"), nullable=False),
    Column("kind", String, nullable=False),
    Column("value", Integer, nullable=False),
    Column("rationale", String, nullable=True),
    Column("opens_tick", Integer, nullable=False, default=0),
    Column("closes_tick", Integer, nullable=False, default=0),
    Column("status", String, nullable=False, default="open"),
    Column("ballots", String, nullable=False, default="{}"),
    Column("yes_weight", Integer, nullable=False, default=0),
    Column("no_weight", Integer, nullable=False, default=0),
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

    def _sync_relational(self, db, state: WorldState, playing: bool = False, speed: int = 1):
        db.execute(text("PRAGMA defer_foreign_keys = ON"))

        # 1. World & policies
        rng_raw = json.dumps(state.rng_state)
        w_exists = db.execute(
            select(world_table.c.id).where(world_table.c.id == state.branch_id)
        ).scalar()
        policies = getattr(state, "policies", None)
        tax_bps = getattr(policies, "market_tax_bps", 0) if policies else 0
        price_cap = getattr(policies, "bread_price_cap", 0) if policies else 0
        min_wage = getattr(policies, "min_wage", 0) if policies else 0
        w_values = dict(
            id=state.branch_id,
            tick=state.tick,
            sequence=state.sequence,
            seed=state.seed,
            rng_state=rng_raw,
            playing=1 if playing else 0,
            speed=speed,
            market_tax_bps=tax_bps,
            bread_price_cap=price_cap,
            min_wage=min_wage,
        )
        if w_exists:
            db.execute(
                update(world_table).where(world_table.c.id == state.branch_id).values(**w_values)
            )
        else:
            db.execute(insert(world_table).values(**w_values))

        # 2. Citizens (Pass 1: employer_id=None, research_invention_id=None to break circular FKs)
        existing_citizens = set(db.execute(select(citizens_table.c.id)).scalars())
        current_citizens = set(state.citizens.keys())
        for cid in existing_citizens - current_citizens:
            db.execute(delete(citizens_table).where(citizens_table.c.id == cid))

        for c in state.citizens.values():
            gw = getattr(c, "goal_weights", None)
            gw_dict = gw.model_dump() if hasattr(gw, "model_dump") else {}
            values = dict(
                id=c.id,
                name=c.name,
                occupation=c.occupation,
                employer_id=c.employer_id if c.id in existing_citizens else None,
                money=c.money,
                hunger=c.hunger,
                wheat=c.inventory.wheat,
                bread=c.inventory.bread,
                position_x=float(c.position.x),
                position_z=float(c.position.z),
                reputation=getattr(c, "reputation", 50),
                destitute_days=getattr(c, "destitute_days", 0),
                personality=getattr(c, "personality", "practical"),
                goals=json.dumps(getattr(c, "goals", [])),
                goal_weights=json.dumps(gw_dict),
                relationships=json.dumps([r.model_dump() for r in getattr(c, "relationships", [])]),
                memories=json.dumps(getattr(c, "memories", [])),
                memory_summary=getattr(c, "memory_summary", ""),
                memory_tally=json.dumps(getattr(c, "memory_tally", {})),
                research_invention_id=None,
                research_start_tick=getattr(c, "research_start_tick", 0),
                research_until_tick=getattr(c, "research_until_tick", 0),
            )
            if c.id in existing_citizens:
                stmt = update(citizens_table).where(citizens_table.c.id == c.id).values(**values)
                db.execute(stmt)
            else:
                db.execute(insert(citizens_table).values(**values))

        # 3. Plots
        for p in state.plots.values():
            p_exists = db.execute(select(plots_table.c.id).where(plots_table.c.id == p.id)).scalar()
            values = dict(
                id=p.id,
                position_x=float(p.position.x),
                position_z=float(p.position.z),
                owner_id=getattr(p, "owner_id", None),
                tenant_id=getattr(p, "tenant_id", None),
                rent=getattr(p, "rent", 0),
                arrears=getattr(p, "arrears", 0),
                missed_periods=getattr(p, "missed_periods", 0),
                prepaid_periods=getattr(p, "prepaid_periods", 0),
            )
            if p_exists:
                db.execute(update(plots_table).where(plots_table.c.id == p.id).values(**values))
            else:
                db.execute(insert(plots_table).values(**values))

        # 4. Inventions
        inventions = getattr(state, "inventions", {})
        existing_inventions = set(db.execute(select(inventions_table.c.id)).scalars())
        for inv in inventions.values():
            effect = inv.effect
            values = dict(
                id=inv.id,
                name=inv.name,
                cost=inv.cost,
                progress=inv.progress,
                contributors=json.dumps(inv.contributors),
                unlocked=1 if inv.unlocked else 0,
                owner_id=inv.owner_id,
                licensees=json.dumps(inv.licensees),
                adopters=json.dumps(inv.adopters),
                adoption_cost=inv.adoption_cost,
                building_kind=effect.building_kind,
                resource=effect.resource,
                multiplier_pct=effect.multiplier_pct,
            )
            if inv.id in existing_inventions:
                db.execute(
                    update(inventions_table).where(inventions_table.c.id == inv.id).values(**values)
                )
            else:
                db.execute(insert(inventions_table).values(**values))

        # 5. Buildings
        existing_buildings = set(db.execute(select(buildings_table.c.id)).scalars())
        current_buildings = set(state.buildings.keys())
        for bid in existing_buildings - current_buildings:
            db.execute(delete(buildings_table).where(buildings_table.c.id == bid))

        for b in state.buildings.values():
            values = dict(
                id=b.id,
                name=b.name,
                kind=b.kind,
                level=b.level,
                owner_id=b.owner_id,
                plot_id=b.plot_id,
                cash=b.cash,
                wheat=b.inventory.wheat,
                bread=b.inventory.bread,
                bread_price=b.prices.get("bread", 500),
                wheat_price=b.prices.get("wheat", 100),
                wage=b.wage,
                job_slots=b.job_slots,
                unpaid_days=getattr(b, "unpaid_days", 0),
            )
            if b.id in existing_buildings:
                stmt = update(buildings_table).where(buildings_table.c.id == b.id).values(**values)
                db.execute(stmt)
            else:
                db.execute(insert(buildings_table).values(**values))

        # 6. Citizens (Pass 2: update employer_id & research_invention_id)
        for c in state.citizens.values():
            upd = {}
            if c.employer_id is not None:
                upd["employer_id"] = c.employer_id
            if getattr(c, "research_invention_id", None) is not None:
                upd["research_invention_id"] = c.research_invention_id
            if upd:
                db.execute(update(citizens_table).where(citizens_table.c.id == c.id).values(**upd))

        # 8. Resources
        resources = getattr(state, "resources", {})
        for r in resources.values():
            r_exists = db.execute(
                select(resources_table.c.kind).where(resources_table.c.kind == r.kind)
            ).scalar()
            values = dict(
                kind=r.kind,
                stock=r.stock,
                regen_per_tick=r.regen_per_tick,
                cap=r.cap,
            )
            if r_exists:
                db.execute(
                    update(resources_table).where(resources_table.c.kind == r.kind).values(**values)
                )
            else:
                db.execute(insert(resources_table).values(**values))

        # 9. Job Applications
        job_apps = getattr(state, "job_applications", {})
        existing_apps = set(db.execute(select(job_applications_table.c.id)).scalars())
        current_apps = set(job_apps.keys())
        for aid in existing_apps - current_apps:
            db.execute(delete(job_applications_table).where(job_applications_table.c.id == aid))
        for ja in job_apps.values():
            values = dict(
                id=ja.id,
                citizen_id=ja.citizen_id,
                building_id=ja.building_id,
                status=ja.status,
                tick=ja.tick,
                sequence=getattr(ja, "sequence", 0),
            )
            if ja.id in existing_apps:
                db.execute(
                    update(job_applications_table)
                    .where(job_applications_table.c.id == ja.id)
                    .values(**values)
                )
            else:
                db.execute(insert(job_applications_table).values(**values))

        # 10. Loans
        loans = getattr(state, "loans", {})
        existing_loans = set(db.execute(select(loans_table.c.id)).scalars())
        current_loans = set(loans.keys())
        for lid in existing_loans - current_loans:
            db.execute(delete(loans_table).where(loans_table.c.id == lid))
        for ln in loans.values():
            values = dict(
                id=ln.id,
                lender_id=ln.lender_id,
                borrower_id=ln.borrower_id,
                principal=ln.principal,
                rate_bps=ln.rate_bps,
                due_tick=ln.due_tick,
                amount_owed=ln.amount_owed,
                amount_repaid=ln.amount_repaid,
                status=ln.status,
                created_tick=ln.created_tick,
            )
            if ln.id in existing_loans:
                db.execute(update(loans_table).where(loans_table.c.id == ln.id).values(**values))
            else:
                db.execute(insert(loans_table).values(**values))

        # 11. Trade Offers
        trades = getattr(state, "trade_offers", {})
        existing_trades = set(db.execute(select(trade_offers_table.c.id)).scalars())
        current_trades = set(trades.keys())
        for tid in existing_trades - current_trades:
            db.execute(delete(trade_offers_table).where(trade_offers_table.c.id == tid))
        for tr in trades.values():
            values = dict(
                id=tr.id,
                offerer_id=tr.offerer_id,
                recipient_id=tr.recipient_id,
                give_money=tr.give.money,
                give_wheat=tr.give.goods.wheat,
                give_bread=tr.give.goods.bread,
                get_money=tr.get.money,
                get_wheat=tr.get.goods.wheat,
                get_bread=tr.get.goods.bread,
                created_tick=tr.created_tick,
                expires_tick=tr.expires_tick,
                event_id=tr.event_id,
                rationale=tr.rationale,
            )
            if tr.id in existing_trades:
                db.execute(
                    update(trade_offers_table)
                    .where(trade_offers_table.c.id == tr.id)
                    .values(**values)
                )
            else:
                db.execute(insert(trade_offers_table).values(**values))

        # 12. License Offers
        lic_offers = getattr(state, "license_offers", {})
        existing_lics = set(db.execute(select(license_offers_table.c.id)).scalars())
        current_lics = set(lic_offers.keys())
        for lid in existing_lics - current_lics:
            db.execute(delete(license_offers_table).where(license_offers_table.c.id == lid))
        for lo in lic_offers.values():
            values = dict(
                id=lo.id,
                invention_id=lo.invention_id,
                owner_id=lo.owner_id,
                recipient_id=lo.recipient_id,
                fee=lo.fee,
                tick=lo.tick,
            )
            if lo.id in existing_lics:
                db.execute(
                    update(license_offers_table)
                    .where(license_offers_table.c.id == lo.id)
                    .values(**values)
                )
            else:
                db.execute(insert(license_offers_table).values(**values))

        # 13. Votes
        votes = getattr(state, "votes", {})
        existing_votes = set(db.execute(select(votes_table.c.id)).scalars())
        current_votes = set(votes.keys())
        for vid in existing_votes - current_votes:
            db.execute(delete(votes_table).where(votes_table.c.id == vid))
        for vt in votes.values():
            values = dict(
                id=vt.id,
                proposer_id=vt.proposer_id,
                kind=vt.kind,
                value=vt.value,
                rationale=vt.rationale,
                opens_tick=vt.opens_tick,
                closes_tick=vt.closes_tick,
                status=vt.status,
                ballots=json.dumps(vt.ballots),
                yes_weight=vt.yes_weight,
                no_weight=vt.no_weight,
            )
            if vt.id in existing_votes:
                db.execute(update(votes_table).where(votes_table.c.id == vt.id).values(**values))
            else:
                db.execute(insert(votes_table).values(**values))

    def create(self, state: WorldState, meta: BranchMetadata):
        with self.engine.begin() as db:
            db.execute(
                insert(branches).values(
                    id=meta.id, metadata=meta.model_dump_json(), state=state.model_dump_json()
                )
            )
            self._snapshot(db, state)
            self._sync_relational(db, state)

    def commit(self, result: WorldUpdate, expected_sequence: int, mirror: bool = True):
        """Save a world and its events atomically. `mirror=False` skips the relational
        tables, which hold one live world: background (headless) branches must not touch it."""
        state = result.state
        with self.engine.begin() as db:
            current = db.execute(
                select(branches.c.state).where(branches.c.id == state.branch_id)
            ).scalar()
            if current is None or json.loads(current)["sequence"] != expected_sequence:
                raise ValueError("Concurrent or stale world update")
            if not result.events or result.events[0].sequence != expected_sequence + 1:
                raise ValueError("Commit requires contiguous events")
            for index, event_item in enumerate(result.events, expected_sequence + 1):
                if event_item.sequence != index or event_item.branch_id != state.branch_id:
                    raise ValueError("Event stream mismatch")
                pl = getattr(event_item, "payload", {})
                pl_dict = pl.model_dump() if hasattr(pl, "model_dump") else pl
                db.execute(
                    insert(events).values(
                        id=event_item.id,
                        branch_id=event_item.branch_id,
                        sequence=event_item.sequence,
                        tick=event_item.tick,
                        type=event_item.type,
                        actor_id=event_item.actor_id,
                        payload=json.dumps(pl_dict),
                        data=event_item.model_dump_json(),
                        created_at=datetime.now(UTC).isoformat(),
                    )
                )
            if result.events[-1].sequence != state.sequence:
                raise ValueError("State and event versions differ")
            db.execute(
                update(branches)
                .where(branches.c.id == state.branch_id)
                .values(state=state.model_dump_json())
            )
            for outcome in getattr(result, "action_results", []):
                saved = db.execute(
                    update(actions)
                    .where(
                        actions.c.id == outcome.action_id,
                        actions.c.branch_id == state.branch_id,
                        actions.c.status == "queued",
                    )
                    .values(status=outcome.status, data=outcome.model_dump_json())
                )
                if saved.rowcount != 1:
                    raise ValueError("Action was missing or already resolved")
            # Every commit is a checkpoint: simple, exact historical reconstruction, no LLM replay.
            self._snapshot(db, state)
            if mirror:
                self._sync_relational(db, state)

    def enqueue(self, state: WorldState, action, source="agent", text=None) -> ActionResult:
        with self.engine.begin() as db:
            count = db.execute(
                select(func.count())
                .select_from(actions)
                .where(actions.c.branch_id == state.branch_id)
            ).scalar_one()
            ordinal = count + 1
            action_id = f"action-{state.branch_id}:{ordinal}"
            scheduled_tick = state.tick + 1
            record = ActionResult(
                action_id=action_id,
                branch_id=state.branch_id,
                status="queued",
                scheduled_tick=scheduled_tick,
                order=ordinal,
                source=source,
                text=text,
                action=action,
                tick=state.tick,
                sequence=state.sequence,
            )
            db.execute(
                insert(actions).values(
                    id=action_id,
                    branch_id=state.branch_id,
                    ordinal=ordinal,
                    status="queued",
                    data=record.model_dump_json(),
                )
            )
            return record

    def action(self, action_id: str) -> ActionResult:
        with self.engine.connect() as db:
            row = db.execute(
                select(actions.c.data).where(actions.c.id == action_id)
            ).scalar_one_or_none()
            if row is None:
                raise KeyError("Unknown action")
            return ActionResult.model_validate_json(row)

    def pending(self, branch_id: str) -> list[ActionResult]:
        with self.engine.connect() as db:
            rows = db.execute(
                select(actions.c.data)
                .where(actions.c.branch_id == branch_id, actions.c.status == "queued")
                .order_by(actions.c.ordinal)
            ).scalars()
            return [ActionResult.model_validate_json(data) for data in rows]

    def world(self, branch_id: str) -> WorldState:
        with self.engine.connect() as db:
            raw = db.execute(
                select(branches.c.state).where(branches.c.id == branch_id)
            ).scalar_one_or_none()
            if raw is None:
                raise KeyError(f"Unknown branch: {branch_id}")
            return WorldState.model_validate_json(raw)

    def list_branches(self) -> list[BranchMetadata]:
        with self.engine.connect() as db:
            rows = db.execute(select(branches.c.metadata).order_by(branches.c.id)).scalars()
            return [BranchMetadata.model_validate_json(data) for data in rows]

    def list_snapshots(self, branch_id: str) -> list[SnapshotMetadata]:
        with self.engine.connect() as db:
            rows = db.execute(
                select(snapshots.c.metadata)
                .where(snapshots.c.branch_id == branch_id)
                .order_by(snapshots.c.sequence)
            ).scalars()
            return [SnapshotMetadata.model_validate_json(data) for data in rows]

    def restore(self, snapshot_id: str) -> WorldState:
        with self.engine.connect() as db:
            raw = db.execute(
                select(snapshots.c.state).where(snapshots.c.id == snapshot_id)
            ).scalar()
            if raw is None:
                raise KeyError("Unknown snapshot")
            return WorldState.model_validate_json(raw)

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

    # Branching, tracing and comparison
    def branch(self, branch_id: str) -> BranchMetadata:
        with self.engine.connect() as db:
            raw = db.execute(
                select(branches.c.metadata).where(branches.c.id == branch_id)
            ).scalar_one_or_none()
        if raw is None:
            raise KeyError(f"Unknown branch: {branch_id}")
        return BranchMetadata.model_validate_json(raw)

    def snapshot(self, snapshot_id: str) -> SnapshotMetadata:
        with self.engine.connect() as db:
            raw = db.execute(
                select(snapshots.c.metadata).where(snapshots.c.id == snapshot_id)
            ).scalar_one_or_none()
        if raw is None:
            raise KeyError("Unknown snapshot")
        return SnapshotMetadata.model_validate_json(raw)

    def event(self, event_id: str) -> SimulationEvent:
        with self.engine.connect() as db:
            raw = db.execute(
                select(events.c.data).where(events.c.id == event_id)
            ).scalar_one_or_none()
        if raw is None:
            raise KeyError("Unknown event")
        return TypeAdapter(SimulationEvent).validate_json(raw)

    def events_citing(self, branch_id: str, event_id: str) -> list[SimulationEvent]:
        """Events on a branch whose causal_refs include event_id, oldest first."""
        query = select(events.c.data).where(
            events.c.branch_id == branch_id,
            # Coarse text prefilter; the exact causal_refs check below decides.
            events.c.data.contains(json.dumps(event_id), autoescape=True),
        )
        adapter = TypeAdapter(SimulationEvent)
        with self.engine.connect() as db:
            rows = db.execute(query.order_by(events.c.sequence)).scalars()
            parsed = [adapter.validate_json(raw) for raw in rows]
        return [e for e in parsed if event_id in e.causal_refs]

    def events_of_action(self, branch_id: str, action_id: str) -> list[SimulationEvent]:
        query = select(events.c.data).where(
            events.c.branch_id == branch_id,
            events.c.data.contains(json.dumps(action_id), autoescape=True),
        )
        adapter = TypeAdapter(SimulationEvent)
        with self.engine.connect() as db:
            rows = db.execute(query.order_by(events.c.sequence)).scalars()
            parsed = [adapter.validate_json(raw) for raw in rows]
        return [e for e in parsed if e.action_id == action_id]

    def events_through(self, branch_id: str, through: int | None = None) -> list[SimulationEvent]:
        """Every event on one branch up to a sequence (inclusive), oldest first. Unbounded."""
        query = select(events.c.data).where(events.c.branch_id == branch_id)
        if through is not None:
            query = query.where(events.c.sequence <= through)
        adapter = TypeAdapter(SimulationEvent)
        with self.engine.connect() as db:
            rows = db.execute(query.order_by(events.c.sequence)).scalars()
            return [adapter.validate_json(raw) for raw in rows]

    def filter_events(
        self,
        branch_id: str,
        after: int = 0,
        limit: int = 100,
        types: list[str] | None = None,
        actor: str | None = None,
        target: str | None = None,
        tick_from: int | None = None,
        tick_to: int | None = None,
    ) -> list[SimulationEvent]:
        """Events after a sequence matching every given filter, oldest first.

        `target` matches a citizen or entity named in the payload (sender, recipient,
        subject); the indexed columns (type, actor, tick) are filtered in SQL.
        """
        query = select(events.c.data).where(
            events.c.branch_id == branch_id, events.c.sequence > after
        )
        if types:
            query = query.where(events.c.type.in_(types))
        if actor is not None:
            query = query.where(events.c.actor_id == actor)
        if tick_from is not None:
            query = query.where(events.c.tick >= tick_from)
        if tick_to is not None:
            query = query.where(events.c.tick <= tick_to)
        if target is not None:
            query = query.where(events.c.payload.contains(json.dumps(target), autoescape=True))
        adapter = TypeAdapter(SimulationEvent)
        found: list[SimulationEvent] = []
        with self.engine.connect() as db:
            for raw in db.execute(query.order_by(events.c.sequence)).scalars():
                event = adapter.validate_json(raw)
                if target is not None:
                    payload = event.payload.model_dump()
                    if target not in {payload.get(k) for k in (*INVOLVEMENT_KEYS, "building_id")}:
                        continue
                found.append(event)
                if len(found) == limit:
                    break
        return found

    def update_branch(self, meta: BranchMetadata):
        with self.engine.begin() as db:
            db.execute(
                update(branches)
                .where(branches.c.id == meta.id)
                .values(metadata=meta.model_dump_json())
            )

    # Relational Inspection Queries
    def get_world_row(self) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(world_table)).mappings().first()
            return dict(row) if row else None

    def get_citizens_rows(self) -> list[dict]:
        with self.engine.connect() as db:
            stmt = select(citizens_table).order_by(citizens_table.c.id)
            return [dict(r) for r in db.execute(stmt).mappings().all()]

    def get_buildings_rows(self) -> list[dict]:
        with self.engine.connect() as db:
            stmt = select(buildings_table).order_by(buildings_table.c.id)
            return [dict(r) for r in db.execute(stmt).mappings().all()]

    def get_plots_rows(self) -> list[dict]:
        with self.engine.connect() as db:
            stmt = select(plots_table).order_by(plots_table.c.id)
            return [dict(r) for r in db.execute(stmt).mappings().all()]

    def get_job_applications_rows(self, building_id: str | None = None) -> list[dict]:
        query = select(job_applications_table)
        if building_id:
            query = query.where(job_applications_table.c.building_id == building_id)
        with self.engine.connect() as db:
            stmt = query.order_by(job_applications_table.c.id)
            return [dict(r) for r in db.execute(stmt).mappings().all()]

    def get_resources_rows(self) -> list[dict]:
        with self.engine.connect() as db:
            stmt = select(resources_table).order_by(resources_table.c.kind)
            return [dict(r) for r in db.execute(stmt).mappings().all()]

    def get_inventions_rows(self) -> list[dict]:
        with self.engine.connect() as db:
            stmt = select(inventions_table).order_by(inventions_table.c.id)
            return [dict(r) for r in db.execute(stmt).mappings().all()]

    def get_loans_rows(self) -> list[dict]:
        with self.engine.connect() as db:
            stmt = select(loans_table).order_by(loans_table.c.id)
            return [dict(r) for r in db.execute(stmt).mappings().all()]

    def get_trade_offers_rows(self) -> list[dict]:
        with self.engine.connect() as db:
            stmt = select(trade_offers_table).order_by(trade_offers_table.c.id)
            return [dict(r) for r in db.execute(stmt).mappings().all()]

    def get_votes_rows(self) -> list[dict]:
        with self.engine.connect() as db:
            stmt = select(votes_table).order_by(votes_table.c.id)
            return [dict(r) for r in db.execute(stmt).mappings().all()]

    def get_relational_events(self, limit: int = 50) -> list[dict]:
        with self.engine.connect() as db:
            stmt = select(events).order_by(events.c.sequence.desc()).limit(limit)
            return [dict(r) for r in db.execute(stmt).mappings().all()]
