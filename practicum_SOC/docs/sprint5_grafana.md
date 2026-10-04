# Sprint 5: oscilaciones de servicios en Grafana

Grafana cubre tendencias; la bandeja SOC conserva investigación y cierre de casos. No se incorpora Power BI ni se cambian reglas de detección.

## Activar sobre el despliegue Docker existente

Desde la carpeta del proyecto, con Docker Desktop abierto y `.env.docker` ya configurado:

```powershell
docker compose --env-file .env.docker build
docker compose --env-file .env.docker --profile live stop worker
docker compose --env-file .env.docker up -d postgres
docker compose --env-file .env.docker run --rm init
docker compose --env-file .env.docker up -d web grafana
```

El inicializador crea las estructuras analíticas y completa el histórico local una sola vez. La primera ejecución toma un bloqueo de escritura sobre los eventos locales mientras agrega datos; realizarla en una ventana de mantenimiento con el monitor detenido. No consulta ni modifica PostgreSQL institucional. No borrar volúmenes.

Para cargar el CSV sin red UTPL:

```powershell
docker compose --env-file .env.docker --profile demo run --rm demo
```

Se conserva todo el histórico normalizado para analítica, pero el detector sigue usando únicamente evaluación. Repetir la carga no duplica eventos. La primera importación puede tardar más.

Abrir http://127.0.0.1:3000/d/adfs-services-oscillations (adaptar el puerto si se cambió). Iniciar sesión con las credenciales de Grafana existentes. Seleccionar fuente, fechas y agrupación Hora/Día. **Servicios → All (Todos)** muestra todos simultáneamente; también permite seleccionar varios. Para CSV o históricos institucionales, usar sus fechas, no «hoy». Se conserva el dashboard anterior por minuto y se añade un detalle individual al abrir un servicio.

## Qué muestra

- Vista conjunta: autenticaciones, fallos, bloqueos, tasa de fallos y casos abiertos, con una serie por servicio.
- Ranking de los diez servicios con más casos abiertos; la tabla completa conserva todos, ordenados por abiertos, críticos y fallos. Incluye todas las alertas del periodo, aunque estén cerradas.
- Última fecha de datos y último ciclo del monitor, para distinguir falta de actividad de un monitor detenido.
- Detalle individual: periodo anterior, referencia de entrenamiento, éxitos, fallos, bloqueos, distintos y desviación.
- Enlaces desde cada servicio a sus casos del mismo periodo y al detalle de Grafana.

La vista conjunta y el detalle se actualizan cada 30 segundos; el tablero anterior por minuto cada minuto. El monitor consulta cada 5 segundos (`config/operational.json`). Esto no elimina el retraso con el que ADFS registra los eventos. El máximo de consulta es 31 días. La variable `web_url` debe apuntar a la bandeja SOC accesible al operador. Los enlaces conservan fuente, servicio e intervalo; requieren una sesión SOC autorizada. Grafana no otorga acceso adicional al SOC.

Si «Últimos datos disponibles» es anterior al rango seleccionado, las gráficas estarán vacías aunque el monitor funcione. El histórico institucional cargado en esta revisión llega al **24 de septiembre de 2026, 19:59 (Loja)**: para demostrarlo, seleccionar del 1 de septiembre al 1 de octubre. Para monitoreo nuevo, usar últimas horas y revisar que avance la fecha de datos. El último ciclo muestra cuándo se consultó la fuente, no cuándo ocurrió la última autenticación.

## Monitor en vivo (Docker)

Conectado a la red autorizada y con `.env.docker` ya configurado:

```powershell
docker compose --env-file .env.docker --profile live up -d web grafana worker
docker compose --env-file .env.docker logs -f --tail 20 worker
```

La salida debe indicar `postgresql_live`. `fetched: 0` significa que no hay filas nuevas después del checkpoint. Ctrl+C deja de mostrar los logs; no detiene el monitor. No ejecutar un segundo monitor PowerShell con SQLite esperando verlo en Grafana Docker.

## Interpretación y límites

