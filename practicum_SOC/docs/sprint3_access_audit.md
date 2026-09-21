# Sprint 3 — Acceso privado y auditoría

Alcance acordado: dos roles (administrador y analista), OIDC local con Keycloak
y Grafana con su acceso independiente. Los usuarios del SOC son operadores de
la plataforma y no se mezclan con los sujetos de los logs ADFS.

## Uso

1. Iniciar sesión desde http://127.0.0.1:8000.
2. El analista abre un caso: se registra case_viewed con usuario, caso y fecha.
3. Al investigar, resolver o marcar falso positivo se guarda el autor y el
   cambio de estado. Ver una ficha no cambia su estado automáticamente.
4. El administrador consulta Usuarios de la plataforma: puede gestionar el
   acceso y desplegar el detalle de auditoría con los valores anteriores/nuevos.
5. Auditoría de configuración permite revisar huellas de archivos desplegados.

Grafana continúa en http://127.0.0.1:3000. El Keycloak de este equipo utiliza
http://127.0.0.1:18080. Los puertos de una copia del proyecto los define .env.docker.

## Permisos y protección

| Operación | Administrador | Analista |
|---|---|---|
| Dashboards, servicios, reportes y casos | Sí | Sí |
| Investigar y cerrar casos | Sí | Sí |
| Cambiar roles y habilitar/deshabilitar operadores | Sí | No |
| Consultar auditoría administrativa/configuración | Sí | No |
| Editar reglas desde la interfaz | Pendiente del Sprint 6 | No |

Las rutas de datos, documentación API y exportación requieren sesión. Login,
callback, pantalla de sesión cerrada, archivos estáticos y /healthz son públicos
por su función; /health detallado es privado. El modo heredado disabled solo es
admisible con loopback explícito; el Compose del SOC utiliza siempre oidc.

Las escrituras requieren CSRF y validan Origin cuando está presente. Se rechazan
tokens con firma, emisor, audiencia, nonce o expiración incorrectos. Las cookies
son HttpOnly y SameSite=Lax; Secure se activa con HTTPS. El piloto local utiliza
HTTP sobre 127.0.0.1; el despliegue en red requiere dominio y HTTPS.

La sesión dura un máximo de 60 minutos y caduca tras 15 minutos sin actividad.
El sondeo automático del dashboard/servicios no renueva la inactividad; al
detectar una sesión caducada el navegador vuelve al acceso. Keycloak conserva
su propia sesión SSO, por lo que la reautenticación puede no pedir contraseña
si esa sesión todavía está vigente.

Cambiar el acceso de un operador revoca sus sesiones. Los cambios administrativos
revalidan el rol actual dentro de la transacción y preservan un administrador
activo. Las comprobaciones de autorización ocurren en el servidor.

## Límites de solicitudes

Todos los valores residen en config/auth.json:

| Operación | Solicitudes por 60 segundos | Identidad de agrupación |
|---|---:|---|
| Iniciar login | 15 | IP de conexión |
| Callback OIDC | 30 | IP de conexión |
| Consultar fichas de casos | 120 | Operador |
| Cambiar estados | 30 | Operador |
| Gestión de usuarios | 20 | Operador |
| Auditoría de configuración | 10 | Operador |
| Descargar reportes | 10 | Operador |
| Ejecutar demo desde HTTP | 1 | Operador |
| Cerrar sesión | 10 | Operador |

El contador se guarda en platform_rate_limits. Se actualiza atómicamente y
persiste entre reinicios; también comparte límites entre sesiones del mismo
usuario y procesos web. Responde HTTP 429 con Retry-After al agotar la ventana.
Los contadores vencidos se limpian al consumir un nuevo límite.

Se usa una ventana fija, no deslizante: puede admitir hasta dos cuotas en los
extremos de dos ventanas consecutivas. La base guarda un hash del identificador
de agrupación. No se confía directamente en X-Forwarded-For; si se añade un proxy
se deberá configurar explícitamente qué proxy puede aportar la IP cliente.
En Docker/NAT varios navegadores pueden compartir IP para el login. Estos límites
no sustituyen controles de tráfico a nivel de proxy ni pruebas de carga.

## Auditoría de configuración

Se observan auth.json, detection_rules.json y operational.json al arrancar la
web y al abrir la pantalla administrativa. Se compara el SHA-256 del JSON
canonicalizado: cambiar solo espacios o el orden de claves no crea un cambio.

El registro conserva nombre del archivo, huella anterior/nueva y fecha de
observación; no copia valores, secretos, IP ni cuentas del archivo.
Los cambios fuera de la aplicación se atribuyen a autor externo desconocido,
con el observador del sistema identificado. La fecha es la de detección, no
necesariamente la de edición. Cambios transitorios entre observaciones pueden
no verse. La pantalla refleja los archivos de esta instancia web, no certifica
la configuración de un worker de otro despliegue.

El historial no es inmutable ante un administrador de la base. El versionado,
borradores, justificación y autor humano de publicaciones desde el editor serán
parte del Sprint 6. No se añadió un editor anticipadamente.

## Archivos

| Archivo | Función |
|---|---|
| src/auth_web.py | Sesión, autorización, CSRF y aplicación de límites HTTP |
| src/auth_store.py | Operadores, sesiones, revocación y auditoría |
| src/rate_limits.py | Contadores atómicos persistentes |
| src/configuration_audit.py | Observación de huellas de configuración |
| src/auth_schema.py | Tablas e índices nuevos, sin borrar datos existentes |
| src/dashboard_service.py | Registro del operador que consulta cada ficha |
| src/alert_store.py | Historial de cambios y cierre de casos |
| templates/users.html | Administración y detalle de actividad |
| templates/configuration.html | Consulta de huellas y cambios detectados |
| tools/verify_oidc_browser.cjs | Prueba del login con navegador real |
| tools/smoke_containers.py | Despliegue de pruebas aislado y verificación integral |

## Actualizar y probar

```powershell
docker compose --env-file .env.docker up -d --build web grafana
.\.venv\Scripts\python.exe -m ruff check src tools tests
.\.venv\Scripts\python.exe -m pytest -q
```

La inicialización agrega tablas e índices de forma idempotente. No elimina
casos, checkpoints ni usuarios. No ejecutar down -v sobre el proyecto de trabajo.

Sin SOC_TEST_STORAGE_DSN se omiten las pruebas de PostgreSQL explícitamente;
se verificaron también contra una instancia local desechable. La prueba Docker
usa cuentas y datos sintéticos y limpia solo su proyecto soc-smoke aleatorio.
Ver docs/oidc_local.md para preparar Node/Playwright en el equipo de pruebas.

Se verifican acceso real de ambos roles, revocación, cierre, permisos, autoría
de consulta y estados, CSRF, expiración, cookies HTTPS, auditoría de cambios,
ausencia de secretos en observaciones y límites bajo solicitudes concurrentes.
El piloto multiusuario UTPL, HTTPS institucional y la carga de temporada lectiva
continúan pendientes de su infraestructura; no son pruebas realizadas aquí.
