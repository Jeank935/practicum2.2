# MVP SOC para autenticaciones ADFS

## Nuevo: despliegue portable Docker + PostgreSQL SOC + Grafana

El flujo local SQLite continúa funcionando. Para el nuevo despliegue, abra
Docker Desktop y siga [la guía Docker](docs/container_deployment.md).
No se modifican la base institucional, las reglas actuales ni los datos SQLite.

```powershell
.\.venv\Scripts\python.exe tools/setup_docker.py
docker compose --env-file .env.docker up -d --build web grafana
docker compose --env-file .env.docker --profile demo run --rm demo
```

Web: http://127.0.0.1:8000 · Grafana: http://127.0.0.1:3000.
En Grafana seleccione la fuente y las fechas del CSV; se agrupa por minuto.
El modo live se inicia explícitamente tras configurar fuente y checkpoint;
los comandos y precauciones están en la guía. No copie credenciales a Git.
El acceso ahora requiere OIDC local con Keycloak y los roles administrador y
analista. Consulte [acceso y usuarios](docs/oidc_local.md). Las identidades de los
operadores son independientes de los usuarios que aparecen en logs ADFS.
El Sprint 3 añade auditoría de consultas a casos, control de cambios externos de
configuración y límites persistentes de solicitudes. Consulte el
[alcance y pruebas del Sprint 3](docs/sprint3_access_audit.md).

El Sprint 4 añade API privada versionada, filtros combinables y páginas por cursor
en Alertas y Servicios, sin reemplazar Jinja2. Consulte
[la guía de navegación y API](docs/sprint4_api_pagination.md).

Aplicación local para normalizar eventos ADFS, detectar anomalías explicables y gestionar casos desde una bandeja SOC. El sistema consulta PostgreSQL en modo de solo lectura y pseudonimiza usuarios e IP cliente mediante HMAC-SHA256 antes de almacenarlos o mostrarlos.

La solución apoya al analista: prioriza señales y conserva evidencia. No confirma ataques por sí sola, no bloquea cuentas y no modifica ADFS ni PostgreSQL.

## Requisitos iniciales

- Windows PowerShell.
- Python 3.11 o superior.
- Acceso autorizado a la red y PostgreSQL de UTPL para el modo live.
- Archivo `.env` configurado y excluido de Git.
- Clave HMAC en `.secrets/pseudonym_key.txt`.

```powershell
cd "C:\ruta\del\proyecto\practicum_SOC"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools\generate_secret.py .secrets\pseudonym_key.txt
Copy-Item .env.example .env
```

Complete `.env` con las credenciales institucionales. No comparta ni versione ese archivo.

## Abrir únicamente la plataforma

Este comando abre la bandeja con los casos que ya estén guardados en la SQLite principal. No consulta PostgreSQL.

La web exige OIDC por defecto. Para usar este arranque configure el proveedor
según la guía OIDC. Solo para la demostración local heredada sin login, establezca
`$env:SOC_AUTH_MODE="disabled"` en esa consola; se permite exclusivamente loopback.
No use esa excepción en el despliegue institucional.

```powershell
cd "C:\ruta\del\proyecto\practicum_SOC"
.\run_web.ps1
```

