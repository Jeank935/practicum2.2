"""Solicitudes para editar parámetros, simular, publicar y restaurar."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Edit(BaseModel):
    expected_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    changes: dict[str, object]


class PreviewRequest(BaseModel):
    source: Literal["csv_demo_mvp", "csv_demo", "postgresql_live"]
    from_utc: datetime
    to_utc: datetime


class Justification(BaseModel):
    justification: str = Field(min_length=10, max_length=500)
