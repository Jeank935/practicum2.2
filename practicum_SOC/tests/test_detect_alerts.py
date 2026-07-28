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
            Event(start.replace(minute=7), "lockout", "usr_d", "ip_y", "app", "8"),
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

    def test_isolated_failures_do_not_create_cases(self):
        start = datetime(2026, 3, 21, 10, 0, tzinfo=ZoneInfo("America/Guayaquil"))
        events = [
            Event(
                start.replace(minute=index),
                "failure",
                f"usr_{index}",
                f"ip_{index}",
                "app",
                str(index),
            )
            for index in range(10)
        ]

        self.assertEqual(detect_alerts(events, mvp_config(), baseline()), [])

    def test_six_failures_for_one_user_generate_one_high_case(self):
        config = mvp_config()
        config["brute_force_user"]["minimum_failures"] = 6
        start = datetime(2026, 3, 21, 10, 0, tzinfo=ZoneInfo("America/Guayaquil"))
        events = [
            Event(start.replace(minute=index), "failure", "usr_x", f"ip_{index}", "app", str(index))
            for index in range(6)
        ]

        alerts = detect_alerts(events, config)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["rule_id"], "AUTH_BRUTE_FORCE_USER")
        self.assertEqual(alerts[0]["severity"], "high")
        self.assertEqual(alerts[0]["failure_count"], 6)

    def test_password_spray_correlates_one_ip_and_multiple_users(self):
        config = mvp_config()
        config["brute_force_user"]["minimum_failures"] = 6
        config["password_spraying_ip"].update({"minimum_failures": 6, "minimum_distinct_users": 3})
        start = datetime(2026, 3, 21, 10, 0, tzinfo=ZoneInfo("America/Guayaquil"))
        events = [
            Event(
                start.replace(minute=index),
                "failure",
                f"usr_{index % 3}",
                "ip_source",
                "app",
                str(index),
            )
            for index in range(6)
        ]

        alerts = detect_alerts(events, config)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["rule_id"], "AUTH_PASSWORD_SPRAY_IP")
        self.assertEqual(alerts[0]["severity"], "high")
        self.assertEqual(alerts[0]["distinct_users"], 3)

    def test_single_lockout_is_historical_but_repeated_lockout_is_critical(self):
        config = mvp_config()
        start = datetime(2026, 3, 21, 10, 0, tzinfo=ZoneInfo("America/Guayaquil"))
        first = Event(start, "lockout", "usr_x", "ip_x", "app", "1")
        second = Event(start.replace(minute=4), "lockout", "usr_x", "ip_x", "app", "2")

        self.assertEqual(detect_alerts([first], config), [])
        alerts = detect_alerts([first, second], config)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["rule_id"], "AUTH_ACCOUNT_LOCKOUT")
        self.assertEqual(alerts[0]["severity"], "critical")
        self.assertEqual(alerts[0]["lockout_count"], 2)

    def test_new_ip_requires_repeated_activity(self):
        config = mvp_config()
        start = datetime(2026, 3, 21, 10, 0, tzinfo=ZoneInfo("America/Guayaquil"))
        events = [
            Event(start.replace(minute=index), "success", "usr_a", "ip_new", "app", str(index))
            for index in range(3)
        ]

        self.assertEqual(detect_alerts(events[:1], config, baseline()), [])
        alerts = detect_alerts(events, config, baseline())

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["rule_id"], "AUTH_NEW_IP_FOR_USER")
        self.assertEqual(alerts[0]["severity"], "medium")

    def test_authorized_entities_use_anomalous_thresholds(self):
        config = mvp_config()
        config["brute_force_user"]["minimum_failures"] = 6
        exclusions = {
            "user_keys": {"usr_technical"},
            "client_ip_keys": set(),
            "relying_parties": set(),
            "anomalous_thresholds": {"failures_per_user": 8},
        }
        start = datetime(2026, 3, 21, 10, 0, tzinfo=ZoneInfo("America/Guayaquil"))
        events = [
            Event(
                start.replace(minute=index),
                "failure",
                "usr_technical",
                f"ip_{index}",
                "app",
                str(index),
            )
            for index in range(8)
        ]

        self.assertEqual(detect_alerts(events[:6], config, exclusions=exclusions), [])
        alerts = detect_alerts(events, config, exclusions=exclusions)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["rule_id"], "AUTH_BRUTE_FORCE_USER")
        self.assertEqual(alerts[0]["severity"], "high")


if __name__ == "__main__":
    unittest.main()
