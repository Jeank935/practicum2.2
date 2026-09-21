"""Selección explícita del almacenamiento; nunca reutiliza la conexión institucional."""

from __future__ import annotations

import os
from pathlib import Path

from alert_store import AlertStore


def storage_backend() -> str:
    backend = os.environ.get("SOC_STORAGE_BACKEND", "sqlite")
    if backend not in {"sqlite", "postgres"}:
        raise ValueError("SOC_STORAGE_BACKEND debe ser sqlite o postgres")
    return backend


def open_store(path: Path) -> AlertStore:
    if storage_backend() == "sqlite":
        return AlertStore(path)
    from postgres_store import PostgresAlertStore

    return PostgresAlertStore()
