"""Controles de producción con cuerpos, hosts y sesiones sintéticos."""

import asyncio
import time

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from test_auth import claims

from practicum_soc import main
from practicum_soc.api.routes import auth
from practicum_soc.api.security import SecurityMiddleware
from practicum_soc.core.auth_config import AuthSettings
from practicum_soc.core.security import SecurityPolicy
from practicum_soc.repositories.alerts import AlertStore
from practicum_soc.repositories.auth import AuthStore
from practicum_soc.schemas.alerts import StatusUpdate
from practicum_soc.schemas.auth import UserAccessUpdate


@pytest.fixture
def production(monkeypatch):
    for name, value in {
        "SOC_ENV": "production",
        "SOC_AUTH_MODE": "oidc",
        "SOC_PUBLIC_URL": "https://soc.example.edu",
        "SOC_OIDC_ISSUER": "https://identity.example.edu/realms/soc",
        "SOC_OIDC_INTERNAL_ORIGIN": "",
        "SOC_OIDC_CLIENT_SECRET": "synthetic-oidc-secret-at-least-32-chars",
        "SOC_CURSOR_SECRET": "synthetic-cursor-secret-at-least-32-chars",
        "SOC_ALLOWED_HOSTS": "soc.example.edu",
        "SOC_STORAGE_BACKEND": "postgres",
        "SOC_STORAGE_HOST": "postgres",
    }.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize(
    "name,value",
    [
        ("SOC_AUTH_MODE", "disabled"),
        ("SOC_PUBLIC_URL", "http://soc.example.edu"),
        ("SOC_OIDC_ISSUER", "http://identity.example.edu"),
        ("SOC_OIDC_INTERNAL_ORIGIN", "http://keycloak:8080"),
        ("SOC_STORAGE_BACKEND", "sqlite"),
        ("SOC_CURSOR_SECRET", "short"),
        ("SOC_OIDC_CLIENT_SECRET", "short"),
        ("SOC_ALLOWED_HOSTS", "*"),
        ("SOC_ALLOWED_HOSTS", "attacker.example"),
        ("SOC_STORAGE_HOST", "external-database"),
    ],
)
def test_insecure_production_fails_before_opening_database(production, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        main.create_app()


def test_production_host_https_headers_and_private_docs(production):
    application = main.create_app()
    assert not any(
        getattr(route, "path", None) in {"/docs", "/redoc", "/openapi.json"}
        for route in application.routes
    )
    client = TestClient(application, base_url="https://soc.example.edu")
    response = client.get("/static/styles.css")
    assert response.status_code == 200
    assert "max-age=" in response.headers["Strict-Transport-Security"]
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert client.get("/static/styles.css", headers={"Host": "attacker.example"}).status_code == 400
    assert TestClient(application, base_url="http://soc.example.edu").get("/").status_code == 403


def test_local_api_documentation_keeps_its_existing_assets(monkeypatch):
    monkeypatch.setenv("SOC_ENV", "local")
    monkeypatch.setenv("SOC_AUTH_MODE", "disabled")
    client = TestClient(main.create_app())
    for path in ("/docs", "/redoc"):
        response = client.get(path)
        assert response.status_code == 200
        assert "Content-Security-Policy" not in response.headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in client.get("/static/styles.css").headers


def test_production_demo_disabled_even_for_administrator(production, monkeypatch):
    application = main.create_app()
    operator = {"user_id": "synthetic", "role": "administrator", "csrf_token": "synthetic"}
    monkeypatch.setattr(auth, "current_session", lambda *args: operator)
    monkeypatch.setattr(auth, "consume_request_limit", lambda *args: 0)
    client = TestClient(application, base_url="https://soc.example.edu")
    assert client.post("/demo/run", headers={"X-CSRF-Token": "synthetic"}).status_code == 404


def body_application():
    application = FastAPI()
    policy = SecurityPolicy.load().model_copy(update={"maximum_request_bytes": 1024})
    application.add_middleware(SecurityMiddleware, policy=policy)

    @application.post("/echo")
    async def echo(request: Request):
        return {"bytes": len(await request.body())}

    @application.get("/broken")
    async def broken():
        raise RuntimeError("synthetic-secret-must-not-appear")

    return application


def test_body_and_query_limits_and_safe_exception():
    client = TestClient(body_application(), raise_server_exceptions=False)
    assert client.post("/echo", content=b"x" * 1024).json() == {"bytes": 1024}
    assert client.post("/echo", content=b"x" * 1025).status_code == 413
    assert client.post("/echo", content=b"x", headers={"Content-Length": "-1"}).status_code == 400
    assert client.post("/echo", content=b"x", headers={"Content-Length": "2"}).status_code == 400
    assert (
        client.post(
            "/echo", content=b"x", headers={"Content-Length": "1", "Transfer-Encoding": "chunked"}
        ).status_code
        == 400
    )
    assert client.get("/broken?q=" + "x" * 16385).status_code == 414
    response = client.get("/broken")
    assert response.status_code == 503
    assert "synthetic-secret" not in response.text
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_chunked_body_is_limited_without_trusting_content_length():
    async def run():
        app = body_application()
        chunks = iter([b"x" * 700, b"x" * 700])
        messages = []

        async def receive():
            return {"type": "http.request", "body": next(chunks), "more_body": True}

        async def send(message):
            messages.append(message)

        await app(
            {
                "type": "http",
                "method": "POST",
                "path": "/echo",
                "query_string": b"",
                "scheme": "https",
                "headers": [],
                "http_version": "1.1",
            },
            receive,
            send,
        )
        assert messages[0]["status"] == 413

    asyncio.run(run())


def test_no_per_request_session_write_and_idle_expiry(tmp_path):
    policy = AuthSettings.from_env().policy
    with AlertStore(tmp_path / "session.db") as store:
        manager = AuthStore(store, policy)
        token = manager.login(claims())
        before = store.connection.total_changes
        for _ in range(100):
            assert manager.session(token)
        assert store.connection.total_changes == before
        with store.connection:
            store.connection.execute(
                "UPDATE platform_sessions SET last_seen = ?", (int(time.time()) - 20,)
            )
        before = store.connection.total_changes
        assert manager.session(token)
        assert store.connection.total_changes == before + 1
        with store.connection:
            store.connection.execute("UPDATE platform_sessions SET last_seen=0")
        assert manager.session(token) is None


def test_mass_assignment_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        UserAccessUpdate(role="analyst", enabled=True, user_id="forged")
    # Se conserva el contrato previo: campos desconocidos no llegan al servicio.
    update = StatusUpdate(status="resolved", risk_score=0, actor_id="forged")
    assert update.model_dump() == {"status": "resolved", "note": ""}


def test_loopback_readiness_remains_compatible_with_docker(production, monkeypatch, tmp_path):
    from practicum_soc.api.routes import monitoring

    monkeypatch.setattr(monitoring, "open_store", lambda _: AlertStore(tmp_path / "readiness.db"))
    client = TestClient(main.create_app(), base_url="http://127.0.0.1:8000")
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/static/styles.css").status_code == 403


def test_slow_body_has_finite_timeout():
    async def run():
        messages = []
        policy = SecurityPolicy.load().model_copy(update={"request_body_timeout_seconds": 0.01})
        middleware = SecurityMiddleware(FastAPI(), policy)

        async def receive():
            await asyncio.sleep(0.03)
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await middleware(
            {
                "type": "http",
                "path": "/",
                "method": "POST",
                "scheme": "http",
                "headers": [],
            },
            receive,
            send,
        )
        assert messages[0]["status"] == 408

    asyncio.run(run())


def test_sql_filters_bind_hostile_values(tmp_path):
    from test_alert_store import sample_alert

    from practicum_soc.core.cursor import CursorCodec
    from practicum_soc.repositories.browsing import BrowseRepository
    from practicum_soc.schemas.browsing import AlertQuery

    with AlertStore(tmp_path / "sql.db") as store:
        store.insert_alert(sample_alert())
        rows, _ = BrowseRepository(store).alerts(
            AlertQuery(rule_id="' OR 1=1; DROP TABLE alerts; --"),
            "legacy",
            CursorCodec("synthetic-security-sql", {}),
        )
        assert rows == []
        assert store.connection.execute("SELECT COUNT(*) AS n FROM alerts").fetchone()["n"] == 1
