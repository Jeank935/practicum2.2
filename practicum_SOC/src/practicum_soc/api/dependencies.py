"""Recursos compartidos por aplicación e inyección de servicios ligeros."""

import os

from fastapi import Request

from practicum_soc.services.browsing import BrowseService
from practicum_soc.services.dashboard import DashboardService


def get_dashboard(request: Request) -> DashboardService:
    return request.app.state.dashboard_factory()


def get_reader(request: Request) -> BrowseService:
    dashboard = get_dashboard(request)
    root = request.app.state.config_dir.parent
    secret = os.environ.get("SOC_CURSOR_SECRET") or os.environ.get("SOC_OIDC_CLIENT_SECRET")
    if not secret:
        key_file = root / ".secrets/pseudonym_key.txt"
        secret = os.environ.get("SOC_PSEUDONYM_KEY") or (
            key_file.read_text().strip() if key_file.is_file() else ""
        )
    return BrowseService(dashboard, secret)
