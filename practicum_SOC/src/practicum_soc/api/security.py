"""Controles ASGI con memoria acotada, sin alterar el contenido de las páginas."""

import asyncio
import logging

from starlette.middleware.trustedhost import TrustedHostMiddleware

from practicum_soc.api.errors import problem

LOGGER = logging.getLogger(__name__)


class HealthcheckTrustedHostMiddleware(TrustedHostMiddleware):
    """La sonda Docker local solo puede exceptuar el host de /healthz."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/healthz":
            hosts = [value for key, value in scope.get("headers", []) if key.lower() == b"host"]
            if len(hosts) == 1 and hosts[0].split(b":")[0] in {b"127.0.0.1", b"localhost"}:
                return await self.app(scope, receive, send)
        return await super().__call__(scope, receive, send)


class SecurityMiddleware:
    def __init__(self, app, policy, production=False):
        self.app, self.policy, self.production = app, policy, production

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def secured_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                additions = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"no-referrer",
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
                    b"content-security-policy": self.policy.content_security_policy.encode("ascii"),
                }
                # Swagger/ReDoc locales conservan sus recursos previos; no existen en producción.
                if not self.production and scope["path"] in {"/docs", "/redoc"}:
                    additions.pop(b"content-security-policy")
                if self.production:
                    additions[b"strict-transport-security"] = (
                        f"max-age={self.policy.hsts_max_age_seconds}".encode()
                    )
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() not in additions
                ]
                message = {**message, "headers": [*headers, *additions.items()]}
            await send(message)

        async def reject(status, detail):
            response = problem(status, detail)
            await response(scope, receive, secured_send)

        if len(scope.get("query_string", b"")) > self.policy.maximum_query_bytes:
            return await reject(414, "Consulta demasiado larga")
        if self.production and scope.get("scheme") != "https" and scope["path"] != "/healthz":
            return await reject(403, "HTTPS es obligatorio")
        headers = scope.get("headers", [])
        lengths = [value for key, value in headers if key.lower() == b"content-length"]
        transfer_encoding = any(key.lower() == b"transfer-encoding" for key, _ in headers)
        if (
            len(lengths) > 1
            or (lengths and (not lengths[0].isdigit() or len(lengths[0]) > 10))
            or (lengths and transfer_encoding)
        ):
            return await reject(400, "Longitud de petición inválida")
        if lengths and int(lengths[0]) > self.policy.maximum_request_bytes:
            return await reject(413, "Petición demasiado grande")
        has_body = (
            lengths or scope["method"] in {"POST", "PATCH", "PUT", "DELETE"} or transfer_encoding
        )
        downstream_receive = receive
        if has_body:
            chunks, size = [], 0
            try:
                async with asyncio.timeout(self.policy.request_body_timeout_seconds):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        chunk = message.get("body", b"")
                        size += len(chunk)
                        if size > self.policy.maximum_request_bytes:
                            return await reject(413, "Petición demasiado grande")
                        chunks.append(chunk)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                return await reject(408, "Tiempo de recepción agotado")
            if lengths and size != int(lengths[0]):
                return await reject(400, "Longitud de petición inconsistente")
            body, delivered = b"".join(chunks), False

            async def replay_body():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            downstream_receive = replay_body
        try:
            await self.app(scope, downstream_receive, secured_send)
        except Exception as error:
            LOGGER.error("http_unavailable error_type=%s", type(error).__name__)
            if started:
                raise
            await reject(503, "Servicio temporalmente no disponible")
