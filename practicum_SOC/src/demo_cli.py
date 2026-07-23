"""Punto de entrada delgado para poblar la bandeja SOC en modo demo."""

from __future__ import annotations

import json
from pathlib import Path

from dashboard_service import DashboardService


def main() -> None:
    service = DashboardService(
        state_db=Path("analysis/state/soc_alerts.db"),
        analysis_dir=Path("analysis"),
        detection_config=Path("config/detection_rules.json"),
        operational_config=Path("config/operational.json"),
    )
    print(json.dumps(service.run_demo(), ensure_ascii=False))


if __name__ == "__main__":
    main()
