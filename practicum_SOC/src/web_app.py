"""Rutas HTTP del MVP; delegan toda la lógica en DashboardService."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from auth_config import AuthSettings
from auth_web import AuthAccessFilter, AuthenticationMiddleware
from auth_web import router as auth_router
from browse_models import AlertQuery, ServiceQuery
from browse_web import install_error_handlers, navigation, reader, safe_return_path
from browse_web import router as browse_router
from configuration_audit import observe_configuration
from dashboard_service import DashboardService
from store_factory import open_store

ROOT = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=ROOT / "templates")
configured_state_db = Path(
    os.environ.get("SOC_STATE_DB", str(ROOT / "analysis" / "state" / "soc_alerts.db"))
)
service = DashboardService(
    state_db=configured_state_db,
    analysis_dir=ROOT / "analysis",
    detection_config=ROOT / "config" / "detection_rules.json",
    operational_config=ROOT / "config" / "operational.json",
)


def observe_deployment(application):
    with open_store(application.state.soc_state_db) as store:
        observe_configuration(store, application.state.config_dir, AuthSettings.from_env().policy)


@asynccontextmanager
async def lifespan(application):
    await run_in_threadpool(observe_deployment, application)
    yield


app = FastAPI(title="Bandeja SOC ADFS", version="1.0.0", lifespan=lifespan)
app.state.soc_state_db = configured_state_db
app.state.config_dir = ROOT / "config"
app.state.dashboard_factory = lambda: service
app.add_middleware(AuthenticationMiddleware)
app.include_router(auth_router)
app.include_router(browse_router)
install_error_handlers(app, templates)
logging.getLogger("uvicorn.access").addFilter(AuthAccessFilter())
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


class StatusUpdate(BaseModel):
    status: Literal["new", "notified", "investigating", "resolved", "false_positive"]
    note: str = Field(default="", max_length=500)


@app.get("/")
def dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=service.overview(),
    )


@app.get("/alerts")
def alerts_page(
    request: Request,
    query: Annotated[AlertQuery, Query()],
):
    result = reader(request).alerts(query)
    return templates.TemplateResponse(
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


@app.get("/services")
def services_page(request: Request, query: Annotated[ServiceQuery, Query()]):
    result = reader(request).services(query, with_summary=True)
    from dashboard_service import SOURCE_LABELS

    return templates.TemplateResponse(
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


@app.get("/api/services-version")
def services_version(request: Request, query: Annotated[ServiceQuery, Query()]):
    return reader(request).revision()


@app.get("/alerts/{alert_id}")
def alert_detail(
    request: Request, alert_id: str, return_to: str | None = Query(None, max_length=8192)
):
    alert = service.alert_detail(alert_id, actor=request.state.operator)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    return templates.TemplateResponse(
        request=request,
        name="alert_detail.html",
        context={"alert": alert, "return_to": safe_return_path(return_to)},
    )


@app.patch("/alerts/{alert_id}/status")
def update_alert_status(alert_id: str, payload: StatusUpdate, request: Request):
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


@app.get("/health")
def health():
    return service.health()


@app.get("/healthz")
def readiness(request: Request):
    from store_factory import open_store

    try:
        with open_store(request.app.state.soc_state_db) as store:
            store.connection.execute("SELECT 1").fetchone()
        return {"status": "ok"}
    except Exception:
        raise HTTPException(503, "Servicio no disponible") from None


@app.get("/api/dashboard-version")
def dashboard_version():
    return service.dashboard_version()


@app.post("/demo/run")
def demo_run():
    try:
        return service.run_demo()
    except FileNotFoundError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/reports/latest")
def latest_report():
    report = service.latest_report()
    if not report.is_file():
        raise HTTPException(status_code=404, detail="Reporte no generado")
    return FileResponse(report, media_type="text/markdown", filename=report.name)
