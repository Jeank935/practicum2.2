"""Configuración OIDC de operadores del SOC, independiente de los eventos ADFS."""

import json
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from practicum_soc.core.paths import PROJECT_ROOT


def origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


@dataclass(frozen=True)
class AuthSettings:
    mode: str
    public_url: str
    issuer: str
    internal_origin: str
    client_id: str
    client_secret: str
    policy: dict

    @classmethod
    def from_env(cls):
        policy = json.loads((PROJECT_ROOT / "config/auth.json").read_text())
        mode = os.environ.get("SOC_AUTH_MODE", "oidc")
        if mode not in {"oidc", "disabled"}:
            raise ValueError("Modo de autenticación inválido")
        return cls(
            mode,
            os.environ.get("SOC_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/"),
            os.environ.get("SOC_OIDC_ISSUER", "").rstrip("/"),
            os.environ.get("SOC_OIDC_INTERNAL_ORIGIN", "").rstrip("/"),
            os.environ.get("SOC_OIDC_CLIENT_ID", "soc-web"),
            os.environ.get("SOC_OIDC_CLIENT_SECRET", ""),
            policy,
        )

    @property
    def secure_cookie(self) -> bool:
        return self.public_url.startswith("https://")

    def validate(self):
        if not self.issuer or not self.client_secret:
            raise ValueError("OIDC requiere configuración")
        for url in (self.public_url, self.issuer, self.internal_origin or self.issuer):
            parsed = urlsplit(url)
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("URL OIDC inválida")
            if parsed.scheme != "https" and not (
                parsed.scheme == "http"
                and parsed.hostname in {"127.0.0.1", "localhost", "keycloak"}
            ):
                raise ValueError("HTTP solo está permitido para OIDC local")

    def transport_url(self, url: str) -> str:
        if origin(url) != origin(self.issuer):
            raise ValueError("El endpoint OIDC no pertenece al proveedor configurado")
        return (self.internal_origin or origin(self.issuer)) + urlsplit(url).path
