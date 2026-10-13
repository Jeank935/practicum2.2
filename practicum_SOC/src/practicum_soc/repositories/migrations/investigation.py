"""Migración aditiva del SOC propio; nunca opera sobre la fuente institucional."""

INVESTIGATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS investigation_migrations (version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS investigation_private_ips (
    source_event_id TEXT PRIMARY KEY REFERENCES normalized_events(source_event_id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    client_ip_key TEXT NOT NULL,
    encrypted_ip TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_private_ip_entity
    ON investigation_private_ips(source_name, client_ip_key, created_at_utc DESC);
CREATE TABLE IF NOT EXISTS alert_investigations (
    analysis_id TEXT PRIMARY KEY,
    alert_id TEXT NOT NULL REFERENCES alerts(alert_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK(status IN ('pending','in_progress','completed','failed')),
    requested_by TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    started_at_utc TEXT,
    finished_at_utc TEXT,
    lease_until BIGINT,
    policy_json TEXT NOT NULL,
    result_ciphertext TEXT,
    error_code TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_investigation_active_alert
    ON alert_investigations(alert_id) WHERE status IN ('pending','in_progress');
CREATE INDEX IF NOT EXISTS idx_investigation_queue
    ON alert_investigations(status, created_at_utc);
CREATE INDEX IF NOT EXISTS idx_investigation_recent
    ON alert_investigations(alert_id, created_at_utc DESC);
CREATE INDEX IF NOT EXISTS idx_investigation_events_user
    ON normalized_events(source_name, user_key, event_time_utc);
CREATE INDEX IF NOT EXISTS idx_investigation_events_ip
    ON normalized_events(source_name, client_ip_key, event_time_utc);
CREATE TABLE IF NOT EXISTS investigation_guard (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision BIGINT NOT NULL
);
INSERT INTO investigation_guard VALUES (1,0) ON CONFLICT DO NOTHING;
INSERT INTO investigation_migrations VALUES (1) ON CONFLICT DO NOTHING;
"""


def install_investigation(connection, *, postgres=False):
    if postgres:
        connection.execute(INVESTIGATION_SCHEMA)
        return
    marker = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='investigation_migrations'"
    ).fetchone()
    if (
        marker
        and connection.execute("SELECT 1 FROM investigation_migrations WHERE version=1").fetchone()
    ):
        return
    connection.executescript(INVESTIGATION_SCHEMA)
