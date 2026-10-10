-- KRONOS Relational Data Model (v1 + Economy Systems)
-- Unified schema connecting core simulation entities, economy, governance, and history.
-- Money is stored in integer cents.

PRAGMA foreign_keys = ON;

-- 1. World & Policies (1 row: clock, settings, town policies)
CREATE TABLE IF NOT EXISTS world (
    id TEXT PRIMARY KEY,
    tick INTEGER NOT NULL DEFAULT 0,
    sequence INTEGER NOT NULL DEFAULT 0,
    seed INTEGER NOT NULL DEFAULT 42,
    rng_state TEXT NOT NULL,
    playing BOOLEAN NOT NULL DEFAULT 0,
    speed INTEGER NOT NULL DEFAULT 1,
    market_tax_bps INTEGER NOT NULL DEFAULT 0 CHECK (market_tax_bps >= 0 AND market_tax_bps <= 10000),
    bread_price_cap INTEGER NOT NULL DEFAULT 0 CHECK (bread_price_cap >= 0),
    min_wage INTEGER NOT NULL DEFAULT 0 CHECK (min_wage >= 0)
);

-- 2. Plots (Lots: unowned lots are town land anyone can build on)
CREATE TABLE IF NOT EXISTS plots (
    id TEXT PRIMARY KEY,
    position_x REAL NOT NULL,
    position_z REAL NOT NULL,
    owner_id TEXT,
    tenant_id TEXT,
    rent INTEGER NOT NULL DEFAULT 0 CHECK (rent >= 0),
    arrears INTEGER NOT NULL DEFAULT 0 CHECK (arrears >= 0),
    missed_periods INTEGER NOT NULL DEFAULT 0 CHECK (missed_periods >= 0),
    prepaid_periods INTEGER NOT NULL DEFAULT 0 CHECK (prepaid_periods >= 0 AND prepaid_periods <= 4),
    FOREIGN KEY (owner_id) REFERENCES citizens(id) ON DELETE SET NULL,
    FOREIGN KEY (tenant_id) REFERENCES citizens(id) ON DELETE SET NULL
);

-- 3. Inventions & Technologies (Shared research, licensing, production multiplier)
CREATE TABLE IF NOT EXISTS inventions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cost INTEGER NOT NULL CHECK (cost > 0),
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress >= 0),
    contributors TEXT NOT NULL DEFAULT '{}',
    unlocked BOOLEAN NOT NULL DEFAULT 0,
    owner_id TEXT,
    licensees TEXT NOT NULL DEFAULT '[]',
    adopters TEXT NOT NULL DEFAULT '[]',
    adoption_cost INTEGER NOT NULL DEFAULT 1000 CHECK (adoption_cost >= 0),
    building_kind TEXT NOT NULL CHECK (building_kind IN ('farm', 'bakery', 'market')),
    resource TEXT NOT NULL,
    multiplier_pct INTEGER NOT NULL CHECK (multiplier_pct > 100),
    FOREIGN KEY (owner_id) REFERENCES citizens(id) ON DELETE SET NULL
);

-- 4. Citizens (Villagers: needs, employment, relationships, goals, memories)
CREATE TABLE IF NOT EXISTS citizens (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    occupation TEXT NOT NULL,
    employer_id TEXT,
    money INTEGER NOT NULL CHECK (money >= 0),
    hunger INTEGER NOT NULL CHECK (hunger >= 0 AND hunger <= 100),
    wheat INTEGER NOT NULL DEFAULT 0 CHECK (wheat >= 0),
    bread INTEGER NOT NULL DEFAULT 0 CHECK (bread >= 0),
    position_x REAL NOT NULL,
    position_z REAL NOT NULL,
    reputation INTEGER NOT NULL DEFAULT 50 CHECK (reputation >= 0 AND reputation <= 100),
    destitute_days INTEGER NOT NULL DEFAULT 0 CHECK (destitute_days >= 0),
    personality TEXT NOT NULL DEFAULT 'practical',
    goals TEXT NOT NULL DEFAULT '["Stay fed", "Save for tomorrow"]',
    goal_weights TEXT NOT NULL DEFAULT '{"wealth": 25, "influence": 25, "safety": 25, "reputation": 25}',
    relationships TEXT NOT NULL DEFAULT '[]',
    memories TEXT NOT NULL DEFAULT '[]',
    memory_summary TEXT NOT NULL DEFAULT '',
    memory_tally TEXT NOT NULL DEFAULT '{}',
    research_invention_id TEXT,
    research_start_tick INTEGER NOT NULL DEFAULT 0 CHECK (research_start_tick >= 0),
    research_until_tick INTEGER NOT NULL DEFAULT 0 CHECK (research_until_tick >= 0),
    FOREIGN KEY (employer_id) REFERENCES buildings(id) ON DELETE SET NULL,
    FOREIGN KEY (research_invention_id) REFERENCES inventions(id) ON DELETE SET NULL
);

