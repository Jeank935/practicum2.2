# Reorganización y rendimiento del backend

Fecha de verificación: 2 de octubre de 2026. Alcance: Python, SQL local, API,
pruebas, CLI y documentación del backend. No se cambiaron la interfaz,
los contratos de datos, las reglas de negocio ni la conexión institucional.
El repositorio ya contenía cambios del usuario en otros componentes; se conservaron.

## 1. Diagnóstico inicial

La aplicación funcionaba, pero numerosos módulos de distintas responsabilidades
compartían la raíz de `src/`. `web_app.py` componía la aplicación y agrupaba
rutas de alertas, servicios, resumen y monitoreo. Los modelos de entrada, la
presentación HTTP y algunas operaciones de servicio estaban juntos.
El motor, los repositorios y los comandos ya podían reutilizarse: no hacía falta
reescribirlos ni cambiar el flujo SOC.

Se revisaron README, configuración del proyecto, dependencias, módulos y pruebas.
No había un AGENTS.md aplicable que impusiera una arquitectura distinta.
La primera ejecución obtuvo 146 pruebas aprobadas y 17 omitidas sin PostgreSQL;
con PostgreSQL local, 163 aprobadas.

## 2. Problemas estructurales

- Resultaba difícil encontrar cada responsabilidad entre los módulos planos.
- Los imports dependían de nombres antiguos de la raíz de `src/`.
- La composición de recursos y las rutas estaban concentradas en la entrada web.
- Las herramientas ejecutadas directamente necesitaban una entrada compatible.
- La documentación histórica apuntaba a los nombres anteriores.

Se migró por etapas: esquemas y utilidades, repositorios, servicios, motor,
integraciones, CLI y finalmente rutas. Se ejecutaron pruebas entre etapas.

## 3. Cuellos de botella observados

La página y API de servicios repetían agregaciones y lectura del catálogo con
los mismos filtros. En la prueba inicial realizaban unas seis consultas de datos
por solicitud. Se eligió esa repetición como objetivo medido de optimización.

La paginación por cursor y la consulta agrupada de casos asociados ya existían.
Se conservaron, en lugar de introducir offsets grandes o una consulta por servicio.
No se detectó una razón suficiente para agregar un pool, Redis o una cola nueva.
Las conexiones locales siguen cerrándose al terminar cada operación.

## 4. Arquitectura final

Todos los paths siguientes son relativos a la raíz del proyecto.

```text
src/
├── web_app.py                 # Compatibilidad del arranque ASGI antiguo
├── ...                       # Otros diez lanzadores CLI delgados
└── practicum_soc/
    ├── main.py               # create_app, recursos, lifespan y routers
    ├── api/
    │   ├── dependencies.py   # Obtiene servicios desde app.state
    │   ├── errors.py         # Errores HTTP consistentes
    │   ├── navigation.py     # URLs y retorno seguro
    │   ├── streaming.py      # Actualizaciones SSE
    │   └── routes/           # Auth, alertas, servicios, reglas y monitoreo
    ├── core/                 # Configuración, caché, cursor, límites y paths
    ├── schemas/              # Modelos de entrada/salida y esquema ADFS
    ├── repositories/         # SQL, persistencia y consultas paginadas
    │   └── migrations/       # Instalación del esquema SOC local
    ├── services/             # Coordinación de casos de uso, sin FastAPI
    ├── soc/                  # Ingesta, normalización, línea base y detección
    ├── analytics/            # Métricas y reportes
    │   └── queries/          # SQL de analítica local
    ├── integrations/         # OIDC y notificaciones
    └── cli/                  # Argumentos y arranque de cada comando
```

Dependencias principales:

```text
Solicitud -> ruta + schemas -> servicio -> repositorio -> SQLite/PostgreSQL SOC
CLI -> fuente -> normalización/HMAC -> línea base -> detección -> persistencia
Servicio -> catálogo / analítica / integraciones
main -> app.state + dependencias + routers + lifespan
```

El motor no importa FastAPI y puede utilizarse sin levantar un servidor.
El PostgreSQL institucional continúa siendo una fuente de solo lectura:
las migraciones y escrituras corresponden únicamente al almacenamiento propio.

## 5. Archivos movidos, creados y modificados

La siguiente tabla permite traducir los imports y localizar las funciones antiguas.
El destino está dentro de `src/practicum_soc/`, salvo indicación contraria.

