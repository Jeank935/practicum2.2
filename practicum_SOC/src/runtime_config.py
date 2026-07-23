"""Lectura segura de configuración local y secretos de ejecución."""

from __future__ import annotations

import json
import os
from pathlib import Path


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_pseudonym_secret(path: Path | None) -> bytes:
    value = ""
    if path and path.is_file():
        value = path.read_text(encoding="utf-8").strip()
    if not value:
        value = os.environ.get("SOC_PSEUDONYM_KEY", "").strip()
    if not value:
        raise RuntimeError("Falta la clave HMAC; use --pseudonym-key-file o SOC_PSEUDONYM_KEY")
    return value.encode("utf-8")
