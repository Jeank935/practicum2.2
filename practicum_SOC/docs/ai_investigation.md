# Investigación asistida de alertas

Esta función es **solo backend**: no añade botones a la bandeja, no modifica
Grafana y no sustituye las reglas. El analista solicita una investigación de una
alerta existente; Python recopila los hechos y la IA los explica en español.
Nunca cambia severidades, cierra casos, bloquea cuentas ni confirma incidentes.

## Flujo y archivos

| Archivo, relativo a la raíz del proyecto | Responsabilidad |
| --- | --- |
| `src/practicum_soc/api/routes/investigation.py` | Solicitar un trabajo y consultar su estado/resultado. |
| `src/practicum_soc/services/investigation.py` | Permisos, coordinación, límites, validación y auditoría. |
| `src/practicum_soc/services/investigation_context.py` | Antecedentes del usuario/IP, conteos y comparación con la línea base. |
| `src/practicum_soc/repositories/investigation.py` | Consultas parametrizadas y cola persistente. |
| `src/practicum_soc/repositories/migrations/investigation.py` | Tablas e índices nuevos en la base propia del SOC. |
| `src/practicum_soc/core/private_ip.py` | Captura opcional de IP cliente y cifrado de IP/resultados. |
| `src/practicum_soc/core/investigation_config.py` | Validación de parámetros y disponibilidad. |
| `src/practicum_soc/integrations/ai_explanation.py` | Cliente HTTP directo de OpenAI Responses, sin herramientas ni MCP. |
| `src/practicum_soc/integrations/ip_reputation.py` | Consulta opcional a AbuseIPDB, solo para IP públicas. |
| `src/practicum_soc/integrations/investigation_http.py` | Tiempo/límite de respuesta y rechazo de redirecciones. |
| `src/practicum_soc/schemas/investigation.py` | Contratos de solicitud, estado, explicación y resultado. |
| `src/practicum_soc/cli/investigation.py`, `src/investigate_alerts.py` | Worker y entrada delgada para PowerShell. |
| `config/investigation.json` | Ventanas, límites, reutilización y tarifas opcionales. |
| `tests/test_investigation.py`, `tests/test_postgres_store.py` | Pruebas simuladas y contrato PostgreSQL local opcional. |

La ruta guarda un trabajo y devuelve su identificador **sin llamar a la IA**.
El worker lee la cola. Las conexiones/transacciones de datos se cierran antes
de consultar proveedores externos. La IP, los conteos, las fechas y la
reputación son campos del backend; no se extraen del texto generado.

Los eventos usados se limitan a la misma fuente de la alerta. Se priorizan sus
IDs de evidencia y se añaden eventos del usuario y de las IP asociadas.
Los conteos ponderan `event_count`; los éxitos posteriores y las otras cuentas
listadas corresponden a la muestra limitada, no necesariamente a toda la ventana.
La línea base solo se compara si el entrenamiento es anterior al día de la
alerta. Sin historial suficiente no se afirma que una IP sea nueva.

## Configuración

La función está deshabilitada inicialmente. Complete las siguientes variables
en **`.env` para PowerShell** o **`.env.docker` para Compose**, sin reemplazar
la configuración existente de almacenamiento y autenticación:

```dotenv
SOC_AI_ENABLED=true
SOC_AI_PROVIDER=openai
SOC_AI_MODEL=
OPENAI_API_KEY=
SOC_INVESTIGATION_IP_KEY=
SOC_INVESTIGATION_CAPTURE_IP=false
SOC_IP_REPUTATION_ENABLED=false
ABUSEIPDB_API_KEY=
```

- `SOC_AI_MODEL`: nombre de un modelo disponible en su cuenta que admita
  Responses y Structured Outputs. No se impone un modelo ni una tarifa.
