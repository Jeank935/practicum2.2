"""Rutas de services; coordinan validación y servicios sin reglas SOC."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from practicum_soc.api.dependencies import get_dashboard
from practicum_soc.api.dependencies import get_reader as reader
from practicum_soc.api.navigation import navigation
from practicum_soc.schemas.browsing import ServiceQuery
from practicum_soc.services.dashboard import DashboardService

router = APIRouter()


@router.get("/services")
def services_page(
    service: Annotated[DashboardService, Depends(get_dashboard)],
    request: Request,
    query: Annotated[ServiceQuery, Query()],
):
    result = reader(request).services(query, with_summary=True)
    from practicum_soc.services.dashboard import SOURCE_LABELS

    return request.app.state.templates.TemplateResponse(
        request=request,
        name="services.html",
        context={
            "metrics": result["metrics"],
            "page": result["page"],
            "filters": query.model_dump(mode="json"),
            "catalog": service._service_catalog()["labels"],
            "nav": navigation("/services", query, result["page"]),
            "source_label": SOURCE_LABELS.get(result["source"], result["source"]),
            "available_windows": [0, 1, 7, 30],
        },
    )


@router.get("/api/services-version")
def services_version(request: Request, query: Annotated[ServiceQuery, Query()]):
    return reader(request).revision()
