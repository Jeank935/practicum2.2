"""Adaptadores HTTP: mismo servicio de lectura para HTML y API v1."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from practicum_soc.api.dependencies import get_reader
from practicum_soc.schemas.browsing import (
    AlertPage,
    AlertQuery,
    ErrorResponse,
    ServicePage,
    ServiceQuery,
)
from practicum_soc.services.browsing import BrowseService

router = APIRouter(
    prefix="/api/v1",
    tags=["Consultas SOC"],
    responses={code: {"model": ErrorResponse} for code in (400, 401, 403, 422, 429, 503)},
)


@router.get("/alerts", response_model=AlertPage)
def alerts(
    reader: Annotated[BrowseService, Depends(get_reader)], query: Annotated[AlertQuery, Query()]
):
    return reader.alerts(query)


@router.get("/services", response_model=ServicePage)
def services(
    reader: Annotated[BrowseService, Depends(get_reader)], query: Annotated[ServiceQuery, Query()]
):
    return reader.services(query)
