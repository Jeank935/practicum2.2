# Ruta para defender el MVP SOC ADFS

Esta guía indica qué archivos abrir y qué bloques explicar durante la defensa.
No es necesario recorrer el código línea por línea. La idea central es demostrar
que existe un flujo trazable desde el CSV hasta una alerta revisable.

## Mensaje central

El proyecto es un motor de apoyo para un analista SOC. Ingiere autenticaciones
ADFS, controla su calidad, pseudonimiza identidades, aprende una referencia
histórica, detecta señales explicables y conserva las alertas para investigación.
No confirma ataques, no bloquea cuentas y no modifica ADFS ni PostgreSQL.

## Recorrido recomendado

```text
run_demo.ps1
├── run_analysis.ps1
│   ├── profile_csv.py              -> calidad del CSV
│   ├── normalize_events.py         -> válidos, rechazados, HMAC y deduplicación
│   ├── build_baseline.py           -> entrenamiento y perfiles habituales
│   ├── detect_alerts.py            -> cinco reglas explicables
│   └── generate_report.py          -> informe histórico reproducible
├── demo_cli.py / demo_service.py
│   ├── alert_store.py              -> SQLite, cooldown, estados y checkpoint
│   └── notifications.py            -> canal demostrativo soc_inbox
└── web_app.py
    └── templates/ + static/        -> bandeja SOC local
```

Para una exposición de 10 a 15 minutos, seguir este orden:

1. Abrir `run_analysis.ps1` y mostrar que coordina todo el análisis.
2. Enseñar las estadísticas de normalización.
3. Explicar la separación entre entrenamiento y evaluación.
4. Abrir la configuración de reglas y explicar sus umbrales.
5. Mostrar una alerta completa en la bandeja SOC.
6. Cambiar su estado y explicar la persistencia SQLite.
7. Abrir el reporte histórico.
8. Finalizar con las pruebas y las limitaciones pendientes.

## 1. Ingesta y normalización

### Archivos principales

| Archivo o bloque | Qué demuestra |
|---|---|
| `run_analysis.ps1` | Orden completo del procesamiento histórico y control de errores entre pasos. |
| `src/event_source.py` — `EventSource`, `CsvEventSource` y `PostgresEventSource` | Contrato común para fuentes, lectura incremental, checkpoint y sesión PostgreSQL de solo lectura. |
| `src/monitor_service.py` — ciclo `once`/`loop` | Ejecución periódica usando el intervalo de configuración. |
| `src/normalize_events.py` — `normalize_record` | Selecciona el usuario real del evento desde `custom_user_id` y la IP cliente desde `custom_ip_address`. |
| `src/normalize_events.py` — `pseudonymize` | Aplica HMAC para no exponer usuarios ni IP reales. |
| `src/normalize_events.py` — `_deduplication_key` | Usa el identificador disponible o una huella determinista para evitar duplicados. |
| `src/normalize_events.py` — `rejection_reasons` y `normalize_csv` | Separa registros válidos y rechazados, conserva el motivo y genera estadísticas. |
| `config/normalization.json` | Reglas de rechazo modificables sin cambiar el código. |
| `docs/data_dictionary.md` | Interpretación documentada de las columnas del CSV. |

### Evidencia para mostrar

- `analysis/normalization_stats.json`: 100.000 entradas, 99.214 válidas y
  786 rechazadas.
- `analysis/rejected_events.csv`: registros rechazados con el motivo, sin
  revelar el usuario o la IP originales.
- `analysis/normalized_events.csv`: conjunto común y pseudonimizado usado por
  las siguientes etapas.
- `tests/test_normalize_events.py`: rechazos, formatos de usuario,
  deduplicación y sanitización.
- `tests/test_event_source.py`: checkpoint combinado y PostgreSQL `READ ONLY`
  mediante mocks.

### Qué decir

> La normalización no elimina silenciosamente registros inconsistentes. Los
> separa, registra el motivo y permite auditar cuántos fueron aceptados o
> rechazados. El CSV oficial se abre en lectura y no se modifica.

## 2. Línea base de comportamiento

### Archivos principales

