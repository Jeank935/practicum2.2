"""Analítica local: exactitud, aislamiento, historia y privilegios."""

from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from test_alert_store import sample_alert
from test_postgres_store import event, insert, pg_store  # noqa: F401

from practicum_soc.analytics.schema import ANALYTIC_VIEWS, install_analytics
from practicum_soc.core.service_identity import service_key

KEY = service_key("https://example.test/private")


def overview(store, keys, source="test", start="2026-03-21T05:00:00Z", end="2026-03-22T05:00:00Z"):
    return store.connection.execute(
        "SELECT * FROM soc_services_overview(?,?,?,?,?)", (source, keys, start, end, "hour")
    ).fetchall()


def test_multi_service_overview_filters_counts_and_preserves_alert_only_buckets(pg_store):  # noqa: F811
    store, _, _ = pg_store
    second = "https://example.test/second"
    only_case = "https://example.test/only-case"
    insert(store, event("a", "2026-03-21T05:01:00Z", event_count=6))
    insert(
        store,
        event(
            "b", "2026-03-21T06:01:00Z", relying_party=second, event_class="success", event_count=2
        ),
    )
    insert(store, event("outside-source", "2026-03-21T05:01:00Z"), source="other")
    alert = sample_alert("synthetic-open")
    alert.update(
        first_seen_local="2026-03-21T00:59:00-05:00",
        last_seen_local="2026-03-21T01:01:00-05:00",
        relying_parties=f"https://example.test/private;{only_case}",
    )
    store.insert_alert(alert, source_name="test")
    closed = {**alert, "alert_id": "synthetic-closed"}
    store.insert_alert(closed, source_name="test")
    store.update_alert_status(closed["alert_id"], "false_positive", "Synthetic test")
    rows = overview(store, ["__all"])
    assert {r["service_key"] for r in rows} == {KEY, service_key(second), service_key(only_case)}
    assert sum(r["total_events"] or 0 for r in rows) == 8
    app = [r for r in rows if r["service_key"] == KEY]
    assert sum(r["alert_count"] for r in app) == 2
    assert sum(r["open_alert_count"] for r in app) == 1
    assert sum(r["high_open_count"] for r in app) == 1
    assert sum(r["critical_open_count"] for r in app) == 0
    assert next(r for r in app if r["alert_count"])["total_events"] is None
    assert {r["service_key"] for r in overview(store, [KEY, service_key(second)])} == {
        KEY,
        service_key(second),
    }
    assert {r["service_key"] for r in overview(store, [KEY])} == {KEY}
    assert overview(store, []) == []
    assert overview(store, ["__no_data"]) == []
    assert overview(store, ["__all"], source="unavailable") == []
    assert not {"user_key", "client_ip_key", "relying_party"} & set(rows[0])


def test_multi_service_overview_range_is_bounded(pg_store):  # noqa: F811
    store, _, _ = pg_store
    with pytest.raises(psycopg.errors.RaiseException):
        overview(store, ["__all"], end="2026-05-01T05:00:00Z")


def series(store, start="2026-03-21T05:00:00Z", end="2026-03-22T05:00:00Z", grain="day"):
    return store.connection.execute(
        "SELECT * FROM soc_service_oscillations(?,?,?,?,?)",
        ("test", KEY, start, end, grain),
    ).fetchall()


def test_exact_distincts_day_boundaries_dedup_and_mutations(pg_store):  # noqa: F811
    store, _, _ = pg_store
    first = event("one", "2026-03-21T04:59:00Z", event_count=2)
    assert insert(store, first)
    assert not insert(store, first)
    insert(store, event("two", "2026-03-21T05:00:00Z", event_count=3))
    insert(store, event("three", "2026-03-21T06:00:00Z", event_class="success", event_count=4))
    insert(store, event("other-source", "2026-03-21T06:00:00Z"), source="other")
    insert(store, event("bad", ""), valid=False)
    daily = series(store)[0]
    assert daily["total_events"] == 7
    assert daily["distinct_users"] == daily["distinct_ips"] == 1
    assert daily["success_count"] == 4 and daily["failure_count"] == 3
    assert float(daily["failure_rate"]) == pytest.approx(300 / 7)
    assert daily["baseline_expected"] is None
    with store.connection:
        store.connection.execute(
            "UPDATE normalized_events SET user_key='usr_changed',event_count=5 WHERE source_event_id='test:three'"
        )
    assert series(store)[0]["distinct_users"] == 2
    with store.connection:
        store.connection.execute("DELETE FROM normalized_events WHERE source_event_id='test:two'")
    assert series(store)[0]["total_events"] == 5
    assert series(store)[0]["distinct_users"] == 1
    assert "relying_party" not in daily and "user_key" not in daily


