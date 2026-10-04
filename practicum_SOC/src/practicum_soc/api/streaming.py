"""Señales SSE acotadas; nunca transmiten eventos de autenticación ni PII."""

from __future__ import annotations

import asyncio
import json
import logging
from time import monotonic

from starlette.concurrency import run_in_threadpool

from practicum_soc.core.auth_config import AuthSettings
from practicum_soc.core.config import load_json
from practicum_soc.repositories.auth import AuthStore
from practicum_soc.repositories.factory import open_store
from practicum_soc.services.dashboard import DashboardService

LOGGER = logging.getLogger(__name__)


def stream_settings(path):
    values = load_json(path)
    check = int(values["stream_check_seconds"])
    maximum = int(values["stream_max_seconds"])
    if check < 2 or maximum < check or maximum > 600:
        raise ValueError("Intervalos SSE inválidos")
    return check, maximum


def event_line(name: str, value: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(value, separators=(',', ':'))}\n\n"


def session_still_valid(state_db, token: str, settings: AuthSettings) -> bool:
    if settings.mode == "disabled":
        return True
    if not token:
        return False
    with open_store(state_db) as store:
        return AuthStore(store, settings.policy).session(token, touch=False) is not None


async def revision_stream(request, dashboard: DashboardService, interval: int, maximum: int):
    started = monotonic()
    previous = None
    token = request.cookies.get("soc_session", "")
    settings = AuthSettings.from_env()
    yield "retry: 3000\n\n"
    while monotonic() - started < maximum:
        if await request.is_disconnected():
            return
        try:
            authorized = await run_in_threadpool(
                session_still_valid, request.app.state.soc_state_db, token, settings
            )
            if not authorized:
                yield event_line("session-expired", {})
                return
            version = await run_in_threadpool(dashboard.dashboard_version)
        except Exception as error:
            LOGGER.warning("SSE temporalmente no disponible: %s", type(error).__name__)
            yield event_line("unavailable", {})
            return
        if version["revision"] != previous:
            previous = version["revision"]
            yield event_line("revision", version)
        else:
            yield ": keepalive\n\n"
        await asyncio.sleep(interval)
