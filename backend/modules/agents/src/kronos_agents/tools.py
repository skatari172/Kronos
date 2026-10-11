"""The player's toolkit as native LLM tools.

Each tool is small: its own parameters and the ones it requires. A model either calls one
tool, or answers in plain text when the request is conversation, a question, or something
the toolkit cannot do; that text goes back to the player and the world is left unchanged.
`service.Service._execute_determined_tool` runs a chosen tool by its `tool` name and
`endpoint`, so `internal` keeps the names it already understands.
"""

from typing import Any

from kronos_sim.models import DeterminedToolCall, ToolParameters

_CITIZEN = {"type": "string", "description": "Citizen ID from the context, e.g. citizen-3"}
_BUILDING = {"type": "string", "description": "Building ID from the context, e.g. bakery"}
_PLOT = {"type": "string", "description": "Plot ID from the context, e.g. plot-3"}
_CENTS = "Integer cents (1 coin = 100 cents)"
_POLICY = {"type": "string", "enum": ["min_wage", "bread_price_cap", "market_tax"]}
_KIND = {"type": "string", "enum": ["farm", "bakery", "market"]}


def _int(description: str, minimum: int | None = None, maximum: int | None = None) -> dict:
    spec: dict[str, Any] = {"type": "integer", "description": description}
    if minimum is not None:
        spec["minimum"] = minimum
    if maximum is not None:
        spec["maximum"] = maximum
    return spec


