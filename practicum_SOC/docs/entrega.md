# Entrega al ingeniero y seguridad

## Qué entregar

Repositorio privado o paquete de fuentes con código, configuración de ejemplo,
Dockerfile, Compose, pruebas y estas tres guías. La aplicación usa Python/FastAPI,
Jinja2 y JavaScript; Docker reúne PostgreSQL SOC, Keycloak y Grafana.

No incluya `.env` reales, claves, CSV institucionales, `analysis/`, respaldos,
volúmenes, `.venv/` ni sesiones. Los catálogos contienen referencias a servicios
institucionales: el destinatario debe estar autorizado.

El paquete de código no transfiere los casos ni las cuentas de la instalación.
Para eso se necesita una migración autorizada de los volúmenes y bases propias,
con custodia separada de secretos. Conserve la clave HMAC del histórico.

## Entregar una imagen Docker

Desde la raíz, sin necesidad de consultar UTPL:

```powershell
docker build --target production -t adfs-soc:local .
docker image save --output adfs-soc-image.tar adfs-soc:local
```

En el destino, con las fuentes y Compose disponibles:

```powershell
docker image load --input adfs-soc-image.tar
python tools/setup_docker.py
docker compose --env-file .env.docker up -d --no-build web grafana
```

El TAR contiene solo la imagen del SOC: no incluye datos ni las imágenes de
PostgreSQL, Keycloak y Grafana. Estas deben descargarse o transferirse aparte.
La arquitectura debe ser compatible con el equipo destino.
El primer arranque local se explica en [Operación](operacion.md).

## Antes de producción

El Compose entregado es local, ligado a `127.0.0.1`. El ingeniero debe validar:

- Dominio, HTTPS, proxy, restricciones de red y URLs/callbacks OIDC exactos.
- Variables de producción y hosts permitidos pasados explícitamente al contenedor.
  Cambiar solo `--env-file` no convierte el Compose local en producción.
- Secretos propios, cuentas individuales, roles y política institucional de MFA.
- Origen PostgreSQL de solo lectura y TLS según la política institucional.
- Respaldos y restauración probada; 30 días de retención como propuesta,
  no como purga automática implementada.
- Pruebas de carga con tráfico de clases y piloto con analistas.
- Umbrales, clasificación de servicios y canal definitivo aprobados por la Dirección.

Las pruebas automatizadas comprueban funciones; no certifican ausencia de
vulnerabilidades ni capacidad ilimitada.

## Controles y límites de seguridad

Resumen STRIDE conservado de la evaluación del proyecto:

| Riesgo | Control o condición |
| --- | --- |
| Suplantación | OIDC, sesiones y cuentas individuales; falta adaptar identidad institucional. |
| Alteración | Fuente de solo lectura y publicación controlada de reglas; proteger la base SOC. |
| Negación de acciones | Auditoría de casos y configuración; no es inmutable ante un administrador de base. |
| Exposición de datos | Pseudónimos y secretos fuera del repositorio; HTTPS y acceso restringido en producción. |
| Saturación | Límites de solicitudes, paginación y agregados; verificar con pruebas de carga. |
| Escalada de privilegios | Administrador y analista con permisos distintos; revisar roles al desplegar. |

El SOC no bloquea cuentas, no escribe en ADFS ni evita restricciones de red.
La pseudonimización no hace anónimos los patrones de uso. No active IA, reputación
u otros proveedores externos sin autorización y revisión del tratamiento de datos.
