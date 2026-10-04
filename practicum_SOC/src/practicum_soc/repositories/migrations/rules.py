"""Tablas propias para versiones de reglas y pruebas históricas."""

RULE_SCHEMA = """
CREATE TABLE IF NOT EXISTS rule_config_versions (
    version_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('draft', 'published')),
    parent_version_id TEXT,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_name TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_versions_created
    ON rule_config_versions(created_at_utc DESC);
CREATE TABLE IF NOT EXISTS rule_config_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    active_version_id TEXT NOT NULL REFERENCES rule_config_versions(version_id)
);
CREATE TABLE IF NOT EXISTS rule_config_previews (
    preview_id TEXT PRIMARY KEY,
    draft_version_id TEXT NOT NULL REFERENCES rule_config_versions(version_id),
    draft_hash TEXT NOT NULL,
    active_version_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    from_utc TEXT NOT NULL,
    to_utc TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_previews_draft
    ON rule_config_previews(draft_version_id, created_at_utc DESC);
CREATE TABLE IF NOT EXISTS rule_config_history (
    history_id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    version_id TEXT NOT NULL,
    previous_version_id TEXT,
    actor_id TEXT NOT NULL,
    actor_name TEXT NOT NULL,
    justification TEXT NOT NULL,
    occurred_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_history_time
    ON rule_config_history(occurred_at_utc DESC);
"""


def install_rules(connection, *, postgres: bool = False) -> None:
    if postgres:
        connection.execute(RULE_SCHEMA)
        connection.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS rule_version_id TEXT")
        return
    marker = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rule_config_versions'"
    ).fetchone()
    if marker:
        return
    connection.executescript(RULE_SCHEMA)
    connection.execute("ALTER TABLE alerts ADD COLUMN rule_version_id TEXT")
    connection.commit()
