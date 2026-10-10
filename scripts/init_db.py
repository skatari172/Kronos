"""Initialize or seed the default SQLite database in backend/database/."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for source in [
    "backend/api/src",
    *[f"backend/modules/{name}/src" for name in ["simulation", "agents", "history"]],
]:
    sys.path.insert(0, str(ROOT / source))

from kronos.config import Settings  # noqa: E402
from kronos_history.store import HistoryStore  # noqa: E402
from kronos_sim.models import BranchMetadata  # noqa: E402
from kronos_sim.seed import initial_world  # noqa: E402


def init_database(db_url: str | None = None) -> Path:
    settings = Settings()
    url = db_url or settings.database_url
    print(f"Initializing database at: {url}")
    store = HistoryStore(url)
    if store.active_id() is None:
        store.create(
            initial_world(settings.seed), BranchMetadata(id="main", name="Original timeline")
        )
        store.activate("main")
        print("Created 'main' branch with initial seeded world.")
    else:
        print(f"Database already initialized. Active branch: {store.active_id()}")
    store.close()
    if url.startswith("sqlite:///"):
        return Path(url.removeprefix("sqlite:///")).resolve()
    return Path(url)


if __name__ == "__main__":
    init_database()
