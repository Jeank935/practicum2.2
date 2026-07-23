import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from test_alert_store import sample_alert

from alert_store import AlertStore
from generate_report import generate_report


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class GenerateReportTests(unittest.TestCase):
    def test_historical_report_includes_required_counts_and_false_positives(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            analysis = root / "analysis"
            output = analysis / "report"
            config = root / "config" / "detection_rules.json"
            state_db = analysis / "state" / "soc.db"
            write_json(
                analysis / "normalization_stats.json",
                {
                    "input_rows": 3,
                    "valid_rows": 2,
                    "rejected_rows": 1,
                    "duplicate_rows": 0,
                    "event_classes": {"success": 1, "failure": 1, "lockout": 0},
                },
            )
            write_json(
                analysis / "baseline" / "baseline_summary.json",
                {
                    "timezone": "America/Guayaquil",
                    "evaluation_period": {
                        "start_local": "2026-03-21",
                        "end_local": "2026-03-22",
                    },
                },
            )
            write_json(
                analysis / "alerts" / "alert_summary.json",
                {
                    "total_alerts": 1,
                    "alerts_by_rule": {"AUTH_BRUTE_FORCE_USER": 1},
                    "alerts_by_severity": {"high": 1},
                },
            )
            write_json(
                config,
                {
                    "brute_force_user": {"enabled": True},
                    "after_hours": {
                        "enabled": False,
                        "reason_disabled": "Cobertura temporal incompleta",
                    },
                },
            )
            write_csv(
                analysis / "baseline" / "user_behavior.csv",
                [
                    {
                        "user_key": "usr_synthetic",
                        "failure_count": "1",
                        "lockout_count": "0",
                        "history_status": "sufficient",
                    }
                ],
            )
            write_csv(
                analysis / "baseline" / "ip_behavior.csv",
                [
                    {
                        "client_ip_key": "ip_synthetic",
                        "failure_count": "1",
                        "distinct_users": "1",
                    }
                ],
            )
            with AlertStore(state_db) as store:
                alert = sample_alert()
                store.insert_alert(alert, source_name="csv_demo_mvp")
                store.update_alert_status(alert["alert_id"], "false_positive", "Prueba")

            report = generate_report(
                analysis,
                output,
                detection_config_path=config,
                state_db=state_db,
            )
            content = report.read_text(encoding="utf-8")
            self.assertIn("Reporte histórico", content)
            self.assertIn("Falsos positivos registrados en SQLite: **1**", content)
            self.assertIn("Cobertura temporal incompleta", content)
            self.assertIn("usr_synthetic", content)
            self.assertTrue((output / "charts" / "alerts_by_rule.svg").is_file())


if __name__ == "__main__":
    unittest.main()
