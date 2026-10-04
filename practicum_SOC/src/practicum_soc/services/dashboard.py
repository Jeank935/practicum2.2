"""Consultas preparadas para la bandeja SOC, sin lógica HTTP."""

from __future__ import annotations

import json
from pathlib import Path

from practicum_soc.analytics.operational import pilot_metrics, technical_metrics
from practicum_soc.analytics.reporting import generate_report
from practicum_soc.core.cache import BoundedTTLCache, CacheSettings
from practicum_soc.core.config import load_json
from practicum_soc.integrations.notifications import SocInboxProvider
from practicum_soc.repositories.alerts import ALERT_STATUSES, AlertStore
from practicum_soc.repositories.auth import AuthStore
from practicum_soc.repositories.factory import open_store
from practicum_soc.repositories.rules import RuleConfigStore
from practicum_soc.services.catalog import (
    add_service_monitoring_context,
    annotate_sensitive_alerts,
    load_service_catalog,
)
from practicum_soc.services.demo import DEMO_SOURCE_NAME, run_demo

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
        cache_settings = CacheSettings.from_file(
            operational_config.with_name("backend_performance.json")
        )
        self.service_pages = BoundedTTLCache(cache_settings)
        self._catalog_cache = BoundedTTLCache(
            cache_settings.model_copy(update={"maximum_entries": 2})
        )

    def clear_caches(self) -> None:
        self.service_pages.clear()
        self._catalog_cache.clear()

    def catalog_revision(self) -> str:
        path = self.operational_config.with_name("service_catalog.json")
        stamp = path.stat() if path.is_file() else None
        return f"{path}:{stamp.st_mtime_ns}:{stamp.st_size}" if stamp else str(path)

    def _service_catalog(self) -> dict:
        revision = self.catalog_revision()
        cached = self._catalog_cache.get(revision)
        if cached is not None:
            return cached
        catalog = load_service_catalog(self.operational_config.with_name("service_catalog.json"))
        self._catalog_cache.put(revision, catalog)
        return catalog

    @staticmethod
    def _selected_source(store: AlertStore) -> tuple[dict, str]:
        # Las vistas operativas no necesitan contar todos los eventos históricos.
        source_name = store.latest_source()
        selected_source = source_name if source_name != "none" else DEMO_SOURCE_NAME
        return {"active_source": source_name}, selected_source

    def overview(self) -> dict:
        with open_store(self.state_db) as store:
            health, selected_source = self._selected_source(store)
            operational = store.operational_alert_summary(selected_source)
            operational["revision"] = store.dashboard_revision(selected_source)
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
            active_source = store.latest_source()
            selected_source = active_source if active_source != "none" else DEMO_SOURCE_NAME
            revision = store.dashboard_revision(selected_source)
            updated_at = store.last_alert_updated(selected_source)
        return {
            "source": selected_source,
            "revision": revision,
            "last_updated_at_utc": updated_at,
        }

    def dashboard_snapshot(self) -> dict:
        """Carga una sola vez resumen y casos recientes para refresco parcial."""
        overview = self.overview()
        return {
            "source_label": overview["source_label"],
            "operational": overview["operational"],
            "recent_alerts": overview["recent_alerts"],
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
        config = self._active_detection_config()
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
        config = self._active_detection_config()
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

    def _active_detection_config(self) -> dict:
        initial = load_json(self.detection_config)
        if "risk_scoring" not in initial:
            return initial  # Catálogos sintéticos antiguos usados en pruebas de la vista.
        with open_store(self.state_db) as store:
            return RuleConfigStore(store, initial).current()["config"]

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

    def operational_metrics(self) -> dict:
        with open_store(self.state_db) as store:
            _, source = self._selected_source(store)
            return {
                "technical": technical_metrics(store, source),
                "pilot": pilot_metrics(store, source),
            }

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
