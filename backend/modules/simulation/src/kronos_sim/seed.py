import json
import random

from kronos_sim.models import (
    Building,
    Citizen,
    GoalWeights,
    Invention,
    InventionEffect,
    Plot,
    Position,
    ResourceInventory,
    WorldState,
    default_resources,
)


def initial_inventions() -> dict[str, Invention]:
    """Inventions whose effects fit today's wheat/bread economy.

    Costs use the spec's florins at 10 cents each (150 florins = 1,500 cents, i.e. ten days
    of a 150-cent wage). The spec's printing_press (books) and ledger_banking (loans) wait for
    books, scribes, and loans to exist; add them here with a matching InventionEffect then.
    """
    specs = [
        ("crop_rotation", "Crop Rotation", 1500, 1000, "farm", "wheat", 140),
        ("water_mill", "Water Mill", 2500, 1500, "bakery", "bread", 200),
    ]
    return {
        iid: Invention(
            id=iid,
            name=name,
            cost=cost,
            adoption_cost=adoption,
            effect=InventionEffect(building_kind=kind, resource=resource, multiplier_pct=pct),
        )
        for iid, name, cost, adoption, kind, resource, pct in specs
    }


# Who each founder is: personality, goals, and goal weights (wealth, influence, safety,
# reputation). Real providers role-play these; the mock reads the temper words.
FOUNDERS = [
    (
        "Shrewd and proud landowner who hates being undersold",
        ["Own the most land", "Keep the farm ahead"],
        (45, 30, 10, 15),
    ),
    (
        "Ambitious baker, jealous of any rival oven",
        ["Feed the whole town", "Be the richest baker"],
        (40, 25, 15, 20),
    ),
    (
        "Sociable merchant who knows everyone's business",
        ["Broker every deal", "Be liked by all"],
        (30, 30, 10, 30),
    ),
    (
        "Hot-headed farmhand tired of being poor",
        ["Earn a fair wage", "Stand up to Elena"],
        (35, 15, 35, 15),
    ),
    (
        "Quiet, careful miller who counts every crumb",
        ["Never go hungry", "Save for a home"],
        (20, 10, 55, 15),
    ),
    (
        "Blunt builder with big plans for the town",
        ["Build something lasting", "Earn respect"],
        (25, 35, 10, 30),
    ),
    ("Gentle weaver who mends quarrels", ["Make friends", "Find steady work"], (15, 15, 30, 40)),
]

