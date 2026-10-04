"""Versiones y publicación transaccional de parámetros de detección."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from practicum_soc.repositories.alerts import utc_now
from practicum_soc.repositories.auth import AuthStore

RULE_FIELDS = {
    "brute_force_user": (
        "enabled",
        "window_minutes",
        "minimum_failures",
        "cooldown_minutes",
        "base_risk",
        "critical_failure_threshold",
        "intense_pattern_bonus",
    ),
    "password_spraying_ip": (
        "enabled",
        "window_minutes",
        "minimum_failures",
        "minimum_distinct_users",
        "cooldown_minutes",
        "base_risk",
        "multiple_accounts_bonus",
        "critical_failure_threshold",
        "critical_distinct_users_threshold",
        "intense_pattern_bonus",
    ),
    "success_after_failures": (
        "enabled",
        "window_minutes",
        "minimum_failures",
        "cooldown_minutes",
        "base_risk",
        "success_bonus",
        "critical_failure_threshold",
        "intense_pattern_bonus",
    ),
    "account_lockout": (
        "enabled",
        "window_minutes",
        "minimum_lockouts",
        "cooldown_minutes",
        "base_risk",
    ),
    "new_ip_for_user": (
        "enabled",
        "window_minutes",
        "minimum_events",
        "cooldown_minutes",
        "base_risk",
    ),
}
SCORING_FIELDS = ("volume_bonus_per_event", "max_volume_bonus", "severity_thresholds")
SEVERITIES = ("low", "medium", "high", "critical")


def canonical(config: dict) -> str:
    return json.dumps(config, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(config: dict) -> str:
    return hashlib.sha256(canonical(config).encode("utf-8")).hexdigest()


def _bounded_number(value: object, name: str, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name}: use un entero entre {minimum} y {maximum}")


def validate_config(config: dict) -> None:
    """El editor solo altera claves conocidas; esto valida también configuraciones iniciales."""
    thresholds = config["risk_scoring"]["severity_thresholds"]
    if set(thresholds) != set(SEVERITIES):
        raise ValueError("Los cuatro niveles de severidad son obligatorios")
    if thresholds["low"] != 0:
        raise ValueError("El umbral bajo debe ser cero")
    for name in SEVERITIES:
        _bounded_number(thresholds[name], name, 0, 100)
    if not (thresholds["low"] < thresholds["medium"] < thresholds["high"] < thresholds["critical"]):
        raise ValueError("Los umbrales de severidad deben ser crecientes")
    for name in ("volume_bonus_per_event", "max_volume_bonus"):
        _bounded_number(config["risk_scoring"][name], name, 0, 100)
    for key, allowed in RULE_FIELDS.items():
        rule = config[key]
        if type(rule["enabled"]) is not bool:
            raise ValueError(f"{key}.enabled: use verdadero o falso")
        for name in allowed:
            if name == "enabled":
                continue
            minimum, maximum = (
                (1, 1440)
                if name == "window_minutes"
                else (
                    (0, 10080)
                    if name == "cooldown_minutes"
                    else (0, 100)
                    if name.endswith("bonus") or name == "base_risk"
                    else (1, 1000)
                )
            )
            _bounded_number(rule[name], f"{key}.{name}", minimum, maximum)
        for minimum_key, critical_key in (
            ("minimum_failures", "critical_failure_threshold"),
            ("minimum_distinct_users", "critical_distinct_users_threshold"),
        ):
            if critical_key in rule and rule[critical_key] < rule[minimum_key]:
                raise ValueError(f"{key}.{critical_key} no puede ser menor que {minimum_key}")


def edited_rule(config: dict, key: str, changes: dict) -> dict:
    if key not in RULE_FIELDS or not changes or set(changes) - set(RULE_FIELDS[key]):
        raise ValueError("Solo puede modificar parámetros de las cinco reglas admitidas")
    updated = copy.deepcopy(config)
    updated[key].update(changes)
    validate_config(updated)
    return updated


def edited_scoring(config: dict, changes: dict) -> dict:
    if not changes or set(changes) - set(SCORING_FIELDS):
        raise ValueError("Parámetros de puntaje no admitidos")
    updated = copy.deepcopy(config)
    for name, value in changes.items():
        if name == "severity_thresholds":
            if not isinstance(value, dict) or set(value) != set(SEVERITIES):
                raise ValueError("Indique los cuatro umbrales de severidad")
        updated["risk_scoring"][name] = value
    validate_config(updated)
    return updated


class RuleConfigStore:
    def __init__(self, store, initial_config: dict):
        self.db = store.connection
        self.store = store
        self.initial_config = initial_config

    def _actor(self, actor: dict) -> None:
        if actor.get("role") != "administrator":
            raise PermissionError("Se requiere rol administrador")
        if actor.get("user_id") == "local":
            return
        row = self.db.execute(
            "SELECT enabled,role FROM platform_users WHERE user_id=?", (actor["user_id"],)
        ).fetchone()
        if row is None or not row["enabled"] or row["role"] != "administrator":
            raise PermissionError("El acceso del administrador ya no está vigente")

    def current(self) -> dict:
        row = self.db.execute(
            "SELECT v.* FROM rule_config_state s JOIN rule_config_versions v "
            "ON v.version_id=s.active_version_id WHERE s.singleton=1"
        ).fetchone()
        if row:
            return {**dict(row), "config": json.loads(row["payload_json"])}
        validate_config(self.initial_config)
        with self.db:
            # La fila de guardia serializa el bootstrap en varios procesos.
            self.db.execute("UPDATE platform_auth_guard SET revision=revision+1 WHERE singleton=1")
            row = self.db.execute(
                "SELECT v.* FROM rule_config_state s JOIN rule_config_versions v "
                "ON v.version_id=s.active_version_id WHERE s.singleton=1"
            ).fetchone()
            if not row:
                version, now = "rv_" + uuid4().hex, utc_now()
                self.db.execute(
                    "INSERT INTO rule_config_versions VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        version,
                        "published",
                        None,
                        canonical(self.initial_config),
                        digest(self.initial_config),
                        "system:initial",
                        "Configuración inicial",
                        now,
                        now,
                    ),
                )
                self.db.execute("INSERT INTO rule_config_state VALUES (1,?)", (version,))
                self._history(
                    "initial",
                    version,
                    None,
                    {"user_id": "system:initial", "display_name": "Sistema"},
                    "Parámetros iniciales desde config/detection_rules.json",
                )
                row = self.db.execute(
                    "SELECT * FROM rule_config_versions WHERE version_id=?", (version,)
                ).fetchone()
        return {**dict(row), "config": json.loads(row["payload_json"])}

    def _history(
        self, action: str, version: str, previous: str | None, actor: dict, justification: str
    ) -> None:
        now = utc_now()
        self.db.execute(
            "INSERT INTO rule_config_history VALUES (?,?,?,?,?,?,?,?)",
            (
                uuid4().hex,
                action,
                version,
                previous,
                actor["user_id"],
                actor["display_name"],
                justification,
                now,
            ),
        )
        AuthStore(self.store, {}).audit(
            actor,
            "rule_" + action,
            version,
            {
                "previous_version": previous,
                "justification": justification,
            },
        )

    def version(self, version_id: str) -> dict:
        row = self.db.execute(
            "SELECT * FROM rule_config_versions WHERE version_id=?", (version_id,)
        ).fetchone()
        if row is None:
            raise KeyError(version_id)
        return {**dict(row), "config": json.loads(row["payload_json"])}

    def versions(self, limit: int = 50) -> list[dict]:
        rows = self.db.execute(
            "SELECT version_id,status,parent_version_id,payload_hash,created_name,"
            "created_at_utc,updated_at_utc FROM rule_config_versions "
            "ORDER BY created_at_utc DESC,version_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def history(self, limit: int = 50) -> list[dict]:
        rows = self.db.execute(
            "SELECT action,version_id,previous_version_id,actor_name,justification,"
            "occurred_at_utc FROM rule_config_history "
            "ORDER BY occurred_at_utc DESC,history_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def create_draft(self, actor: dict) -> dict:
        with self.db:
            self._actor(actor)
            current = self.current()
            version, now = "rv_" + uuid4().hex, utc_now()
            self.db.execute(
                "INSERT INTO rule_config_versions VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    version,
                    "draft",
                    current["version_id"],
                    current["payload_json"],
                    current["payload_hash"],
                    actor["user_id"],
                    actor["display_name"],
                    now,
                    now,
                ),
            )
            self._history(
                "draft_created",
                version,
                current["version_id"],
                actor,
                "Borrador creado desde versión activa",
            )
        return self.version(version)

    def update_draft(
        self, version_id: str, actor: dict, expected_hash: str, section: str, changes: dict
    ) -> dict:
        with self.db:
            self._actor(actor)
            draft = self.version(version_id)
            if draft["status"] != "draft" or draft["payload_hash"] != expected_hash:
                raise ValueError("El borrador cambió o ya fue publicado; vuelva a cargarlo")
            updated = (
                edited_scoring(draft["config"], changes)
                if section == "scoring"
                else edited_rule(draft["config"], section, changes)
            )
            new_hash = digest(updated)
            cursor = self.db.execute(
                "UPDATE rule_config_versions SET payload_json=?,payload_hash=?,updated_at_utc=? "
                "WHERE version_id=? AND status='draft' AND payload_hash=?",
                (canonical(updated), new_hash, utc_now(), version_id, expected_hash),
            )
            if cursor.rowcount != 1:
                raise ValueError("El borrador cambió; vuelva a cargarlo")
            self._history(
                "draft_changed",
                version_id,
                draft["parent_version_id"],
                actor,
                "Parámetros del borrador actualizados: " + section,
            )
        return self.version(version_id)

    def save_preview(
        self,
        draft_id: str,
        actor: dict,
        active_id: str,
        source: str,
        from_utc: str,
        to_utc: str,
        result: dict,
    ) -> dict:
        with self.db:
            self._actor(actor)
            draft = self.version(draft_id)
            if draft["status"] != "draft" or self.current()["version_id"] != active_id:
                raise ValueError("La versión activa cambió; repita la comparación")
            identifier, now = "rp_" + uuid4().hex, utc_now()
            self.db.execute(
                "INSERT INTO rule_config_previews VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    draft_id,
                    draft["payload_hash"],
                    active_id,
                    source,
                    from_utc,
                    to_utc,
                    canonical(result),
                    actor["user_id"],
                    now,
                ),
            )
            self._history("preview", draft_id, active_id, actor, "Simulación histórica: " + source)
        return {"preview_id": identifier, **result}

    def latest_preview(self, draft_id: str) -> dict | None:
        draft = self.version(draft_id)
        active_id = self.current()["version_id"]
        row = self.db.execute(
            "SELECT preview_id,draft_hash,active_version_id,result_json,created_at_utc "
            "FROM rule_config_previews WHERE draft_version_id=? "
            "ORDER BY created_at_utc DESC,preview_id DESC LIMIT 1",
            (draft_id,),
        ).fetchone()
        if (
            not row
            or row["draft_hash"] != draft["payload_hash"]
            or row["active_version_id"] != active_id
        ):
            return None
        return {
            "preview_id": row["preview_id"],
            "created_at_utc": row["created_at_utc"],
            **json.loads(row["result_json"]),
        }

    def publish(
        self, draft_id: str, actor: dict, justification: str, preview_valid_minutes: int
    ) -> dict:
        justification = justification.strip()
        if not 10 <= len(justification) <= 500:
            raise ValueError("Explique la publicación en 10 a 500 caracteres")
        with self.db:
            self.db.execute("UPDATE platform_auth_guard SET revision=revision+1 WHERE singleton=1")
            self._actor(actor)
            active = self.current()
            draft = self.version(draft_id)
            if draft["status"] != "draft" or draft["parent_version_id"] != active["version_id"]:
                raise ValueError("El borrador ya no parte de la versión activa")
            if draft["payload_hash"] == active["payload_hash"]:
                raise ValueError("Modifique algún parámetro antes de publicar")
            validate_config(draft["config"])
            preview = self.db.execute(
                "SELECT draft_hash,active_version_id,created_at_utc "
                "FROM rule_config_previews WHERE draft_version_id=? "
                "ORDER BY created_at_utc DESC,preview_id DESC LIMIT 1",
                (draft_id,),
            ).fetchone()
            if (
                not preview
                or preview["draft_hash"] != draft["payload_hash"]
                or preview["active_version_id"] != active["version_id"]
                or datetime.fromisoformat(preview["created_at_utc"])
                < datetime.now(UTC) - timedelta(minutes=preview_valid_minutes)
            ):
                raise ValueError("Pruebe y compare este borrador antes de publicarlo")
            self.db.execute(
                "UPDATE rule_config_versions SET status='published' WHERE version_id=?", (draft_id,)
            )
            self.db.execute(
                "UPDATE rule_config_state SET active_version_id=? WHERE singleton=1", (draft_id,)
            )
            self._history("published", draft_id, active["version_id"], actor, justification)
        return self.current()

    def rollback(self, target_id: str, actor: dict, justification: str) -> dict:
        justification = justification.strip()
        if not 10 <= len(justification) <= 500:
            raise ValueError("Explique la restauración en 10 a 500 caracteres")
        with self.db:
            self.db.execute("UPDATE platform_auth_guard SET revision=revision+1 WHERE singleton=1")
            self._actor(actor)
            active = self.current()
            target = self.version(target_id)
            if target["status"] != "published" or target_id == active["version_id"]:
                raise ValueError("Seleccione una versión publicada anterior")
            self.db.execute(
                "UPDATE rule_config_state SET active_version_id=? WHERE singleton=1", (target_id,)
            )
            self._history("restored", target_id, active["version_id"], actor, justification)
        return self.current()
