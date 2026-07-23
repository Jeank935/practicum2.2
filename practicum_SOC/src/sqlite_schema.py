"""Esquema y migraciones idempotentes del almacenamiento local."""

from __future__ import annotations

import sqlite3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS checkpoints (
    source_name TEXT PRIMARY KEY,
    cursor_time_utc TEXT NOT NULL,
    cursor_event_id TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS normalized_events (
    source_event_id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL DEFAULT 'legacy',
    record_id TEXT,
    event_time_utc TEXT,
    event_class TEXT NOT NULL,
    event_type_id TEXT,
    event_name TEXT,
    user_key TEXT,
    client_ip_key TEXT,
    relying_party TEXT,
    event_count INTEGER NOT NULL,
    quality_flags TEXT,
    is_consistent INTEGER NOT NULL,
    source_cursor_time_utc TEXT NOT NULL,
    source_cursor_event_id TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL DEFAULT 'legacy',
    rule_id TEXT NOT NULL,
    rule_name TEXT NOT NULL,
    severity TEXT NOT NULL,
    risk_score INTEGER NOT NULL,
    risk_factors_json TEXT NOT NULL,
    first_seen_local TEXT NOT NULL,
    last_seen_local TEXT NOT NULL,
    user_key TEXT,
    client_ip_key TEXT,
    event_types TEXT,
    event_count INTEGER NOT NULL,
    success_count INTEGER NOT NULL,
    failure_count INTEGER NOT NULL,
    lockout_count INTEGER NOT NULL,
    distinct_users INTEGER NOT NULL,
    distinct_client_ips INTEGER NOT NULL,
    relying_parties TEXT,
    evidence_event_ids TEXT,
    description TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    requires_human_review INTEGER NOT NULL DEFAULT 1,
    generated_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    delivery_channel TEXT NOT NULL DEFAULT 'none',
    delivery_status TEXT NOT NULL DEFAULT 'pending',
    investigation_status TEXT NOT NULL DEFAULT 'new'
);

CREATE TABLE IF NOT EXISTS alert_status_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT NOT NULL,
    changed_at_utc TEXT NOT NULL,
    note TEXT,
    FOREIGN KEY(alert_id) REFERENCES alerts(alert_id)
);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    attempted_at_utc TEXT NOT NULL,
    outcome TEXT NOT NULL,
    error_code TEXT,
    UNIQUE(alert_id, channel, attempt_number),
    FOREIGN KEY(alert_id) REFERENCES alerts(alert_id)
);

CREATE TABLE IF NOT EXISTS suppression_log (
    suppression_id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT,
    entity_key TEXT,
    source_event_id TEXT,
    reason TEXT NOT NULL,
    occurred_at_utc TEXT NOT NULL,
    details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS service_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    finished_at_utc TEXT,
    status TEXT NOT NULL,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    inserted_event_count INTEGER NOT NULL DEFAULT 0,
    alert_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT
);
"""


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if column not in _columns(connection, table):
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_schema(connection: sqlite3.Connection, now_utc: str) -> None:
    connection.executescript(SCHEMA_SQL)
    _add_column(
        connection,
        "normalized_events",
        "source_name",
        "TEXT NOT NULL DEFAULT 'legacy'",
    )
    _add_column(connection, "alerts", "source_name", "TEXT NOT NULL DEFAULT 'legacy'")
    _add_column(connection, "alerts", "updated_at_utc", "TEXT")
    for index_name in (
        "idx_events_time",
        "idx_alerts_rule_entity_time",
        "idx_alerts_status",
        "idx_events_source_time",
        "idx_alerts_source_time",
    ):
        connection.execute(f"DROP INDEX IF EXISTS {index_name}")
    connection.executescript(
        """
        CREATE INDEX idx_events_source_time
            ON normalized_events(source_name, event_time_utc);
        CREATE INDEX idx_alerts_source_time
            ON alerts(source_name, generated_at_utc);
        CREATE INDEX idx_alerts_rule_entity_time
            ON alerts(source_name, rule_id, user_key, client_ip_key, last_seen_local);
        CREATE INDEX idx_alerts_status
            ON alerts(source_name, investigation_status, severity);
        """
    )
    connection.execute(
        "UPDATE alerts SET updated_at_utc = COALESCE(updated_at_utc, generated_at_utc, ?)",
        (now_utc,),
    )
    connection.execute(
        "UPDATE alerts SET investigation_status = 'investigating' "
        "WHERE investigation_status = 'acknowledged'"
    )
    connection.commit()
