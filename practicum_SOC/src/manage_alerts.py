"""CLI mínima para consultar y cambiar el ciclo de vida de alertas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from alert_store import ALERT_STATUSES, AlertStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-db", type=Path, default=Path("analysis/state/soc_alerts.db"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health")
    list_parser = commands.add_parser("list")
    list_parser.add_argument("--limit", type=int, default=20)
    show_parser = commands.add_parser("show")
    show_parser.add_argument("alert_id")
    status_parser = commands.add_parser("status")
    status_parser.add_argument("alert_id")
    status_parser.add_argument("new_status", choices=sorted(ALERT_STATUSES))
    status_parser.add_argument("--note", default="")
    args = parser.parse_args()

    with AlertStore(args.state_db) as store:
        if args.command == "health":
            output = store.health_summary()
        elif args.command == "list":
            output = store.list_alerts(max(1, min(args.limit, 500)))
        elif args.command == "show":
            output = store.get_alert(args.alert_id)
            if output is None:
                raise SystemExit("No existe la alerta solicitada")
        else:
            store.update_alert_status(args.alert_id, args.new_status, args.note)
            output = store.get_alert(args.alert_id)
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
