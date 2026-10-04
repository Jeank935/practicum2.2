"""Invalidación, límites, cursores y recursos compartidos con datos sintéticos."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from test_alert_store import sample_alert
from test_browsing import SOURCE, client  # noqa: F401
from test_postgres_store import event, insert

from practicum_soc import main
from practicum_soc.core.cache import BoundedTTLCache, CacheSettings
from practicum_soc.core.cursor import InvalidCursor
from practicum_soc.core.paths import PROJECT_ROOT
from practicum_soc.repositories.alerts import AlertStore
from practicum_soc.repositories.browsing import BrowseRepository
from practicum_soc.schemas.browsing import ServiceQuery
from practicum_soc.services.browsing import BrowseService
from practicum_soc.services.dashboard import DashboardService


def dashboard(tmp_path):
    return DashboardService(
        state_db=tmp_path / "state.db",
        analysis_dir=tmp_path / "analysis",
        detection_config=PROJECT_ROOT / "config/detection_rules.json",
        operational_config=PROJECT_ROOT / "config/operational.json",
    )


def test_cache_ttl_and_copy_isolation():
    clock = [0.0]
    cache = BoundedTTLCache(CacheSettings(), clock=lambda: clock[0])
    value = {"rows": [{"count": 1}]}
    cache.put("a", value)
    value["rows"][0]["count"] = 9
    result = cache.get("a")
    result["rows"][0]["count"] = 8
    assert cache.get("a")["rows"][0]["count"] == 1
    clock[0] = 5.0
    assert cache.get("a") is None and cache.payload_bytes == 0


def test_cache_lru_bytes_and_empty_behavior():
    cache = BoundedTTLCache(CacheSettings(maximum_entries=2, maximum_payload_bytes=1024))
    assert cache.get("missing") is None
    cache.put("a", "a" * 400)
    cache.put("b", "b" * 400)
    cache.get("a")
    cache.put("c", "c" * 400)
    assert cache.get("b") is None
    assert len(cache) == 2 and cache.payload_bytes <= 1024
    cache.put("oversized", "x" * 2000)
    assert cache.get("oversized") is None
    cache.clear()
    assert len(cache) == 0 and cache.payload_bytes == 0


def test_cache_concurrent_access_stays_bounded():
    cache = BoundedTTLCache(CacheSettings(maximum_entries=4, maximum_payload_bytes=1024))

    def access(index):
        cache.put(str(index), {"count": index})
        return cache.get(str(index))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(access, range(100)))
    assert len(cache) <= 4 and cache.payload_bytes <= 1024


def test_services_cache_invalidates_on_events_and_case_status(tmp_path, monkeypatch):
    monkeypatch.setenv("SOC_STORAGE_BACKEND", "sqlite")
    service = dashboard(tmp_path)
    reader = BrowseService(service, "synthetic-cache-secret")
    query = ServiceQuery()
    with AlertStore(service.state_db) as store:
        insert(store, event("initial"), source=SOURCE)
        alert = sample_alert("synthetic-case")
        alert["relying_parties"] = event()["relying_party"]
        store.insert_alert(alert, source_name=SOURCE)
    original = BrowseRepository.services
    with patch.object(
        BrowseRepository, "services", autospec=True, side_effect=original
    ) as aggregate:
        first = reader.services(query)
        assert reader.services(query) == first
        assert aggregate.call_count == 1
        with AlertStore(service.state_db) as store:
            insert(store, event("new"), source=SOURCE)
        second = reader.services(query)
        assert aggregate.call_count == 2
        assert second["metrics"]["total_events"] == first["metrics"]["total_events"] + 2
        with AlertStore(service.state_db) as store:
            store.update_alert_status("synthetic-case", "resolved", "Synthetic")
        third = reader.services(query)
        assert aggregate.call_count == 3
        assert third["metrics"]["revision"] != second["metrics"]["revision"]
        assert reader.services(query, with_summary=True)["metrics"]["top_services"]


def test_cache_filters_catalog_and_signing_key_are_separate(tmp_path, monkeypatch):
    monkeypatch.setenv("SOC_STORAGE_BACKEND", "sqlite")
    service = dashboard(tmp_path)
    reader = BrowseService(service, "synthetic-cache-secret")
    with AlertStore(service.state_db) as store:
        for index in range(3):
            insert(store, event(str(index), relying_party=f"urn:app{index}"), source=SOURCE)
    first = reader.services(ServiceQuery(page_size=1))
    token = first["page"]["next_cursor"]
    assert token
    assert (
        reader.services(ServiceQuery(service="urn:app1"))["data"][0]["relying_party"] == "urn:app1"
    )
    with pytest.raises(InvalidCursor):
        reader.services(ServiceQuery(page_size=1, service="urn:app1", cursor=token))
    with pytest.raises(InvalidCursor):
        BrowseService(service, "rotated-secret").services(ServiceQuery(page_size=1, cursor=token))
    reader.services(ServiceQuery(page_size=1, cursor=token))
    before = len(service.service_pages)
    monkeypatch.setattr(service, "catalog_revision", lambda: "changed-catalog")
    reader.services(ServiceQuery(page_size=1))
    assert len(service.service_pages) == before + 1


def test_catalog_cache_returns_copies_and_detects_file_change(tmp_path):
    config = tmp_path / "operational.json"
    catalog = config.with_name("service_catalog.json")
    catalog.write_text('{"labels":{"urn:app":"Initial"},"sensitivity":{}}')
    service = DashboardService(
        state_db=tmp_path / "state.db",
        analysis_dir=tmp_path,
        detection_config=tmp_path / "rules.json",
        operational_config=config,
    )
    service._service_catalog()["labels"]["urn:app"] = "mutated"
    assert service._service_catalog()["labels"]["urn:app"] == "Initial"
    catalog.write_text('{"labels":{"urn:app":"Changed label"},"sensitivity":{}}')
    assert service._service_catalog()["labels"]["urn:app"] == "Changed label"


def test_connections_are_closed_after_service_read(tmp_path, monkeypatch):
    monkeypatch.setenv("SOC_STORAGE_BACKEND", "sqlite")
    service = dashboard(tmp_path)
    opened = []

    def factory(path):
        store = AlertStore(path)
        opened.append(store)
        return store

    monkeypatch.setattr("practicum_soc.services.browsing.open_store", factory)
    BrowseService(service, "synthetic-cache-secret").services(ServiceQuery())
    import sqlite3

    for store in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            store.connection.execute("SELECT 1")


def test_application_lifespan_owns_distinct_resources(tmp_path, monkeypatch):
    monkeypatch.setenv("SOC_AUTH_MODE", "disabled")
    monkeypatch.setenv("SOC_STORAGE_BACKEND", "sqlite")
    first, second = dashboard(tmp_path), dashboard(tmp_path)
    a, b = main.create_app(first), main.create_app(second)
    first.service_pages.put("test", {"count": 1})
    assert a.state.dashboard_factory() is first
    assert b.state.dashboard_factory() is second
    with TestClient(a):
        assert len(first.service_pages) == 1
    assert len(first.service_pages) == 0


def test_stream_route_uses_application_service(client, monkeypatch):  # noqa: F811
    async def stream(request, service, interval, maximum):
        assert service is main.app.state.dashboard_service
        yield "event: revision\ndata: {}\n\n"

    monkeypatch.setattr("practicum_soc.api.routes.dashboard.revision_stream", stream)
    response = client.get("/api/v1/dashboard/stream")
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "event: revision" in response.text
