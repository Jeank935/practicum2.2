# Guía de archivos y tecnologías

Esta guía describe la versión esencial del MVP SOC ADFS. El sistema conserva separados la ingesta, normalización, línea base, detección, persistencia, notificaciones y presentación web.

## Flujo principal

```text
CSV o PostgreSQL
        ↓
event_source.py
        ↓
normalize_events.py
        ↓
SQLite + línea base
        ↓
detect_alerts.py
        ↓
alert_store.py + notifications.py
        ↓
FastAPI + Jinja2
```

Los registros aislados permanecen como eventos normalizados. Solo los patrones que superan los umbrales configurados se convierten en casos.

## Archivos de la raíz

| Archivo | Función y forma de uso |
|---|---|
| `README.md` | Instrucciones rápidas de instalación y ejecución. Es el primer documento que debe leer otro operador. |
| `requirements.txt` | Versiones reproducibles de las dependencias Python. Se instala con `python -m pip install -r requirements.txt`. |
| `pyproject.toml` | Configuración de `pytest` y Ruff. No contiene lógica de negocio. |
| `.env.example` | Plantilla segura de variables PostgreSQL. Se copia como `.env` y luego se completan los datos locales. |
| `.env` | Credenciales locales reales. Nunca debe compartirse ni versionarse. |
| `.gitignore` | Evita publicar credenciales, datos reales, SQLite, reportes generados y cachés. |
| `run_analysis.ps1` | Ejecuta el flujo histórico completo: perfil, normalización, línea base, reglas y reporte. |
| `run_demo.ps1` | Prepara el modo CSV y levanta la bandeja SOC en el puerto 8000. |
| `run_monitor.ps1` | Ejecuta una iteración o el monitoreo continuo desde CSV/PostgreSQL. |
| `run_live_today.ps1` | Consulta una muestra aislada de los últimos eventos del día y abre una bandeja independiente. |

## Configuración

| Archivo | Responsabilidad |
|---|---|
| `config/normalization.json` | Año mínimo y criterios de calidad de normalización. |
| `config/baseline.json` | Separación de entrenamiento/evaluación y mínimo de historial por usuario. |
| `config/detection_rules.json` | Ventanas, umbrales, cooldown, riesgo y severidad de todas las reglas. |
| `config/exclusions.json` | Pseudónimos de cuentas técnicas, IP autorizadas y sus umbrales anómalos elevados. |
| `config/operational.json` | Tamaño de lote, intervalos, lookback y política de notificación. |

Los valores operativos se cambian en estos JSON; no se deben introducir números mágicos en el código.

## Código Python (`src/`)

| Archivo | Responsabilidad |
|---|---|
| `adfs_schema.py` | Define las 18 columnas esperadas y la clasificación conocida de eventos ADFS. |
| `runtime_config.py` | Carga `.env`, archivos JSON y la clave HMAC sin imprimir secretos. |
| `event_source.py` | Contrato común para CSV/PostgreSQL, consultas incrementales, validación de identificadores y sesión de solo lectura. |
| `normalize_events.py` | Valida, deduplica, clasifica y pseudonimiza usuarios/IP mediante HMAC-SHA256. |
| `build_baseline.py` | Construye perfiles históricos por usuario, IP, aplicación y hora sin usar información futura. |
| `detect_alerts.py` | Correlaciona eventos en ventanas y aplica las cinco reglas activas con riesgo explicable. |
| `sqlite_schema.py` | Crea y migra las tablas SQLite e índices necesarios. |
| `alert_store.py` | Persiste eventos, alertas, checkpoints, cooldown, entregas e historial de estados. |
| `notifications.py` | Define `NotificationProvider` e implementa el canal local `soc_inbox`. |
| `monitoring.py` | Orquesta un ciclo: ingesta, normalización, detección, persistencia y entrega. |
| `monitor_service.py` | CLI del monitor en modo `once` o `loop`; mantiene delgada la entrada de PowerShell. |
| `demo_service.py` | Ejecuta de forma reproducible el periodo de evaluación del CSV. |
| `demo_cli.py` | Entrada mínima utilizada por `run_demo.ps1`. |
| `live_sample.py` | Calcula un checkpoint aislado para consultar los últimos eventos del día sin alterar el principal. |
| `live_sample_cli.py` | Entrada mínima utilizada por `run_live_today.ps1`. |
| `generate_report.py` | Produce el reporte histórico Markdown y sus gráficos SVG. |
| `dashboard_service.py` | Prepara resúmenes y operaciones para la interfaz sin mezclar SQL con rutas web. |
| `web_app.py` | Define FastAPI, rutas, validación de estados, plantillas y archivos estáticos. |

## Interfaz

