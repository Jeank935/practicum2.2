"""Repositorio SQLite para eventos, alertas, estados y entregas del SOC."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlite_schema import ensure_schema

ALERT_STATUSES = {
    "new",
    "notified",
    "investigating",
    "resolved",
    "false_positive",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class AlertStore:
    """Persistencia idempotente independiente de la fuente institucional."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        ensure_schema(self.connection, utc_now())

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> AlertStore:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection:
            yield self.connection

    def get_checkpoint(self, source_name: str) -> tuple[str, str] | None:
        row = self.connection.execute(
            "SELECT cursor_time_utc, cursor_event_id FROM checkpoints WHERE source_name = ?",
            (source_name,),
        ).fetchone()
        if row is None:
            return None
        return row["cursor_time_utc"], row["cursor_event_id"]

    def save_checkpoint(self, source_name: str, cursor_time_utc: str, event_id: str) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO checkpoints(source_name, cursor_time_utc, cursor_event_id, updated_at_utc)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_name) DO UPDATE SET
                    cursor_time_utc = excluded.cursor_time_utc,
                    cursor_event_id = excluded.cursor_event_id,
                    updated_at_utc = excluded.updated_at_utc
                """,
                (source_name, cursor_time_utc, event_id, utc_now()),
            )

    def insert_event(
        self,
        event: dict,
        cursor_time_utc: str,
        cursor_event_id: str,
        is_consistent: bool,
        source_name: str = "legacy",
    ) -> bool:
        event_key = str(
            event.get("deduplication_key")
            or event.get("source_event_id")
            or f"record:{event.get('record_id', '')}"
        )
        storage_key = f"{source_name}:{event_key}"
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO normalized_events(
                    source_event_id, source_name, record_id, event_time_utc,
                    event_class, event_type_id, event_name, user_key,
                    client_ip_key, relying_party, event_count, quality_flags,
                    is_consistent, source_cursor_time_utc,
                    source_cursor_event_id, ingested_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    storage_key,
                    source_name,
                    event.get("record_id", ""),
                    event.get("event_time_utc", ""),
                    event.get("event_class", "other"),
                    event.get("event_type_id", ""),
                    event.get("event_name", ""),
                    event.get("user_key", ""),
                    event.get("client_ip_key", ""),
                    event.get("relying_party", ""),
                    int(event.get("event_count", 1)),
                    event.get("quality_flags", ""),
                    1 if is_consistent else 0,
                    cursor_time_utc,
                    cursor_event_id,
                    utc_now(),
                ),
            )
        return cursor.rowcount == 1

    def recent_consistent_events(
        self, since_utc: str, source_name: str | None = None
    ) -> list[dict]:
        query = """
            SELECT source_event_id, event_time_utc, event_class, user_key,
                   client_ip_key, relying_party, event_count
              FROM normalized_events
             WHERE is_consistent = 1 AND event_time_utc >= ?
        """
        parameters: list[object] = [since_utc]
        if source_name:
            query += " AND source_name = ?"
            parameters.append(source_name)
        query += " ORDER BY event_time_utc, source_cursor_event_id"
        rows = self.connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _entity_key(alert: dict) -> str:
        if alert.get("user_key"):
            return f"user:{alert['user_key']}"
        if alert.get("client_ip_key"):
            return f"ip:{alert['client_ip_key']}"
        return "global"

    def record_suppression(
        self,
        reason: str,
        *,
        rule_id: str = "",
        entity_key: str = "",
        source_event_id: str = "",
        details: dict | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO suppression_log(
                    rule_id, entity_key, source_event_id, reason,
                    occurred_at_utc, details_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    rule_id,
                    entity_key,
                    source_event_id,
                    reason,
                    utc_now(),
                    json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
                ),
            )

    def _cooldown_active(self, alert: dict, cooldown_minutes: int, source_name: str) -> bool:
        if cooldown_minutes <= 0:
            return False
        previous = self.connection.execute(
            """
            SELECT last_seen_local FROM alerts
             WHERE source_name = ? AND rule_id = ?
               AND COALESCE(user_key, '') = ?
               AND COALESCE(client_ip_key, '') = ?
             ORDER BY last_seen_local DESC LIMIT 1
            """,
            (
                source_name,
                alert["rule_id"],
                alert.get("user_key", ""),
                alert.get("client_ip_key", ""),
            ),
        ).fetchone()
        if previous is None:
            return False
        current_time = datetime.fromisoformat(alert["last_seen_local"])
        previous_time = datetime.fromisoformat(previous["last_seen_local"])
        return current_time - previous_time < timedelta(minutes=cooldown_minutes)

    def insert_alert(
        self,
        alert: dict,
        cooldown_minutes: int = 0,
        source_name: str = "legacy",
    ) -> tuple[bool, str]:
        entity_key = self._entity_key(alert)
        existing = self.get_alert(alert["alert_id"])
        if existing is not None and existing["source_name"] != source_name:
            source_fingerprint = f"{source_name}|{alert['alert_id']}"
            alert["alert_id"] = (
                "alt_" + hashlib.sha256(source_fingerprint.encode("utf-8")).hexdigest()[:20]
            )
            existing = self.get_alert(alert["alert_id"])
        if existing is not None:
            self.record_suppression(
                "duplicate_alert",
                rule_id=alert["rule_id"],
                entity_key=entity_key,
                details={"alert_id": alert["alert_id"], "source_name": source_name},
            )
            return False, "duplicate_alert"
        if self._cooldown_active(alert, cooldown_minutes, source_name):
            self.record_suppression(
                "persistent_cooldown",
                rule_id=alert["rule_id"],
                entity_key=entity_key,
                details={"cooldown_minutes": cooldown_minutes, "source_name": source_name},
            )
            return False, "persistent_cooldown"

        created_at = utc_now()
        values = (
            alert["alert_id"],
            source_name,
            alert["rule_id"],
            alert["rule_name"],
            alert["severity"],
            int(alert.get("risk_score", 0)),
            alert.get("risk_factors", "[]"),
            alert["first_seen_local"],
            alert["last_seen_local"],
            alert.get("user_key", ""),
            alert.get("client_ip_key", ""),
            alert.get("event_types", ""),
            int(alert.get("event_count", 0)),
            int(alert.get("success_count", 0)),
            int(alert.get("failure_count", 0)),
            int(alert.get("lockout_count", 0)),
            int(alert.get("distinct_users", 0)),
            int(alert.get("distinct_client_ips", 0)),
            alert.get("relying_parties", ""),
            alert.get("evidence_event_ids", ""),
            alert["description"],
            alert.get("recommendation", "Revisar la evidencia y validar el contexto."),
            1,
            created_at,
            created_at,
            "none",
            "pending",
            "new",
        )
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO alerts(
                    alert_id, source_name, rule_id, rule_name, severity,
                    risk_score, risk_factors_json, first_seen_local,
                    last_seen_local, user_key, client_ip_key, event_types,
                    event_count, success_count, failure_count, lockout_count,
                    distinct_users, distinct_client_ips, relying_parties,
                    evidence_event_ids, description, recommendation,
                    requires_human_review, generated_at_utc, updated_at_utc,
                    delivery_channel, delivery_status, investigation_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            self.connection.execute(
                """
                INSERT INTO alert_status_history(
                    alert_id, old_status, new_status, changed_at_utc, note
                ) VALUES (?, NULL, 'new', ?, 'Alerta creada por el motor')
                """,
                (alert["alert_id"], created_at),
            )
        return True, "created"

    def get_alert(self, alert_id: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def list_alerts(
        self,
        limit: int = 100,
        *,
        source_name: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        rule_id: str | None = None,
    ) -> list[dict]:
        filters = []
        parameters: list[object] = []
        for column, value in (
            ("source_name", source_name),
            ("severity", severity),
            ("investigation_status", status),
            ("rule_id", rule_id),
        ):
            if value:
                filters.append(f"{column} = ?")
                parameters.append(value)
        query = "SELECT * FROM alerts"
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY risk_score DESC, generated_at_utc DESC LIMIT ?"
        parameters.append(max(1, min(limit, 5000)))
        rows = self.connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def alert_counts(self, source_name: str | None = None) -> dict:
        where = " WHERE source_name = ?" if source_name else ""
        parameters = (source_name,) if source_name else ()
        alerts = self.connection.execute(
            f"SELECT COUNT(*) AS count FROM alerts{where}", parameters
        ).fetchone()["count"]
        severity_rows = self.connection.execute(
            f"SELECT severity, COUNT(*) AS count FROM alerts{where} GROUP BY severity",
            parameters,
        ).fetchall()
        status_rows = self.connection.execute(
            f"SELECT investigation_status, COUNT(*) AS count FROM alerts{where} "
            "GROUP BY investigation_status",
            parameters,
        ).fetchall()
        rule_rows = self.connection.execute(
            f"SELECT rule_id, COUNT(*) AS count FROM alerts{where} GROUP BY rule_id",
            parameters,
        ).fetchall()
        return {
            "total": int(alerts),
            "by_severity": {row["severity"]: row["count"] for row in severity_rows},
            "by_status": {row["investigation_status"]: row["count"] for row in status_rows},
            "by_rule": {row["rule_id"]: row["count"] for row in rule_rows},
        }

    def alert_history(self, alert_id: str) -> list[dict]:
        rows = self.connection.execute(
            """
            SELECT old_status, new_status, changed_at_utc, note
              FROM alert_status_history WHERE alert_id = ?
             ORDER BY changed_at_utc
            """,
            (alert_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def alert_deliveries(self, alert_id: str) -> list[dict]:
        rows = self.connection.execute(
            """
            SELECT channel, attempt_number, attempted_at_utc, outcome, error_code
              FROM notification_deliveries WHERE alert_id = ?
             ORDER BY attempt_number
            """,
            (alert_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def health_summary(self, source_name: str | None = None) -> dict:
        if source_name:
            last_run = self.connection.execute(
                "SELECT * FROM service_runs WHERE source_name = ? ORDER BY run_id DESC LIMIT 1",
                (source_name,),
            ).fetchone()
        else:
            last_run = self.connection.execute(
                "SELECT * FROM service_runs ORDER BY run_id DESC LIMIT 1"
            ).fetchone()
        counts = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM normalized_events) AS events,
                (SELECT COUNT(*) FROM alerts) AS alerts,
                (SELECT COUNT(*) FROM checkpoints) AS checkpoints,
                (SELECT COUNT(*) FROM suppression_log) AS suppressions
            """
        ).fetchone()
        return {
            "status": (
                "healthy"
                if last_run is not None and last_run["status"] == "completed"
                else "no_successful_run"
            ),
            "active_source": last_run["source_name"] if last_run else "none",
            "last_run": dict(last_run) if last_run is not None else None,
            "counts": dict(counts),
        }

    def update_alert_status(self, alert_id: str, new_status: str, note: str = "") -> None:
        if new_status not in ALERT_STATUSES:
            raise ValueError(f"Estado de alerta no permitido: {new_status}")
        current = self.get_alert(alert_id)
        if current is None:
            raise KeyError(f"No existe la alerta: {alert_id}")
        old_status = current["investigation_status"]
        if old_status == new_status:
            return
        changed_at = utc_now()
        with self.connection:
            self.connection.execute(
                """
                UPDATE alerts SET investigation_status = ?, updated_at_utc = ?
                 WHERE alert_id = ?
                """,
                (new_status, changed_at, alert_id),
            )
            self.connection.execute(
                """
                INSERT INTO alert_status_history(
                    alert_id, old_status, new_status, changed_at_utc, note
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (alert_id, old_status, new_status, changed_at, note),
            )

    def delivery_succeeded(self, alert_id: str, channel: str) -> bool:
        row = self.connection.execute(
            """
            SELECT 1 FROM notification_deliveries
             WHERE alert_id = ? AND channel = ? AND outcome IN ('sent', 'dry_run')
             LIMIT 1
            """,
            (alert_id, channel),
        ).fetchone()
        return row is not None

    def delivery_attempt_count(self, alert_id: str, channel: str) -> int:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS count FROM notification_deliveries
             WHERE alert_id = ? AND channel = ?
            """,
            (alert_id, channel),
        ).fetchone()
        return int(row["count"])

    def record_delivery(
        self,
        alert_id: str,
        channel: str,
        outcome: str,
        error_code: str = "",
    ) -> None:
        attempt = self.delivery_attempt_count(alert_id, channel) + 1
        changed_at = utc_now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO notification_deliveries(
                    alert_id, channel, attempt_number, attempted_at_utc,
                    outcome, error_code
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (alert_id, channel, attempt, changed_at, outcome, error_code),
            )
            self.connection.execute(
                """
                UPDATE alerts SET delivery_channel = ?, delivery_status = ?,
                                  updated_at_utc = ?
                 WHERE alert_id = ?
                """,
                (channel, outcome, changed_at, alert_id),
            )

    def start_run(self, source_name: str) -> int:
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO service_runs(source_name, started_at_utc, status)
                VALUES (?, ?, 'running')
                """,
                (source_name, utc_now()),
            )
        return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        status: str,
        *,
        fetched_count: int = 0,
        inserted_event_count: int = 0,
        alert_count: int = 0,
        error_code: str = "",
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE service_runs
                   SET finished_at_utc = ?, status = ?, fetched_count = ?,
                       inserted_event_count = ?, alert_count = ?, error_code = ?
                 WHERE run_id = ?
                """,
                (
                    utc_now(),
                    status,
                    fetched_count,
                    inserted_event_count,
                    alert_count,
                    error_code,
                    run_id,
                ),
            )
