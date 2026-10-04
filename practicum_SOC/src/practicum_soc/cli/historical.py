"""Entrada delgada para análisis por fechas en la fuente institucional autorizada."""

import argparse
import json
import os
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from practicum_soc.analytics.historical_report import save_report
from practicum_soc.core.config import load_env_file, load_json, read_pseudonym_secret
from practicum_soc.repositories.factory import open_store
from practicum_soc.services.history import analyze_history
from practicum_soc.soc.history_source import HistoricalPostgresSource
from practicum_soc.soc.normalization import NormalizationConfig


def safe_failure(error: Exception) -> dict:
    """Ubica el fallo sin publicar mensajes SQL, credenciales ni valores de eventos."""
    frames = traceback.extract_tb(error.__traceback__)
    origin = f"{Path(frames[-1].filename).name}:{frames[-1].name}" if frames else "unknown"
    return {
        "stage": "failed",
        "error_code": type(error).__name__,
        "sqlstate": getattr(error, "sqlstate", None),
        "error_origin": origin,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-date", required=True)
    parser.add_argument("--to-date", required=True, help="Fin exclusivo; no se incluye ese día")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    load_env_file(args.env_file)
    policy = load_json(Path("config/historical_analysis.json"))
    detection = load_json(Path("config/detection_rules.json"))
    zone = ZoneInfo(detection["timezone"])
    start = datetime.fromisoformat(args.from_date).replace(tzinfo=zone)
    end = datetime.fromisoformat(args.to_date).replace(tzinfo=zone)
    if end <= start or end - start > timedelta(days=policy["maximum_range_days"]):
        raise ValueError("Seleccione un periodo positivo de hasta 62 días")
    source = HistoricalPostgresSource(
        dsn=os.environ.get("SOC_DB_DSN", ""),
        view_name=os.environ.get("SOC_DB_VIEW", ""),
        source_name="postgresql_live",
        time_column=os.environ.get("SOC_DB_TIME_COLUMN", "event_time"),
        id_column=os.environ.get("SOC_DB_ID_COLUMN", "event_id"),
        statement_timeout_seconds=policy["statement_timeout_seconds"],
    )

    def progress(value):
        print(json.dumps(value, ensure_ascii=False), flush=True)

    with open_store(Path("analysis/state/soc_alerts.db")) as store:
        result = analyze_history(
            source=source,
            store=store,
            start=start,
            end=end,
            secret=read_pseudonym_secret(None),
            normalization=NormalizationConfig.from_file(Path("config/normalization.json")),
            detection=detection,
            operational=load_json(Path("config/operational.json")),
            policy=policy,
            progress=progress,
        )
        report = save_report(store, result, args.output_dir)
        progress(
            {
                "stage": "completed",
                "months": report["months"],
                "verification": report["verification"],
                "output": str(args.output_dir),
            }
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Un error SQL puede incluir identidades o cadenas de conexión.
        print(json.dumps(safe_failure(error)), flush=True)
        raise SystemExit(1) from None
