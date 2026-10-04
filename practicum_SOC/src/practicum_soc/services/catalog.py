"""Nombres legibles para los identificadores técnicos de servicios ADFS."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

SENSITIVITY_ORDER = {"normal": 0, "medium": 1, "high": 2}


def load_service_catalog(path: Path) -> dict:
    """Carga nombres y clasificación operativa de servicios."""
    if not path.exists():
        return {"labels": {}, "sensitivity": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "labels": {str(key): str(value) for key, value in payload.get("labels", {}).items()},
        "sensitivity": {
            str(key): dict(value) for key, value in payload.get("sensitivity", {}).items()
        },
    }


def load_service_labels(path: Path) -> dict[str, str]:
    """Carga etiquetas configuradas sin convertir el catálogo en una dependencia obligatoria."""
    return load_service_catalog(path)["labels"]


def _fallback_name(identifier: str) -> str:
    parsed = urlparse(identifier)
    candidate = parsed.path.strip("/").split("/")[-1] if parsed.scheme else identifier
    if not candidate and parsed.hostname:
        candidate = parsed.hostname.split(".")[0]
    candidate = re.sub(r"[_-]+", " ", candidate).strip()
    return candidate.title() if candidate else "Servicio ADFS sin identificar"


def add_service_display_names(metrics: dict, labels: dict[str, str]) -> None:
    """Añade un nombre de presentación manteniendo intacto el relying party original."""
    for service in metrics.get("services", []):
        identifier = str(service.get("relying_party", ""))
        service["display_name"] = labels.get(identifier, _fallback_name(identifier))


def add_service_monitoring_context(
    metrics: dict,
    catalog: dict,
    open_alerts: dict[str, dict] | None = None,
) -> None:
    """Clasifica servicios observados y adjunta sus alertas abiertas."""
    labels = catalog.get("labels", {})
    sensitivity = catalog.get("sensitivity", {})
    open_alerts = open_alerts or {}
    for service in metrics.get("services", []):
        identifier = str(service.get("relying_party", ""))
        classification = sensitivity.get(identifier, {})
        alert_context = open_alerts.get(identifier, {})
        service.update(
            {
                "display_name": labels.get(identifier, _fallback_name(identifier)),
                "sensitivity_level": classification.get("level", "normal"),
                "sensitivity_category": classification.get("category", "General"),
                "sensitivity_reason": classification.get("reason", ""),
                "open_alert_count": int(alert_context.get("count", 0)),
                "highest_alert_severity": alert_context.get("highest_severity", ""),
                "latest_alert_id": alert_context.get("latest_alert_id", ""),
            }
        )
    sensitive = [
        service
        for service in metrics.get("services", [])
        if service["sensitivity_level"] in {"medium", "high"}
    ]
    sensitive.sort(
        key=lambda item: (
            -int(item["open_alert_count"]),
            -SENSITIVITY_ORDER[item["sensitivity_level"]],
            -int(item["failure_count"] + item["lockout_count"]),
            item["display_name"],
        )
    )
    metrics["sensitive_services"] = sensitive
    metrics["sensitive_service_count"] = len(sensitive)
    metrics["sensitive_services_with_alerts"] = sum(
        service["open_alert_count"] > 0 for service in sensitive
    )


def annotate_sensitive_alerts(alerts: list[dict], catalog: dict) -> list[dict]:
    """Marca casos que ya contienen actividad de un servicio sensible."""
    labels = catalog.get("labels", {})
    sensitivity = catalog.get("sensitivity", {})
    for alert in alerts:
        contexts = []
        identifiers = filter(None, str(alert.get("relying_parties", "")).split(";"))
        for identifier in identifiers:
            classification = sensitivity.get(identifier, {})
            level = classification.get("level", "normal")
            if level not in {"medium", "high"}:
                continue
            contexts.append(
                {
                    "identifier": identifier,
                    "name": labels.get(identifier, _fallback_name(identifier)),
                    "level": level,
                    "category": classification.get("category", "General"),
                    "reason": classification.get("reason", ""),
                }
            )
        contexts.sort(key=lambda item: -SENSITIVITY_ORDER[item["level"]])
        alert["sensitive_services"] = contexts
        alert["has_sensitive_service"] = bool(contexts)
        alert["service_sensitivity_level"] = contexts[0]["level"] if contexts else "normal"
    return alerts
