"""Construye el resumen periódico de alertas no inmediatas desde SQLite."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alert_store import AlertStore


def generate_digest(
    state_db: Path,
    output: Path,
    hours: int = 24,
    severities: set[str] | None = None,
) -> Path:
    selected_severities = severities or {"low", "medium"}
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    with AlertStore(state_db) as store:
        alerts = [
            alert
            for alert in store.list_alerts(5000)
            if alert["severity"] in selected_severities
            and datetime.fromisoformat(alert["generated_at_utc"]) >= cutoff
        ]
    by_rule = Counter(alert["rule_id"] for alert in alerts)
    by_status = Counter(alert["investigation_status"] for alert in alerts)
    lines = [
        "# Resumen periódico de alertas ADFS",
        "",
        f"Ventana: últimas {hours} horas. Total: **{len(alerts)}**.",
        "",
        "Las señales requieren revisión humana y no confirman un ataque.",
        "",
        "## Por regla",
        "",
        "| Regla | Cantidad |",
        "|---|---:|",
        *[f"| {rule} | {count} |" for rule, count in sorted(by_rule.items())],
        "",
        "## Por estado",
        "",
        "| Estado | Cantidad |",
        "|---|---:|",
        *[f"| {status} | {count} |" for status, count in sorted(by_status.items())],
        "",
        "## Muestra priorizada",
        "",
        "| Alerta | Severidad | Riesgo | Regla | Usuario | IP | Estado |",
        "|---|---|---:|---|---|---|---|",
    ]
    for alert in sorted(
        alerts, key=lambda item: (item["risk_score"], item["generated_at_utc"]), reverse=True
    )[:50]:
        lines.append(
            "| {alert_id} | {severity} | {risk_score} | {rule_id} | {user_key} | {client_ip_key} | {investigation_status} |".format(
                **alert
            )
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-db", type=Path, default=Path("analysis/state/soc_alerts.db"))
    parser.add_argument("--output", type=Path, default=Path("analysis/report/alert_digest.md"))
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()
    print(generate_digest(args.state_db, args.output, max(1, args.hours)))


if __name__ == "__main__":
    main()
