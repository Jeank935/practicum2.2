"""CSV sintético → normalización → línea base → casos → reporte, sin Docker."""

import csv
import json
from pathlib import Path

from test_normalize_events import valid_record

from adfs_schema import SOURCE_COLUMNS
from container_demo import run_pipeline


def test_container_pipeline_is_reproducible_and_preserves_csv(tmp_path, monkeypatch):
    monkeypatch.setenv("SOC_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SOC_PSEUDONYM_KEY", "synthetic-hmac-key-for-tests-only")
    root = Path(__file__).resolve().parents[1]
    config = tmp_path / "config"
    config.mkdir()
    for name in ("normalization", "detection_rules", "operational"):
        (config / f"{name}.json").write_text(
            (root / "config" / f"{name}.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
    (config / "baseline.json").write_text(
        json.dumps(
            {
                "timezone": "UTC",
                "minimum_events_per_day": 2,
                "minimum_active_hours_per_day": 2,
                "minimum_user_history_events": 2,
                "training_start_local": "2026-03-20",
                "training_end_local": "2026-03-20",
                "evaluation_start_local": "2026-03-21",
            }
        ),
        encoding="utf-8",
    )
    records = []
    for i, timestamp in enumerate(
        ["2026-03-20T09:00:00+00:00", "2026-03-20T10:00:00+00:00"]
        + [f"2026-03-21T10:0{minute}:00+00:00" for minute in range(6)]
    ):
        record = valid_record(str(i))
        record.update(event_time=timestamp, created_at=timestamp)
        records.append(record)
    path = tmp_path / "events.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows([[item[column] for column in SOURCE_COLUMNS] for item in records])
    original = path.read_bytes()
    analysis = tmp_path / "analysis"
    first = run_pipeline(path, analysis, config)
    second = run_pipeline(path, analysis, config)
    assert first["created_alerts"] >= 1
    assert second["created_alerts"] == second["inserted_events"] == 0
    assert path.read_bytes() == original
    report = (analysis / "report/historical_report.md").read_text(encoding="utf-8")
    assert "Falsos positivos" in report
    assert "real-user-for-test" not in report and "203.0.113.10" not in report
