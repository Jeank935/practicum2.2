# Preparación para producción y revisión de seguridad

Revisión: 4 de octubre de 2026. La aplicación conserva el flujo actual, las reglas,
la pseudonimización, los datos y los puntos de entrada. Esta revisión **no es un
despliegue institucional ni una certificación de ausencia de vulnerabilidades**.

## Qué cambió

- `core/security.py`: valida el perfil `SOC_ENV=production` antes de abrir la base.
  Exige OIDC, HTTPS, dominio explícito, PostgreSQL propio y secretos de sesión
  adecuados. Rechaza configuraciones inseguras en lugar de permitir acceso abierto.
- `api/security.py`: limita consulta y cuerpo HTTP, valida longitud, rechaza
  cabeceras ambiguas, impone tiempo de recepción y añade cabeceras de seguridad.
  Los valores se administran en `config/security.json`, no en las rutas.
- `main.py`: conserva la composición actual; en producción restringe hosts y
  desactiva Swagger, ReDoc y la exposición de OpenAPI. `/healthz` sigue disponible
  para la sonda local de Docker; no revela casos ni configuración.
- `api/routes/monitoring.py`: no permite ejecutar la demo desde producción;
  en modo local esa operación requiere administrador.
- `api/routes/auth.py` y `schemas/auth.py`: límites en el callback, registro de
  rechazos sin tokens ni credenciales y rechazo de campos no definidos al editar
  permisos. El autor de cambios de casos sigue proviniendo de la sesión, nunca
  de un campo enviado por el navegador.
- `core/rate_limits.py`: también limita consultas de resumen y sondeos por usuario.
  Se mantienen los límites configurables en `config/auth.json`.
- `repositories/auth.py`: no escribe `last_seen` en cada petición. Lo actualiza
  como máximo una vez cada 15 segundos de actividad; las consultas automáticas
  no mantienen la sesión abierta. Se conservan expiración absoluta y revocación.
  La expiración por inactividad tiene esa granularidad de hasta 15 segundos.
- `repositories/postgres.py`: admite una CA mediante `SOC_STORAGE_SSLROOTCERT`
  para validar TLS cuando el almacenamiento propio esté en otro servidor.
- `requirements-runtime.txt` y `constraints-runtime.txt`: separan y fijan
  dependencias de ejecución. `requirements.txt` conserva la instalación de desarrollo.
- `Dockerfile`: separa imagen de ejecución y etapa `backend-tests`. La imagen
  final no incorpora pytest, Ruff, Bandit, documentación, CSV ni archivos `.env`.
- `.env.production.example`: referencia sin secretos reales; los campos vacíos
  deben completarse y no sirven para iniciar producción.
- `tests/test_production_security.py`: regresión de transporte, hosts, configuración,
  límites, sesiones, asignación de permisos e inyección SQL mediante filtros.

Las rutas anteriores son relativas al proyecto; los módulos indicados viven en
`src/practicum_soc/`. No se introdujeron nuevas reglas de detección ni se cambiaron
umbrales para mejorar artificialmente los resultados.

## Limpieza conservadora

En la limpieza de entrega del 13 de octubre se retiraron la presentación, el plan
inicial, la validación Docker antigua, dos mapas archivados y las notas de diseño
de Grafana. Se respaldó `docs/` localmente en `backups/` antes de retirarlos;
ese respaldo no forma parte del paquete de entrega. Las referencias vigentes son
`docs/project_guide.md`, `docs/backend_refactor.md` y `docs/README.md`.

Se mantienen pruebas, scripts PowerShell, lanzadores `src/*.py`,
respaldos y archivos de análisis. Los lanzadores siguen siendo necesarios para
Docker y los comandos existentes. No se eliminó el CSV ni ningún caso almacenado.
Las herramientas de auditoría se instalaron fuera del proyecto y de la imagen.

## OWASP Top 10: cobertura y pendientes

