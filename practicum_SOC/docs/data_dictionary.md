# Diccionario de datos ADFS

Este documento describe el CSV fuente y su transformación al esquema analítico.
El archivo fuente no contiene una fila de encabezados; el orden fue confirmado
por el propietario de los datos.

## Columnas de origen

| Posición | Columna | Uso propuesto | Observación del perfil |
|---:|---|---|---|
| 1 | `id` | Identificador de fila | 100.000 valores únicos. |
| 2 | `event_name` | Tipo descriptivo del evento | Tres valores: éxito, error de credenciales y bloqueo externo. |
| 3 | `log_source` | Servidor que produjo el evento | Dos servidores ADFS. |
| 4 | `event_count` | Peso o cantidad del registro | Vale 1 en todas las filas actuales. |
| 5 | `event_time` | Tiempo procesado del evento | Campo principal; siete valores de 1970 deben marcarse como inválidos. |
| 6 | `created_at` | Tiempo de creación en la integración | No debe sustituir automáticamente al tiempo del evento. |
| 7 | `updated_at` | Tiempo de actualización | Vacío en 98,78 % de las filas. |
| 8 | `event_id` | Identificador técnico del evento | Único en la muestra. |
| 9 | `low_level_category` | Clasificación de bajo nivel | Éxito, fallo o actividad de monitoreo. |
| 10 | `source_ip` | IP del servidor fuente | Solo contiene las dos IP privadas de ADFS; no es la IP del usuario. |
| 11 | `destination_ip` | IP del servidor destino | Coincide con los servidores ADFS. |
| 12 | `username` | Cuenta técnica de integración | Es constante y no identifica al usuario autenticado. |
| 13 | `custom_user_id` | Usuario autenticado | Campo útil para análisis; debe pseudonimizarse. |
| 14 | `custom_ip_address` | IP del cliente | Campo útil para detección; 0,78 % está vacío. |
| 15 | `custom_relying_party` | Aplicación o servicio solicitado | 37 valores; `N/A` se interpreta como ausencia. |
| 16 | `custom_message` | Mensaje complementario | Vacío en 99,62 %; no es adecuado como campo principal. |
| 17 | `event_type_id` | ID del tipo de evento ADFS | 1200, 1203 o 1210; dos filas contradicen `event_name`. |
| 18 | `event_time_origen` | Tiempo original cuando está disponible | Solo aparece en 368 filas y precede a `event_time` entre 1 y 90 segundos. |

## Clasificación de eventos

| `event_name` | ID esperado | Clase normalizada |
|---|---:|---|
| `Application Token Success` | 1200 | `success` |
| `Fresh Credential Validation Error` | 1203 | `failure` |
| `Extranet Lockout Audit` | 1210 | `lockout` |

La clase se deriva del nombre descriptivo. Si el ID no coincide con el valor
esperado, el evento se conserva y recibe la bandera `EVENT_TYPE_MISMATCH`.

## Esquema normalizado

| Campo | Descripción |
|---|---|
| `record_id` | ID de la fila fuente. |
| `source_event_id` | ID técnico único del evento. |
| `event_type_id` | ID ADFS informado. |
| `event_name` | Nombre original del evento. |
| `event_class` | `success`, `failure`, `lockout` u `other`. |
| `event_time_utc` | `event_time_origen` válido; en su ausencia, `event_time` válido. |
| `event_time_source` | Indica qué columna proporcionó el tiempo normalizado. |
| `created_at_utc` | Tiempo de creación en la integración. |
| `updated_at_utc` | Tiempo de actualización, si existe. |
| `log_source_key` | HMAC del origen lógico; no publica nombre ni IP interna. |
| `user_key` | HMAC del usuario canónico; no expone su identidad. |
| `user_id_format` | Formato observado: dominio, correo u otro. |
| `client_ip_key` | HMAC de la IP del cliente para correlación sin revelarla. |
| `client_ip_version` | Versión 4 o 6. |
| `client_ip_scope` | `private` o `public`. |
| `relying_party` | Aplicación o servicio solicitado. |
| `event_count` | Peso del registro. |
| `quality_flags` | Problemas de calidad separados por punto y coma. |

## Normalización del usuario

Para relacionar el mismo usuario entre formatos distintos se transforma a
minúsculas y se retira `DOMINIO\\` o el dominio del correo. El valor canónico no
se guarda: se protege con HMAC-SHA256 usando una clave externa al repositorio.

## Decisiones de calidad

- No se corrige una fecha de 1970 usando `created_at`, porque `created_at` puede
  representar una carga o actualización posterior, no la autenticación.
- Los eventos problemáticos se conservan con banderas para auditoría.
- `analysis/inconsistent_events.csv` separa una copia pseudonimizada de cada
  fila con banderas; los duplicados no se incorporan por segunda vez al archivo
  normalizado principal.
- Las reglas SOC usarán `custom_ip_address`, no `source_ip`.
- La clave de pseudonimización debe ser estable y administrada fuera del código.
