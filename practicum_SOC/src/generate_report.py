"""Genera un reporte histórico reproducible con datos pseudonimizados."""

from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path

from alert_store import AlertStore


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def write_bar_chart(
    path: Path,
    title: str,
    labels: list[str],
    values: list[int],
    color: str = "#2563eb",
) -> None:
    """Escribe un SVG autocontenido sin incorporar datos identificables."""
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 960, 420
    left, top, bottom = 70, 55, 90
    plot_width, plot_height = width - left - 30, height - top - bottom
    maximum = max(values, default=0) or 1
    slot = plot_width / max(1, len(values))
    bar_width = max(2, slot * 0.7)
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2}" y="28" text-anchor="middle" '
        f'font-family="Arial" font-size="18">{html.escape(title)}</text>',
    ]
    for index, (label, value) in enumerate(zip(labels, values, strict=True)):
        bar_height = (value / maximum) * plot_height
        x = left + index * slot + (slot - bar_width) / 2
        y = top + plot_height - bar_height
        elements.extend(
            [
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" '
                f'height="{bar_height:.1f}" fill="{color}" rx="2"/>',
                f'<text x="{x + bar_width / 2:.1f}" y="{max(45, y - 5):.1f}" '
                f'text-anchor="middle" font-family="Arial" font-size="10">{value}</text>',
                f'<text x="{x + bar_width / 2:.1f}" y="{top + plot_height + 18}" '
                f'transform="rotate(45 {x + bar_width / 2:.1f} {top + plot_height + 18})" '
                f'font-family="Arial" font-size="10">{html.escape(label)}</text>',
            ]
        )
    elements.append("</svg>")
    path.write_text("\n".join(elements), encoding="utf-8")


def _state_counts(state_db: Path | None, source_name: str) -> dict:
    empty = {"total": 0, "by_status": {}, "by_severity": {}, "by_rule": {}}
    if state_db is None or not state_db.is_file():
        return empty
    with AlertStore(state_db) as store:
        return store.alert_counts(source_name)


def _configured_rules(config: dict, alert_counts: dict[str, int]) -> tuple[list, list]:
    enabled = []
    disabled = []
    for key, value in config.items():
        if not isinstance(value, dict) or "enabled" not in value:
            continue
        if value["enabled"]:
            rule_id = {
                "brute_force_user": "AUTH_BRUTE_FORCE_USER",
                "password_spraying_ip": "AUTH_PASSWORD_SPRAY_IP",
                "success_after_failures": "AUTH_SUCCESS_AFTER_FAILURES",
                "account_lockout": "AUTH_ACCOUNT_LOCKOUT",
                "new_ip_for_user": "AUTH_NEW_IP_FOR_USER",
            }.get(key, key)
            enabled.append([rule_id, int(alert_counts.get(rule_id, 0))])
        else:
            disabled.append([key, value.get("reason_disabled", "Sin motivo documentado")])
    return enabled, disabled


def _top_rows(rows: list[dict], count_column: str, limit: int = 10) -> list[dict]:
    return sorted(rows, key=lambda row: int(row.get(count_column, 0)), reverse=True)[:limit]


