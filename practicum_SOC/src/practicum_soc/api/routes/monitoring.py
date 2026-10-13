"""Rutas de monitoring; coordinan validación y servicios sin reglas SOC."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from practicum_soc.api.dependencies import get_dashboard
from practicum_soc.repositories.factory import open_store
from practicum_soc.services.dashboard import DashboardService

router = APIRouter()


@router.get("/health")
def health(
    service: Annotated[DashboardService, Depends(get_dashboard)],
):
    return service.health()


@router.get("/api/v1/operations/metrics")
def operations_metrics(
    service: Annotated[DashboardService, Depends(get_dashboard)], request: Request
):
    if request.state.operator["role"] != "administrator":
        raise HTTPException(403, "Se requiere rol administrador")
    return service.operational_metrics()


@router.get("/healthz")
def readiness(request: Request):

    try:
        with open_store(request.app.state.soc_state_db) as store:
            store.connection.execute("SELECT 1").fetchone()
        return {"status": "ok"}
    except Exception:
        raise HTTPException(503, "Servicio no disponible") from None


@router.post("/demo/run")
def demo_run(
    service: Annotated[DashboardService, Depends(get_dashboard)],
    request: Request,
):
    if request.app.state.production:
        raise HTTPException(404, "Operación no disponible en producción")
    if request.state.operator["role"] != "administrator":
        raise HTTPException(403, "Se requiere rol administrador")
    try:
        return service.run_demo()
    except FileNotFoundError:
        raise HTTPException(
            status_code=409, detail="No está preparado el dataset de demostración"
        ) from None


@router.get("/reports/latest")
def latest_report(
    service: Annotated[DashboardService, Depends(get_dashboard)],
):
    report = service.latest_report()
    if not report.is_file():
        raise HTTPException(status_code=404, detail="Reporte no generado")
    return FileResponse(report, media_type="text/markdown", filename=report.name)
