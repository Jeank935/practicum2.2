"""Política de transporte y límites; producción requiere configuración explícita."""

import ipaddress
import os
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from practicum_soc.core.auth_config import AuthSettings
from practicum_soc.core.paths import PROJECT_ROOT


class SecurityPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    maximum_request_bytes: int = Field(ge=1024, le=8388608)
    maximum_query_bytes: int = Field(ge=1024, le=32768)
    request_body_timeout_seconds: int = Field(ge=1, le=60)
    content_security_policy: str = Field(min_length=20, max_length=2048)
    hsts_max_age_seconds: int = Field(ge=0, le=63072000)

    @classmethod
    def load(cls):
        return cls.model_validate_json(
            (PROJECT_ROOT / "config/security.json").read_text(encoding="utf-8")
        )


def production_mode() -> bool:
    environment = os.environ.get("SOC_ENV", "local")
    if environment not in {"local", "production"}:
        raise ValueError("SOC_ENV debe ser local o production")
    return environment == "production"


def require_https(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Producción requiere URLs HTTPS válidas sin credenciales")


def validate_production(settings: AuthSettings) -> list[str]:
    """Falla antes de abrir la base; no imprime valores de configuración."""
    if settings.mode != "oidc":
        raise ValueError("Producción requiere autenticación OIDC")
    settings.validate()
    for url in (settings.public_url, settings.issuer, settings.internal_origin or settings.issuer):
        require_https(url)
    public = urlsplit(settings.public_url)
    if public.path:
        raise ValueError("SOC_PUBLIC_URL debe indicar el origen, sin ruta")
    if public.hostname in {"localhost", "127.0.0.1", "::1", "testserver"}:
        raise ValueError("Producción requiere un dominio de despliegue")
    if os.environ.get("SOC_STORAGE_BACKEND") != "postgres":
        raise ValueError("Producción requiere el PostgreSQL propio del SOC")
    for name in ("SOC_CURSOR_SECRET", "SOC_OIDC_CLIENT_SECRET"):
        if len(os.environ.get(name, "")) < 32:
            raise ValueError(f"Producción requiere configurar {name} con al menos 32 caracteres")
    host = os.environ.get("SOC_STORAGE_HOST", "")
    local_database = host in {"postgres", "localhost", "127.0.0.1", "::1"}
    if not host or (not local_database and os.environ.get("SOC_STORAGE_SSLMODE") != "verify-full"):
        raise ValueError("PostgreSQL fuera de la red Docker local requiere TLS verify-full")
    hosts = [
        item.strip() for item in os.environ.get("SOC_ALLOWED_HOSTS", public.hostname).split(",")
    ]
    for host in hosts:
        if not host or any(character in host for character in "* /\\:@"):
            raise ValueError("SOC_ALLOWED_HOSTS solo admite nombres de host exactos")
        # Un IP literal no sustituye la confirmación del dominio institucional.
        try:
            ipaddress.ip_address(host)
        except ValueError:
            continue
        raise ValueError("SOC_ALLOWED_HOSTS debe usar dominios, no IP literales")
    if public.hostname not in hosts:
        raise ValueError("SOC_ALLOWED_HOSTS debe incluir el dominio público")
    return hosts
