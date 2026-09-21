"""Consultas preparadas para la bandeja SOC, sin lógica HTTP."""

from __future__ import annotations

import json
from pathlib import Path

from alert_store import ALERT_STATUSES, AlertStore
from auth_store import AuthStore
from demo_service import DEMO_SOURCE_NAME, run_demo
from generate_report import generate_report
from notifications import SocInboxProvider
from runtime_config import load_json
from service_catalog import (
    add_service_monitoring_context,
    annotate_sensitive_alerts,
    load_service_catalog,
)
from store_factory import open_store

SOURCE_LABELS = {
    DEMO_SOURCE_NAME: "CSV demo",
    "csv_demo": "CSV demo incremental",
    "postgresql_live": "PostgreSQL live",
    "none": "Sin ejecución",
}


class DashboardService:
    def __init__(
        self,
        *,
        state_db: Path,
        analysis_dir: Path,
        detection_config: Path,
        operational_config: Path,
    ):
        self.state_db = state_db
        self.analysis_dir = analysis_dir
        self.detection_config = detection_config
        self.operational_config = operational_config

    def _service_catalog(self) -> dict:
        return load_service_catalog(self.operational_config.with_name("service_catalog.json"))

    @staticmethod
    def _selected_source(store: AlertStore) -> tuple[dict, str]:
        health = store.health_summary()
        source_name = health["active_source"]
        selected_source = source_name if source_name != "none" else DEMO_SOURCE_NAME
        return health, selected_source

    def overview(self) -> dict:
        with open_store(self.state_db) as store:
            health, selected_source = self._selected_source(store)
            operational = store.operational_alert_summary(selected_source)
            recent = store.list_alerts(8, source_name=selected_source)
        annotate_sensitive_alerts(recent, self._service_catalog())
        return {
            "health": health,
            "source_name": selected_source,
            "source_label": SOURCE_LABELS.get(selected_source, selected_source),
            "operational": operational,
            "recent_alerts": recent,
        }

    def dashboard_version(self) -> dict:
        with open_store(self.state_db) as store:
            _, selected_source = self._selected_source(store)
            summary = store.operational_alert_summary(selected_source)
        return {
            "source": selected_source,
            "revision": summary["revision"],
            "last_updated_at_utc": summary["last_updated_at_utc"],
        }

    def services_overview(self, window_days: int | None = None) -> dict:
        settings = load_json(self.operational_config)["services_dashboard"]
        available_windows = [int(value) for value in settings["available_windows_days"]]
        selected_window = (
            int(window_days)
            if window_days is not None and int(window_days) in available_windows
            else int(settings["default_window_days"])
        )
        with open_store(self.state_db) as store:
            health, selected_source = self._selected_source(store)
            metrics = store.service_metrics(
                selected_source,
                window_days=selected_window,
                top_limit=int(settings["top_services_limit"]),
                rare_max_events=int(settings["rare_service_max_events"]),
            )
            open_alerts = store.open_alert_counts_by_service(selected_source)
        add_service_monitoring_context(metrics, self._service_catalog(), open_alerts)
        return {
            "health": health,
            "source_name": selected_source,
            "source_label": SOURCE_LABELS.get(selected_source, selected_source),
            "available_windows": available_windows,
            "metrics": metrics,
        }

    def services_version(self, window_days: int | None = None) -> dict:
        overview = self.services_overview(window_days)
        return {
            "source": overview["source_name"],
            "revision": overview["metrics"]["revision"],
        }

    def disabled_rules(self) -> list[dict[str, str]]:
        config = load_json(self.detection_config)
        return [
            {
                "key": key,
                "reason": str(value.get("reason_disabled", "Sin motivo documentado")),
            }
            for key, value in config.items()
            if isinstance(value, dict) and value.get("enabled") is False
        ]

    def enabled_rules(self) -> list[dict[str, str]]:
        """Expone el catálogo configurado para filtros y otras vistas operativas."""
        config = load_json(self.detection_config)
        return [
            {
                "rule_id": str(value["rule_id"]),
                "display_name": str(value["display_name"]),
            }
            for value in config.values()
            if isinstance(value, dict)
            and value.get("enabled") is True
            and value.get("rule_id")
            and value.get("display_name")
        ]

    def list_alerts(
        self,
        *,
        severity: str | None = None,
        status: str | None = None,
        rule_id: str | None = None,
    ) -> list[dict]:
        with open_store(self.state_db) as store:
            _, selected_source = self._selected_source(store)
            alerts = store.list_alerts(
                500,
                source_name=selected_source,
                severity=severity,
                status=status,
                rule_id=rule_id,
            )
        return annotate_sensitive_alerts(alerts, self._service_catalog())

    def alert_detail(self, alert_id: str, *, actor: dict | None = None) -> dict | None:
        with open_store(self.state_db) as store:
            alert = store.get_alert(alert_id)
            if alert is None:
                return None
            alert["risk_factors"] = json.loads(alert["risk_factors_json"])
            alert["history"] = store.alert_history(alert_id)
            alert["deliveries"] = store.alert_deliveries(alert_id)
            if actor:
                with store.connection:
                    AuthStore(store, {}).audit(actor, "case_viewed", alert_id)
            return annotate_sensitive_alerts([alert], self._service_catalog())[0]

    def update_status(
        self,
        alert_id: str,
        status: str,
        note: str = "",
        *,
        actor_id: str = "system",
        actor_name: str = "Motor SOC",
    ) -> dict:
        if status not in ALERT_STATUSES:
            raise ValueError("Estado de alerta no permitido")
        with open_store(self.state_db) as store:
            store.update_alert_status(
                alert_id, status, note, actor_id=actor_id, actor_name=actor_name
            )
            updated = store.get_alert(alert_id)
        if updated is None:
            raise KeyError(alert_id)
        return updated

    def health(self) -> dict:
        with open_store(self.state_db) as store:
            health = store.health_summary()
        health["source_label"] = SOURCE_LABELS.get(health["active_source"], health["active_source"])
        return health

    def run_demo(self) -> dict:
        result = run_demo(
            analysis_dir=self.analysis_dir,
            state_db=self.state_db,
            detection_config_path=self.detection_config,
            operational_config_path=self.operational_config,
            provider=SocInboxProvider(),
        )
        report = generate_report(
            self.analysis_dir,
            self.analysis_dir / "report",
            detection_config_path=self.detection_config,
            state_db=self.state_db,
            source_name=DEMO_SOURCE_NAME,
        )
        return {**result, "report": str(report)}

    def latest_report(self) -> Path:
        return self.analysis_dir / "report" / "historical_report.md"
