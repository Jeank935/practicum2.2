"""Servicio reutilizable de ingesta incremental y alertamiento."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from alert_store import AlertStore
from detect_alerts import Event, detect_alerts, load_baseline_context
from event_source import CsvEventSource, IncrementalCursor, PostgresEventSource
from normalize_events import (
    NormalizationConfig,
    normalize_record,
    rejection_reasons,
)
from notifications import NotificationProvider, deliver_once

LOGGER = logging.getLogger("soc_monitor")
INSTITUTIONAL_SOURCE_UNAVAILABLE = "Fuente institucional no disponible. Utilizando modo demo"
RULE_CONFIG_KEYS = {
    "AUTH_BRUTE_FORCE_USER": "brute_force_user",
    "AUTH_PASSWORD_SPRAY_IP": "password_spraying_ip",
    "AUTH_ACCOUNT_LOCKOUT": "account_lockout",
    "AUTH_SUCCESS_AFTER_FAILURES": "success_after_failures",
    "AUTH_NEW_IP_FOR_USER": "new_ip_for_user",
}


def event_from_row(row: dict, timezone_name: str) -> Event | None:
    try:
        timestamp = datetime.fromisoformat(str(row.get("event_time_utc", "")))
        weight = max(1, int(row.get("event_count", 1)))
    except (ValueError, TypeError):
        return None
    return Event(
        timestamp=timestamp.astimezone(ZoneInfo(timezone_name)),
        event_class=str(row.get("event_class", "other")),
        user_key=str(row.get("user_key", "")),
        client_ip_key=str(row.get("client_ip_key", "")),
        relying_party=str(row.get("relying_party", "")),
        source_event_id=str(row.get("source_event_id", "")),
        weight=weight,
    )


def load_exclusions(path: Path) -> dict[str, set[str]]:
    from runtime_config import load_json

    if not path.is_file():
        return {"user_keys": set(), "client_ip_keys": set(), "relying_parties": set()}
    raw = load_json(path)
    return {
        "user_keys": set(raw.get("authorized_user_keys", [])),
        "client_ip_keys": set(raw.get("authorized_client_ip_keys", [])),
        "relying_parties": set(raw.get("authorized_relying_parties", [])),
    }


def exclusion_reason(event: Event, exclusions: dict[str, set[str]]) -> str:
    if event.user_key and event.user_key in exclusions["user_keys"]:
        return "authorized_user_exclusion"
    if event.client_ip_key and event.client_ip_key in exclusions["client_ip_keys"]:
        return "authorized_ip_exclusion"
    if event.relying_party and event.relying_party in exclusions["relying_parties"]:
        return "authorized_application_exclusion"
    return ""


def cooldown_for_alert(alert: dict, detection_config: dict) -> int:
    key = RULE_CONFIG_KEYS[str(alert["rule_id"])]
    return int(detection_config[key]["cooldown_minutes"])


def build_event_source(mode: str, input_csv: Path):
    if mode == "csv":
        return CsvEventSource(input_csv, source_name="csv_demo")
    view_name = os.environ.get("SOC_DB_VIEW", "").strip()
    if not view_name:
        raise RuntimeError("SOC_DB_VIEW no está configurado")
    return PostgresEventSource(
        dsn=os.environ.get("SOC_DB_DSN", ""),
        view_name=view_name,
        time_column=os.environ.get("SOC_DB_TIME_COLUMN", "event_time"),
        id_column=os.environ.get("SOC_DB_ID_COLUMN", "event_id"),
        source_name="postgresql_live",
        connect_timeout_seconds=int(os.environ.get("SOC_DB_CONNECT_TIMEOUT_SECONDS", "10")),
        statement_timeout_seconds=int(os.environ.get("SOC_DB_STATEMENT_TIMEOUT_SECONDS", "30")),
        retry_attempts=int(os.environ.get("SOC_DB_RETRY_ATTEMPTS", "3")),
        retry_delay_seconds=float(os.environ.get("SOC_DB_RETRY_DELAY_SECONDS", "2")),
    )


def initial_checkpoint_from_env() -> IncrementalCursor | None:
    timestamp = os.environ.get("SOC_INITIAL_CHECKPOINT_TIME_UTC", "").strip()
    event_id = os.environ.get("SOC_INITIAL_CHECKPOINT_EVENT_ID", "").strip()
    if bool(timestamp) != bool(event_id):
        raise RuntimeError("El checkpoint inicial requiere tiempo e identificador conjuntamente")
    return IncrementalCursor(timestamp, event_id) if timestamp else None


def _recent_events(
    store: AlertStore,
    source_name: str,
    latest_cursor: IncrementalCursor,
    operational_config: dict,
    detection_config: dict,
) -> list[Event]:
    latest = datetime.fromisoformat(latest_cursor.timestamp_utc).astimezone(UTC)
    lookback = int(operational_config["detection_lookback_minutes"])
    since_utc = (latest - timedelta(minutes=lookback)).isoformat()
    exclusions = load_exclusions(Path(operational_config["exclusions_file"]))
    events = []
    for row in store.recent_consistent_events(since_utc, source_name):
        event = event_from_row(row, detection_config["timezone"])
        if event is None:
            continue
        reason = exclusion_reason(event, exclusions)
        if reason:
            store.record_suppression(
                reason,
                source_event_id=event.source_event_id,
                entity_key=AlertStore._entity_key(event.__dict__),
            )
            continue
        events.append(event)
    return events


def _persist_alerts(
    alerts: list[dict],
    store: AlertStore,
    source_name: str,
    detection_config: dict,
) -> list[dict]:
    created_alerts = []
    for alert in alerts:
        created, _ = store.insert_alert(
            alert,
            cooldown_for_alert(alert, detection_config),
            source_name=source_name,
        )
        if created:
            created_alerts.append(alert)
    return created_alerts


def _deliver_alerts(
    alerts: list[dict],
    store: AlertStore,
    provider: NotificationProvider,
    operational_config: dict,
) -> int:
    policy = operational_config["notification_policy"]
    immediate = set(policy["immediate_severities"])
    maximum = int(policy["maximum_notifications_per_run"])
    attempts = int(policy["maximum_delivery_attempts"])
    delivered = 0
    for alert in alerts:
        if alert["severity"] not in immediate:
            store.record_suppression(
                "notification_deferred_by_severity_policy",
                rule_id=alert["rule_id"],
                entity_key=AlertStore._entity_key(alert),
                details={"severity": alert["severity"]},
            )
            continue
        if delivered >= maximum:
            store.record_suppression(
                "notification_run_limit",
                rule_id=alert["rule_id"],
                entity_key=AlertStore._entity_key(alert),
            )
            continue
        deliver_once(store, provider, alert, attempts)
        delivered += 1
    return delivered


def run_monitor_cycle(
    *,
    source,
    store: AlertStore,
    secret: bytes,
    normalization_config: NormalizationConfig,
    detection_config: dict,
    operational_config: dict,
    provider: NotificationProvider,
) -> dict:
    run_id = store.start_run(source.source_name)
    fetched = inserted = 0
    created_alerts: list[dict] = []
    try:
        stored = store.get_checkpoint(source.source_name)
        checkpoint = IncrementalCursor(*stored) if stored else initial_checkpoint_from_env()
        records = source.fetch_after(checkpoint, int(operational_config["batch_size"]))
        fetched = len(records)
        for source_record in records:
            normalized = normalize_record(
                source_record.values, secret, normalization_config.minimum_year
            )
            is_valid = not rejection_reasons(normalized, normalization_config)
            inserted += store.insert_event(
                normalized,
                source_record.cursor.timestamp_utc,
                source_record.cursor.event_id,
                is_valid,
                source_name=source.source_name,
            )

        if records:
            last_cursor = records[-1].cursor
            events = _recent_events(
                store,
                source.source_name,
                last_cursor,
                operational_config,
                detection_config,
            )
            baseline = load_baseline_context(Path(operational_config["baseline_dir"]))
            created_alerts = _persist_alerts(
                detect_alerts(events, detection_config, baseline),
                store,
                source.source_name,
                detection_config,
            )
            store.save_checkpoint(
                source.source_name, last_cursor.timestamp_utc, last_cursor.event_id
            )

        delivered = _deliver_alerts(created_alerts, store, provider, operational_config)
        store.finish_run(
            run_id,
            "completed",
            fetched_count=fetched,
            inserted_event_count=inserted,
            alert_count=len(created_alerts),
        )
        return {
            "source": source.source_name,
            "fetched": fetched,
            "inserted_events": inserted,
            "created_alerts": len(created_alerts),
            "notifications_processed": delivered,
            "checkpoint": (
                {
                    "time_utc": records[-1].cursor.timestamp_utc,
                    "event_id": records[-1].cursor.event_id,
                }
                if records
                else None
            ),
        }
    except Exception as error:
        LOGGER.exception("La ejecución incremental falló sin exponer credenciales")
        store.finish_run(
            run_id,
            "failed",
            fetched_count=fetched,
            inserted_event_count=inserted,
            alert_count=len(created_alerts),
            error_code=type(error).__name__,
        )
        raise