# name: (endpoint, internal tool name, description, properties, required)
TOOLS: dict[str, tuple[str, str, str, dict, list[str]]] = {
    "change_bread_prices": (
        "/api/interventions",
        "modify_price",
        "Raise or lower the bread price at every bakery by a percentage.",
        {"percent": _int("Percent change, e.g. 20 or -20", -90, 200)},
        ["percent"],
    ),
    "set_town_wages": (
        "/api/interventions",
        "set_wage_intervention",
        "Change the daily wage at every business: to a fixed amount, or by a percentage.",
        {
            "wage": _int(f"New daily wage. {_CENTS}", 0),
            "percent": _int("Percent change instead of a fixed wage", -90, 200),
        },
        [],
    ),
    "grant_money": (
        "/api/interventions",
        "grant_money",
        "Give coins to one citizen or to everyone; a negative amount takes coins away. "
        "Zero-sum: a gift is a tax on businesses' cash and the well-off, shared out (the town "
        "can only give what it collects); coins taken go to the businesses.",
        {"amount": _int(_CENTS), "citizen_id": _CITIZEN},
        ["amount"],
    ),
    "adjust_wheat": (
        "/api/interventions",
        "adjust_resource",
        "Add or remove wheat from the shared field (harvest boom +50, drought -50), "
        "or set how much regrows each day.",
        {
            "stock_change": _int("Wheat added (positive) or removed (negative)"),
            "regen_per_tick": _int("Wheat that regrows each day", 0),
        },
        [],
    ),
    "adjust_hunger": (
        "/api/interventions",
        "adjust_hunger",
        "Feed or starve one citizen or everyone (feast -30, famine +30). A feast is eaten "
        "from the bakeries' bread (one loaf per 30 hunger), so it fails with empty bakeries.",
        {
            "change": _int("Hunger change; negative is less hungry", -100, 100),
            "citizen_id": _CITIZEN,
        },
        ["change"],
    ),
    "set_policy": (
        "/api/interventions",
        "set_policy",
        "Enact or lift a town policy: minimum wage (cents), bread price cap (cents), or "
        "market tax (basis points, 500 = 5%). A value of 0 lifts it.",
        {"kind": _POLICY, "value": _int("Policy value", 0)},
        ["kind", "value"],
    ),
    "spawn_citizen": (
        "/api/agents",
        "spawn_citizen",
        "Bring a new citizen into the village.",
        {
            "name": {"type": "string"},
            "occupation": {"type": "string"},
            "money": _int(f"Starting money. {_CENTS}", 0),
        },
        ["name"],
    ),
    "found_business": (
        "/api/actions",
        "found_business",
        "Have a citizen found a farm, bakery or market on a plot they may build on.",
        {"actor_id": _CITIZEN, "plot_id": _PLOT, "kind": _KIND, "capital": _int(_CENTS, 0)},
        ["actor_id", "plot_id", "kind"],
    ),
    "set_business_price": (
        "/api/actions",
        "set_price",
        "Have a business owner set the price of bread or wheat at their business.",
        {
            "building_id": _BUILDING,
            "resource": {"type": "string", "enum": ["bread", "wheat"]},
            "price": _int(_CENTS, 1),
        },
        ["building_id", "price"],
    ),
    "set_business_wage": (
        "/api/actions",
        "set_wage",
        "Have a business owner set the daily wage at their business.",
        {"building_id": _BUILDING, "wage": _int(_CENTS, 0)},
        ["building_id", "wage"],
    ),
    "hire": (
        "/api/actions",
        "hire",
        "Have a business owner hire a citizen.",
        {"building_id": _BUILDING, "citizen_id": _CITIZEN},
        ["building_id", "citizen_id"],
    ),
    "fire": (
        "/api/actions",
        "fire",
        "Have a business owner fire one of their workers.",
        {"building_id": _BUILDING, "citizen_id": _CITIZEN},
        ["building_id", "citizen_id"],
    ),
    "upgrade_building": (
        "/api/actions",
        "upgrade_building",
        "Have a business owner upgrade their building one level.",
        {"building_id": _BUILDING},
        ["building_id"],
    ),
    "close_business": (
        "/api/actions",
        "close_business",
        "Have a business owner close their business.",
        {"building_id": _BUILDING},
        ["building_id"],
    ),
    "lease_lot": (
        "/api/actions",
        "lease_lot",
        "Have a citizen lease a vacant plot as their home.",
        {"actor_id": _CITIZEN, "plot_id": _PLOT},
        ["actor_id", "plot_id"],
    ),
    "set_rent": (
        "/api/actions",
        "set_rent",
        "Have a plot's owner set its rent.",
        {"plot_id": _PLOT, "rent": _int(_CENTS, 0)},
        ["plot_id", "rent"],
    ),
    "evict": (
        "/api/actions",
        "evict",
        "Have a plot's owner evict a tenant who is behind on rent.",
        {"plot_id": _PLOT},
        ["plot_id"],
    ),
    "propose_vote": (
        "/api/actions",
        "propose_vote",
        "Have a citizen propose a town vote on a policy.",
        {"actor_id": _CITIZEN, "kind": _POLICY, "value": _int("Policy value", 0)},
        ["actor_id", "kind", "value"],
    ),
    "advance_day": (
        "/api/simulation/tick",
        "simulation_tick",
        "Advance the simulation by one day.",
        {},
        [],
    ),
    "set_playback": (
        "/api/simulation/play",
        "simulation_playback",
        "Play or pause the simulation clock, optionally at speed 1, 2 or 4.",
        {"playing": {"type": "boolean"}, "speed": {"type": "integer", "enum": [1, 2, 4]}},
        ["playing"],
    ),
}


def tool_definitions() -> list[dict]:
    """Anthropic `tools` for the Messages API, in a stable order (prompt-cache friendly)."""
    return [
        {
            "name": name,
            "description": description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        }
        for name, (_, _, description, properties, required) in TOOLS.items()
    ]


def tool_call(name: str, arguments: dict, rationale: str = "") -> DeterminedToolCall:
    """The executable call for a tool the model chose. Unknown names raise ValueError."""
    if name not in TOOLS:
        raise ValueError(f"Unknown tool {name!r}")
    endpoint, internal, *_ = TOOLS[name]
    if internal == "simulation_playback" and arguments.get("playing") is False:
        endpoint = "/api/simulation/pause"
    return DeterminedToolCall(
        endpoint=endpoint,  # type: ignore[arg-type]
        tool=internal,
        parameters=ToolParameters(**arguments),
        rationale=rationale[:300],
    )
