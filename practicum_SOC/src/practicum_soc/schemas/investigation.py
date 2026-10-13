"""Contrato del texto interpretativo, separado de hechos calculados por Python."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(min_length=1, max_length=2000)]
ShortText = Annotated[str, Field(min_length=1, max_length=500)]


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    force_new: bool = False


class AIEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: ShortText
    references: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        min_length=1, max_length=10
    )


class AIExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: Text
    evidence: list[AIEvidence] = Field(max_length=12)
    interpretation: Text
    legitimate_explanations: list[ShortText] = Field(max_length=8)
    missing_information: list[ShortText] = Field(max_length=8)
    recommendations: list[ShortText] = Field(min_length=1, max_length=8)


class ReputationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["available", "unavailable", "not_applicable", "disabled"]
    ip_address: str | None = None
    provider: str | None = None
    checked_at_utc: str | None = None
    abuse_confidence_score: int | None = Field(default=None, ge=0, le=100)
    total_reports: int | None = Field(default=None, ge=0)
    reason: str | None = None


class InvestigationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alert_id: str
    analysis_id: str
    real_ip: str | None
    real_ip_unavailable_reason: str | None
    real_ips: list[str]
    context: dict
    reputation: list[ReputationResult]
    explanation: AIExplanation
    usage: dict
    confirmed_incident: Literal[False] = False
    disclaimer: str = (
        "Interpretación asistida; requiere validación del analista y no confirma un ataque."
    )


class InvestigationJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_id: str
    alert_id: str
    status: Literal["pending", "in_progress", "completed", "failed"]
    requested_by: str
    created_at_utc: str
    started_at_utc: str | None
    finished_at_utc: str | None
    real_ip: str | None
    real_ip_unavailable_reason: str | None
    result: InvestigationResult | None
    error_code: str | None
    reused: bool = False
