"""Migración acotada de fechas/indexación y revisiones para consultas paginadas."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from browsing_config import SETTINGS


def canonical_time(value: str) -> str:
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=ZoneInfo(SETTINGS.timezone))
    return instant.astimezone(UTC).isoformat(timespec="microseconds")


def install_browsing(connection, *, postgres=False):
    def execute(query, params=()):
        return connection.execute(query.replace("?", "%s") if postgres else query, params)

    execute("CREATE TABLE IF NOT EXISTS browsing_migrations (version INTEGER PRIMARY KEY)")
    if execute("SELECT version FROM browsing_migrations WHERE version = 1").fetchone():
        return
    if postgres:
        execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS occurred_at_utc TEXT")
    elif "occurred_at_utc" not in {
        row[1] for row in execute("PRAGMA table_info(alerts)").fetchall()
    }:
        execute("ALTER TABLE alerts ADD COLUMN occurred_at_utc TEXT")
    execute(
        "CREATE TABLE IF NOT EXISTS alert_services ("
        "alert_id TEXT NOT NULL REFERENCES alerts(alert_id) ON DELETE CASCADE, "
        "service TEXT NOT NULL, PRIMARY KEY(alert_id, service))"
    )
    execute("CREATE INDEX IF NOT EXISTS idx_alert_service ON alert_services(service, alert_id)")
    while True:
        rows = execute(
            "SELECT alert_id, first_seen_local, relying_parties FROM alerts "
            "WHERE occurred_at_utc IS NULL LIMIT ?",
            (SETTINGS.migration_batch_size,),
        ).fetchall()
        if not rows:
            break
        for row in rows:
            execute(
                "UPDATE alerts SET occurred_at_utc = ? WHERE alert_id = ?",
                (canonical_time(row[1]), row[0]),
            )
            for service in set(filter(None, (row[2] or "").split(";"))):
                execute(
                    "INSERT INTO alert_services VALUES (?, ?) ON CONFLICT DO NOTHING",
                    (row[0], service),
                )
    for name, fields in (
        (
            "idx_alert_browse_risk",
            "source_name, risk_score DESC, occurred_at_utc DESC, alert_id DESC",
        ),
        ("idx_alert_browse_time", "source_name, occurred_at_utc DESC, alert_id DESC"),
        ("idx_event_service_time", "source_name, relying_party, event_time_utc"),
    ):
        execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON "
            f"{'normalized_events' if name.startswith('idx_event') else 'alerts'}({fields})"
        )
    execute(
        "CREATE TABLE IF NOT EXISTS source_revisions ("
        "source_name TEXT PRIMARY KEY, events_revision BIGINT NOT NULL DEFAULT 0, "
        "alerts_revision BIGINT NOT NULL DEFAULT 0)"
    )
    for table, column in (("normalized_events", "events_revision"), ("alerts", "alerts_revision")):
        execute(
            f"INSERT INTO source_revisions(source_name, {column}) "
            f"SELECT source_name, COUNT(*) FROM {table} GROUP BY source_name "
            f"ON CONFLICT(source_name) DO UPDATE SET {column} = excluded.{column}"
        )
        for operation in ("INSERT", "UPDATE", "DELETE"):
            ref = "OLD" if operation == "DELETE" else "NEW"
            increment = (
                f"INSERT INTO source_revisions(source_name, {column}) VALUES ({ref}.source_name, 1) "
                f"ON CONFLICT(source_name) DO UPDATE SET {column} = source_revisions.{column} + 1;"
            )
            name = f"browse_{table}_{operation.lower()}"
            if postgres:
                execute(
                    f"CREATE OR REPLACE FUNCTION {name}_fn() RETURNS trigger LANGUAGE plpgsql AS $$ "
                    f"BEGIN {increment} RETURN {ref}; END; $$"
                )
                execute(
                    f"CREATE OR REPLACE TRIGGER {name} AFTER {operation} ON {table} "
                    f"FOR EACH ROW EXECUTE FUNCTION {name}_fn()"
                )
            else:
                execute(
                    f"CREATE TRIGGER IF NOT EXISTS {name} AFTER {operation} ON {table} "
                    f"BEGIN {increment} END"
                )
    execute("INSERT INTO browsing_migrations VALUES (1)")