def test_baseline_previous_period_no_future_and_overlapping_cases(pg_store):  # noqa: F811
    store, _, _ = pg_store
    with store.connection:
        store.connection.execute(
            "UPDATE soc_analytics_policy SET minimum_day_events=1,minimum_day_hours=1,"
            "training_end='2026-03-17T05:00:00Z'"
        )
    for day, weight in [(14, 10), (15, 10), (16, 10), (20, 15), (21, 30), (22, 1000)]:
        insert(store, event(str(day), f"2026-03-{day}T15:00:00Z", event_count=weight))
    alert = sample_alert()
    alert.update(
        first_seen_local="2026-03-20T23:59:00-05:00",
        last_seen_local="2026-03-21T00:02:00-05:00",
        relying_parties="https://example.test/private",
    )
    store.insert_alert(alert, source_name="test")
    daily = series(store)[0]
    assert daily["previous_events"] == 15 and daily["change_percent"] == 100
    assert daily["baseline_samples"] == 3 and daily["baseline_expected"] == 10
    assert daily["deviation_percent"] == 200
    assert daily["alert_count"] == daily["open_alert_count"] == 1
    hourly = series(store, "2026-03-21T15:00:00Z", "2026-03-21T16:00:00Z", "hour")[0]
    assert hourly["baseline_expected"] == 10
    # Evaluación dentro del entrenamiento solo usa buckets completos anteriores.
    earlier = series(store, "2026-03-15T05:00:00Z", "2026-03-16T05:00:00Z")[0]
    assert earlier["baseline_samples"] == 1 and earlier["baseline_expected"] is None
    store.connection.execute("UPDATE soc_analytics_policy SET minimum_day_hours=12")
    assert series(store)[0]["baseline_expected"] is None


def test_backfill_idempotence_and_rollback(pg_store):  # noqa: F811
    store, _, _ = pg_store
    insert(store, event())
    raw = store.connection.raw
    with raw.transaction():
        raw.execute("DELETE FROM soc_service_buckets")
        raw.execute("DELETE FROM soc_bucket_entities")
        raw.execute("DELETE FROM soc_analytics_migrations")
        # El instalador usa filas tuple, como container_init.
        from psycopg.rows import tuple_row

        previous = raw.row_factory
        raw.row_factory = tuple_row
        try:
            install_analytics(raw)
            install_analytics(raw)
        finally:
            raw.row_factory = previous
    row = store.connection.execute("SELECT * FROM soc_service_day_dashboard").fetchone()
    assert row["total_events"] == 2 and row["distinct_users"] == 1
    with pytest.raises(ValueError), store.transaction():
        insert(store, event("rollback"))
        raise ValueError("Synthetic")
    assert (
        store.connection.execute(
            "SELECT SUM(total_events) AS n FROM soc_service_day_dashboard"
        ).fetchone()["n"]
        == 2
    )


def test_readonly_role_cannot_read_raw_data_or_modify_analytics(pg_store):  # noqa: F811
    store, schema, admin = pg_store
    insert(store, event("today", "2026-03-21T15:00:00Z"))
    role = "analytics_test_" + uuid4().hex
    admin.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
    try:
        admin.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(role)
            )
        )
        for view in ANALYTIC_VIEWS:
            admin.execute(
                sql.SQL("GRANT SELECT ON {}.{} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(view), sql.Identifier(role)
                )
            )
        admin.execute(
            sql.SQL(
                "GRANT EXECUTE ON FUNCTION {}.soc_service_oscillations(text,text,timestamptz,timestamptz,text) TO {}"
            ).format(sql.Identifier(schema), sql.Identifier(role))
        )
        admin.execute(
            sql.SQL(
                "GRANT EXECUTE ON FUNCTION {}.soc_services_overview(text,text[],timestamptz,timestamptz,text) TO {}"
            ).format(sql.Identifier(schema), sql.Identifier(role))
        )
        raw = store.connection.raw
        raw.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
        try:
            assert series(store)[0]["total_events"] == 2
            assert overview(store, ["__all"])[0]["total_events"] == 2
            raw.execute("SELECT * FROM soc_monitor_health").fetchall()
            for statement in (
                "SELECT * FROM normalized_events",
                "SELECT * FROM soc_bucket_entities",
                "DELETE FROM soc_service_buckets",
                "UPDATE soc_analytics_policy_view SET minimum_samples=0",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    raw.execute(statement)
        finally:
            raw.execute("RESET ROLE")
    finally:
        admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
        admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_invalid_ranges_and_partial_bucket(pg_store):  # noqa: F811
    store, _, _ = pg_store
    with pytest.raises(psycopg.errors.RaiseException):
        series(store, "2026-01-01", "2026-03-01")
    assert series(store) == []
    now = datetime.now(UTC).isoformat()
    insert(store, event("current", now))
    rows = series(store, now[:10] + "T00:00:00Z", now, "hour")
    assert rows[-1]["partial_bucket"] is True