| Archivo anterior en src | Destino |
|---|---|
| web_app.py | main.py; api/routes/{alerts,dashboard,monitoring,services}.py; schemas/alerts.py |
| auth_web.py | api/routes/auth.py; schemas/auth.py |
| browse_web.py | api/routes/browsing.py; api/{dependencies,errors,navigation}.py |
| rule_web.py | api/routes/rules.py; schemas/rules.py; services/rules.py |
| api_errors.py | api/errors.py |
| live_updates.py | api/streaming.py |
| runtime_config.py | core/config.py |
| auth_config.py | core/auth_config.py |
| browsing_config.py | core/browsing_config.py |
| presentation.py | core/presentation.py |
| service_identity.py | core/service_identity.py |
| page_cursor.py | core/cursor.py |
| rate_limits.py | core/rate_limits.py |
| adfs_schema.py | schemas/events.py |
| browse_models.py | schemas/browsing.py |
| alert_store.py | repositories/alerts.py |
| postgres_store.py | repositories/postgres.py |
| store_factory.py | repositories/factory.py |
| auth_store.py | repositories/auth.py |
| rule_config.py | repositories/rules.py |
| browse_repository.py | repositories/browsing.py |
| state_backup.py | repositories/backup.py |
| sqlite_schema.py | repositories/migrations/sqlite.py |
| postgres_schema.py | repositories/migrations/postgres.py |
| browsing_schema.py | repositories/migrations/browsing.py |
| auth_schema.py | repositories/migrations/auth.py |
| rule_config_schema.py | repositories/migrations/rules.py |
| dashboard_service.py | services/dashboard.py |
| browse_service.py | services/browsing.py |
| demo_service.py | services/demo.py |
| monitoring.py | services/monitoring.py |
| service_catalog.py | services/catalog.py |
| configuration_audit.py | services/configuration_audit.py |
| rule_preview.py | services/rule_preview.py |
| historical_analysis.py | services/history.py |
| live_sample.py | services/live_sample.py |
| event_source.py | soc/ingestion.py |
| history_source.py | soc/history_source.py |
| normalize_events.py | soc/normalization.py; cli/normalization.py |
| build_baseline.py | soc/baseline.py; cli/baseline.py |
| detect_alerts.py | soc/detection.py; cli/detection.py |
| generate_report.py | analytics/reporting.py; cli/report.py |
| historical_report.py | analytics/historical_report.py |
| analytics_schema.py | analytics/schema.py |
| operational_metrics.py | analytics/operational.py |
| oidc_client.py | integrations/oidc.py |
| notifications.py | integrations/notifications.py |
| demo_cli.py | cli/demo.py |
| live_sample_cli.py | cli/live_sample.py |
| historical_cli.py | cli/historical.py |
| monitor_service.py | cli/monitor.py |
| container_demo.py | cli/container_demo.py |
| container_init.py | cli/container_init.py |
| Los tres SQL de analítica | analytics/queries/; contenido conservado |
| tools/profile_csv.py | cli/profile_csv.py; tools conserva el lanzador |
| tools/backup_state.py | cli/backup.py; tools conserva el lanzador |

Nuevos componentes: `core/paths.py`, `core/cache.py`,
`config/backend_performance.json`, `tools/backend_cli.py`,
`tools/benchmark_backend.py`, tres archivos de pruebas de backend y esta guía.
Se actualizaron imports en pruebas y herramientas, y se añadió una referencia en
README y en las guías antiguas. No se borraron CSV, bases, claves, credenciales
ni volúmenes: las eliminaciones de código corresponden a módulos trasladados.

## 6. Optimizaciones realizadas

- Un DashboardService por aplicación, guardado en `app.state`.
- Templates compartidos por aplicación; creación y cierre en la composición.
- `Depends` recupera los servicios; `main.py` reúne la configuración web.
- Modelos Pydantic y routers separados; contratos de respuesta conservados.
- Operaciones síncronas de SSE y auditoría de inicio fuera del event loop.
- Caché de catálogo y páginas agregadas de servicios por instancia.
- No se guarda una colección de eventos originales ni identidades reales en caché.
- Paginación SQL por cursor, límites y consultas agrupadas conservados.

La caché de páginas expira a los 5 segundos, admite 32 entradas y tiene un
presupuesto de payload serializado de 1 MiB. El límite no equivale exactamente
al heap de Python; también se limita el número de objetos.
El catálogo admite dos entradas y detecta cambios por fecha/tamaño de archivo.
Los parámetros están en `config/backend_performance.json`.

