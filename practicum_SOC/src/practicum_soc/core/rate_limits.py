"""Límites de ventana fija, compartidos por procesos y persistentes entre reinicios."""

import time

from practicum_soc.repositories.auth import fingerprint


def request_scope(method: str, path: str) -> str | None:
    if path.startswith("/api/v1/"):
        path = path[len("/api/v1") :]
    if path in {"/alerts", "/services"}:
        return "browse"
    if path == "/dashboard/stream":
        return "live_stream"
    if path == "/dashboard/snapshot":
        return "live_snapshot"
    if path == "/operations/metrics":
        return "operations_metrics"
    if path == "/auth/login":
        return "login"
    if path == "/auth/callback":
        return "callback"
    if path.startswith("/admin/users"):
        return "user_management"
    if path == "/admin/configuration":
        return "configuration"
    if path.startswith("/admin/rules") or path.startswith("/admin/rule-config"):
        return "rule_preview" if path.endswith("/preview") else "rule_management"
    if path.startswith("/alerts/"):
        return "case_update" if method == "PATCH" else "case_view"
    return {
        "/reports/latest": "report",
        "/demo/run": "demo",
        "/auth/logout": "logout",
    }.get(path)


def consume(store, scope: str, subject: str, policy: dict, *, now: int | None = None) -> int:
    """Devuelve segundos de espera o cero. El incremento es atómico en ambos motores."""
    now = int(time.time()) if now is None else now
    limit = policy["rate_limits"][scope]
    maximum, seconds = int(limit["requests"]), int(limit["window_seconds"])
    if maximum < 1 or seconds < 1:
        raise ValueError("Los límites deben ser positivos")
    started = now - now % seconds
    expires = started + seconds
    with store.connection:
        store.connection.execute("DELETE FROM platform_rate_limits WHERE expires_at <= ?", (now,))
        row = store.connection.execute(
            "INSERT INTO platform_rate_limits(scope, subject_hash, window_started, hits, expires_at) "
            "VALUES (?, ?, ?, 1, ?) ON CONFLICT (scope, subject_hash, window_started) "
            "DO UPDATE SET hits = platform_rate_limits.hits + 1 "
            "WHERE platform_rate_limits.hits < ? RETURNING hits",
            (scope, fingerprint(subject), started, expires, maximum),
        ).fetchone()
    return expires - now if row is None else 0
