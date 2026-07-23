import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from build_baseline import percentile, run_baseline  # noqa: E402


class BuildBaselineTests(unittest.TestCase):
    def test_percentile(self):
        self.assertEqual(percentile([1, 2, 3, 4, 5], 0.95), 5.0)
        self.assertEqual(percentile([], 0.95), 0.0)

    def test_partial_day_is_excluded(self):
        fieldnames = [
            "event_class",
            "event_time_utc",
            "user_key",
            "client_ip_key",
            "relying_party",
            "event_count",
        ]
        rows = [
            {
                "event_class": "success",
                "event_time_utc": "2026-03-14T01:00:00+00:00",
                "user_key": "usr_a",
                "client_ip_key": "ip_a",
                "relying_party": "app",
                "event_count": "1",
            },
            {
                "event_class": "failure",
                "event_time_utc": "2026-03-14T02:00:00+00:00",
                "user_key": "usr_a",
                "client_ip_key": "ip_b",
                "relying_party": "app",
                "event_count": "1",
            },
            {
                "event_class": "lockout",
                "event_time_utc": "2026-03-15T01:00:00+00:00",
                "user_key": "usr_b",
                "client_ip_key": "ip_c",
                "relying_party": "app",
                "event_count": "1",
            },
        ]
        with tempfile.TemporaryDirectory() as temp_directory:
            temp = Path(temp_directory)
            source = temp / "normalized.csv"
            output = temp / "baseline"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            summary = run_baseline(
                source,
                output,
                {
                    "timezone": "UTC",
                    "minimum_events_per_day": 2,
                    "minimum_active_hours_per_day": 2,
                    "minimum_user_history_events": 2,
                    "training_start_local": "2026-03-14",
                    "training_end_local": "2026-03-14",
                    "evaluation_start_local": "2026-03-15",
                },
            )
            self.assertEqual(summary["baseline_days"], ["2026-03-14"])
            self.assertEqual(summary["baseline_event_count"], 2)
            self.assertTrue((output / "user_behavior.csv").is_file())
            self.assertTrue((output / "user_app_profile.csv").is_file())
            saved = json.loads((output / "baseline_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["baseline_day_count"], 1)
            self.assertEqual(saved["baseline_event_classes"]["success"], 1)
            self.assertEqual(saved["evaluation_event_count"], 1)
            users = (output / "user_behavior.csv").read_text(encoding="utf-8")
            self.assertIn("usr_a", users)
            self.assertNotIn("usr_b", users)


if __name__ == "__main__":
    unittest.main()