Se usan horas y días de America/Guayaquil. Los extremos se ajustan a intervalos completos. El periodo anterior tiene la misma duración ajustada. Un intervalo actual sin terminar se identifica como parcial. La ausencia de datos no se presenta como cero, ni como ausencia de ataques.

La referencia utiliza exclusivamente entrenamiento anterior al comienzo del periodo consultado. Reutiliza fechas y criterios de días completos de `config/baseline.json`; exige las muestras de `config/analytics.json`. Para horas se compara la misma hora local; para días, el volumen diario. Si faltan datos suficientes aparece sin referencia, no una desviación inventada. Las fechas de entrenamiento históricas deben validarse antes de evaluar periodos futuros.

Los distintos son exactos por intervalo: no deben sumarse para obtener distintos de todo el periodo. **Vista conjunta:** cada caso se cuenta una vez por servicio, en el intervalo donde termina su evidencia; abiertos significa `new`, `notified` o `investigating` en su estado actual, no el estado que tenía entonces. Un caso puede estar asociado a varios servicios: sumar servicios no da casos globales únicos. **Detalle individual:** un caso que cruza intervalos puede aparecer en ambos. Los porcentajes comparativos no se calculan cuando el denominador es cero o falta. Una alerta es una señal pendiente de revisión, no un ataque confirmado.

SQLite continúa disponible para el flujo local, pero este dashboard requiere PostgreSQL SOC. Las vistas no publican IP, identificadores de usuario ni URLs internas; exponen nombres de servicios, claves de servicio y métricas. La cuenta `soc_grafana` solo recibe lectura y ejecución de la consulta analítica, sin acceso a tablas de eventos ni permisos de escritura.

## Archivos

| Ruta | Responsabilidad |
| --- | --- |
| `config/analytics.json` | Límite temporal y muestras mínimas. |
| `src/analytics_schema.py` | Instalación, política y migración idempotente. |
| `src/analytics_tables.sql` | Agregados incrementales y distintos exactos; mantiene inserciones, cambios y borrados. |
| `src/analytics_backfill.sql` | Agregación inicial de eventos locales ya existentes. |
| `src/analytics_queries.sql` | Vistas de lectura, comparaciones, referencia y asociación con casos. |
| `src/service_identity.py` | Clave determinista del servicio para navegación sin URL interna. |
| `src/container_init.py` | Permisos de aplicación y de Grafana. |
| `src/browse_models.py`, `src/browse_repository.py` | Validación y filtros de casos por fuente, servicio e intervalo. |
| `deploy/grafana/dashboards/oscillations.json` | Vista conjunta, ranking de abiertos y tabla completa; multiselección. |
| `deploy/grafana/dashboards/service_detail.json` | Seis paneles de un servicio, comparación, referencia y enlaces. |
| `tests/test_analytics.py` | Conteos, referencia, migración, límites y permisos PostgreSQL. |
| `tools/verify_grafana_browser.cjs` | Verificación de Grafana real con datos sintéticos. |

Cambiar fechas o límites exige volver a ejecutar `init` con la imagen actualizada. Cambiar zona horaria necesita una migración explícita. Las tablas auxiliares de entidades aportan exactitud, a cambio de almacenamiento y trabajo de escritura adicional; medir esto durante el piloto con volumen representativo. Este sprint no activa eliminación automática a los 30 días ni modifica la política de conservación existente.

La función `soc_services_overview` consulta agregados locales, no la tabla institucional ni identidades. Admite varios servicios, conserva servicios con alertas sin métricas y cuenta casos distintos. `soc_monitor_health` expone únicamente tiempos y conteos operativos. La opción All usa un literal SQL fijo entre comillas, porque Grafana inserta el valor personalizado sin aplicar `:sqlstring`.

## Verificación

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

Las pruebas PostgreSQL requieren `SOC_TEST_STORAGE_DSN` apuntando exclusivamente a una base local de pruebas. La prueba `tools/smoke_containers.py` requiere Docker, Node y Playwright con Edge; crea datos y volúmenes temporales aislados, que elimina al terminar. Nunca configurar esa prueba contra UTPL.

La navegación utiliza [enlaces de datos de Grafana](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-data-links/) para trasladar el intervalo a la bandeja.
