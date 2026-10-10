-- KRONOS Mock Data (v1 + Economy Systems)
-- Seed world matching initial_world(42): 6 plots, 7 citizens, 3 buildings, resources, inventions, 1 sample event.

PRAGMA foreign_keys = OFF;

-- 1. World & Policies
INSERT OR REPLACE INTO world (id, tick, sequence, seed, rng_state, playing, speed, market_tax_bps, bread_price_cap, min_wage)
VALUES (
    'main',
    0,
    1,
    42,
    '[3, [2147483648, 3564348608, 1266698288, 4212342371, 3595291661, 3180588708, 3037210256, 946923017, 2565409715, 2900535780, 924383152, 4180157270, 4230508198, 2039675917, 3755350407, 2362848650, 2818100609, 2097423432, 524478045, 540883378, 281170210, 1485176884, 1493190386, 1773214509, 380915208, 3667698522, 2648371337, 2961234806, 3857480267, 1582950522, 246289694, 3322185604, 1944574775, 302623699, 169865066, 1143540808, 3733177770, 513116636, 1411153081, 3205493053, 768926902, 549624109, 1470655403, 59539609, 3678480009, 3087139671, 1176835859, 2018449081, 3424160085, 2655519803, 4016629232, 2801457199, 1993439977, 2736187748, 1982736154, 2198374615, 3819274615, 1928374615, 1283746152, 3819283746, 2918273645, 1029384756, 624], null]',
    0,
    1,
    0,
    0,
    0
);

-- 2. Plots (6 lots: 3 north, 3 south. Elena owns plot-0 and plot-5; Marcus plot-1; Ada plot-2; Mira rents plot-5)
INSERT OR REPLACE INTO plots (id, position_x, position_z, owner_id, tenant_id, rent, arrears, missed_periods, prepaid_periods) VALUES
('plot-0', -4.0, -3.0, 'citizen-0', NULL,        0, 0, 0, 0),
('plot-1',  0.0, -3.0, 'citizen-1', NULL,        0, 0, 0, 0),
('plot-2',  4.0, -3.0, 'citizen-2', NULL,        0, 0, 0, 0),
('plot-3', -4.0,  3.0, NULL,        NULL,        0, 0, 0, 0),
('plot-4',  0.0,  3.0, NULL,        NULL,        0, 0, 0, 0),
('plot-5',  4.0,  3.0, 'citizen-0', 'citizen-5', 300, 0, 0, 0);

-- 3. Inventions
INSERT OR REPLACE INTO inventions (id, name, cost, progress, contributors, unlocked, owner_id, licensees, adopters, adoption_cost, building_kind, resource, multiplier_pct) VALUES
('crop_rotation', 'Crop Rotation', 1500, 0, '{}', 0, NULL, '[]', '[]', 1000, 'farm',   'wheat', 140),
('water_mill',    'Water Mill',    2500, 0, '{}', 0, NULL, '[]', '[]', 1500, 'bakery', 'bread', 200);

-- 4. Citizens (7 villagers: Elena, Marcus, Ada, Rowan, Theo, Mira, Finn)
INSERT OR REPLACE INTO citizens (id, name, occupation, employer_id, money, hunger, wheat, bread, position_x, position_z, reputation, destitute_days, personality, goals, goal_weights, relationships, memories, memory_summary, memory_tally, research_invention_id, research_start_tick, research_until_tick) VALUES
('citizen-0', 'Elena',  'Farmer',   'farm',   18000, 20, 0, 1, -3.0, 0.0, 50, 0, 'practical', '["Stay fed", "Save for tomorrow"]', '{"wealth": 25, "influence": 25, "safety": 25, "reputation": 25}', '[]', '[]', '', '{}', NULL, 0, 0),
('citizen-1', 'Marcus', 'Baker',    'bakery', 22000, 20, 0, 1, -2.0, 0.0, 50, 0, 'practical', '["Stay fed", "Save for tomorrow"]', '{"wealth": 25, "influence": 25, "safety": 25, "reputation": 25}', '[]', '[]', '', '{}', NULL, 0, 0),
('citizen-2', 'Ada',    'Merchant', 'market', 16000, 20, 0, 1, -1.0, 0.0, 50, 0, 'practical', '["Stay fed", "Save for tomorrow"]', '{"wealth": 25, "influence": 25, "safety": 25, "reputation": 25}', '[]', '[]', '', '{}', NULL, 0, 0),
('citizen-3', 'Rowan',  'Farmhand', 'farm',     800, 20, 0, 1,  0.0, 0.0, 50, 0, 'practical', '["Stay fed", "Save for tomorrow"]', '{"wealth": 25, "influence": 25, "safety": 25, "reputation": 25}', '[]', '[]', '', '{}', NULL, 0, 0),
('citizen-4', 'Theo',   'Miller',   'bakery',   650, 20, 0, 1,  1.0, 0.0, 50, 0, 'practical', '["Stay fed", "Save for tomorrow"]', '{"wealth": 25, "influence": 25, "safety": 25, "reputation": 25}', '[]', '[]', '', '{}', NULL, 0, 0),
('citizen-5', 'Mira',   'Builder',  NULL,      6000, 20, 0, 1,  2.0, 0.0, 50, 0, 'practical', '["Stay fed", "Save for tomorrow"]', '{"wealth": 25, "influence": 25, "safety": 25, "reputation": 25}', '[]', '[]', '', '{}', NULL, 0, 0),
('citizen-6', 'Finn',   'Weaver',   NULL,       550, 20, 0, 1,  3.0, 0.0, 50, 0, 'practical', '["Stay fed", "Save for tomorrow"]', '{"wealth": 25, "influence": 25, "safety": 25, "reputation": 25}', '[]', '[]', '', '{}', NULL, 0, 0);

-- 5. Buildings (3 businesses: farm, bakery, market)
INSERT OR REPLACE INTO buildings (id, name, kind, level, owner_id, plot_id, cash, wheat, bread, bread_price, wheat_price, wage, job_slots, unpaid_days) VALUES
('farm',   'Goldenfield Farm', 'farm',   1, 'citizen-0', 'plot-0', 10000, 12,  0, 500, 100, 150, 3, 0),
('bakery', 'Hearth & Grain',   'bakery', 1, 'citizen-1', 'plot-1', 10000, 12, 16, 500, 100, 150, 3, 0),
('market', 'Market Square',    'market', 1, 'citizen-2', 'plot-2', 10000,  0,  0, 500, 100, 150, 3, 0);

-- 6. Shared Natural Stocks
INSERT OR REPLACE INTO resources (kind, stock, regen_per_tick, cap) VALUES
('wheat', 120, 6, 200);

-- 7. Job Applications (sample)
INSERT OR REPLACE INTO job_applications (id, citizen_id, building_id, status, tick, sequence) VALUES
('job-app-1', 'citizen-5', 'market', 'pending', 0, 1);

-- 8. Events
INSERT OR REPLACE INTO events (id, branch_id, sequence, tick, type, actor_id, payload, data, created_at) VALUES
('evt-settle-1', 'main', 1, 0, 'village_settled', NULL,
 '{"message": "The village of Veloria was settled.", "citizens": 7, "buildings": 3}',
 '{"id": "evt-settle-1", "branch_id": "main", "sequence": 1, "tick": 0, "type": "village_settled", "actor_id": null, "rationale": null, "causal_refs": [], "action_id": null, "payload": {"message": "The village of Veloria was settled.", "citizens": 7, "buildings": 3}}',
 '2026-10-10T00:00:00Z');

PRAGMA foreign_keys = ON;
