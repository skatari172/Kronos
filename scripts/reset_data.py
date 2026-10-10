"""Reset only the default local SQLite files. Stop the API first."""

from pathlib import Path

root = Path(__file__).resolve().parents[1]
db_dir = root / "backend" / "database"
for target_dir in (db_dir, root):
    for name in ("kronos.db", "kronos.db-wal", "kronos.db-shm"):
        (target_dir / name).unlink(missing_ok=True)
print("Default local world reset. Restart the API to create a fresh village.")
