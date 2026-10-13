# Mapa de entregables para presentar al ingeniero

El SOC transforma eventos de autenticación en casos explicables para revisión
humana. Una alerta es una señal que necesita investigación, no un ataque confirmado.

## Dónde se cumple cada entregable

| Entregable | Implementación principal | Cómo demostrarlo |
| --- | --- | --- |
| Ingesta y normalización | `src/practicum_soc/soc/ingestion.py`, `soc/normalization.py`, `services/monitoring.py` | Ejecutar una iteración autorizada; mostrar fuente, procesados y rechazos sin datos reales. |
| Línea base | `src/practicum_soc/soc/baseline.py`, `config/baseline.json` | Explicar separación de entrenamiento/evaluación y perfiles en `docs/baseline.md`. |
| Reglas y riesgo | `src/practicum_soc/soc/detection.py`, `config/detection_rules.json`, `repositories/rules.py` | Abrir evidencia del caso y mostrar condición, puntaje y versión aplicada. |
| Alertas tempranas | `src/practicum_soc/repositories/`, `integrations/notifications.py` | Abrir la bandeja, investigar un caso y registrar estado/nota con su autor. |
| Reporte histórico | `src/practicum_soc/analytics/reporting.py`, `analytics/historical_report.py`, `services/history.py` | Mostrar periodo, resultados y limitaciones del informe. |
| Analítica de servicios | `src/practicum_soc/analytics/`, `deploy/grafana/` | Comparar oscilaciones y casos abiertos de varios servicios sin afirmar que volumen significa ataque. |
| Documentación y operación | `README.md`, `docs/README.md`, `docs/engineer_handoff.md`, scripts | Levantar un entorno nuevo con secretos propios y ejecutar las pruebas. |

En la tabla, las rutas abreviadas después de una primera ruta completa parten
también de `src/practicum_soc/`. El [mapa de archivos](project_guide.md) amplía las
responsabilidades y [la arquitectura del backend](backend_refactor.md) explica
el diseño y las mediciones.

## Cinco reglas configurables

1. Múltiples fallos contra un usuario: posible fuerza bruta.
2. Una IP intentando acceder a varias cuentas: posible password spraying.
3. Éxito después de múltiples fallos: correlación de una secuencia sospechosa.
4. Bloqueos múltiples de cuenta.
5. IP nueva con actividad repetida y línea base suficiente.

Ventana, umbral, cooldown, puntaje y bonos son parámetros. La configuración
inicial está en JSON; las publicaciones posteriores se conservan por versión
en la base SOC. Una comparación histórica no escribe alertas reales.

## Recorrido breve de la demostración

1. Acceder con un operador autorizado y explicar los roles administrador/analista.
2. Mostrar pendientes, prioridad y estado del monitor; distinguir histórico de live.
3. Abrir una alerta, revisar evidencia y cambiar estado con una nota de prueba autorizada.
4. Mostrar Servicios y Grafana para comparar tendencias y localizar sus casos.
5. Como administrador, abrir Reglas y puntajes y mostrar un borrador sin publicarlo.
6. Mostrar el reporte y las instrucciones de entrega/mantenimiento.

## Límites que deben decirse

- La fuente institucional solo se lee; los casos se guardan en PostgreSQL propio.
- Los eventos aislados no deben convertirse automáticamente en incidencias.
- Deduplicación y cooldown reducen repetición, pero no sustituyen el ajuste de umbrales.
- HMAC oculta identificadores; no permite recuperar una identidad sin una consulta institucional autorizada.
- Los horarios, CIDR, NAT, VPN, cuentas técnicas y sensibilidad de servicios necesitan validación institucional.
- La revisión automática no sustituye un piloto ni una prueba de carga de periodo lectivo.
- Docker facilita la instalación; producción todavía requiere dominio, HTTPS, configuración segura, respaldos y aprobación del entorno.
- IA y reputación son opcionales; no se habilitan al entregar el repositorio.

Las pruebas usan datos sintéticos o mocks. Las integraciones PostgreSQL se ejecutan
solo sobre una base de prueba separada, nunca sobre el origen institucional.
