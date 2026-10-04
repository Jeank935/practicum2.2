# Árbol del proyecto MVP SOC ADFS

Las rutas Python de este árbol corresponden a la organización anterior. Consulte
[el árbol y mapa actualizado del backend](backend_refactor.md#4-arquitectura-final)
para localizar sus módulos dentro de `src/practicum_soc/`.

Este documento resume la estructura del proyecto y la responsabilidad principal de cada archivo. Los datos reales, credenciales, claves HMAC, bases SQLite y cachés no deben versionarse.

## Flujo principal

```text
CSV histórico o PostgreSQL READ ONLY
    -> event_source.py
    -> normalize_events.py
    -> build_baseline.py
    -> detect_alerts.py
    -> alert_store.py y notifications.py
    -> dashboard_service.py
    -> web_app.py y templates
```

Los eventos aislados se conservan para el análisis histórico. Solo los patrones que superan los umbrales configurados se convierten en casos SOC.

## Estructura de archivos

```text
practicum_SOC/
|
|-- README.md                         # Instalación, comandos de ejecución y flujo operativo.
|-- requirements.txt                 # Dependencias Python mínimas y reproducibles.
|-- pyproject.toml                   # Configuración de pytest, Ruff y formato del código.
|-- .env.example                     # Plantilla segura para la conexión PostgreSQL.
|-- .gitignore                       # Excluye secretos, datos reales, SQLite, salidas y cachés.
|
|-- run_analysis.ps1                 # Ejecuta perfilado, normalización, línea base, reglas y reporte histórico.
|-- run_demo.ps1                     # Ejecuta el modo CSV y abre la bandeja SOC de demostración.
|-- run_monitor.ps1                  # Ejecuta una iteración o el monitoreo continuo CSV/PostgreSQL.
|-- run_live_today.ps1               # Analiza una muestra independiente de los últimos eventos del día.
|-- run_web.ps1                      # Abre únicamente la plataforma con la SQLite seleccionada.
|
|-- config/
|   |-- normalization.json           # Define el año mínimo y los motivos de rechazo.
|   |-- baseline.json                # Define entrenamiento, evaluación y suficiencia de historial.
|   |-- detection_rules.json         # Contiene umbrales, puntajes, severidades y cooldown de las reglas.
|   |-- exclusions.json              # Contiene cuentas e IP autorizadas y sus umbrales elevados.
|   |-- operational.json             # Controla lotes, intervalos, lookback, notificaciones y dashboard.
|   `-- service_catalog.json         # Traduce identificadores de servicios y asigna sensibilidad provisional.
|
|-- src/
|   |-- adfs_schema.py               # Define las 18 columnas y tipos de eventos ADFS conocidos.
|   |-- runtime_config.py            # Carga .env, JSON y clave HMAC sin exponer secretos.
|   |-- event_source.py              # Implementa CSV/PostgreSQL, consultas incrementales y READ ONLY.
|   |-- normalize_events.py          # Valida, rechaza, deduplica y pseudonimiza usuarios e IP.
|   |-- build_baseline.py            # Construye perfiles históricos sin utilizar eventos futuros.
|   |-- detect_alerts.py             # Correlaciona eventos, calcula riesgo y genera las cinco alertas.
|   |-- sqlite_schema.py             # Crea y migra el esquema local de SQLite.
|   |-- alert_store.py               # Persiste casos, estados, historial, cooldown, entregas y checkpoint.
|   |-- notifications.py             # Define NotificationProvider y el canal demostrativo soc_inbox.
|   |-- monitoring.py                # Coordina ingesta, normalización, detección, persistencia y entrega.
|   |-- monitor_service.py           # CLI del monitor en modo once o loop.
|   |-- demo_service.py              # Ejecuta de manera reproducible el análisis CSV de demostración.
|   |-- demo_cli.py                  # Entrada delgada utilizada por run_demo.ps1.
|   |-- live_sample.py               # Calcula la ventana aislada de los últimos eventos del día.
|   |-- live_sample_cli.py           # Entrada delgada utilizada por run_live_today.ps1.
|   |-- generate_report.py           # Genera el informe histórico y gráficos reproducibles.
|   |-- service_catalog.py           # Calcula métricas y contexto de uso de los servicios ADFS.
|   |-- dashboard_service.py         # Prepara consultas de la bandeja sin mezclar SQL con rutas HTTP.
|   `-- web_app.py                   # Define FastAPI, endpoints, plantillas y cambio de estados.
|
|-- templates/
|   |-- base.html                    # Estructura general, navegación lateral y encabezado institucional.
|   |-- dashboard.html               # Resumen de pendientes, investigación, criticidad y cierres.
|   |-- alerts.html                  # Bandeja filtrable por severidad, estado y regla.
|   |-- alert_detail.html            # Evidencia, riesgo, historial y acciones sobre un caso.
|   |-- services.html                # Métricas de servicios frecuentes, raros y sensibles.
|   `-- partials/
|       `-- alerts_table.html        # Tabla reutilizable de alertas para la interfaz.
|
|-- static/
|   |-- styles.css                   # Sistema visual institucional, responsive y colores de severidad.
|   |-- dashboard.js                 # Actualiza el resumen cuando cambia la versión de los datos.
|   |-- services.js                  # Actualiza las métricas de servicios cuando llegan eventos.
|   |-- alert-detail.js              # Envía cambios de estado y notas mediante la API.
|   `-- utpl-institucional-azul.png  # Logotipo institucional mostrado en la navegación.
|
|-- tools/
|   |-- profile_csv.py               # Perfila calidad, cobertura y estructura del CSV sin publicar PII.
|   `-- generate_secret.py           # Genera la clave HMAC externa cuando no existe.
|
|-- tests/
|   |-- test_normalize_events.py     # Prueba rechazo, deduplicación y pseudonimización.
|   |-- test_build_baseline.py       # Prueba la separación temporal y los perfiles históricos.
|   |-- test_detect_alerts.py        # Prueba reglas, riesgo, exclusiones y reducción de ruido.
|   |-- test_alert_store.py          # Prueba SQLite, estados, cooldown, historial y checkpoint.
|   |-- test_event_source.py         # Prueba CSV y PostgreSQL READ ONLY mediante mocks.
|   |-- test_notifications.py        # Prueba la entrega idempotente por soc_inbox.
|   |-- test_demo_service.py         # Prueba la reproducibilidad del modo CSV.
|   |-- test_live_sample.py          # Prueba la selección aislada de eventos recientes.
|   |-- test_monitor_service.py      # Prueba el ciclo, intervalos y carga de exclusiones.
|   |-- test_generate_report.py      # Prueba la construcción del informe histórico.
|   |-- test_service_catalog.py      # Prueba nombres, sensibilidad y métricas de servicios.
|   `-- test_web_app.py              # Prueba endpoints, filtros y cambios de estado.
|
|-- docs/
|   |-- architecture.md              # Explica las capas y el flujo técnico completo.
|   |-- audit_and_plan.md            # Registra el diagnóstico inicial y las fases ejecutadas.
|   |-- baseline.md                  # Documenta la línea base, resultados y limitaciones.
|   |-- data_dictionary.md           # Explica las columnas originales y normalizadas.
|   |-- rules_catalog.md             # Describe cada regla, umbral, evidencia y recomendación.
|   |-- alerts.md                    # Explica formato, persistencia y ciclo de vida de alertas.
|   |-- operations.md                # Indica cómo operar, mantener y recuperar el sistema.
|   |-- security.md                  # Documenta privacidad, secretos y acceso de solo lectura.
|   |-- defense_guide.md             # Ruta para demostrar y defender los entregables.
|   |-- project_guide.md             # Guía extendida de archivos y tecnologías.
|   `-- PROJECT_TREE.md              # Este árbol resumido del repositorio.
|
|-- data/
|   |-- README.md                    # Condiciones de uso y privacidad de los datos fuente.
|   `-- INTEGRATIONDB_*.csv          # CSV histórico oficial abierto únicamente en lectura.
|
`-- analysis/                        # Salidas reproducibles y estado operativo no versionable.
    |-- data_profile.json            # Perfil técnico y de calidad del CSV.
    |-- normalized_events.csv        # Eventos válidos, deduplicados y pseudonimizados.
    |-- rejected_events.csv          # Registros rechazados con su motivo.
    |-- normalization_stats.json     # Totales de entrada, válidos, rechazados y duplicados.
    |-- baseline/                    # Perfiles de usuarios, IP, horas, días y aplicaciones.
    |-- alerts/                      # Alertas y resumen del análisis histórico.
    |-- report/                      # Informe histórico y gráficos SVG.
    |-- reports/                     # Resultados de auditorías y mantenimientos controlados.
    `-- state/
        |-- soc_alerts.db            # SQLite principal con casos, estados y checkpoint live.
        |-- soc_live_today_*.db      # SQLite aislada creada por cada demostración diaria.
        `-- backups/                 # Respaldos anteriores a limpiezas o recalibraciones.
```

## Ubicación del puntaje de riesgo

El detector no mantiene los puntajes base como números fijos dentro de cada regla. La configuración y la lógica están separadas:

- `config/detection_rules.json`: define `base_risk`, bonificaciones y cortes de severidad.
- `src/detect_alerts.py`: suma el puntaje base, volumen y factores contextuales.
- `src/detect_alerts.py`: convierte el resultado numérico en baja, media, alta o crítica.

La fórmula aplicada es:

```text
riesgo = mínimo de 100 entre:
         puntaje base de la regla
       + eventos que superan el umbral
       + bonificaciones contextuales
```

Los cortes actuales son: baja desde 0, media desde 40, alta desde 65 y crítica desde 85.

## Comandos de verificación

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```
