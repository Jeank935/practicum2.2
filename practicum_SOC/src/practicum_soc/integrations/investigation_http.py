"""HTTP directo, sin MCP, sin redirecciones ni texto de error del proveedor."""

import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from practicum_soc.integrations.oidc import NoRedirects


class ProviderFailure(ValueError):
    def __init__(self, code, *, retryable=False):
        self.code, self.retryable = code, retryable
        super().__init__(code)


def request_json(url, headers, *, payload=None, timeout=30, maximum_bytes=131072):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, headers={"Accept": "application/json", **headers})
    started = time.monotonic()
    try:
        # No usar proxies de entorno que puedan cambiar el destino autorizado.
        with build_opener(ProxyHandler({}), NoRedirects).open(request, timeout=timeout) as response:
            parts, size = [], 0
            while chunk := response.read1(4096):
                size += len(chunk)
                if size > maximum_bytes or time.monotonic() - started > timeout:
                    raise ProviderFailure("provider_response_limit")
                parts.append(chunk)
            if time.monotonic() - started > timeout:
                raise ProviderFailure("provider_response_limit")
        return json.loads(b"".join(parts))
    except HTTPError as error:
        # Reintentar solo rechazos explícitos de cuota; no timeouts de resultado incierto.
        raise ProviderFailure("provider_http_error", retryable=error.code == 429) from None
    except (URLError, TimeoutError, OSError):
        raise ProviderFailure("provider_unavailable") from None
    except (ValueError, UnicodeError) as error:
        if isinstance(error, ProviderFailure):
            raise
        raise ProviderFailure("provider_invalid_json") from None
