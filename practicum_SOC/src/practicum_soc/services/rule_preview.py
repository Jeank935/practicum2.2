"""Reproduce detección sin modificar eventos, casos ni checkpoints."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from practicum_soc.repositories.rules import RuleConfigStore
from practicum_soc.services.monitoring import cooldown_for_alert, event_from_row, load_exclusions
from practicum_soc.soc.detection import detect_alerts, evaluation_events, load_baseline_context

SOURCES = ("csv_demo_mvp", "csv_demo", "postgresql_live")


def _simulated_alerts(alerts: list[dict], config: dict) -> list[dict]:
    """Aplica en memoria la deduplicación y el cooldown del repositorio."""
    accepted: list[dict] = []
    identities: set[str] = set()
    latest: dict[tuple[str, str, str], datetime] = {}
    for alert in alerts:
        identifier = str(alert["alert_id"])
        if identifier in identities:
            continue
        key = (
            str(alert["rule_id"]),
            str(alert.get("user_key", "")),
            str(alert.get("client_ip_key", "")),
        )
        timestamp = datetime.fromisoformat(str(alert["last_seen_local"]))
        previous = latest.get(key)
        if previous and timestamp - previous < timedelta(minutes=cooldown_for_alert(alert, config)):
            continue
        identities.add(identifier)
        latest[key] = timestamp
        accepted.append(alert)
    return accepted


def _counts(alerts: list[dict]) -> dict:
    return {
        "total": len(alerts),
        "by_rule": dict(sorted(Counter(str(item["rule_id"]) for item in alerts).items())),
        "by_severity": dict(sorted(Counter(str(item["severity"]) for item in alerts).items())),
    }


def history_bounds(store, source: str) -> dict:
    if source not in SOURCES:
        raise ValueError("Fuente de prueba no admitida")
    values = []
    for direction in ("ASC", "DESC"):
        row = store.connection.execute(
            "SELECT event_time_utc FROM normalized_events "
            "WHERE source_name=? AND is_consistent=1 "
            f"ORDER BY event_time_utc {direction} LIMIT 1",
            (source,),
        ).fetchone()
        values.append(row["event_time_utc"] if row else None)
    return {"start_utc": values[0], "end_utc": values[1]}


def preview(
    store,
    initial_config: dict,
    management: dict,
    operational: dict,
    draft_id: str,
    actor: dict,
    source: str,
    start: datetime,
    end: datetime,
    project_root: Path,
) -> dict:
    if source not in SOURCES:
        raise ValueError("Fuente de prueba no admitida")
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise ValueError("Indique inicio y fin con zona horaria; el fin debe ser posterior")
    if end - start > timedelta(days=management["maximum_preview_days"]):
        raise ValueError("El periodo supera el máximo permitido")
    versions = RuleConfigStore(store, initial_config)
    versions._actor(actor)
    active = versions.current()
    draft = versions.version(draft_id)
    if draft["status"] != "draft" or draft["parent_version_id"] != active["version_id"]:
        raise ValueError("El borrador ya no corresponde a la versión activa")
    from_utc, to_utc = start.astimezone(UTC), end.astimezone(UTC)
    lookback = max(
        max(
            int(active["config"][key]["window_minutes"]),
            int(draft["config"][key]["window_minutes"]),
        )
        for key in (
            "brute_force_user",
            "password_spraying_ip",
            "success_after_failures",
            "account_lockout",
            "new_ip_for_user",
        )
    )
    since = (from_utc - timedelta(minutes=lookback)).isoformat(timespec="seconds")
    until = to_utc.isoformat(timespec="seconds")
    maximum = int(management["maximum_preview_events"])
    rows = store.connection.execute(
        "SELECT source_event_id,event_time_utc,event_class,user_key,client_ip_key,"
        "relying_party,event_count FROM normalized_events "
        "WHERE source_name=? AND is_consistent=1 AND event_time_utc>=? "
        "AND event_time_utc<? ORDER BY event_time_utc,source_event_id LIMIT ?",
        (source, since, until, maximum + 1),
    ).fetchall()
    if len(rows) > maximum:
        raise ValueError("Demasiados eventos: reduzca el periodo para comparar sin recortes")
    if not rows:
        raise ValueError("No hay eventos válidos en el periodo elegido")
    baseline_path = Path(operational["baseline_dir"])
    if not baseline_path.is_absolute():
        baseline_path = project_root / baseline_path
    baseline = load_baseline_context(baseline_path)
    exclusion_path = Path(operational["exclusions_file"])
    if not exclusion_path.is_absolute():
        exclusion_path = project_root / exclusion_path
    exclusions = load_exclusions(exclusion_path)
    results = {}
    for name, version in (("active", active), ("draft", draft)):
        events = [event_from_row(dict(row), version["config"]["timezone"]) for row in rows]
        valid = evaluation_events([event for event in events if event], baseline)
        if not valid:
            raise ValueError(
                "El periodo no contiene eventos de evaluación posteriores al entrenamiento"
            )
        candidates = detect_alerts(valid, version["config"], baseline, exclusions)
        relevant = [
            item
            for item in candidates
            if from_utc
            <= datetime.fromisoformat(str(item["last_seen_local"])).astimezone(UTC)
            < to_utc
        ]
        results[name] = _counts(_simulated_alerts(relevant, version["config"]))
    result = {
        "source": source,
        "from_utc": from_utc.isoformat(),
        "to_utc": to_utc.isoformat(),
        "events_read": len(rows),
        "active_version_id": active["version_id"],
        "draft_version_id": draft_id,
        "active": results["active"],
        "draft": results["draft"],
        "difference": results["draft"]["total"] - results["active"]["total"],
    }
    return versions.save_preview(
        draft_id,
        actor,
        active["version_id"],
        source,
        from_utc.isoformat(),
        to_utc.isoformat(),
        result,
    )
