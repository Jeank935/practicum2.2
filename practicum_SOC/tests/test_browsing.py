"""Contratos de navegación con datos sintéticos, sin red institucional."""

from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from test_alert_store import sample_alert
from test_postgres_store import event, insert

import practicum_soc.main as web_app
from practicum_soc.api.navigation import navigation, safe_return_path
from practicum_soc.core.cursor import CursorCodec, InvalidCursor
from practicum_soc.repositories.alerts import AlertStore
from practicum_soc.repositories.browsing import BrowseRepository
from practicum_soc.schemas.browsing import AlertQuery, ServiceQuery
from practicum_soc.services.browsing import BrowseService
from practicum_soc.services.dashboard import DashboardService

SOURCE = "csv_demo_mvp"


@pytest.fixture
def store(tmp_path):
    with AlertStore(tmp_path / "soc.db") as repository:
        yield repository


def codec(query, kind="alerts"):
    return CursorCodec(
        "synthetic-pagination-secret",
        {
            "kind": kind,
            "source": SOURCE,
            "query": query.model_dump(mode="json", exclude={"cursor"}),
        },
    )


def seed_alerts(store, count=31):
    for index in range(count):
        item = sample_alert(f"alt_{index:04}")
        item["relying_parties"] = "app_test;other" if index % 2 == 0 else "app_test_extended"
        store.insert_alert(item, source_name=SOURCE)


@pytest.mark.parametrize("sort", ["risk", "newest", "oldest"])
def test_alert_cursor_ties_forward_back_and_bounded_sql(store, sort):
    seed_alerts(store)
    query = AlertQuery(page_size=7, sort=sort)
    repo = BrowseRepository(store)
    statements = []
    store.connection.set_trace_callback(statements.append)
    first, page = repo.alerts(query, SOURCE, codec(query))
    seen = [row["alert_id"] for row in first]
    second_query = query.model_copy(update={"cursor": page["next_cursor"]})
    second, second_page = repo.alerts(second_query, SOURCE, codec(second_query))
    back = query.model_copy(update={"cursor": second_page["previous_cursor"]})
    previous, _ = repo.alerts(back, SOURCE, codec(back))
    assert previous == first
    while page["has_next"]:
        query = query.model_copy(update={"cursor": page["next_cursor"]})
        rows, page = repo.alerts(query, SOURCE, codec(query))
        seen.extend(row["alert_id"] for row in rows)
    assert len(seen) == len(set(seen)) == 31
    assert all("LIMIT 8" in sql and "OFFSET" not in sql for sql in statements)
    assert not set(row["alert_id"] for row in second) & set(row["alert_id"] for row in first)


def test_filters_combined_and_local_date_boundary(store):
    seed_alerts(store, 4)
    excluded = sample_alert("foreign")
    store.insert_alert(excluded, source_name="postgres_live")
    late = sample_alert("late")
    late["first_seen_local"] = "2026-03-17T00:01:00-05:00"
    store.insert_alert(late, source_name=SOURCE)
    query = AlertQuery(
        service="app_test",
        severity="high",
        status="new",
        rule_id="AUTH_TEST",
        date_from=date(2026, 3, 16),
        date_to=date(2026, 3, 16),
        sort="oldest",
    )
    rows, _ = BrowseRepository(store).alerts(query, SOURCE, codec(query))
    assert {row["alert_id"] for row in rows} == {"alt_0000", "alt_0002"}
    injection = query.model_copy(update={"service": "' OR 1=1 --"})
    assert BrowseRepository(store).alerts(injection, SOURCE, codec(injection))[0] == []


def test_cursor_cannot_change_filters_or_be_tampered(store):
    seed_alerts(store, 4)
    query = AlertQuery(page_size=2)
    _, page = BrowseRepository(store).alerts(query, SOURCE, codec(query))
    changed = query.model_copy(update={"cursor": page["next_cursor"], "severity": "critical"})
    with pytest.raises(InvalidCursor):
        BrowseRepository(store).alerts(changed, SOURCE, codec(changed))
    with pytest.raises(InvalidCursor):
        codec(query).decode("broken-token", 3)


@pytest.mark.parametrize("sort", ["volume", "failures", "recent", "service"])
def test_services_paginate_aggregates_not_raw_events(store, sort):
    for index in range(12):
        insert(store, event(f"e{index}", relying_party=f"app_{index:02}"), source=SOURCE)
    repo = BrowseRepository(store)
    query = ServiceQuery(page_size=3, sort=sort)
    scope, params, _ = repo.event_scope(query, SOURCE, [])
    first, page = repo.services(query, scope, params, codec(query, "services"))
    seen = list(first)
    next_query = query.model_copy(update={"cursor": page["next_cursor"]})
    _, second_page = repo.services(next_query, scope, params, codec(next_query, "services"))
    previous = query.model_copy(update={"cursor": second_page["previous_cursor"]})
    assert repo.services(previous, scope, params, codec(previous, "services"))[0] == first
    while page["has_next"]:
        query = query.model_copy(update={"cursor": page["next_cursor"]})
        rows, page = repo.services(query, scope, params, codec(query, "services"))
        seen.extend(rows)
    assert len({item["relying_party"] for item in seen}) == 12
    assert repo.summary(scope, params)["total_events"] == 24


