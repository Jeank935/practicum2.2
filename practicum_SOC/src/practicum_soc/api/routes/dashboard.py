"""Rutas de dashboard; coordinan validación y servicios sin reglas SOC."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse

from practicum_soc.api.dependencies import get_dashboard
from practicum_soc.api.streaming import revision_stream, stream_settings
from practicum_soc.core.config import load_json
from practicum_soc.core.paths import PROJECT_ROOT as ROOT
from practicum_soc.core.presentation import grafana_dashboard_url
from practicum_soc.services.dashboard import DashboardService

router = APIRouter()


@router.get("/")
def dashboard(service: Annotated[DashboardService, Depends(get_dashboard)], request: Request):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            **service.overview(),
            "live_updates": load_json(ROOT / "config" / "live_updates.json"),
        },
    )


@router.get("/dashboard", include_in_schema=False)
def grafana_dashboard():
    try:
        return RedirectResponse(grafana_dashboard_url(), status_code=303)
    except (ValueError, KeyError):
        raise HTTPException(503, "El enlace de Grafana no está configurado correctamente") from None


@router.get("/api/dashboard-version")
def dashboard_version(
    service: Annotated[DashboardService, Depends(get_dashboard)],
):
    return service.dashboard_version()


@router.get("/api/v1/dashboard/snapshot")
def dashboard_snapshot(
    service: Annotated[DashboardService, Depends(get_dashboard)], request: Request
):
    snapshot = service.dashboard_snapshot()
    html = request.app.state.templates.env.get_template("partials/alerts_table.html").render(
        alerts=snapshot.pop("recent_alerts")
    )
    return {**snapshot, "recent_html": html}


@router.get("/api/v1/dashboard/stream")
async def dashboard_stream(
    service: Annotated[DashboardService, Depends(get_dashboard)], request: Request
):
    interval, maximum = stream_settings(ROOT / "config" / "live_updates.json")
    return StreamingResponse(
        revision_stream(request, service, interval, maximum),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )
