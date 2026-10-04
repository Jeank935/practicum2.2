"""Benchmark HTTP sintético y reproducible; nunca consulta PostgreSQL institucional.

Ejecutar con PYTHONPATH=src;tests. Mide 3 calentamientos y 20 solicitudes por ruta.
La traza SQL excluye la inicialización del esquema y la autenticación real.
"""

import json
import os
import statistics
import tempfile
import time
from pathlib import Path
from unittest.mock import patch


def main() -> None:
    os.environ.update(
        SOC_AUTH_MODE="disabled",
        SOC_STORAGE_BACKEND="sqlite",
        SOC_CURSOR_SECRET="synthetic-benchmark-secret",
    )
    from fastapi.testclient import TestClient
    from test_browsing_load import measure

    import practicum_soc.main as web_app
    from practicum_soc.repositories.alerts import AlertStore
    from practicum_soc.services.dashboard import DashboardService

    root = Path.cwd()
    original_init = AlertStore.__init__
    statements = []

    def traced_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.connection.set_trace_callback(lambda sql: statements.append(sql.split()[0]))

    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "synthetic.db"
        with AlertStore(db) as store:
            measure(store, "sqlite")
            run = store.start_run("load_test")
            store.finish_run(
                run, "completed", fetched_count=10000, inserted_event_count=10000, alert_count=5001
            )
        dashboard = DashboardService(
            state_db=db,
            analysis_dir=Path(d) / "analysis",
            detection_config=root / "config/detection_rules.json",
            operational_config=root / "config/operational.json",
        )
        web_app.app.state.dashboard_service = dashboard
        web_app.app.state.soc_state_db = db
        web_app.app.state.dashboard_factory = lambda: dashboard
        output = {}
        with (
            patch.object(AlertStore, "__init__", traced_init),
            TestClient(web_app.app, base_url="http://127.0.0.1:8000") as client,
        ):
            for endpoint in [
                "/",
                "/alerts",
                "/services",
                "/api/v1/alerts",
                "/api/v1/services",
                "/api/dashboard-version",
                "/api/services-version",
                "/api/v1/dashboard/snapshot",
            ]:
                for _ in range(3):
                    client.get(endpoint)
                durations = []
                queries = []
                for _ in range(20):
                    statements.clear()
                    started = time.perf_counter()
                    response = client.get(endpoint)
                    durations.append((time.perf_counter() - started) * 1000)
                    queries.append(len(statements))
                    assert response.status_code == 200, (endpoint, response.text[:150])
                output[endpoint] = {
                    "min_ms": round(min(durations), 2),
                    "mean_ms": round(statistics.mean(durations), 2),
                    "median_ms": round(statistics.median(durations), 2),
                    "p95_ms": round(sorted(durations)[18], 2),
                    "bytes": len(response.content),
                    "queries": statistics.median(queries),
                }
        print("HTTP_BENCHMARK=" + json.dumps(output))


if __name__ == "__main__":
    main()