Una revisión de eventos/alertas en la base invalida el resultado al llegar datos
o cambiar estados. Filtros, cursor, orden, catálogo y clave de firma forman parte
de la clave. Se valida el cursor antes de consultar la caché. La caché vacía vuelve
al repositorio y las entradas demasiado grandes no se almacenan.
El lifespan limpia las cachés al cerrar; no hay estado mutable compartido global
para estos recursos.

## 7. Pruebas nuevas y actualizadas

- `test_backend_characterization.py`: rechazo, deduplicación, separación de siete
  días y resultados exactos de las cinco reglas sobre datos sintéticos.
- `test_backend_cache.py`: expiración, copias, límites, acceso concurrente,
  invalidación, cursor, catálogo, cierre de conexiones, lifespan y SSE.
- `test_backend_entrypoints.py`: seis comprobaciones de CLI y exportación ASGI.
- Pruebas existentes: imports nuevos, recursos por aplicación, permisos,
  persistencia SQLite/PostgreSQL, reglas, respuestas, paginación y carga local.

Las cinco alertas de caracterización conservan regla, severidad, puntaje,
evidencia, cantidad y fechas. Su JSON completo conserva la huella:
`90d253eca6e21d93c266e7f358b682ec34dc9d720daabf08cf5c2772a6b4a1bf`.
Los umbrales del fixture son de prueba; no sustituyen la configuración activa.

## 8. Comandos de verificación y compatibilidad

