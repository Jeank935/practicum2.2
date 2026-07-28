"""Punto de entrada del monitor incremental ADFS."""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

from alert_store import AlertStore
from monitoring import (
    INSTITUTIONAL_SOURCE_UNAVAILABLE,
    build_event_source,
    run_monitor_cycle,
)
from normalize_events import NormalizationConfig
from notifications import build_notification_provider
from runtime_config import load_env_file, load_json, read_pseudonym_secret


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("csv", "postgres"), required=True)
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--state-db", type=Path, default=Path("analysis/state/soc_alerts.db"))
    parser.add_argument(
        "--detection-config", type=Path, default=Path("config/detection_rules.json")
    )
    parser.add_argument(
        "--normalization-config", type=Path, default=Path("config/normalization.json")
    )
    parser.add_argument("--operational-config", type=Path, default=Path("config/operational.json"))
    parser.add_argument("--pseudonym-key-file", type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--notification-mode", choices=("soc_inbox", "dry_run"))
    parser.add_argument("--batch-size", type=int)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    return parser.parse_args()


def next_cycle_delay_seconds(result: dict, operational_config: dict) -> float:
    """Evita esperas durante la recuperación y limita el sondeo en tiempo real."""
    fetched = int(result.get("fetched", 0))
    batch_size = int(operational_config["batch_size"])
    if fetched >= batch_size:
        return max(0.0, float(operational_config.get("catch_up_interval_seconds", 0)))
    return max(0.0, float(operational_config["interval_seconds"]))


def main() -> None:
    args = parse_args()
    load_env_file(args.env_file)
    logging.basicConfig(
        level=os.environ.get("SOC_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    detection_config = load_json(args.detection_config)
    operational_config = load_json(args.operational_config)
    if args.batch_size is not None:
        if args.batch_size < 1:
            raise ValueError("--batch-size debe ser mayor que cero")
        operational_config = {**operational_config, "batch_size": args.batch_size}
    normalization_config = NormalizationConfig.from_file(args.normalization_config)
    provider = build_notification_provider(
        args.notification_mode or operational_config["notification_mode"]
    )
    secret = read_pseudonym_secret(args.pseudonym_key_file)
    requested_mode = args.source
    try:
        source = build_event_source(requested_mode, args.input_csv)
    except RuntimeError:
        print(INSTITUTIONAL_SOURCE_UNAVAILABLE)
        source = build_event_source("csv", args.input_csv)

    with AlertStore(args.state_db) as store:
        while True:
            try:
                result = run_monitor_cycle(
                    source=source,
                    store=store,
                    secret=secret,
                    normalization_config=normalization_config,
                    detection_config=detection_config,
                    operational_config=operational_config,
                    provider=provider,
                )
            except RuntimeError:
                if requested_mode != "postgres" or source.source_name == "csv_demo":
                    raise
                print(INSTITUTIONAL_SOURCE_UNAVAILABLE)
                source = build_event_source("csv", args.input_csv)
                result = run_monitor_cycle(
                    source=source,
                    store=store,
                    secret=secret,
                    normalization_config=normalization_config,
                    detection_config=detection_config,
                    operational_config=operational_config,
                    provider=provider,
                )
            print(json.dumps(result, ensure_ascii=False))
            if args.once:
                break
            delay_seconds = next_cycle_delay_seconds(result, operational_config)
            if delay_seconds:
                time.sleep(delay_seconds)


if __name__ == "__main__":
    main()
