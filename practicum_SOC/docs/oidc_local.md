# Sprint 2: acceso OIDC local

Los operadores del SOC NO son los usuarios presentes en los logs de ADFS.
Keycloak administra el acceso a esta plataforma, sin federación con UTPL.
Autenticarse aquí no crea eventos normalizados ni alertas de autenticación ADFS.

## Arranque

Desde la raíz del proyecto y con Docker Desktop en contenedores Linux:

```powershell
python tools/setup_docker.py
docker compose --env-file .env.docker config --quiet
docker compose --env-file .env.docker up -d --build web grafana
```

El primer arranque descarga Keycloak y puede tardar varios minutos.
Abra http://127.0.0.1:8000 exactamente, no localhost: OIDC valida la dirección.
La actualización añade secretos ausentes sin cambiar los que ya existían.
Nunca comparta .env.docker ni ejecute compose config sin --quiet para compartirlo.

| Usuario inicial | Función | Contraseña en .env.docker |
|---|---|---|
| soc-admin | Administrador SOC | SOC_BOOTSTRAP_ADMIN_PASSWORD |
| soc-analyst | Analista SOC | SOC_BOOTSTRAP_ANALYST_PASSWORD |
| identity-admin | Administración técnica de Keycloak | SOC_IDP_ADMIN_PASSWORD |

identity-admin no es un tercer rol de la aplicación. Administra el proveedor en
`http://127.0.0.1:<SOC_IDP_PORT>/admin` (realm master). En este equipo el puerto
configurado es 18080 porque 8080 pertenece al listener de Oracle. Para crear operadores seleccione realm
soc, cree el usuario, configure contraseña y asigne administrator o analyst.
No hay registro público. Sustituya las cuentas de demostración por cuentas
personales antes de entregar acceso a varias personas.

## Permisos

Ambos roles consultan casos, servicios y reportes y cambian estados de alertas.
Solo el administrador ve Usuarios y puede cambiar el rol o desactivar un
operador. La pantalla lista operadores que ya iniciaron sesión; las contraseñas
y la creación inicial se gestionan en Keycloak, no en el SOC.

En el primer acceso, un rol reconocido de Keycloak permite registrar al operador.
Después, el rol y la habilitación del SOC son autoritativos. Cambiar el rol en
Keycloak no sobreescribe un rol local ya registrado. Para revocar acceso
inmediatamente use Usuarios del SOC: elimina sus sesiones, incluso aunque el
proveedor conserve una sesión SSO. No se permite desactivar ni degradar al último
administrador habilitado. Las modificaciones quedan auditadas.

Cada cambio de estado de un caso registra el operador obtenido de la sesión;
el navegador no puede elegir el autor. El historial anterior conserva la
etiqueta Motor SOC cuando no existía información del operador.

## Sesiones y separación de datos

- Authorization Code con PKCE S256, state y nonce de un solo uso.
- ID token validado: firma RSA, emisor, audiencia, expiración y nonce.
- Sesión opaca: el servidor guarda su hash, no el token de sesión original.
- Duración absoluta 60 minutos, inactividad 15; ajustes en config/auth.json.
  Las consultas automáticas de cambios no prolongan la inactividad.
- Cookie HttpOnly y SameSite=Lax; Secure cuando SOC_PUBLIC_URL utiliza HTTPS.
- Escrituras protegidas con CSRF y comprobación de Origin.
- Dashboard, API, reportes y documentación API requieren sesión.
- /healthz solo publica disponibilidad; /health detallado requiere sesión.
- Se desactiva el access log de Uvicorn en Docker para evitar códigos OIDC en URLs.
- Keycloak guarda contraseñas en su PostgreSQL independiente (identity_data).
- platform_users, platform_sessions y platform_audit pertenecen al PostgreSQL SOC.
- Los logs institucionales y sus pseudónimos mantienen sus tablas y detector.

El cierre elimina la sesión local y dirige al cierre del proveedor; Keycloak
puede pedir confirmación. Una sesión local expirada puede volver a autenticarse
sin contraseña si el SSO de Keycloak sigue activo.