| Archivo | Función |
|---|---|
| `templates/base.html` | Estructura común, navegación lateral y logo institucional. |
| `templates/dashboard.html` | Resumen operativo de casos pendientes, severidad y actividad reciente. |
| `templates/alerts.html` | Bandeja con filtros de severidad, estado y regla. |
| `templates/alert_detail.html` | Evidencia y cambio de estado de un caso. |
| `templates/partials/alerts_table.html` | Tabla reutilizable de alertas. |
| `static/styles.css` | Diseño blanco institucional, navegación y colores de severidad. |
| `static/dashboard.js` | Consulta cambios cada cinco segundos y actualiza únicamente cuando existen datos nuevos. |
| `static/alert-detail.js` | Envía mediante API el cambio de estado de una alerta. |
| `static/utpl-institucional-azul.png` | Logo utilizado por la plataforma. |

## Herramientas

| Archivo | Uso |
|---|---|
| `tools/generate_secret.py` | Crea la clave HMAC externa cuando todavía no existe. |
| `tools/profile_csv.py` | Perfila estructura, calidad, fechas y cobertura del CSV sin publicar usuarios ni IP. |

## Pruebas

Las pruebas son parte esencial del entregable y usan datos sintéticos o mocks; no consultan la red UTPL.

| Archivo | Qué comprueba |
|---|---|
| `tests/test_normalize_events.py` | Rechazos, deduplicación y pseudonimización. |
| `tests/test_build_baseline.py` | Separación entrenamiento/evaluación y perfiles. |
| `tests/test_detect_alerts.py` | Reglas, ventanas, severidad, exclusiones y reducción de ruido. |
| `tests/test_alert_store.py` | SQLite, checkpoint, estados, historial, deduplicación y cooldown. |
| `tests/test_event_source.py` | CSV y PostgreSQL de solo lectura mediante mocks. |
| `tests/test_notifications.py` | Entrega única por `soc_inbox`. |
| `tests/test_demo_service.py` | Reproducibilidad del modo demo. |
| `tests/test_live_sample.py` | Cálculo del checkpoint de la muestra diaria. |
| `tests/test_monitor_service.py` | Ritmo del monitor y carga de exclusiones. |
| `tests/test_generate_report.py` | Generación del informe histórico. |
| `tests/test_web_app.py` | Endpoints, filtros y cambios de estado. |

Ejecución:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

## Datos y resultados (`data/` y `analysis/`)

| Ruta | Contenido |
|---|---|
| `data/INTEGRATIONDB_integrt_security_event_logs1.csv` | Fuente histórica oficial. Se abre en solo lectura. |
| `analysis/data_profile.json` | Perfil técnico del CSV. |
| `analysis/normalized_events.csv` | Eventos válidos, deduplicados y pseudonimizados. |
| `analysis/rejected_events.csv` | Registros rechazados con su motivo. |
| `analysis/normalization_stats.json` | Conteos de válidos, rechazados y duplicados. |
| `analysis/baseline/` | Resumen y perfiles de comportamiento habitual. |
| `analysis/alerts/` | Alertas reproducibles del análisis histórico CSV. |
| `analysis/report/` | Reporte histórico y gráficos. |
| `analysis/state/soc_alerts.db` | Estado operativo principal: eventos live, casos, estados y checkpoint. |
| `analysis/state/backups/` | Respaldo previo a operaciones de mantenimiento. |
| `analysis/reports/` | Resultados de auditorías operativas. |

Los archivos de `analysis/` son resultados generados. Pueden reconstruirse con `run_analysis.ps1`, excepto la SQLite principal y sus respaldos, que contienen el trabajo operativo acumulado.

## Tecnologías utilizadas

| Tecnología | Uso en el proyecto |
|---|---|
| Python 3.11+ | Procesamiento, reglas, servicios, CLI y pruebas. |
| FastAPI | API HTTP y rutas de la bandeja SOC. |
| Uvicorn | Servidor local ASGI. |
| Jinja2 | Renderizado HTML sin un frontend separado. |
| Pydantic | Validación de solicitudes de cambio de estado. |
| HTTPX2 | Cliente utilizado por `TestClient` para probar la API sin abrir la red. |
| psycopg 3 | Conexión PostgreSQL institucional en modo de solo lectura. |
| SQLite | Persistencia local, checkpoint, cooldown y trazabilidad. |
| HMAC-SHA256 | Pseudonimización determinista de usuarios e IP. |
| HTML, CSS y JavaScript | Interfaz institucional y actualización automática. |
| PowerShell | Automatización de instalación y modos de ejecución en Windows. |
| pytest | Pruebas automatizadas. |
| Ruff | Formato y análisis estático. |

No se utilizan machine learning, Docker, Redis, Celery, React, Angular ni servicios externos. El MVP permanece local, explicable y mantenible.
