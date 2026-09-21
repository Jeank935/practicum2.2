"""Adaptador PostgreSQL del repositorio existente, sin duplicar reglas de negocio."""

from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from alert_store import AlertStore, utc_now


def storage_parameters() -> dict:
    """Parámetros exclusivos del SOC; SOC_DB_DSN sigue siendo solo la fuente."""
    required = ("SOC_STORAGE_HOST", "SOC_STORAGE_DB", "SOC_STORAGE_USER", "SOC_STORAGE_PASSWORD")
    if any(not os.environ.get(name) for name in required):
        raise RuntimeError("Falta configurar la conexión PostgreSQL propia del SOC")
    return {
        "host": os.environ["SOC_STORAGE_HOST"],
        "port": int(os.environ.get("SOC_STORAGE_PORT", "5432")),
        "dbname": os.environ["SOC_STORAGE_DB"],
        "user": os.environ["SOC_STORAGE_USER"],
        "password": os.environ["SOC_STORAGE_PASSWORD"],
        "sslmode": os.environ.get("SOC_STORAGE_SSLMODE", "require"),
        "connect_timeout": 10,
        "options": "-c timezone=UTC -c statement_timeout=30000",
    }


def postgres_sql(query: str) -> str:
    """Adapta el SQL interno parametrizado del repositorio, no consultas del usuario.

    El subconjunto compartido usa ? exclusivamente como placeholder; nunca contiene
    operadores JSON ni literales con ?. Los valores no se interpolan en el SQL.
    """
    query = query.replace("?", "%s")
    if "INSERT OR IGNORE INTO normalized_events" in query:
        query = query.replace("INSERT OR IGNORE", "INSERT")
        query = query.rstrip().rstrip(";") + " ON CONFLICT (source_event_id) DO NOTHING"
    return query


class RepositoryConnection:
    """Mantiene la semántica de transacciones de AlertStore sin cerrar cada bloque."""

    def __init__(self, connection):
        self.raw = connection
        self._transactions = []

    def execute(self, query: str, parameters=()):
        return self.raw.execute(postgres_sql(query), parameters)

    def __enter__(self):
        transaction = self.raw.transaction()
        transaction.__enter__()
        self._transactions.append(transaction)
        return self

    def __exit__(self, *args):
        return self._transactions.pop().__exit__(*args)

    def close(self):
        self.raw.close()


class PostgresAlertStore(AlertStore):
    def __init__(self):
        connection = psycopg.connect(**storage_parameters(), autocommit=True, row_factory=dict_row)
        self.connection = RepositoryConnection(connection)
        try:
            marker = connection.execute(
                "SELECT version FROM soc_schema_version WHERE singleton = 1"
            ).fetchone()
            if marker is None or marker["version"] != 1:
                raise RuntimeError("Ejecute la inicialización del PostgreSQL propio del SOC")
        except Exception:
            connection.close()
            raise

    @contextmanager
    def transaction(self):
        with self.connection:
            yield self.connection

    def start_run(self, source_name: str) -> int:
        with self.connection:
            row = self.connection.execute(
                "INSERT INTO service_runs(source_name, started_at_utc, status) "
                "VALUES (?, ?, 'running') RETURNING run_id",
                (source_name, utc_now()),
            ).fetchone()
        return int(row["run_id"])
