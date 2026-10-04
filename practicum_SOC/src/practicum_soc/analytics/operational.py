"""Indicadores técnicos y de piloto a partir del almacenamiento propio del SOC."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median


def _seconds_since(value: str | None, now: datetime) -> int | None:
    if not value:
        return None
    return max(0, int((now - datetime.fromisoformat(value)).total_seconds()))


def _database_bytes(store) -> int:
    if hasattr(store, "path"):
        path = Path(store.path)
        return sum(
            item.stat().st_size for item in (path, Path(str(path) + "-wal")) if item.is_file()
        )
    return int(
        store.connection.execute("SELECT pg_database_size(current_database()) AS size").fetchone()[
            "size"
        ]
    )


def technical_metrics(store, source: str, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    run = store.connection.execute(
        "SELECT source_name,started_at_utc,finished_at_utc,status,fetched_count,"
        "inserted_event_count,alert_count,error_code FROM service_runs "
        "WHERE source_name=? ORDER BY run_id DESC LIMIT 1",
        (source,),
    ).fetchone()
    errors = store.connection.execute(
        "SELECT COUNT(*) AS total FROM service_runs "
        "WHERE source_name=? AND status='failed' AND started_at_utc>=?",
        (source, (now - timedelta(hours=24)).isoformat()),
    ).fetchone()
    checkpoint = store.connection.execute(
        "SELECT cursor_time_utc FROM checkpoints WHERE source_name=?", (source,)
    ).fetchone()
    latest_event = store.connection.execute(
        "SELECT event_time_utc,ingested_at_utc FROM normalized_events "
        "WHERE source_name=? AND is_consistent=1 "
        "AND event_time_utc IS NOT NULL AND event_time_utc<>'' "
        "ORDER BY ingested_at_utc DESC LIMIT 1",
        (source,),
    ).fetchone()
    duration = None
    if run and run["finished_at_utc"]:
        duration = round(
            (
                datetime.fromisoformat(run["finished_at_utc"])
                - datetime.fromisoformat(run["started_at_utc"])
            ).total_seconds(),
            3,
        )
    return {
        "source": source,
        "observed_at_utc": now.isoformat(),
        "last_run": dict(run) if run else None,
        "last_run_duration_seconds": duration,
        "last_run_age_seconds": _seconds_since(run["started_at_utc"], now) if run else None,
        "failed_runs_24h": int(errors["total"]),
        "checkpoint_age_seconds": _seconds_since(checkpoint["cursor_time_utc"], now)
        if checkpoint
        else None,
        "event_to_soc_seconds": max(
            0,
            int(
                (
                    datetime.fromisoformat(latest_event["ingested_at_utc"])
                    - datetime.fromisoformat(latest_event["event_time_utc"])
                ).total_seconds()
            ),
        )
        if latest_event
        else None,
        "database_bytes": _database_bytes(store),
    }


def pilot_metrics(
    store, source: str, *, now: datetime | None = None, days: int = 30, limit: int = 500
) -> dict:
    if not 1 <= days <= 90 or not 1 <= limit <= 1000:
        raise ValueError("Periodo o tamaño de muestra no permitido")
    now = now or datetime.now(UTC)
    rows = store.connection.execute(
        "SELECT a.alert_id,a.generated_at_utc,a.investigation_status,"
        "MIN(h.changed_at_utc) AS first_action_utc,"
        "MAX(CASE WHEN h.new_status IN ('resolved','false_positive') "
        "THEN h.changed_at_utc END) AS closed_at_utc "
        "FROM (SELECT alert_id,generated_at_utc,investigation_status FROM alerts "
        "WHERE source_name=? AND generated_at_utc>=? "
        "ORDER BY generated_at_utc DESC LIMIT ?) a "
        "LEFT JOIN alert_status_history h ON h.alert_id=a.alert_id AND h.actor_id<>'system' "
        "GROUP BY a.alert_id,a.generated_at_utc,a.investigation_status",
        (source, (now - timedelta(days=days)).isoformat(), limit + 1),
    ).fetchall()
    sampled = rows[:limit]
    closed = sum(row["investigation_status"] in {"resolved", "false_positive"} for row in sampled)
    false_positives = sum(row["investigation_status"] == "false_positive" for row in sampled)
    delays = [
        max(
            0,
            (
                datetime.fromisoformat(row["first_action_utc"])
                - datetime.fromisoformat(row["generated_at_utc"])
            ).total_seconds(),
        )
        for row in sampled
        if row["first_action_utc"]
    ]
    closures = [
        max(
            0,
            (
                datetime.fromisoformat(row["closed_at_utc"])
                - datetime.fromisoformat(row["generated_at_utc"])
            ).total_seconds(),
        )
        for row in sampled
        if row["closed_at_utc"]
    ]
    return {
        "source": source,
        "window_days": days,
        "sampled_cases": len(sampled),
        "sample_truncated": len(rows) > limit,
        "closed_cases": closed,
        "false_positive_cases": false_positives,
        "false_positive_rate_percent": round(false_positives / closed * 100, 2) if closed else None,
        "cases_with_analyst_action": len(delays),
        "median_first_action_minutes": round(median(delays) / 60, 2) if delays else None,
        "median_closure_minutes": round(median(closures) / 60, 2) if closures else None,
    }