Abra [http://127.0.0.1:8000](http://127.0.0.1:8000) y detenga el servidor con `Ctrl+C`.

## PostgreSQL: una sola iteración

Consulta únicamente los eventos posteriores al checkpoint, normaliza, detecta casos y termina.

```powershell
cd "C:\ruta\del\proyecto\practicum_SOC"
.\run_monitor.ps1 -Source postgres -Mode once
```

Es útil para comprobar manualmente la conexión sin dejar un proceso permanente.

## PostgreSQL en tiempo casi real

Utilice dos terminales.

Terminal 1 — monitor institucional:

```powershell
cd "C:\ruta\del\proyecto\practicum_SOC"
.\run_monitor.ps1 -Source postgres -Mode loop
```

Terminal 2 — bandeja SOC:

```powershell
cd "C:\ruta\del\proyecto\practicum_SOC"
.\run_web.ps1
```

La bandeja comprueba cada 5 segundos si hay casos nuevos y solo recarga cuando detecta cambios. El monitor utiliza el checkpoint principal de `analysis/state/soc_alerts.db`; si existe atraso pendiente, continuará desde ese punto antes de alcanzar el presente.

## Prueba live: últimos 500 eventos del día

Esta es la opción recomendada para una exposición. Consulta como máximo los 500 eventos más recientes del día en que se ejecuta el comando, aplica las reglas y muestra únicamente los casos generados.

```powershell
cd "C:\ruta\del\proyecto\practicum_SOC"
.\run_live_today.ps1
```

Después abra [http://127.0.0.1:8001](http://127.0.0.1:8001).

También puede elegir otra cantidad o puerto:

```powershell
.\run_live_today.ps1 -Limit 500 -Port 8001
```

Propiedades de esta prueba:

- PostgreSQL se abre en modo `READ ONLY`.
- Solo considera eventos cuya fecha corresponde al día actual de Loja, Ecuador.
- Procesa como máximo la cantidad indicada.
- Crea una SQLite independiente con nombre `analysis/state/soc_live_today_FECHA_HORA.db`.
- No modifica el checkpoint principal ni reactiva la recuperación histórica.
- No muestra usuarios o IP reales.
- Puede producir menos de 500 casos, porque 500 eventos no equivalen a 500 alertas.
- Si ningún evento cumple las reglas, la bandeja mostrará cero casos; eso no representa un fallo.

El script deja la bandeja de prueba activa hasta presionar `Ctrl+C`.

## Modo demo con CSV

El modo CSV se conserva para ejecutar la solución fuera de la red UTPL:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_demo.ps1
```

El CSV original se abre en solo lectura y nunca se modifica. Este modo no debe confundirse con la prueba PostgreSQL de los últimos 500 eventos.

## Flujo de atención SOC

1. El monitor recibe eventos de autenticación.
2. Los datos se normalizan y pseudonimizan.
3. Las reglas generan una alerta cuando encuentran un patrón sospechoso.
4. La alerta entra como caso `new` o `notified`.
5. El analista la cambia a `investigating` y registra una nota.
6. Si era actividad legítima, se cierra como `false_positive`.
7. Si se confirma y se atiende, se cierra como `resolved`.

Estados permitidos: `new`, `notified`, `investigating`, `resolved` y `false_positive`.

## Reglas activas

- Seis o más fallos contra un usuario en diez minutos.
- Seis o más fallos desde una IP contra al menos tres cuentas en diez minutos.
- Éxito después de múltiples fallos.
- Bloqueos múltiples de una cuenta.
- IP nueva con actividad repetida para un usuario con historial suficiente.

Las reglas de horario nocturno/inusual y red externa permanecen desactivadas hasta validar horarios, CIDR, NAT, proxy y VPN oficiales con la Dirección.

## API

- `GET /`
- `GET /alerts`
- `GET /alerts/{id}`
- `PATCH /alerts/{id}/status`
- `GET /services`
- `GET /health`
- `GET /api/dashboard-version`
- `GET /api/services-version`
- `POST /demo/run`
- `GET /reports/latest`

## Calidad y pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
```

Las pruebas utilizan datos sintéticos y mocks; no requieren conexión con la red UTPL.

## Ubicación de las reglas de detección

- `config/detection_rules.json`: habilitación, ventanas, umbrales, cooldown y puntajes.
- `src/detect_alerts.py`: correlación y generación explicable de las alertas.
- `config/exclusions.json`: cuentas técnicas e IP autorizadas con umbrales elevados.
- `docs/rules_catalog.md`: descripción funcional para operación y defensa del proyecto.

La sección **Servicios** es analítica. Un servicio poco frecuente no genera una alerta por sí
solo; sirve como contexto para revisar el comportamiento antes de clasificar una actividad.

Documentación adicional:

- `docs/project_guide.md` — función de cada archivo y tecnologías.
- `docs/architecture.md`
- `docs/rules_catalog.md`
- `docs/operations.md`
- `docs/security.md`
- `docs/defense_guide.md`
