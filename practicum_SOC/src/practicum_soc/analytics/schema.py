"""Instala el mart analítico exclusivamente en PostgreSQL del SOC."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from practicum_soc.core.paths import PROJECT_ROOT

ROOT = PROJECT_ROOT
SQL_ROOT = Path(__file__).resolve().parent / "queries"
ANALYTIC_VIEWS = (
    "soc_service_analytics",
    "soc_service_hour_dashboard",
    "soc_service_day_dashboard",
    "soc_analytics_policy_view",
    "soc_analytics_alerts",
    "soc_monitor_health",
)


def install_analytics(connection):
    baseline = json.loads((ROOT / "config/baseline.json").read_text(encoding="utf-8"))
    policy = json.loads((ROOT / "config/analytics.json").read_text(encoding="utf-8"))
    zone = ZoneInfo(baseline["timezone"])
    start = datetime.fromisoformat(baseline["training_start_local"]).replace(tzinfo=zone)
    end = datetime.fromisoformat(baseline["training_end_local"]).replace(tzinfo=zone) + timedelta(
        days=1
    )
    if end <= start or policy["max_range_days"] < 1 or policy["minimum_baseline_samples"] < 1:
        raise ValueError("Política analítica inválida")
    connection.execute((SQL_ROOT / "analytics_tables.sql").read_text(encoding="utf-8"))
    old_zone = connection.execute(
        "SELECT timezone FROM soc_analytics_policy WHERE singleton = 1"
    ).fetchone()
    if old_zone and old_zone[0] != baseline["timezone"]:
        raise ValueError("Cambiar la zona del mart requiere una migración explícita")
    connection.execute(
        "INSERT INTO soc_analytics_policy VALUES (1, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT(singleton) DO UPDATE SET training_start=excluded.training_start, "
        "training_end=excluded.training_end, max_range_days=excluded.max_range_days, "
        "minimum_samples=excluded.minimum_samples, minimum_day_events=excluded.minimum_day_events, "
        "minimum_day_hours=excluded.minimum_day_hours",
        (
            baseline["timezone"],
            start,
            end,
            policy["max_range_days"],
            policy["minimum_baseline_samples"],
            baseline["minimum_events_per_day"],
            baseline["minimum_active_hours_per_day"],
        ),
    )
    # Una sola reconstrucción inicial bajo bloqueo de escritura, consistente con la ingesta.
    if not connection.execute(
        "SELECT version FROM soc_analytics_migrations WHERE version=1"
    ).fetchone():
        connection.execute("LOCK TABLE normalized_events IN SHARE ROW EXCLUSIVE MODE")
        connection.execute((SQL_ROOT / "analytics_backfill.sql").read_text(encoding="utf-8"))
        connection.execute("INSERT INTO soc_analytics_migrations VALUES (1)")
    connection.execute((SQL_ROOT / "analytics_queries.sql").read_text(encoding="utf-8"))
