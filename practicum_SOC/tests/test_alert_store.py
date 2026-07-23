import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from alert_store import AlertStore  # noqa: E402


def sample_alert(alert_id="alt_1", minute=0):
    return {
        "alert_id": alert_id,
        "rule_id": "AUTH_TEST",
        "rule_name": "Regla sintética",
        "severity": "high",
        "risk_score": 75,
        "risk_factors": json.dumps([{"factor": "base_rule", "points": 75}]),
        "first_seen_local": f"2026-03-16T10:{minute:02d}:00-05:00",
        "last_seen_local": f"2026-03-16T10:{minute:02d}:00-05:00",
        "user_key": "usr_test",
        "client_ip_key": "ip_test",
        "event_types": "failure:3",
        "event_count": 3,
        "success_count": 0,
        "failure_count": 3,
        "lockout_count": 0,
        "distinct_users": 1,
        "distinct_client_ips": 1,
        "relying_parties": "app_test",
        "evidence_event_ids": "1;2;3",
        "description": "Evidencia sintética.",
        "recommendation": "Revisar.",
    }


class AlertStoreTests(unittest.TestCase):
    def test_checkpoint_event_deduplication_and_status_history(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            path = Path(temp_directory) / "state.db"
            with AlertStore(path) as store:
                store.save_checkpoint("test", "2026-03-16T10:00:00+00:00", "10")
                self.assertEqual(
                    store.get_checkpoint("test"),
                    ("2026-03-16T10:00:00+00:00", "10"),
                )
                event = {
                    "source_event_id": "evt_1",
                    "record_id": "1",
                    "event_time_utc": "2026-03-16T10:00:00+00:00",
                    "event_class": "failure",
                    "event_type_id": "1203",
                    "event_name": "Fresh Credential Validation Error",
                    "user_key": "usr_test",
                    "client_ip_key": "ip_test",
                    "relying_party": "app_test",
                    "event_count": 1,
                    "quality_flags": "",
                }
                self.assertTrue(
                    store.insert_event(
                        event, event["event_time_utc"], "1", True, source_name="test"
                    )
                )
                self.assertFalse(
                    store.insert_event(
                        event, event["event_time_utc"], "1", True, source_name="test"
                    )
                )
                self.assertTrue(
                    store.insert_event(
                        event, event["event_time_utc"], "1", True, source_name="other"
                    )
                )

                created, reason = store.insert_alert(
                    sample_alert(), cooldown_minutes=15, source_name="test"
                )
                self.assertTrue(created)
                self.assertEqual(reason, "created")
                duplicate, reason = store.insert_alert(
                    sample_alert(), cooldown_minutes=15, source_name="test"
                )
                self.assertFalse(duplicate)
                self.assertEqual(reason, "duplicate_alert")
                cooled, reason = store.insert_alert(
                    sample_alert("alt_2", minute=5),
                    cooldown_minutes=15,
                    source_name="test",
                )
                self.assertFalse(cooled)
                self.assertEqual(reason, "persistent_cooldown")

                store.update_alert_status("alt_1", "investigating", "Caso sintético")
                self.assertEqual(store.get_alert("alt_1")["investigation_status"], "investigating")
                run_id = store.start_run("test")
                store.finish_run(run_id, "completed", fetched_count=1)
                self.assertEqual(store.health_summary()["status"], "healthy")
                self.assertEqual(len(store.alert_history("alt_1")), 2)

    def test_cooldown_survives_store_reopen(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            path = Path(temp_directory) / "state.db"
            with AlertStore(path) as store:
                store.insert_alert(
                    sample_alert("alt_first", minute=0),
                    cooldown_minutes=15,
                    source_name="csv_demo_mvp",
                )
            with AlertStore(path) as reopened:
                created, reason = reopened.insert_alert(
                    sample_alert("alt_second", minute=5),
                    cooldown_minutes=15,
                    source_name="csv_demo_mvp",
                )
                self.assertFalse(created)
                self.assertEqual(reason, "persistent_cooldown")


if __name__ == "__main__":
    unittest.main()
