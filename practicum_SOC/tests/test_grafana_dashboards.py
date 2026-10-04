"""Contrato de filtros provisionados; las consultas vacías no deben romper SQL."""

import json
from pathlib import Path

import pytest

DASHBOARDS = Path(__file__).resolve().parents[1] / "deploy/grafana/dashboards"


@pytest.mark.parametrize("name", ["services", "oscillations", "service_detail"])
def test_service_variable_has_explicit_table_query(name):
    dashboard = json.loads((DASHBOARDS / f"{name}.json").read_text(encoding="utf-8"))
    variable = next(v for v in dashboard["templating"]["list"] if v["name"] == "service")
    query = variable["query"]
    assert query["format"] == "table"
    assert "SELECT DISTINCT" in query["rawSql"]
    assert "WHERE NOT EXISTS (SELECT 1 FROM choices)" in query["rawSql"]
    assert query["meta"] == {"textField": "__text", "valueField": "__value"}


@pytest.mark.parametrize("name", ["services", "oscillations", "service_detail"])
def test_empty_service_selection_uses_typed_array(name):
    dashboard = json.loads((DASHBOARDS / f"{name}.json").read_text(encoding="utf-8"))
    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            sql = target["rawSql"]
            if "${service:sqlstring}" not in sql:
                assert name == "oscillations" and panel["type"] == "stat"
                continue
            assert "ARRAY[${service:sqlstring}]::text[]" in sql
            empty_sql = sql.replace("${service:sqlstring}", "")
            assert "ARRAY[]::text[]" in empty_sql
            assert "IN ()" not in empty_sql
            assert ",," not in empty_sql


def test_overview_defaults_to_all_services_and_preserves_row_drilldown():
    dashboard = json.loads((DASHBOARDS / "oscillations.json").read_text(encoding="utf-8"))
    service = next(v for v in dashboard["templating"]["list"] if v["name"] == "service")
    assert service["multi"] and service["includeAll"]
    # Grafana inserts a custom All value verbatim, bypassing :sqlstring.
    assert service["allValue"] == "'__all'"
    assert service["current"]["value"] == "$__all"
    assert dashboard["refresh"] == "30s"
    for panel in dashboard["panels"]:
        if panel["type"] == "stat":
            assert panel["options"]["textSize"]["value"] >= 18
            assert panel["options"]["orientation"] == "vertical"
    queries = [t["rawSql"] for p in dashboard["panels"] for t in p.get("targets", [])]
    assert not any("(ARRAY[${service:sqlstring}]::text[])[1]" in q for q in queries)
    assert any("ORDER BY SUM(open_alert_count) DESC" in q for q in queries)
    table = next(p for p in dashboard["panels"] if p["type"] == "table")
    assert "LIMIT" not in table["targets"][0]["rawSql"]
    links = [
        link
        for override in table["fieldConfig"]["overrides"]
        for prop in override["properties"]
        if prop["id"] == "links"
        for link in prop["value"]
    ]
    assert all("${__data.fields.service_key}" in link["url"] for link in links)
    assert any("adfs-service-detail" in link["url"] for link in links)
