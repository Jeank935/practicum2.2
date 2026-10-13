"""Límites de investigación; secretos solo en variables de entorno."""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from practicum_soc.core.paths import PROJECT_ROOT


class InvestigationUnavailable(ValueError):
    """Error público de configuración; nunca contiene un secreto."""


class InvestigationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: Literal["openai"] = "openai"
    model: str = Field(default="", max_length=128, pattern=r"^[a-zA-Z0-9._:-]*$")
    window_before_minutes: int = Field(ge=1, le=1440)
    window_after_minutes: int = Field(ge=0, le=240)
    maximum_events: int = Field(ge=1, le=500)
    maximum_ip_entities: int = Field(ge=1, le=10)
    maximum_context_bytes: int = Field(ge=8192, le=100000)
    maximum_response_bytes: int = Field(ge=8192, le=1048576)
    maximum_output_tokens: int = Field(ge=256, le=8192)
    ai_timeout_seconds: int = Field(ge=1, le=60)
    maximum_retries: int = Field(ge=0, le=2)
    reputation_timeout_seconds: int = Field(ge=1, le=15)
    reuse_minutes: int = Field(ge=1, le=1440)
    maximum_concurrent_jobs: int = Field(ge=1, le=4)
    maximum_pending_jobs: int = Field(ge=1, le=200)
    lease_seconds: int = Field(ge=60, le=600)
    poll_seconds: int = Field(ge=1, le=30)
    send_real_ip_to_ai: bool
    input_usd_per_million_tokens: float | None = Field(default=None, ge=0, le=10000)
    output_usd_per_million_tokens: float | None = Field(default=None, ge=0, le=10000)

    @model_validator(mode="after")
    def adequate_lease(self):
        minimum = self.ai_timeout_seconds * (self.maximum_retries + 1) * 2
        minimum += self.reputation_timeout_seconds * 2 * self.maximum_ip_entities + 30
        if self.lease_seconds < minimum:
            raise ValueError("El lease debe cubrir llamadas, reintentos y margen de finalización")
        return self

    @classmethod
    def load(cls, path: Path | None = None):
        try:
            settings = cls.model_validate_json(
                (path or PROJECT_ROOT / "config/investigation.json").read_text(encoding="utf-8")
            )
            return settings.model_copy(
                update={
                    "model": os.environ.get("SOC_AI_MODEL", ""),
                    "provider": os.environ.get("SOC_AI_PROVIDER", settings.provider),
                }
            ).validated()
        except (ValueError, OSError):
            raise InvestigationUnavailable(
                "Configuración de investigación inválida; revise config/investigation.json, "
                "SOC_AI_MODEL y SOC_AI_PROVIDER"
            ) from None

    def validated(self):
        return type(self).model_validate(self.model_dump())

    def require_available(self):
        if os.environ.get("SOC_AI_ENABLED", "false").casefold() != "true":
            raise InvestigationUnavailable("Configure SOC_AI_ENABLED=true para habilitar análisis")
        if not self.model or not os.environ.get("OPENAI_API_KEY", "").strip():
            raise InvestigationUnavailable("Falta SOC_AI_MODEL u OPENAI_API_KEY")
        from practicum_soc.core.private_ip import investigation_cipher

        investigation_cipher()
