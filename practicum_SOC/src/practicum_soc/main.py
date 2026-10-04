"""Composición de FastAPI; las rutas y el motor viven en módulos separados."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from practicum_soc.api.errors import install_error_handlers
from practicum_soc.api.routes import alerts, auth, browsing, dashboard, monitoring, rules, services
from practicum_soc.api.routes.auth import AuthAccessFilter, AuthenticationMiddleware
from practicum_soc.core.auth_config import AuthSettings
from practicum_soc.core.paths import PROJECT_ROOT
from practicum_soc.core.presentation import format_local_datetime
from practicum_soc.repositories.factory import open_store
from practicum_soc.services.configuration_audit import observe_configuration
from practicum_soc.services.dashboard import DashboardService

ROOT = PROJECT_ROOT


def observe_deployment(application):
    with open_store(application.state.soc_state_db) as store:
        observe_configuration(store, application.state.config_dir, AuthSettings.from_env().policy)


@asynccontextmanager
async def lifespan(application):
    await run_in_threadpool(observe_deployment, application)
    try:
        yield
    finally:
        resources = application.state.dashboard_service
        if hasattr(resources, "clear_caches"):
            resources.clear_caches()


def create_app(dashboard_service: DashboardService | None = None) -> FastAPI:
    state_db = Path(os.environ.get("SOC_STATE_DB", str(ROOT / "analysis/state/soc_alerts.db")))
    if dashboard_service is not None:
        state_db = dashboard_service.state_db
    application = FastAPI(title="Bandeja SOC ADFS", version="1.0.0", lifespan=lifespan)
    application.state.soc_state_db = state_db
    application.state.config_dir = ROOT / "config"
    application.state.dashboard_service = dashboard_service or DashboardService(
        state_db=state_db,
        analysis_dir=ROOT / "analysis",
        detection_config=ROOT / "config/detection_rules.json",
        operational_config=ROOT / "config/operational.json",
    )
    application.state.dashboard_factory = lambda: application.state.dashboard_service
    application.state.templates = Jinja2Templates(directory=ROOT / "templates")
    application.state.templates.env.filters["local_datetime"] = format_local_datetime
    application.add_middleware(AuthenticationMiddleware)
    for module in (auth, browsing, rules, alerts, dashboard, monitoring, services):
        application.include_router(module.router)
    install_error_handlers(application, application.state.templates)
    logging.getLogger("uvicorn.access").addFilter(AuthAccessFilter())
    application.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return application


app = create_app()
