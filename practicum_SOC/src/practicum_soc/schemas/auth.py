"""Entradas de administración de operadores, no identidades de los eventos."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool


class UserAccessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["administrator", "analyst"]
    enabled: StrictBool
