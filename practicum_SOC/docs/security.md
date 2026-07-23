# Seguridad y privacidad

## Controles

- CSV original en solo lectura e ignorado por Git.
- Usuario, IP cliente y origen lógico pseudonimizados con HMAC-SHA256 y clave externa.
- Rechazos sanitizados: no conservan valores crudos del usuario o IP.
- SQLite separado de PostgreSQL.
- PostgreSQL incremental, parametrizado y `READ ONLY`.
- Credenciales y clave solo en entorno o `.secrets/`, ambos ignorados.
- Interfaz y reporte muestran exclusivamente pseudónimos.
- `soc_inbox` no transmite información fuera del equipo local.
- Pruebas sintéticas y mocks sin dependencia de la red UTPL.

Los pseudónimos, servicios y marcas de tiempo siguen siendo datos operativos; por eso todo `analysis/` permanece fuera de control de versiones. La clave HMAC debe ser estable, restringida y respaldada mediante un mecanismo institucional autorizado.

## Acciones que el sistema no realiza

- No bloquea cuentas ni modifica ADFS.
- No escribe en PostgreSQL.
- No envía correos, Teams o webhooks.
- No consulta reputación o geolocalización externa.
- No inventa perfiles de estudiante/docente ni rangos de red.
- No presenta una anomalía como ataque confirmado.

## Antes de producción

La Dirección debe validar vista y permisos, zona horaria, retención de SQLite, rangos de red, umbrales, tratamiento de falsos positivos y canal definitivo de notificación.
