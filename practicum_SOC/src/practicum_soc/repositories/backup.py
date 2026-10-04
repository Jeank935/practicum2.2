"""Respaldo consistente de SQLite local; la base institucional queda fuera de alcance."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


def _distinct_paths(source: Path, destination: Path) -> tuple[Path, Path]:
    origin, target = source.resolve(), destination.resolve()
    if origin == target:
        raise ValueError("Origen y destino deben ser diferentes")
    if not origin.is_file():
        raise FileNotFoundError("La base de origen no existe")
    if destination.is_symlink() or target.exists():
        raise FileExistsError("El destino ya existe; no se sobrescribe")
    if not target.parent.is_dir():
        raise FileNotFoundError("La carpeta de destino no existe")
    return origin, target


def sqlite_backup(source: Path, destination: Path) -> Path:
    origin, target = _distinct_paths(source, destination)
    with target.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(origin)) as current:
            if current.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("La base de origen no pasó la verificación de integridad")
            with closing(sqlite3.connect(target)) as backup:
                current.backup(backup)
                if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("El respaldo no pasó la verificación de integridad")
    except Exception:
        if target.is_file():
            target.unlink()
        raise
    return target


def sqlite_restore(backup: Path, new_database: Path) -> Path:
    """Restaura a una ruta nueva; nunca reemplaza la base activa."""
    return sqlite_backup(backup, new_database)