# Each newcomer arrives as their own person: personality, two goals, and goal weights
# (wealth, influence, safety, reputation). 36 personas, so even a City is all distinct;
# past that the list starts over. Real providers role-play these; the mock reads the
# temper words (proud, jealous, hot, blunt, ambitious) in `MockProvider._socialize`.
NEWCOMERS = [
    (
        "Hopeful wanderer looking for a fresh start",
        ["Find a home", "Make one good friend"],
        (25, 15, 40, 20),
    ),
    (
        "Proud ex-soldier who takes no insult",
        ["Earn respect", "Keep the peace by force"],
        (20, 30, 25, 25),
    ),
    (
        "Cheerful traveler who befriends everyone",
        ["Know every name in town", "Never eat alone"],
        (15, 20, 25, 40),
    ),
    (
        "Jealous drifter who envies the rich",
        ["Get rich quick", "Bring the landowners down a peg"],
        (45, 25, 20, 10),
    ),
    (
        "Shy apprentice eager to learn a trade",
        ["Learn a craft", "Stay out of trouble"],
        (25, 10, 45, 20),
    ),
    (
        "Ambitious trader with an eye for profit",
        ["Open a shop", "Outsell the market"],
        (50, 25, 10, 15),
    ),
    (
        "Widowed baker starting over with nothing",
        ["Bake again", "Feed the hungry"],
        (30, 10, 35, 25),
    ),
    (
        "Hot-tempered blacksmith's son with fast fists",
        ["Prove himself", "Never back down"],
        (30, 25, 15, 30),
    ),
    (
        "Pious pilgrim who gives away what she earns",
        ["Help the poor", "Live simply"],
        (10, 15, 30, 45),
    ),
    ("Sly gambler who always has an angle", ["Win big", "Owe nobody"], (55, 20, 15, 10)),
    (
        "Retired sailor full of tall tales",
        ["Tell his stories", "Settle somewhere quiet"],
        (20, 20, 35, 25),
    ),
    (
        "Ambitious young scholar who wants to run the town",
        ["Win a town vote", "Be heard"],
        (20, 50, 10, 20),
    ),
    (
        "Nervous refugee fleeing a famine",
        ["Never go hungry again", "Save every coin"],
        (25, 5, 60, 10),
    ),
    (
        "Blunt shepherd who says what everyone thinks",
        ["Speak the truth", "Earn a fair wage"],
        (30, 20, 25, 25),
    ),
    (
        "Charming con artist with a silver tongue",
        ["Make easy money", "Be admired"],
        (45, 30, 5, 20),
    ),
    (
        "Hard-working farm girl who distrusts merchants",
        ["Work the land", "Buy her own plot"],
        (35, 10, 40, 15),
    ),
    (
        "Proud noble's runaway heir",
        ["Live without his family's money", "Be seen as an equal"],
        (20, 25, 20, 35),
    ),
    (
        "Gentle herbalist who tends to the sick",
        ["Heal people", "Find a quiet corner"],
        (15, 10, 35, 40),
    ),
    (
        "Jealous rival baker from the next village",
        ["Beat Hearth & Grain", "Steal their customers"],
        (50, 20, 15, 15),
    ),
    (
        "Old soldier who mistrusts everyone",
        ["Stay safe", "Keep his savings hidden"],
        (25, 10, 55, 10),
    ),
    (
        "Restless carpenter dreaming of big buildings",
        ["Build a grand hall", "Leave a mark"],
        (30, 30, 10, 30),
    ),
    (
        "Kind-hearted orphan raised on charity",
        ["Repay kindness", "Find a family"],
        (15, 10, 35, 40),
    ),
    (
        "Ambitious moneylender who loves a good deal",
        ["Grow her savings", "Be owed favors"],
        (55, 30, 10, 5),
    ),
    (
        "Hot-headed young farmhand spoiling for a fight",
        ["Earn more than his boss", "Win every argument"],
        (35, 25, 15, 25),
    ),
    (
        "Quiet miller's widow who misses nothing",
        ["Live comfortably", "Know every secret"],
        (25, 30, 35, 10),
    ),
    (
        "Jolly tavern singer who lifts every room",
        ["Make people laugh", "Earn a crowd"],
        (15, 25, 20, 40),
    ),
    (
        "Stern former magistrate who loves order",
        ["Keep the rules", "Lead the town"],
        (15, 45, 20, 20),
    ),
    (
        "Proud weaver who sells only the finest cloth",
        ["Be the best at her craft", "Charge what she's worth"],
        (40, 15, 15, 30),
    ),
    (
        "Lazy dreamer who hopes for a lucky break",
        ["Avoid hard work", "Get lucky"],
        (35, 10, 45, 10),
    ),
    (
        "Loyal farmhand devoted to whoever pays him",
        ["Keep his job", "Be trusted"],
        (25, 10, 40, 25),
    ),
    (
        "Bitter ex-landowner who lost everything",
        ["Own land again", "Get even with the rich"],
        (45, 30, 15, 10),
    ),
    (
        "Curious tinkerer obsessed with new inventions",
        ["Invent something", "Make work easier"],
        (25, 25, 20, 30),
    ),
    (
        "Generous merchant who believes in fair prices",
        ["Keep bread cheap", "Be loved by all"],
        (20, 20, 20, 40),
    ),
    ("Blunt mason who hates waste", ["Build things that last", "Waste nothing"], (30, 15, 35, 20)),
    (
        "Ambitious tailor courting the town's elite",
        ["Dress the rich", "Climb the social ladder"],
        (35, 40, 5, 20),
    ),
    (
        "Weary traveler who just wants peace and bread",
        ["Eat every day", "Avoid quarrels"],
        (20, 5, 60, 15),
    ),
]

NEWCOMER_NAMES = [
    "Ivy",
    "Bram",
    "Lena",
    "Oswin",
    "Hazel",
    "Corin",
    "Willa",
    "Edric",
    "Nell",
    "Tobin",
    "Greta",
    "Silas",
    "Maren",
    "Pip",
    "Rhea",
    "Alder",
    "Juno",
    "Cass",
    "Wren",
    "Hugo",
    "Odette",
    "Garrick",
    "Fern",
    "Leof",
    "Brynn",
    "Cedric",
    "Isolde",
    "Jory",
    "Kestrel",
    "Lorne",
    "Mabel",
    "Nils",
    "Orla",
    "Percy",
    "Quill",
    "Rosalind",
    "Soren",
    "Tamsin",
    "Ulric",
    "Vera",
]


def newcomer_name(index: int) -> str:
    """A stable name per arrival; repeats get a numeral once the list runs out."""
    name = NEWCOMER_NAMES[index % len(NEWCOMER_NAMES)]
    return name if index < len(NEWCOMER_NAMES) else f"{name} {index // len(NEWCOMER_NAMES) + 1}"


def newcomer_persona(index: int) -> tuple[str, list[str], GoalWeights]:
    """Personality, goals and goal weights for the index-th newcomer."""
    personality, goals, (wealth, influence, safety, reputation) = NEWCOMERS[index % len(NEWCOMERS)]
    weights = GoalWeights(wealth=wealth, influence=influence, safety=safety, reputation=reputation)
    return personality, list(goals), weights


def initial_world(seed: int = 42, branch_id: str = "main") -> WorldState:
    plots = {
        f"plot-{i}": Plot(id=f"plot-{i}", position=Position(x=x, z=z))
        for i, (x, z) in enumerate([(-4, -3), (0, -3), (4, -3), (-4, 3), (0, 3), (4, 3)])
    }
    citizens = {}
    for i, name in enumerate(["Elena", "Marcus", "Ada", "Rowan", "Theo", "Mira", "Finn"]):
        citizens[f"citizen-{i}"] = Citizen(
            id=f"citizen-{i}",
            name=name,
            occupation=["Farmer", "Baker", "Merchant", "Farmhand", "Miller", "Builder", "Weaver"][
                i
            ],
            employer_id=["farm", "bakery", "market", "farm", "bakery", None, None][i],
            position=Position(x=i - 3, z=0),
            money=[18000, 22000, 16000, 800, 650, 6000, 550][i],
            inventory=ResourceInventory(bread=1),
            personality=FOUNDERS[i][0],
            goals=FOUNDERS[i][1],
            goal_weights=GoalWeights(
                **dict(zip(("wealth", "influence", "safety", "reputation"), FOUNDERS[i][2]))
            ),
        )
    buildings = {
        kind: Building(
            id=kind,
            name=name,
            kind=kind,
            plot_id=f"plot-{i}",
            position=plots[f"plot-{i}"].position.model_copy(),
            owner_id=f"citizen-{i}",
            inventory=ResourceInventory(
                wheat=12 if kind != "market" else 0, bread=16 if kind == "bakery" else 0
            ),
        )
        for i, (kind, name) in enumerate(
            [
                ("farm", "Goldenfield Farm"),
                ("bakery", "Hearth & Grain"),
                ("market", "Market Square"),
            ]
        )
    }
    # Building plots belong to their building's owner. Elena is also a landlord: Mira rents
    # plot-5 as her home. plot-3 and plot-4 stay unowned town land, open to anyone.
    for building in buildings.values():
        plots[building.plot_id].owner_id = building.owner_id
    home = plots["plot-5"]
    home.owner_id, home.tenant_id, home.rent = "citizen-0", "citizen-5", 300
    return WorldState(
        branch_id=branch_id,
        seed=seed,
        citizens=citizens,
        buildings=buildings,
        plots=plots,
        # Shared wheat field: about one farm's harvest plus room for gathering each day.
        resources=default_resources(),
        inventions=initial_inventions(),
        rng_state=json.loads(json.dumps(random.Random(seed).getstate())),
    )