def test_revision_changes_only_on_persisted_changes(store):
    repo = BrowseRepository(store)
    before = repo.revision(SOURCE)
    insert(store, event(), source=SOURCE)
    after = repo.revision(SOURCE)
    assert before != after
    insert(store, event(), source=SOURCE)
    assert repo.revision(SOURCE) == after
    seed_alerts(store, 1)
    before = repo.revision(SOURCE)
    store.update_alert_status("alt_0000", "resolved", "Synthetic")
    assert repo.revision(SOURCE) != before
    revision = repo.revision(SOURCE)
    with AlertStore(store.path) as reopened:
        assert BrowseRepository(reopened).revision(SOURCE) == revision


def test_migration_backfills_existing_alerts_idempotently(store):
    from practicum_soc.repositories.migrations.browsing import install_browsing

    seed_alerts(store, 2)
    with store.connection:
        store.connection.execute("DELETE FROM browsing_migrations")
        store.connection.execute("DELETE FROM alert_services")
        store.connection.execute("UPDATE alerts SET occurred_at_utc = NULL")
        install_browsing(store.connection)
        install_browsing(store.connection)
    assert store.connection.execute("SELECT COUNT(*) FROM alert_services").fetchone()[0] == 3
    assert (
        store.connection.execute("SELECT occurred_at_utc FROM alerts LIMIT 1").fetchone()[0]
        == "2026-03-16T15:00:00.000000+00:00"
    )


def test_safe_return_and_navigation_preserve_filters():
    query = AlertQuery(severity="high", page_size=7, cursor="token")
    page = {"has_next": False, "has_previous": True, "previous_cursor": "back"}
    nav = navigation("/alerts", query, page)
    assert parse_qs(urlsplit(nav["return_to"]).query)["cursor"] == ["token"]
    assert safe_return_path(nav["return_to"]) == nav["return_to"]
    assert safe_return_path("https://evil.test") == "/alerts"
    assert safe_return_path("//evil.test/alerts") == "/alerts"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SOC_AUTH_MODE", "disabled")
    monkeypatch.setenv("SOC_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SOC_CURSOR_SECRET", "synthetic-http-secret")
    db = tmp_path / "http.db"
    monkeypatch.setattr(
        web_app.app.state,
        "dashboard_service",
        DashboardService(
            state_db=db,
            analysis_dir=tmp_path / "analysis",
            detection_config=web_app.ROOT / "config/detection_rules.json",
            operational_config=web_app.ROOT / "config/operational.json",
        ),
    )
    monkeypatch.setattr(web_app.app.state, "soc_state_db", db)
    with AlertStore(db) as store:
        seed_alerts(store)
        insert(store, event(), source=SOURCE)
    return TestClient(web_app.app, base_url="http://127.0.0.1:8000")


def test_api_html_openapi_and_return_navigation(client):
    response = client.get("/api/v1/alerts?page_size=3")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["data"]) == 3 and body["page"]["has_next"]
    assert set(body) == {"data", "page", "source"}
    assert client.get("/api/v1/services?page_size=1").status_code == 200
    html = client.get("/alerts?page_size=3&severity=high")
    assert html.status_code == 200 and 'rel="next"' in html.text
    assert "return_to=" in html.text and 'name="date_from"' in html.text
    assert client.get("/services?page_size=1").status_code == 200
    assert client.get("/services?window_days=7&page_size=1").status_code == 200
    assert client.get("/api/services-version?window_days=0").status_code == 200
    schema = client.get("/openapi.json").json()
    assert "/api/v1/alerts" in schema["paths"]
    assert schema["paths"]["/api/v1/alerts"]["get"]["responses"]["200"]["content"]


def test_services_bars_follow_cursor_and_keep_filters(client):
    with AlertStore(web_app.app.state.dashboard_service.state_db) as store:
        for index in range(13):
            insert(store, event(f"paged-{index}", relying_party=f"app_page_{index}"), source=SOURCE)
    first = client.get("/services?window_days=7&page_size=3&sort=volume")
    assert first.status_code == 200
    first_ids = {row["relying_party"] for row in first.context["metrics"]["top_services"]}
    assert len(first_ids) == 3
    assert first.context["metrics"]["top_services"] == first.context["metrics"]["services"]
    assert 'aria-label="Paginación de servicios más utilizados"' in first.text
    next_url = first.context["nav"]["next_url"]
    assert parse_qs(urlsplit(next_url).query)["window_days"] == ["7"]
    second = client.get(next_url)
    second_ids = {row["relying_party"] for row in second.context["metrics"]["top_services"]}
    assert len(second_ids) == 3 and not first_ids & second_ids
    previous = client.get(second.context["nav"]["previous_url"])
    assert previous.context["metrics"]["top_services"] == first.context["metrics"]["top_services"]
    default = client.get("/services")
    assert default.context["page"]["page_size"] == 10
    assert len(default.context["metrics"]["top_services"]) == 10
    assert default.context["page"]["has_next"]
    assert all(
        row["bar_percent"] == row["share_percent"]
        for row in default.context["metrics"]["top_services"]
    )