La referencia es [OWASP Top 10:2025](https://owasp.org/Top10/2025/), un catálogo de
riesgos, no una lista que certifique por sí sola la seguridad. Para la aceptación
institucional debe definirse un alcance de verificación basado en
[OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/).
No se declara conformidad completa con ASVS.

| Riesgo | Controles existentes o reforzados | Pendiente antes de exposición institucional |
| --- | --- | --- |
| A01 Control de acceso roto | OIDC, roles en backend, CSRF, auditoría de acciones y autor obtenido de sesión; sin demo en producción | Validar permisos reales de analistas, administradores y Grafana; probar acceso horizontal con casos autorizados |
| A02 Configuración insegura | Perfil que rechaza HTTP y hosts no admitidos; documentación API privada; usuario de contenedor no root y privilegios reducidos ya presentes | Dominio, proxy, certificados, secretos de despliegue y endurecimiento de Keycloak/Grafana |
| A03 Cadena de suministro | Versiones fijadas, separación de herramientas y auditoría de dependencias; imágenes Keycloak/Grafana ya fijadas por digest | Construir y escanear las imágenes finales, revisar PostgreSQL y la imagen base, actualizar periódicamente |
| A04 Fallos criptográficos | HMAC con clave externa; OIDC firmado; cookies Secure al usar HTTPS; TLS validado para almacenamiento remoto | Custodia de claves, CA, rotación de credenciales y cifrado de volúmenes/respaldos según infraestructura |
| A05 Inyección | Valores SQL parametrizados, identificadores de fuente validados y parámetros de reglas sin código/SQL; escape de Jinja2 y CSP | Revisar los avisos B608 descritos abajo y ejecutar pruebas dinámicas autorizadas en staging |
| A06 Diseño inseguro | Fuente institucional de solo lectura, almacenamiento separado, reglas versionadas, publicación previa a activación y rollback | Aprobación de umbrales, perfiles, servicios sensibles y piloto; sin respuestas automáticas |
| A07 Fallos de autenticación | Validación OIDC, state/nonce/PKCE, sesiones revocables y límites en login/callback | MFA y política de contraseñas en el proveedor; ciclo de altas, bajas y recuperación; cuentas individuales |
| A08 Integridad de software/datos | Configuración validada, historial de versiones, checkpoints y deduplicación; no aceptar SQL ni código del usuario | Proteger repositorio, pipeline, imágenes y respaldos; acordar revisión y aprobación de cambios |
| A09 Registro/alertamiento de seguridad | Auditoría persistente de casos y configuración; eventos de rechazo sin secretos; métricas de operación | Alertar sobre fallos repetidos de acceso y caídas, acordar responsables/canal, exportación protegida y retención |
| A10 Condiciones excepcionales | Errores HTTP genéricos, límites de tamaño/tiempo, manejo explícito de fuente no disponible y no evasión de red | Pruebas de caída, disco lleno, restauración, concurrencia, proxy y recuperación con PostgreSQL |

La CSP de la aplicación no permite scripts externos ni inline. Mantiene `style-src 'unsafe-inline'`
por las barras de servicios actuales. No se usa esto como prueba de seguridad
absoluta: una política de estilos más estricta requeriría adaptar ese componente.
En modo local se exceptúan únicamente `/docs` y `/redoc` de la CSP para conservar
sus recursos externos anteriores, sin alterar autenticación ni las demás cabeceras.
En producción esas páginas no existen; no se flexibiliza su política para habilitarlas.

### Revisión STRIDE resumida

- Suplantación: OIDC y sesiones; validar MFA y administración del proveedor.
- Manipulación: parámetros validados, SQL parametrizado y versionado de reglas.
- Repudio: cambios y acciones asociados al usuario; proteger la auditoría almacenada.
- Divulgación: pseudónimos, respuestas sin secretos, HTTPS y mínimo privilegio.
- Denegación de servicio: límites, paginación y cachés; pendiente prueba de carga real.
- Elevación de privilegios: roles comprobados en backend; pendiente validar permisos del despliegue.

## Resultados verificados

Los resultados numéricos de esta sección corresponden a la revisión del
4 de octubre; no son un contador de pruebas de la versión actual. La limpieza
de documentación no constituye una nueva auditoría de dependencias ni imágenes.

- Suite completa: **196 pasan y 17 se omiten**. Las omitidas requieren PostgreSQL
  local disponible; no se sustituyen por pruebas contra la universidad.
- Ruff: análisis y formato correctos, 132 archivos revisados por el formateador.
- `pip check`: sin dependencias incompatibles.
- Auditoría de dependencias instalada: **sin vulnerabilidades conocidas detectadas**
  después de actualizar `httpx2`/`httpcore2` a 2.13.1, PyJWT a 2.15.0 y pip a 26.2.1.
  Es un resultado puntual, no cubre vulnerabilidades desconocidas ni imágenes/OS.
- Bandit: **22 avisos medios B608, ninguno alto**. Se revisaron las construcciones
  de consultas en repositorios de alertas, navegación, auditoría, previews e histórico,
  migraciones y fuentes. Usan parámetros para valores y fragmentos constantes o
  identificadores restringidos; no se confirmó inyección en esos puntos. No se
  silenciaron indiscriminadamente. Una prueba comprueba que un filtro SQL hostil
  no devuelve casos ni elimina tablas.
- Docker Desktop estaba apagado. El intento de construcción no pudo conectar con
  el motor: **la nueva imagen y las 17 pruebas PostgreSQL están pendientes**.

El auditado de dependencias consultó paquetes/versiones en fuentes públicas. No se
enviaron logs, código de la aplicación, credenciales ni datos de UTPL.

### Rendimiento: medición sintética, no capacidad institucional

TestClient, SQLite aislado, 10 000 eventos, 5 001 casos y 100 servicios;
tres calentamientos y 20 solicitudes por ruta, sin autenticación real ni concurrencia.

| Ruta | Mediana antes/después (ms) | p95 antes/después (ms) |
| --- | --- | --- |
| `/` | 27.35 / 20.86 | 32.23 / 36.89 |
| `/alerts` | 19.11 / 15.10 | 22.18 / 16.62 |
| `/services` | 12.67 / 10.81 | 13.41 / 12.39 |
| `/api/v1/alerts` | 9.60 / 9.96 | 10.35 / 12.22 |
| `/api/v1/services` | 9.62 / 9.18 | 10.96 / 11.26 |
| `/api/dashboard-version` | 8.29 / 7.11 | 9.31 / 8.43 |
| `/api/services-version` | 8.46 / 7.01 | 8.98 / 8.07 |
| `/api/v1/dashboard/snapshot` | 26.76 / 20.51 | 31.80 / 21.72 |

Hay variación entre solicitudes y algunas medidas empeoran: no se afirma una mejora
universal. El número de consultas por ruta se mantuvo entre 2 y 5. Una prueba
específica confirma que 100 lecturas seguidas de una sesión no generan 100 escrituras
de actividad; después del intervalo se realiza una actualización. No se cambiaron
índices ni parámetros del PostgreSQL institucional.

## Cómo comprobarlo sin tocar los datos institucionales

Desde PowerShell, en la carpeta real del proyecto:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check src tests tools
.\.venv\Scripts\python.exe -m ruff format --check src tests tools
.\.venv\Scripts\python.exe -m pytest -q
```

En un entorno de auditoría separado, instalar `requirements-security.txt` y ejecutar
Bandit sobre `src` y pip-audit sobre las dependencias de ejecución. Estas herramientas
no se instalan en la imagen del SOC. Examinar los resultados, no solo el código de salida.

Cuando Docker Desktop esté iniciado y se haya acordado la ventana de prueba:

```powershell
docker build --target production -t adfs-soc:production-review .
docker build --target backend-tests -t adfs-soc:backend-tests .
```

La construcción no activa el worker ni consulta la fuente. Las pruebas PostgreSQL
deben ejecutarse en una base de prueba separada, nunca en la institucional ni sobre
la base con casos reales. Consultar las instrucciones del entorno de pruebas actual.

## Activación de producción: pasos todavía necesarios

1. Confirmar dominio, acceso permitido y quién operará respaldos, monitorización y
   respuesta a incidentes. No se modificó el piloto local para simular estas decisiones.
2. Copiar `.env.production.example` a un archivo privado, completar secretos y
   configuración. No reutilizar las contraseñas compartidas durante demostraciones;
   rotarlas de forma coordinada. **No rotar sin plan la clave HMAC**: cambia pseudónimos
   y afecta correlación con el histórico.
3. Configurar HTTPS y certificados válidos en el proxy y proveedor OIDC. Registrar
   solo redirect URIs exactas. El `compose.yaml` actual conserva Keycloak local HTTP
   para no romper la demostración: no es una configuración pública de producción.
4. Pasar explícitamente las variables del perfil al contenedor web, mediante una
   configuración de despliegue/override revisada. `docker compose --env-file ...`
   por sí solo sustituye variables del YAML; **no inyecta todas las variables al
   contenedor**. `SOC_ENV=production` debe estar en `services.web.environment` o
   en su `env_file`. Las URLs HTTP del Compose local también deben sustituirse.
5. La etapa Docker `production` elimina herramientas, pero no activa por sí misma
   el perfil seguro. No llamar «producción» a un contenedor sin `SOC_ENV=production`.
6. Configurar Uvicorn para confiar únicamente en la IP del proxy que termina TLS,
   usando `--proxy-headers --forwarded-allow-ips=<IP_del_proxy>`, nunca `*` por
   comodidad. Bloquear acceso directo al puerto. El proxy debe limitar conexiones,
   tamaño, tiempos y login; la limitación por usuario de la aplicación no sustituye
   protección contra tráfico anónimo. SSE requiere no almacenar respuestas en buffer.
7. Mantener la base propia aislada y sus usuarios separados: aplicación sin superusuario,
   analítica en solo lectura y credenciales de inicialización fuera del runtime normal.
   Si el servidor está separado, usar `verify-full`, CA de confianza montada en solo
   lectura y permisos de red mínimos. La fuente institucional sigue en solo lectura.
8. Configurar HTTPS, cookies seguras, acceso individual y roles de Grafana; revisar
   Keycloak y sus privilegios administrativos. No exponer interfaces administrativas
   sin restricciones. Escanear imágenes y fijar versiones/digests aprobados.
9. Acordar retención inicial de 30 días, respaldos cifrados y restauración a una base
   nueva de prueba. La retención no autoriza borrar datos existentes sin validación.
10. Repetir todas las pruebas con PostgreSQL, probar HTTPS/OIDC/CSRF/SSE reales,
    carga concurrente, fallos y restauración. Hacer un piloto con analistas y aprobación
    institucional antes de abrir el servicio al personal.

La revisión aporta controles comprobables y un modo de arranque más estricto. El
paso siguiente es verificar el despliegue concreto; ninguna modificación de código
puede garantizar por sí sola que una infraestructura aún no definida esté libre de riesgos.
