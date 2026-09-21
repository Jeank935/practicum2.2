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
    def test_service_metrics_separate_common_and_rare_services(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            path = Path(temp_directory) / "state.db"
            with AlertStore(path) as store:
                for index, service_name in enumerate(["app_common"] * 3 + ["app_rare"]):
                    event = {
                        "source_event_id": f"evt_{index}",
                        "record_id": str(index),
                        "event_time_utc": f"2026-03-16T10:0{index}:00+00:00",
                        "event_class": "success" if index < 3 else "failure",
                        "event_type_id": "1200" if index < 3 else "1203",
                        "event_name": "Evento sintético",
                        "user_key": f"usr_{index}",
                        "client_ip_key": f"ip_{index}",
                        "relying_party": service_name,
                        "event_count": 1,
                        "quality_flags": "",
                    }
                    store.insert_event(
                        event,
                        event["event_time_utc"],
                        str(index),
                        True,
                        source_name="test",
                    )

                metrics = store.service_metrics(
                    "test", window_days=0, top_limit=10, rare_max_events=1
                )
                self.assertEqual(metrics["total_events"], 4)
                self.assertEqual(metrics["distinct_services"], 2)
                self.assertEqual(metrics["top_services"][0]["relying_party"], "app_common")
                self.assertEqual(metrics["rare_services"][0]["relying_party"], "app_rare")
                self.assertEqual(metrics["failure_count"], 1)

    def test_operational_summary_tracks_the_soc_queue(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            path = Path(temp_directory) / "state.db"
            with AlertStore(path) as store:
                store.insert_alert(sample_alert(), source_name="postgresql_live")
                initial = store.operational_alert_summary("postgresql_live")
                self.assertEqual(initial["pending_review"], 1)
                self.assertEqual(initial["investigating"], 0)
                self.assertEqual(initial["open_by_severity"]["high"], 1)

                store.update_alert_status("alt_1", "investigating", "Revisión")
                updated = store.operational_alert_summary("postgresql_live")
                self.assertEqual(updated["pending_review"], 0)
                self.assertEqual(updated["investigating"], 1)
                self.assertNotEqual(initial["revision"], updated["revision"])

    def test_open_alerts_are_grouped_by_service(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            path = Path(temp_directory) / "state.db"
            alert = sample_alert()
            alert["relying_parties"] = "service_sensitive"
            with AlertStore(path) as store:
                store.insert_alert(alert, source_name="test")

                counts = store.open_alert_counts_by_service("test")

                self.assertEqual(counts["service_sensitive"]["count"], 1)
                self.assertEqual(counts["service_sensitive"]["highest_severity"], "high")
                self.assertEqual(counts["service_sensitive"]["latest_alert_id"], "alt_1")

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