def test_services_format_display_dates_but_preserve_api_iso(client):
    timestamp = "2026-09-25T00:59:51+00:00"
    with AlertStore(web_app.app.state.dashboard_service.state_db) as store:
        insert(store, event("readable-date", timestamp, relying_party="app_date"), source=SOURCE)
    response = client.get("/services")
    assert "Último evento (Loja)" in response.text
    assert 'datetime="2026-09-25T00:59:51+00:00">24/09/2026 · 19:59:51</time>' in response.text
    rows = client.get("/api/v1/services").json()["data"]
    assert (
        next(row for row in rows if row["relying_party"] == "app_date")["last_seen_utc"]
        == timestamp
    )


def test_dashboard_menu_redirect_is_configured_and_not_user_supplied(client, monkeypatch):
    monkeypatch.setenv("SOC_GRAFANA_DASHBOARDS_URL", "http://127.0.0.1:3000/dashboards")
    response = client.get("/dashboard?url=https://untrusted.example.test", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "http://127.0.0.1:3000/dashboards"
    assert (
        'href="/dashboard" target="_blank" rel="noopener noreferrer"'
        in client.get("/services").text
    )
    monkeypatch.setenv("SOC_GRAFANA_DASHBOARDS_URL", "javascript:alert(1)")
    assert client.get("/dashboard", follow_redirects=False).status_code == 503


@pytest.mark.parametrize(
    "query",
    [
        "page_size=101",
        "page_size=0",
        "sort=sql",
        "date_from=2026-03-20&date_to=2026-03-10",
        "severity=unknown",
        "unexpected=1",
    ],
)
def test_invalid_queries_are_consistent(client, query):
    response = client.get("/api/v1/alerts?" + query)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_query"
    assert "input" not in response.text


def test_cursor_errors_and_empty_state(client):
    assert client.get("/api/v1/alerts?cursor=invalid").status_code == 400
    response = client.get("/alerts?cursor=invalid")
    assert response.status_code == 400 and "No pudimos mostrar" in response.text
    assert client.get("/api/v1/alerts?severity=low").json()["data"] == []
    assert "No se encontraron casos" in client.get("/alerts?severity=low").text


def test_grafana_drilldown_preserves_source_service_and_interval(client):
    from practicum_soc.core.service_identity import service_key

    params = {
        "source": "csv_demo_mvp",
        "service_key": service_key("app_test"),
        "time_from": "2026-03-16T15:00:00Z",
        "time_to": "2026-03-16T16:00:00Z",
        "page_size": 3,
    }
    response = client.get("/api/v1/alerts", params=params)
    assert response.status_code == 200
    assert len(response.json()["data"]) == 3
    html = client.get("/alerts", params=params)
    for key in ("source", "service_key", "time_from", "time_to"):
        assert f'type="hidden" name="{key}"' in html.text
    assert "Intervalo de Grafana" not in html.text
    assert "elimina este contexto" not in html.text
    params["time_from"] = "2026-03-16T15:00:00"
    assert client.get("/api/v1/alerts", params=params).status_code == 422


@pytest.mark.parametrize(
    "has_previous,has_next", [(False, False), (False, True), (True, False), (True, True)]
)
def test_pagination_only_shown_when_navigation_is_needed(has_previous, has_next):
    html = web_app.app.state.templates.env.get_template("partials/pagination.html").render(
        page={"page": 1, "page_size": 25, "has_previous": has_previous, "has_next": has_next},
        nav={
            "first_url": "/alerts",
            "previous_url": "/alerts?previous=1",
            "next_url": "/alerts?next=1",
        },
    )
    assert ('class="pagination"' in html) == (has_previous or has_next)
    assert ("Anterior" in html) == has_previous
    assert ("Siguiente" in html) == has_next


def test_sensitive_filter_and_global_percentages(store, tmp_path):
    for index in range(4):
        insert(store, event(str(index), relying_party=f"app_{index}"), source=SOURCE)
    dashboard = DashboardService(
        state_db=store.path if hasattr(store, "path") else tmp_path / "soc.db",
        analysis_dir=tmp_path,
        detection_config=web_app.ROOT / "config/detection_rules.json",
        operational_config=web_app.ROOT / "config/operational.json",
    )
    result = BrowseService(dashboard, "synthetic").services(ServiceQuery(page_size=1))
    assert result["data"][0]["share_percent"] == 25
    assert result["page"]["has_next"]
    dashboard._service_catalog = lambda: {
        "labels": {"app_0": "Aplicación sensible"},
        "sensitivity": {"app_0": {"level": "high"}},
    }
    reader = BrowseService(dashboard, "synthetic")
    result = reader.services(ServiceQuery(sensitive=True))
    assert [item["relying_party"] for item in result["data"]] == ["app_0"]
    result = reader.services(ServiceQuery(date_from="2026-04-01"))
    assert result["data"] == []
    assert result["metrics"]["latest_event_time"] is None
