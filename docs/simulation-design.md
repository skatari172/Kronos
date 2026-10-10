# Simulation mechanics

A tick represents one day. The engine runs these steps in stable insertion order:

1. If a bakery lacks wheat, buy two wheat from the first farm if cash/stock permit.
2. Farms produce a seeded 3–6 wheat per level. Bakeries consume two wheat for three bread per level.
3. Employers with available cash pay each employed citizen 150 cents.
4. Each citizen gains 20 hunger, capped at 100. If they have no bread, purchase one loaf from the cheapest stocked bakery they can afford. Consume one bread for 30 hunger relief.
5. Citizens choose a seeded plot waypoint and walk via the central lane in presentation time.
6. Apply optional strategic proposals in order, each in an isolated validation transaction.
7. Return the new world, ordered events, final RNG state, and rejected proposal reasons.

The API obtains the bounded strategic proposal from the pre-tick observation every third day. It therefore observes yesterday's state, not half-finished production/trades. Routine mechanics never call a model. This timing is explicit and can be revised by the team without changing renderer ownership.

Player price changes occur between ticks and take effect immediately in all existing bakeries, using Decimal half-up rounding into cents. This is a one-time operation, not a continuing constraint; newly built businesses start at the default price and owner `set_price` actions can revise it. Accepted percent range is −90% through +200%, with final prices constrained to 1–1,000,000 cents.

Buy/sell validate cash, stock, quantities, and buyer limits. Owner actions validate ownership. Construction requires a vacant predefined plot and 5,000 cents; upgrades cost 2,500 cents and cap at level three. Costs leave the modeled economy as construction inputs; trades and wages conserve money. Communication stores bounded recent memories and increases familiarity by one, capped at 100; its content is not a proven economic cause. Citizens cannot spend each other's money through agent proposals.

Current omissions: production cooldown on manually submitted `produce`, richer market roles, need-based occupations, survival/death, population mechanics, investments driven by strategy, ownership transfers, and ongoing policies. Daily routines deliberately stay small. Add constraints and test them before exposing new command vocabularies.

## Innovation

`WorldState.inventions` is seeded with `crop_rotation` (1,500 cents; adopting farms make wheat ×1.4) and `water_mill` (2,500 cents; adopting bakeries make bread ×2). Costs are the spec's florins at 10 cents each. Multipliers are integer percentages applied in invention-ID order inside `Produce`, so production stays deterministic and uses no extra RNG.

- `research` money mode spends at most the remaining cost; the money leaves the economy like construction inputs. Time mode needs a job: for the next `ticks` days the employer keeps the wage (`research_invention_id` / `research_until_tick` on the citizen; the wage loop skips them) and each skipped wage counts as progress. At full cost the top contributor owns the invention (ties go to the lowest citizen ID) and other time researchers are released.
- `license_invention` only creates a `LicenseOffer`; the recipient answers with `respond_license` on the same tick (funds re-checked) or the offer expires at the next tick. The fee moves recipient → owner.
- `adopt_invention` is for the building owner who owns or licenses an unlocked invention matching the building kind; the business pays `adoption_cost` (a sink).
- Waiting on richer goods: `printing_press` (books, scribes) and `ledger_banking` (loans). Add them with a matching `InventionEffect` once those goods and actions exist. Closed buildings stay in `adopters`; building IDs are never reused.
