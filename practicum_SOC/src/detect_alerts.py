"""Reglas explicables del MVP para autenticaciones ADFS.

El motor recibe eventos normalizados y no conoce SQLite, FastAPI ni canales de
notificación. Cada regla devuelve alertas deterministas para que la capa de
almacenamiento controle deduplicación y cooldown entre ejecuciones.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ALERT_COLUMNS = [
    "alert_id",
    "rule_id",
    "rule_name",
    "severity",
    "risk_score",
    "risk_factors",
    "status",
    "first_seen_local",
    "last_seen_local",
    "user_key",
    "client_ip_key",
    "event_types",
    "event_count",
    "success_count",
    "failure_count",
    "lockout_count",
    "distinct_users",
    "distinct_client_ips",
    "relying_parties",
    "evidence_event_ids",
    "description",
    "recommendation",
    "requires_human_review",
]


@dataclass(frozen=True)
class Event:
    timestamp: datetime
    event_class: str
    user_key: str
    client_ip_key: str
    relying_party: str
    source_event_id: str
    weight: int = 1


@dataclass(frozen=True)
class BaselineContext:
    sufficient_users: frozenset[str]
    known_user_ips: frozenset[tuple[str, str]]
    known_user_apps: frozenset[tuple[str, str]]
    known_user_hours: frozenset[tuple[str, int]]
    global_failure_rate: float
    training_end_local: str = ""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_baseline_context(directory: Path) -> BaselineContext:
    paths = {
        "summary": directory / "baseline_summary.json",
        "users": directory / "user_behavior.csv",
        "ips": directory / "user_ip_profile.csv",
        "apps": directory / "user_app_profile.csv",
        "hours": directory / "user_hour_profile.csv",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Faltan archivos de línea base: {missing}")

    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    sufficient_users = {
        row["user_key"]
        for row in _read_csv(paths["users"])
        if row.get("history_status") == "sufficient"
    }
    known_user_ips = {
        (row["user_key"], row["client_ip_key"])
        for row in _read_csv(paths["ips"])
        if row.get("user_key") and row.get("client_ip_key")
    }
    known_user_apps = {
        (row["user_key"], row["relying_party"])
        for row in _read_csv(paths["apps"])
        if row.get("user_key") and row.get("relying_party")
    }
    known_user_hours = {
        (row["user_key"], int(row["hour_local"]))
        for row in _read_csv(paths["hours"])
        if row.get("user_key") and row.get("hour_local") not in (None, "")
    }
    return BaselineContext(
        sufficient_users=frozenset(sufficient_users),
        known_user_ips=frozenset(known_user_ips),
        known_user_apps=frozenset(known_user_apps),
        known_user_hours=frozenset(known_user_hours),
        global_failure_rate=float(summary.get("baseline_failure_rate", 0.0)),
        training_end_local=str(summary.get("training_period", {}).get("end_local", "")),
    )


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_events(input_csv: Path, timezone_name: str) -> tuple[list[Event], int]:
    local_timezone = ZoneInfo(timezone_name)
    events: list[Event] = []
    skipped_invalid_time = 0
    for row in _read_csv(input_csv):
        timestamp = parse_timestamp(row.get("event_time_utc", ""))
        if timestamp is None:
            skipped_invalid_time += 1
            continue
        try:
            weight = max(1, int(row.get("event_count", "1")))
        except ValueError:
            weight = 1
        events.append(
            Event(
                timestamp=timestamp.astimezone(local_timezone),
                event_class=row.get("event_class", "other"),
                user_key=row.get("user_key", ""),
                client_ip_key=row.get("client_ip_key", ""),
                relying_party=row.get("relying_party", ""),
                source_event_id=(row.get("source_event_id") or row.get("deduplication_key", "")),
                weight=weight,
            )
        )
    events.sort(key=lambda event: (event.timestamp, event.source_event_id))
    return events, skipped_invalid_time


def evaluation_events(events: list[Event], baseline: BaselineContext | None) -> list[Event]:
    if baseline is None or not baseline.training_end_local:
        return list(events)
    return [
        event
        for event in events
        if event.timestamp.date().isoformat() > baseline.training_end_local
    ]


def is_restricted_hour(hour: int, start_hour: int, end_hour: int) -> bool:
    """Se conserva para compatibilidad y pruebas; la regla está deshabilitada."""
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def trim_window(history: deque[Event], current: datetime, minutes: int) -> None:
    cutoff = current - timedelta(minutes=minutes)
    while history and history[0].timestamp < cutoff:
        history.popleft()


def history_weight(events: list[Event] | deque[Event], event_class: str | None = None) -> int:
    return sum(
        event.weight for event in events if event_class is None or event.event_class == event_class
    )


def severity_for_score(score: int, config: dict) -> str:
    thresholds = config["risk_scoring"]["severity_thresholds"]
    for severity in ("critical", "high", "medium", "low"):
        if score >= int(thresholds[severity]):
            return severity
    return "low"


def calculate_risk(
    config: dict,
    rule_config: dict,
    related_count: int,
    threshold: int,
    context_factors: list[tuple[str, int]] | None = None,
) -> tuple[int, str, str]:
    base_points = int(rule_config["base_risk"])
    factors = [{"factor": "base_rule", "points": base_points}]
    scoring = config["risk_scoring"]
    volume_bonus = min(
        int(scoring["max_volume_bonus"]),
        max(0, related_count - threshold) * int(scoring["volume_bonus_per_event"]),
    )
    if volume_bonus:
        factors.append({"factor": "volume_above_threshold", "points": volume_bonus})
    for name, points in context_factors or []:
        if points:
            factors.append({"factor": name, "points": int(points)})
    score = min(100, max(0, sum(int(item["points"]) for item in factors)))
    return (
        score,
        severity_for_score(score, config),
        json.dumps(factors, ensure_ascii=False, separators=(",", ":")),
    )


def make_alert(
    rule_id: str,
    rule_name: str,
    severity: str,
    evidence: list[Event],
    description: str,
    *,
    risk_score: int,
    risk_factors: str,
    recommendation: str,
) -> dict[str, str | int]:
    ordered = sorted(evidence, key=lambda event: (event.timestamp, event.source_event_id))
    classes: Counter[str] = Counter()
    users: set[str] = set()
    ips: set[str] = set()
    apps: set[str] = set()
    source_ids: list[str] = []
    for event in ordered:
        classes[event.event_class] += event.weight
        if event.user_key:
            users.add(event.user_key)
        if event.client_ip_key:
            ips.add(event.client_ip_key)
        if event.relying_party:
            apps.add(event.relying_party)
        if event.source_event_id and len(source_ids) < 10:
            source_ids.append(event.source_event_id)

    first_seen = ordered[0].timestamp
    last_seen = ordered[-1].timestamp
    user_key = next(iter(users)) if len(users) == 1 else ""
    client_ip_key = next(iter(ips)) if len(ips) == 1 else ""
    fingerprint = "|".join(
        (
            rule_id,
            user_key,
            client_ip_key,
            first_seen.isoformat(),
            last_seen.isoformat(),
            ",".join(sorted(source_ids)),
        )
    )
    alert_id = "alt_" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:20]
    return {
        "alert_id": alert_id,
        "rule_id": rule_id,
        "rule_name": rule_name,
        "severity": severity,
        "risk_score": risk_score,
        "risk_factors": risk_factors,
        "status": "new",
        "first_seen_local": first_seen.isoformat(),
        "last_seen_local": last_seen.isoformat(),
        "user_key": user_key,
        "client_ip_key": client_ip_key,
        "event_types": ";".join(
            f"{name}:{count}" for name, count in sorted(classes.items()) if count
        ),
        "event_count": history_weight(ordered),
        "success_count": classes["success"],
        "failure_count": classes["failure"],
        "lockout_count": classes["lockout"],
        "distinct_users": len(users),
        "distinct_client_ips": len(ips),
        "relying_parties": ";".join(sorted(apps)[:8]),
        "evidence_event_ids": ";".join(source_ids),
        "description": description,
        "recommendation": recommendation,
        "requires_human_review": "true",
    }


def cooldown_ready(
    last_alerts: dict[str, datetime],
    entity: str,
    timestamp: datetime,
    cooldown_minutes: int,
) -> bool:
    previous = last_alerts.get(entity)
    if previous is not None and timestamp - previous < timedelta(minutes=cooldown_minutes):
        return False
    last_alerts[entity] = timestamp
    return True


def is_authorized_context(event: Event, exclusions: dict | None) -> bool:
    """Indica si el evento pertenece a una exclusión operativa autorizada."""
    if not exclusions:
        return False
    return bool(
        (event.user_key and event.user_key in exclusions.get("user_keys", set()))
        or (event.client_ip_key and event.client_ip_key in exclusions.get("client_ip_keys", set()))
        or (event.relying_party and event.relying_party in exclusions.get("relying_parties", set()))
    )


def exclusion_threshold(exclusions: dict | None, name: str, default: int) -> int:
    """Obtiene el umbral elevado de una exclusión sin debilitar la regla normal."""
    if not exclusions:
        return default
    thresholds = exclusions.get("anomalous_thresholds", {})
    return max(default, int(thresholds.get(name, default)))


def _rule_alert(
    *,
    rule_id: str,
    rule_name: str,
    evidence: list[Event],
    description: str,
    recommendation: str,
    config: dict,
    rule_config: dict,
    threshold: int,
    context_factors: list[tuple[str, int]] | None = None,
) -> dict:
    risk_score, severity, risk_factors = calculate_risk(
        config,
        rule_config,
        history_weight(evidence),
        threshold,
        context_factors,
    )
    return make_alert(
        rule_id,
        rule_name,
        severity,
        evidence,
        description,
        risk_score=risk_score,
        risk_factors=risk_factors,
        recommendation=recommendation,
    )


def detect_brute_force(
    events: list[Event], config: dict, exclusions: dict | None = None
) -> list[dict]:
    rule = config["brute_force_user"]
    if not rule["enabled"]:
        return []
    histories: dict[tuple[str, bool], deque[Event]] = defaultdict(deque)
    cooldowns: dict[str, datetime] = {}
    alerts = []
    for event in events:
        if event.event_class != "failure" or not event.user_key:
            continue
        authorized = is_authorized_context(event, exclusions)
        history = histories[(event.user_key, authorized)]
        history.append(event)
        trim_window(history, event.timestamp, int(rule["window_minutes"]))
        threshold = (
            exclusion_threshold(exclusions, "failures_per_user", int(rule["minimum_failures"]))
            if authorized
            else int(rule["minimum_failures"])
        )
        failure_count = history_weight(history, "failure")
        if failure_count < threshold:
            continue
        if not cooldown_ready(
            cooldowns,
            f"{event.user_key}:{authorized}",
            event.timestamp,
            int(rule["cooldown_minutes"]),
        ):
            continue
        intense_bonus = (
            int(rule["intense_pattern_bonus"])
            if failure_count >= int(rule["critical_failure_threshold"])
            else 0
        )
        alerts.append(
            _rule_alert(
                rule_id="AUTH_BRUTE_FORCE_USER",
                rule_name="Múltiples fallos contra un usuario",
                evidence=list(history),
                description=(
                    "Una cuenta autorizada superó el umbral anómalo de fallos en la ventana."
                    if authorized
                    else "El usuario superó el umbral de fallos dentro de la ventana."
                ),
                recommendation="Validar el origen y confirmar actividad con el responsable de la cuenta.",
                config=config,
                rule_config=rule,
                threshold=threshold,
                context_factors=[("intense_pattern", intense_bonus)],
            )
        )
    return alerts


def detect_password_spray(
    events: list[Event], config: dict, exclusions: dict | None = None
) -> list[dict]:
    rule = config["password_spraying_ip"]
    if not rule["enabled"]:
        return []
    histories: dict[tuple[str, bool], deque[Event]] = defaultdict(deque)
    cooldowns: dict[str, datetime] = {}
    alerts = []
    for event in events:
        if event.event_class != "failure" or not event.client_ip_key:
            continue
        authorized = is_authorized_context(event, exclusions)
        history = histories[(event.client_ip_key, authorized)]
        history.append(event)
        trim_window(history, event.timestamp, int(rule["window_minutes"]))
        distinct_users = {item.user_key for item in history if item.user_key}
        failure_threshold = (
            exclusion_threshold(exclusions, "failures_per_ip", int(rule["minimum_failures"]))
            if authorized
            else int(rule["minimum_failures"])
        )
        user_threshold = (
            exclusion_threshold(
                exclusions,
                "distinct_users_per_ip",
                int(rule["minimum_distinct_users"]),
            )
            if authorized
            else int(rule["minimum_distinct_users"])
        )
        failure_count = history_weight(history, "failure")
        threshold_reached = (
            failure_count >= failure_threshold and len(distinct_users) >= user_threshold
        )
        if not threshold_reached or not cooldown_ready(
            cooldowns,
            f"{event.client_ip_key}:{authorized}",
            event.timestamp,
            int(rule["cooldown_minutes"]),
        ):
            continue
        intense = failure_count >= int(rule["critical_failure_threshold"]) or len(
            distinct_users
        ) >= int(rule["critical_distinct_users_threshold"])
        alerts.append(
            _rule_alert(
                rule_id="AUTH_PASSWORD_SPRAY_IP",
                rule_name="Una IP intentando acceder a varias cuentas",
                evidence=list(history),
                description=(
                    "Una IP autorizada superó el umbral anómalo contra varias cuentas."
                    if authorized
                    else "La IP produjo fallos contra varias cuentas en la ventana."
                ),
                recommendation="Descartar primero NAT, proxy o infraestructura compartida autorizada.",
                config=config,
                rule_config=rule,
                threshold=failure_threshold,
                context_factors=[
                    ("multiple_accounts", int(rule["multiple_accounts_bonus"])),
                    (
                        "intense_pattern",
                        int(rule["intense_pattern_bonus"]) if intense else 0,
                    ),
                ],
            )
        )
    return alerts


def detect_success_after_failures(
    events: list[Event], config: dict, exclusions: dict | None = None
) -> list[dict]:
    rule = config["success_after_failures"]
    if not rule["enabled"]:
        return []
    failures: dict[tuple[str, bool], deque[Event]] = defaultdict(deque)
    cooldowns: dict[str, datetime] = {}
    alerts = []
    for event in events:
        if not event.user_key:
            continue
        authorized = is_authorized_context(event, exclusions)
        history = failures[(event.user_key, authorized)]
        trim_window(history, event.timestamp, int(rule["window_minutes"]))
        if event.event_class == "failure":
            history.append(event)
            continue
        if event.event_class != "success":
            continue
        threshold = (
            exclusion_threshold(
                exclusions,
                "success_after_failures",
                int(rule["minimum_failures"]),
            )
            if authorized
            else int(rule["minimum_failures"])
        )
        failure_count = history_weight(history, "failure")
        if failure_count < threshold:
            continue
        if not cooldown_ready(
            cooldowns,
            f"{event.user_key}:{authorized}",
            event.timestamp,
            int(rule["cooldown_minutes"]),
        ):
            continue
        evidence = [*history, event]
        alerts.append(
            _rule_alert(
                rule_id="AUTH_SUCCESS_AFTER_FAILURES",
                rule_name="Éxito después de múltiples fallos",
                evidence=evidence,
                description="Se observó un éxito después de varios fallos recientes del usuario.",
                recommendation="Priorizar la revisión del origen y validar el acceso con el usuario.",
                config=config,
                rule_config=rule,
                threshold=threshold + 1,
                context_factors=[
                    ("success_after_failures", int(rule["success_bonus"])),
                    (
                        "intense_pattern",
                        int(rule["intense_pattern_bonus"])
                        if failure_count >= int(rule["critical_failure_threshold"])
                        else 0,
                    ),
                ],
            )
        )
    return alerts


def detect_account_lockout(
    events: list[Event], config: dict, exclusions: dict | None = None
) -> list[dict]:
    rule = config["account_lockout"]
    if not rule["enabled"]:
        return []
    histories: dict[tuple[str, bool], deque[Event]] = defaultdict(deque)
    cooldowns: dict[str, datetime] = {}
    alerts = []
    for event in events:
        if event.event_class != "lockout" or not event.user_key:
            continue
        authorized = is_authorized_context(event, exclusions)
        history = histories[(event.user_key, authorized)]
        history.append(event)
        trim_window(history, event.timestamp, int(rule["window_minutes"]))
        threshold = (
            exclusion_threshold(exclusions, "lockouts_per_user", int(rule["minimum_lockouts"]))
            if authorized
            else int(rule["minimum_lockouts"])
        )
        if history_weight(history, "lockout") < threshold or not cooldown_ready(
            cooldowns,
            f"{event.user_key}:{authorized}",
            event.timestamp,
            int(rule["cooldown_minutes"]),
        ):
            continue
        alerts.append(
            _rule_alert(
                rule_id="AUTH_ACCOUNT_LOCKOUT",
                rule_name="Bloqueos múltiples de cuenta",
                evidence=list(history),
                description=(
                    "Una cuenta autorizada superó el umbral anómalo de bloqueos."
                    if authorized
                    else "ADFS registró múltiples bloqueos de la misma cuenta en la ventana."
                ),
                recommendation="Revisar intentos previos y confirmar si los bloqueos fueron esperados.",
                config=config,
                rule_config=rule,
                threshold=threshold,
            )
        )
    return alerts


def detect_new_ip(
    events: list[Event],
    config: dict,
    baseline: BaselineContext | None,
    exclusions: dict | None = None,
) -> list[dict]:
    rule = config["new_ip_for_user"]
    if not rule["enabled"] or baseline is None:
        return []
    histories: dict[tuple[str, str, bool], deque[Event]] = defaultdict(deque)
    cooldowns: dict[str, datetime] = {}
    alerts = []
    for event in evaluation_events(events, baseline):
        if (
            event.event_class not in {"success", "failure", "lockout"}
            or event.user_key not in baseline.sufficient_users
            or not event.client_ip_key
        ):
            continue
        if (event.user_key, event.client_ip_key) in baseline.known_user_ips:
            continue
        authorized = is_authorized_context(event, exclusions)
        history = histories[(event.user_key, event.client_ip_key, authorized)]
        history.append(event)
        trim_window(history, event.timestamp, int(rule["window_minutes"]))
        threshold = (
            exclusion_threshold(exclusions, "new_ip_events", int(rule["minimum_events"]))
            if authorized
            else int(rule["minimum_events"])
        )
        if history_weight(history) < threshold:
            continue
        if not cooldown_ready(
            cooldowns,
            f"{event.user_key}:{event.client_ip_key}:{authorized}",
            event.timestamp,
            int(rule["cooldown_minutes"]),
        ):
            continue
        alerts.append(
            _rule_alert(
                rule_id="AUTH_NEW_IP_FOR_USER",
                rule_name="IP nueva para el usuario",
                evidence=list(history),
                description=(
                    "Una IP autorizada nueva superó el umbral anómalo de actividad."
                    if authorized
                    else "Una IP nueva repitió actividad fuera de la línea base del usuario."
                ),
                recommendation="Validar si el origen es legítimo antes de clasificar la señal.",
                config=config,
                rule_config=rule,
                threshold=threshold,
            )
        )
    return alerts


RuleDetector = Callable[[list[Event], dict, dict | None], list[dict]]
WINDOW_RULES: tuple[RuleDetector, ...] = (
    detect_brute_force,
    detect_password_spray,
    detect_success_after_failures,
    detect_account_lockout,
)


def detect_alerts(
    events: list[Event],
    config: dict,
    baseline: BaselineContext | None = None,
    exclusions: dict | None = None,
) -> list[dict]:
    ordered_events = sorted(events, key=lambda event: (event.timestamp, event.source_event_id))
    alerts = [
        alert for detector in WINDOW_RULES for alert in detector(ordered_events, config, exclusions)
    ]
    alerts.extend(detect_new_ip(ordered_events, config, baseline, exclusions))
    alerts.sort(key=lambda alert: (alert["first_seen_local"], alert["rule_id"]))
    return alerts


def write_outputs(alerts: list[dict], output_dir: Path, metadata: dict) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "alerts.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ALERT_COLUMNS)
        writer.writeheader()
        writer.writerows(alerts)

    by_rule = Counter(alert["rule_id"] for alert in alerts)
    by_severity = Counter(alert["severity"] for alert in alerts)
    summary = {
        **metadata,
        "total_alerts": len(alerts),
        "alerts_by_rule": dict(sorted(by_rule.items())),
        "alerts_by_severity": dict(sorted(by_severity.items())),
        "risk_score_average": round(
            sum(int(alert["risk_score"]) for alert in alerts) / len(alerts), 2
        )
        if alerts
        else 0,
    }
    (output_dir / "alert_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/detection_rules.json"))
    parser.add_argument("--baseline-dir", type=Path, required=True)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    baseline = load_baseline_context(args.baseline_dir)
    all_events, skipped = load_events(args.input_csv, config["timezone"])
    events = evaluation_events(all_events, baseline)
    alerts = detect_alerts(events, config, baseline)
    summary = write_outputs(
        alerts,
        args.output_dir,
        {
            "source_file": str(args.input_csv),
            "timezone": config["timezone"],
            "processed_events": len(events),
            "training_events_excluded": len(all_events) - len(events),
            "skipped_invalid_time": skipped,
            "rules_are_provisional": True,
            "human_review_required": True,
        },
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
