# Funcionamiento del SOC ADFS

## Objetivo y flujo

El SOC convierte registros de autenticación en casos que un analista puede revisar.
Lee el PostgreSQL institucional sin modificarlo; también permite probar con CSV.

```text
ADFS → PostgreSQL institucional → Ingesta → Normalización
    → Línea base y reglas → Base SOC → Bandeja y Grafana
```

La normalización valida fechas y campos, señala inconsistencias y evita duplicados.
Usuarios e IP se pseudonimizan con HMAC SHA-256: permiten relacionar eventos sin
mostrar sus valores reales. No equivale a anonimización completa.
La línea base describe la actividad habitual y se construye con datos separados
de la evaluación. Los eventos se conservan para el análisis histórico.

## Detección y puntajes iniciales

| Regla | Condición | Puntaje base |
| --- | --- | ---: |
| Múltiples fallos por usuario | 6 fallos en 10 minutos | 65 |
| Password spraying por IP | 6 fallos sobre al menos 3 cuentas en 10 minutos | 65 |
| Éxito después de fallos | Éxito tras 5 fallos en 10 minutos | 75 |
| Bloqueos múltiples | 2 bloqueos de una cuenta en 10 minutos | 85 |
| IP nueva para el usuario | 3 eventos en 10 minutos, con historial suficiente | 40 |

Severidad inicial: baja 0–39, media 40–64, alta 65–84 y crítica 85–100.
El volumen y el contexto pueden añadir puntos. Estos parámetros son configurables;
no deben interpretarse como umbrales aprobados definitivamente por la UTPL.

Un evento aislado queda en el histórico, pero no abre automáticamente un caso.
La deduplicación y la pausa entre casos reducen repeticiones. Las exclusiones
autorizadas elevan umbrales, pero no silencian actividad excepcional.
Las reglas de horario y red externa requieren información institucional validada.

En **Reglas y puntajes**, el administrador crea un borrador, compara con histórico
y publica con justificación; puede restaurar una versión anterior.
El borrador no afecta al monitor. La versión publicada vive en la base SOC,
no en un JSON nuevo, y las alertas nuevas registran qué versión utilizaron.

## Atención y visualización

El analista revisa evidencia, marca el caso en investigación y lo cierra como
resuelto o falso positivo. Una alerta no confirma un ataque ni bloquea una cuenta.
El administrador también gestiona usuarios y reglas; el analista no.

Grafana muestra tres vistas: actividad por minuto, oscilaciones de todos los
servicios y detalle de un servicio. Prioriza casos abiertos y permite ir a su
evidencia. Las pantallas usan filtros y paginación; la bandeja recibe cambios por
SSE con consulta periódica de respaldo.

## Mapa breve del código

Rutas relativas a la raíz:

| Ruta | Responsabilidad |
| --- | --- |
| `src/practicum_soc/soc/` | Ingesta, normalización, línea base y detección. |
| `src/practicum_soc/soc/detection.py` | Aplica reglas, calcula puntajes y asigna severidad. |
| `src/practicum_soc/services/` | Coordina monitor, consultas, histórico y edición de reglas. |
| `src/practicum_soc/repositories/` | Guarda casos, eventos, sesiones, versiones y checkpoints. |
| `src/practicum_soc/api/`, `main.py` | API y aplicación FastAPI. |
| `src/practicum_soc/analytics/`, `integrations/` | Agregados, identidad y notificaciones. |
| `config/` | Parámetros iniciales, exclusiones y límites de ejecución. |
| `templates/`, `static/` | Interfaz Jinja2, CSS y JavaScript. |
| `deploy/`, `Dockerfile`, `compose.yaml` | Keycloak, Grafana y despliegue Docker. |
| `tools/`, `tests/` | Preparación, respaldo y pruebas. |
| `src/*.py`, `run_*.ps1` | Entradas compatibles con Docker y PowerShell; no son código vacío. |

La investigación asistida es opcional y está deshabilitada por defecto. No hace
falta para detectar alertas. No habilite proveedores externos sin autorización.

## Alcance del reto

Se implementaron ingesta, normalización, línea base, reglas documentadas, alertas,
reporte histórico y operación reproducible. La aceptación institucional todavía
requiere validar umbrales, perfiles, horarios, rangos de red, servicios sensibles
y el canal definitivo de entrega. `soc_inbox` es la bandeja interna, no correo ni Teams.
