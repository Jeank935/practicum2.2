# Despliegue portable del SOC

Objetivo: ejecutar la aplicación, el procesador, PostgreSQL propio del SOC y
Grafana mediante Docker Compose. La fuente PostgreSQL institucional se conserva
externa y de solo lectura. Las reglas de detección actuales no se modifican.

Las métricas de servicios se agrupan por minuto. El dominio institucional y las
restricciones de acceso se definirán con la UTPL antes de publicar el servicio.

## Alcance

- Web y procesador usan la misma imagen Python; no se cambia el detector.
- PostgreSQL institucional: origen externo de solo lectura.
- PostgreSQL SOC: destino independiente para eventos pseudonimizados, casos,
  estados, entregas, checkpoints y métricas.
- Grafana: visualización, no un segundo motor de detección.
- SQLite y los scripts PowerShell anteriores siguen disponibles por defecto.
- No se migra ni elimina automáticamente el SQLite existente.
- No se ejecutan purgas: la propuesta de retención necesita aprobación.

## Preparación

Desde la raíz real de este repositorio, con Docker Desktop iniciado en modo
contenedores Linux y Docker Compose v2:

```powershell
.\.venv\Scripts\python.exe tools/setup_docker.py
docker compose --env-file .env.docker config --quiet
docker compose --env-file .env.docker up -d --build web grafana
```

En otra máquina puede usar `python tools/setup_docker.py`; el script solo necesita
la biblioteca estándar. Conserva valores de .env.docker, añade secretos faltantes y reutiliza la clave HMAC local
si existe. Las credenciales institucionales NO se copian automáticamente.

- Web: http://127.0.0.1:8000
- Grafana: http://127.0.0.1:3000, usuario admin; contraseña GRAFANA_ADMIN_PASSWORD
  del archivo local .env.docker.
- Dashboard: carpeta SOC ADFS, “SOC ADFS · Servicios por minuto”.

PostgreSQL no publica su puerto al host. Los volúmenes persisten entre reinicios.
Los puertos web pueden cambiarse con SOC_WEB_PORT y SOC_GRAFANA_PORT.
No ejecute `docker compose config` sin --quiet si va a compartir la salida:
la configuración resuelta puede contener secretos.

## CSV histórico, sin UTPL

Configure SOC_CSV_PATH con el CSV local. No se incluye en la imagen ni se descarga.
El montaje es de solo lectura y exige que el archivo ya exista.

```powershell
docker compose --env-file .env.docker --profile demo run --rm demo
```

El proceso reutiliza normalización, línea base, evaluación y reporte del MVP.
Guarda el periodo de evaluación, no el entrenamiento, bajo fuente csv_demo_mvp.
En Grafana seleccione esa fuente y las fechas del histórico; “últimas 6 horas”
no mostrará eventos de meses anteriores. El informe queda en el volumen analysis
y puede descargarse desde /reports/latest. Repetir la demo no duplica los eventos.
No ejecute dos demos simultáneas: comparten los artefactos históricos.

## Fuente institucional

Complete SOLO en .env.docker SOC_DB_DSN (con política TLS institucional),
SOC_DB_VIEW, SOC_DB_TIME_COLUMN y SOC_DB_ID_COLUMN usando los valores ya validados.
SOC_STORAGE_* es exclusivamente el destino SOC; no lo configure con la UTPL.

Antes del primer arranque live, defina el checkpoint inicial autorizado si no
desea recuperar todo el histórico. Debe indicar tiempo e identificador juntos.
Un checkpoint guardado prevalece sobre estas variables; no lo borre para probar.

```powershell
docker compose --env-file .env.docker --profile live up -d worker
docker compose --env-file .env.docker logs --tail 50 worker
docker compose --env-file .env.docker stop worker
```

Solo el worker recibe credenciales de la fuente. Mantenga UNA instancia: el
cooldown actual no tiene bloqueo distribuido para varios detectores simultáneos.
El fallback a CSV conserva el comportamiento anterior y su fuente separada
csv_demo; no interprete actividad demo como conectividad institucional.
El worker requiere el CSV de fallback disponible. No se ha cambiado la política
de recuperación del origen ni la ventana de detección existente.