-- 5. Buildings (Businesses: farm, bakery, market)
CREATE TABLE IF NOT EXISTS buildings (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('farm', 'bakery', 'market')),
    level INTEGER NOT NULL DEFAULT 1 CHECK (level >= 1 AND level <= 3),
    owner_id TEXT NOT NULL,
    plot_id TEXT NOT NULL UNIQUE,
    cash INTEGER NOT NULL DEFAULT 0 CHECK (cash >= 0),
    wheat INTEGER NOT NULL DEFAULT 0 CHECK (wheat >= 0),
    bread INTEGER NOT NULL DEFAULT 0 CHECK (bread >= 0),
    bread_price INTEGER NOT NULL DEFAULT 500 CHECK (bread_price >= 0),
    wheat_price INTEGER NOT NULL DEFAULT 100 CHECK (wheat_price >= 0),
    wage INTEGER NOT NULL DEFAULT 150 CHECK (wage >= 0),
    job_slots INTEGER NOT NULL DEFAULT 3 CHECK (job_slots >= 0),
    unpaid_days INTEGER NOT NULL DEFAULT 0 CHECK (unpaid_days >= 0),
    FOREIGN KEY (owner_id) REFERENCES citizens(id),
    FOREIGN KEY (plot_id) REFERENCES plots(id)
);

-- 6. Shared Natural Resources (e.g. natural wheat stock)
CREATE TABLE IF NOT EXISTS resources (
    kind TEXT PRIMARY KEY CHECK (kind IN ('wheat')),
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    regen_per_tick INTEGER NOT NULL DEFAULT 0 CHECK (regen_per_tick >= 0),
    cap INTEGER
);

-- 7. Job Applications (Citizen applications to work at a business; resolved applications are retained)
CREATE TABLE IF NOT EXISTS job_applications (
    id TEXT PRIMARY KEY,
    citizen_id TEXT NOT NULL,
    building_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'hired', 'rejected')),
    tick INTEGER NOT NULL DEFAULT 0,
    sequence INTEGER NOT NULL DEFAULT 0
);

-- 8. Loans (P2P loans with flat interest; retained across all lifecycles)
CREATE TABLE IF NOT EXISTS loans (
    id TEXT PRIMARY KEY,
    lender_id TEXT NOT NULL,
    borrower_id TEXT NOT NULL,
    principal INTEGER NOT NULL CHECK (principal > 0),
    rate_bps INTEGER NOT NULL CHECK (rate_bps >= 0 AND rate_bps <= 10000),
    due_tick INTEGER NOT NULL CHECK (due_tick > 0),
    amount_owed INTEGER NOT NULL CHECK (amount_owed > 0),
    amount_repaid INTEGER NOT NULL DEFAULT 0 CHECK (amount_repaid >= 0),
    status TEXT NOT NULL DEFAULT 'offered' CHECK (status IN ('offered', 'active', 'repaid', 'defaulted', 'declined', 'expired')),
    created_tick INTEGER NOT NULL DEFAULT 0
);

