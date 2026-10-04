"""Prueba Docker aislada con datos ficticios; no usa .env ni la red UTPL."""

from __future__ import annotations

import base64
import json
import os
import secrets
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, urlopen

ROOT = Path(__file__).resolve().parents[1]


def expect_denied(browser, url, status):
    try:
        browser.open(url)
    except HTTPError as error:
        assert error.code == status
    else:
        raise AssertionError("El acceso debía rechazarse")


def available_ports():
    sockets = [socket.socket() for _ in range(3)]
    try:
        for listener in sockets:
            listener.bind(("127.0.0.1", 0))
        return [str(listener.getsockname()[1]) for listener in sockets]
    finally:
        for listener in sockets:
            listener.close()


def wait_json(url: str, authorization: str = "") -> dict:
    for _ in range(30):
        try:
            headers = {"Authorization": authorization} if authorization else {}
            with urlopen(Request(url, headers=headers), timeout=5) as response:
                return json.load(response)
        except (OSError, ValueError):
            time.sleep(2)
    raise RuntimeError(f"Servicio de prueba no disponible: {url}")


def main() -> None:
    project = "soc-smoke-" + secrets.token_hex(5)
    node = os.environ.get("SOC_SMOKE_NODE", "node")
    browser_channel = os.environ.get("SOC_BROWSER_CHANNEL", "msedge")
    environment = os.environ.copy()
    for name in list(environment):
        if name.startswith(("SOC_", "GRAFANA_")):
            environment.pop(name)
    for name in (
        "SOC_POSTGRES_PASSWORD",
        "SOC_APP_PASSWORD",
        "SOC_GRAFANA_PASSWORD",
        "GRAFANA_ADMIN_PASSWORD",
        "SOC_PSEUDONYM_KEY",
        "SOC_IDP_DB_PASSWORD",
        "SOC_IDP_ADMIN_PASSWORD",
        "SOC_OIDC_CLIENT_SECRET",
        "SOC_BOOTSTRAP_ADMIN_PASSWORD",
        "SOC_BOOTSTRAP_ANALYST_PASSWORD",
    ):
        environment[name] = secrets.token_hex(32)
    web_port, grafana_port, idp_port = available_ports()
    web_url, grafana_url, idp_url = (
        "http://127.0.0.1:" + port for port in (web_port, grafana_port, idp_port)
    )
    environment.update(
        SOC_WEB_PORT=web_port,
        SOC_GRAFANA_PORT=grafana_port,
        SOC_IDP_PORT=idp_port,
        SOC_SMOKE_WEB_URL=web_url,
        SOC_SMOKE_IDP_URL=idp_url,
        SOC_SMOKE_GRAFANA_URL=grafana_url,
        SOC_SMOKE_MUTATIONS="yes",
        SOC_SMOKE_SCREENSHOTS=str(ROOT / "analysis" / "sprint5-ui"),
        SOC_BROWSER_CHANNEL=browser_channel,
    )
    base = ["docker", "compose", "--env-file", ".env.docker.example", "-p", project]

    def compose(*args: str, capture=False, stdin=None):
        return subprocess.run(
            [*base, *args],
            cwd=ROOT,
            env=environment,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            input=stdin,
            capture_output=capture,
            timeout=900,
        )

    try:
        compose("config", "--quiet")
        compose("up", "-d", "--build", "web", "grafana")
        assert wait_json(web_url + "/healthz")["status"] == "ok"
        expect_denied(build_opener(), web_url + "/alerts", 401)
        seed = """
from pathlib import Path
from practicum_soc.repositories.factory import open_store
with open_store(Path('unused.db')) as store:
    for index in range(32):
        alert = dict(alert_id=f'synthetic_{index:02}', rule_id='AUTH_TEST',
                     rule_name='Regla sintética', severity='high', risk_score=75,
                     first_seen_local='2026-03-16T10:00:00-05:00',
                     last_seen_local='2026-03-16T10:00:00-05:00',
                     relying_parties=f'app_{index:02}', description='Prueba de navegación.')
        assert store.insert_alert(alert, source_name='csv_demo_mvp')[0]
        event = dict(source_event_id=f'page_{index}', event_time_utc='2026-03-16T15:00:25+00:00',
                     event_class='success', event_count=1, relying_party=f'app_{index:02}',
                     user_key='usr_synthetic', client_ip_key='ip_synthetic')
        assert store.insert_event(event, event['event_time_utc'], str(index), True, 'csv_demo_mvp')
"""
        compose("exec", "-T", "web", "python", "-c", seed)
        analytics_seed = """
from pathlib import Path
from practicum_soc.repositories.factory import open_store
with open_store(Path('unused.db')) as store:
    for day in (14,15,16,17,18,19,20,21,22):
        for hour in range(8,20):
            item = dict(source_event_id=f'history-{day}-{hour}',
                        event_time_utc=f'2026-03-{day:02}T{hour:02}:00:00-05:00',
                        event_class='failure' if hour==12 else 'success',
                        event_count=(100 if day<21 else 180),
                        relying_party='app_00',user_key='usr_synthetic',client_ip_key='ip_synthetic')
            store.insert_event(item,item['event_time_utc'],item['source_event_id'],True,'csv_demo_mvp')
    item=dict(alert_id='synthetic_oscillation',rule_id='AUTH_TEST',rule_name='Oscilación sintética',
              severity='high',risk_score=75,first_seen_local='2026-03-21T12:00:00-05:00',
              last_seen_local='2026-03-21T12:15:00-05:00',relying_parties='app_00',description='Caso de prueba')
    store.insert_alert(item,source_name='csv_demo_mvp')
"""
        compose("exec", "-T", "web", "python", "-c", analytics_seed)
        subprocess.run(
            [node, str(ROOT / "tools/verify_oidc_browser.cjs")],
            env=environment,
            check=True,
            timeout=120,
        )
        token = base64.b64encode(f"admin:{environment['GRAFANA_ADMIN_PASSWORD']}".encode()).decode()
        auth = "Basic " + token
        wait_json(grafana_url + "/api/health")
        dashboard = wait_json(grafana_url + "/api/dashboards/uid/adfs-services-minute", auth)
        assert len(dashboard["dashboard"]["panels"]) == 4
        datasource = wait_json(grafana_url + "/api/datasources/uid/soc-postgres/health", auth)
        assert datasource["status"] == "OK"
        oscillations = wait_json(
            grafana_url + "/api/dashboards/uid/adfs-services-oscillations", auth
        )
        assert len(oscillations["dashboard"]["panels"]) == 6
        subprocess.run(
            [node, str(ROOT / "tools/verify_grafana_browser.cjs")],
            env=environment,
            check=True,
            timeout=120,
        )
        code = """
from pathlib import Path
from practicum_soc.repositories.factory import open_store
with open_store(Path('unused.db')) as store:
    event = dict(source_event_id='synthetic', event_time_utc='2026-03-16T15:00:25+00:00',
                 event_class='failure', event_count=6, relying_party='synthetic-service',
                 user_key='usr_synthetic', client_ip_key='ip_synthetic')
    assert store.insert_event(event, event['event_time_utc'], 'synthetic', True, 'smoke_grafana')
    assert not store.insert_event(event, event['event_time_utc'], 'synthetic', True, 'smoke_grafana')
"""
        compose("exec", "-T", "web", "python", "-c", code)
        query = {
            "from": "1773673200000",
            "to": "1773673260000",
            "queries": [
                {
                    "refId": "A",
                    "datasource": {"type": "grafana-postgresql-datasource", "uid": "soc-postgres"},
                    "rawSql": "SELECT total_events::double precision AS value FROM soc_service_minute_dashboard WHERE source_name = 'smoke_grafana'",
                    "format": "table",
                }
            ],
        }
        request = Request(
            grafana_url + "/api/ds/query",
            data=json.dumps(query).encode(),
            headers={"Authorization": auth, "Content-Type": "application/json"},
        )
        with urlopen(request, timeout=15) as response:
            result = json.load(response)["results"]["A"]
        assert not result.get("error"), "Grafana devolvió un error de consulta"
        assert result["frames"][0]["data"]["values"][0] == [6]
        compose(
            "exec",
            "-T",
            "postgres",
            "pg_dump",
            "-U",
            "postgres",
            "-d",
            "soc",
            "-Fc",
            "-f",
            "/tmp/soc-test.dump",
        )
        compose("exec", "-T", "postgres", "createdb", "-U", "postgres", "soc_restore_test")
        compose(
            "exec",
            "-T",
            "postgres",
            "pg_restore",
            "-U",
            "postgres",
            "-d",
            "soc_restore_test",
            "--no-owner",
            "/tmp/soc-test.dump",
        )
        restored = compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "postgres",
            "-d",
            "soc_restore_test",
            "-Atc",
            "SELECT COUNT(*) FROM alerts",
            capture=True,
        )
        assert int(restored.stdout.strip()) >= 32
        print("Respaldo PostgreSQL restaurado en una base de prueba independiente.")
        print("SMOKE OK: OIDC Keycloak, roles, revocación, PostgreSQL, Grafana y deduplicación.")
    finally:
        # Solo el proyecto aleatorio de esta prueba. Nunca adfs-soc del usuario.
        compose("down", "-v", "--remove-orphans")


if __name__ == "__main__":
    main()
