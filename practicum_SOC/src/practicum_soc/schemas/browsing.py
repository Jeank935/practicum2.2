"""Contratos públicos de lectura y validación compartidos por HTML y API."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from practicum_soc.core.browsing_config import SETTINGS

Severity = Literal["critical", "high", "medium", "low"]
CaseStatus = Literal["new", "notified", "investigating", "resolved", "false_positive"]


class PageQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_size: int = Field(SETTINGS.default_page_size, ge=1, le=SETTINGS.max_page_size)
    cursor: str | None = Field(None, max_length=SETTINGS.cursor_max_length)
    date_from: date | None = None
    date_to: date | None = None
    service: str | None = Field(None, max_length=2048)

    @field_validator("*", mode="before")
    @classmethod
    def blank_is_missing(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def valid_range(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("La fecha inicial no puede ser posterior a la final")
        return self


class AlertQuery(PageQuery):
    source: Literal["csv_demo_mvp", "csv_demo", "postgresql_live"] | None = None
    service_key: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")
    time_from: datetime | None = None
    time_to: datetime | None = None
    severity: Severity | None = None
    status: CaseStatus | None = None
    rule_id: str | None = Field(None, max_length=128)
    sort: Literal["risk", "newest", "oldest"] = "risk"

    @model_validator(mode="after")
    def valid_instants(self):
        if bool(self.time_from) != bool(self.time_to):
            raise ValueError("Se requieren inicio y fin del intervalo")
        if self.time_from and (
            self.time_from.tzinfo is None
            or self.time_to.tzinfo is None
            or self.time_to <= self.time_from
        ):
            raise ValueError("Use un intervalo positivo con zona horaria")
        return self


class ServiceQuery(PageQuery):
    page_size: int = Field(SETTINGS.top_services, ge=1, le=SETTINGS.max_page_size)
    window_days: Literal[0, 1, 7, 30] = 0
    sort: Literal["volume", "failures", "recent", "service"] = "volume"
    sensitive: bool = False

    @field_validator("window_days", mode="before")
    @classmethod
    def parse_window(cls, value):
        # Los parámetros de URL llegan como texto, incluso para Literal[int].
        if isinstance(value, str) and value in {"0", "1", "7", "30"}:
            return int(value)
        return value


class PageInfo(BaseModel):
    page_size: int
    page: int
    has_next: bool
    has_previous: bool
    next_cursor: str | None = None
    previous_cursor: str | None = None


class AlertItem(BaseModel):
    alert_id: str
    rule_id: str
    rule_name: str
    severity: Severity
    risk_score: int
    user_key: str | None
    client_ip_key: str | None
    event_count: int
    investigation_status: CaseStatus
    first_seen_local: str
    occurred_at_utc: str
    delivery_channel: str
    delivery_status: str


class AlertPage(BaseModel):
    data: list[AlertItem]
    page: PageInfo
    source: str


class ServiceItem(BaseModel):
    relying_party: str
    display_name: str
    total_events: int
    success_count: int
    failure_count: int
    lockout_count: int
    distinct_users: int
    distinct_client_ips: int
    first_seen_utc: str
    last_seen_utc: str
    adverse_rate: float
    share_percent: float
    sensitivity_level: str
    open_alert_count: int


class ServicePage(BaseModel):
    data: list[ServiceItem]
    page: PageInfo
    source: str


class ErrorBody(BaseModel):
    code: str
    message: str
    fields: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorBody
