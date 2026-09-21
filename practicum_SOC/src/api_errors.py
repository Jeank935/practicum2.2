"""Respuestas consistentes sin reflejar datos de entrada en mensajes de error."""

from fastapi.responses import JSONResponse


def problem(status, message, *, fields=None, headers=None):
    code = {
        400: "invalid_cursor",
        401: "unauthenticated",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
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
