"""Ejecución reproducible del MVP sobre el periodo de evaluación del CSV."""

from __future__ import annotations

import csv
from pathlib import Path

from alert_store import AlertStore
from detect_alerts import (
    detect_alerts,
    evaluation_events,
    load_baseline_context,
    load_events,
)
from monitoring import cooldown_for_alert
from notifications import NotificationProvider, deliver_once
from runtime_config import load_json

DEMO_SOURCE_NAME = "csv_demo_mvp"


def _normalized_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            row.get("source_event_id") or row["deduplication_key"]: row
            for row in csv.DictReader(handle)
            if row.get("source_event_id") or row.get("deduplication_key")
        }


def _persist_events(store: AlertStore, events, rows_by_id: dict[str, dict[str, str]]) -> int:
    inserted = 0
    for event in events:
        row = rows_by_id[event.source_event_id]
        inserted += store.insert_event(
            row,
            row["event_time_utc"],
            event.source_event_id,
            True,
            source_name=DEMO_SOURCE_NAME,
        )
    return inserted


def _persist_and_deliver_alerts(
    store: AlertStore,
    alerts: list[dict],
    detection_config: dict,
    operational_config: dict,
    provider: NotificationProvider,
) -> tuple[int, int]:
    created = delivered = 0
    immediate = set(operational_config["notification_policy"]["immediate_severities"])
    max_attempts = int(operational_config["notification_policy"]["maximum_delivery_attempts"])
    for alert in alerts:
        was_created, _ = store.insert_alert(
            alert,
            cooldown_for_alert(alert, detection_config),
            source_name=DEMO_SOURCE_NAME,
        )
        if not was_created:
            continue
        created += 1
        if alert["severity"] in immediate:
            deliver_once(store, provider, alert, max_attempts)
            delivered += 1
        else:
            store.record_suppression(
                "notification_deferred_by_severity_policy",
                rule_id=alert["rule_id"],
                entity_key=AlertStore._entity_key(alert),
                details={"severity": alert["severity"]},
            )
    return created, delivered


def run_demo(
    *,
    analysis_dir: Path,
    state_db: Path,
    detection_config_path: Path,
    operational_config_path: Path,
    provider: NotificationProvider,
) -> dict:
    normalized_path = analysis_dir / "normalized_events.csv"
    baseline_dir = analysis_dir / "baseline"
    if not normalized_path.is_file() or not baseline_dir.is_dir():
        raise FileNotFoundError(
            "Faltan artefactos históricos. Ejecute run_analysis.ps1 antes del demo."
        )

    detection_config = load_json(detection_config_path)
    operational_config = load_json(operational_config_path)
    baseline = load_baseline_context(baseline_dir)
    all_events, skipped = load_events(normalized_path, detection_config["timezone"])
    events = evaluation_events(all_events, baseline)
    rows_by_id = _normalized_rows(normalized_path)

    with AlertStore(state_db) as store:
        run_id = store.start_run(DEMO_SOURCE_NAME)
        try:
            inserted_events = _persist_events(store, events, rows_by_id)
            alerts = detect_alerts(events, detection_config, baseline)
            created_alerts, delivered = _persist_and_deliver_alerts(
                store,
                alerts,
                detection_config,
                operational_config,
                provider,
            )
            if events:
                last_event = events[-1]
                store.save_checkpoint(
                    DEMO_SOURCE_NAME,
                    last_event.timestamp.isoformat(),
                    last_event.source_event_id,
                )
            store.finish_run(
                run_id,
                "completed",
                fetched_count=len(events),
                inserted_event_count=inserted_events,
                alert_count=created_alerts,
            )
            return {
                "source": DEMO_SOURCE_NAME,
                "mode": "demo",
                "evaluation_events": len(events),
                "skipped_invalid_time": skipped,
                "inserted_events": inserted_events,
                "created_alerts": created_alerts,
                "delivered_to_soc_inbox": delivered,
                "persisted_alerts": store.alert_counts(DEMO_SOURCE_NAME)["total"],
            }
        except Exception as error:
            store.finish_run(run_id, "failed", error_code=type(error).__name__)
            raise