Desde la raíz real del proyecto:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests tools
.\.venv\Scripts\python.exe -m ruff format --check src tests tools
.\.venv\Scripts\python.exe -m pytest -q
$env:PYTHONPATH = "src;tests"
.\.venv\Scripts\python.exe tools/benchmark_backend.py
Remove-Item Env:PYTHONPATH
```

La prueba completa PostgreSQL se ejecutó dentro de Docker, con código montado
en solo lectura y `SOC_TEST_STORAGE_DSN` dirigido exclusivamente a la instancia
SOC local. Los fixtures crean esquemas aleatorios y los eliminan al finalizar.
Sin esa variable, se omiten 17 pruebas PostgreSQL; no se usa la fuente institucional.
No se publica la cadena de conexión de pruebas.

Los comandos públicos anteriores continúan siendo válidos:

```powershell
.\.venv\Scripts\python.exe -m uvicorn web_app:app --app-dir src --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe tools/profile_csv.py --help
.\.venv\Scripts\python.exe tools/backup_state.py --help
.\run_demo.ps1
.\run_analysis.ps1
.\run_monitor.ps1 -Source postgres -Mode loop
```

No se ejecutaron estos flujos contra datos reales para verificar la refactorización.
Los once lanzadores de `src/` son compatibilidad temporal, no copias del motor.
Las herramientas usan un proceso Python con PYTHONPATH del proyecto, como Docker;
no modifican `sys.path` y no requieren instalar setuptools ni un paquete nuevo.
Para imports en herramientas propias, use los nombres `practicum_soc.*`.
Los lanzadores solo deben retirarse cuando se actualicen todos sus consumidores.

## 9. Resultados de las pruebas

La verificación final completa, incluida la base PostgreSQL local, obtuvo
181 pruebas aprobadas. Ruff terminó sin errores y el formato quedó verificado.
La ejecución previa a las seis últimas pruebas de compatibilidad había obtenido
175 aprobadas. Ninguna prueba consultó PostgreSQL institucional.

Corrección posterior de arranque Docker: se restituyó `main()` en
`cli/container_init.py`, requerido por el lanzador antiguo. Se añadieron pruebas
de importación de los diez CLI y de delegación/redacción de errores de init.
La verificación focalizada de entradas y demo obtuvo 19 pruebas aprobadas.

## 10. Medición antes y después

Corpus equivalente: 10 000 eventos sintéticos, 5 001 alertas y 100 servicios,
SQLite temporal. FastAPI TestClient, tres solicitudes de calentamiento y veinte
mediciones seriales por endpoint. Auth desactivado únicamente en el proceso
aislado de benchmark; no se cambió la configuración del despliegue.
Todos los tiempos son milisegundos. A/D: antes/después.

| Endpoint | Mín A/D | Media A/D | Mediana A/D | p95 A/D | Bytes A/D | Consultas A/D |
|---|---:|---:|---:|---:|---:|---:|
| / | 28,46 / 19,53 | 33,61 / 21,31 | 32,96 / 20,93 | 38,89 / 24,00 | 10 664 / 10 664 | 5 / 5 |
| /alerts | 20,36 / 12,52 | 23,03 / 14,26 | 23,28 / 14,47 | 24,87 / 15,10 | 22 968 / 22 968 | 3 / 3 |
| /services | 52,06 / 8,99 | 63,26 / 10,24 | 61,72 / 9,90 | 72,56 / 12,69 | 22 820 / 22 820 | 6 / 2 |
| /api/v1/alerts | 12,30 / 6,76 | 13,20 / 7,44 | 13,23 / 7,37 | 14,27 / 8,28 | 9 409 / 9 409 | 2 / 2 |
| /api/v1/services | 54,74 / 6,27 | 60,98 / 7,00 | 61,32 / 6,98 | 69,14 / 7,62 | 3 850 / 3 850 | 6 / 2 |
| /api/dashboard-version | 9,64 / 5,14 | 12,39 / 7,28 | 12,57 / 6,05 | 13,85 / 7,16 | 107 / 107 | 3 / 3 |
| /api/services-version | 9,60 / 5,23 | 11,07 / 6,07 | 11,16 / 6,13 | 12,17 / 6,86 | 56 / 56 | 2 / 2 |
| /api/v1/dashboard/snapshot | 28,74 / 17,93 | 33,46 / 19,67 | 32,33 / 18,88 | 38,17 / 23,33 | 4 164 / 4 164 | 5 / 5 |

Alertas devuelve 25 casos; servicios, diez grupos; resumen/snapshot, ocho casos.
Las rutas de versión devuelven metadatos, no listas completas. La agregación
fría examina el corpus filtrado; no se midió el número exacto de filas visitadas
por el plan SQL. Una página de servicios sin caché conserva seis consultas.
La traza cuenta SQL de datos después de inicializar el repositorio: excluye DDL,
PRAGMA y autenticación, aunque la latencia HTTP sí incluye la construcción.

La medición aislada del repositorio de servicios fue de unos 12,59 ms antes y
12,27 ms después; no se reescribió su algoritmo. La ganancia comprobable es evitar
repetir la agregación al navegar con el mismo contexto. No se separaron todos los
tiempos de validación, Python y serialización. Las otras reducciones de latencia
no deben atribuirse por completo a la reorganización: existe variación del equipo.

## 11. Comportamiento conservado

No cambiaron umbrales, ventanas, severidades, línea base, cinco reglas,
exclusiones, deduplicación, HMAC, formatos HTTP ni canal soc_inbox.
Las mejoras afectan organización, reutilización de recursos y lecturas repetidas.
No se reprocesó el CSV oficial, no se migró una base de datos ni se cambiaron
cuentas o servicios externos.

## 12. Limitaciones de las mediciones

El benchmark no mide red, navegador, OIDC real ni renderizado del frontend.
Diez mil eventos no representan un periodo lectivo con millones de registros.
El p95 de veinte muestras es orientativo. Los resultados de caché corresponden
a lecturas calientes dentro de su TTL. La carga concurrente de pruebas verifica
contratos y recursos, pero no certifica capacidad operativa de producción.

## 13. Riesgos pendientes

- Las agregaciones frías pueden seguir siendo costosas con mucho histórico.
- Cada proceso web mantiene su propia caché; no es un almacenamiento compartido.
- Los módulos de repositorio extensos conservan operaciones históricas: se evitó
  una división adicional que aumentara el riesgo sin mejorar lo medido.
- La imagen Docker que ya estuviera ejecutándose no cambia solo al editar Python.
- Antes de entregar, revisar y versionar separadamente los cambios previos del usuario.

## 14. Recomendaciones

Medir con un corpus pseudonimizado de un periodo lectivo y carga concurrente;
observar latencia, memoria y consultas frías; usar EXPLAIN en la base SOC propia
antes de proponer índices o un pool. Mantener métricas del ciclo del monitor.
No cambiar índices ni esquema de la fuente institucional desde este proyecto.

Para incorporar este backend a la bandeja Docker sin reiniciar el worker:

```powershell
docker compose --env-file .env.docker up -d --build --no-deps web
```

Ese despliegue no se ejecutó como parte de estas pruebas. Si se cambia la imagen
del monitor posteriormente, hacerlo de forma controlada conservando su checkpoint.
