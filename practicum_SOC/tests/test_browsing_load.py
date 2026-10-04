"""Medición local reproducible; no es una certificación de carga institucional."""

import time
from statistics import median

from test_alert_store import sample_alert
from test_postgres_store import pg_store  # noqa: F401

from practicum_soc.core.browsing_config import SETTINGS
from practicum_soc.core.cursor import CursorCodec
from practicum_soc.repositories.alerts import AlertStore
from practicum_soc.repositories.browsing import BrowseRepository
from practicum_soc.repositories.postgres import postgres_sql
from practicum_soc.schemas.browsing import AlertQuery, ServiceQuery


def measure(store, backend):
    store.insert_alert(sample_alert("template"), source_name="load_test")
    row = dict(
        store.connection.execute("SELECT * FROM alerts WHERE alert_id = 'template'").fetchone()
    )
    keys = list(row)
    values = []
    for index in range(5000):
        item = {**row, "alert_id": f"load_{index:05}"}
        values.append(tuple(item[key] for key in keys))
    raw = getattr(store.connection, "raw", store.connection)
    alert_sql = f"INSERT INTO alerts ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})"
    event_sql = (
        "INSERT INTO normalized_events(source_event_id,source_name,event_time_utc,event_class,"
        "user_key,client_ip_key,relying_party,event_count,is_consistent,source_cursor_time_utc,"
        "source_cursor_event_id,ingested_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    instant = "2026-03-16T15:00:00+00:00"
    events = [
        (
            f"e{index}",
            "load_test",
            instant,
            "failure",
            f"usr_{index % 300}",
            f"ip_{index % 100}",
            f"app_{index % 100}",
            1,
            1,
            instant,
            str(index),
            instant,
        )
        for index in range(10000)
    ]
    with store.connection:
        cursor = raw.cursor()
        cursor.executemany(postgres_sql(alert_sql) if backend == "postgres" else alert_sql, values)
        cursor.executemany(postgres_sql(event_sql) if backend == "postgres" else event_sql, events)
    # Simula estadísticas posteriores a una carga; no forzamos el planificador.
    if backend == "postgres":
        store.connection.execute("ANALYZE alerts")
        store.connection.execute("ANALYZE normalized_events")
    repo = BrowseRepository(store)
    query = AlertQuery()
    # Mantiene el tamaño histórico del benchmark, independiente del predeterminado de la UI.
    service_query = ServiceQuery(page_size=SETTINGS.default_page_size)
    codec = CursorCodec("synthetic-load-test", {})
    scope, params, _ = repo.event_scope(service_query, "load_test", [])
    results = {}
    for name, operation in {
        "alerts": lambda: repo.alerts(query, "load_test", codec),
        "services": lambda: repo.services(service_query, scope, params, codec),
    }.items():
        times = []
        for _ in range(10):
            started = time.perf_counter()
            rows, _ = operation()
            times.append((time.perf_counter() - started) * 1000)
            assert len(rows) == SETTINGS.default_page_size
        assert max(times) < SETTINGS.response_target_ms
        results[name] = {"median_ms": round(median(times), 2), "max_ms": round(max(times), 2)}
    prefix = "EXPLAIN " if backend == "postgres" else "EXPLAIN QUERY PLAN "
    plan = store.connection.execute(
        prefix + "SELECT alert_id FROM alerts WHERE source_name = ? "
        "ORDER BY risk_score DESC, occurred_at_utc DESC, alert_id DESC LIMIT 26",
        ("load_test",),
    ).fetchall()
    assert "idx_alert_browse_risk" in str([dict(item) for item in plan])
    print(f"BENCHMARK {backend}: 5001 alertas, 10000 eventos, 100 servicios: {results}")


def test_sqlite_browsing_load(tmp_path):
    with AlertStore(tmp_path / "load.db") as store:
        measure(store, "sqlite")


def test_postgres_browsing_load(pg_store):  # noqa: F811 - fixture compartida de integración
    measure(pg_store[0], "postgres")
