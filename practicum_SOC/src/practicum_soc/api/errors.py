from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from practicum_soc.core.cursor import InvalidCursor


def problem(status, message, *, fields=None, headers=None):
    code = {
        400: "invalid_cursor",
        401: "unauthenticated",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        408: "request_timeout",
        413: "payload_too_large",
        414: "query_too_long",
        422: "invalid_query",
        429: "rate_limited",
        500: "internal_error",
        503: "unavailable",
    }.get(status, "request_error")
    return JSONResponse(
        {"error": {"code": code, "message": message, "fields": fields or []}},
        status_code=status,
        headers={"Cache-Control": "no-store", **(headers or {})},
    )


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
