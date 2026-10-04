import json
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from test_alert_store import sample_alert

import practicum_soc.api.routes.auth as auth_web
import practicum_soc.main as web_app
from practicum_soc.core.auth_config import AuthSettings
from practicum_soc.integrations.oidc import OIDCClient
from practicum_soc.repositories.alerts import AlertStore
from practicum_soc.repositories.auth import AuthStore, fingerprint
from practicum_soc.services.dashboard import DashboardService

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("SOC_AUTH_MODE", "oidc")
    monkeypatch.setenv("SOC_PUBLIC_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("SOC_OIDC_ISSUER", "http://127.0.0.1:8080/realms/soc")
    monkeypatch.setenv("SOC_OIDC_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("SOC_STORAGE_BACKEND", "sqlite")
    return AuthSettings.from_env()


def claims(subject="operator-1", role="analyst"):
    return {
        "iss": "http://127.0.0.1:8080/realms/soc",
        "sub": subject,
        "preferred_username": subject,
        "soc_roles": [role],
    }


@pytest.fixture
def db(tmp_path, config):
    return tmp_path / "auth.db"


def create_session(db, config, subject="operator-1", role="analyst"):
    with AlertStore(db) as store:
        auth = AuthStore(store, config.policy)
        token = auth.login(claims(subject, role))
        return token, auth.session(token)


@pytest.fixture
def client(db, config, monkeypatch, tmp_path):
    monkeypatch.setattr(web_app.app.state, "soc_state_db", db)
    monkeypatch.setattr(
        web_app.app.state,
        "dashboard_service",
        DashboardService(
            state_db=db,
            analysis_dir=tmp_path / "analysis",
            detection_config=ROOT / "config/detection_rules.json",
            operational_config=ROOT / "config/operational.json",
        ),
    )
    return TestClient(web_app.app, base_url="http://127.0.0.1:8000")


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/alerts",
        "/services",
        "/dashboard",
        "/reports/latest",
        "/health",
        "/api/dashboard-version",
        "/api/services-version",
        "/api/v1/alerts",
        "/api/v1/services",
        "/api/v1/dashboard/snapshot",
        "/api/v1/dashboard/stream",
        "/api/v1/operations/metrics",
        "/admin/users",
        "/admin/configuration",
        "/docs",
        "/openapi.json",
        "/auth/me",
    ],
)
def test_private_routes_require_session(client, path):
    assert client.get(path, follow_redirects=False).status_code == 401


