"""Contrato PostgreSQL opcional: solo contra una instancia LOCAL de pruebas."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from test_alert_store import sample_alert

import postgres_store
from auth_config import AuthSettings
from auth_store import AuthStore
from configuration_audit import observe_configuration
from notifications import SocInboxProvider, deliver_once
from postgres_schema import install_schema
from postgres_store import PostgresAlertStore, postgres_sql
from rate_limits import consume
from store_factory import open_store


def test_postgres_rate_limits_are_atomic_between_connections(pg_store):
    store, _, _ = pg_store
    policy = AuthSettings.from_env().policy
    policy["rate_limits"]["case_update"] = {"requests": 3, "window_seconds": 60}

    def attempt(_):
        with PostgresAlertStore() as connection:
            return consume(connection, "case_update", "same-operator", policy, now=120)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(attempt, range(10)))
    assert results.count(0) == 3 and results.count(60) == 7
    assert consume(store, "case_update", "same-operator", policy, now=180) == 0


def test_postgres_observations_are_idempotent_and_audited(pg_store, tmp_path):
    store, _, _ = pg_store
    policy = AuthSettings.from_env().policy
    for name in ("auth.json", "detection_rules.json", "operational.json"):
        (tmp_path / name).write_text('{"value":1}')
    assert len(observe_configuration(store, tmp_path, policy)) == 3
    observe_configuration(store, tmp_path, policy)
    (tmp_path / "auth.json").write_text('{"value":2}')
    observe_configuration(store, tmp_path, policy)
    rows = AuthStore(store, policy).audit_entries()
    assert len(rows) == 4
    assert sum(item["action"] == "configuration_change_detected" for item in rows) == 1


def test_postgres_operator_sessions_roles_and_audit(pg_store):
    store, _, _ = pg_store
    auth = AuthStore(store, AuthSettings.from_env().policy)
    admin_token = auth.login({"iss": "local-test", "sub": "admin", "soc_roles": ["administrator"]})
    analyst_token = auth.login({"iss": "local-test", "sub": "analyst", "soc_roles": ["analyst"]})
    admin = auth.session(admin_token)
    analyst = auth.session(analyst_token)
    state, browser, nonce, verifier = auth.begin_login()
    assert auth.consume_login(state, browser) == {"nonce": nonce, "verifier": verifier}
    with pytest.raises(ValueError):
        auth.consume_login(state, browser)
    store.insert_alert(sample_alert())
    store.update_alert_status(
        sample_alert()["alert_id"],
        "investigating",
        "Synthetic",
        actor_id=analyst["user_id"],
        actor_name=analyst["display_name"],
    )
    assert store.alert_history(sample_alert()["alert_id"])[-1]["actor_id"] == analyst["user_id"]
    auth.update_user(analyst["user_id"], "analyst", False, admin)
    assert auth.session(analyst_token) is None
    with pytest.raises(ValueError):
        auth.update_user(admin["user_id"], "analyst", True, admin)
    assert any(row["action"] == "user_access_changed" for row in auth.audit_entries())


def test_sql_adapter_keeps_parameters_out_of_sql():
    assert postgres_sql("SELECT * FROM alerts WHERE alert_id = ?").endswith("alert_id = %s")
    assert "ON CONFLICT (source_event_id) DO NOTHING" in postgres_sql(
        "INSERT OR IGNORE INTO normalized_events(source_event_id) VALUES (?)"
    )


def test_storage_defaults_to_sqlite(tmp_path, monkeypatch):
    monkeypatch.delenv("SOC_STORAGE_BACKEND", raising=False)
    with open_store(tmp_path / "state.db") as store:
        assert store.get_checkpoint("test") is None


def test_storage_does_not_fallback_to_institutional_credentials(monkeypatch):
    monkeypatch.setenv("SOC_STORAGE_BACKEND", "postgres")
    for name in ("SOC_STORAGE_HOST", "SOC_STORAGE_DB", "SOC_STORAGE_USER", "SOC_STORAGE_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SOC_DB_DSN", "not-a-storage-connection")
    with pytest.raises(RuntimeError, match="propia del SOC"):
        open_store(Path("unused.db"))


@pytest.fixture
def pg_store(monkeypatch):
    dsn = os.environ.get("SOC_TEST_STORAGE_DSN")
    if not dsn:
        pytest.skip("Defina SOC_TEST_STORAGE_DSN para PostgreSQL local desechable")
    parameters = conninfo_to_dict(dsn)
    parameters["connect_timeout"] = "5"
    if parameters.get("host") not in {"localhost", "127.0.0.1"}:
        pytest.fail("Las pruebas no se ejecutan contra servidores externos")
    schema = "soc_test_" + uuid4().hex
    with psycopg.connect(**parameters, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            test_parameters = {**parameters, "options": f"-c search_path={schema} -c timezone=UTC"}
            monkeypatch.setattr(postgres_store, "storage_parameters", lambda: test_parameters)
            monkeypatch.setenv("SOC_STORAGE_BACKEND", "postgres")
            with psycopg.connect(**test_parameters, autocommit=True) as connection:
                install_schema(connection)
                install_schema(connection)  # Inicialización idempotente.
            with PostgresAlertStore() as store:
                yield store, schema, admin
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def event(identifier="e1", time="2026-03-16T15:00:45+00:00", **changes):
    return {
        "source_event_id": identifier,
        "event_time_utc": time,
        "event_class": "failure",
        "event_count": 2,
        "user_key": "usr_synthetic",
        "client_ip_key": "ip_synthetic",
        "relying_party": "https://example.test/private",
        **changes,
    }


def test_postgres_keyset_browsing_and_service_aggregation(pg_store):
    from browse_models import AlertQuery, ServiceQuery
    from browse_repository import BrowseRepository
    from page_cursor import CursorCodec

    store, _, _ = pg_store
    for index in range(9):
        store.insert_alert(sample_alert(f"page_{index}"), source_name="test")
        insert(store, event(str(index), relying_party=f"app_{index}"))
    repo = BrowseRepository(store)
    query = AlertQuery(page_size=3, service="app_test", date_to="2026-03-16")
    codec = CursorCodec("synthetic", {})
    first, page = repo.alerts(query, "test", codec)
    second, back = repo.alerts(
        query.model_copy(update={"cursor": page["next_cursor"]}), "test", codec
    )
    assert len(first) == len(second) == 3
    assert (
        first
        == repo.alerts(query.model_copy(update={"cursor": back["previous_cursor"]}), "test", codec)[
            0
        ]
    )
    service_query = ServiceQuery(page_size=2)
    scope, params, _ = repo.event_scope(service_query, "test", [])
    rows, page = repo.services(service_query, scope, params, codec)
    assert len(rows) == 2 and page["has_next"]
    assert repo.summary(scope, params)["total_events"] == 18
    assert repo.open_alerts("test", ["app_test"])["app_test"]["count"] == 9


def insert(store, item, source="test", valid=True):
    return store.insert_event(item, item["event_time_utc"], item["source_event_id"], valid, source)


def test_postgres_metrics_atomic_dedup_late_event_and_source_isolation(pg_store):
    store, _, _ = pg_store
    assert insert(store, event())
    assert not insert(store, event())
    assert insert(store, event("e2", "2026-03-16T10:00:12-05:00", event_class="success"))
    assert insert(store, event("e3", "2026-03-16T15:01:00+00:00", event_class="lockout"))
    assert insert(store, event(), source="other")
    assert insert(store, event("bad", ""), valid=False)
    rows = store.connection.execute(
        "SELECT * FROM service_minute_metrics WHERE source_name = ? ORDER BY minute_utc",
        ("test",),
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["minute_utc"] == datetime(2026, 3, 16, 15, 0, tzinfo=UTC)
    assert rows[0]["total_events"] == 4
    assert rows[0]["failure_count"] == rows[0]["success_count"] == 2
    assert rows[1]["lockout_count"] == 2
    with pytest.raises(ValueError), store.transaction():
        insert(store, event("rolled_back"))
        raise ValueError("synthetic rollback")
    assert (
        store.connection.execute(
            "SELECT SUM(total_events) AS n FROM service_minute_metrics WHERE source_name = 'test'"
        ).fetchone()["n"]
        == 6
    )


def test_postgres_case_persistence_cooldown_delivery_and_checkpoint(pg_store):
    store, _, _ = pg_store
    alert = sample_alert()
    assert store.insert_alert(alert, 10, "test")[0]
    assert not store.insert_alert(sample_alert(), 10, "test")[0]
    assert not store.insert_alert(sample_alert("second", 1), 10, "test")[0]
    deliver_once(store, SocInboxProvider(), alert, 3)
    store.update_alert_status(alert["alert_id"], "investigating", "Prueba")
    store.save_checkpoint("test", "2026-03-16T15:00:00+00:00", "e1")
    run_id = store.start_run("test")
    store.finish_run(run_id, "completed", fetched_count=1)
    with open_store(Path("unused.db")) as reopened:
        assert reopened.get_alert(alert["alert_id"])["investigation_status"] == "investigating"
        assert len(reopened.alert_history(alert["alert_id"])) == 3
        assert reopened.delivery_succeeded(alert["alert_id"], "soc_inbox")
        assert reopened.get_checkpoint("test")[1] == "e1"
        assert reopened.health_summary()["status"] == "healthy"
        assert not reopened.insert_alert(sample_alert("third", 2), 10, "test")[0]


def test_postgres_service_window_and_view_privacy(pg_store):
    store, schema, admin = pg_store
    insert(store, event())
    insert(store, event("later", "2026-03-19T15:00:00+00:00"))
    metrics = store.service_metrics("test", window_days=1, top_limit=10, rare_max_events=10)
    assert metrics["total_events"] == 2
    reader = "reader_" + uuid4().hex
    admin.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(reader)))
    try:
        admin.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(reader)
            )
        )
        admin.execute(
            sql.SQL("GRANT SELECT ON {}.soc_service_minute_dashboard TO {}").format(
                sql.Identifier(schema), sql.Identifier(reader)
            )
        )
        store.connection.raw.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(reader)))
        row = store.connection.execute(
            "SELECT * FROM soc_service_minute_dashboard LIMIT 1"
        ).fetchone()
        assert "user_key" not in row and "client_ip_key" not in row
        assert "https://" not in row["service"]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            store.connection.execute("SELECT * FROM normalized_events")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            store.connection.execute("DELETE FROM service_minute_metrics")
    finally:
        store.connection.raw.execute("RESET ROLE")
        admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(reader)))
        admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(reader)))
