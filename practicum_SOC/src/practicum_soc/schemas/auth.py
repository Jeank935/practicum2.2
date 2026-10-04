"""Entradas de administración de operadores, no identidades de los eventos."""

from typing import Literal

from pydantic import BaseModel, StrictBool


class UserAccessUpdate(BaseModel):
    role: Literal["administrator", "analyst"]
    enabled: StrictBool
