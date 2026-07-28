"""CLI delgado para preparar una muestra live del día actual."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from live_sample import prepare_live_sample
from runtime_config import load_env_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-db", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_env_file(args.env_file)
    result = prepare_live_sample(
        dsn=os.environ.get("SOC_DB_DSN", ""),
        view_name=os.environ.get("SOC_DB_VIEW", ""),
        time_column=os.environ.get("SOC_DB_TIME_COLUMN", "event_time"),
        id_column=os.environ.get("SOC_DB_ID_COLUMN", "event_id"),
        state_db=args.state_db,
        limit=args.limit,
        connect_timeout_seconds=int(os.environ.get("SOC_DB_CONNECT_TIMEOUT_SECONDS", "10")),
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
