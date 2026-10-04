# Análisis histórico desde PostgreSQL

El análisis histórico utiliza `src/historical_cli.py`. Consulta solamente la
fuente autorizada; no usa el CSV si falla la conexión. Se ejecuta en el mismo
PostgreSQL propio del SOC que alimenta la bandeja y Grafana.

## Ejecución controlada con Docker

Mantenga la red UTPL conectada durante la lectura. No ejecute dos análisis
históricos al mismo tiempo ni cambie las reglas durante la evaluación.

```powershell
docker compose --env-file .env.docker stop worker
docker compose --env-file .env.docker build worker
docker compose --env-file .env.docker run --rm --no-deps -T worker python src/historical_cli.py --from-date 2026-08-01 --to-date 2026-10-01 --output-dir analysis/reports/history_2026_08_09
```

El final es exclusivo: el ejemplo incluye todo agosto y septiembre de 2026 en
la zona horaria de Loja, pero no incluye octubre. Se agrupa por la fecha original
de autenticación (`event_time_origen`), utilizando `event_time` solo si aquella
es nula. No se cambian las fechas de los eventos.

La lectura usa una instantánea de solo lectura y un cursor de servidor; obtiene
las columnas necesarias para normalización sin copiar mensajes ni cuentas de
servidores. `config/historical_analysis.json` limita lote, duración de consultas
y rango. La normalización, HMAC, rechazos, reglas y línea base se reutilizan.

La ingesta mantiene memoria por lote. El detector actual necesita la secuencia
completa del intervalo en memoria; esto no es una garantía de escalabilidad
ilimitada. El máximo de 62 días evita intervalos no acotados; para históricos
mayores, revise recursos y cobertura antes de ejecutar.

## Qué guarda y verifica

- `normalized_events`: registros pseudonimizados, con `is_consistent=0` y
  `quality_flags` cuando son rechazados.
- `alerts`: casos, evidencia, puntaje y versión de reglas utilizada.
- `alert_status_history` y `notification_deliveries`: trazabilidad y entrega
  interna por `soc_inbox`; no se envía correo ni Teams.
- Métricas por minuto, hora y día: los triggers locales se ejecutan al insertar.
- `service_runs`: ejecución completada o fallida y sus contadores.
- `analysis/reports/history_2026_08_09/summary.json` y `report.md`: resumen
  de lo realmente almacenado por mes, cobertura, reglas y severidades.

El análisis no escribe el checkpoint live. Comprueba que continúa igual y
repite hasta 100 eventos ya guardados para verificar cero inserciones duplicadas.
Una reejecución reutiliza las claves deterministas y el cooldown persistente.
No cambia estados de casos existentes ni los elimina.

La línea base de marzo debe ser anterior a agosto y septiembre. No se reentrena
con el mismo conjunto evaluado. Su antigüedad es una limitación, especialmente
para la regla de IP nueva: requiere revisión institucional.

## Visualización

En la bandeja, abra Alertas y seleccione `postgresql_live` junto con las fechas:

- Agosto: `2026-08-01` a `2026-08-31`.
- Septiembre: `2026-09-01` a `2026-09-30`.

En Grafana seleccione `postgresql_live` y el intervalo absoluto del mes. El
tablero de oscilaciones admite como máximo 31 días: consulte cada mes por
separado. Los huecos no demuestran ausencia de uso ni disponibilidad del servicio.
Un caso automático tampoco confirma un ataque: necesita revisión humana.

Al concluir, si sigue conectado a la red autorizada, reanude el monitor:

```powershell
docker compose --env-file .env.docker --profile live up -d worker
docker compose --env-file .env.docker logs --tail 10 worker
```

Los reportes del ejemplo están en el volumen Docker `analysis`, no en la carpeta
del host. Puede copiarlos a una carpeta nueva local con `docker cp` desde el
contenedor web (`/app/analysis/reports/history_2026_08_09`); no copie credenciales
ni registros crudos al repositorio. `analysis/reports/` está ignorado por Git.
