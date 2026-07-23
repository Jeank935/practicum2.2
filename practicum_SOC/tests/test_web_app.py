import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from test_alert_store import sample_alert

import web_app
from alert_store import AlertStore
from dashboard_service import DashboardService


class WebAppTests(unittest.TestCase):
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
                        "after_hours": {
                            "enabled": False,
                            "reason_disabled": "Prueba sintética",
                        }
                    }
                ),
                encoding="utf-8",
            )
            operational.write_text("{}", encoding="utf-8")
            with AlertStore(state_db) as store:
                store.insert_alert(sample_alert(), source_name="csv_demo_mvp")

            service = DashboardService(
                state_db=state_db,
                analysis_dir=analysis,
                detection_config=config,
                operational_config=operational,
            )
            service.run_demo = lambda: {"created_alerts": 0, "persisted_alerts": 1}
            with patch.object(web_app, "service", service):
                client = TestClient(web_app.app)
                self.assertEqual(client.get("/").status_code, 200)
                self.assertEqual(client.get("/alerts").status_code, 200)
                self.assertEqual(client.get("/alerts/alt_1").status_code, 200)
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
