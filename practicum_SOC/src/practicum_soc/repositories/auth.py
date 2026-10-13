"""Sesiones revocables, operadores y auditoría sobre el almacenamiento propio."""

import hashlib
import json
import secrets
import time
from uuid import uuid4

from practicum_soc.repositories.alerts import utc_now


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class AuthStore:
    def __init__(self, store, policy):
        self.store = store
        self.db = store.connection
        self.policy = policy

    def audit(self, actor, action: str, target: str, details=None):
        self.db.execute(
            "INSERT INTO platform_audit VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                uuid4().hex,
                actor["user_id"],
                actor["display_name"],
                action,
                target,
                json.dumps(details or {}, ensure_ascii=False),
                utc_now(),
            ),
        )

    def begin_login(self):
        now = int(time.time())
        state, browser, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
        with self.db:
            self.db.execute("DELETE FROM oidc_login_attempts WHERE expires_at <= ?", (now,))
            self.db.execute("DELETE FROM platform_sessions WHERE expires_at <= ?", (now,))
            count = self.db.execute("SELECT COUNT(*) AS n FROM oidc_login_attempts").fetchone()["n"]
            if count >= self.policy["maximum_pending_logins"]:
                raise ValueError("Demasiados inicios de sesión pendientes")
            self.db.execute(
                "INSERT INTO oidc_login_attempts VALUES (?, ?, ?, ?, ?)",
                (
                    fingerprint(state),
                    fingerprint(browser),
                    nonce,
                    verifier,
                    now + self.policy["login_attempt_seconds"],
                ),
            )
        return state, browser, nonce, verifier

    def consume_login(self, state: str, browser: str):
        with self.db:
            row = self.db.execute(
                "DELETE FROM oidc_login_attempts WHERE state_hash = ? AND browser_hash = ? "
                "AND expires_at > ? RETURNING nonce, verifier",
                (fingerprint(state), fingerprint(browser), int(time.time())),
            ).fetchone()
        if row is None:
            raise ValueError("Solicitud de autenticación inválida o caducada")
        return dict(row)

    def login(self, claims: dict):
        roles = claims.get("soc_roles", [])
        if not isinstance(roles, list):
            raise PermissionError("Rol no autorizado")
        role = next((role for role in ("administrator", "analyst") if role in roles), None)
        if role is None:
            raise PermissionError("Rol no autorizado")
        user_id = fingerprint(claims["iss"] + "|" + claims["sub"])
        name = str(claims.get("preferred_username") or claims["sub"])[:150]
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = int(time.time())
        with self.db:
            self.db.execute(
                "INSERT INTO platform_users VALUES (?, ?, ?, ?, ?, 1, ?) "
                "ON CONFLICT (issuer, subject) DO NOTHING",
                (user_id, claims["iss"], claims["sub"], name, role, utc_now()),
            )
            user = dict(
                self.db.execute(
                    "SELECT * FROM platform_users WHERE user_id = ?", (user_id,)
                ).fetchone()
            )
            if not user["enabled"]:
                raise PermissionError("Acceso deshabilitado")
            self.db.execute(
                "INSERT INTO platform_sessions VALUES (?, ?, ?, ?, ?)",
                (
                    fingerprint(token),
                    user_id,
                    csrf,
                    now + self.policy["session_absolute_seconds"],
                    now,
                ),
            )
            self.audit(user, "login", user_id)
        return token

    def session(self, token: str, *, touch: bool = True):
        now = int(time.time())
        row = self.db.execute(
            "SELECT u.*, s.csrf_token, s.expires_at, s.last_seen FROM platform_sessions s "
            "JOIN platform_users u ON u.user_id = s.user_id "
            "WHERE s.token_hash = ? AND s.expires_at > ? AND s.last_seen > ? AND u.enabled = 1",
            (fingerprint(token), now, now - self.policy["session_idle_seconds"]),
        ).fetchone()
        if row is None:
            return None
        if touch and row["last_seen"] <= now - self.policy["session_touch_interval_seconds"]:
            with self.db:
                self.db.execute(
                    "UPDATE platform_sessions SET last_seen = ? WHERE token_hash = ? AND last_seen <= ?",
                    (now, fingerprint(token), now - self.policy["session_touch_interval_seconds"]),
                )
        return dict(row)

    def logout(self, token: str, actor):
        with self.db:
            self.db.execute(
                "DELETE FROM platform_sessions WHERE token_hash = ?", (fingerprint(token),)
            )
            self.audit(actor, "logout", actor["user_id"])

    def users(self):
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT user_id, display_name, role, enabled, created_at_utc FROM platform_users "
                "ORDER BY display_name LIMIT ?",
                (self.policy["users_page_limit"],),
            ).fetchall()
        ]

    def update_user(self, user_id: str, role: str, enabled: bool, actor):
        if actor["role"] != "administrator":
            raise PermissionError("Solo el administrador puede gestionar usuarios")
        if role not in {"administrator", "analyst"}:
            raise ValueError("Rol inválido")
        with self.db:
            # Serializa cambios de administradores también entre procesos.
            self.db.execute(
                "UPDATE platform_auth_guard SET revision = revision + 1 WHERE singleton = 1"
            )
            if actor["user_id"] != "local":
                acting_user = self.db.execute(
                    "SELECT role, enabled FROM platform_users WHERE user_id = ?",
                    (actor["user_id"],),
                ).fetchone()
                if (
                    not acting_user
                    or not acting_user["enabled"]
                    or acting_user["role"] != "administrator"
                ):
                    raise PermissionError("El acceso del administrador ya no está vigente")
            current = self.db.execute(
                "SELECT * FROM platform_users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if current is None:
                raise KeyError(user_id)
            if (
                current["role"] == "administrator"
                and current["enabled"]
                and (role != "administrator" or not enabled)
            ):
                count = self.db.execute(
                    "SELECT COUNT(*) AS n FROM platform_users WHERE role = 'administrator' AND enabled = 1"
                ).fetchone()["n"]
                if count <= 1:
                    raise ValueError("Debe conservarse al menos un administrador activo")
            self.db.execute(
                "UPDATE platform_users SET role = ?, enabled = ? WHERE user_id = ?",
                (role, int(enabled), user_id),
            )
            self.db.execute("DELETE FROM platform_sessions WHERE user_id = ?", (user_id,))
            self.audit(
                actor,
                "user_access_changed",
                user_id,
                {
                    "previous": {"role": current["role"], "enabled": bool(current["enabled"])},
                    "current": {"role": role, "enabled": enabled},
                },
            )

    def audit_entries(self, actions: tuple[str, ...] = ()):
        where = " WHERE action IN (" + ",".join("?" for _ in actions) + ")" if actions else ""
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT actor_name, action, target_id, details_json, occurred_at_utc "
                "FROM platform_audit"
                + where
                + " ORDER BY occurred_at_utc DESC, audit_id DESC LIMIT ?",
                (*actions, self.policy["audit_page_limit"]),
            ).fetchall()
        ]
