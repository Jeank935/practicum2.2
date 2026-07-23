"""Fuentes incrementales para eventos ADFS.

La implementación PostgreSQL importa ``psycopg`` únicamente al conectarse, de
modo que el análisis histórico y las pruebas locales sigan siendo stdlib-only.
"""

from __future__ import annotations

import csv
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from adfs_schema import SOURCE_COLUMNS
from normalize_events import parse_timestamp

LOGGER = logging.getLogger(__name__)
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


@dataclass(frozen=True)
class IncrementalCursor:
    timestamp_utc: str
    event_id: str


@dataclass(frozen=True)
class SourceRecord:
    values: dict[str, str]
    cursor: IncrementalCursor


class EventSource(Protocol):
    source_name: str

    def fetch_after(
        self, checkpoint: IncrementalCursor | None, limit: int
    ) -> list[SourceRecord]: ...


def _cursor_id_key(value: str) -> tuple[int, int | str]:
    stripped = str(value).strip()
    if stripped.isdigit():
        return 0, int(stripped)
    return 1, stripped


def _cursor_key(cursor: IncrementalCursor) -> tuple[datetime, tuple[int, int | str]]:
    parsed = parse_timestamp(cursor.timestamp_utc)
    if parsed is None:
        raise ValueError("El cursor contiene una fecha inválida")
    return parsed.astimezone(UTC), _cursor_id_key(cursor.event_id)


class CsvEventSource:
    """Adaptador local para demostrar el flujo incremental sin tocar PostgreSQL."""

    def __init__(self, path: Path, source_name: str = "historical_csv"):
        self.path = path
        self.source_name = source_name

    def fetch_after(self, checkpoint: IncrementalCursor | None, limit: int) -> list[SourceRecord]:
        checkpoint_key = _cursor_key(checkpoint) if checkpoint else None
        candidates: list[SourceRecord] = []
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            for row in reader:
                if not row or all(not value.strip() for value in row):
                    continue
                if len(row) != len(SOURCE_COLUMNS):
                    continue
                values = dict(zip(SOURCE_COLUMNS, row, strict=True))
                timestamp = parse_timestamp(values["event_time"])
                event_id = values["event_id"].strip()
                if timestamp is None or not event_id:
                    continue
                cursor = IncrementalCursor(timestamp.isoformat(), event_id)
                if checkpoint_key is not None and _cursor_key(cursor) <= checkpoint_key:
                    continue
                candidates.append(SourceRecord(values, cursor))
        candidates.sort(key=lambda item: _cursor_key(item.cursor))
        return candidates[:limit]


def quote_identifier(value: str) -> str:
    parts = value.split(".")
    if not parts or any(not IDENTIFIER_PATTERN.fullmatch(part) for part in parts):
        raise ValueError(f"Identificador SQL no permitido: {value!r}")
    return ".".join(f'"{part}"' for part in parts)


class PostgresEventSource:
    """Consulta incremental y de solo lectura sobre una vista autorizada."""

    def __init__(
        self,
        *,
        dsn: str,
        view_name: str,
        time_column: str = "event_time",
        id_column: str = "event_id",
        source_name: str = "institutional_postgresql",
        connect_timeout_seconds: int = 10,
        statement_timeout_seconds: int = 30,
        retry_attempts: int = 3,
        retry_delay_seconds: float = 2.0,
    ):
        if not dsn:
            raise ValueError("SOC_DB_DSN no está configurado")
        if time_column not in SOURCE_COLUMNS or id_column not in SOURCE_COLUMNS:
            raise ValueError("Las columnas de checkpoint deben existir en el esquema confirmado")
        self.dsn = dsn
        self.view_name = view_name
        self.time_column = time_column
        self.id_column = id_column
        self.source_name = source_name
        self.connect_timeout_seconds = connect_timeout_seconds
        self.statement_timeout_seconds = statement_timeout_seconds
        self.retry_attempts = max(1, retry_attempts)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)

    def _connect(self):
        """Abre una sesión PostgreSQL; se reemplaza por un mock en pruebas."""
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:
            raise RuntimeError(
                "Falta psycopg. Instale requirements.txt dentro del entorno autorizado."
            ) from error
        return psycopg.connect(
            self.dsn,
            connect_timeout=self.connect_timeout_seconds,
            autocommit=True,
            row_factory=dict_row,
        )

    def _query(self, has_checkpoint: bool) -> str:
        columns = ", ".join(quote_identifier(column) for column in SOURCE_COLUMNS)
        view = quote_identifier(self.view_name)
        time_column = quote_identifier(self.time_column)
        id_column = quote_identifier(self.id_column)
        where = ""
        if has_checkpoint:
            where = f" WHERE ({time_column} > %s OR ({time_column} = %s AND {id_column} > %s))"
        return f"SELECT {columns} FROM {view}{where} ORDER BY {time_column}, {id_column} LIMIT %s"

    def fetch_after(self, checkpoint: IncrementalCursor | None, limit: int) -> list[SourceRecord]:
        parameters: tuple
        if checkpoint:
            checkpoint_time = datetime.fromisoformat(checkpoint.timestamp_utc)
            parameters = (
                checkpoint_time,
                checkpoint_time,
                checkpoint.event_id,
                limit,
            )
        else:
            parameters = (limit,)

        for attempt in range(1, self.retry_attempts + 1):
            try:
                with self._connect() as connection:
                    connection.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
                    connection.execute(
                        "SELECT set_config('statement_timeout', %s, false)",
                        (str(self.statement_timeout_seconds * 1000),),
                    )
                    rows = connection.execute(
                        self._query(checkpoint is not None), parameters
                    ).fetchall()
                records = []
                for raw_row in rows:
                    values = {
                        column: "" if raw_row.get(column) is None else str(raw_row[column])
                        for column in SOURCE_COLUMNS
                    }
                    cursor_time = parse_timestamp(values[self.time_column])
                    cursor_id = values[self.id_column].strip()
                    if cursor_time is None or not cursor_id:
                        LOGGER.warning("Registro omitido: cursor incremental incompleto o inválido")
                        continue
                    records.append(
                        SourceRecord(
                            values,
                            IncrementalCursor(cursor_time.isoformat(), cursor_id),
                        )
                    )
                return records
            except Exception as error:
                if attempt >= self.retry_attempts:
                    raise RuntimeError(
                        "No fue posible consultar la fuente PostgreSQL autorizada"
                    ) from error
                LOGGER.warning(
                    "Consulta PostgreSQL fallida; reintento %s de %s",
                    attempt,
                    self.retry_attempts,
                )
                time.sleep(self.retry_delay_seconds * attempt)
        return []
