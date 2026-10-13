# SOC ADFS — UTPL

Plataforma para analizar autenticaciones institucionales, detectar patrones
sospechosos y ayudar al analista a investigar casos. Consulta la fuente UTPL
en solo lectura: no bloquea cuentas ni confirma ataques automáticamente.

## Qué incluye

Ingesta y normalización, línea base, reglas y puntajes configurables, bandeja
de casos, reporte histórico, acceso por roles y dashboards de servicios.
Los fallos aislados se conservan como eventos, sin generar un caso por sí solos.

**Tecnologías:** Python, FastAPI, Jinja2, JavaScript, PostgreSQL, Keycloak/OIDC,
Grafana y Docker Compose. SQLite queda como alternativa local.
El PostgreSQL SOC es independiente de la base institucional.

## Arrancar con Docker

Desde la carpeta que contiene `compose.yaml`, con Docker Desktop iniciado:

```powershell
python tools/setup_docker.py
docker compose --env-file .env.docker config --quiet
docker compose --env-file .env.docker up -d --build web grafana
```

Web: <http://127.0.0.1:8000>. Grafana: <http://127.0.0.1:3000>.
Keycloak usa `SOC_IDP_PORT` de `.env.docker`.
Esto inicia la plataforma y sus dependencias para consultar datos almacenados.

## Datos en vivo desde UTPL

Requiere red autorizada, credenciales en `.env`, CSV de fallback y línea base
preparados según [Operación](docs/operacion.md).

```powershell
python tools/setup_docker.py --source-env .env
docker compose --env-file .env.docker --profile live up -d --build web grafana worker
docker compose --env-file .env.docker logs -f --tail 20 worker
```

Compruebe ciclos completados con fuente `postgresql_live`. CSV significa demo
o fallback, no conexión institucional. La demora incluye el registro del log
en la universidad. `Ctrl+C` cierra el visor, no detiene la ingesta.

## Demostración sin red UTPL

Con el CSV autorizado configurado:

```powershell
docker compose --env-file .env.docker --profile demo run --rm demo
```

En Grafana seleccione la fuente histórica y sus fechas. Los comandos locales,
la muestra de 500 eventos del día y el análisis mensual están en la guía de operación.

## Uso y entrega

El analista revisa evidencia, investiga y cierra casos. El administrador también
gestiona usuarios y publica reglas. Grafana permite ver todos los servicios,
sus oscilaciones y el detalle individual.

La entrega local no equivale a producción certificada. Deben validarse HTTPS,
dominio, secretos, acceso de red, carga y operación institucional.
No entregue contraseñas, CSV ni bases reales dentro del paquete de código.

## Tres guías de entrega

| Documento | Contenido |
| --- | --- |
| [Funcionamiento](docs/funcionamiento.md) | Flujo, reglas, puntajes y mapa breve del código. |
| [Operación](docs/operacion.md) | Comandos, demo, datos en vivo, histórico y respaldos. |
| [Entrega](docs/entrega.md) | Docker para el ingeniero, seguridad y requisitos de producción. |
