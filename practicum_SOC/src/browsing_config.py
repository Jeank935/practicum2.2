"""Límites de lectura inmutables; se cargan al arrancar el proceso."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BrowsingSettings:
    default_page_size: int
    max_page_size: int
    top_services: int
    migration_batch_size: int
    cursor_max_length: int
    timezone: str
    response_target_ms: int


SETTINGS = BrowsingSettings(
    **json.loads((Path(__file__).resolve().parents[1] / "config/browsing.json").read_text())
)
