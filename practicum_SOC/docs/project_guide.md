# Mapa vigente del proyecto

Referencia de mantenimiento para la entrega Docker. Los nombres de la tabla son
rutas relativas a la raíz del proyecto; la implementación vive en el paquete
`src/practicum_soc/`, no en los lanzadores cortos de `src/`.

## Flujo

```text
PostgreSQL institucional (solo lectura) o CSV autorizado
  -> soc/ingestion.py: leer eventos nuevos
  -> soc/normalization.py: validar, deduplicar y pseudonimizar
  -> soc/baseline.py: construir el comportamiento de referencia
  -> soc/detection.py: correlacionar patrones y calcular riesgo
  -> repositories/: conservar eventos, casos, estados y checkpoint
  -> integrations/notifications.py: entregar a soc_inbox
  -> main.py + api/: bandeja privada y API
  -> analytics/ + Grafana: métricas agregadas y reportes
```

Docker utiliza un PostgreSQL propio del SOC, separado del origen institucional.
Los scripts locales mantienen SQLite como alternativa. No se cambia de motor
solo por estar conectado a la red: lo decide `SOC_STORAGE_BACKEND`.

## Archivos que se deben conservar

| Ruta | Responsabilidad |
| --- | --- |
| `Dockerfile` | Construye la imagen de ejecución sin CSV, secretos ni herramientas de pruebas. |
| `compose.yaml` | Define web, worker, PostgreSQL SOC, Keycloak, Grafana y volúmenes. |
| `.dockerignore` | Restringe qué archivos entran en la construcción. |
| `.gitignore` | Excluye secretos, datos, cachés, respaldos y paquetes generados. |
| `.env*.example` | Plantillas sin credenciales reales para cada modo de ejecución. |
| `requirements-runtime.txt`, `constraints-runtime.txt` | Dependencias de ejecución fijadas. |
| `requirements.txt`, `requirements-security.txt` | Herramientas de desarrollo y revisión, fuera de la imagen final. |
| `pyproject.toml` | Configura pytest y Ruff. |
| `run_*.ps1` | Entradas Windows para demo, histórico, muestra diaria, monitor y web. |
| `tools/setup_docker.py` | Prepara secretos locales y sincroniza únicamente la conexión de origen cuando se solicita. |
| `tools/backup_state.py` | Entrada al respaldo/restauración del almacenamiento propio. |
| `tools/smoke_containers.py` | Verificación Docker aislada con datos sintéticos. |
| `tools/benchmark_backend.py` | Medición reproducible; no certifica capacidad institucional. |
| `tests/` | Regresión funcional, seguridad, integración y contratos. No son archivos prescindibles. |

## Backend por responsabilidades

Todas las rutas siguientes parten de `src/practicum_soc/`.

| Ruta | Función |
| --- | --- |
| `main.py` | Compone FastAPI, middleware, rutas, plantillas y recursos por aplicación. |
| `api/routes/` | Recibe solicitudes y delega a servicios; comprueba permisos administrativos. |
| `api/security.py`, `api/streaming.py` | Controles HTTP y envío de cambios por SSE. |
| `core/` | Configuración, rutas, cachés, firma de cursores y políticas de seguridad. |
| `schemas/` | Valida entradas/salidas y el formato de eventos ADFS. |
| `soc/ingestion.py`, `soc/history_source.py` | Lectura incremental o por fechas del origen, con acceso de solo lectura. |
| `soc/normalization.py` | Selección de usuario/IP cliente, HMAC, validación y deduplicación. |
| `soc/baseline.py` | Perfiles por usuario, IP, servicio y hora, separados de la evaluación. |
| `soc/detection.py` | Reglas explicables, correlación temporal, `calculate_risk()` y severidad. |
| `services/monitoring.py` | Coordina lectura, normalización, detección, persistencia y notificación. |
| `services/history.py`, `services/live_sample.py`, `services/demo.py` | Análisis por fechas, muestra del día y reproducción CSV. |
| `services/rules.py`, `services/rule_preview.py` | Editor de parámetros y simulación sin escribir casos. |
| `services/browsing.py`, `services/dashboard.py`, `services/catalog.py` | Consultas y contexto de presentación con límites y cachés. |
| `repositories/alerts.py`, `repositories/postgres.py`, `repositories/factory.py` | Persistencia SQLite/PostgreSQL y selección del motor. |
| `repositories/rules.py`, `repositories/auth.py`, `repositories/browsing.py` | Versiones de reglas, sesiones/auditoría y paginación SQL. |
| `repositories/migrations/` | Esquema del SOC propio; nunca migraciones de la base institucional. |
| `analytics/` | Agregados de servicios y reportes históricos. |
| `integrations/oidc.py`, `integrations/notifications.py` | Identidad OIDC y canal desacoplado soc_inbox. |
| `services/investigation*.py`, `integrations/ai_explanation.py`, `integrations/ip_reputation.py` | Investigación opcional por solicitud; servicios externos deshabilitados por defecto. |
| `cli/` | Argumentos y arranque de los comandos reutilizables. |

