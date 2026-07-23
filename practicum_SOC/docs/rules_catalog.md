# Catálogo de reglas del MVP

Umbrales, ventanas, cooldown y riesgo están centralizados en `config/detection_rules.json`. Toda alerta contiene ID, usuario/IP pseudonimizados, tipo, evidencia, conteo, periodo, severidad, puntaje y recomendación.

## Habilitadas

| ID | Condición inicial | Riesgo base | Revisión sugerida |
|---|---|---:|---|
| `AUTH_BRUTE_FORCE_USER` | 10 fallos del usuario en 10 min | 70 | Validar origen y actividad del responsable. |
| `AUTH_PASSWORD_SPRAY_IP` | 10 fallos contra 10 usuarios desde una IP en 10 min | 75 | Descartar NAT, proxy o infraestructura compartida. |
| `AUTH_SUCCESS_AFTER_FAILURES` | Éxito tras 5 fallos del usuario en 10 min | 85 | Priorizar origen y confirmar el acceso. |
| `AUTH_ACCOUNT_LOCKOUT` | Bloqueo explícito de cuenta | 65 | Revisar intentos previos y dispositivo desactualizado. |
| `AUTH_NEW_IP_FOR_USER` | IP ausente de la línea base de un usuario con 20 eventos o más | 50 | Validar red móvil, cambio de ISP o acceso legítimo. |

Severidad por puntaje: baja 0–39, media 40–64, alta 65–84 y crítica 85–100. El exceso de volumen y el contexto agregan puntos visibles en `risk_factors`.

## Desactivadas

| Regla | Motivo |
|---|---|
| Horario nocturno/fuera de horario | Cobertura horaria incompleta y semántica temporal pendiente. |
| Hora inusual por usuario | Comparte la limitación temporal anterior. |
| Red no autorizada | Faltan CIDR, NAT, proxy y VPN oficiales. |
| Aplicación nueva, pico global, cambio de patrón y bloqueo repetido | Fuera del alcance demostrable acordado para este MVP. |

El detector no ejecuta estas reglas. En particular, no se generan alertas por actividad posterior a las 21:00, aunque esa hipótesis pueda retomarse cuando la Dirección valide el dato.

## Control de ruido

- alertas deterministas y deduplicadas;
- cooldown en memoria y persistente en SQLite;
- límite de entrega por ciclo;
- IP nueva solo con historial suficiente;
- evidencia y recomendación para revisión humana;
- registro de falsos positivos y supresiones.
