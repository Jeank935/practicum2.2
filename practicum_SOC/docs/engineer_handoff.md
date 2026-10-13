# Entrega Docker al ingeniero

## Qué se entrega

Entregar el repositorio privado o el ZIP de fuentes preparado en `deliverables/`.
Incluye `Dockerfile`, `compose.yaml`, dependencias fijadas, código, configuración
sin secretos, plantillas, pruebas y provisionamiento de Keycloak/Grafana.

No entregar `.env`, `.env.docker`, `.env.production`, `.secrets/`, CSV, `analysis/`,
respaldos, `.venv/` ni volúmenes dentro del paquete de código. Los catálogos de
servicios contienen nombres y URLs institucionales necesarios para relacionar
servicios; esta entrega es para el ingeniero autorizado, no para publicación pública.

El ZIP no incluye las cuentas, sesiones ni casos de tu instalación actual.
Para migrarlos se necesita un respaldo autorizado de los PostgreSQL propios,
Grafana y el volumen de análisis, junto con custodia separada de sus claves.
Conservar la HMAC si se transfiere histórico: cambiarla cambia los pseudónimos.

## Prueba inicial en una máquina nueva

Requisitos: Docker Engine/Compose v2, contenedores Linux, Python 3 para generar
secretos y acceso permitido a los registros de imágenes/dependencias. Extraer el
ZIP y abrir una terminal en su raíz, donde están `compose.yaml` y `Dockerfile`.

```powershell
python tools/setup_docker.py
docker compose --env-file .env.docker config --quiet
docker compose --env-file .env.docker up -d --build web grafana
docker compose --env-file .env.docker ps
```

Estos comandos son igualmente válidos en una shell Linux con `python3` en lugar
de `python` si ese es el nombre instalado. `setup_docker.py` usa la biblioteca
estándar: no requiere instalar las dependencias de la aplicación en el host.

Web: `http://127.0.0.1:8000`; Grafana: `http://127.0.0.1:3000`; Keycloak:
`http://127.0.0.1:8080`. Cambiar puertos en `.env.docker` si están ocupados.
En un entorno NUEVO el realm crea `soc-admin` y `soc-analyst`; sus contraseñas
están en las variables `SOC_BOOTSTRAP_ADMIN_PASSWORD` y
`SOC_BOOTSTRAP_ANALYST_PASSWORD` del archivo privado generado. No son las
credenciales de tu instalación actual. Cambiar variables no restablece usuarios
ni contraseñas de una base ya inicializada.

Este arranque es un piloto LOCAL. No se debe compartir `127.0.0.1` con otros
usuarios como si fuese el servidor institucional.

## Habilitar la fuente institucional

1. Obtener del ingeniero la conexión de SOLO LECTURA, tabla/vista y columnas
   autorizadas. Configurarlas únicamente en `.env.docker`.
2. Mantener `SOC_STORAGE_*` apuntando al almacenamiento SOC propio; `SOC_DB_*`
   describe el origen institucional. Son dos bases diferentes.
3. Facilitar por un canal autorizado el CSV de fallback y configurar `SOC_CSV_PATH`.
   No está en el ZIP. El worker actual exige ese montaje de solo lectura.
4. Preparar la línea base del volumen `analysis` según
   [la guía Docker](container_deployment.md#fuente-institucional).
5. Acordar el checkpoint inicial para no recuperar todo el histórico por accidente.
   No borrar checkpoints ni volúmenes existentes para empezar una prueba.

Después, ejecutar UNA instancia del monitor:

```powershell
docker compose --env-file .env.docker --profile live up -d worker
docker compose --env-file .env.docker logs -f --tail 20 worker
```

Un ciclo completado debe indicar `postgresql_live`. Cero eventos puede significar
que no hay registros nuevos. `csv_demo` es fallback, no conectividad con la UTPL.
Ctrl+C cierra el visor de logs; para detener el monitor usar `stop worker`.

## Paso de piloto a producción

El ingeniero debe adaptar el despliegue a su infraestructura antes de exponerlo:

- Dominio, HTTPS y proxy con acceso directo al puerto restringido.
- URLs HTTPS de web, Keycloak y Grafana; redirect URIs exactas y cookies seguras.
- Override de Compose o despliegue equivalente que pase explícitamente
  `SOC_ENV=production`, `SOC_ALLOWED_HOSTS` y las variables de
  `.env.production.example` al contenedor web. El Compose local conserva HTTP;
  cambiar solo `--env-file` NO activa el perfil de producción.
- Secretos propios, usuarios individuales, permisos mínimos, revisión de MFA y
  retirada de credenciales compartidas de demostración.
- Origen institucional de solo lectura; TLS validado cuando lo exija su política.
- Respaldos, restauración probada y retención aprobada. Se propone 30 días como
  punto de partida, sin activar borrado automático.
- Revisión de imágenes, pruebas de carga, fallos, OIDC, CSRF, SSE y piloto.

La [guía de producción](production_readiness.md#activación-de-producción-pasos-todavía-necesarios)
detalla estos pendientes. La etapa Docker llamada `production` no sustituye la
configuración segura del entorno. No se declara producción certificada.

## Si solicita un archivo de imagen `.tar`

Además del ZIP, se puede construir y exportar la imagen Python sin levantar
servicios ni consultar la fuente:

```powershell
docker build --target production -t adfs-soc:local -t adfs-soc:entrega-20261013 .
docker image save --output adfs-soc-image-20261013.tar adfs-soc:local adfs-soc:entrega-20261013
```

En la máquina destino:

```powershell
docker image load --input adfs-soc-image-20261013.tar
python tools/setup_docker.py
docker compose --env-file .env.docker up -d --no-build web grafana
```

El `.tar` contiene la imagen de aplicación, no los volúmenes ni las imágenes
PostgreSQL, Keycloak o Grafana. Estas últimas se obtienen del registro o se
transfieren separadamente si la institución exige despliegue sin Internet.
La arquitectura de la imagen debe coincidir con el host de destino.
No usar `docker export` para transferir la instalación completa.
Docker documenta el intercambio mediante
[image save](https://docs.docker.com/reference/cli/docker/image/save/) y la
[interpolación de variables Compose](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).

## Verificar y mantener

En un entorno de desarrollo aislado:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests tools
.\.venv\Scripts\python.exe -m ruff format --check src tests tools
```

Las integraciones PostgreSQL omitidas requieren una base sintética de prueba.
No apuntar `SOC_TEST_STORAGE_DSN` al origen ni al almacenamiento con casos reales.
Nunca ejecutar `docker compose down -v` sobre la instalación que se quiere conservar.

Para actualizar solo la web del piloto, sin reiniciar el monitor:

```powershell
docker compose --env-file .env.docker up -d --build --no-deps web
```
