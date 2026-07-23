"""Genera una clave local estable sin imprimir su contenido."""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        print(f"La clave ya existe y no fue reemplazada: {args.output}")
        return

    args.output.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    print(f"Clave creada sin mostrar su contenido: {args.output}")


if __name__ == "__main__":
    main()
