"""Consultas SQL acotadas de alertas y agregados, compartidas por SQLite y PostgreSQL."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from browsing_config import SETTINGS
from page_cursor import keyset_page

ALERT_COLUMNS = (
    "alert_id, rule_id, rule_name, severity, risk_score, user_key, client_ip_key, "
    "event_count, investigation_status, first_seen_local, occurred_at_utc, "
    "delivery_channel, delivery_status, relying_parties"
)


def date_bounds(query):
    zone = ZoneInfo(SETTINGS.timezone)
    start = (
        datetime.combine(query.date_from, time.min, zone).astimezone(UTC)
        if query.date_from
        else None
    )
    end = (
        datetime.combine(query.date_to + timedelta(days=1), time.min, zone).astimezone(UTC)
        if query.date_to
        else None
    )
    return start, end


class BrowseRepository:
    def __init__(self, store):
        self.db = store.connection

    def source(self):
        row = self.db.execute(
            "SELECT source_name FROM service_runs ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        return row["source_name"] if row else "csv_demo_mvp"

    def revision(self, source):
        row = self.db.execute(
            "SELECT events_revision, alerts_revision FROM source_revisions WHERE source_name = ?",
            (source,),
        ).fetchone()
        return (
            f"{source}:{row['events_revision']}:{row['alerts_revision']}"
            if row
            else source + ":0:0"
        )

    def alerts(self, query, source, codec):
        sql, params = f"SELECT {ALERT_COLUMNS} FROM alerts WHERE source_name = ?", [source]
        for column, value in (
            ("severity", query.severity),
            ("investigation_status", query.status),
            ("rule_id", query.rule_id),
        ):
            if value:
                sql += f" AND {column} = ?"
                params.append(value)
        start, end = date_bounds(query)
        for operator, value in ((">=", start), ("<", end)):
            if value:
                sql += f" AND occurred_at_utc {operator} ?"
                params.append(value.isoformat(timespec="microseconds"))
        if query.service:
            sql += " AND EXISTS (SELECT 1 FROM alert_services s WHERE s.alert_id = alerts.alert_id AND s.service = ?)"
            params.append(query.service)
        keys = (
            ("risk_score", "occurred_at_utc", "alert_id")
            if query.sort == "risk"
            else ("occurred_at_utc", "alert_id")
        )
        return keyset_page(self.db, sql, params, keys, query.sort != "oldest", query, codec)

    def event_scope(self, query, source, sensitive_ids):
        sql = "source_name = ? AND is_consistent = 1 AND TRIM(COALESCE(relying_party, '')) <> ''"
        params = [source]
        latest = self.db.execute(
            "SELECT MAX(event_time_utc) AS latest FROM normalized_events WHERE source_name = ? AND is_consistent = 1",
            (source,),
        ).fetchone()["latest"]
        start, end = date_bounds(query)
        if query.window_days and latest:
            window = datetime.fromisoformat(latest) - timedelta(days=query.window_days)
            start = max(start, window) if start else window
        for operator, value in ((">=", start), ("<", end)):
            if value:
                sql += f" AND event_time_utc {operator} ?"
                params.append(value.isoformat())
        if query.service:
            sql += " AND relying_party = ?"
            params.append(query.service)
        if query.sensitive:
            if sensitive_ids:
                sql += " AND relying_party IN (" + ", ".join("?" for _ in sensitive_ids) + ")"
                params.extend(sensitive_ids)
            else:
                sql += " AND 1 = 0"
        return sql, params, latest

    def services(self, query, scope, params, codec):
        aggregate = (
            "SELECT relying_party, SUM(event_count) AS total_events, "
            "SUM(CASE WHEN event_class = 'success' THEN event_count ELSE 0 END) AS success_count, "
            "SUM(CASE WHEN event_class = 'failure' THEN event_count ELSE 0 END) AS failure_count, "
            "SUM(CASE WHEN event_class = 'lockout' THEN event_count ELSE 0 END) AS lockout_count, "
            "COUNT(DISTINCT NULLIF(user_key, '')) AS distinct_users, "
            "COUNT(DISTINCT NULLIF(client_ip_key, '')) AS distinct_client_ips, "
            "MIN(event_time_utc) AS first_seen_utc, MAX(event_time_utc) AS last_seen_utc "
            f"FROM normalized_events WHERE {scope} GROUP BY relying_party"
        )
        keys = {
            "volume": ("total_events", "relying_party"),
            "failures": ("failure_count", "relying_party"),
            "recent": ("last_seen_utc", "relying_party"),
            "service": ("relying_party",),
        }[query.sort]
        return keyset_page(
            self.db,
            f"WITH grouped AS ({aggregate}) SELECT * FROM grouped WHERE 1 = 1",
            params,
            keys,
            query.sort != "service",
            query,
            codec,
        )

    def summary(self, scope, params):
        row = self.db.execute(
            "SELECT MAX(event_time_utc) AS last_seen_utc, SUM(event_count) AS total_events, COUNT(DISTINCT relying_party) AS distinct_services, "
            "COUNT(DISTINCT NULLIF(user_key, '')) AS distinct_users, "
            "SUM(CASE WHEN event_class = 'success' THEN event_count ELSE 0 END) AS success_count, "
            "SUM(CASE WHEN event_class = 'failure' THEN event_count ELSE 0 END) AS failure_count, "
            "SUM(CASE WHEN event_class = 'lockout' THEN event_count ELSE 0 END) AS lockout_count "
            f"FROM normalized_events WHERE {scope}",
            params,
        ).fetchone()
        return {
            key: value if key == "last_seen_utc" else int(value or 0)
            for key, value in dict(row).items()
        }

    def open_alerts(self, source, identifiers):
        if not identifiers:
            return {}
        rows = self.db.execute(
            "WITH ranked AS (SELECT s.service, a.alert_id, COUNT(*) OVER (PARTITION BY s.service) AS count, "
            "ROW_NUMBER() OVER (PARTITION BY s.service ORDER BY a.updated_at_utc DESC, a.alert_id DESC) AS position "
            "FROM alert_services s JOIN alerts a ON a.alert_id = s.alert_id "
            "WHERE a.source_name = ? AND a.investigation_status IN ('new', 'notified', 'investigating') "
            "AND s.service IN (" + ",".join("?" for _ in identifiers) + ")) "
            "SELECT service, count, alert_id FROM ranked WHERE position = 1",
            (source, *identifiers),
        ).fetchall()
        return {
            row["service"]: {"count": int(row["count"]), "latest_alert_id": row["alert_id"]}
            for row in rows
        }
