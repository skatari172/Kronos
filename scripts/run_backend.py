"""Run from the repo root; keeps backend modules independently importable."""

import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
for source in [
    "backend/api/src",
    *[f"backend/modules/{name}/src" for name in ["simulation", "agents", "history"]],
]:
    sys.path.insert(0, str(ROOT / source))

if __name__ == "__main__":
    uvicorn.run(
        "kronos.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[str(ROOT / "backend")],
    )