-- 9. Trade Offers (P2P exchange of goods and money)
CREATE TABLE IF NOT EXISTS trade_offers (
    id TEXT PRIMARY KEY,
    offerer_id TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    give_money INTEGER NOT NULL DEFAULT 0 CHECK (give_money >= 0),
    give_wheat INTEGER NOT NULL DEFAULT 0 CHECK (give_wheat >= 0),
    give_bread INTEGER NOT NULL DEFAULT 0 CHECK (give_bread >= 0),
    get_money INTEGER NOT NULL DEFAULT 0 CHECK (get_money >= 0),
    get_wheat INTEGER NOT NULL DEFAULT 0 CHECK (get_wheat >= 0),
    get_bread INTEGER NOT NULL DEFAULT 0 CHECK (get_bread >= 0),
    created_tick INTEGER NOT NULL DEFAULT 0,
    expires_tick INTEGER NOT NULL DEFAULT 0,
    event_id TEXT,
    rationale TEXT,
    FOREIGN KEY (offerer_id) REFERENCES citizens(id) ON DELETE CASCADE,
    FOREIGN KEY (recipient_id) REFERENCES citizens(id) ON DELETE CASCADE
);

-- 10. License Offers (Consent-based invention licensing)
CREATE TABLE IF NOT EXISTS license_offers (
    id TEXT PRIMARY KEY,
    invention_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    fee INTEGER NOT NULL DEFAULT 0 CHECK (fee >= 0),
    tick INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (invention_id) REFERENCES inventions(id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id) REFERENCES citizens(id) ON DELETE CASCADE,
    FOREIGN KEY (recipient_id) REFERENCES citizens(id) ON DELETE CASCADE
);

-- 11. Town Votes (Democratic governance and policies)
CREATE TABLE IF NOT EXISTS votes (
    id TEXT PRIMARY KEY,
    proposer_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('market_tax', 'bread_price_cap', 'min_wage')),
    value INTEGER NOT NULL CHECK (value >= 0),
    rationale TEXT,
    opens_tick INTEGER NOT NULL DEFAULT 0,
    closes_tick INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'passed', 'failed')),
    ballots TEXT NOT NULL DEFAULT '{}',
    yes_weight INTEGER NOT NULL DEFAULT 0,
    no_weight INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (proposer_id) REFERENCES citizens(id) ON DELETE CASCADE
);

-- 12. Actions Queue (Durable queue of player and citizen proposals)
CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY,
    branch_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'applied', 'rejected')),
    data TEXT NOT NULL
);

-- 13. Events (Append-only log of village events)
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    branch_id TEXT NOT NULL DEFAULT 'main',
    sequence INTEGER NOT NULL,
    tick INTEGER NOT NULL DEFAULT 0,
    type TEXT NOT NULL,
    actor_id TEXT,
    payload TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (actor_id) REFERENCES citizens(id) ON DELETE SET NULL
);

-- 14. History Metadata Tables (Branches, snapshots, settings for time travel)
CREATE TABLE IF NOT EXISTS branches (
    id TEXT PRIMARY KEY,
    metadata TEXT NOT NULL,
    state TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    branch_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    metadata TEXT NOT NULL,
    state TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS ix_citizens_employer ON citizens(employer_id);
CREATE INDEX IF NOT EXISTS ix_plots_owner ON plots(owner_id);
CREATE INDEX IF NOT EXISTS ix_plots_tenant ON plots(tenant_id);
CREATE INDEX IF NOT EXISTS ix_buildings_owner ON buildings(owner_id);
CREATE INDEX IF NOT EXISTS ix_job_applications_building ON job_applications(building_id);
CREATE INDEX IF NOT EXISTS ix_job_applications_citizen ON job_applications(citizen_id);
CREATE INDEX IF NOT EXISTS ix_loans_borrower ON loans(borrower_id);
CREATE INDEX IF NOT EXISTS ix_loans_lender ON loans(lender_id);
CREATE INDEX IF NOT EXISTS ix_trade_offers_recipient ON trade_offers(recipient_id);
CREATE INDEX IF NOT EXISTS ix_votes_status ON votes(status);
CREATE INDEX IF NOT EXISTS ix_actions_branch_status ON actions(branch_id, status);
CREATE INDEX IF NOT EXISTS ix_events_branch_sequence ON events(branch_id, sequence);
CREATE INDEX IF NOT EXISTS ix_events_type ON events(type);
CREATE INDEX IF NOT EXISTS ix_events_tick ON events(tick);
CREATE INDEX IF NOT EXISTS ix_snapshots_branch_sequence ON snapshots(branch_id, sequence);
