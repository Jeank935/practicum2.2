"""Consultas preparadas para la bandeja SOC, sin lógica HTTP."""

from __future__ import annotations

import json
from pathlib import Path

from alert_store import ALERT_STATUSES, AlertStore
from demo_service import DEMO_SOURCE_NAME, run_demo
from generate_report import generate_report
from notifications import SocInboxProvider
from runtime_config import load_json

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

    def overview(self) -> dict:
        with AlertStore(self.state_db) as store:
            health = store.health_summary()
            source_name = health["active_source"]
            selected_source = source_name if source_name != "none" else DEMO_SOURCE_NAME
            operational = store.operational_alert_summary(selected_source)
            recent = store.list_alerts(8, source_name=selected_source)
        return {
            "health": health,
            "source_name": selected_source,
            "source_label": SOURCE_LABELS.get(selected_source, selected_source),
            "operational": operational,
            "recent_alerts": recent,
        }

    def dashboard_version(self) -> dict:
        with AlertStore(self.state_db) as store:
            health = store.health_summary()
            source_name = health["active_source"]
            selected_source = source_name if source_name != "none" else DEMO_SOURCE_NAME
            summary = store.operational_alert_summary(selected_source)
        return {
            "source": selected_source,
            "revision": summary["revision"],
            "last_updated_at_utc": summary["last_updated_at_utc"],
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

    def list_alerts(
        self,
        *,
        severity: str | None = None,
        status: str | None = None,
        rule_id: str | None = None,
    ) -> list[dict]:
        with AlertStore(self.state_db) as store:
            active_source = store.health_summary()["active_source"]
            selected_source = active_source if active_source != "none" else DEMO_SOURCE_NAME
            return store.list_alerts(
                500,
                source_name=selected_source,
                severity=severity,
                status=status,
                rule_id=rule_id,
            )

    def alert_detail(self, alert_id: str) -> dict | None:
        with AlertStore(self.state_db) as store:
            alert = store.get_alert(alert_id)
            if alert is None:
                return None
            alert["risk_factors"] = json.loads(alert["risk_factors_json"])
            alert["history"] = store.alert_history(alert_id)
            alert["deliveries"] = store.alert_deliveries(alert_id)
            return alert

    def update_status(self, alert_id: str, status: str, note: str = "") -> dict:
        if status not in ALERT_STATUSES:
            raise ValueError("Estado de alerta no permitido")
        with AlertStore(self.state_db) as store:
            store.update_alert_status(alert_id, status, note)
            updated = store.get_alert(alert_id)
        if updated is None:
            raise KeyError(alert_id)
        return updated

    def health(self) -> dict:
        with AlertStore(self.state_db) as store:
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
