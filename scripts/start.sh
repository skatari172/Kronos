#!/usr/bin/env bash
# One command for a fresh KRONOS session:
#   1. install tools and dependencies if missing (and the Claude SDK when .env uses it)
#   2. create .env from .env.example if there is none, and check the Claude key
#   3. stop old servers, then reset the database to a fresh day-0 village
#   4. start the backend, wait until it is healthy, then start the frontend
#   5. open the browser; Ctrl+C stops everything
#
#   ./scripts/start.sh          # fresh village (resets the database)
#   ./scripts/start.sh --keep   # keep the current village
set -euo pipefail
cd "$(dirname "$0")/.."

KEEP=false
[ "${1:-}" = "--keep" ] && KEEP=true
BACKEND=http://127.0.0.1:8000
FRONTEND=http://127.0.0.1:5173
UV=$(command -v uv 2>/dev/null || echo "$PWD/.tools/python/bin/uv")
PNPM=$(command -v pnpm 2>/dev/null || echo "$PWD/.tools/node/node_modules/.bin/pnpm")
export PATH="$(dirname "$PNPM"):$PATH"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/.cache/uv}"

step() { printf '\n\033[1;33m▸ %s\033[0m\n' "$1"; }

step "Checking tools and dependencies"
if [ ! -x "$UV" ] || [ ! -x "$PNPM" ] || [ ! -d .venv ] || [ ! -d node_modules ]; then
  make install
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example (mock agents; no key needed)."
fi
provider=$(grep -E '^KRONOS_LLM_PROVIDER=' .env | tail -1 | cut -d= -f2 | tr -d '[:space:]')
provider=${provider:-mock}
echo "Agents: $provider"
if [ "$provider" = "anthropic" ]; then
  # `make install` syncs without extras, so add the Claude SDK back every time (fast when present).
  "$UV" sync --extra anthropic --quiet
  if ! "$UV" run python scripts/check_anthropic_key.py 2>/dev/null; then
    echo "Claude key check failed: villagers will fall back to the utility rule."
    echo "Fix ANTHROPIC_API_KEY in .env, or set KRONOS_LLM_PROVIDER=mock."
  fi
fi
if [ "$provider" = "gemini" ]; then
  # `make install` syncs without extras, so add the Gemini SDK back every time (fast when present).
  "$UV" sync --extra gemini --quiet
fi

step "Stopping old servers"
make stop >/dev/null

if [ "$KEEP" = false ]; then
  step "Resetting the database to a fresh village"
  "$UV" run python scripts/reset_data.py
  "$UV" run python scripts/init_db.py
else
  echo "Keeping the current village (--keep)."
fi

# Both servers run in this script's process group; Ctrl+C or any exit stops them together.
trap 'echo; echo "Stopping KRONOS…"; kill 0 2>/dev/null' EXIT INT TERM

step "Starting the backend on $BACKEND"
"$UV" run python scripts/run_backend.py 2>&1 | sed -u 's/^/[backend]  /' &
for _ in $(seq 1 60); do
  curl -sf "$BACKEND/health" >/dev/null && break
  sleep 0.5
done
if ! curl -sf "$BACKEND/health" >/dev/null; then
  echo "The backend did not start; see the [backend] lines above."
  exit 1
fi
echo "Backend healthy: $(curl -s "$BACKEND/health")"

step "Starting the frontend on $FRONTEND"
"$PNPM" dev 2>&1 | sed -u 's/^/[frontend] /' &
for _ in $(seq 1 60); do
  curl -sf "$FRONTEND" >/dev/null && break
  sleep 0.5
done

step "KRONOS is running at $FRONTEND  (Ctrl+C to stop)"
[ -z "${KRONOS_NO_OPEN:-}" ] && command -v open >/dev/null && open "$FRONTEND" || true
wait