| Archivo o bloque | Qué demuestra |
|---|---|
| `config/baseline.json` | Fechas de entrenamiento/evaluación y mínimo de historial por usuario. |
| `src/build_baseline.py` — `_scan_daily` y `_select_period_days` | Revisa cobertura y selecciona días aptos para entrenar. |
| `src/build_baseline.py` — `_aggregate_training` | Agrega únicamente eventos del periodo de entrenamiento. |
| `src/build_baseline.py` — `_profile_rows` | Construye perfiles por usuario, IP, hora y aplicación. |
| `src/build_baseline.py` — `_build_summary` | Registra periodo, volumen, distribuciones y datos insuficientes. |
| `docs/baseline.md` | Explicación funcional, resultados y limitaciones. |

### Evidencia para mostrar

- `analysis/baseline/baseline_summary.json`: entrenamiento del 14 al 20 de
  marzo de 2026 con 92.332 eventos; los eventos futuros están excluidos.
- `analysis/baseline/hourly_activity.csv`: volumen por hora local.
- `analysis/baseline/user_hour_profile.csv`: comportamiento horario por usuario.
- `analysis/baseline/user_ip_profile.csv`: IP frecuentes por usuario.
- `analysis/baseline/user_behavior.csv` e `ip_behavior.csv`: éxitos, fallos y
  bloqueos por entidad.
- `tests/test_build_baseline.py` y `tests/test_detect_alerts.py`: cobertura
  temporal y uso de la línea base sin evaluar el periodo de entrenamiento.

### Limitación que debe declararse

El CSV no incluye una ubicación geográfica confiable. El proyecto caracteriza
IP y origen lógico, pero no inventa país o ciudad. La geolocalización deberá
enriquecerse dentro del entorno controlado antes de pseudonimizar la IP.

### Qué decir

> La línea base es descriptiva, no un modelo que declare ataques. Sirve para
> comparar un evento nuevo con el comportamiento observado anteriormente y
> evita fuga temporal separando formalmente entrenamiento y evaluación.

## 3. Catálogo de reglas

La configuración que debe abrirse durante la defensa es
`config/detection_rules.json`. La explicación funcional está en
`docs/rules_catalog.md` y la implementación vive en `src/detect_alerts.py`.

| Regla | Bloque de código | Umbral provisional |
|---|---|---|
| `AUTH_BRUTE_FORCE_USER` | `detect_brute_force` | 10 fallos del usuario en 10 minutos. |
| `AUTH_PASSWORD_SPRAY_IP` | `detect_password_spray` | 10 fallos contra 10 usuarios desde una IP en 10 minutos. |
| `AUTH_SUCCESS_AFTER_FAILURES` | `detect_success_after_failures` | Un éxito después de 5 fallos en 10 minutos. |
| `AUTH_ACCOUNT_LOCKOUT` | `detect_account_lockout` | Evento explícito de bloqueo. |
| `AUTH_NEW_IP_FOR_USER` | `detect_new_ip` | IP no observada y usuario con al menos 20 eventos históricos. |

Bloques comunes que conviene mencionar:

- `calculate_risk`: suma factores explicables y limita el puntaje a 100.
- `severity_for_score`: transforma el puntaje en baja, media, alta o crítica.
- `make_alert`: garantiza el formato común y la evidencia mínima.
- `evaluation_events`: excluye el periodo utilizado para entrenamiento.
- `cooldown_ready`: evita repetir señales iguales dentro de la ventana.

### Reglas desactivadas

| Regla | Motivo defendible |
|---|---|
| Horario nocturno o inusual | Solo se observan 12 horas locales; una hora ausente no demuestra que no exista actividad legítima. |
| Red no autorizada | Faltan CIDR, NAT, proxy y VPN oficiales de la UTPL. |
| Ubicación no reconocida | No hay fuente geográfica confiable en el CSV. |

Los umbrales son provisionales. El reto indica que los definitivos deben
acordarse con la Dirección, por lo que centralizarlos en configuración es parte
de la solución.

### Evidencia para mostrar

- `analysis/alerts/alert_summary.json`: 43 alertas sobre el periodo de
  evaluación; 29 altas y 14 medias.
