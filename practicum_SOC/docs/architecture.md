# Arquitectura del MVP

## Flujo

```text
CSV demo / vista PostgreSQL READ ONLY
  -> EventSource
  -> normalización + rechazo + HMAC + deduplicación
  -> línea base de entrenamiento
  -> evaluación temporal + cinco detectores
  -> AlertStore (SQLite)
  -> NotificationProvider (soc_inbox)
  -> DashboardService
  -> FastAPI + Jinja2 / reporte Markdown
```

Cada capa tiene una responsabilidad:

| Capa | Archivos | Responsabilidad |
|---|---|---|
| Esquema | `adfs_schema.py`, `config/` | Columnas, eventos, umbrales y políticas. |
| Ingesta | `event_source.py` | CSV incremental o PostgreSQL de solo lectura. |
| Normalización | `normalize_events.py` | Validación, HMAC, rechazo y deduplicación. |
| Línea base | `build_baseline.py` | Perfiles solo con el periodo de entrenamiento. |
| Detección | `detect_alerts.py` | Cinco reglas puras y riesgo explicable. |
| Almacenamiento | `sqlite_schema.py`, `alert_store.py` | Persistencia, cooldown, historial y entregas. |
| Notificación | `notifications.py` | Contrato desacoplado y canal interno `soc_inbox`. |
| Aplicación | `demo_service.py`, `monitoring.py`, `dashboard_service.py` | Orquestación reutilizable. |
| Entrada | `monitor_service.py`, `demo_cli.py`, `web_app.py` | CLI y rutas HTTP delgadas. |
| Presentación | `templates/`, `static/`, `generate_report.py` | Bandeja local y reporte reproducible. |

## Consistencia temporal

La configuración separa entrenamiento (hasta 2026-03-20) y evaluación (desde 2026-03-21). Los perfiles solo contienen eventos de entrenamiento. La regla de IP nueva consulta esos perfiles y nunca incorpora eventos futuros.

## SQLite

`normalized_events`, `alerts`, `alert_status_history`, `notification_deliveries`, `checkpoints`, `suppression_log` y `service_runs` ofrecen persistencia e idempotencia. Los registros anteriores se conservan con origen `legacy`; el demo usa `csv_demo_mvp` para no mezclar resultados históricos anteriores con la demostración vigente.

## Live y degradación segura

Los nombres SQL se validan, los valores se parametrizan y la sesión es `READ ONLY`. El checkpoint combinado evita perder empates de timestamp. Ante indisponibilidad institucional, el sistema cambia a CSV demo sin intentar evadir restricciones de red.
