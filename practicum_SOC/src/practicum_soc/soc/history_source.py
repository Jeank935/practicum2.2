"""Lectura acotada de la fuente institucional sin checkpoints ni escrituras."""

from collections.abc import Iterator
from datetime import datetime

from practicum_soc.schemas.events import SOURCE_COLUMNS
from practicum_soc.soc.ingestion import (
    IncrementalCursor,
    PostgresEventSource,
    SourceRecord,
    quote_identifier,
)
from practicum_soc.soc.normalization import parse_timestamp

NORMALIZATION_COLUMNS = (
    "id",
    "event_name",
    "log_source",
    "event_count",
    "event_time",
    "created_at",
    "updated_at",
    "event_id",
    "custom_user_id",
    "custom_ip_address",
    "custom_relying_party",
    "event_type_id",
    "event_time_origen",
)


class HistoricalPostgresSource(PostgresEventSource):
    """Un cursor de servidor recorre la instantánea; no repite el escaneo por lote."""

    def range_query(self) -> str:
        columns = ", ".join(quote_identifier(name) for name in NORMALIZATION_COLUMNS)
        relation = quote_identifier(self.view_name)
        return (
            f"SELECT {columns} FROM {relation} "
            "WHERE COALESCE(event_time_origen,event_time) >= %s "
            "AND COALESCE(event_time_origen,event_time) < %s "
            "ORDER BY COALESCE(event_time_origen,event_time),event_id"
        )

    def batches(self, start: datetime, end: datetime, size: int) -> Iterator[list[SourceRecord]]:
        if start.tzinfo is None or end.tzinfo is None or end <= start or size < 1:
            raise ValueError("Periodo histórico o tamaño de lote inválido")
        with self._connect() as connection, connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self.statement_timeout_seconds * 1000),),
            )
            with connection.cursor(name="soc_historical_read") as cursor:
                cursor.execute(self.range_query(), (start, end))
                while rows := cursor.fetchmany(size):
                    records = []
                    for raw in rows:
                        values = {key: "" for key in SOURCE_COLUMNS}
                        values.update(
                            {key: "" if value is None else str(value) for key, value in raw.items()}
                        )
                        timestamp = parse_timestamp(values[self.time_column])
                        if timestamp is None:
                            timestamp = parse_timestamp(values["event_time_origen"])
                        records.append(
                            SourceRecord(
                                values,
                                IncrementalCursor(timestamp.isoformat(), values[self.id_column]),
                            )
                        )
                    yield records