- `analysis/alerts/alerts.csv`: detalle explicable de cada alerta.
- `tests/test_detect_alerts.py`: activación de las cinco reglas y confirmación
  de que las reglas desactivadas no generan alertas.

## 4. Alertamiento temprano, persistencia y bandeja SOC

### Archivos principales

| Archivo o bloque | Qué demuestra |
|---|---|
| `src/sqlite_schema.py` | Tablas de alertas, eventos, checkpoint, historial, entregas y supresiones. |
| `src/alert_store.py` — `insert_alert` | Persistencia y deduplicación de alertas. |
| `src/alert_store.py` — `_cooldown_active` | Cooldown que sobrevive entre ejecuciones. |
| `src/alert_store.py` — `update_alert_status` | Estados e historial de investigación. |
| `src/alert_store.py` — `record_delivery` | Resultado y fecha de cada intento de entrega. |
| `src/notifications.py` — `NotificationProvider` | Interfaz para cambiar de canal sin modificar el detector. |
| `src/notifications.py` — `SocInboxProvider` y `deliver_once` | Entrega interna e idempotente de alertas altas/críticas. |
| `src/demo_service.py` | Une alertas históricas, SQLite y notificación. |
| `src/web_app.py` | Endpoints del panel; las rutas delegan la lógica a servicios. |
| `src/dashboard_service.py` | Consultas para resumen, detalle, salud y cambio de estado. |
| `templates/` y `static/` | Presentación local de la bandeja SOC. |

### Información contenida en una alerta

- identificador determinista;
- usuario e IP pseudonimizados;
- regla y tipo de evento;
- primera y última marca de tiempo;
- cantidad de eventos y entidades;
- evidencia de eventos;
- severidad y puntaje explicable;
- recomendación inicial;
- estado de investigación y resultado de entrega.

### Evidencia para mostrar

- `analysis/state/soc_alerts.db`: 43 alertas vigentes del demo, historial de
  estados, cooldown y checkpoint.
- Abrir `http://127.0.0.1:8000`, entrar al detalle de una alerta y cambiarla a
  `investigating`, `resolved` o `false_positive`.
- `tests/test_alert_store.py`: persistencia, deduplicación, checkpoint,
  historial y cooldown.
- `tests/test_notifications.py`: entrega única mediante `soc_inbox`.
- `tests/test_web_app.py`: endpoints y cambio de estado.
- `tests/test_demo_service.py`: reproducibilidad entre ejecuciones.

### Qué decir

> `soc_inbox` es el canal de demostración. Permite probar el ciclo completo sin
> enviar información real a terceros. El canal definitivo debe acordarse con la
> Dirección; la interfaz `NotificationProvider` permite incorporarlo después.

## 5. Reporte histórico

### Archivos principales

| Archivo o bloque | Qué demuestra |
|---|---|
| `src/generate_report.py` — `generate_report` | Une normalización, línea base, alertas, estados y configuración en un informe reproducible. |
| `src/generate_report.py` — `_state_counts` | Incorpora falsos positivos registrados en SQLite. |
| `src/generate_report.py` — `_configured_rules` | Separa reglas activas y desactivadas con su motivo. |
| `tests/test_generate_report.py` | Verifica que el reporte contenga los conteos y apartados obligatorios. |

### Evidencia para mostrar

Abrir `analysis/report/historical_report.md`. Contiene:

- periodo analizado;
- eventos procesados, válidos y rechazados;
- éxitos, fallos y bloqueos;
- alertas por regla y severidad;
- principales usuarios e IP pseudonimizados;
- falsos positivos registrados;
- reglas desactivadas y motivo;
- limitaciones del dataset.

## 6. Documentación técnica y de uso

| Documento | Uso durante la defensa |
|---|---|
| `README.md` | Instalación, ejecución, modos demo/live, API y pruebas. |
| `docs/architecture.md` | Flujo completo y separación de responsabilidades. |
| `docs/data_dictionary.md` | Significado de columnas y selección correcta de usuario/IP. |
| `docs/baseline.md` | Construcción y límites de la línea base. |
| `docs/rules_catalog.md` | Reglas, umbrales, riesgo y control de ruido. |
| `docs/alerts.md` | Estados, origen y política de alertas. |
| `docs/operations.md` | Operación, mantenimiento y diagnóstico. |
| `docs/security.md` | Privacidad, secretos y conexión de solo lectura. |

