#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Install missing tools locally; no global npm/pip changes or administrator privileges.
if ! command -v uv >/dev/null && [ ! -x .tools/python/bin/uv ]; then
  python3 -m pip install --target .tools/python 'uv==0.13.0'
fi
if ! command -v pnpm >/dev/null && [ ! -x .tools/node/node_modules/.bin/pnpm ]; then
  npm install --prefix .tools/node 'pnpm@10.32.1'
fi
