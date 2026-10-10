"""Export without starting the app or creating a database."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for source in [
    "backend/api/src",
    "backend/modules/simulation/src",
    "backend/modules/agents/src",
    "backend/modules/history/src",
]:
    sys.path.insert(0, str(ROOT / source))

from kronos.main import create_app  # noqa: E402
from kronos_sim.models import WorldUpdate  # noqa: E402
from kronos_sim.seed import initial_world  # noqa: E402

(ROOT / "backend/contracts/schemas/openapi.json").write_text(
    json.dumps(create_app().openapi(), indent=2) + "\n"
)
state = initial_world(branch_id="offline")
(ROOT / "backend/contracts/generated/initial-world.json").write_text(
    WorldUpdate(branch_id=state.branch_id, tick=0, sequence=0, state=state).model_dump_json(
        indent=2
    )
    + "\n"
)