## Reglas y puntajes

- `config/detection_rules.json`: configuración inicial de ventanas, umbrales,
  pausas, puntajes y bonificaciones.
- `src/practicum_soc/soc/detection.py`: aplica las reglas y suma el riesgo.
- `src/practicum_soc/repositories/rules.py`: conserva borradores y versiones
  publicadas en el almacenamiento SOC. Una edición desde la web no crea otro JSON.
- `config/exclusions.json`: exclusiones autorizadas y umbrales anómalos.
- `config/rule_management.json`: límites de simulación y vigencia de comparaciones.

El monitor toma la versión publicada; un borrador no modifica su comportamiento.
Las reglas de horario y red externa continúan sujetas a validación institucional.

## Frontend y despliegue

| Ruta | Función |
| --- | --- |
| `templates/base.html` | Estructura común, menú y sesión del operador. |
| `templates/dashboard.html`, `alerts.html`, `alert_detail.html`, `services.html` | Resumen, cola de trabajo, evidencia y métricas de servicios. |
| `templates/rules.html`, `static/rules.css`, `static/rules.js` | Editor de reglas, comparación y publicación controlada. |
| `templates/partials/` | Fragmentos para actualización parcial y tablas compartidas. |
| `static/` | CSS, JavaScript progresivo y recursos institucionales. |
| `deploy/keycloak/soc-realm.json` | Realm, cliente OIDC y roles de operadores; usa variables para secretos. |
| `deploy/grafana/` | Datasource, provisionamiento y tres dashboards. |

## Por qué algunos Python son pequeños

`src/investigate_alerts.py`, `src/monitor_service.py`, `src/container_init.py` y
los demás lanzadores importan `main()` del paquete y lo ejecutan. Se conservan
porque Docker, PowerShell y las instrucciones de operación usan esas rutas.
No son implementaciones vacías ni copias del motor.

Los `__init__.py` identifican paquetes Python y documentan su propósito. No necesitan
contener funciones para ser útiles. Retirarlos sería un cambio de empaquetado,
no una limpieza de código muerto.

## Tecnologías

Python, FastAPI/Uvicorn, Jinja2, Pydantic y JavaScript progresivo componen la
aplicación. Psycopg conecta PostgreSQL; SQLite conserva el modo local. Keycloak
gestiona OIDC, Grafana presenta analítica y Docker Compose reúne los servicios.
HMAC-SHA256 pseudonimiza identidades. Pytest y Ruff verifican calidad.
No se utiliza aprendizaje automático para detectar alertas.

Los archivos de `analysis/`, los CSV, las bases, las claves y los volúmenes son
datos operativos, no código de entrega. No borrarlos ni incluirlos en un ZIP de
fuentes. Su transferencia requiere respaldo y un canal autorizado.
