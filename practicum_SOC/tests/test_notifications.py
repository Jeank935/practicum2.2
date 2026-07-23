import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from test_alert_store import sample_alert

from alert_store import AlertStore
from notifications import DeliveryResult, DryRunProvider, SocInboxProvider, deliver_once


class FailingProvider:
    channel_name = "synthetic_failure"

    def send(self, alert):
        return DeliveryResult("failed", "controlled_test_failure")


class NotificationTests(unittest.TestCase):
    def test_soc_inbox_is_persisted_once_and_marks_notified(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            with AlertStore(Path(temp_directory) / "state.db") as store:
                alert = sample_alert()
                store.insert_alert(alert, source_name="csv_demo_mvp")
                first = deliver_once(store, SocInboxProvider(), alert, 3)
                second = deliver_once(store, SocInboxProvider(), alert, 3)
                self.assertEqual(first.outcome, "sent")
                self.assertEqual(second.error_code, "already_delivered")
                self.assertEqual(store.delivery_attempt_count("alt_1", "soc_inbox"), 1)
                self.assertEqual(store.get_alert("alt_1")["investigation_status"], "notified")

    def test_dry_run_and_failure_are_controlled(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            with AlertStore(Path(temp_directory) / "state.db") as store:
                alert = sample_alert()
                store.insert_alert(alert)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        deliver_once(store, DryRunProvider(), alert, 3).outcome, "dry_run"
                    )
                self.assertEqual(deliver_once(store, FailingProvider(), alert, 1).outcome, "failed")
                self.assertEqual(
                    deliver_once(store, FailingProvider(), alert, 1).error_code,
                    "retry_limit",
                )


if __name__ == "__main__":
    unittest.main()
