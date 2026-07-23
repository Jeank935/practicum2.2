"""Proveedores desacoplados de entrega de alertas."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from alert_store import AlertStore


@dataclass(frozen=True)
class DeliveryResult:
    outcome: str
    error_code: str = ""


class NotificationProvider(Protocol):
    """Contrato para incorporar futuros canales sin cambiar el detector."""

    channel_name: str

    def send(self, alert: dict) -> DeliveryResult: ...


def safe_notification_payload(alert: dict) -> dict:
    return {
        "alert_id": alert["alert_id"],
        "severity": alert["severity"],
        "risk_score": alert.get("risk_score", 0),
        "first_seen_local": alert["first_seen_local"],
        "last_seen_local": alert["last_seen_local"],
        "anomaly_type": alert["rule_name"],
        "rule_id": alert["rule_id"],
        "user_key": alert.get("user_key", ""),
        "client_ip_key": alert.get("client_ip_key", ""),
        "event_count": alert.get("event_count", 0),
        "evidence": alert.get("description", ""),
        "recommendation": alert.get("recommendation", ""),
        "notice": "Señal automática que requiere revisión humana; no confirma un ataque.",
    }


class SocInboxProvider:
    """Canal interno del MVP; la persistencia SQLite actúa como bandeja."""

    channel_name = "soc_inbox"

    def send(self, alert: dict) -> DeliveryResult:
        safe_notification_payload(alert)
        return DeliveryResult("sent")


class DryRunProvider:
    channel_name = "dry_run"

    def send(self, alert: dict) -> DeliveryResult:
        print(
            json.dumps(
                {"notification_dry_run": safe_notification_payload(alert)},
                ensure_ascii=False,
            )
        )
        return DeliveryResult("dry_run")


def build_notification_provider(mode: str) -> NotificationProvider:
    providers: dict[str, NotificationProvider] = {
        "soc_inbox": SocInboxProvider(),
        "dry_run": DryRunProvider(),
    }
    try:
        return providers[mode]
    except KeyError as error:
        raise ValueError(f"Canal de notificación no soportado: {mode}") from error


def deliver_once(
    store: AlertStore,
    provider: NotificationProvider,
    alert: dict,
    max_attempts: int,
) -> DeliveryResult:
    if store.delivery_succeeded(alert["alert_id"], provider.channel_name):
        store.record_suppression(
            "notification_already_delivered",
            rule_id=alert["rule_id"],
            entity_key=AlertStore._entity_key(alert),
            details={"channel": provider.channel_name},
        )
        return DeliveryResult("skipped", "already_delivered")
    if store.delivery_attempt_count(alert["alert_id"], provider.channel_name) >= max_attempts:
        store.record_suppression(
            "notification_retry_limit",
            rule_id=alert["rule_id"],
            entity_key=AlertStore._entity_key(alert),
            details={"channel": provider.channel_name, "max_attempts": max_attempts},
        )
        return DeliveryResult("skipped", "retry_limit")

    result = provider.send(alert)
    store.record_delivery(
        alert["alert_id"], provider.channel_name, result.outcome, result.error_code
    )
    if result.outcome == "sent":
        store.update_alert_status(
            alert["alert_id"],
            "notified",
            f"Entrega registrada por {provider.channel_name}",
        )
    return result
