import json
import random

from kronos_sim.models import (
    Building,
    Citizen,
    Plot,
    Position,
    ResourceInventory,
    WorldState,
    default_resources,
)


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
    return WorldState(
        branch_id=branch_id,
        seed=seed,
        citizens=citizens,
        buildings=buildings,
        plots=plots,
        # Shared wheat field: about one farm's harvest plus room for gathering each day.
        resources=default_resources(),
        rng_state=json.loads(json.dumps(random.Random(seed).getstate())),
    )
