"""Inicialización explícita del PostgreSQL dedicado, nunca de la fuente UTPL."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg import sql

from practicum_soc.analytics.schema import ANALYTIC_VIEWS
from practicum_soc.repositories.migrations.postgres import install_schema
from practicum_soc.repositories.postgres import storage_parameters
from practicum_soc.services.catalog import load_service_labels


def configure_role(connection, name: str, password: str) -> None:
    if len(password) < 20:
        raise ValueError("Use contraseñas locales aleatorias de al menos 20 caracteres")
    if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone():
        connection.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(name)))
    connection.execute(
        sql.SQL("ALTER ROLE {} PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
            sql.Identifier(name), sql.Literal(password)
        )
    )


def initialize() -> None:
    if os.environ.get("SOC_ALLOW_STORAGE_INIT") != "yes":
        raise RuntimeError("Inicialización no autorizada; use el servicio init de Compose")
    parameters = storage_parameters()
    with psycopg.connect(**parameters, autocommit=True) as connection:
        with connection.transaction():
            configure_role(connection, "soc_app", os.environ["SOC_APP_PASSWORD"])
            configure_role(connection, "soc_grafana", os.environ["SOC_GRAFANA_PASSWORD"])
            install_schema(connection)
            labels = load_service_labels(Path("config/service_catalog.json"))
            for identifier, label in labels.items():
                connection.execute(
                    "INSERT INTO service_labels VALUES (%s, %s) ON CONFLICT (relying_party) "
                    "DO UPDATE SET display_name = EXCLUDED.display_name",
                    (identifier, label),
                )
            connection.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            connection.execute("GRANT USAGE ON SCHEMA public TO soc_app, soc_grafana")
            connection.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO soc_app"
            )
            connection.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO soc_app")
            connection.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM soc_grafana")
            connection.execute("GRANT SELECT ON soc_service_minute_dashboard TO soc_grafana")
            for view in ANALYTIC_VIEWS:
                connection.execute(
                    sql.SQL("GRANT SELECT ON {} TO soc_grafana").format(sql.Identifier(view))
                )
            connection.execute(
                "GRANT EXECUTE ON FUNCTION soc_service_oscillations(text,text,timestamptz,timestamptz,text) TO soc_grafana,soc_app"
            )
            connection.execute(
                "GRANT EXECUTE ON FUNCTION soc_services_overview(text,text[],timestamptz,timestamptz,text) TO soc_grafana,soc_app"
            )
            connection.execute(
                "GRANT EXECUTE ON FUNCTION soc_apply_analytics(normalized_events,integer) TO soc_app"
            )
            connection.execute("ALTER ROLE soc_grafana SET default_transaction_read_only = on")
            connection.execute("ALTER ROLE soc_grafana SET statement_timeout = '15s'")
    print("PostgreSQL propio del SOC inicializado. No se consultó la fuente institucional.")


def main() -> None:
    try:
        initialize()
    except Exception as error:
        # El texto de errores de conexión/SQL puede incluir datos de configuración.
        raise SystemExit(f"No se pudo inicializar el SOC: {type(error).__name__}") from None


if __name__ == "__main__":
    main()
