# Línea base de autenticaciones ADFS

## Propósito

La línea base describe el comportamiento observado antes de crear reglas de
alerta. No declara incidentes: proporciona distribuciones y referencias para
seleccionar umbrales y reducir falsos positivos.

## Fuente y tiempo

- Entrada: `analysis/normalized_events.csv`.
- Zona horaria de análisis: `America/Guayaquil`.
- Filas recibidas: 100.000.
- Eventos válidos normalizados: 99.214.
- Registros rechazados con motivo: 786.

El CSV presenta cobertura consistente durante 12 horas locales. Los días se
incluyen en la línea base cuando tienen al menos 1.000 eventos y actividad en
12 horas distintas. Con este criterio se seleccionaron siete días, del 14 al
20 de marzo de 2026, con 92.332 eventos.

Las horas no observadas no equivalen a cero actividad. Por ello no deben
activarse todavía reglas de horario inusual fuera de la ventana cubierta.

## Resultados principales

- Éxitos: 68.445.
- Fallos de credenciales: 12.476.
- Bloqueos: 11.411.
- Tasa de fallos sobre intentos de autenticación: 15,42 %.
- Usuarios pseudonimizados distintos: 20.838.
- IP de cliente pseudonimizadas distintas: 19.833.
- Usuarios con historial suficiente (20 eventos o más): 510.
- Usuarios con historial insuficiente: 20.328.

Distribuciones agregadas del período:

| Métrica | P50 | P95 | P99 | Máximo |
|---|---:|---:|---:|---:|
| Fallos por usuario | 0 | 2 | 10 | 79 |
| Fallos por IP | 0 | 2 | 7 | 622 |
| Usuarios distintos por IP | 1 | 4 | 11 | 616 |

Los máximos son candidatos para investigación, no confirmaciones de ataque.
Una IP con muchos usuarios podría corresponder a password spraying, pero
también a NAT, VPN, proxy institucional o un servicio compartido.

## Archivos generados

- `daily_activity.csv`: cobertura y totales por fecha.
- `hourly_activity.csv`: volumen y tasas por hora local.
- `user_behavior.csv`: actividad agregada por usuario.
- `ip_behavior.csv`: actividad agregada por IP.
- `relying_party_behavior.csv`: actividad por aplicación.
- `user_hour_profile.csv`: distribución horaria por usuario.
- `user_ip_profile.csv`: IP frecuentes por usuario.
- `user_app_profile.csv`: aplicaciones frecuentes por usuario.
- `baseline_summary.json`: resumen técnico y percentiles.

## Limitaciones que afectan las reglas

1. Solo hay siete días con cobertura consistente.
2. Solo se observan 12 horas locales por día.
3. El CSV no contiene el perfil institucional del usuario, como estudiante,
   docente, administrativo o cuenta privilegiada.
4. Las IP están pseudonimizadas; la geolocalización o reputación debe
   enriquecerse dentro del entorno controlado antes de ocultar el valor.
5. Los umbrales agregados no sustituyen reglas por ventanas de minutos.

## Uso temporal correcto

El periodo 14–20 de marzo de 2026 se considera entrenamiento. Las reglas que
comparan IP, aplicación, hora o tasa de fallos con la línea base solo evalúan
eventos posteriores al 20 de marzo. Esto evita utilizar comportamiento futuro
para evaluar eventos pasados. La actualización propuesta es mensual y requiere
una revisión previa de cobertura y calidad.
