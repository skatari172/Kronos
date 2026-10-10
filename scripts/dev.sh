#!/usr/bin/env bash
# Run everything KRONOS needs locally: dependencies, the SQLite database, the API and the 3D frontend.
#   scripts/dev.sh              start (installs dependencies on first run)
#   scripts/dev.sh --install    reinstall locked dependencies first
#   scripts/dev.sh --anthropic  also install the optional Claude provider (set ANTHROPIC_API_KEY
#                               and KRONOS_LLM_PROVIDER=anthropic in .env to use it)
#   scripts/dev.sh --reset      start from a fresh seeded world (deletes local SQLite data)
# Ctrl+C stops both servers.
set -euo pipefail
cd "$(dirname "$0")/.."

install=false anthropic=false reset=false
for arg in "$@"; do
  case "$arg" in
    --install) install=true ;;
    --anthropic) anthropic=true install=true ;;
    --reset) reset=true ;;
    -h | --help)
      sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (try --help)" >&2
      exit 1
      ;;
  esac
done

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

# 1. Dependencies: uv/pnpm (installed into .tools/ if missing) and the locked Python and Node packages.
if $install || [ ! -d .venv ] || [ ! -d node_modules ]; then
  say "Installing dependencies"
  make install
fi
UV=$(command -v uv 2>/dev/null || echo "$PWD/.tools/python/bin/uv")
if $anthropic; then
  say "Installing the optional Anthropic provider"
  "$UV" sync --frozen --extra anthropic
fi
[ -f .env ] || { cp .env.example .env && say "Created .env from .env.example"; }

# 2. Database: free the ports first so the API isn't holding the SQLite file, then seed if needed.
make stop >/dev/null
if $reset; then
  say "Resetting local data"
  make reset
fi
say "Preparing the SQLite database"
make db-init

# 3. Servers. Job control gives each its own process group so Ctrl+C stops the whole tree.
set -m
pids=()
cleanup() {
  trap - INT TERM EXIT
  echo
  say "Stopping servers"
  for pid in "${pids[@]}"; do kill -- "-$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

say "Starting backend on http://localhost:8000 (API docs at /docs)"
"$UV" run python scripts/run_backend.py &
pids+=($!)

for _ in $(seq 1 60); do
  curl -sf http://localhost:8000/health >/dev/null && break
  if ! kill -0 "${pids[0]}" 2>/dev/null; then
    echo "Backend failed to start; see the output above." >&2
    exit 1
  fi
  sleep 0.5
done

say "Starting frontend on http://localhost:5173"
make frontend &
pids+=($!)

say "KRONOS is running. Open http://localhost:5173 — press Ctrl+C to stop."
# Exit (and stop the other server) as soon as either one dies.
while kill -0 "${pids[0]}" 2>/dev/null && kill -0 "${pids[1]}" 2>/dev/null; do sleep 1; done
echo "A server exited; shutting down." >&2
