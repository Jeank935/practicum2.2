import copy
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from alert_store import AlertStore
from build_baseline import run_baseline
from demo_service import run_demo
from notifications import SocInboxProvider


def normalized_row(
    event_id: str,
    timestamp: str,
    event_class: str,
    ip_key: str = "ip_known",
) -> dict[str, str]:
    return {
        "source_event_id": event_id,
        "deduplication_key": f"event:{event_id}",
        "record_id": event_id,
        "event_type_id": "1201",
        "event_name": "Synthetic",
        "event_time_utc": timestamp,
        "event_class": event_class,
        "user_key": "usr_a",
        "client_ip_key": ip_key,
        "relying_party": "app",
        "event_count": "1",
        "quality_flags": "",
    }


class DemoServiceTests(unittest.TestCase):
    def test_demo_is_reproducible_and_persistent_between_executions(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            analysis = root / "analysis"
            normalized = analysis / "normalized_events.csv"
            normalized.parent.mkdir(parents=True)
            rows = [
                normalized_row("1", "2026-03-20T09:00:00+00:00", "success"),
                normalized_row("2", "2026-03-20T10:00:00+00:00", "success"),
                normalized_row("3", "2026-03-21T10:00:00+00:00", "failure", "ip_new"),
                normalized_row("4", "2026-03-21T10:01:00+00:00", "failure", "ip_new"),
                normalized_row("5", "2026-03-21T10:02:00+00:00", "failure", "ip_new"),
                normalized_row("6", "2026-03-21T10:03:00+00:00", "success", "ip_new"),
            ]
            with normalized.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)

            run_baseline(
                normalized,
                analysis / "baseline",
                {
                    "timezone": "UTC",
                    "minimum_events_per_day": 2,
                    "minimum_active_hours_per_day": 2,
                    "minimum_user_history_events": 2,
                    "training_start_local": "2026-03-20",
                    "training_end_local": "2026-03-20",
                    "evaluation_start_local": "2026-03-21",
                },
            )
            detection = json.loads(
                (ROOT / "config" / "detection_rules.json").read_text(encoding="utf-8")
            )
            detection = copy.deepcopy(detection)
            detection["timezone"] = "UTC"
            detection["brute_force_user"]["minimum_failures"] = 3
            detection["password_spraying_ip"]["enabled"] = False
            detection["success_after_failures"]["minimum_failures"] = 2
            detection_path = root / "detection.json"
            detection_path.write_text(json.dumps(detection), encoding="utf-8")
            operational = json.loads(
                (ROOT / "config" / "operational.json").read_text(encoding="utf-8")
            )
            operational_path = root / "operational.json"
            operational_path.write_text(json.dumps(operational), encoding="utf-8")
            database = analysis / "state" / "soc.db"

            arguments = {
                "analysis_dir": analysis,
                "state_db": database,
                "detection_config_path": detection_path,
                "operational_config_path": operational_path,
                "provider": SocInboxProvider(),
            }
            first = run_demo(**arguments)
            second = run_demo(**arguments)

            self.assertEqual(first["evaluation_events"], 4)
            self.assertEqual(first["created_alerts"], 3)
            self.assertEqual(first["delivered_to_soc_inbox"], 2)
            self.assertEqual(second["inserted_events"], 0)
            self.assertEqual(second["created_alerts"], 0)
            with AlertStore(database) as store:
                self.assertEqual(store.alert_counts("csv_demo_mvp")["total"], 3)


if __name__ == "__main__":
    unittest.main()
