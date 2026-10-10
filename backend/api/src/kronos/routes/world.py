"""Shared world queries and the live update stream."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from kronos_sim import models as m

from kronos.dependencies import ServiceDependency

router = APIRouter(tags=["World"])


@router.get("/api/world", response_model=m.WorldUpdate, summary="Read the active world")
async def world(service: ServiceDependency):
    return service.update()


@router.websocket("/ws/world")
async def websocket(socket: WebSocket):
    await socket.accept()
    service = socket.app.state.service
    try:
        async with service.lock:
            await socket.send_json(service.update().model_dump(mode="json"))
            service.clients.add(socket)
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        service.clients.discard(socket)
