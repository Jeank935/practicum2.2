import json

from monitor_service import next_cycle_delay_seconds
from monitoring import load_exclusions


def test_monitor_skips_delay_while_catching_up() -> None:
    config = {
        "batch_size": 2000,
        "interval_seconds": 5,
        "catch_up_interval_seconds": 0,
    }

    assert next_cycle_delay_seconds({"fetched": 2000}, config) == 0


def test_monitor_waits_at_live_edge() -> None:
    config = {
        "batch_size": 2000,
        "interval_seconds": 5,
        "catch_up_interval_seconds": 0,
    }

    assert next_cycle_delay_seconds({"fetched": 41}, config) == 5


def test_exclusion_configuration_loads_elevated_thresholds(tmp_path) -> None:
    path = tmp_path / "exclusions.json"
    path.write_text(
        json.dumps(
            {
                "authorized_user_keys": ["usr_technical"],
                "authorized_client_ip_keys": ["ip_internal"],
                "authorized_relying_parties": [],
                "anomalous_thresholds": {"failures_per_user": 25},
            }
        ),
        encoding="utf-8",
    )

    exclusions = load_exclusions(path)

    assert exclusions["user_keys"] == {"usr_technical"}
    assert exclusions["client_ip_keys"] == {"ip_internal"}
    assert exclusions["anomalous_thresholds"]["failures_per_user"] == 25
