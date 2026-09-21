"""Adaptadores HTTP: mismo servicio de lectura para HTML y API v1."""

import os
from typing import Annotated
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from api_errors import problem
from browse_models import AlertPage, AlertQuery, ErrorResponse, ServicePage, ServiceQuery
from browse_service import BrowseService
from page_cursor import InvalidCursor

router = APIRouter(
    prefix="/api/v1",
    tags=["Consultas SOC"],
    responses={code: {"model": ErrorResponse} for code in (400, 401, 403, 422, 429, 503)},
)


def reader(request):
    dashboard = request.app.state.dashboard_factory()
    root = request.app.state.config_dir.parent
    secret = os.environ.get("SOC_CURSOR_SECRET") or os.environ.get("SOC_OIDC_CLIENT_SECRET")
    if not secret:
        key_file = root / ".secrets/pseudonym_key.txt"
        secret = os.environ.get("SOC_PSEUDONYM_KEY") or (
            key_file.read_text().strip() if key_file.is_file() else ""
        )
    return BrowseService(dashboard, secret)


def query_url(path, query, **changes):
    data = query.model_dump(mode="json")
    data.update(changes)
    return (
        path
        + "?"
        + urlencode(
            {
                key: str(value).lower() if isinstance(value, bool) else value
                for key, value in data.items()
                if value is not None
            }
        )
    )


def navigation(path, query, page):
    return {
        "first_url": query_url(path, query, cursor=None),
        "previous_url": query_url(path, query, cursor=page["previous_cursor"])
        if page["has_previous"]
        else None,
        "next_url": query_url(path, query, cursor=page["next_cursor"])
        if page["has_next"]
        else None,
        "return_to": query_url(path, query),
    }


def safe_return_path(value):
    if not value or len(value) > 8192 or any(ch in value for ch in ("\\", "\r", "\n")):
        return "/alerts"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.path not in {"/alerts", "/services"}:
        return "/alerts"
    return value


@router.get("/alerts", response_model=AlertPage)
def alerts(request: Request, query: Annotated[AlertQuery, Query()]):
    return reader(request).alerts(query)


@router.get("/services", response_model=ServicePage)
def services(request: Request, query: Annotated[ServiceQuery, Query()]):
    return reader(request).services(query)


def install_error_handlers(app, templates):
    async def render_error(request, status, message, fields=None, headers=None):
        if request.url.path.startswith("/api/v1/"):
            return problem(status, message, fields=fields, headers=headers)
        if request.url.path in {"/alerts", "/services"}:
            # Los parámetros inválidos no se reflejan en el HTML de errores.
            response = templates.TemplateResponse(
                request=request,
                name="browse_error.html",
                context={"message": message, "retry_path": request.url.path},
                status_code=status,
            )
            response.headers["Cache-Control"] = "no-store"
            return response
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": message}, status_code=status, headers=headers)

    @app.exception_handler(InvalidCursor)
    async def bad_cursor(request, error):
        return await render_error(request, 400, str(error))

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def validation_error(request, error):
        fields = [".".join(str(part) for part in item["loc"]) for item in error.errors()]
        return await render_error(
            request, 422, "Revisa los filtros, las fechas y el tamaño de página.", fields
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return await render_error(
            request, error.status_code, str(error.detail), headers=error.headers
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        import logging

        logging.getLogger(__name__).error("Fallo de lectura HTTP: %s", type(error).__name__)
        return await render_error(
            request, 503, "No se pudo cargar la información. Vuelve a intentarlo."
        )
