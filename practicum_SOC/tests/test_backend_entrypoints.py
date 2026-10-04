"""Los lanzadores públicos siguen funcionando sin instalación editable."""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "module",
    [
        "normalize_events",
        "build_baseline",
        "detect_alerts",
        "generate_report",
        "demo_cli",
        "monitor_service",
        "live_sample_cli",
        "historical_cli",
        "container_demo",
        "container_init",
    ],
)
def test_legacy_pipeline_entries_export_callable_main(module):
    assert callable(importlib.import_module(module).main)


def test_container_init_main_delegates_without_import_side_effects(monkeypatch):
    from practicum_soc.cli import container_init

    calls = []
    monkeypatch.setattr(container_init, "initialize", lambda: calls.append("initialized"))
    importlib.import_module("container_init").main()
    assert calls == ["initialized"]


def test_container_init_main_does_not_expose_secrets(monkeypatch):
    from practicum_soc.cli import container_init

    def fail():
        raise RuntimeError("synthetic-private-detail")

    monkeypatch.setattr(container_init, "initialize", fail)
    with pytest.raises(SystemExit) as error:
        container_init.main()
    assert str(error.value) == "No se pudo inicializar el SOC: RuntimeError"


@pytest.mark.parametrize(
    "script",
    [
        "tools/profile_csv.py",
        "tools/backup_state.py",
        "src/normalize_events.py",
        "src/detect_alerts.py",
        "src/monitor_service.py",
    ],
)
def test_legacy_cli_help_without_pythonpath(script, tmp_path):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(ROOT / script), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()


def test_legacy_asgi_entrypoint_exports_app(tmp_path):
    environment = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "SOC_AUTH_MODE": "disabled",
        "SOC_STORAGE_BACKEND": "sqlite",
        "SOC_STATE_DB": str(tmp_path / "state.db"),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from fastapi import FastAPI; from web_app import app; assert isinstance(app, FastAPI)",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
