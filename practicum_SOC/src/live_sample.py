"""Preparación segura de una muestra live diaria sin alterar el checkpoint principal."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from alert_store import AlertStore
from event_source import quote_identifier
from normalize_events import parse_timestamp


def sample_checkpoint(
    boundary_time: object | None,
    boundary_event_id: object | None,
    earliest_time: object,
    earliest_event_id: object,
) -> tuple[str, str]:
    """Devuelve el cursor anterior a la muestra solicitada."""
    if boundary_time is not None and boundary_event_id is not None:
        parsed_boundary = parse_timestamp(str(boundary_time))
        if parsed_boundary is None:
            raise ValueError("La fecha límite de la muestra no es válida")
        return parsed_boundary.isoformat(), str(boundary_event_id).strip()

    parsed_earliest = parse_timestamp(str(earliest_time))
    if parsed_earliest is None:
        raise ValueError("La primera fecha del día no es válida")
    return (parsed_earliest - timedelta(microseconds=1)).isoformat(), str(earliest_event_id).strip()


def prepare_live_sample(
    *,
    dsn: str,
    view_name: str,
    time_column: str,
    id_column: str,
    state_db: Path,
    limit: int,
    timezone_name: str = "America/Guayaquil",
    connect_timeout_seconds: int = 10,
) -> dict:
    if not 1 <= limit <= 5000:
        raise ValueError("El límite de la muestra debe estar entre 1 y 5000")

    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError("Falta psycopg para consultar PostgreSQL") from error

    view = quote_identifier(view_name)
    time_field = quote_identifier(time_column)
    id_field = quote_identifier(id_column)
    daily_filter = (
        f"{time_field} >= CURRENT_DATE "
        f"AND {time_field} < CURRENT_DATE + INTERVAL '1 day' "
        f"AND {id_field} IS NOT NULL"
    )

    with psycopg.connect(dsn, connect_timeout=connect_timeout_seconds) as connection:
        connection.read_only = True
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('TimeZone', %s, false)", (timezone_name,))
            cursor.execute(f"SELECT COUNT(*) FROM {view} WHERE {daily_filter}")
            available_today = int(cursor.fetchone()[0])
            if available_today == 0:
                raise RuntimeError("La fuente institucional no contiene eventos del día actual")

            cursor.execute(
                f"SELECT {time_field}, {id_field} FROM {view} "
                f"WHERE {daily_filter} "
                f"ORDER BY {time_field} DESC, {id_field} DESC OFFSET %s LIMIT 1",
                (limit,),
            )
            boundary = cursor.fetchone()
            cursor.execute(
                f"SELECT {time_field}, {id_field} FROM {view} "
                f"WHERE {daily_filter} "
                f"ORDER BY {time_field}, {id_field} LIMIT 1"
            )
            earliest = cursor.fetchone()

    boundary_time, boundary_id = boundary if boundary else (None, None)
    cursor_time, cursor_event_id = sample_checkpoint(
        boundary_time,
        boundary_id,
        earliest[0],
        earliest[1],
    )
    with AlertStore(state_db) as store:
        store.save_checkpoint("postgresql_live", cursor_time, cursor_event_id)

    return {
        "available_today": available_today,
        "requested_limit": limit,
        "selected_events": min(available_today, limit),
        "state_db": str(state_db),
    }
