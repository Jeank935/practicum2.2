import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from practicum_soc.services.catalog import (  # noqa: E402
    add_service_display_names,
    add_service_monitoring_context,
    annotate_sensitive_alerts,
    load_service_labels,
)


class ServiceCatalogTests(unittest.TestCase):
    def test_configured_label_preserves_original_identifier(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            catalog = Path(temp_directory) / "service_catalog.json"
            catalog.write_text(
                json.dumps({"labels": {"urn:test": "Servicio de prueba"}}),
                encoding="utf-8",
            )
            metrics = {"services": [{"relying_party": "urn:test"}]}

            add_service_display_names(metrics, load_service_labels(catalog))

            self.assertEqual(metrics["services"][0]["display_name"], "Servicio de prueba")
            self.assertEqual(metrics["services"][0]["relying_party"], "urn:test")

    def test_unknown_url_uses_readable_path_name(self):
        metrics = {"services": [{"relying_party": "https://example.test/new_service"}]}

        add_service_display_names(metrics, {})

        self.assertEqual(metrics["services"][0]["display_name"], "New Service")

    def test_sensitive_service_is_correlated_with_open_alerts(self):
        identifier = "https://example.test/admin"
        metrics = {
            "services": [
                {
                    "relying_party": identifier,
                    "failure_count": 6,
                    "lockout_count": 0,
                }
            ]
        }
        catalog = {
            "labels": {identifier: "Administración de prueba"},
            "sensitivity": {
                identifier: {"level": "high", "category": "Pruebas", "reason": "Controlado"}
            },
        }

        add_service_monitoring_context(
            metrics,
            catalog,
            {identifier: {"count": 2, "highest_severity": "high", "latest_alert_id": "alt_2"}},
        )
        alerts = annotate_sensitive_alerts([{"relying_parties": identifier}], catalog)

        self.assertEqual(metrics["sensitive_service_count"], 1)
        self.assertEqual(metrics["sensitive_services_with_alerts"], 1)
        self.assertEqual(metrics["sensitive_services"][0]["open_alert_count"], 2)
        self.assertTrue(alerts[0]["has_sensitive_service"])
        self.assertEqual(alerts[0]["service_sensitivity_level"], "high")


if __name__ == "__main__":
    unittest.main()