## 7. Mapa de criterios de aceptación

| Criterio | Archivos para defenderlo | Prueba o salida |
|---|---|---|
| Ingesta correcta y registros inconsistentes señalados | `event_source.py`, `normalize_events.py`, `normalization.json` | `normalization_stats.json`, `rejected_events.csv`, `test_normalize_events.py` |
| Reglas activadas sobre casos de prueba | `detect_alerts.py`, `detection_rules.json` | `test_detect_alerts.py`, `alert_summary.json` |
| Control de falsos positivos | Línea base, historial mínimo, deduplicación, cooldown y estados | `test_alert_store.py` y clasificación `false_positive` en SQLite |
| Información mínima de las alertas | `make_alert`, `AlertStore`, plantilla de detalle | `alerts.csv` y bandeja SOC |
| Entrega por un canal | `NotificationProvider`, `SocInboxProvider` | `notification_deliveries` y `test_notifications.py` |
| Ejecución y mantenimiento por otra persona | `README.md`, scripts y documentos de `docs/` | Ejecución de `run_demo.ps1` y 19 pruebas automáticas |

## 8. Demostración práctica sugerida

Antes de exponer:

```powershell
.\run_demo.ps1
```

Durante la demostración:

1. Abrir el resumen de eventos.
2. Explicar la separación de entrenamiento y evaluación.
3. Mostrar las alertas por severidad.
4. Abrir una alerta de bloqueo o IP nueva.
5. Señalar usuario, IP, tiempo, evidencia, riesgo y recomendación.
6. Cambiar su estado a `investigating`.
7. Volver a cargar la página para demostrar persistencia.
8. Abrir el reporte histórico.
9. Ejecutar, si se solicita:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

El resultado esperado actual es `19 passed`.

## 9. Respuestas breves para preguntas frecuentes

**¿El sistema detecta hackers?**  
No directamente. Detecta patrones de riesgo que un analista debe investigar.

**¿Por qué se usa HMAC y no se ocultan caracteres al azar?**  
HMAC protege el dato real y conserva un pseudónimo estable, necesario para
relacionar eventos del mismo usuario o IP.

**¿Por qué se separan entrenamiento y evaluación?**  
Para no usar información futura al decidir qué era normal en el pasado.

**¿Por qué SQLite?**  
Es suficiente para un MVP local, conserva alertas entre ejecuciones y no
requiere infraestructura adicional.

**¿Por qué no está activa la regla después de las 21:00?**  
Porque el dataset no tiene cobertura suficiente para demostrar que esas horas
son anómalas. Activarla ahora produciría conclusiones sin respaldo.

**¿Cero falsos positivos significa que todas las alertas son ataques?**  
No. Significa que todavía no se han clasificado alertas como falso positivo.
La tasa real requiere revisión de la DGTITD.

**¿PostgreSQL ya está listo?**  
El adaptador, modo de solo lectura, consulta incremental, checkpoint y fallback
están implementados y probados con mocks. Falta validarlos con la vista
institucional dentro de la red autorizada.

## 10. Continuación con PostgreSQL

Para la próxima sesión se necesitará confirmar:

- acceso desde una red o VPN autorizada;
- servidor, puerto y base de datos;
- usuario con permiso exclusivamente `SELECT`;
- nombre exacto de la vista ADFS;
- columnas de tiempo e identificador incremental;
- requisitos de SSL;
- correspondencia de las columnas de la vista con el esquema esperado.

Las credenciales deben escribirse localmente en `.env`, que ya está ignorado
por Git. No deben pegarse en documentación, capturas, logs ni mensajes. La
secuencia de validación será:

1. copiar `.env.example` a `.env`;
2. completar el secreto localmente;
3. comprobar conectividad sin imprimir el DSN;
4. ejecutar `run_monitor.ps1 -Source postgres -Mode once`;
5. verificar lectura incremental y checkpoint;
6. repetir el ciclo y comprobar que no duplica eventos;
7. probar el fallback controlado;
8. solo después habilitar `-Mode loop`.

