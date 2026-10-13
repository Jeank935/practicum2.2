# Operación y demostración

Ejecute desde la carpeta que contiene `compose.yaml`.
Docker Desktop debe estar iniciado. No sobrescriba secretos ni archivos de un
entorno existente. Los comandos siguientes no cambian la base institucional.

## Arrancar la plataforma

```powershell
python tools/setup_docker.py
docker compose --env-file .env.docker config --quiet
docker compose --env-file .env.docker up -d --build web grafana
```

Web: <http://127.0.0.1:8000>. Grafana: <http://127.0.0.1:3000>.
Keycloak usa el puerto `SOC_IDP_PORT` de `.env.docker` (8080 por defecto).
Compose inicia sus dependencias. Este arranque permite ver datos almacenados;
no inicia el monitor continuo.

En una instalación nueva, `soc-admin` y `soc-analyst` usan las contraseñas
`SOC_BOOTSTRAP_ADMIN_PASSWORD` y `SOC_BOOTSTRAP_ANALYST_PASSWORD` del entorno privado.
Cambiar esas variables no restablece cuentas existentes. Administre cuentas
en Keycloak y permisos de operadores desde la plataforma.

## Ingesta real desde UTPL

Configure `.env` con la conexión autorizada; `SOC_DB_*` es el origen y
`SOC_STORAGE_*` es la base propia del SOC. No los intercambie.

```powershell
python tools/setup_docker.py --source-env .env
docker compose --env-file .env.docker --profile live up -d --build web grafana worker
docker compose --env-file .env.docker logs -f --tail 20 worker
```

Debe aparecer `postgresql_live` en ciclos completados. CSV indica demostración
o fallback, no conexión institucional. Cero eventos puede significar que no hay
nuevos registros. La demora incluye el registro institucional, la ingesta y el
refresco de la interfaz.

El worker necesita el CSV autorizado de fallback configurado en `SOC_CSV_PATH`.
Mantenga una sola instancia. En un volumen Docker nuevo, prepare la línea base:

```powershell
docker compose --env-file .env.docker --profile demo run --rm --no-deps -T demo python src/normalize_events.py /data/events.csv --output analysis/normalized_events.csv --rejected-output analysis/rejected_events.csv --stats-output analysis/normalization_stats.json
docker compose --env-file .env.docker --profile demo run --rm --no-deps -T demo python src/build_baseline.py analysis/normalized_events.csv --output-dir analysis/baseline
```

Hágalo antes del primer arranque del worker. Acuerde el inicio de lectura mediante
`SOC_INITIAL_CHECKPOINT_TIME_UTC` y `SOC_INITIAL_CHECKPOINT_EVENT_ID` juntos.
Un checkpoint guardado prevalece; no lo borre para una prueba.

```powershell
# Detener solo la ingesta
docker compose --env-file .env.docker --profile live stop worker
# Reanudar tras recuperar conectividad
docker compose --env-file .env.docker --profile live up -d worker
```

`Ctrl+C` en los logs solo cierra el visor. No detiene el contenedor.

## Demo e histórico

CSV, sin red UTPL:

```powershell
docker compose --env-file .env.docker --profile demo run --rm demo
```

Para agosto y septiembre de 2026 desde PostgreSQL, con acceso autorizado:

```powershell
docker compose --env-file .env.docker --profile live stop worker
docker compose --env-file .env.docker run --rm --no-deps -T worker python src/historical_cli.py --from-date 2026-08-01 --to-date 2026-10-01 --output-dir analysis/reports/history_2026_08_09
```

La fecha final es exclusiva. Guarda eventos, casos y métricas en el SOC sin mover
el checkpoint live. No usa CSV si falla esta consulta. No ejecute análisis
históricos simultáneos; para intervalos grandes, revise memoria y límites.
En Grafana seleccione la fuente y las fechas analizadas.

## Alternativa PowerShell

Requiere `.venv` con `requirements.txt` y configuración OIDC. Usa SQLite por
defecto, separado del PostgreSQL de Docker.

```powershell
.\run_web.ps1
.\run_monitor.ps1 -Source postgres -Mode once
.\run_monitor.ps1 -Source postgres -Mode loop
.\run_live_today.ps1 -Limit 500 -Port 8001
.\run_demo.ps1
```

Son alternativas: no ejecute todos a la vez. La muestra diaria lee hasta
500 eventos, no 500 alertas, en un destino independiente; abre el puerto 8001.
La excepción sin autenticación solo es válida para demo en loopback.

## Comprobación y respaldo

Revise `/healthz`, `/health`, logs del worker y
`/api/v1/operations/metrics` (administrador). Distinga desconexión de falta de tráfico.
Para pruebas locales:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tools tests
```

Respaldo del PostgreSQL propio, no del institucional:

```powershell
New-Item -ItemType Directory -Path .\backups -Force
docker compose --env-file .env.docker exec -T postgres pg_dump -U postgres -d soc -Fc -f /tmp/soc-pilot.dump
$socContainer = docker compose --env-file .env.docker ps -q postgres
docker cp "${socContainer}:/tmp/soc-pilot.dump" .\backups\soc-pilot.dump
```

Use nombres nuevos para no sobrescribir respaldos. Pruebe la restauración con
`pg_restore` en una base separada antes de cambiar el destino de producción.
Keycloak (`identity-db`), Grafana y la clave HMAC necesitan respaldo independiente.
Nunca ejecute `docker compose down -v` sobre una instalación que desea conservar.
