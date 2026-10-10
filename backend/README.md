# Backend

One uv environment, four source areas: `api/` orchestrates, `modules/simulation/` owns all world rules, `modules/agents/` proposes typed actions, and `modules/history/` stores committed outcomes. `contracts/` contains generated client artifacts.

Run `make backend` from the root. Pure modules are intentionally not coupled to FastAPI startup. Tests and the launcher configure their source paths explicitly; independent publication as separate Python distributions is deferred until useful. Run a single API worker for the shared local simulation session.

## API route ownership

`api/src/kronos/main.py` wires the app together. Add endpoints in `api/src/kronos/routes/`: `user.py` for player tools, `agents.py` for citizen-agent tools, `backend.py` for simulation operations, `world.py` for state/streaming, and `history.py` for checkpoints and branches. Swagger at `/docs` uses the same groups. Route modules receive the shared service through `dependencies.py`; action routes share `Service.execute_action` so validation and commit ordering remain consistent.
