import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]

from test_alert_store import sample_alert

import practicum_soc.main as web_app
from practicum_soc.repositories.alerts import AlertStore
from practicum_soc.services.dashboard import DashboardService


class WebAppTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(
            os.environ, {"SOC_AUTH_MODE": "disabled", "SOC_CURSOR_SECRET": "synthetic-web-test"}
        )
        environment.start()
        self.addCleanup(environment.stop)

    def test_dashboard_endpoints_and_status_change(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            analysis = root / "analysis"
            config = root / "detection.json"
            operational = root / "operational.json"
            state_db = analysis / "state" / "soc.db"
            (analysis / "baseline").mkdir(parents=True)
            (analysis / "report").mkdir(parents=True)
            (analysis / "normalization_stats.json").write_text(
                json.dumps({"input_rows": 1, "valid_rows": 1, "rejected_rows": 0}),
                encoding="utf-8",
            )
            (analysis / "baseline" / "baseline_summary.json").write_text(
                json.dumps({"training_period": {}, "evaluation_event_count": 1}),
                encoding="utf-8",
            )
            (analysis / "report" / "historical_report.md").write_text(
                "# Reporte sintético", encoding="utf-8"
            )
            config.write_text(
                json.dumps(
                    {
                        "test_rule": {
                            "enabled": True,
                            "rule_id": "AUTH_TEST",
                            "display_name": "Regla sintética",
                        },
                        "after_hours": {
                            "enabled": False,
                            "reason_disabled": "Prueba sintética",
                        },
                    }
                ),
                encoding="utf-8",
            )
            operational.write_text(
                json.dumps(
                    {
                        "services_dashboard": {
                            "default_window_days": 0,
                            "available_windows_days": [0, 1, 7, 30],
                            "top_services_limit": 10,
                            "rare_service_max_events": 10,
                        }
                    }
                ),
                encoding="utf-8",
            )
            service_identifier = "https://service.example.test"
            (root / "service_catalog.json").write_text(
                json.dumps(
                    {
                        "labels": {service_identifier: "Servicio de prueba"},
                        "sensitivity": {
                            service_identifier: {
                                "level": "high",
                                "category": "Pruebas",
                                "reason": "Servicio sintético controlado.",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with AlertStore(state_db) as store:
                alert = sample_alert()
                alert["relying_parties"] = service_identifier
                store.insert_alert(alert, source_name="csv_demo_mvp")
                event = {
                    "source_event_id": "evt_service",
                    "record_id": "1",
                    "event_time_utc": "2026-03-16T10:00:00+00:00",
                    "event_class": "success",
                    "event_type_id": "1200",
                    "event_name": "Application Token Success",
                    "user_key": "usr_test",
                    "client_ip_key": "ip_test",
                    "relying_party": service_identifier,
                    "event_count": 1,
                    "quality_flags": "",
                }
                store.insert_event(
                    event,
                    event["event_time_utc"],
                    "1",
                    True,
                    source_name="csv_demo_mvp",
                )

            service = DashboardService(
                state_db=state_db,
                analysis_dir=analysis,
                detection_config=config,
                operational_config=operational,
            )
            service.run_demo = lambda: {"created_alerts": 0, "persisted_alerts": 1}
            with patch.object(web_app.app.state, "dashboard_service", service):
                client = TestClient(web_app.app)
                dashboard = client.get("/")
                self.assertEqual(dashboard.status_code, 200)
                self.assertIn("Pendientes de revisión", dashboard.text)
                self.assertNotIn("CSV histórico", dashboard.text)
                version = client.get("/api/dashboard-version")
                self.assertEqual(version.status_code, 200)
                self.assertIn("revision", version.json())
                alerts = client.get("/alerts")
                self.assertEqual(alerts.status_code, 200)
                self.assertIn("Servicio sensible", alerts.text)
                self.assertIn('select name="rule_id"', alerts.text)
                self.assertIn("Regla sintética · AUTH_TEST", alerts.text)
                filtered_alerts = client.get("/alerts?rule_id=AUTH_TEST")
                self.assertIn('value="AUTH_TEST" selected', filtered_alerts.text)
                services = client.get("/services")
                self.assertEqual(services.status_code, 200)
                self.assertIn("Servicios ADFS", services.text)
                self.assertIn("Servicio de prueba", services.text)
                self.assertIn("Identificador técnico: https://service.example.test", services.text)
                self.assertIn("Servicios sensibles bajo vigilancia", services.text)
                self.assertIn("1 alerta abierta", services.text)
                self.assertEqual(client.get("/api/services-version").status_code, 200)
                detail = client.get("/alerts/alt_1")
                self.assertEqual(detail.status_code, 200)
                self.assertIn("Sensibilidad alta", detail.text)
                updated = client.patch(
                    "/alerts/alt_1/status",
                    json={"status": "investigating", "note": "Revisión sintética"},
                )
                self.assertEqual(updated.status_code, 200)
                self.assertEqual(updated.json()["investigation_status"], "investigating")
                self.assertEqual(client.get("/health").status_code, 200)
                self.assertEqual(client.post("/demo/run").status_code, 200)
                self.assertEqual(client.get("/reports/latest").status_code, 200)


if __name__ == "__main__":
    unittest.main()
