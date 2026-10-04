"""Actualización incremental, salud y recuperación sin conexión institucional."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from test_alert_store import sample_alert

import practicum_soc.api.streaming as live_updates
import practicum_soc.main as web_app
from practicum_soc.analytics.operational import pilot_metrics, technical_metrics
from practicum_soc.repositories.alerts import AlertStore
from practicum_soc.repositories.backup import sqlite_backup, sqlite_restore
from practicum_soc.services.dashboard import DashboardService

ROOT = Path(__file__).resolve().parents[1]


def test_online_backup_and_restore_are_consistent_and_never_overwrite(tmp_path):
    original = tmp_path / "active.db"
    backup = tmp_path / "backup.db"
    restored = tmp_path / "restored.db"
    with AlertStore(original) as store:
        store.insert_alert(sample_alert(), source_name="csv_demo_mvp")
        sqlite_backup(original, backup)
        store.update_alert_status("alt_1", "resolved", actor_id="analyst")
    sqlite_restore(backup, restored)
    with AlertStore(restored) as store:
        assert store.get_alert("alt_1")["investigation_status"] == "new"
    with pytest.raises(FileExistsError):
        sqlite_restore(backup, original)
    with pytest.raises(ValueError):
        sqlite_backup(original, original)


def test_technical_and_pilot_metrics_are_bounded_and_explicit(tmp_path):
    now = datetime.now(UTC)
    with AlertStore(tmp_path / "soc.db") as store:
        event_time = (now - timedelta(seconds=30)).isoformat()
        store.insert_event(
            {
                "source_event_id": "event_lag",
                "event_time_utc": event_time,
                "event_class": "failure",
                "event_count": 1,
                "user_key": "usr_test",
                "client_ip_key": "ip_test",
            },
            event_time,
            "event_lag",
            True,
            source_name="csv_demo_mvp",
        )
        store.insert_alert(sample_alert(), source_name="csv_demo_mvp")
        store.update_alert_status("alt_1", "investigating", actor_id="analyst")
        store.update_alert_status("alt_1", "false_positive", actor_id="analyst")
        run_id = store.start_run("csv_demo_mvp")
        store.finish_run(run_id, "failed", error_code="SyntheticFailure")
        technical = technical_metrics(store, "csv_demo_mvp", now=now + timedelta(seconds=1))
        pilot = pilot_metrics(store, "csv_demo_mvp", now=now + timedelta(seconds=1))
    assert technical["failed_runs_24h"] == 1
    assert technical["last_run"]["status"] == "failed"
    assert technical["last_run_duration_seconds"] is not None
    assert technical["database_bytes"] > 0
    assert technical["event_to_soc_seconds"] >= 29
    assert pilot["closed_cases"] == 1
    assert pilot["false_positive_rate_percent"] == 100.0
    assert pilot["cases_with_analyst_action"] == 1
    assert pilot["median_closure_minutes"] is not None
    with pytest.raises(ValueError):
        pilot_metrics(None, "csv_demo_mvp", limit=10_000)


def test_private_snapshot_and_operations_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("SOC_AUTH_MODE", "disabled")
    state = tmp_path / "soc.db"
    with AlertStore(state) as store:
        store.insert_alert(sample_alert(), source_name="csv_demo_mvp")
        run_id = store.start_run("csv_demo_mvp")
        store.finish_run(run_id, "completed")
    dashboard = DashboardService(
        state_db=state,
        analysis_dir=tmp_path,
        detection_config=ROOT / "config/detection_rules.json",
        operational_config=ROOT / "config/operational.json",
    )
    with patch.object(web_app.app.state, "dashboard_service", dashboard):
        client = TestClient(web_app.app)
        page = client.get("/")
        assert page.status_code == 200
        assert 'data-summary="pending_review"' in page.text
        snapshot = client.get("/api/v1/dashboard/snapshot")
        assert snapshot.status_code == 200
        assert snapshot.json()["operational"]["pending_review"] == 1
        assert "Regla sintética" in snapshot.json()["recent_html"]
        metrics = client.get("/api/v1/operations/metrics")
        assert metrics.status_code == 200
        assert metrics.json()["technical"]["last_run"]["status"] == "completed"
        assert (
            dashboard.dashboard_version()["revision"] == snapshot.json()["operational"]["revision"]
        )


def test_concurrent_readers_observe_consistent_revision(tmp_path):
    state = tmp_path / "shared.db"
    with AlertStore(state) as store:
        store.insert_alert(sample_alert(), source_name="csv_demo_mvp")
        run_id = store.start_run("csv_demo_mvp")
        store.finish_run(run_id, "completed")
    dashboard = DashboardService(
        state_db=state,
        analysis_dir=tmp_path,
        detection_config=ROOT / "config/detection_rules.json",
        operational_config=ROOT / "config/operational.json",
    )
    before = dashboard.dashboard_version()["revision"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        versions = list(pool.map(lambda _: dashboard.dashboard_version(), range(12)))
    assert {item["revision"] for item in versions} == {before}
    with AlertStore(state) as store:
        store.update_alert_status("alt_1", "investigating", actor_id="analyst")
    assert dashboard.dashboard_version()["revision"] != before


def test_sse_rechecks_session_and_stops_after_revocation(monkeypatch):
    monkeypatch.setattr(live_updates.AuthSettings, "from_env", lambda: object())
    decisions = iter([True, False])
    monkeypatch.setattr(live_updates, "session_still_valid", lambda *_: next(decisions))

    class Request:
        cookies = {"soc_session": "synthetic"}
        app = type("App", (), {"state": type("State", (), {"soc_state_db": None})()})()

        async def is_disconnected(self):
            return False

    class Dashboard:
        def dashboard_version(self):
            return {"revision": "one", "source": "csv_demo_mvp"}

    async def read():
        events = []
        async for event in live_updates.revision_stream(Request(), Dashboard(), 0, 10):
            events.append(event)
        return events

    events = asyncio.run(read())
    assert any("event: revision" in event for event in events)
    assert events[-1].startswith("event: session-expired")


def test_stream_settings_reject_unsafe_intervals(tmp_path):
    config = tmp_path / "updates.json"
    config.write_text('{"stream_check_seconds":1,"stream_max_seconds":601}')
    with pytest.raises(ValueError):
        live_updates.stream_settings(config)