def generate_report(
    analysis_dir: Path,
    output_dir: Path,
    *,
    detection_config_path: Path | None = None,
    state_db: Path | None = None,
    source_name: str = "csv_demo_mvp",
) -> Path:
    normalization = read_json(analysis_dir / "normalization_stats.json")
    baseline = read_json(analysis_dir / "baseline" / "baseline_summary.json")
    alert_summary = read_json(analysis_dir / "alerts" / "alert_summary.json")
    users = read_csv(analysis_dir / "baseline" / "user_behavior.csv")
    ips = read_csv(analysis_dir / "baseline" / "ip_behavior.csv")
    config_path = detection_config_path or analysis_dir.parent / "config" / "detection_rules.json"
    detection_config = read_json(config_path) if config_path.is_file() else {}

    persistent = _state_counts(state_db, source_name)
    rule_counts = alert_summary.get("alerts_by_rule", {})
    severity_counts = alert_summary.get("alerts_by_severity", {})
    enabled_rules, disabled_rules = _configured_rules(detection_config, rule_counts)
    false_positives = int(persistent.get("by_status", {}).get("false_positive", 0))
    event_classes = normalization.get("event_classes", {})
    evaluation = baseline.get("evaluation_period", {})

    output_dir.mkdir(parents=True, exist_ok=True)
    rule_chart = sorted(rule_counts.items())
    write_bar_chart(
        output_dir / "charts" / "alerts_by_rule.svg",
        "Alertas por regla",
        [rule.replace("AUTH_", "") for rule, _ in rule_chart],
        [int(count) for _, count in rule_chart],
        "#7c3aed",
    )

    top_users = _top_rows(users, "failure_count")
    top_ips = _top_rows(ips, "failure_count")
    lines = [
        "# Reporte histórico de autenticaciones ADFS",
        "",
        "Resultado reproducible para revisión humana. Una alerta es una señal, no una confirmación de ataque.",
        "",
        "## Periodo y procesamiento",
        "",
        f"- Periodo evaluado: **{evaluation.get('start_local', 'N/D')} a {evaluation.get('end_local', 'N/D')}**, zona `{baseline.get('timezone', 'America/Guayaquil')}`.",
        f"- Eventos procesados: **{int(normalization.get('input_rows', 0)):,}**.",
        f"- Válidos: **{int(normalization.get('valid_rows', 0)):,}**; rechazados: **{int(normalization.get('rejected_rows', 0)):,}**; duplicados: **{int(normalization.get('duplicate_rows', 0)):,}**.",
        f"- Éxitos: **{int(event_classes.get('success', 0)):,}**; fallos: **{int(event_classes.get('failure', 0)):,}**; bloqueos: **{int(event_classes.get('lockout', 0)):,}**.",
        "",
        "## Reglas habilitadas y alertas",
        "",
        markdown_table(["Regla", "Alertas"], enabled_rules),
        "",
        "![Alertas por regla](charts/alerts_by_rule.svg)",
        "",
        "## Alertas por severidad",
        "",
        markdown_table(
            ["Severidad", "Cantidad"],
            [[severity, count] for severity, count in sorted(severity_counts.items())],
        ),
        "",
        f"Falsos positivos registrados en SQLite: **{false_positives}**.",
        "",
        "## Perfiles pseudonimizados con más fallos",
        "",
        markdown_table(
            ["Usuario", "Fallos", "Bloqueos", "Historial"],
            [
                [row["user_key"], row["failure_count"], row["lockout_count"], row["history_status"]]
                for row in top_users
            ],
        ),
        "",
        "## IP pseudonimizadas con más fallos",
        "",
        markdown_table(
            ["IP", "Fallos", "Usuarios distintos"],
            [
                [row["client_ip_key"], row["failure_count"], row["distinct_users"]]
                for row in top_ips
            ],
        ),
        "",
        "## Reglas desactivadas",
        "",
        markdown_table(["Regla", "Motivo"], disabled_rules),
        "",
        "## Limitaciones del dataset",
        "",
        "- La cobertura horaria no demuestra ausencia de actividad en horas no observadas.",
        "- No se dispone de CIDR, NAT, proxy o VPN oficiales para validar origen institucional.",
        "- Una IP compartida puede representar NAT, proxy o infraestructura intermedia.",
        "- Los umbrales del MVP requieren calibración mediante casos revisados por la DGTITD.",
        "- Todos los usuarios e IP mostrados son pseudónimos HMAC; el CSV original no se modifica.",
        "",
        "## Canal de demostración",
        "",
        "`soc_inbox` registra internamente alertas altas y críticas. No envía correo, Teams ni webhooks. El canal definitivo debe acordarse con la Dirección.",
    ]
    report_path = output_dir / "historical_report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis-dir", type=Path, default=Path("analysis"))
    parser.add_argument("--output-dir", type=Path, default=Path("analysis/report"))
    parser.add_argument(
        "--detection-config", type=Path, default=Path("config/detection_rules.json")
    )
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--source-name", default="csv_demo_mvp")
    args = parser.parse_args()
    report = generate_report(
        args.analysis_dir,
        args.output_dir,
        detection_config_path=args.detection_config,
        state_db=args.state_db,
        source_name=args.source_name,
    )
    print(json.dumps({"report": str(report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
