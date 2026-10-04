"""Resultados congelados antes de reorganizar el backend, con datos sintéticos."""

import csv
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from test_detect_alerts import baseline, mvp_config
from test_normalize_events import valid_record

from practicum_soc.schemas.events import SOURCE_COLUMNS
from practicum_soc.soc.baseline import run_baseline
from practicum_soc.soc.detection import Event, detect_alerts, load_baseline_context
from practicum_soc.soc.normalization import NormalizationConfig, normalize_csv


def test_seven_day_baseline_characterization(tmp_path):
    start = datetime(2026, 3, 14, 9, tzinfo=ZoneInfo("UTC"))
    rows = [
        {
            "event_time_utc": (start + timedelta(days=day, hours=hour)).isoformat(),
            "event_class": "success" if hour == 0 else "failure",
            "user_key": "usr_training" if day < 7 else "usr_evaluation",
            "client_ip_key": "ip_known" if day < 7 else "ip_evaluation",
            "relying_party": "urn:synthetic",
            "event_count": 1,
        }
        for day in range(8)
        for hour in range(2)
    ]
    source = tmp_path / "normalized.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    output = tmp_path / "baseline"
    summary = run_baseline(
        source,
        output,
        {
            "timezone": "UTC",
            "minimum_events_per_day": 2,
            "minimum_active_hours_per_day": 2,
            "minimum_user_history_events": 2,
            "training_start_local": "2026-03-14",
            "training_end_local": "2026-03-20",
            "evaluation_start_local": "2026-03-21",
        },
    )
    assert summary["baseline_day_count"] == 7
    assert summary["baseline_event_count"] == 14
    assert summary["evaluation_event_count"] == 2
    assert summary["baseline_event_classes"]["success"] == 7
    assert summary["baseline_event_classes"]["failure"] == 7
    context = load_baseline_context(output)
    assert context.sufficient_users == frozenset({"usr_training"})
    assert ("usr_training", "ip_known") in context.known_user_ips
    assert "usr_evaluation" not in context.sufficient_users


def test_normalization_characterization(tmp_path):
    records = [valid_record("1"), valid_record("1"), valid_record("2"), valid_record("3")]
    records[2]["custom_ip_address"] = "invalid"
    records[3].update(event_time="not-a-date", created_at="")
    source = tmp_path / "events.csv"
    with source.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(
            [[record[column] for column in SOURCE_COLUMNS] for record in records] + [["malformed"]]
        )
    original = source.read_bytes()
    result = normalize_csv(
        source,
        tmp_path / "normalized.csv",
        tmp_path / "rejected.csv",
        tmp_path / "stats.json",
        b"characterization-test-key",
        NormalizationConfig.from_file(
            Path(__file__).resolve().parents[1] / "config/normalization.json"
        ),
    )
    assert result["input_rows"] == 5
    assert result["valid_rows"] == 1
    assert result["rejected_rows"] == 4
    assert result["duplicate_rows"] == 1
    assert result["rejection_reasons"] == {
        "DUPLICATE_EVENT": 1,
        "INVALID_CLIENT_IP": 1,
        "INVALID_EVENT_TIME": 1,
        "MALFORMED_COLUMN_COUNT": 1,
    }
    assert source.read_bytes() == original


def characterized_alerts():
    start = datetime(2026, 3, 21, 10, 0, tzinfo=ZoneInfo("America/Guayaquil"))
    patterns = (
        [("failure", "usr_a", "ip_x")] * 3
        + [
            ("failure", "usr_b", "ip_x"),
            ("failure", "usr_c", "ip_x"),
            ("success", "usr_a", "ip_x"),
        ]
        + [("lockout", "usr_d", "ip_y")] * 2
    )
    events = [
        Event(start + timedelta(minutes=i), kind, user, ip, "app", str(i + 1))
        for i, (kind, user, ip) in enumerate(patterns)
    ]
    return detect_alerts(events, mvp_config(), baseline())


def test_five_rules_characterization():
    alerts = characterized_alerts()
    assert [(a["rule_id"], a["severity"], a["risk_score"], a["event_count"]) for a in alerts] == [
        ("AUTH_BRUTE_FORCE_USER", "high", 65, 3),
        ("AUTH_NEW_IP_FOR_USER", "medium", 40, 3),
        ("AUTH_PASSWORD_SPRAY_IP", "high", 72, 5),
        ("AUTH_SUCCESS_AFTER_FAILURES", "high", 81, 4),
        ("AUTH_ACCOUNT_LOCKOUT", "critical", 85, 2),
    ]
    # Todos los campos, incluidas evidencia e identificadores, deben ser idénticos.
    payload = json.dumps(alerts, sort_keys=True, separators=(",", ":")).encode()
    assert (
        hashlib.sha256(payload).hexdigest()
        == "90d253eca6e21d93c266e7f358b682ec34dc9d720daabf08cf5c2772a6b4a1bf"
    )
