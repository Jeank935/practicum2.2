import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from practicum_soc.analytics.historical_report import save_report
from practicum_soc.cli.historical import safe_failure
from practicum_soc.repositories.alerts import AlertStore
from practicum_soc.schemas.events import SOURCE_COLUMNS
from practicum_soc.services.history import analyze_history
from practicum_soc.soc.detection import BaselineContext
from practicum_soc.soc.history_source import HistoricalPostgresSource
from practicum_soc.soc.ingestion import IncrementalCursor, SourceRecord
from practicum_soc.soc.normalization import NormalizationConfig

ROOT = Path(__file__).resolve().parents[1]
ZONE = ZoneInfo("America/Guayaquil")


def record(identifier, timestamp, name="Fresh Credential Validation Error", user="synthetic"):
    values = {name: "" for name in SOURCE_COLUMNS}
    values.update(
        {
            "id": str(identifier),
            "event_id": str(identifier),
            "event_name": name,
            "event_type_id": "1203" if "Error" in name else "1200",
            "event_time": timestamp.isoformat(),
            "event_time_origen": timestamp.isoformat(),
            "created_at": timestamp.isoformat(),
            "updated_at": timestamp.isoformat(),
            "custom_user_id": user,
            "custom_ip_address": "192.0.2.1",
            "event_count": "1",
        }
    )
    return SourceRecord(values, IncrementalCursor(timestamp.isoformat(), str(identifier)))


class FakeSource:
    source_name = "postgresql_live"

    def __init__(self, records):
        self.records = records

    def batches(self, start, end, size):
        rows = [
            r for r in self.records if start <= datetime.fromisoformat(r.cursor.timestamp_utc) < end
        ]
        for index in range(0, len(rows), size):
            yield rows[index : index + size]


def test_history_preserves_checkpoint_boundary_detection_and_replay(tmp_path, monkeypatch):
    start = datetime(2026, 8, 1, tzinfo=ZONE)
    end = datetime(2026, 10, 1, tzinfo=ZONE)
    baseline = BaselineContext(
        frozenset(), frozenset(), frozenset(), frozenset(), 0.1, "2026-03-20"
    )
    monkeypatch.setattr("practicum_soc.services.history.load_baseline_context", lambda _: baseline)
    rows = [record(i, start - timedelta(minutes=3) + timedelta(minutes=i)) for i in range(6)]
    rows += [record(6, start + timedelta(minutes=3), "Application Token Success")]
    rows += [record(20 + i, start + timedelta(hours=2 + i), user=f"other_{i}") for i in range(8)]
    rows += [record(40, datetime(2026, 9, 5, tzinfo=ZONE), "Application Token Success")]
    rules = json.loads((ROOT / "config/detection_rules.json").read_text())
    settings = dict(
        source=FakeSource(rows),
        start=start,
        end=end,
        secret=b"synthetic-only",
        normalization=NormalizationConfig(2000, frozenset({"MISSING_USER_ID"})),
        detection=rules,
        operational={
            "baseline_dir": "unused",
            "exclusions_file": "unused",
            "notification_policy": {"maximum_delivery_attempts": 3},
        },
        policy={"batch_size": 2, "progress_every_batches": 1, "verification_event_limit": 100},
        progress=lambda _: None,
    )
    path = tmp_path / "history.db"
    with AlertStore(path) as store:
        store.save_checkpoint("postgresql_live", "2026-10-01T19:00:01+00:00", "0")
        result = analyze_history(store=store, **settings)
        assert result["verification"]["live_checkpoint_unchanged"]
        assert result["verification"]["new_events_on_replay"] == 0
        alerts = store.list_alerts(100, source_name="postgresql_live")
        assert {a["rule_id"] for a in alerts} == {
            "AUTH_BRUTE_FORCE_USER",
            "AUTH_SUCCESS_AFTER_FAILURES",
        }
        assert len(alerts) == 2
        assert all(a["delivery_status"] == "sent" for a in alerts)
        rerun = analyze_history(store=store, **settings)
        assert rerun["ingestion"]["inserted"] == 0
        assert rerun["persistence"].get("created", 0) == 0
    with AlertStore(path) as store:
        report = save_report(store, result, tmp_path / "report")
        assert [m["month"] for m in report["months"]] == ["2026-08", "2026-09"]
        assert sum(m["stored_alerts"] for m in report["months"]) == 2
        assert report["months"][1]["stored_rows"] == 1
        saved = json.loads((tmp_path / "report/summary.json").read_text())
        assert saved["verification"]["live_checkpoint_unchanged"]
        markdown = (tmp_path / "report/report.md").read_text()
        assert markdown.index("| 2026-09 |") < markdown.index("## 2026-08")
        assert "Cobertura observada (hora de Loja)" in markdown


def test_bulk_rejected_records_are_persisted_without_generating_cases(tmp_path):
    with AlertStore(tmp_path / "state.db") as store:
        item = {
            "deduplication_key": "invalid",
            "event_time_utc": "",
            "event_count": 1,
            "quality_flags": "INVALID_EVENT_TIME",
        }
        batch = [(item, "2026-08-01T00:00:00+00:00", "1", False)]
        assert store.insert_events(batch, "postgresql_live") == 1
        assert store.insert_events(batch, "postgresql_live") == 0
        row = store.connection.execute("SELECT * FROM normalized_events").fetchone()
        assert row["is_consistent"] == 0
        assert row["quality_flags"] == "INVALID_EVENT_TIME"
        assert store.list_alerts() == []


def test_range_source_uses_bound_parameters_and_no_offset():
    source = HistoricalPostgresSource(dsn="synthetic", view_name="integration.logs")
    query = source.range_query()
    assert query.count("%s") == 2
    assert "COALESCE(event_time_origen,event_time)" in query
    assert "OFFSET" not in query
    assert "custom_message" not in query
    assert '"integration"."logs"' in query


def test_history_error_diagnostic_does_not_publish_sensitive_message():
    try:
        raise RuntimeError("password=synthetic-secret user=private-user")
    except RuntimeError as error:
        diagnostic = safe_failure(error)
    assert diagnostic["error_code"] == "RuntimeError"
    assert "test_historical_analysis.py:" in diagnostic["error_origin"]
    assert "synthetic-secret" not in json.dumps(diagnostic)
    assert "private-user" not in json.dumps(diagnostic)