## Métricas y coste

Un trigger AFTER INSERT actualiza contadores por fuente, servicio y minuto UTC
en la misma transacción que el evento. Se usa event_count como peso, no el
número de filas. Rechazados y eventos sin servicio no alimentan estas métricas.
ON CONFLICT evita sumar eventos duplicados; eventos tardíos actualizan el minuto
original. No se reescanea la tabla completa para cada refresco de Grafana.

Grafana refresca cada minuto y muestra volumen, resultados, porcentaje de fallos
y resumen por servicio. Las consultas filtran el rango y la fuente; el usuario
soc_grafana solo tiene SELECT sobre soc_service_minute_dashboard. La vista no
incluye usuarios, IP ni URL de servicio. Los nombres proceden del catálogo;
servicios desconocidos reciben un identificador de presentación.

Un hueco en el gráfico no confirma ausencia de actividad o salud de la fuente.
Para periodos muy largos, millones de puntos también pueden ser costosos:
usar ventanas operativas acotadas. La carga de pico queda pendiente de medición.
La retención futura de eventos no deberá borrar acumulados mediante triggers.

## Seguridad y entrega

El piloto publica únicamente en 127.0.0.1. La web implementa OIDC local con
Keycloak, sesiones y autorización administrador/analista; consulte
[la guía de acceso](oidc_local.md). No cambie el bind a 0.0.0.0 antes de acordar
dominio, HTTPS, restricciones de red y pruebas de despliegue con UTPL.
La comunicación con PostgreSQL SOC usa la red local Docker sin TLS en este
piloto; use TLS validado si se separan hosts o lo exige la política institucional.
El origen mantiene su configuración TLS independiente.

.env.docker contiene secretos y debe protegerse mediante permisos del sistema
operativo. No se incluye en Git ni en el contexto de build. No comparta capturas.
Grafana está fijado por digest verificado en el registro oficial. Python y
PostgreSQL usan etiquetas de versión; antes de la entrega institucional fije
también sus digests aprobados y haga análisis de vulnerabilidades. Las
dependencias Python mantienen las versiones existentes.

No se enviarán logs a Grafana Cloud. Se desactiva el reporte de uso y las
comprobaciones de actualización de Grafana en esta configuración.

## Operación

```powershell
docker compose --env-file .env.docker ps
docker compose --env-file .env.docker logs --tail 50 init web
docker compose --env-file .env.docker --profile live stop
docker compose --env-file .env.docker --profile live down
```

NO añada -v a down: elimina volúmenes persistentes.
La UTPL definirá dominio, acceso de red, monitoreo del host, respaldos cifrados,
pruebas de restauración, responsables y actualizaciones. Docker facilita la
portabilidad; no proporciona alta disponibilidad ni respaldos por sí solo.
Cambiar POSTGRES_PASSWORD con un volumen existente no cambia la contraseña del
servidor automáticamente. Coordine la rotación; no borre volúmenes para resolverla.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m ruff check --no-cache src tools tests
.\.venv\Scripts\python.exe -m pytest -q
# Solo instancia PostgreSQL LOCAL y desechable, nunca la institucional:
$env:SOC_TEST_STORAGE_DSN="host=127.0.0.1 port=15439 user=postgres dbname=postgres connect_timeout=5"
.\.venv\Scripts\python.exe -m pytest -q tests/test_postgres_store.py
Remove-Item Env:SOC_TEST_STORAGE_DSN
```

Sin SOC_TEST_STORAGE_DSN, las pruebas PostgreSQL se omiten explícitamente;
el resto se ejecuta sin red UTPL. Las pruebas de integración crean y eliminan
únicamente esquemas sintéticos con nombres aleatorios.

La prueba Docker autocontenida está en tools/smoke_containers.py. Consulte
[resultados y límites de la validación](deployment_validation.md).
