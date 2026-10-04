"""Fechas legibles y navegación configurable sin cambiar datos originales."""

from datetime import datetime

import pytest

from practicum_soc.core.presentation import format_local_datetime, grafana_dashboard_url


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-09-25T00:59:51+00:00", "24/09/2026 · 19:59:51"),
        ("2026-09-24T19:59:51-05:00", "24/09/2026 · 19:59:51"),
        ("2026-09-25T00:59:51Z", "24/09/2026 · 19:59:51"),
        (datetime.fromisoformat("2026-09-25T00:59:51+00:00"), "24/09/2026 · 19:59:51"),
        (None, "Sin datos"),
        ("not-a-date", "Fecha no disponible"),
        ("2026-09-25T00:59:51", "Fecha sin zona horaria"),
    ],
)
def test_local_datetime(value, expected):
    assert format_local_datetime(value) == expected


def test_grafana_destination_default_and_override(monkeypatch):
    monkeypatch.delenv("SOC_GRAFANA_DASHBOARDS_URL", raising=False)
    assert grafana_dashboard_url() == "http://127.0.0.1:3000/dashboards"
    monkeypatch.setenv("SOC_GRAFANA_DASHBOARDS_URL", "https://grafana.example.test/dashboards")
    assert grafana_dashboard_url() == "https://grafana.example.test/dashboards"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "//example.test",
        "http://user:secret@example.test",
        "http://example.test\n",
    ],
)
def test_grafana_destination_rejects_unsafe_configuration(monkeypatch, url):
    monkeypatch.setenv("SOC_GRAFANA_DASHBOARDS_URL", url)
    with pytest.raises(ValueError):
        grafana_dashboard_url()