def test_browser_is_sent_to_login(client):
    response = client.get("/", headers={"Accept": "text/html"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/auth/login"


def test_technical_metrics_require_administrator(client, db, config):
    token, _ = create_session(db, config, role="analyst")
    client.cookies.set("soc_session", token)
    assert client.get("/api/v1/dashboard/snapshot").status_code == 200
    assert client.get("/api/v1/operations/metrics").status_code == 403


def test_versioned_api_authentication_and_rate_limit_envelope(client, db, config, monkeypatch):
    response = client.get("/api/v1/alerts", headers={"Accept": "text/html"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    config.policy["rate_limits"]["browse"] = {"requests": 1, "window_seconds": 60}
    monkeypatch.setattr(auth_web, "settings", lambda request: config)
    token, _ = create_session(db, config)
    client.cookies.set("soc_session", token)
    assert client.get("/api/v1/alerts").status_code == 200
    limited = client.get("/api/v1/services")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert "Retry-After" in limited.headers


def test_case_views_audited_without_inventing_actor_or_counting_missing_cases(client, db, config):
    token, user = create_session(db, config)
    with AlertStore(db) as store:
        store.insert_alert(sample_alert())
    client.cookies.set("soc_session", token)
    assert client.get("/alerts/alt_1?actor_id=forged").status_code == 200
    assert client.get("/alerts/missing").status_code == 404
    with AlertStore(db) as store:
        rows = store.connection.execute(
            "SELECT actor_id, target_id FROM platform_audit WHERE action = 'case_viewed'"
        ).fetchall()
    assert [(row["actor_id"], row["target_id"]) for row in rows] == [(user["user_id"], "alt_1")]


def test_rate_limit_is_per_user_and_returns_retry_header(client, db, config, monkeypatch):
    config.policy["rate_limits"]["case_update"] = {"requests": 2, "window_seconds": 60}
    monkeypatch.setattr(web_app.app.state, "auth_settings", config, raising=False)
    token, user = create_session(db, config)
    with AlertStore(db) as store:
        store.insert_alert(sample_alert())
    client.cookies.set("soc_session", token)
    headers = {"X-CSRF-Token": user["csrf_token"]}
    for status in ("investigating", "resolved"):
        assert (
            client.patch(
                "/alerts/alt_1/status", json={"status": status}, headers=headers
            ).status_code
            == 200
        )
    response = client.patch("/alerts/alt_1/status", json={"status": "new"}, headers=headers)
    assert response.status_code == 429 and 1 <= int(response.headers["Retry-After"]) <= 60
    assert response.headers["Cache-Control"] == "no-store"
    token, other = create_session(db, config, "another")
    client.cookies.set("soc_session", token)
    assert (
        client.patch(
            "/alerts/alt_1/status",
            json={"status": "new"},
            headers={"X-CSRF-Token": other["csrf_token"]},
        ).status_code
        == 200
    )


def test_login_rate_limit_does_not_trust_forwarded_header(client, config, monkeypatch):
    config.policy["rate_limits"]["login"] = {"requests": 1, "window_seconds": 60}
    monkeypatch.setattr(web_app.app.state, "auth_settings", config, raising=False)
    monkeypatch.setattr(auth_web.OIDCClient, "authorize_url", lambda *args: config.issuer)
    assert client.get("/auth/login", follow_redirects=False).status_code == 303
    assert (
        client.get(
            "/auth/login", headers={"X-Forwarded-For": "192.0.2.1"}, follow_redirects=False
        ).status_code
        == 429
    )


def test_polling_does_not_extend_idle_session(client, db, config):
    token, _ = create_session(db, config)
    old_seen = int(time.time()) - 20
    with AlertStore(db) as store:
        with store.connection:
            store.connection.execute("UPDATE platform_sessions SET last_seen = ?", (old_seen,))
    client.cookies.set("soc_session", token)
    assert client.get("/api/dashboard-version").status_code == 200
    with AlertStore(db) as store:
        assert (
            store.connection.execute("SELECT last_seen FROM platform_sessions").fetchone()[
                "last_seen"
            ]
            == old_seen
        )
    assert client.get("/auth/me").status_code == 200
    with AlertStore(db) as store:
        assert (
            store.connection.execute("SELECT last_seen FROM platform_sessions").fetchone()[
                "last_seen"
            ]
            > old_seen
        )


def test_configuration_audit_admin_only_and_hides_values(client, db, config, tmp_path, monkeypatch):
    directory = tmp_path / "config"
    directory.mkdir()
    for filename in ("auth.json", "detection_rules.json", "operational.json"):
        (directory / filename).write_text('{"private":"sensitive-example"}')
    monkeypatch.setattr(web_app.app.state, "config_dir", directory)
    token, _ = create_session(db, config)
    client.cookies.set("soc_session", token)
    assert client.get("/admin/configuration").status_code == 403
    token, _ = create_session(db, config, "admin", "administrator")
    client.cookies.set("soc_session", token)
    response = client.get("/admin/configuration")
    assert response.status_code == 200 and "sensitive-example" not in response.text
    assert client.get("/admin/configuration").status_code == 200
    (directory / "detection_rules.json").write_text('{"private":"different-sensitive-example"}')
    assert client.get("/admin/configuration").status_code == 200
    with AlertStore(db) as store:
        audit = AuthStore(store, config.policy).audit_entries()
    baselines = [item for item in audit if item["action"] == "configuration_baseline"]
    changes = [item for item in audit if item["action"] == "configuration_change_detected"]
    assert len(baselines) == 3 and len(changes) == 1
    assert json.loads(changes[0]["details_json"])["change_author"] == "unknown_external"
    assert "sensitive-example" not in json.dumps(audit)


def test_csrf_authorization_and_actor_cannot_be_forged(client, db, config):
    token, user = create_session(db, config)
    with AlertStore(db) as store:
        store.insert_alert(sample_alert())
    client.cookies.set("soc_session", token)
    assert client.get("/admin/users").status_code == 403
    assert (
        client.patch(
            "/admin/users/any", json={"role": "administrator", "enabled": True}
        ).status_code
        == 403
    )
    body = {"status": "investigating", "note": "Prueba", "actor_id": "forged"}
    assert client.patch("/alerts/alt_1/status", json=body).status_code == 403
    headers = {"X-CSRF-Token": user["csrf_token"]}
    assert (
        client.patch(
            "/alerts/alt_1/status", json=body, headers={**headers, "Origin": "http://evil.example"}
        ).status_code
        == 403
    )
    assert client.patch("/alerts/alt_1/status", json=body, headers=headers).status_code == 200
    with AlertStore(db) as store:
        last = store.alert_history("alt_1")[-1]
        assert last["actor_id"] == user["user_id"] and last["actor_name"] == "operator-1"
        assert (
            AuthStore(store, config.policy).audit_entries()[0]["action"] == "alert_status_changed"
        )


def test_admin_changes_role_revokes_sessions_and_protects_last_admin(client, db, config):
    token, admin = create_session(db, config, "admin-1", "administrator")
    other_token, analyst = create_session(db, config)
    client.cookies.set("soc_session", token)
    headers = {"X-CSRF-Token": admin["csrf_token"]}
    assert client.get("/admin/users").status_code == 200
    response = client.patch(
        f"/admin/users/{analyst['user_id']}",
        json={"role": "analyst", "enabled": False},
        headers=headers,
    )
    assert response.status_code == 200
    with AlertStore(db) as store:
        assert AuthStore(store, config.policy).session(other_token) is None
        with pytest.raises(PermissionError):
            AuthStore(store, config.policy).login(claims())
    assert (
        client.patch(
            f"/admin/users/{admin['user_id']}",
            json={"role": "analyst", "enabled": True},
            headers=headers,
        ).status_code
        == 409
    )


def test_expiry_unknown_role_and_logout(db, config):
    token, user = create_session(db, config)
    with AlertStore(db) as store:
        auth = AuthStore(store, config.policy)
        with pytest.raises(PermissionError):
            auth.login(claims("unknown", "reader"))
        with store.connection:
            store.connection.execute("UPDATE platform_sessions SET expires_at = 0")
        assert auth.session(token) is None
        token = auth.login(claims())
        with store.connection:
            store.connection.execute("UPDATE platform_sessions SET last_seen = 0")
        assert auth.session(token) is None
        token = auth.login(claims())
        auth.logout(token, user)
        assert auth.session(token) is None
        assert (
            store.connection.execute("SELECT COUNT(*) AS n FROM normalized_events").fetchone()["n"]
            == 0
        )


@pytest.mark.parametrize("secure", [False, True])
def test_callback_binding_replay_and_cookie_flags(client, db, config, monkeypatch, secure):
    if secure:
        config = replace(config, public_url="https://soc.example.test")
        monkeypatch.setattr(web_app.app.state, "auth_settings", config, raising=False)
        client = TestClient(web_app.app, base_url=config.public_url)

    class FakeOIDC:
        def __init__(self, settings):
            pass

        def authorize_url(self, state, nonce, verifier):
            return "http://127.0.0.1:8080/auth?state=" + state

        def exchange(self, code, nonce, verifier):
            return claims()

        def logout_url(self):
            return config.public_url + "/auth/logged-out"

    monkeypatch.setattr(auth_web, "OIDCClient", FakeOIDC)
    response = client.get("/auth/login", follow_redirects=False)
    assert "HttpOnly" in response.headers["set-cookie"]
    state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
    attacker = TestClient(web_app.app, base_url=config.public_url)
    assert attacker.get(f"/auth/callback?code=x&state={state}").status_code == 403
    callback_url = f"/auth/callback?code=x&state={state}"
    response = client.get(callback_url, follow_redirects=False)
    assert response.status_code == 303
    assert (
        "HttpOnly" in response.headers["set-cookie"]
        and "SameSite=lax" in response.headers["set-cookie"]
    )
    assert ("Secure" in response.headers["set-cookie"]) is secure
    token = client.cookies.get("soc_session")
    with AlertStore(db) as store:
        stored = store.connection.execute("SELECT token_hash FROM platform_sessions").fetchone()[
            "token_hash"
        ]
        assert stored == fingerprint(token) and stored != token
    assert client.get(callback_url, follow_redirects=False).status_code == 403
    user = client.get("/auth/me").json()
    assert (
        client.post("/auth/logout", headers={"X-CSRF-Token": user["csrf_token"]}).status_code == 200
    )
    assert client.get("/auth/me").status_code == 401


@pytest.mark.parametrize(
    "bad", ["valid", "issuer", "audience", "expired", "nonce", "signature", "algorithm"]
)
def test_rejects_invalid_id_tokens(config, monkeypatch, bad):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="key-1", use="sig")
    data = {
        **claims(),
        "aud": "soc-web",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "nonce": "expected",
    }
    if bad == "issuer":
        data["iss"] = "https://wrong.example"
    if bad == "audience":
        data["aud"] = "other"
    if bad == "expired":
        data["exp"] = int(time.time()) - 3600
    if bad == "nonce":
        data["nonce"] = "wrong"
    signing = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if bad == "signature"
        else key
    )
    token = jwt.encode(
        data,
        "x" * 40 if bad == "algorithm" else signing,
        algorithm="HS256" if bad == "algorithm" else "RS256",
        headers={"kid": "key-1"},
    )
    provider = OIDCClient(config)
    monkeypatch.setattr(
        provider,
        "metadata",
        lambda: {"token_endpoint": config.issuer + "/token", "jwks_uri": config.issuer + "/keys"},
    )
    monkeypatch.setattr(
        provider,
        "request_json",
        lambda url, data=None: {"id_token": token} if data else {"keys": [jwk]},
    )
    if bad == "valid":
        assert provider.exchange("code", "expected", "verifier")["sub"] == data["sub"]
    else:
        with pytest.raises((ValueError, jwt.InvalidTokenError)):
            provider.exchange("code", "expected", "verifier")
