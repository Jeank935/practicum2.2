"""Reporte mensual de datos realmente persistidos, no de contadores del CSV demo."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path


def month_ranges(start, end):
    current = start
    while current < end:
        year, month = (
            (current.year + 1, 1) if current.month == 12 else (current.year, current.month + 1)
        )
        following = current.replace(year=year, month=month, day=1)
        yield current, min(following, end)
        current = following


def monthly_metrics(store, source, start, end):
    parameters = (source, start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat())
    scope = "source_name=? AND event_time_utc>=? AND event_time_utc<?"
    rows = store.connection.execute(
        "SELECT event_class,is_consistent,COUNT(*) AS rows,SUM(event_count) AS events,"
        "MIN(event_time_utc) AS first_event,MAX(event_time_utc) AS last_event "
        f"FROM normalized_events WHERE {scope} GROUP BY event_class,is_consistent",
        parameters,
    ).fetchall()
    summary = {
        "month": start.strftime("%Y-%m"),
        "stored_rows": 0,
        "valid_rows": 0,
        "rejected_rows": 0,
        "classes": {},
        "first_event": None,
        "last_event": None,
    }
    for row in rows:
        summary["stored_rows"] += int(row["rows"])
        key = "valid_rows" if row["is_consistent"] else "rejected_rows"
        summary[key] += int(row["rows"])
        summary["classes"][row["event_class"]] = summary["classes"].get(
            row["event_class"], 0
        ) + int(row["events"])
        summary["first_event"] = min(filter(None, [summary["first_event"], row["first_event"]]))
        summary["last_event"] = max(filter(None, [summary["last_event"], row["last_event"]]))
    alert_rows = store.connection.execute(
        "SELECT rule_id,severity,COUNT(*) AS n FROM alerts WHERE source_name=? "
        "AND last_seen_local>=? AND last_seen_local<? GROUP BY rule_id,severity",
        (source, start.isoformat(), end.isoformat()),
    ).fetchall()
    summary["alerts_by_rule"] = {}
    summary["alerts_by_severity"] = {}
    for row in alert_rows:
        for key, value in (
            ("alerts_by_rule", row["rule_id"]),
            ("alerts_by_severity", row["severity"]),
        ):
            summary[key][value] = summary[key].get(value, 0) + int(row["n"])
    summary["stored_alerts"] = sum(summary["alerts_by_rule"].values())
    return summary


def save_report(store, result, directory: Path):
    start = datetime.fromisoformat(result["from_local"])
    end = datetime.fromisoformat(result["to_local_exclusive"])
    months = [monthly_metrics(store, result["source"], a, b) for a, b in month_ranges(start, end)]
    report = {**result, "generated_at_utc": datetime.now(UTC).isoformat(), "months": months}
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        f"# Análisis histórico ADFS: {start:%Y-%m} a {end - timedelta(days=1):%Y-%m}",
        "",
        "Fuente institucional en solo lectura. Datos y casos persistidos en el PostgreSQL propio del SOC.",
        "Fechas según event_time_origen; event_time se utiliza solo cuando falta la fecha original.",
        f"Versión de reglas: `{result['rule_version_id']}`. Entrenamiento anterior: {result['baseline_training_end']}.",
        "",
        "| Mes | Registros | Válidos | Rechazados | Éxitos | Fallos | Bloqueos | Casos |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in months:
        classes = item["classes"]
        lines.append(
            f"| {item['month']} | {item['stored_rows']} | {item['valid_rows']} | {item['rejected_rows']} | "
            f"{classes.get('success', 0)} | {classes.get('failure', 0)} | {classes.get('lockout', 0)} | {item['stored_alerts']} |"
        )
    lines.extend(
        [
            "",
            "Éxitos, fallos y bloqueos son conteos normalizados ponderados, incluidos los registros rechazados; solo los válidos alimentan la detección.",
        ]
    )
    for item in months:
        first_local = (
            datetime.fromisoformat(item["first_event"]).astimezone(start.tzinfo).isoformat()
            if item["first_event"]
            else "sin registros"
        )
        last_local = (
            datetime.fromisoformat(item["last_event"]).astimezone(start.tzinfo).isoformat()
            if item["last_event"]
            else "sin registros"
        )
        lines.extend(
            [
                "",
                f"## {item['month']}",
                "",
                f"Cobertura observada (hora de Loja): {first_local} a {last_local}.",
                f"Casos por regla: {json.dumps(item['alerts_by_rule'], ensure_ascii=False)}.",
                f"Casos por severidad: {json.dumps(item['alerts_by_severity'], ensure_ascii=False)}.",
            ]
        )
    lines.extend(
        [
            "",
            "## Verificación y límites",
            "",
            f"Persistencia: {json.dumps(result['persistence'], ensure_ascii=False)}.",
            f"Deduplicación y checkpoint: {json.dumps(result['verification'], ensure_ascii=False)}.",
            "Los casos son señales para revisión, no ataques confirmados. No se puede medir precisión ni falsos positivos sin revisión humana.",
            "La ausencia de registros en una fecha no demuestra ausencia de uso: puede deberse a cobertura incompleta de la fuente.",
            "La línea base de marzo no se reentrena con agosto/septiembre, para no usar datos de evaluación como entrenamiento.",
            "Horario inusual y red no autorizada continúan deshabilitados; no se cambiaron umbrales.",
        ]
    )
    (directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
