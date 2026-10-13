"""Hechos acotados de la alerta: sin interpretar hashes ni copiar mensajes sensibles."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from practicum_soc.core.service_identity import service_key
from practicum_soc.repositories.investigation import InvestigationRepository
from practicum_soc.soc.detection import load_baseline_context


def baseline_comparison(directory: Path, alert: dict, ip_keys: list[str]) -> dict:
    try:
        baseline = load_baseline_context(directory)
    except (FileNotFoundError, ValueError, KeyError):
        return {"available": False, "reason": "Línea base no disponible o incompleta"}
    occurred = datetime.fromisoformat(alert["first_seen_local"])
    if (
        not baseline.training_end_local
        or baseline.training_end_local >= occurred.date().isoformat()
    ):
        return {
            "available": False,
            "reason": "No se puede verificar que el entrenamiento sea anterior",
        }
    user = alert.get("user_key")
    sufficient = bool(user and user in baseline.sufficient_users)
    return {
        "available": True,
        "training_end_local": baseline.training_end_local,
        "sufficient_user_history": sufficient,
        "known_user_ips": {key: (user, key) in baseline.known_user_ips for key in ip_keys}
        if sufficient
        else None,
        "global_failure_rate": baseline.global_failure_rate,
        "reason": None if sufficient else "Usuario ausente o con historial insuficiente",
    }


def _event_evidence(row: dict) -> dict:
    # Solo campos permitidos; ni custom_message ni nombres reales ni URL de aplicaciones.
    return {
        **{
            key: row[key]
            for key in (
                "source_event_id",
                "event_time_utc",
                "event_class",
                "event_count",
                "user_key",
                "client_ip_key",
            )
        },
        "service_key": service_key(row.get("relying_party", "")),
    }


def success_after_failures(events: list[dict]) -> list[str]:
    failed_pairs, successes = set(), []
    for event in sorted(events, key=lambda row: (row["event_time_utc"], row["source_event_id"])):
        pair = event["user_key"], event["client_ip_key"]
        if not all(pair):
            continue
        if event["event_class"] == "failure":
            failed_pairs.add(pair)
        elif event["event_class"] == "success" and pair in failed_pairs:
            successes.append(event["source_event_id"])
    return successes


def collect_context(store, alert, policy, baseline_dir):
    repository = InvestigationRepository(store)
    first = datetime.fromisoformat(alert["first_seen_local"]).astimezone(UTC)
    last = datetime.fromisoformat(alert["last_seen_local"]).astimezone(UTC)
    start = (first - timedelta(minutes=policy.window_before_minutes)).isoformat()
    end = (last + timedelta(minutes=policy.window_after_minutes)).isoformat()
    anchors = repository.evidence_events(alert, policy.maximum_events)
    primary_key = alert.get("client_ip_key") or ""
    all_keys = sorted({row["client_ip_key"] for row in anchors if row["client_ip_key"]})
    if primary_key:
        all_keys = [primary_key, *[key for key in all_keys if key != primary_key]]
    ip_keys = all_keys[: policy.maximum_ip_entities]
    candidates = list(anchors)
    user_key = alert.get("user_key") or ""
    candidates += repository.events(
        alert["source_name"], "user_key", user_key, start, end, policy.maximum_events + 1
    )
    ip_counts = {}
    for key in ip_keys:
        candidates += repository.events(
            alert["source_name"], "client_ip_key", key, start, end, policy.maximum_events + 1
        )
        ip_counts[key] = repository.counts(alert["source_name"], "client_ip_key", key, start, end)
    unique = {row["source_event_id"]: row for row in candidates}
    # Mantener la evidencia original antes de añadir antecedentes hasta el límite.
    ordered = list({row["source_event_id"]: row for row in anchors}.values())
    anchored = {row["source_event_id"] for row in ordered}
    ordered += sorted(
        (row for key, row in unique.items() if key not in anchored),
        key=lambda row: row["event_time_utc"],
        reverse=True,
    )
    events = sorted(ordered[: policy.maximum_events], key=lambda row: row["event_time_utc"])
    addresses, unavailable = repository.original_ips(alert["source_name"], ip_keys)
    real_ip = addresses[0] if len(addresses) == 1 else None
    reason = (
        None
        if real_ip
        else (
            "La alerta tiene varias IP originales; consulte real_ips"
            if addresses
            else "; ".join(unavailable) or "No hay IP cliente asociada a la evidencia disponible"
        )
    )
    missing = []
    if not anchors:
        missing.append(
            "Los eventos que originaron la alerta no están disponibles en la base propia"
        )
    missing.extend(unavailable)
    if not addresses and not unavailable:
        missing.append(reason)
    if len(unique) > policy.maximum_events or len(all_keys) > len(ip_keys):
        missing.append(
            "Evidencia detallada truncada por límites; los conteos por entidad cubren la ventana"
        )
    context = {
        "alert": {
            key: alert.get(key)
            for key in (
                "alert_id",
                "source_name",
                "rule_id",
                "rule_name",
                "rule_version_id",
                "severity",
                "risk_score",
                "first_seen_local",
                "last_seen_local",
                "user_key",
                "client_ip_key",
            )
        },
        "window": {"from_utc": start, "to_utc": end},
        "user_counts": repository.counts(alert["source_name"], "user_key", user_key, start, end),
        "ip_counts": ip_counts,
        "events": [_event_evidence(row) for row in events],
        "success_after_failure_event_ids": success_after_failures(events),
        "other_affected_user_keys": sorted(
            {
                row["user_key"]
                for row in events
                if row["client_ip_key"] in ip_keys
                and row["user_key"]
                and row["user_key"] != user_key
            }
        ),
        "baseline": baseline_comparison(baseline_dir, alert, ip_keys),
        "missing_information": missing,
        "sampling_note": "Los éxitos posteriores y otras cuentas listadas corresponden a la muestra limitada.",
    }
    return context, real_ip, addresses, reason
