# Sprint 7: actualización operativa y piloto

## Qué se implementó

La bandeja `/` recibe una señal SSE por `/api/v1/dashboard/stream` cuando cambia la revisión de casos. La señal solo contiene revisión y fuente; el navegador obtiene el resumen y la tabla de ocho casos por `/api/v1/dashboard/snapshot`. No hay navegación ni recarga completa. En Servicios, cuando cambia la revisión se sustituye únicamente la zona de contenido y se conservan filtros y paginación; si el analista está editando filtros o está en una página posterior, se avisa del cambio sin alterar su trabajo. La conexión SSE se cierra en pestañas ocultas, vuelve a conectar y usa consulta periódica como respaldo. Los intervalos están en `config/live_updates.json`.

El servidor relee la sesión durante el stream, de modo que revocar un usuario o vencer la sesión interrumpe los datos. La consulta de revisión reutiliza el contador incremental por fuente; la marca de última actualización usa un índice. No cuenta todas las alertas en cada comprobación. Una conexión SSE abierta consulta cada diez segundos; se renueva a los 120 segundos. Es adecuado para un piloto pequeño, **no equivale a una prueba de carga de la red institucional**.

## Activación en Docker

Realice primero el respaldo del PostgreSQL SOC y programe una ventana de mantenimiento. En la raíz del repositorio:

```powershell
docker compose --env-file .env.docker --profile live stop worker
docker compose --env-file .env.docker build
docker compose --env-file .env.docker run --rm init
docker compose --env-file .env.docker up -d web grafana
```

`init` añade índices idempotentes al PostgreSQL propio del SOC. El último comando no reinicia el monitor; tras verificar `/healthz` y el acceso OIDC, el operador decide cuándo reanudar `worker` según [la guía Docker](container_deployment.md). SQLite agrega los índices al abrirse con esta versión. Si se coloca un proxy delante de la web, debe permitir `text/event-stream` sin buffering y mantener la sesión privada; el despliegue actual permanece en loopback.

`GET /api/v1/operations/metrics` está limitado a administradores y devuelve:

- Último ciclo: fuente, estado, eventos, casos, error tipificado y duración.
- Errores de ciclos en 24 horas y bytes de la base SOC.
- Tiempo del evento hasta su almacenamiento SOC (`event_to_soc_seconds`) para el último evento ingerido y edad del último checkpoint. El primero incluye demora de la fuente y del monitor, pero no separa ambas; el segundo es diagnóstico, **no** retraso real extremo a extremo. Si no llegan autenticaciones, la edad del checkpoint crece aunque el monitor esté sano. La latencia ADFS→tabla institucional no puede medirse por separado sin una marca de recepción confiable de la fuente.
- Piloto de los últimos 30 días: hasta 500 casos recientes, cerrados, falsos positivos, mediana hasta la primera acción humana y mediana hasta el cierre. `sample_truncated=true` advierte que el resultado no abarca todos los casos. La tasa de falsos positivos usa solo casos cerrados como denominador; con cero cierres es `null`, no 0 %.

No se devuelven usuarios ni IP en estas métricas.

## Respaldos y recuperación

No incluya respaldos en Git. Contienen seudónimos, historial de casos y posiblemente datos de administración; guárdelos cifrados con acceso restringido. Antes de una restauración, detenga web y worker y conserve la base vigente. Una restauración siempre se ensaya primero en una **ruta o base nueva**.

### SQLite local

Desde la raíz del proyecto, con la carpeta `backups` creada:

```powershell
New-Item -ItemType Directory -Path .\backups -Force
.\.venv\Scripts\python.exe tools/backup_state.py backup .\analysis\state\soc_alerts.db .\backups\soc-2026-09-24.db
.\.venv\Scripts\python.exe tools/backup_state.py restore .\backups\soc-2026-09-24.db .\analysis\state\soc-restored.db
```

El CLI usa el mecanismo de copia consistente de SQLite, verifica integridad y rehúsa sobrescribir. Para volver a operar, apunte `SOC_STATE_DB` a `soc-restored.db` después de verificar casos, sesiones y configuración versionada. No copie directamente el archivo `.db` con el sistema activo: WAL puede contener transacciones todavía no volcadas.

### PostgreSQL propio del SOC en Docker

Ejemplo **manual**: elija un nombre y fecha propios; no publique los archivos ni pegue `.env.docker` en tickets. Estos comandos solo alcanzan al contenedor `postgres` del SOC, **nunca** a la base institucional. `docker cp` copia el binario sin pasar por la redirección de PowerShell.

```powershell
New-Item -ItemType Directory -Path .\backups -Force
docker compose --env-file .env.docker exec -T postgres pg_dump -U postgres -d soc -Fc -f /tmp/soc-pilot.dump
$socContainer = docker compose --env-file .env.docker ps -q postgres
docker cp "${socContainer}:/tmp/soc-pilot.dump" .\backups\soc-pilot.dump
```

Pruebe la recuperación en una base separada, sin tocar `soc`:

```powershell
docker compose --env-file .env.docker exec -T postgres createdb -U postgres soc_restore_test
docker cp .\backups\soc-pilot.dump "${socContainer}:/tmp/soc-restore.dump"
docker compose --env-file .env.docker exec -T postgres pg_restore -U postgres -d soc_restore_test --no-owner /tmp/soc-restore.dump
docker compose --env-file .env.docker exec -T postgres psql -U postgres -d soc_restore_test -c "SELECT COUNT(*) FROM alerts;"
```

Verifique también checkpoints, `rule_config_versions` e historial antes de solicitar un cambio controlado de base. No cambie el volumen ni reemplace `soc` automáticamente. Keycloak usa **otra** base (`identity-db`): planifique un respaldo/restauración independiente de ella. Los dashboards Grafana provisionados viven en el repositorio; cambios manuales en Grafana requieren respaldo propio.

## Piloto con analistas: pendiente de ejecución institucional

1. La Dirección designa participantes, duración, alcance de servicios y horario. Se acuerdan quién recibe incidencias y cómo documentar casos reales sin exportar identificadores a canales no autorizados.
2. En el entorno autorizado, se toma un respaldo verificable y se constata `/healthz`, `/health`, `/api/v1/operations/metrics`, el acceso de analista y el de administrador. Un analista no puede publicar reglas.
3. Durante el piloto, registre diariamente ciclos fallidos, edad de checkpoint, duración, casos abiertos, cierres, falsos positivos y mediana a la primera acción. Distinga actividad real de CSV demo y de periodos sin tráfico.
4. Revise con analistas una muestra de casos de cada regla. Un falso positivo exige clasificación humana; no se infiere solo del volumen. Registre la causa y la propuesta de umbral.
5. Antes de cambiar una regla, el administrador crea borrador y compara con histórico como en [Sprint 6](sprint6_rules.md). La Dirección debe aprobar por su canal acordado; el administrador copia la referencia de aprobación y el motivo en la justificación de publicación. La plataforma audita autor y fecha, pero **no verifica externamente** la aprobación. No se declara una regla aprobada sin esa evidencia.
6. Repita las métricas tras el ajuste y documente mejora y señales perdidas. Use rollback si aumenta el ruido o se debilita la detección.

**Pendientes reales:** autorización y ejecución del piloto por la UTPL, umbrales/SLA definitivos, prueba de carga con volumen de clases, dominio/HTTPS institucional, aprobación formal de reglas y retención/borrado acordados. El código no hace purgas automáticas ni afirma haber probado la base institucional.
