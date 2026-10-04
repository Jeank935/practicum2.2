"""Formato de lectura y destinos de navegación; no altera eventos almacenados."""

import os
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from practicum_soc.core.browsing_config import SETTINGS
from practicum_soc.core.config import load_json
from practicum_soc.core.paths import PROJECT_ROOT


def format_local_datetime(value: str | datetime | None) -> str:
    if not value:
        return "Sin datos"
    try:
        moment = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return "Fecha no disponible"
    if moment.tzinfo is None:
        return "Fecha sin zona horaria"
    return moment.astimezone(ZoneInfo(SETTINGS.timezone)).strftime("%d/%m/%Y · %H:%M:%S")


def grafana_dashboard_url() -> str:
    config = load_json(PROJECT_ROOT / "config/interface.json")
    url = os.environ.get("SOC_GRAFANA_DASHBOARDS_URL") or config["grafana_dashboard_url"]
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or any(character.isspace() for character in url)
    ):
        raise ValueError("El destino de Grafana debe ser una URL HTTP(S) sin credenciales")
    return url
