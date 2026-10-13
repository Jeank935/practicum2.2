"""Cifrado de material de investigación; no incorpora originales al CSV normalizado."""

import ipaddress
import json
import os

from cryptography.fernet import Fernet, InvalidToken

from practicum_soc.core.investigation_config import InvestigationUnavailable


def is_public_ip(address: str) -> bool:
    parsed = ipaddress.ip_address(address)
    return parsed.is_global and not (
        parsed.is_multicast or parsed.is_reserved or getattr(parsed, "is_site_local", False)
    )


def investigation_cipher() -> Fernet:
    try:
        return Fernet(os.environ.get("SOC_INVESTIGATION_IP_KEY", "").encode("ascii"))
    except (ValueError, UnicodeError) as error:
        raise InvestigationUnavailable(
            "Configure SOC_INVESTIGATION_IP_KEY con una clave Fernet válida"
        ) from error


def encrypt_payload(value: dict) -> str:
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return investigation_cipher().encrypt(body).decode("ascii")


def decrypt_payload(value: str) -> dict:
    try:
        return json.loads(investigation_cipher().decrypt(value.encode("ascii")))
    except (InvalidToken, ValueError, UnicodeError) as error:
        raise InvestigationUnavailable(
            "No se puede leer el material con la clave configurada"
        ) from error


def capture_original_ip(values: dict, normalized: dict, secret: bytes) -> str | None:
    if os.environ.get("SOC_INVESTIGATION_CAPTURE_IP", "false").casefold() != "true":
        return None
    from practicum_soc.soc.normalization import pseudonymize

    try:
        address = ipaddress.ip_address(str(values.get("custom_ip_address", "")).strip())
    except ValueError:
        return None
    if pseudonymize(address.compressed, secret, "ip") != normalized.get("client_ip_key"):
        return None
    return address.compressed
