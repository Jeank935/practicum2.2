import copy
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from detect_alerts import BaselineContext, Event, detect_alerts, evaluation_events


def mvp_config() -> dict:
    config = json.loads((ROOT / "config" / "detection_rules.json").read_text(encoding="utf-8"))
    config = copy.deepcopy(config)
    config["brute_force_user"]["minimum_failures"] = 3
    config["password_spraying_ip"].update({"minimum_failures": 3, "minimum_distinct_users": 3})
    config["success_after_failures"]["minimum_failures"] = 2
    return config


def baseline(training_end: str = "2026-03-20") -> BaselineContext:
    return BaselineContext(
        sufficient_users=frozenset({"usr_a"}),
        known_user_ips=frozenset({("usr_a", "ip_known")}),
        known_user_apps=frozenset(),
        known_user_hours=frozenset(),
        global_failure_rate=0.1,
        training_end_local=training_end,
    )


class DetectAlertsTests(unittest.TestCase):
    def test_five_mvp_rules_generate_explainable_alerts(self):
        start = datetime(2026, 3, 21, 10, 0, tzinfo=ZoneInfo("America/Guayaquil"))
        events = [
            Event(start.replace(minute=0), "failure", "usr_a", "ip_x", "app", "1"),
            Event(start.replace(minute=1), "failure", "usr_a", "ip_x", "app", "2"),
            Event(start.replace(minute=2), "failure", "usr_a", "ip_x", "app", "3"),
            Event(start.replace(minute=3), "failure", "usr_b", "ip_x", "app", "4"),
            Event(start.replace(minute=4), "failure", "usr_c", "ip_x", "app", "5"),
            Event(start.replace(minute=5), "success", "usr_a", "ip_x", "app", "6"),
            Event(start.replace(minute=6), "lockout", "usr_d", "ip_y", "app", "7"),
        ]
        alerts = detect_alerts(events, mvp_config(), baseline())
        rule_ids = {alert["rule_id"] for alert in alerts}
        self.assertEqual(
            rule_ids,
            {
                "AUTH_BRUTE_FORCE_USER",
                "AUTH_PASSWORD_SPRAY_IP",
                "AUTH_SUCCESS_AFTER_FAILURES",
                "AUTH_ACCOUNT_LOCKOUT",
                "AUTH_NEW_IP_FOR_USER",
            },
        )
        self.assertTrue(all(alert["recommendation"] for alert in alerts))
        self.assertTrue(all(alert["risk_factors"] != "[]" for alert in alerts))
        self.assertTrue(all(0 <= int(alert["risk_score"]) <= 100 for alert in alerts))

    def test_new_ip_requires_sufficient_history_and_evaluation_period(self):
        config = mvp_config()
        context = baseline()
        training_event = Event(
            datetime(2026, 3, 20, 10, 0, tzinfo=ZoneInfo("America/Guayaquil")),
            "success",
            "usr_a",
            "ip_new",
            "app",
            "1",
        )
        insufficient = Event(
            datetime(2026, 3, 21, 10, 0, tzinfo=ZoneInfo("America/Guayaquil")),
            "success",
            "usr_without_history",
            "ip_new",
            "app",
            "2",
        )
        alerts = detect_alerts([training_event, insufficient], config, context)
        self.assertNotIn("AUTH_NEW_IP_FOR_USER", {alert["rule_id"] for alert in alerts})
        self.assertEqual(evaluation_events([training_event, insufficient], context), [insufficient])

    def test_disabled_time_rules_never_generate_alerts(self):
        config = mvp_config()
        for rule in (
            "brute_force_user",
            "password_spraying_ip",
            "success_after_failures",
            "account_lockout",
            "new_ip_for_user",
        ):
            config[rule]["enabled"] = False
        event = Event(
            datetime(2026, 3, 21, 23, 0, tzinfo=ZoneInfo("America/Guayaquil")),
            "success",
            "usr_a",
            "ip_known",
            "app",
            "1",
        )
        self.assertEqual(detect_alerts([event], config, baseline()), [])
        self.assertFalse(config["after_hours"]["enabled"])
        self.assertFalse(config["unusual_hour_for_user"]["enabled"])


if __name__ == "__main__":
    unittest.main()