- `OPENAI_API_KEY`: clave propia; no se incluye en Git ni en resultados.
- `SOC_INVESTIGATION_IP_KEY`: clave Fernet **distinta** de la clave HMAC.
  Se necesita también si no hay IP original, porque cifra el resultado.
  Debe ser la misma en web, monitor/histórico y worker de investigación.
- `SOC_INVESTIGATION_CAPTURE_IP=true`: conserva la IP original de los
  **eventos nuevos** ingresados por el monitor o el análisis histórico.
  Con `false` se mantiene la ingesta anterior, sin esa copia.
- Reputación opcional: `SOC_IP_REPUTATION_ENABLED=true` y
  `ABUSEIPDB_API_KEY`. Si falta la clave o falla el servicio, la investigación
  continúa y deja constancia de la información no disponible.

Genere la clave de investigación en su propio terminal y guárdela en el archivo
de entorno (no publique la salida):

```powershell
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

No cambie esa clave sin un procedimiento de migración: los resultados y las IP
guardadas con otra clave no podrán descifrarse. Inclúyala en el respaldo seguro,
separada del respaldo de datos.

Los parámetros están en `config/investigation.json`:

| Parámetro | Valor inicial |
| --- | --- |
| Ventana antes / después de la alerta | 60 / 15 minutos |
| Eventos detallados / entidades IP | 100 / 5 |
| Contexto máximo / respuesta HTTP máxima | 48 000 / 131 072 bytes |
| Salida máxima de IA | 1 800 tokens |
| Timeout IA / reputación | 30 / 5 segundos |
| Reintentos | 0; solo un rechazo HTTP 429 admite reintento si se configura |
| Reutilización de resultados | 60 minutos |
| Llamadas simultáneas / pendientes | 1 / 50, controladas en la base propia |
| Reserva de trabajo / consulta de cola | 180 / 2 segundos |
| `send_real_ip_to_ai` | `false`; la IP sigue visible para el analista |
| Tarifas por millón de tokens de entrada/salida | `null`; sin estimación de costo |

La validación rechaza límites excesivos y reservas demasiado cortas. Las tarifas
son opcionales y deben corresponder al modelo contratado. Tokens no informados
por el proveedor se guardan como `null`, no como consumo cero. El costo solo
se estima cuando hay ambos conteos y ambas tarifas; no es una factura.

## Arranque local

Desde la raíz del proyecto, con el entorno virtual y la autenticación existentes:

```powershell
.\run_web.ps1
```

En otro terminal:

```powershell
.\.venv\Scripts\python.exe src/investigate_alerts.py --loop --env-file .env
```

Para procesar, como máximo, un trabajo pendiente y salir:

```powershell
.\.venv\Scripts\python.exe src/investigate_alerts.py --once --env-file .env
```

Web y worker deben usar **el mismo backend/base propia**. Iniciar el worker no
crea investigaciones ni consulta automáticamente una IA: solo atiende solicitudes
ya guardadas. Reinicie el worker si cambia límites o variables.

## Docker y migración

No se consulta ni modifica la base institucional durante la migración. Primero
realice el respaldo de la base propia con el procedimiento existente. Con Docker
Desktop activo y las variables nuevas añadidas a `.env.docker`:

```powershell
docker compose --env-file .env.docker build
docker compose --env-file .env.docker run --rm init
docker compose --env-file .env.docker up -d web
docker compose --env-file .env.docker --profile investigation up -d investigation-worker
docker compose --env-file .env.docker logs --tail 20 investigation-worker
```

`init` añade el esquema al PostgreSQL **propio**, utilizando la inicialización
idempotente existente. No use `down -v`: borraría volúmenes. No es necesario
reiniciar ni reconfigurar Grafana.

Si activa la captura original en la ingesta live, recree ese worker para que
reciba las variables nuevas, únicamente cuando corresponda operar en la red UTPL:

```powershell
docker compose --env-file .env.docker --profile live up -d worker
```

En SQLite la migración aditiva se instala al abrir la base. PostgreSQL requiere
`init` explícito; la aplicación no ejecuta cambios de esquema con el usuario de
operación.

## API autenticada y ejemplo de solicitud

- `POST /api/v1/alerts/{alert_id}/investigations`: crea/reutiliza un análisis.
  Devuelve `202` si está pendiente/en proceso, o `200` si reutiliza uno completo.
- `GET /api/v1/alerts/{alert_id}/investigations/{analysis_id}`: estado y resultado.
- Cuerpo del POST: `{"force_new":false}`. `true` permite otro análisis después de
  finalizar, pero **no** duplica uno ya pendiente o en proceso.
- Solo operadores activos con rol `analyst` o `administrator`. Se usa la sesión
  existente y el POST exige CSRF. Las solicitudes y consultas quedan auditadas.
- Límites de solicitudes en `config/auth.json`: 5 envíos/minuto y 30
  consultas/minuto por operador. La cola llena devuelve `429`.
- Falta de sesión: `401`; permisos/CSRF: `403`; alerta/análisis inexistente:
  `404`; configuración faltante: `503`. Las respuestas no son cacheables.

Con la sesión abierta en la bandeja SOC, puede ejecutar en la consola del
navegador este ejemplo, sustituyendo el ID por **una alerta realmente existente**:

```javascript
const operador = await fetch("/auth/me").then(r => r.json());
const solicitud = await fetch("/api/v1/alerts/ID_REAL_DE_ALERTA/investigations", {
  method: "POST",
  headers: {"Content-Type": "application/json", "X-CSRF-Token": operador.csrf_token},
  body: JSON.stringify({force_new: false})
});
const trabajo = await solicitud.json();
console.log(trabajo);
// Una vez procesado por el worker, consulte la URL entregada en Location:
const resultado = await fetch(solicitud.headers.get("Location")).then(r => r.json());
console.log(resultado);
```

No publique capturas/salidas con IP reales. Evite consultar más rápido que cada
dos segundos y deténgase cuando el estado sea `completed` o `failed`.
El estado del análisis es independiente del estado del caso SOC.

### Ejemplo de respuesta: datos completamente simulados

Respuesta inicial abreviada (ningún dato corresponde a una consulta institucional):

```json
{
  "analysis_id": "a1b2c3",
  "alert_id": "alt_simulada",
  "status": "pending",
  "real_ip": null,
  "real_ip_unavailable_reason": "La investigación aún no tiene un resultado disponible",
  "result": null,
  "error_code": null,
  "reused": false
}
```

Fragmento de un resultado completado **simulado**, para ilustrar IP, evidencia
y explicación. La respuesta completa también contiene actor y fechas del trabajo:

```json
{
  "status": "completed",
  "real_ip": "10.5.6.7",
  "real_ip_unavailable_reason": null,
  "result": {
    "alert_id": "alt_simulada",
    "analysis_id": "a1b2c3",
    "real_ip": "10.5.6.7",
    "real_ip_unavailable_reason": null,
    "real_ips": ["10.5.6.7"],
    "context": {
      "user_counts": {"records": 4, "events": 7, "failures": 6, "successes": 1, "lockouts": 0, "distinct_users": 1},
      "events": [
        {"source_event_id": "postgresql_live:4", "event_time_utc": "2026-03-16T15:03:00+00:00", "event_class": "success", "event_count": 1, "user_key": "usr_simulado", "client_ip_key": "ip_simulada", "service_key": "app_simulada"}
      ],
      "success_after_failure_event_ids": ["postgresql_live:4"]
    },
    "reputation": [
      {"status": "not_applicable", "ip_address": "10.5.6.7", "provider": null, "checked_at_utc": null, "abuse_confidence_score": null, "total_reports": null, "reason": "IP no pública; análisis interno"}
    ],
    "explanation": {
      "summary": "Hubo varios fallos y después un acceso exitoso; esto requiere revisión.",
      "evidence": [{"statement": "Se registró un éxito posterior a los fallos.", "references": ["postgresql_live:4"]}],
      "interpretation": "El patrón es sospechoso, pero no confirma un ataque.",
      "legitimate_explanations": ["Una contraseña guardada pudo estar desactualizada."],
      "missing_information": ["Falta confirmar la actividad con el responsable de la cuenta."],
      "recommendations": ["Revisar los eventos relacionados y solicitar validación al responsable autorizado."]
    },
    "usage": {"input_tokens": 120, "output_tokens": 70, "provider": "openai", "model": "synthetic-model", "estimated_cost_usd": null},
    "confirmed_incident": false,
    "disclaimer": "Interpretación asistida; requiere validación del analista y no confirma un ataque."
  }
}
```

Una alerta con varias IP devuelve `real_ip:null`, explica el motivo y lista las
originales disponibles en `result.real_ips`. Si solo queda un HMAC, devuelve
`null` y el motivo: **no se revierte ni se inventa una IP**.

## Persistencia, reinicios y privacidad

Estados: `pending → in_progress → completed / failed`.
Los pendientes sobreviven a un reinicio. Un trabajo en curso tiene una reserva
temporal; si caduca, el siguiente ciclo lo marca `failed`, con
`worker_interrupted`. No se reenvía a la IA automáticamente: el proveedor pudo
cobrar antes de que se perdiera la respuesta. El analista decide si fuerza otra
ejecución. No se añaden Redis, Celery, dependencias de IA ni procesos dentro del
servidor web.

La captura original usa exclusivamente `custom_ip_address`, comprueba su relación
con el HMAC normalizado y guarda una copia cifrada relacionada con el evento.
No sustituye `client_ip_key` ni cambia las reglas. El CSV original no se modifica;
el modo demo histórico que ya opera sobre CSV normalizado no recupera las IP
originales automáticamente. La investigación no consulta por su cuenta la tabla
institucional para recuperar IP antiguas.

IP y resultado se cifran con Fernet en las tablas de investigación. El rol de
analítica de Grafana no recibe permisos sobre ellas; las vistas existentes no
añaden IP originales. La retención de eventos elimina sus copias asociadas; si
se elimina una alerta, desaparecen sus investigaciones. Restrinja también el
acceso a respaldos y a la clave.

El contexto de IA excluye mensajes originales, credenciales, nombres reales y
URL completas de servicios. Sus referencias se validan contra la evidencia
enviada; una referencia inventada hace fallar el análisis. No hay herramientas
ejecutables, SQL generado, MCP, redirecciones HTTP ni envío de reportes de IP.
El contenido externo se trata como datos, nunca como instrucciones. Esto reduce
riesgos, pero no garantiza que todas las interpretaciones sean correctas.

Por defecto no se envían IP originales a OpenAI; los pseudónimos y patrones
también pueden ser sensibles. Revise la autorización institucional para usar
proveedores externos. `store:false` evita persistir la respuesta en Responses,
pero **no equivale a garantizar retención cero** por el proveedor.
La reputación describe la IP al consultar, no demuestra su reputación histórica
ni confirma un ataque. IP privadas/reservadas permanecen en análisis interno.

## Verificación y fuentes

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m ruff format --check src tests
.\.venv\Scripts\python.exe -m pytest -q
```

Las pruebas de esta función usan eventos y clientes simulados: no consultan
OpenAI, AbuseIPDB ni la fuente UTPL y no generan gastos. El contrato PostgreSQL
requiere una instancia **local desechable** configurada con
`SOC_TEST_STORAGE_DSN`; de lo contrario esas pruebas se omiten.
Una prueba simulada no valida credenciales, conectividad ni disponibilidad real
del modelo. Complete las variables y solicite un análisis controlado para esa
validación posterior.

Implementación basada en la documentación oficial de
[Structured Outputs de OpenAI](https://developers.openai.com/api/docs/guides/structured-outputs)
y [consulta de IP de AbuseIPDB](https://docs.abuseipdb.com/#check-endpoint).
