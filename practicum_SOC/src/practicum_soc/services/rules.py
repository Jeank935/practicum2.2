"""Preparación del catálogo de reglas sin depender de HTTP."""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from practicum_soc.core.config import load_json
from practicum_soc.repositories.factory import open_store
from practicum_soc.repositories.rules import RULE_FIELDS, RuleConfigStore
from practicum_soc.services.rule_preview import SOURCES, history_bounds


class RulePageConflict(ValueError):
    pass


def rules_context(state_db: Path, config_dir: Path, draft_id: str | None) -> dict:
    with open_store(state_db) as store:
        service = RuleConfigStore(store, load_json(config_dir / "detection_rules.json"))
        active = service.current()
        try:
            draft = service.version(draft_id) if draft_id else None
        except KeyError:
            raise KeyError("Borrador no encontrado") from None
        if draft and draft["status"] != "draft":
            raise RulePageConflict("Esta versión ya no es un borrador")
        limits = load_json(config_dir / "rule_management.json")
        context = {
            "active": active,
            "draft": draft,
            "preview": service.latest_preview(draft_id) if draft else None,
            "versions": service.versions(limits["history_page_limit"]),
            "history": service.history(limits["history_page_limit"]),
            "bounds": {source: history_bounds(store, source) for source in SOURCES},
            "rule_fields": RULE_FIELDS,
            "rule_labels": {key: active["config"][key]["display_name"] for key in RULE_FIELDS},
            "management": limits,
            "field_labels": {
                "enabled": "Regla habilitada",
                "window_minutes": "Ventana (minutos)",
                "minimum_failures": "Fallos mínimos",
                "minimum_distinct_users": "Cuentas mínimas",
                "minimum_lockouts": "Bloqueos mínimos",
                "minimum_events": "Eventos mínimos",
                "cooldown_minutes": "Pausa entre casos (minutos)",
                "base_risk": "Puntaje base",
                "critical_failure_threshold": "Fallos intensos",
                "critical_distinct_users_threshold": "Cuentas intensas",
                "intense_pattern_bonus": "Bono por patrón intenso",
                "multiple_accounts_bonus": "Bono por varias cuentas",
                "success_bonus": "Bono por éxito posterior",
            },
        }
        context["has_events"] = any(item["start_utc"] for item in context["bounds"].values())
        context["selected_source"] = next(
            (source for source in SOURCES if context["bounds"][source]["start_utc"]), None
        )
        if context["selected_source"]:
            bounds = context["bounds"][context["selected_source"]]
            zone = ZoneInfo(active["config"]["timezone"])
            last = datetime.fromisoformat(bounds["end_utc"]).astimezone(zone) + timedelta(minutes=1)
            first = max(
                datetime.fromisoformat(bounds["start_utc"]).astimezone(zone),
                last - timedelta(hours=6),
            )
            context["default_from"] = first.strftime("%Y-%m-%dT%H:%M")
            context["default_to"] = last.strftime("%Y-%m-%dT%H:%M")
        context["restore_options"] = [
            item
            for item in context["versions"]
            if item["status"] == "published" and item["version_id"] != active["version_id"]
        ]
    return context
