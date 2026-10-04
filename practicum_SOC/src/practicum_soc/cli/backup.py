"""CLI mínimo para respaldar/restaurar una base SQLite a una ruta nueva."""

import argparse
from pathlib import Path

from practicum_soc.repositories.backup import sqlite_backup, sqlite_restore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("backup", "restore"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    operation = sqlite_backup if arguments.action == "backup" else sqlite_restore
    result = operation(arguments.source, arguments.destination)
    print(f"{arguments.action}: copia verificada en {result}")


if __name__ == "__main__":
    main()
