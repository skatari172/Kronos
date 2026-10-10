"""Application setup; endpoint behavior lives in routes/."""

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from kronos_agents.provider import ProviderError
from kronos_sim.engine import InvalidAction

from kronos.config import Settings
from kronos.routes import (
    agents,
    backend,
    businesses,
    history,
    inventions,
    loans,
    market,
    resources,
    user,
    world,
)
from kronos.service import Service


def create_app(config: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        app.state.service = Service(config or Settings())
        task = asyncio.create_task(app.state.service.loop())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            app.state.service.store.close()

    app = FastAPI(
        title="KRONOS",
        version="0.1.0",
        lifespan=lifespan,
        description=(
            "Tools organized by caller and responsibility. All mutations are validated by the "
            "simulation engine and saved before broadcasting. Caller groups describe intended "
            "usage in one trusted local session; they are not authentication boundaries."
        ),
        openapi_tags=[
            {
                "name": "User tools",
                "description": "Player interventions and explicit citizen actions.",
            },
            {
                "name": "Agent tools",
                "description": "Citizen observations, proposal validation, and execution.",
            },
            {
                "name": "Backend tools",
                "description": "Simulation clock, village creation, health, and automation.",
            },
            {
                "name": "World",
                "description": "Authoritative world queries. Live updates use WS /ws/world.",
            },
            {"name": "History", "description": "Events, checkpoints, and alternate timelines."},
        ],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(InvalidAction)
    @app.exception_handler(ProviderError)
    async def bad_action(request, exc):
        content = {"detail": str(exc), "code": getattr(exc, "code", None)}
        return JSONResponse(status_code=422, content=content)

    @app.exception_handler(KeyError)
    async def not_found(request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    routers = (
        user,
        agents,
        businesses,
        loans,
        market,
        resources,
        inventions,
        backend,
        world,
        history,
    )
    for module in routers:
        app.include_router(module.router)
    return app


app = create_app()
