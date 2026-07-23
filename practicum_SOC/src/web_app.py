"""Rutas HTTP del MVP; delegan toda la lógica en DashboardService."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from dashboard_service import DashboardService

ROOT = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=ROOT / "templates")
service = DashboardService(
    state_db=ROOT / "analysis" / "state" / "soc_alerts.db",
    analysis_dir=ROOT / "analysis",
    detection_config=ROOT / "config" / "detection_rules.json",
    operational_config=ROOT / "config" / "operational.json",
)

app = FastAPI(title="Bandeja SOC ADFS", version="1.0.0")
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
    severity: str | None = Query(default=None),
    status: str | None = Query(default=None),
    rule_id: str | None = Query(default=None),
):
    return templates.TemplateResponse(
        request=request,
        name="alerts.html",
        context={
            "alerts": service.list_alerts(severity=severity, status=status, rule_id=rule_id),
            "filters": {"severity": severity, "status": status, "rule_id": rule_id},
        },
    )


@app.get("/alerts/{alert_id}")
def alert_detail(request: Request, alert_id: str):
    alert = service.alert_detail(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    return templates.TemplateResponse(
        request=request,
        name="alert_detail.html",
        context={"alert": alert},
    )


@app.patch("/alerts/{alert_id}/status")
def update_alert_status(alert_id: str, payload: StatusUpdate):
    try:
        return service.update_status(alert_id, payload.status, payload.note)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Alerta no encontrada") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/health")
def health():
    return service.health()


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
