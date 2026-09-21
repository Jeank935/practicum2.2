# Sprint 4: API, paginación y experiencia del analista

## Qué cambia

Se conserva FastAPI, Jinja2 y JavaScript progresivo. No cambian las reglas,
el scoring, el checkpoint de ingesta ni los permisos de los dos roles.
La fuente institucional sigue siendo de solo lectura; los índices y migraciones
de este sprint pertenecen exclusivamente al almacenamiento del SOC.

- Alertas: combinar fecha inicial/final, regla, severidad, estado y servicio.
- Ordenar por riesgo, más recientes o más antiguos.
- Servicios: combinar periodo observado, fechas, servicio y sensibilidad;
  ordenar por volumen, fallos, actividad reciente o identificador técnico.
- 25 elementos por defecto; entre 1 y 100 por página.
- Anterior, Siguiente y Primera sin cargar toda la cola en Python.
- Abrir un caso y usar «Volver al listado» conserva filtros, tamaño, orden y cursor.
- Se anuncian carga, ausencia de resultados y errores; la navegación funciona sin JavaScript.
- La actualización de Servicios consulta una revisión incremental. En páginas
  posteriores o al editar filtros avisa de cambios sin interrumpir la navegación.

Las fechas se interpretan en America/Guayaquil: «Hasta» incluye todo ese día.
En alertas se filtra la fecha inicial del patrón, no la fecha en que se importó.
En Servicios, el periodo de últimos días parte del último evento disponible,
no del reloj del equipo; si se indican fechas se aplica la intersección.

## API y OpenAPI

Iniciar sesión en la plataforma antes de abrir /docs o /openapi.json.
Los endpoints mantienen autenticación y limitación de solicitudes por operador.

- GET /api/v1/alerts
- GET /api/v1/services

Ejemplos para abrir en el mismo navegador con sesión:

    /api/v1/alerts?page_size=25&severity=high&status=new&sort=newest
    /api/v1/alerts?date_from=2026-03-16&date_to=2026-03-16&rule_id=AUTH_ACCOUNT_LOCKOUT
    /api/v1/services?window_days=7&page_size=25&sort=failures&sensitive=true

El parámetro service utiliza el identificador exacto del catálogo (codificado como URL).
La interfaz muestra su nombre legible. No se admite SQL ni nombres libres de columnas
para ordenar.

Respuestas: data (lista limitada), page (tamaño, número orientativo, cursores
anterior/siguiente y disponibilidad), source (fuente activa).
Para avanzar, enviar next_cursor como cursor conservando exactamente los filtros,
el orden y el tamaño. No fabricar ni interpretar el cursor.
Errores: error.code, error.message y error.fields; 400 cursor incompatible,
401 sin sesión, 422 filtros inválidos, 429 límite con Retry-After,
503 indisponibilidad. No se reflejan valores de entrada ni excepciones internas.

## Cómo funciona y límites

La paginación usa keyset: fecha/riesgo más identificador único como desempate.
Cada consulta recupera como máximo el tamaño pedido más una fila de comprobación.
No usa OFFSET ni cuenta todos los casos para calcular páginas.
Los cursores están firmados con HMAC y ligados a fuente, filtros y orden.
Cambiar esos parámetros obliga a empezar en la primera página.
La firma protege integridad; no es cifrado ni sustituye el control de acceso.

Con datos nuevos o casos que cambian de orden, no hay una instantánea congelada
entre solicitudes. La numeración orienta sobre el recorrido, no promete un número
total de páginas. Volver a Primera reinicia la consulta.

Los servicios se agrupan y ordenan en SQL; solo se transfieren la página,
los 10 servicios principales y los agregados escalares. Los porcentajes se
calculan sobre todo el periodo filtrado, no sobre la página. La tabla de
servicios sensibles y su indicador se refieren a la página actual.
COUNT DISTINCT y las agregaciones todavía recorren el periodo dentro de la base:
esto reduce transferencia/memoria de la aplicación, pero no garantiza coste
constante para millones de eventos. Grafana conserva su agregado por minuto.

## Archivos principales

| Ruta | Responsabilidad |
| --- | --- |
| config/browsing.json | Tamaños, zona horaria, lote de migración y objetivo local de respuesta |
| src/browse_models.py | Filtros y contratos Pydantic de OpenAPI |
| src/page_cursor.py | Firma, validación y paginación por claves |
| src/browse_repository.py | SQL parametrizado, filtros, orden y agregados |
| src/browse_service.py | Orquestación y nombres/contexto de servicios |
| src/browse_web.py | API, navegación segura y errores HTML/JSON |
| src/api_errors.py | Formato común de errores |
| src/browsing_schema.py | Migración e índices del SOC y revisiones incrementales |
| src/web_app.py | Rutas HTML delgadas |
| templates/partials/browse_filters.html | Controles compartidos |
| templates/partials/pagination.html | Navegación de páginas |
| templates/browse_error.html | Recuperación ante consulta inválida o indisponible |
| static/browse.js y static/browse.css | Carga accesible y distribución adaptable |
| config/auth.json | Límite compartido de consultas HTML/API por operador |
| tests/test_browsing.py | Filtros, cursores, migración, API y regreso |
| tests/test_browsing_load.py | Medición sintética SQLite/PostgreSQL e índice utilizado |
| tools/smoke_containers.py | Integración aislada con Keycloak, PostgreSQL y Grafana |
| tools/verify_oidc_browser.cjs | Navegación autenticada y verificación visual sintética |

## Actualizar y ejecutar

Desde la raíz real del proyecto, con Docker Desktop abierto:

    docker compose --env-file .env.docker build web init
    docker compose --env-file .env.docker run --rm init
    docker compose --env-file .env.docker up -d web grafana

No ejecutar down -v: borraría volúmenes. No hace falta recuperar logs ni iniciar
el worker para probar esta interfaz con datos ya almacenados.
En una instalación compartida, respaldar el PostgreSQL propio del SOC y coordinar
una ventana para la migración antes de actualizar los procesos que lo utilizan.

La migración conserva alertas/eventos; añade fecha UTC normalizada,
relaciones alerta-servicio, índices y revisiones. El relleno se lee en lotes de
500, aunque PostgreSQL aplica la migración completa en una transacción.
SQLite la aplica al abrir una base antigua; las conexiones posteriores solo
verifican su marcador, sin repetir actualizaciones masivas.

La firma usa SOC_CURSOR_SECRET si está definida; en su defecto la clave OIDC
o la clave HMAC local existente. Todos los procesos web deben usar la misma clave.
Rotarla invalida enlaces de páginas anteriores, no alertas.

## Verificación

    .\.venv\Scripts\python.exe -m ruff check src tests tools
    .\.venv\Scripts\python.exe -m pytest -q
    .\.venv\Scripts\python.exe -m pytest tests/test_browsing_load.py -q -s

Para incluir PostgreSQL, definir SOC_TEST_STORAGE_DSN contra una instancia
local desechable con permiso para crear esquemas. Las pruebas rechazan hosts
externos y eliminan solo los esquemas aleatorios que crean.
Sin esa variable se omiten las pruebas PostgreSQL explícitamente.

Objetivo técnico provisional de consulta: menos de 2000 ms en la medición local
de 5001 alertas, 10000 eventos y 100 servicios por motor. No constituye un SLA
institucional ni demuestra capacidad para millones de eventos o muchos usuarios
simultáneos. Es distinto del retraso de 2–3 minutos de llegada de logs.
El piloto y las pruebas de concurrencia a escala siguen correspondiendo al Sprint 7.
