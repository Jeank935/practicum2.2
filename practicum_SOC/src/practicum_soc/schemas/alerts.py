"""Validación de cambios de estado; contrato HTTP existente."""

from typing import Literal

from pydantic import BaseModel, Field


class StatusUpdate(BaseModel):
    status: Literal["new", "notified", "investigating", "resolved", "false_positive"]
    note: str = Field(default="", max_length=500)