## Archivos principales

| Archivo | Responsabilidad |
|---|---|
| compose.yaml | Keycloak, su PostgreSQL y conexión OIDC de la web |
| deploy/keycloak/soc-realm.json | Realm, cliente, roles y cuentas iniciales |
| src/auth_config.py | URLs, política y configuración externa |
| src/oidc_client.py | Intercambio de código y validación criptográfica |
| src/auth_store.py | Sesiones, permisos, revocaciones y auditoría |
| src/auth_schema.py | Tablas separadas de identidad |
| src/auth_web.py | Protección de rutas, login, logout y gestión de usuarios |
| templates/users.html | Administración de operadores registrados |
| tests/test_auth.py | Pruebas sin UTPL ni proveedor externo |
| tools/smoke_containers.py | Prueba integral aislada con Keycloak real |

## Límites operativos

Esto es OIDC LOCAL, no federación con el ADFS de UTPL. Grafana mantiene su propio
login privado (admin y GRAFANA_ADMIN_PASSWORD); no tiene SSO con el SOC.
No se añaden editor de reglas, MFA ni políticas de retención en este sprint.
El registro de auditoría no es inmutable frente al administrador de la base.

Los puertos se ligan a 127.0.0.1. HTTP es solo para el piloto local; para otros
equipos se debe configurar dominio, HTTPS, emisor, callbacks, cookies y restricciones
de red. No basta con abrir el puerto. No publique Keycloak admin en Internet.

El realm se importa SOLO cuando no existe. Cambiar las contraseñas iniciales
en .env.docker no cambia usuarios ya creados. Rote contraseñas y secretos desde
Keycloak y coordine los valores del cliente SOC; no borre los volúmenes.

PowerShell conserva SQLite como destino por defecto, pero la web requiere OIDC.
Para conectarla al Keycloak local configure SOC_AUTH_MODE=oidc, SOC_PUBLIC_URL,
SOC_OIDC_ISSUER, SOC_OIDC_CLIENT_ID=soc-web y SOC_OIDC_CLIENT_SECRET iguales al
cliente Docker; deje SOC_OIDC_INTERNAL_ORIGIN vacío fuera del contenedor.
No ejecute dos webs en el mismo puerto. SOC_AUTH_MODE=disabled es una excepción
explícita exclusivamente loopback para la demo heredada, no para producción.

## Verificación

```powershell
python -m pytest -q
python -m ruff check src tools tests
python tools/smoke_containers.py
```

La prueba integral crea un proyecto soc-smoke aleatorio con claves y datos
ficticios, y elimina SOLO sus contenedores y volúmenes al finalizar. No usa
credenciales UTPL, no consulta su fuente y no borra volúmenes del proyecto real.

### Validación del Sprint 3

La prueba integral Docker ya pasó con Keycloak real, PostgreSQL, Grafana y un
navegador Edge: login de administrador y analista, permisos, revocación, cierre
de sesión y consulta de métricas. Utiliza un proyecto aislado con puertos libres.

El error anterior cookie_not_found procedía del cliente urllib: no reenviaba
cookies Secure sobre HTTP loopback. La nueva prueba utiliza Playwright y un
navegador real, manteniendo las protecciones del proveedor.

Para esta prueba de desarrollo se necesita Node.js, Playwright y Edge. No son
dependencias del servicio SOC ni se incluyen en su imagen Docker.
Preparación opcional del equipo que ejecuta pruebas:

```powershell
npm install --no-save --package-lock=false playwright
.\.venv\Scripts\python.exe tools/smoke_containers.py
```

Puede indicar SOC_SMOKE_NODE si node no está en PATH. Si utiliza Chrome en lugar
de Edge, configure SOC_BROWSER_CHANNEL=chrome para la prueba de navegador.
Las dependencias Python se instalan con requirements.txt como antes.
Consulte [los controles y límites del Sprint 3](sprint3_access_audit.md).
