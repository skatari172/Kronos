"""Shared dependency wiring for the local simulation session."""

from typing import Annotated

from fastapi import Depends, Request

from kronos.service import Service


def get_service(request: Request) -> Service:
    return request.app.state.service


ServiceDependency = Annotated[Service, Depends(get_service)]
