"""Identificador estable de servicio; no sustituye el HMAC de usuarios e IP."""

import hashlib


def service_key(identifier: str) -> str:
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()
