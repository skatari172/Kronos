# Database

This directory stores the authoritative SQLite database for local KRONOS simulation state.

## Files

- `kronos.db`: The authoritative SQLite database containing:
  - `branches`: Active and historical branch metadata and serialized world states
  - `snapshots`: Immutable point-in-time state checkpoints with SHA-256 integrity hashes
  - `events`: Append-only event ledger tracking actions, prices, transactions, and dialogue
  - `settings`: Active timeline pointer and local simulation configuration
- `*.db-wal`, `*.db-shm`: Ephemeral SQLite write-ahead log and shared memory files (ignored by Git)

## Usage

- Seed / initialize the database: `make db-init` (or start the backend with `make backend`)
- Reset local world: `make reset`
- Custom database URL: configured via `KRONOS_DATABASE_URL` in `.env`
