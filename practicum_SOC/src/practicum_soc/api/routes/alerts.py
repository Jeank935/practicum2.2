"""Rutas de alerts; coordinan validación y servicios sin reglas SOC."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from practicum_soc.api.dependencies import get_dashboard
from practicum_soc.api.dependencies import get_reader as reader
from practicum_soc.api.navigation import navigation, safe_return_path
from practicum_soc.schemas.alerts import StatusUpdate
from practicum_soc.schemas.browsing import AlertQuery
from practicum_soc.services.dashboard import DashboardService

router = APIRouter()


@router.get("/alerts")
def alerts_page(
    service: Annotated[DashboardService, Depends(get_dashboard)],
    request: Request,
    query: Annotated[AlertQuery, Query()],
):
    result = reader(request).alerts(query)
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="alerts.html",
        context={
            "alerts": result["data"],
            "page": result["page"],
            "filters": query.model_dump(mode="json"),
            "nav": navigation("/alerts", query, result["page"]),
            "catalog": service._service_catalog()["labels"],
            "rules": service.enabled_rules(),
        },
    )


@router.get("/alerts/{alert_id}")
def alert_detail(
    service: Annotated[DashboardService, Depends(get_dashboard)],
    request: Request,
    alert_id: str,
    return_to: str | None = Query(None, max_length=8192),
):
    alert = service.alert_detail(alert_id, actor=request.state.operator)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="alert_detail.html",
        context={"alert": alert, "return_to": safe_return_path(return_to)},
    )


@router.patch("/alerts/{alert_id}/status")
def update_alert_status(
    service: Annotated[DashboardService, Depends(get_dashboard)],
    alert_id: str,
    payload: StatusUpdate,
    request: Request,
):
    try:
        actor = request.state.operator
        return service.update_status(
            alert_id,
            payload.status,
            payload.note,
            actor_id=actor["user_id"],
            actor_name=actor["display_name"],
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Alerta no encontrada") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
